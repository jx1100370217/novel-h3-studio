import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import write, read, file_hash
from novel_h3.voices import bindings
from novel_h3.director import h3_prompt
from novel_h3.comfy import graph, fingerprint, _speaker_review_correction, _retake_shot_contract
from novel_h3.arcreel import check_speaker_audit
from novel_h3.speech_qc import compare
from novel_h3.character_views import select_view
from novel_h3.shot_package import compile_package

REPO = Path(__file__).resolve().parents[1]


class VoiceBindingTests(unittest.TestCase):
    def test_transcription_rejects_wrong_reference_text_and_truncated_short_lines(self):
        self.assertTrue(compare('这是哪里？','这是哪里')['passed'])
        self.assertFalse(compare('这是哪里？','哪里')['passed'])
        self.assertFalse(compare('你将他送回去了？','只是胸口有些疼，歇一歇便好。')['passed'])
        self.assertFalse(compare('我也将永远破灭成光，不再轮回。','我也将永远破灭成光，再轮回。')['passed'])
        self.assertTrue(compare('你将他送回去了？','你将它送回去了')['passed'])
        self.assertFalse(compare('','有人吗')['passed'])
        self.assertTrue(compare('','')['passed'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        wave = self.root / 'voice.wav'
        wave.write_bytes(b'test-audio-fixture')
        self.bank = {'无极': dict(asset_id='wuji', path='voice.wav', sha256=file_hash(wave), approved=True),
                     '旁白': dict(asset_id=None, path='voice.wav', sha256=file_hash(wave), approved=True)}
        write(self.root/'bible/voices.json', self.bank)
        self.shot = copy.deepcopy(read(REPO/'projects/rendao-wuji/episodes/chapter_s0003.json')['shots'][0])
        self.shot['references'] = [dict(asset_id='outer_heaven',description='empty environment',lock='environment'),
                                   dict(asset_id='wuji',description='young man',lock='face')]
        self.shot['dialogue'] = [dict(speaker='无极',kind='dialogue',text='这是哪里？',start_frame=6,end_frame=118)]

    def test_subject_follows_asset_not_picture_or_speaker_position(self):
        b = bindings(self.root, self.shot)
        self.assertEqual((b[0]['picture'], b[0]['audio']), (2, 1))
        prompt = h3_prompt(dict(self.shot,speech_bindings=b),'cinema')
        self.assertIn('<Audio 1> is the voice-timbre reference for <Subject 2> (S1)',prompt)
        self.assertIn('<Subject 2> (S1) says <d>[Chinese] 这是哪里？</d>',prompt)
        self.shot['references'][1]['description']='角色资产 无极'
        prompt=h3_prompt(dict(self.shot,speech_bindings=b),'cinema')
        self.assertNotIn('无极',prompt)

    def test_dialogue_prompt_excludes_chinese_identity_metadata(self):
        shot = copy.deepcopy(self.shot)
        shot['asset_package'] = {
            'identity_bindings': [
                {'asset_id': 'wuji', 'name': '无极', 'subject_label': 'Subject 2',
                 'picture_label': 'Picture 2', 'role': 'listener',
                 'selected_character_view_label': '背面',
                 'design_description': '男性角色设计说明'},
            ],
            'visual_assets': [],
        }
        prompt = h3_prompt(shot, 'cinema')
        self.assertEqual(prompt.count('无极'), 1)  # exact <d> line only
        self.assertNotIn('背面', prompt)
        self.assertNotIn('男性角色设计说明', prompt)

    def test_c3p01_03_closes_incomplete_voiceover_clause(self):
        shot = copy.deepcopy(read(REPO/'projects/rendao-wuji/episodes/chapter_s0003.json')['shots'][2])
        shot['id'] = 'C3P01_03'
        shot['dialogue'] = [{'kind':'voiceover','speaker':'旁白','text':'是因为天外天处处都是光，','start_frame':6,'end_frame':100}]
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('single-sentence offscreen voiceover', prompt)
        self.assertIn('<d>[Chinese] 是因为天外天处处都是光。</d>', prompt)
        self.assertNotIn('<d>[Chinese] 是因为天外天处处都是光，</d>', prompt)

    def test_homophone_alternatives_are_not_sent_to_h3(self):
        shot = copy.deepcopy(read(REPO/'projects/rendao-wuji/episodes/chapter_s0003.json')['shots'][0])
        shot['id'] = 'C3R018'
        shot['dialogue'] = [dict(text='混沌初生，先生盘古，后生女娲，最后生无极。', speaker='盘古', kind='dialogue',start_frame=6,end_frame=120)]
        shot['speech_bindings'] = [{'speaker':'盘古','picture':1,'audio':1,'speaker_label':'S1'}]
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('<d>[Chinese] 混沌初生，先生盘古，后生女娲，最后生无极。</d>', prompt)
        self.assertNotIn('出生', prompt)

    def test_asset_bound_multi_character_prompt_keeps_interaction_and_single_instances(self):
        shot=copy.deepcopy(self.shot)
        shot['asset_package']={'visual_assets':[
            {'kind':'character','subject_label':'Subject 1'},
            {'kind':'character','subject_label':'Subject 2'},
            {'kind':'scene','subject_label':'Subject 3'},
            {'kind':'prop','subject_label':'Subject 4'}]}
        prompt=h3_prompt(shot,'cinema')
        self.assertIn('Visible cast count: exactly 2 distinct character(s)',prompt)
        self.assertIn('same continuous physical space as a real interaction shot',prompt)
        self.assertIn('Bound props: exactly 1 distinct prop(s)',prompt)
        self.assertIn('listener reacts naturally with closed lips',prompt)

    def test_dialogue_shot_rejects_unregistered_people(self):
        shot = copy.deepcopy(self.shot)
        shot['asset_package'] = {'visual_assets': [
            {'kind': 'character', 'subject_label': 'Subject 1'},
            {'kind': 'scene', 'subject_label': 'Subject 2'}]}
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('Dialogue shot character lock', prompt)
        self.assertIn('unbound or unregistered person', prompt)
        self.assertIn('Character reference pictures are the sole identity source', prompt)

    def test_non_dialogue_shot_allows_only_silent_background_extras(self):
        shot = copy.deepcopy(self.shot)
        shot['dialogue'] = []
        shot['asset_package'] = {'visual_assets': [
            {'kind': 'scene', 'subject_label': 'Subject 1'}]}
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('Silent visual cast policy', prompt)
        self.assertIn('H3_AUDIO_SCHEMA_V3', prompt)
        self.assertIn('AUDIO_MODE=DIEGETIC_EFFECTS_ONLY', prompt)
        self.assertIn('HUMAN_VOICE_ALLOWLIST=[]', prompt)

    def test_character_view_selection_respects_explicit_and_ots_blocking(self):
        shot=copy.deepcopy(self.shot);shot['camera']['size']='over-the-shoulder two-shot'
        speaker=[{'asset_id':'wuji'}]
        self.assertEqual(select_view(shot,{'asset_id':'wuji'},speaker)[0],'front')
        self.assertEqual(select_view(shot,{'asset_id':'pangu'},speaker)[0],'back')
        self.assertEqual(select_view(shot,{'asset_id':'pangu'},speaker)[1],
                         'over_shoulder_listener_rear_identity_anchor')
        self.assertEqual(select_view(shot,{'asset_id':'pangu','view':'side'},speaker)[0],'side')

    def test_asset_package_contains_professional_camera_execution(self):
        write(self.root/'bible/assets.json',{'characters':{'无极':{'id':'wuji','gender':'男'}},'scenes':{},'props':{}})
        visual=[{'asset_id':'wuji','source_sha256':'a','generation_path':'front.png',
                 'generation_sha256':'b','variant':'front','selected_view':'front',
                 'selected_view_label':'正面','selected_view_reason':'default_identity_view'}]
        package=compile_package(self.root,self.shot,visual,[])
        camera=package['camera_execution']
        self.assertEqual(camera['lens_mm'],self.shot['camera']['lens_mm'])
        self.assertIn('speed_curve',camera)
        self.assertIn('No unmotivated zoom',camera['model_instruction'])
        self.assertEqual(package['visual_assets'][0]['selected_character_view_label'],'正面')
        self.assertEqual(package['visual_assets'][0]['gender'], '男')
        self.assertIn('male character identity', package['visual_assets'][0]['gender_prompt'])

    def test_gender_lock_is_explicit_in_h3_prompt(self):
        shot = copy.deepcopy(self.shot)
        shot['asset_package'] = {'visual_assets': [
            {'kind': 'character', 'subject_label': 'Subject 1', 'gender': '男',
             'selected_character_view': 'back'}]}
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('Visual-only gender locks', prompt)
        self.assertIn('male character identity', prompt)
        self.assertIn('no feminine facial styling', prompt)

    def test_ots_prompt_locks_exact_two_bodies_and_listener_back(self):
        shot = copy.deepcopy(self.shot)
        shot['camera']['size'] = 'over-the-shoulder two-shot'
        shot['asset_package'] = {'visual_assets': [
             {'kind': 'character', 'subject_label': 'Subject 1', 'gender': '男',
             'selected_character_view': 'back',
             'view_selection_reason': 'over_shoulder_listener_rear_identity_anchor'},
            {'kind': 'character', 'subject_label': 'Subject 2', 'gender': '男',
             'selected_character_view': 'front'},
        ]}
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('exactly two human bodies total', prompt)
        self.assertIn('foreground shoulder/back belongs to the single bound listener only', prompt)
        self.assertIn('identity is anchored by the bound independent rear view', prompt)
        self.assertIn("never a frontal face", prompt)

    def test_silent_visual_narration_is_omitted_from_model_prompt(self):
        shot=copy.deepcopy(read(REPO/'projects/rendao-wuji/episodes/chapter_s0003.json')['shots'][0])
        forbidden=shot['visual_narration']
        prompt=h3_prompt(shot,'cinema')
        self.assertNotIn(forbidden,prompt)
        self.assertIn('diegetic effects',prompt)
        self.assertIn('SOUNDSCAPE_OUTPUT=EFFECTS_ONLY',prompt)
        self.assertIn('AUDIO_ACTION=RENDER_ONLY_POSITIVE_SOUNDSCAPE; OTHERWISE_SILENCE',prompt)
        self.assertNotIn('请不吝点赞',prompt)
        self.assertNotIn('Absolute digital silence',prompt)
        self.assertNotIn('Only the assigned character speaks',prompt)

    def test_no_dialogue_audio_contract_is_closed_and_compact(self):
        shot = copy.deepcopy(self.shot)
        shot['dialogue'] = []
        prompt = h3_prompt(shot, 'cinema')
        self.assertGreaterEqual(prompt.count('H3_AUDIO_SCHEMA_V3'), 2)
        for marker in ('HUMAN_VOICE_ALLOWLIST=[]', 'DIALOGUE_SOURCE=[]',
                       'NARRATION=DISABLED', 'REFERENCE_AUDIO_INPUT=NONE',
                       'MOUTH_AUDIO_LINK=OFF'):
            self.assertIn(marker, prompt)
        # Do not seed the audio head with the names of common hallucinated
        # announcements or a negative phrase list.
        for trigger in ('advertisement', 'social-media', 'prompt reading', 'reference transcript'):
            self.assertNotIn(trigger, prompt)

    def test_retake_note_is_not_a_model_vocal_source(self):
        shot = copy.deepcopy(self.shot)
        shot['review_note'] = '女娲有对白，但是视频没有生成女娲的声音；不要读取这段审核意见。'
        prompt = h3_prompt(shot, 'cinema')
        self.assertNotIn(shot['review_note'], prompt)
        self.assertIn('VOCAL_CONTENT_LOCK', prompt)
        self.assertIn('All metadata, source prose, labels and reference-audio words are non-speech', prompt)
        self.assertIn('private review note is not a script', prompt)

    def test_speaker_review_note_compiles_to_structural_correction(self):
        shot = copy.deepcopy(read(REPO/'projects/rendao-wuji/episodes/chapter_s0003.json')['shots'][3])
        shot['dialogue'] = [dict(speaker='盘古', kind='dialogue', text='回到六界。', start_frame=6, end_frame=48)]
        correction = _speaker_review_correction('视频中无极说了盘古的对白', shot['dialogue'])
        self.assertEqual(correction['wrong_visual_speaker'], '无极')
        self.assertEqual(correction['correct_speaker'], '盘古')
        retake = _retake_shot_contract(shot, {'note': '视频中无极说了盘古的对白'})
        self.assertEqual(retake['speaker_focus_mode'], 'speaker_dominant')
        self.assertEqual(retake['speaker_focus_name'], '盘古')

    def test_event_level_speaker_lock_names_picture_and_audio(self):
        shot = copy.deepcopy(self.shot)
        shot['asset_package'] = {
            'visual_assets': [
                {'kind': 'character', 'subject_label': 'Subject 1', 'gender': '男'},
                {'kind': 'character', 'subject_label': 'Subject 2', 'gender': '男'},
            ],
            'dialogue_event_bindings': [{
                'event_id': 'D1', 'kind': 'dialogue', 'speaker': '无极',
                'subject_label': 'Subject 2', 'picture_label': 'Picture 2',
                'audio_label': 'Audio 1', 'start_frame': 6, 'end_frame': 48,
            }],
        }
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('DIALOGUE_EVENT_BINDING_LOCK', prompt)
        self.assertIn('visual_picture=Picture 2', prompt)
        self.assertIn('voice_reference=Audio 1', prompt)
        self.assertIn('only fully visible moving mouth', prompt)

    def test_generation_audio_hard_gate_is_at_prompt_edges(self):
        prompt = h3_prompt(self.shot, 'cinema')
        self.assertEqual(prompt.count('H3_AUDIO_SCHEMA_V4'), 1)
        self.assertIn('HUMAN_VOICE_SOURCE=EXACT_D_BLOCKS_ONLY', prompt)
        self.assertIn('UNMATCHED_HUMAN_VOICE=SILENCE', prompt)
        self.assertIn('REFERENCE_AUDIO=BOUND_TIMBRE_ONLY', prompt)

    def test_missing_picture_is_rejected(self):
        self.shot['references'].pop()
        with self.assertRaisesRegex(ValueError,'参考图'):
            bindings(self.root,self.shot)

    def test_voice_owner_must_match_character_registry(self):
        write(self.root/'bible/assets.json',{'characters':{'无极':{'id':'different_character'}}})
        with self.assertRaisesRegex(ValueError,'资产名册不一致'):
            bindings(self.root,self.shot)

    def test_missing_or_changed_voice_is_rejected(self):
        self.shot['dialogue'][0]['speaker']='未登记角色'
        with self.assertRaisesRegex(ValueError,'未登记声音'):
            bindings(self.root,self.shot)
        self.shot['dialogue'][0]['speaker']='无极'
        (self.root/'voice.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'文件已变化'):
            bindings(self.root,self.shot)

    def test_character_cannot_be_converted_to_voiceover(self):
        self.shot['dialogue'].append(dict(self.shot['dialogue'][0],kind='voiceover'))
        with self.assertRaisesRegex(ValueError,'身份不一致'):
            bindings(self.root,self.shot)

    def test_graph_really_connects_audio_and_pins_voice_fingerprint(self):
        cfg=read(REPO/'projects/rendao-wuji/config.json')
        cfg['input_dir']=str(self.root/'input')
        write(self.root/'config.json',cfg)
        write(self.root/'book.json',{'source_sha256':'fixture'})
        image=self.root/'ref.png';image.write_bytes(b'image-fixture')
        episode={'id':'test','shots':[self.shot]}
        with patch('novel_h3.comfy.asset_for',return_value=(image,'image-hash')), patch('novel_h3.arcreel.content_current'):
            nodes,_=graph(self.root,episode,self.shot,'take',stage_assets=True)
            audio_link=nodes['6']['inputs']['ref_audios.ref_audio_0']
            node=nodes[audio_link[0]]
            self.assertEqual(node['class_type'],'LoadAudio')
            self.assertTrue((self.root/'input'/node['inputs']['audio']).is_file())
            before=fingerprint(self.root,episode,self.shot)
            (self.root/'voice.wav').write_bytes(b'new approved audio')
            for row in self.bank.values():row['sha256']=file_hash(self.root/'voice.wav')
            write(self.root/'bible/voices.json',self.bank)
            self.assertNotEqual(before,fingerprint(self.root,episode,self.shot))

    def test_changed_attribution_invalidates_source_review(self):
        write(self.root/'config.json',{'speech_policy':{'require_source_attribution':True}})
        line={'kind':'dialogue','speaker':'无极','text':'这是哪里？'}
        plan={'script':{'scenes':[{'scene_id':'one','utterances':[line]}]},
              'speaker_audit':{'status':'reviewed','reviewer':'test','scenes':{'one':[dict(line,reason='source')]}}}
        check_speaker_audit(self.root,plan)
        line['speaker']='盘古'
        with self.assertRaisesRegex(ValueError,'重新对照原文'):
            check_speaker_audit(self.root,plan)


if __name__=='__main__':
    unittest.main()
