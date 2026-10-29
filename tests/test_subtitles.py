import tempfile
import unittest
from pathlib import Path

from novel_h3.subtitles import _ass_time, shot_cues, write_ass


class CueTimingTests(unittest.TestCase):
    def test_single_line_starts_after_the_lead_in(self):
        shot = {'frames': 158, 'dialogue': '许某：你袖子怎么不湿？'}
        cues = shot_cues(shot)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]['start'], 1.5)
        self.assertEqual(cues[0]['text'], '你袖子怎么不湿？')
        self.assertLessEqual(cues[0]['end'], 158 / 24 - 0.1)

    def test_multiple_lines_are_spread_and_do_not_overlap(self):
        shot = {'frames': 243,
                'dialogue': '许某：第一句。\n王六郎（低声）：第二句。\n许某：第三句。'}
        cues = shot_cues(shot)
        self.assertEqual([c['text'] for c in cues], ['第一句。', '第二句。', '第三句。'])
        for earlier, later in zip(cues, cues[1:]):
            self.assertLess(earlier['end'], later['start'])

    def test_skip_lines_keeps_only_the_uncaptioned_line(self):
        shot = {'frames': 311, 'dialogue': '许某：第一句。\n王六郎：第二句。'}
        cues = shot_cues(shot, timing=[[1.0, 2.0], [5.0, 6.0]], skip_lines=(1,))
        self.assertEqual([c['text'] for c in cues], ['第一句。'])
        self.assertEqual(cues[0]['start'], 1.0)

    def test_lines_without_speaker_prefix_are_ignored(self):
        self.assertEqual(shot_cues({'frames': 124, 'dialogue': '（无对白）'}), [])


class AssOutputTests(unittest.TestCase):
    def test_ass_time_format(self):
        self.assertEqual(_ass_time(0), '0:00:00.00')
        self.assertEqual(_ass_time(1.5), '0:00:01.50')
        self.assertEqual(_ass_time(3661.25), '1:01:01.25')

    def test_write_ass_contains_cue_and_escapes_braces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_ass([{'start': 1.0, 'end': 2.0, 'text': '你好{世界}'}],
                             Path(tmp) / 'x.ass', width=1344, height=768)
            body = path.read_text(encoding='utf-8')
        self.assertIn('PlayResX: 1344', body)
        self.assertIn('Dialogue: 0,0:00:01.00,0:00:02.00,Dialogue,,0,0,0,,你好（世界）', body)


if __name__ == '__main__':
    unittest.main()
