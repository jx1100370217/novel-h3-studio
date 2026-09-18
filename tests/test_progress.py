import json
import unittest
from unittest.mock import patch

from novel_h3.progress import _live_comfy_text, parse_sampling_progress


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


if __name__ == '__main__':
    unittest.main()
