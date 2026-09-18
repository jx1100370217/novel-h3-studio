import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import (ingest, read, write, digest, file_hash, analysis_packet, accept_analysis,
                               inside, load_state, update_state, approve_asset, precheck_scene_prop_assets,
                               approve_prechecked_scene_prop_assets)
from novel_h3.director import validate_episode, h3_prompt, coverage, frames_for, delivered_frames
from novel_h3.comfy import graph, current_takes, review_take, review_chapter, review_visual, cancel, asset_for, bound_shot
from novel_h3.media import concatenate, enforce_silent_audio, technical_qc, probe, assemble_book, assemble_episode
from novel_h3.arcreel import save_content, approve_content, compile_visual, content_current

REPO = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "project"
        source = self.base / "novel.txt"
        source.write_bytes(('『状态:更新到:第320章：最后』\r\n'
                            '内容还在处理中,请稍后重第1章：资料\r\n人物资料。\r\n'
                            '第4章：山河\r\n海水泛滥，通天峰亮起金光。\r\n他说第8章：不能当成标题。\r\n'
                            '第4章：另一个章节\r\n船继续在洪水中摇晃。\r\n『还在连载中...』').encode('gb18030'))
        self.book = ingest(source, self.root)
        self.ep = read(REPO / "examples/proof_tongtian.json")
        pid = next(p['id'] for p in read(self.root/'paragraphs.json') if p['section']=='s0002')
        for shot in self.ep['shots']:
            shot['source_ids'] = [pid]
        self.ep['shots'][0].pop('first_frame')
        write(self.root/'episodes/proof_tongtian.json', self.ep)
        write(self.root/'config.json', {'generation':{'width':1024,'height':576,'steps':32},'models':{'fl2va':'a','ref2va':'b','clip':'c','video_vae':'v','audio_vae':'au'},'style':'Real cinema.','upstream_commit':'fixed','comfy_url':'http://localhost:8191','input_dir':str(self.base/'input')})

    def test_lossless_source_duplicate_numbers_and_glued_header(self):
        self.assertEqual([c['source_number'] for c in self.book['chapters']], [1,4,4])
        self.assertEqual(self.book['issues']['missing_chapter_numbers'], [2,3])
        self.assertEqual(self.book['issues']['duplicate_chapter_numbers'], {'4':2})
        self.assertTrue(self.book['issues']['serial_not_finished'])
        self.assertEqual(len({p['id'] for p in read(self.root/'paragraphs.json')}), len(read(self.root/'paragraphs.json')))
        source = (self.root/'source/original.txt').read_bytes()
        self.assertEqual(source,(self.base/'novel.txt').read_bytes())
        with self.assertRaises(ValueError): ingest(self.base/'novel.txt',self.root)

    def test_analysis_rejects_missing_paragraph_and_fabricated_evidence(self):
        packet = analysis_packet(self.root,'s0002')
        result = {'section':'s0002','dispositions':[], 'events':[]}
        with self.assertRaises(ValueError):accept_analysis(self.root,result)
        result['dispositions']=[{'paragraph_id':p['id'],'treatment':'dramatize','reason':'需要画面讲述'} for p in packet['paragraphs']]
        result['events']=[{'paragraph_ids':[packet['paragraphs'][0]['id']],'evidence':'原文没有这句话'}]
        with self.assertRaises(ValueError):accept_analysis(self.root,result)
        result['events'][0].update(evidence='通天峰亮起金光',cause='海水泛滥',action='山峰亮起金光',consequence='后果待下文确认',paragraph_ids=[p['id'] for p in packet['paragraphs']])
        accept_analysis(self.root,result)
        self.assertFalse(coverage(self.root)['all_supplied_text_accounted_for'])

    def test_frame_grid_and_no_timing_loss(self):
        self.assertEqual(frames_for(.1),5)
        self.assertEqual(frames_for(.5),22)
        self.assertEqual(frames_for(5),124)
        self.assertEqual(frames_for(5,True),158)
        self.assertEqual(delivered_frames(self.ep['shots'][1]),136)
        self.assertEqual(validate_episode(self.root,self.ep),[])
        with self.assertRaises(ValueError): frames_for(16)
        prompt=h3_prompt(self.ep['shots'][1],'test')
        self.assertIn('From 00:00.917 to 00:01.917',prompt)
        self.assertIn('non_diegetic_music:\nN/A',prompt)

    def test_scene_break_and_hold_and_dialogue_checks(self):
        ep=copy.deepcopy(self.ep);ep['shots'][1]['scene_id']='another_room'
        self.assertTrue(any('跨场景' in e for e in validate_episode(self.root,ep)))
        ep=copy.deepcopy(self.ep);ep['shots'][1]['hold_frames']=0
        self.assertTrue(any('2 秒' in e for e in validate_episode(self.root,ep)))
        ep=copy.deepcopy(self.ep);ep['shots'][1]['timeline'][1]['start_frame']=23
        self.assertTrue(any('时间线' in e for e in validate_episode(self.root,ep)))
        ep=copy.deepcopy(self.ep);ep['shots'][1]['dialogue']=[{'speaker':'A','text':'你好','start_frame':0,'end_frame':24}]
        self.assertTrue(any('抢入' in e for e in validate_episode(self.root,ep)))

    def test_graph_chains_sampler_latent_and_trims_both_streams(self):
        nodes,prefix=graph(self.root,self.ep,self.ep['shots'][1],'t_test','/tmp/old.safetensors')
        self.assertEqual(nodes['7']['inputs']['clip_index'],1)
        self.assertEqual(nodes['14']['inputs']['latent'],['13',0])
        self.assertEqual(nodes['18']['inputs']['trim_frames'],['8',1])
        self.assertEqual(nodes['19']['inputs']['audio'],['18',1])
        self.assertEqual(nodes['17']['inputs']['audio'],['16',0])
        self.assertNotIn('first_frame',nodes['6']['inputs'])
        self.assertEqual(nodes['20']['inputs']['format.codec'],'h264')
        a,_=graph(self.root,self.ep,self.ep['shots'][0],'t_test')
        self.assertEqual(a['7']['inputs']['clip_index'],0)

    def test_vdn_patches_both_sampler_consumers_and_keeps_motion_context(self):
        cfg=read(self.root/'config.json');cfg['vdn']=read(REPO/'examples/vdn_profile.json')
        cfg['generation'].update(steps=8,sampler='er_sde',scheduler='beta');write(self.root/'config.json',cfg)
        nodes,_=graph(self.root,self.ep,self.ep['shots'][1],'t_vdn','/tmp/previous.safetensors')
        self.assertEqual(nodes['21']['class_type'],'ApplyVDNH3')
        self.assertEqual(nodes['21']['inputs']['model'],['1',0])
        self.assertEqual(nodes['21']['inputs']['lora_mode'],'merge')
        self.assertTrue(nodes['21']['inputs']['apply_turbo_adapter'])
        self.assertEqual(nodes['5']['inputs']['model'],['21',0])
        self.assertEqual(nodes['10']['inputs']['model'],['5',0])
        self.assertEqual(nodes['12']['inputs']['model'],['5',0])
        self.assertEqual(nodes['12']['inputs']['steps'],8)
        self.assertEqual(nodes['11']['inputs']['sampler_name'],'er_sde')
        self.assertEqual(nodes['12']['inputs']['scheduler'],'beta')
        self.assertEqual(nodes['8']['inputs']['context_length'],'22')
        self.assertEqual(nodes['18']['inputs']['trim_frames'],['8',1])
        cfg['generation']['steps']=32;write(self.root/'config.json',cfg)
        with self.assertRaisesRegex(ValueError,'8 步'):graph(self.root,self.ep,self.ep['shots'][0],'wrong_steps')

    def test_switching_to_vdn_does_not_reuse_plain_h3_takes(self):
        shot,fp,_=current_takes(self.root,self.ep)[0]
        update_state(self.root,lambda s:s['takes'].update(old={'id':'old','episode':self.ep['id'],'shot':shot['id'],
            'fingerprint':fp,'status':'approved','video_sha256':'old_video','created_at':1}))
        self.assertIsNotNone(current_takes(self.root,self.ep)[0][2])
        cfg=read(self.root/'config.json');cfg['vdn']=read(REPO/'examples/vdn_profile.json');cfg['generation']['steps']=8;write(self.root/'config.json',cfg)
        self.assertIsNone(current_takes(self.root,self.ep)[0][2])
        self.assertIn('old',load_state(self.root)['takes'])

    def test_ref2va_reference_order(self):
        shot=copy.deepcopy(self.ep['shots'][0]);shot['mode']='ref2va';shot['references']=[{'asset_id':'person','description':'a young man','lock':'his face'},{'asset_id':'place','description':'a mountain','lock':'its shape'}]
        frame=self.root/'frame.png';frame.write_bytes(b'fixture')
        with patch('novel_h3.comfy.asset_for',return_value=(frame,'a'*64)):
            nodes,_=graph(self.root,self.ep,shot,'t_test')
        self.assertIn('ref_images.ref_image_0',nodes['6']['inputs'])
        self.assertIn('ref_images.ref_image_1',nodes['6']['inputs'])
        prompt=h3_prompt(shot,'realistic')
        self.assertTrue(prompt.startswith('subject_definitions:'))
        self.assertIn('<Picture 2>',prompt)

    def test_scene_plate_is_primary_reference_and_mismatch_fails_closed(self):
        write(self.root/'bible/assets.json', {
            'characters': {'人物': {'id': 'person'}},
            'scenes': {'场景甲': {'id': 'scene_a'}, '场景乙': {'id': 'scene_b'}},
            'props': {},
        })
        shot = copy.deepcopy(self.ep['shots'][0])
        shot.update(mode='ref2va', scene_id='scene_a', references=[
            {'asset_id': 'person', 'description': 'person', 'lock': 'identity'},
            {'asset_id': 'scene_a', 'description': 'scene', 'lock': 'environment'},
        ])
        def fake_reference(root, ref, camera=None, current_shot=None, speech_bindings=None):
            return {'asset_id': ref['asset_id'], 'source_sha256': ref['asset_id'],
                    'generation_path': ref['asset_id'] + '.png', 'generation_sha256': ref['asset_id'],
                    'variant': 'approved_source'}
        with patch('novel_h3.comfy.generation_reference', side_effect=fake_reference):
            ordered, _, package = bound_shot(self.root, shot)
        self.assertEqual(ordered['references'][0]['asset_id'], 'scene_a')
        self.assertEqual(package['scene_anchor']['picture_label'], 'Picture 1')
        shot['scene_id'] = 'scene_b'
        with patch('novel_h3.comfy.generation_reference', side_effect=fake_reference):
            with self.assertRaisesRegex(ValueError, '场景参考必须且只能绑定'):
                bound_shot(self.root, shot)
        shot['scene_id'] = 'scene_a'
        shot['references'].append({'asset_id': 'scene_b', 'description': 'wrong scene', 'lock': 'environment'})
        with patch('novel_h3.comfy.generation_reference', side_effect=fake_reference):
            with self.assertRaisesRegex(ValueError, '场景参考必须且只能绑定'):
                bound_shot(self.root, shot)
        shot['references'] = [ref for ref in shot['references'] if ref['asset_id'] != 'scene_b']
        shot['scene_id'] = 'scene_missing'
        with patch('novel_h3.comfy.generation_reference', side_effect=fake_reference):
            with self.assertRaisesRegex(ValueError, '不存在于场景资产名册'):
                bound_shot(self.root, shot)

    def test_replacing_upstream_take_invalidates_downstream_fingerprint(self):
        first=current_takes(self.root,self.ep)[0]
        one={'id':'t_one','episode':self.ep['id'],'shot':'S001','fingerprint':first[1],'status':'approved','video_sha256':'old','created_at':1}
        update_state(self.root,lambda s:s['takes'].update(t_one=one))
        fp=current_takes(self.root,self.ep)[1][1]
        two=dict(one,id='t_two',video_sha256='new',created_at=2)
        update_state(self.root,lambda s:s['takes'].update(t_two=two))
        self.assertNotEqual(fp,current_takes(self.root,self.ep)[1][1])

    def test_reject_invalidates_every_descendant(self):
        takes={'a':{'id':'a','status':'rendered'},'b':{'id':'b','status':'approved','previous_take':'a'},'c':{'id':'c','status':'approved','previous_take':'b'}}
        update_state(self.root,lambda s:s['takes'].update(takes))
        review_take(self.root,'a',False,'场景有漂移','tester',{})
        s=load_state(self.root)
        self.assertEqual(s['takes']['b']['status'],'stale');self.assertEqual(s['takes']['c']['status'],'stale')
        self.assertEqual(s['rework_queue']['take:a']['status'], 'queued')
        self.assertEqual(s['rework_queue']['take:a']['note'], '场景有漂移')

    def test_review_chapter_approves_all_current_takes_with_strict_checks(self):
        episode = copy.deepcopy(self.ep)
        episode['id'] = 'chapter_bulk'
        write(self.root/'episodes/chapter_bulk.json', episode)
        takes = {}
        for index, shot in enumerate(episode['shots'], 1):
            video = self.root/f'renders/chapter_bulk_{index}.mp4'
            video.parent.mkdir(parents=True, exist_ok=True)
            video.write_bytes(f'video-{index}'.encode())
            takes[f'take_{index}'] = {'id': f'take_{index}', 'episode': episode['id'], 'shot': shot['id'],
                                     'status': 'rendered', 'video': str(video.relative_to(self.root)),
                                     'video_sha256': file_hash(video), 'qc': {'passed': True}, 'created_at': index}
        update_state(self.root, lambda s: s['takes'].update(takes))
        checks = {key: True for key in ('story','identity','performance','camera','continuity','dialogue','sound','no_artifacts')}
        result = review_chapter(self.root, episode['id'], True, '已完整观看并听音确认', 'tester', checks)
        self.assertEqual(result['approved_shots'], len(episode['shots']))
        self.assertTrue(all(load_state(self.root)['takes'][f'take_{i}']['status'] == 'approved' for i in range(1, len(episode['shots']) + 1)))
        self.assertEqual(load_state(self.root)['takes']['take_1']['review']['scope'], 'chapter')
        with self.assertRaisesRegex(ValueError, '八项'):
            review_chapter(self.root, episode['id'], True, '再次确认', 'tester', {})

    def test_scene_prop_precheck_and_explicit_batch_confirmation_excludes_characters(self):
        write(self.root/'bible/assets.json', {'characters': {'角色甲': {'id': 'character_a'}},
              'scenes': {'场景甲': {'id': 'scene_a'}}, 'props': {'道具甲': {'id': 'prop_a'}}})
        for aid in ('character_a', 'scene_a', 'prop_a'):
            self.install_test_asset(aid)
            update_state(self.root, lambda s, aid=aid: s['assets'][aid].update(
                receipt={'model_verified': True, 'actual_model': 'gpt-image-2.5-test-fixture'}))
        report = precheck_scene_prop_assets(self.root)
        self.assertEqual(report['ready'], 2)
        self.assertEqual({row['bucket'] for row in report['items']}, {'scenes', 'props'})
        result = approve_prechecked_scene_prop_assets(self.root, 'tester', '场景和道具预检结果已逐项确认')
        state = load_state(self.root)
        self.assertEqual(result['approved'], 2)
        self.assertTrue(state['assets']['scene_a']['approved'])
        self.assertTrue(state['assets']['prop_a']['approved'])
        self.assertFalse(state['assets']['character_a']['approved'])

    def test_full_book_and_traversal_fail_closed(self):
        with self.assertRaises(ValueError):assemble_book(self.root)
        with self.assertRaises(ValueError):inside(self.root,'../../private.txt')

    def test_cancel_does_not_interrupt_another_project(self):
        update_state(self.root,lambda s:s['takes'].update(a={'status':'submitted','prompt_id':'ours'}))
        calls=[]
        def fake(base,route,payload=None):
            calls.append((route,payload))
            return {'queue_running':[[1,'theirs',{},{}]],'queue_pending':[[2,'ours',{},{}]]}
        with patch('novel_h3.comfy.api',side_effect=fake):cancel(self.root)
        self.assertNotIn('/interrupt',[r for r,_ in calls])
        self.assertIn(('/queue',{'delete':['ours']}),calls)

    def content_fixture(self):
        plan={k:self.ep[k] for k in ('id','dramatic_question','turning_point')}
        plan['script']={'title':'内容锁定测试','scenes':[]};plan['source_map']={}
        visual={'scenes':[]}
        for shot in self.ep['shots']:
            sid=shot['id'];plan['source_map'][sid]=shot['source_ids']
            plan['script']['scenes'].append({'scene_id':sid,'duration_seconds':5,'characters_in_scene':[],
                'scenes':[],'props':[],'scene_description':shot['action'],'source_text':'通天峰亮起金光',
                'utterances':[{'kind':'voiceover','speaker':None,'text':'金光亮起。'}] if sid=='S001' else []})
            h3={k:copy.deepcopy(v) for k,v in shot.items() if k not in ('id','scene_id','source_ids','dialogue','frames')}
            h3['location_id']=shot['scene_id']
            visual['scenes'].append({'scene_id':sid,'image_prompt':'A flooded mountain at night.', 'h3':h3,
                'speech_timing':[{'start_frame':0,'end_frame':24}] if sid=='S001' else []})
        save_content(self.root,plan)
        visual['content_sha256']=digest(plan)
        return plan,visual

    def test_arcreel_merge_requires_content_review_and_preserves_order(self):
        plan,visual=self.content_fixture()
        with self.assertRaises(ValueError):compile_visual(self.root,plan['id'],visual)
        approve_content(self.root,plan['id'],'tester','原文、台词、结构已阅读')
        visual['scenes'].reverse()
        compile_visual(self.root,plan['id'],visual)
        ep=read(self.root/'episodes'/f"{plan['id']}.json")
        self.assertEqual([s['id'] for s in ep['shots']],['S001','S002'])
        self.assertEqual(ep['shots'][0]['dialogue'][0]['text'],'金光亮起。')
        exported=read(self.root/'arcreel_export'/plan['id']/'script.json')
        self.assertEqual(exported['scenes'][0]['utterances'],plan['script']['scenes'][0]['utterances'])
        self.assertNotIn('金光亮起。',exported['scenes'][0]['video_prompt'])
        self.assertIsNone(exported['scenes'][0]['utterances'][0]['speaker'])

    def test_arcreel_rejects_visual_dialogue_injection_and_duplicate_scenes(self):
        plan,visual=self.content_fixture();approve_content(self.root,plan['id'],'test','reviewed')
        bad=copy.deepcopy(visual);bad['scenes'][0]['utterances']=[]
        with self.assertRaises(ValueError):compile_visual(self.root,plan['id'],bad)
        bad=copy.deepcopy(visual);bad['scenes'][1]=bad['scenes'][0]
        with self.assertRaises(ValueError):compile_visual(self.root,plan['id'],bad)
        bad=copy.deepcopy(visual);bad['scenes'][0]['speech_timing'][0]['text']='偷偷改词'
        with self.assertRaises(ValueError):compile_visual(self.root,plan['id'],bad)

    def test_arcreel_changed_content_or_compiled_dialogue_revokes_approval(self):
        plan,visual=self.content_fixture();approve_content(self.root,plan['id'],'test','reviewed')
        compile_visual(self.root,plan['id'],visual)
        ep=read(self.root/'episodes'/f"{plan['id']}.json")
        altered=copy.deepcopy(ep);altered['shots'][0]['dialogue'][0]['text']='修改过的台词'
        with self.assertRaises(ValueError):content_current(self.root,altered)
        plan['script']['scenes'][0]['utterances'][0]['text']='新台词'
        save_content(self.root,plan)
        with self.assertRaises(ValueError):content_current(self.root,ep)

    def test_compiling_preserves_matching_generated_frame_and_invalidates_changed_prompt(self):
        plan,visual=self.content_fixture();approve_content(self.root,plan['id'],'test','reviewed')
        row=visual['scenes'][0];row['h3']['first_frame']='existing_frame'
        self.install_test_asset('existing_frame')
        path=self.root/'jobs/image_existing_frame.json';job=read(path)
        job.update(prompt=row['image_prompt'],role='shot_first_frame');write(path,job)
        compile_visual(self.root,plan['id'],visual)
        self.assertEqual(read(path),job)
        row['image_prompt']='A changed composition.'
        compile_visual(self.root,plan['id'],visual)
        self.assertNotEqual(digest(read(path)),digest(job))

    def install_test_asset(self,aid,refs=None):
        job={'id':aid,'reference_asset_ids':refs or []};write(self.root/'jobs'/f'image_{aid}.json',job)
        path=self.root/'assets'/f'{aid}.png';path.write_bytes(aid.encode())
        item={'path':str(path.relative_to(self.root)),'sha256':file_hash(path),'approved':False,'job_sha256':digest(job),
              'receipt':{'model_verified':False,'actual_model':'unknown'},
              'reference_hashes':{key:load_state(self.root)['assets'][key]['sha256'] for key in refs or []}}
        update_state(self.root,lambda s:s['assets'].update({aid:item}))

    def test_unverified_image_cannot_be_approved_even_for_a_proof(self):
        self.install_test_asset('base')
        with self.assertRaisesRegex(ValueError,'来源尚未核实'):approve_asset(self.root,'base','test','looks good')
        self.assertFalse(load_state(self.root)['assets']['base']['approved'])

    def test_explicit_managed_tool_policy_preserves_unknown_and_rejects_substitution(self):
        self.install_test_asset('base')
        cfg=read(self.root/'config.json');cfg['image_provider']={'accept_managed_tool_model_unknown':True};write(self.root/'config.json',cfg)
        job=read(self.root/'jobs/image_base.json');job.update(provider='codex_image_gen',prompt='Actual call');write(self.root/'jobs/image_base.json',job)
        receipt={'tool':'image_gen','actual_model':'unknown','model_verified':False,'tool_output_file':'/actual/tool.png','generated_at':'2026-09-14','prompt':'Actual call'}
        update_state(self.root,lambda s:s['assets']['base'].update(job_sha256=digest(job),receipt=receipt))
        approve_asset(self.root,'base','test','reviewed')
        self.assertEqual(load_state(self.root)['assets']['base']['receipt']['actual_model'],'unknown')
        update_state(self.root,lambda s:s['assets']['base']['receipt'].update(actual_model='another-generator'))
        with self.assertRaises(ValueError):asset_for(self.root,'base')

    def test_visual_sampling_cannot_approve_audio_or_release(self):
        video=self.root/'renders/clip.mp4';video.write_bytes(b'video fixture')
        sheet=self.root/'renders/sheet.jpg';sheet.write_bytes(b'sheet fixture')
        take={'id':'t_visual','status':'rendered','video':'renders/clip.mp4','video_sha256':file_hash(video),'qc':{'passed':True}}
        update_state(self.root,lambda s:s['takes'].update(t_visual=take))
        review_visual(self.root,'t_visual','Viewed actual frames','Boat left, mountain right.',sheet)
        current=load_state(self.root)['takes']['t_visual']
        self.assertEqual(current['status'],'rendered')
        self.assertFalse(current['visual_review']['release_approved'])
        with patch('novel_h3.comfy.current_takes',return_value=[({},'hash',current)]):
            with self.assertRaisesRegex(ValueError,'实际审片'):assemble_episode(self.root,self.ep['id'])

    def test_character_reference_regeneration_invalidates_derivative(self):
        self.install_test_asset('base')
        update_state(self.root,lambda s:s['assets']['base'].update(approved=True,receipt={'model_verified':True,'actual_model':'gpt-image-2.5-test-fixture'}))
        self.install_test_asset('rain',['base'])
        update_state(self.root,lambda s:s['assets']['rain'].update(approved=True,receipt={'model_verified':True,'actual_model':'gpt-image-2.5-test-fixture'}))
        asset_for(self.root,'rain')
        path=self.root/'assets/base.png';path.write_bytes(b'changed base identity')
        update_state(self.root,lambda s:s['assets']['base'].update(sha256=file_hash(path)))
        with self.assertRaisesRegex(ValueError,'参考 base 已变化'):asset_for(self.root,'rain')

    def test_cancel_recovers_owned_submission_after_uncertain_post(self):
        update_state(self.root,lambda s:s['takes'].update(t1={'status':'submitting'}))
        calls=[]
        def fake(base,route,payload=None):
            calls.append((route,payload))
            return {'queue_running':[[1,'ours',{}, {'novel_h3_take':'t1'}]],'queue_pending':[]} if route=='/queue' else {}
        with patch('novel_h3.comfy.api',side_effect=fake):cancel(self.root)
        self.assertIn(('/interrupt',{}),calls)
        self.assertEqual(load_state(self.root)['takes']['t1']['status'],'canceled')


