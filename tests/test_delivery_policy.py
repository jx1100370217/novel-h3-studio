import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novel_h3.project import write,read,file_hash
from novel_h3.delivery_policy import finish_shot,maybe_assemble,approve_chapter_video
from novel_h3.scene_continuity import contract

class DeliveryPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        v=self.root/'renders/t/video.mp4';v.parent.mkdir(parents=True);v.write_bytes(b'media')
        self.take={'id':'t','episode':'chapter_s1','shot':'D1','status':'rendered','qc':{'passed':True},'video':'renders/t/video.mp4','video_sha256':file_hash(v),'speech_check':{'passed':False}}
        write(self.root/'state.json',{'takes':{'t':self.take},'assets':{},'approvals':{}})
        write(self.root/'episodes/chapter_s1.json',{'id':'chapter_s1','shots':[{'id':'D1'}]})
    def test_normal_autoapprove_keeps_failed_transcription_and_does_not_fake_manual(self):
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            finish_shot(self.root,'t');compose.assert_called_once_with(self.root,'chapter_s1')
        take=read(self.root/'state.json')['takes']['t']
        self.assertEqual(take['status'],'approved');self.assertFalse(take['speech_check']['passed'])
        self.assertEqual(take['approval_method'],'automatic_normal_queue');self.assertEqual(take['review']['checks'],{})
    def test_retake_requires_human_does_not_compose(self):
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            finish_shot(self.root,'t',retake=True);compose.assert_not_called()
        self.assertEqual(read(self.root/'state.json')['takes']['t']['status'],'rendered')
    def test_partial_and_unreviewed_retake_do_not_compose(self):
        with patch('novel_h3.comfy.current_takes',return_value=[({},None,self.take)]),patch('novel_h3.media.assemble_chapter') as compose:
            self.assertIsNone(maybe_assemble(self.root,'chapter_s1'));compose.assert_not_called()
    def test_approved_retake_composes(self):
        with patch('novel_h3.comfy.current_takes',return_value=[({},None,dict(self.take,status='approved'))]),patch('novel_h3.media.assemble_chapter') as compose:
            maybe_assemble(self.root,'chapter_s1');compose.assert_called_once_with(self.root,'s1')
    def test_cumulative_requires_each_chapter_current_hash_review(self):
        for section in ['s1','s2']:
            path=self.root/'chapter_videos'/f'chapter_{section}.mp4';path.parent.mkdir(exist_ok=True);path.write_bytes(section.encode());write(path.with_suffix('.json'),{'sha256':file_hash(path),'section':section})
        with patch('novel_h3.media.assemble_latest') as merge:
            p=self.root/'chapter_videos/chapter_s1.mp4';approve_chapter_video(self.root,'s1',file_hash(p));merge.assert_not_called()
            with self.assertRaises(ValueError):approve_chapter_video(self.root,'s2','oldhash')
            p=self.root/'chapter_videos/chapter_s2.mp4';approve_chapter_video(self.root,'s2',file_hash(p));merge.assert_called_once()
    def test_staging_is_shared_across_shots_and_changes_invalidate_contract(self):
        write(self.root/'bible/scene_staging.json',{'locations':{'hall':{'layout':'red columns','characters':{'actor':'left seat'}}}})
        a=contract(self.root,{'id':'a','scene_id':'hall','references':[{'asset_id':'hall'},{'asset_id':'actor'}]})
        b=contract(self.root,{'id':'b','scene_id':'hall','references':[{'asset_id':'hall'},{'asset_id':'actor'}]})
        self.assertEqual(a,b);self.assertIn('<Subject 2>: left seat',a['prompt'])

    def test_real_media_normal_then_retake_then_chapter_review(self):
        import subprocess
        from novel_h3.rework_queue import enqueue,claim,complete
        from novel_h3.comfy import review_take,REVIEW_ITEMS
        from novel_h3.project import load_state,update_state
        source=self.root/'renders/t/video.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=64x64:r=24:d=1','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t','1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],check=True)
        shot={'id':'D1','frames':24,'continuity':'cut','source_ids':['p1'],'dialogue':[]}
        write(self.root/'episodes/chapter_s1.json',{'id':'chapter_s1','shots':[shot]})
        write(self.root/'book.json',{'chapters':[{'id':'s1','kind':'story','title':'测试章','source_number':1,'paragraph_ids':['p1']}]})
        write(self.root/'config.json',{'delivery':{'width':64,'height':64}})
        update_state(self.root,lambda s:s['takes']['t'].update(video_sha256=file_hash(source)))
        def rows(root,ep):
            takes=[t for t in load_state(root)['takes'].values() if not t.get('retired')]
            return [(shot,None,takes[-1] if takes else None)]
        with patch('novel_h3.comfy.current_takes',side_effect=rows):
            finish_shot(self.root,'t')
            receipt=self.root/'chapter_videos/chapter_s1.json'
            self.assertTrue(receipt.with_suffix('.mp4').exists())
            self.assertFalse(read(receipt)['release_approved'])
            self.assertFalse((self.root/'final/latest_full_video.mp4').exists())
            approve_chapter_video(self.root,'s1',read(receipt)['sha256'])
            self.assertTrue((self.root/'final/latest_full_video.mp4').exists())
            replacement=self.root/'renders/new/video.mp4';replacement.parent.mkdir(parents=True);replacement.write_bytes(source.read_bytes())
            enqueue(self.root,load_state(self.root)['takes']['t'],'背景漂移','user');item=claim(self.root)
            self.assertFalse(receipt.exists());self.assertFalse((self.root/'final/latest_full_video.mp4').exists())
            update_state(self.root,lambda s:s['takes'].__setitem__('new',dict(self.take,id='new',video='renders/new/video.mp4',video_sha256=file_hash(replacement))))
            complete(self.root,item['id'],'new');finish_shot(self.root,'new',retake=True)
            self.assertFalse(receipt.exists())
            review_take(self.root,'new',True,'已观看重拍符合要求','user',{k:True for k in REVIEW_ITEMS})
            self.assertTrue(receipt.exists());self.assertFalse(read(receipt)['release_approved'])
            self.assertFalse((self.root/'final/latest_full_video.mp4').exists())
            approve_chapter_video(self.root,'s1',read(receipt)['sha256'])
            self.assertTrue((self.root/'final/latest_full_video.mp4').exists())
