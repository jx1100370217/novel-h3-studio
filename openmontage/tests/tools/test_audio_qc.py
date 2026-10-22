import json
import tempfile
import unittest
from pathlib import Path

from tools.audio.audio_qc import check_timeline


class AudioQCTests(unittest.TestCase):
    def setUp(self):
        self.script = {
            'sections': [{'shots': ['S1', 'S2']}],
            'shot_durations': {'S1': 5.0, 'S2': 5.0},
        }

    def test_good_native_and_tts_timeline_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'S2').mkdir()
            (root / 'S2/native.mp4').write_bytes(b'x')
            tts = root / 'n.wav'
            tts.write_bytes(b'x')
            lines = [
                {'id': 'N1', 'role': 'narrator', 'shot': 'S1', 'offset': 0.5, 'wav': str(tts), 'role_gender': 'male'},
                {'id': 'S1line', 'role': 'songtao', 'shot': 'S2', 'offset': 0.5, 'source': 'native'},
            ]
            report = check_timeline(self.script, lines, native_root=root,
                                    duration_fn=lambda p: 2.0, f0_fn=lambda p: 120.0)
            self.assertEqual(report['status'], 'pass', report['issues'])

    def test_out_of_order_line_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'S1').mkdir()
            (root / 'S1/native.mp4').write_bytes(b'x')
            (root / 'S2').mkdir()
            (root / 'S2/native.mp4').write_bytes(b'x')
            lines = [
                {'id': 'late', 'role': 'songtao', 'shot': 'S2', 'offset': 0.5, 'source': 'native'},
                {'id': 'early', 'role': 'zhang', 'shot': 'S1', 'offset': 1.0, 'source': 'native'},
            ]
            report = check_timeline(self.script, lines, native_root=root,
                                    duration_fn=lambda p: 1.0, f0_fn=lambda p: 120.0)
            self.assertTrue(any('order:' in i for i in report['issues']), report['issues'])

    def test_tts_overflow_and_low_female_f0_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tts = root / 'n.wav'
            tts.write_bytes(b'x')
            lines = [{'id': 'M1', 'role': 'mother', 'shot': 'S1', 'offset': 4.5, 'source': 'tts', 'wav': str(tts), 'role_gender': 'female'}]
            report = check_timeline(self.script, lines, native_root=root,
                                    duration_fn=lambda p: 2.0, f0_fn=lambda p: 120.0)
            self.assertTrue(any('beyond' in i for i in report['issues']), report['issues'])
            self.assertTrue(any('F0' in i for i in report['issues']), report['issues'])

    def test_missing_native_take_is_flagged(self):
        lines = [{'id': 'S1line', 'role': 'songtao', 'shot': 'S2', 'offset': 0.5, 'source': 'native'}]
        report = check_timeline(self.script, lines, native_root=Path('/nonexistent'),
                                duration_fn=lambda p: 1.0, f0_fn=lambda p: 120.0)
        self.assertTrue(any('native H3 take missing' in i for i in report['issues']), report['issues'])


if __name__ == '__main__':
    unittest.main()
