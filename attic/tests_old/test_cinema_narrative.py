from copy import deepcopy
from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import read, write
from novel_h3.v2.narrative import BEATS, check, preflight
from novel_h3.v2.production import freeze_plan, produce


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.texts = ['甲病中。', '陌生人召考。', '甲为母请假。', '获准九年。', '九年后赴任。', '死后拜别家人。']
        write(self.root/'paragraphs.json', [{'id':'p1','section':'s1','text':''.join(self.texts)}])
        facts = [{'id':f'F{i}','paragraph_id':'p1','evidence':text} for i,text in enumerate(self.texts)]
        self.plan = {'id':'chapter', 'chapter_id':'chapter_s1','source_paragraph_ids':['p1'], 'source_fact_ledger':facts, 'shots':[
            {'id':f'S{i}','duration_seconds':5,'spoken_lines':[{'text':t,'speaker':'actor'}], 'action':'The character acts.'}
            for i,t in enumerate(self.texts)]}
        self.contract = {'facts':facts, 'requirements':[
            {'id':f'R{i}','beat':beat,'audience_question':'发生了什么？','answer':t,'facts':[f'F{i}'],
             'depends_on':[] if i==0 else [f'R{i-1}'], 'explicit_required':True,
             'deliveries':[{'shot_id':f'S{i}','kind':'dialogue','text':t,'facts':[f'F{i}']}]}
            for i,(beat,t) in enumerate(zip(BEATS,self.texts))]}
        self.timeline = {'tracks':[{'segments':[{'shot_id':f'S{i}','source_in_frame':0,'source_out_frame':120} for i in range(6)]}],
                         'subtitles':[{'text':t,'start_frame':i*120+12,'end_frame':i*120+72} for i,t in enumerate(self.texts)]}

    def test_complete_delivery_is_only_a_structural_pass(self):
        result=check(self.root,self.plan,self.contract,self.timeline)
        self.assertTrue(result['passed'])
        self.assertFalse(result['human_understood_story'])
        self.assertFalse(result['release_approved'])

    def test_missing_ending_is_reported_without_crashing(self):
        self.contract['requirements'].pop()
        result=check(self.root,self.plan,self.contract)
        self.assertFalse(result['passed'])
        self.assertTrue(any('closure' in p for p in result['problems']))

    def test_fact_ids_and_plot_summary_cannot_replace_audible_delivery(self):
        self.plan['shots'][0]['facts']=[f'F{i}' for i in range(6)]
        self.plan['shots'][0]['spoken_lines']=[]
        result=check(self.root,self.plan,self.contract)
        self.assertFalse(result['passed'])
        self.assertTrue(any('实际对白' in p for p in result['problems']))

    def test_crop_losing_the_result_blocks_the_edit(self):
        self.timeline['tracks'][0]['segments'].pop()
        result=check(self.root,self.plan,self.contract,self.timeline)
        self.assertFalse(result['passed'])
        self.assertTrue(any('被剪辑删除' in p for p in result['problems']))
        self.timeline['tracks'][0]['segments'].append({'shot_id':'S5','source_in_frame':0,'source_out_frame':24})
        self.assertTrue(any('关键对白' in p for p in check(self.root,self.plan,self.contract,self.timeline)['problems']))

    def test_source_evidence_and_causal_order_are_required(self):
        changed=deepcopy(self.contract);changed['facts'][0]['evidence']='原文没有这句话'
        self.assertFalse(check(self.root,self.plan,changed)['passed'])
        self.contract['requirements'][2]['depends_on']=['R5']
        self.assertTrue(any('因果前提之前' in p for p in check(self.root,self.plan,self.contract)['problems']))

    def test_a_script_cannot_ignore_the_original_ending_paragraph(self):
        write(self.root/'paragraphs.json', [{'id':'p1','section':'s1','text':''.join(self.texts)},
              {'id':'p2','section':'s1','text':'后来他确实履约。'}])
        self.assertTrue(any('完整原文' in p for p in check(self.root,self.plan,self.contract)['problems']))
        self.plan['source_paragraph_ids'].append('p2')
        self.assertTrue(any('省略理由' in p for p in check(self.root,self.plan,self.contract)['problems']))

    def test_each_delivery_must_cover_its_own_fact(self):
        self.contract['requirements'][0]['deliveries'][0].pop('facts')
        report=check(self.root,self.plan,self.contract)
        self.assertFalse(report['passed'])
        self.assertTrue(any('具体原文事实' in p for p in report['problems']))

    def test_ambiguous_visual_only_information_never_becomes_automatic_approval(self):
        req=self.contract['requirements'][-1]
        req['deliveries']=[{'shot_id':'S5','kind':'visual','facts':['F5'],
                            'event':'The character is dead.','action_evidence':'The character acts.','source_interval_frames':[0,120]}]
        report=check(self.root,self.plan,self.contract,self.timeline)
        self.assertFalse(report['passed'])
        self.assertEqual(report['pending_visual_review'][0]['status'],'needs_actual_visual_review')
        req['explicit_required']=False
        self.assertTrue(check(self.root,self.plan,self.contract,self.timeline)['passed'])
        self.timeline['tracks'][0]['segments'][-1]['source_out_frame']=48
        self.assertTrue(any('必要动作' in p for p in check(self.root,self.plan,self.contract,self.timeline)['problems']))

    def test_readable_text_must_fit_source_and_final_edit(self):
        req=self.contract['requirements'][-1]
        self.plan['typography_cues']=[{'id':'end','shot_id':'S5','text':self.texts[-1], 'start_seconds':1,'end_seconds':4}]
        req['deliveries']=[{'shot_id':'S5','kind':'text','cue_id':'end','text':self.texts[-1],'facts':['F5'],'minimum_seconds':3}]
        self.timeline['typography']=[{'id':'end','start_frame':624,'end_frame':648}]
        self.assertTrue(any('阅读时间' in p for p in check(self.root,self.plan,self.contract,self.timeline)['problems']))
        self.plan['typography_cues'][0]['end_seconds']=6
        self.assertTrue(any('时长' in p for p in check(self.root,self.plan,self.contract)['problems']))

    def test_missing_contract_blocks_gpu_work_before_any_submission(self):
        path=self.root/'production_v2/chapter/plan.json';write(path,self.plan)
        write(self.root/'config.json',{})
        with patch('novel_h3.v2.production.api') as api, patch('novel_h3.v2.production.job') as job:
            with self.assertRaisesRegex(ValueError,'Missing narrative_contract'):
                produce(self.root,path,123)
            api.assert_not_called();job.assert_not_called()
        write(path.parent/'narrative_contract.json',self.contract)
        self.assertTrue(preflight(self.root,path)['passed'])

    def test_freeze_works_for_a_new_chapter_and_preserves_explicit_reuse(self):
        source=self.root/'production_v2/new_chapter/plan.json'
        self.plan['production_id']='new_chapter_r2'
        self.plan['reused_takes']={'S0':'production_v2/old/takes/chosen'}
        self.plan['shots'][0]['audio_target']={'path':'old.wav','sha256':'verified-old-input'}
        write(source,self.plan)
        audio=source.parent/'chapter_audio/manifest.json'
        write(audio,{'entries':[{'shot_id':f'S{i}','expected_text':t,'speaker_asset_id':'actor',
            'timing':{'generated_clip_seconds':5,'lead_seconds':.5},'target':{'path':f'S{i}.wav'},
            'provenance':{},'source_reference':{}} for i,t in enumerate(self.texts)]})
        frozen=freeze_plan(self.root,source,audio)
        self.assertEqual(frozen['id'],'new_chapter_r2')
        self.assertEqual(frozen['shots'][0]['audio_target'],self.plan['shots'][0]['audio_target'])
        self.assertEqual(frozen['shots'][1]['audio_target']['text'],self.texts[1])

    def test_producer_checks_explicit_reused_receipts_before_export(self):
        source=self.root/'production_v2/revised/plan.json'
        selected={s['id']:'take_'+s['id'] for s in self.plan['shots']}
        self.plan['reused_takes']={sid:'production_v2/old/takes/'+tid for sid,tid in selected.items()}
        for sid,relative in self.plan['reused_takes'].items():
            write(self.root/relative/'take.json',{'id':selected[sid],'speech_screening':{'passed':True}})
        write(source,self.plan)
        write(source.with_name('narrative_contract.json'),self.contract)
        write(source.parent/'chapter_audio/manifest.json',{'entries':[]})
        manifest=source.parent/'runs/seed_123.json';write(manifest,{'takes':selected})
        review={'video':'review_exports/revised/review.mp4'}
        with ExitStack() as stack:
            stack.enter_context(patch('novel_h3.v2.cinematization.require', return_value={'passed': True}))
            for name,value in [('config',{'comfy_url':'test'}),('compile_shot',{}),
                               ('freeze_plan',self.plan),('run',manifest),('job',0)]:
                stack.enter_context(patch('novel_h3.v2.production.'+name,return_value=value))
            stack.enter_context(patch('novel_h3.v2.production.api',return_value={'queue_running':[],'queue_pending':[]}))
            for name in ('check_paused','roundtrip','reuse_candidate','time.sleep'):
                stack.enter_context(patch('novel_h3.v2.production.'+name))
            stack.enter_context(patch('novel_h3.v2.chapter_edit.chapter_timeline',return_value={'narrative_check':{'passed':True}}))
            stack.enter_context(patch('novel_h3.v2.edit.export_review',return_value=review))
            self.assertEqual(produce(self.root,source,123),review)
        self.assertEqual(read(source.parent/'production.json')['status'],'chapter_review_ready')
        self.assertFalse((source.parent/'takes').exists())


if __name__=='__main__':unittest.main()