class MediaTests(unittest.TestCase):
    def test_silent_policy_keeps_track_and_removes_generated_sound(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'shot.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x192:rate=24:duration=1',
                            '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
                            '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)],check=True)
            report=enforce_silent_audio(path)
            self.assertEqual(report['policy'],'absolute_silence')
            self.assertTrue(technical_qc(path,24,320,192)['passed'])
            check=subprocess.run(['ffmpeg','-v','info','-i',str(path),'-vn','-af','volumedetect','-f','null','-'],
                                 capture_output=True,text=True,check=True)
            match=re.search(r'max_volume:\s+(-?[\d.]+) dB',check.stderr)
            self.assertIsNotNone(match)
            self.assertLessEqual(float(match.group(1)),-90.0)

    def test_mixed_audio_rates_concatenate_without_silencing_tail(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);paths=[]
            for i,rate in enumerate([32000,48000]):
                path=root/f'{i}.mp4'
                subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=24:duration=1','-f','lavfi','-i',f'sine=frequency={440+440*i}:sample_rate={rate}:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(path)],check=True)
                paths.append(path)
            output=root/'final.mp4'
            report=concatenate(paths,output,320,180)
            self.assertTrue(report['passed']);self.assertEqual(report['frames'],48)
            self.assertEqual(report['audio_sample_rate'],48000)
            result=subprocess.run(['ffmpeg','-v','info','-ss','1.1','-i',str(output),'-vn','-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
            self.assertIn('mean_volume:',result.stderr)
            self.assertNotIn('mean_volume: -inf',result.stderr)
            self.assertFalse(technical_qc(output,49,320,180)['passed'])


if __name__=='__main__':unittest.main()
