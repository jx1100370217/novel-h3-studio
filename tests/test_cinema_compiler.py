import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3.project import file_hash, write
from novel_h3.v2.compiler import compile_shot, frames_for, graph
from novel_h3.v2.frames import sample_indices


class CinemaCompilerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write(self.root / 'config.json', {
            'generation': {'width': 1376, 'height': 768, 'steps': 20, 'fps': 24,
                           'sampler': 'er_sde', 'scheduler': 'beta'},
            'models': {'ref2va': 'ref.safetensors', 'clip': 'clip.safetensors',
                       'video_vae': 'video.safetensors', 'audio_vae': 'audio.safetensors'},
        })
        write(self.root / 'bible/assets.json', {
            'characters': {'甲': {'id': 'actor_a'}, '乙': {'id': 'actor_b'}},
            'scenes': {'殿': {'id': 'hall'}}, 'props': {'册': {'id': 'book'}},
        })
        (self.root / 'voice.wav').write_bytes(b'voice-fixture')
        write(self.root / 'bible/voices.json', {'甲': {
            'asset_id': 'actor_a', 'path': 'voice.wav',
            'sha256': file_hash(self.root / 'voice.wav'), 'approved': True,
        }})
        self.shot = {'id': 'P01', 'scene_id': 'hall', 'cast': ['actor_a', 'actor_b'],
                     'references': ['book'], 'duration_seconds': 6,
                     'spoken_lines': [{'speaker': 'actor_a', 'text': '让我先照顾母亲。'}],
                     'camera': {'size': 'medium two-shot', 'lens_mm': 50,
                                'composition': 'Alpha looks toward Beta, not the lens.'},
                     'action': 'Alpha holds the book; Beta receives the request without speaking.',
                     'start_state': 'The two people face each other.',
                     'end_state': 'Beta lowers his gaze in thought.',
                     'soundscape': 'Quiet hall ambience and soft cloth movement.',
                     'performance_direction': 'An earnest request to the listener, with one restrained breath.'}
        self.plan = {'id': 'pilot', 'subject_aliases': {'actor_a': 'Alpha', 'actor_b': 'Beta'},
                     'shots': [self.shot]}
        self.image = patch('novel_h3.v2.compiler.generation_reference',
                           side_effect=lambda root, ref, **kw: {'asset_id': ref['asset_id'],
                               'generation_path': ref['asset_id']+'.png', 'generation_sha256': 'image-hash'})
        self.image.start()
        self.addCleanup(self.image.stop)
        self.full_image = patch('novel_h3.v2.compiler.asset_for',
                                side_effect=lambda root, a: (root / (a+'.png'), 'full-image-hash'))
        self.full_image.start()
        self.addCleanup(self.full_image.stop)
        self.model_lock = patch('novel_h3.v2.compiler.pinned_models', return_value={'ref2va': {'sha256': 'weights'}})
        self.model_lock.start()
        self.addCleanup(self.model_lock.stop)
        self.duration = patch('novel_h3.v2.compiler.audio_duration', return_value=8.0)
        self.duration.start()
        self.addCleanup(self.duration.stop)

    def test_native_prompt_binds_every_reference_and_keeps_dialogue(self):
        req = compile_shot(self.root, self.plan, self.shot, 123)
        text = req['prompt']
        self.assertIn('<d>[Chinese] 让我先照顾母亲。</d>', text)
        self.assertIn('<Subject 1> holds the <Subject 4>; <Subject 2> receives', text)
        self.assertIn('At 00:00.500', text)
        self.assertIn('<Audio 1> is the voice-timbre reference for <Subject 1> (S1)', text)
        self.assertIn('<Subject 1> (S1) says:', text)
        self.assertNotIn('All bound mouths stay closed', text)
        self.assertNotIn('MOUTH_AUDIO_LINK=OFF', text)
        self.assertNotIn('asset_id', text)
        self.assertEqual(req['audio_route'], 'h3_native_joint')
        self.assertEqual([r['variant'] for r in req['visuals'] if r['kind'] != 'character'],
                         ['approved_full_image', 'approved_full_image'])
        for i, ref in enumerate(req['visuals']): ref['staged_name'] = f'image{i}.png'
        req['voices'][0]['staged_name'] = 'voice.wav'
        nodes, _ = graph(req, 'candidate')
        self.assertEqual(nodes['6']['class_type'], 'MiniMaxH3ReferenceToVideo')
        self.assertEqual(nodes['18']['inputs']['trim_frames'], 0)
        self.assertEqual(nodes['19']['inputs']['audio'], ['18', 1])
        self.assertEqual(nodes['17']['class_type'], 'SaveAudio')
        self.assertNotIn('ApplyVDNH3', [n['class_type'] for n in nodes.values()])

    def test_voice_hash_change_blocks_submission(self):
        (self.root / 'voice.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Voice reference changed'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def dialogue_target(self):
        path = self.root / 'target.wav'
        path.write_bytes(b'full-length-dialogue-fixture')
        self.shot['audio_target'] = {'path': 'target.wav', 'sha256': file_hash(path),
                                     'speaker': 'actor_a', 'text': '让我先照顾母亲。'}

    def test_dialogue_target_is_seen_by_h3_during_sampling(self):
        self.dialogue_target()
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['audio_route'], 'h3_audio_conditioned')
        for i, ref in enumerate(req['visuals']): ref['staged_name'] = f'image{i}.png'
        req['voices'][0]['staged_name'] = 'voice.wav'
        req['audio_target']['staged_name'] = 'dialogue/target.wav'
        nodes, _ = graph(req, 'candidate')
        self.assertEqual(nodes['13']['inputs']['latent_image'], ['304', 0])
        self.assertEqual(nodes['302']['inputs']['value'], 0.0)
        self.assertEqual(nodes['304']['inputs']['video_latent'], ['6', 1])
        self.assertEqual(nodes['301']['class_type'], 'VAEEncodeAudio')
        self.assertEqual(nodes['17']['inputs']['audio'], ['16', 0])

    def test_wrong_target_words_or_speaker_are_rejected(self):
        self.dialogue_target()
        self.shot['audio_target']['text'] = '另外一句。'
        with self.assertRaisesRegex(ValueError, 'literal text'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_nonverbal_conditioning_requires_actual_no_speech_evidence(self):
        self.dialogue_target()
        self.shot['spoken_lines'] = []
        target = self.shot['audio_target']
        target.update(kind='nonverbal', text='', speaker=None)
        proof = self.root / 'no_speech.json'
        write(proof, {'passed': True, 'target_sha256': target['sha256'],
                      'speech_gate': {'speech_detected': False}})
        target.update(verification_path='no_speech.json', verification_sha256=file_hash(proof))
        request = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(request['audio_route'], 'h3_audio_conditioned')
        self.assertEqual(request['voices'], [])
        self.assertNotIn('<d>', request['prompt'])
        write(proof, {'passed': True, 'target_sha256': target['sha256'],
                      'speech_gate': {'speech_detected': True}})
        target['verification_sha256'] = file_hash(proof)
        with self.assertRaisesRegex(ValueError, 'no-speech inspection'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_short_or_changed_target_is_rejected(self):
        self.dialogue_target()
        with patch('novel_h3.v2.compiler.audio_duration', return_value=2.0):
            with self.assertRaisesRegex(ValueError, 'cover the complete'):
                compile_shot(self.root, self.plan, self.shot, 123)
        (self.root / 'target.wav').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'unchanged project WAV'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_unbound_or_second_speaker_is_rejected(self):
        self.shot['spoken_lines'].append({'speaker': 'actor_b', 'text': '答复。'})
        with self.assertRaisesRegex(ValueError, 'one visible speaker'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_unsupported_short_generation_is_not_silently_clamped(self):
        with self.assertRaises(ValueError): frames_for(2)
        self.assertEqual((frames_for(7)-5) % 17, 0)

    def test_undeclared_ordinals_are_rejected_before_prompt_building(self):
        self.shot['action'] = '<Picture 9> appears suddenly.'
        with self.assertRaisesRegex(ValueError, 'compiler'):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_reaction_clip_does_not_receive_voice_or_reference_words(self):
        self.shot['spoken_lines'] = []
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['voices'], [])
        self.assertNotIn('<d>', req['prompt'])
        self.assertNotIn('<Audio', req['prompt'])
        self.assertIn('natural breathing', req['prompt'])

    def test_offscreen_ear_voice_does_not_turn_the_listener_into_the_speaker(self):
        self.shot['cast'] = ['actor_b']
        self.shot['spoken_lines'][0]['offscreen'] = True
        self.shot['soundscape'] = 'A faint close voice is heard from the listening character ear.'
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertIn('the offscreen voice of <Subject 1> (S1)', req['prompt'])
        self.assertIn('All visible characters keep their lips at rest', req['prompt'])
        self.assertIn('exactly 1 people in total', req['prompt'])
        self.assertNotIn('synchronized visible articulation', req['prompt'])
        self.assertEqual(req['voices'][0]['asset_id'], 'actor_a')

    def test_offscreen_permission_cannot_allow_an_unregistered_or_mixed_speaker(self):
        self.shot['spoken_lines'][0]['offscreen'] = 1
        with self.assertRaisesRegex(ValueError, 'boolean'):
            compile_shot(self.root, self.plan, self.shot, 123)
        self.shot['spoken_lines'][0]['offscreen'] = True
        self.shot['spoken_lines'].append({'speaker': 'actor_a', 'text': '答复。', 'offscreen': False})
        with self.assertRaisesRegex(ValueError, 'consistent'):
            compile_shot(self.root, self.plan, self.shot, 123)
        self.shot['spoken_lines'] = [{'speaker':'unknown','text':'耳语。','offscreen':True}]
        with self.assertRaises(ValueError):
            compile_shot(self.root, self.plan, self.shot, 123)

    def test_creative_change_invalidates_the_request(self):
        first = compile_shot(self.root, self.plan, self.shot, 123)
        changed = copy.deepcopy(self.shot)
        changed['action'] += ' He sits down.'
        second = compile_shot(self.root, self.plan, changed, 123)
        self.assertNotEqual(first['request_sha256'], second['request_sha256'])

    def test_paper_insert_has_no_phantom_actor_or_voice(self):
        self.shot.update(cast=[], spoken_lines=[], action='A blank paper lies flat on the desk.')
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertEqual(req['voices'], [])
        self.assertIn('No people are visible in this insert', req['prompt'])
        self.assertNotIn('natural breathing', req['prompt'])

    def test_sampling_covers_last_frame_of_long_clip(self):
        frames = sample_indices(277)
        self.assertEqual(len(frames), 24)
        self.assertEqual(frames[0], 0)
        self.assertEqual(frames[-1], 276)

    def test_ensemble_reference_is_not_misdeclared_as_one_person(self):
        write(self.root / 'bible/assets.json', {
            'characters': {'众官': {'id': 'ensemble', 'instances': 9}},
            'scenes': {'殿': {'id': 'hall'}}, 'props': {},
        })
        self.shot.update(cast=['ensemble'], references=[], spoken_lines=[],
                         action='The ensemble is seated in one coherent row.')
        req = compile_shot(self.root, self.plan, self.shot, 123)
        self.assertIn('ensemble of exactly 9 distinct members', req['prompt'])
        self.assertIn('exactly 9 people in total', req['prompt'])


if __name__ == '__main__':
    unittest.main()
