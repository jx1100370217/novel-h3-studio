import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3.progress import (
    _live_comfy_text,
    _prefer_websocket_progress,
    parse_sampling_progress,
)


class ProgressParserTests(unittest.TestCase):
    def test_parses_tqdm_progress_with_ansi_and_carriage_returns(self):
        text = '\x1b[32m 0%| | 0/8 [00:00<?, ?it/s, Model Initializing ... ]\r'
        text += ' 38%| | 3/8 [01:12<00:30, 6.0s/it]\r'
        self.assertEqual(parse_sampling_progress(text, 8), (3, True))

    def test_parses_prose_progress(self):
        self.assertEqual(parse_sampling_progress('Sampling step 4 of 8', 8), (4, False))

    def test_does_not_treat_latent_step_count_as_sampler_progress(self):
        self.assertEqual(parse_sampling_progress('audio 24 frames -> 40 latent steps', 8), (None, False))

    @patch('novel_h3.progress.subprocess.run')
    def test_decodes_journald_blob_messages(self, run):
        payload = json.dumps({'MESSAGE': list(' 3/8 [sampling]'.encode())})
        run.return_value.returncode = 0
        run.return_value.stdout = payload + '\n'
        # Future timestamp excludes the unrelated file-log fallback.
        text, source = _live_comfy_text({'created_at': 9999999999})
        self.assertEqual(source, 'journal')
        self.assertEqual(parse_sampling_progress(text, 8)[0], 3)

    @patch('novel_h3.progress.subprocess.run')
    def test_reads_latest_sampling_progress_from_workbench_comfy_log(self, run):
        run.return_value.returncode = 1
        run.return_value.stdout = ''
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log = root / 'runtime' / 'liaozhai_comfy_start.log'
            log.parent.mkdir()
            log.write_text('got prompt\n20/20 [done]\ngot prompt\n12/20 [sampling]\n')
            with patch('novel_h3.progress.REPO', root):
                text, source = _live_comfy_text({'created_at': time.time() - 1})
        self.assertEqual(source, 'file')
        self.assertEqual(parse_sampling_progress(text, 20)[0], 12)

    def test_stale_websocket_wait_does_not_replace_newer_log_step(self):
        self.assertFalse(_prefer_websocket_progress(12, {
            'steps': None, 'stage': '已连接，等待实时进度',
        }))
        self.assertTrue(_prefer_websocket_progress(12, {
            'steps': 13, 'stage': '采样',
        }))
        self.assertTrue(_prefer_websocket_progress(20, {
            'steps': None, 'stage': '解码视频与音频',
        }))


if __name__ == '__main__':
    unittest.main()
