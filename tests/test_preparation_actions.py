import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from novel_h3.project import write, read
from novel_h3.regeneration import enqueue, tasks
from continue_preparation import _write_candidate

class PreparationActions(unittest.TestCase):
    def test_repeated_image_clicks_deduplicate_without_claiming_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            write(root/'state.json',{'assets':{},'takes':{}})
            write(root/'jobs/image_prop.json',{'id':'prop'})
            with patch('novel_h3.regeneration.threading.Thread'):
                one=enqueue(root,'image','prop')
                two=enqueue(root,'image','prop')
            self.assertEqual(one['id'],two['id'])
            self.assertEqual(len(tasks(root)),1)
            self.assertEqual(tasks(root)[0]['status'],'queued')

    def test_long_text_splits_without_truncating_or_falsely_capping_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            text='山间风起，众人沿着山路前行。'*18
            out=Path(tmp)
            _write_candidate({'id':'s0001','title':'测试'},[{'id':'s0001_p0001','text':text}],{}, {},out)
            scenes=read(out/'s0001.json')['scenes']
            self.assertEqual(''.join(s['source_text'] for s in scenes),text)
            self.assertTrue(all(s['duration_seconds']<=15 for s in scenes))
            self.assertGreater(len(scenes),1)
            _write_candidate({'id':'s0002'},[{'id':'s0002_p0001','text':'字'*100}],{}, {},out)
            long=read(out/'s0002.json')['scenes'][0]
            self.assertTrue(long['timing']['requires_split'])
            self.assertGreater(long['duration_seconds'],15)
