import threading
import unittest
from novel_h3.live_progress import LiveProgress


class LiveProgressTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveProgress.__new__(LiveProgress)
        self.live.lock = threading.Lock()
        self.live.current = {}
        self.nodes = {'13': {'class_type': 'SamplerCustomAdvanced'}, '15': {'class_type': 'VAEDecode'}}

    def event(self, kind, **data):
        self.live.event({'type': kind, 'data': data}, 'new', self.nodes)

    def test_intermediate_steps_without_log_newlines(self):
        for step in range(1, 9):
            self.event('progress', prompt_id='new', node='13', value=step, max=8)
            self.assertEqual(self.live.get('new')['steps'], step)

    def test_stale_prompt_and_non_sampler_progress_ignored(self):
        self.event('progress', prompt_id='old', node='13', value=8, max=8)
        self.event('progress', prompt_id='new', node='15', value=2, max=8)
        self.event('executing', node='13')
        self.assertEqual(self.live.get('new'), {})

    def test_decode_replaces_completed_sampling(self):
        self.event('progress', prompt_id='new', node='13', value=8, max=8)
        self.event('executing', prompt_id='new', node='15')
        self.assertIsNone(self.live.get('new')['steps'])
        self.assertEqual(self.live.get('new')['stage'], '解码视频与音频')
        self.assertEqual(self.live.get('other'), {})
