import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from audio_review import decode_audio, windows, parse_semantics, SAMPLE_RATE
from novel_h3.listening import start_audio
from novel_h3.project import write


class AudioReviewTests(unittest.TestCase):
    def test_decoder_reads_real_audio_and_rejects_silent_video(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            wav = root / 'sound.wav'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.3', str(wav)], check=True)
            result = decode_audio(wav, root / 'decoded.wav')
            self.assertEqual(result['selected_track'], '0:a:0')
            self.assertEqual(len(result['sha256']), 64)
            video = root / 'silent.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=64x64:duration=0.1', str(video)], check=True)
            with self.assertRaisesRegex(ValueError, '没有音轨'):
                decode_audio(video, root / 'bad.wav')

    def test_long_audio_keeps_last_partial_window(self):
        spans = list(windows(41 * SAMPLE_RATE + 17))
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], 41 * SAMPLE_RATE + 17)
        self.assertEqual(sum(b-a for a,b in spans), 41 * SAMPLE_RATE + 17)
        self.assertTrue(all(a[1] == b[0] for a,b in zip(spans, spans[1:])))

    def test_model_response_never_executes_or_trusts_invalid_values(self):
        value = {'speech':'no','transcript':'','music':'uncertain','events':['流水声']}
        self.assertEqual(parse_semantics('```json\n'+json.dumps(value)+'\n``` trailing {bad'), value)
        self.assertIsNone(parse_semantics('not JSON'))
        self.assertIsNone(parse_semantics('{"speech":"certain","music":"no"}'))

    @patch('novel_h3.safety.check_paused')
    def test_audio_does_not_release_or_interrupt_running_video(self, _pause):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'source.wav';source.write_bytes(b'fixture')
            write(root/'config.json',{'comfy_url':'http://localhost:8191'})
            with patch('novel_h3.comfy.api',return_value={'queue_running':[1],'queue_pending':[]}) as api, patch('novel_h3.listening.subprocess.Popen') as popen:
                with self.assertRaisesRegex(ValueError,'视频正在生成'):
                    start_audio(root,source)
                self.assertEqual([c.args[1] for c in api.call_args_list],['/queue'])
                popen.assert_not_called()
