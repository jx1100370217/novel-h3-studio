import tempfile
import unittest
from pathlib import Path

from novel_h3.project import write
from novel_h3.v2.chapter_edit import chapter_timeline


class ChapterEditTests(unittest.TestCase):
    def test_time_caption_constraint_reads_vad_dictionary_timestamps(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / 'production_v2/chapter/plan.json'
            blueprint = plan.with_name('blueprint.json')
            write(plan, {'shots': [{'id': 'S506', 'spoken_lines': [{'text': '娘，您睡了多久？'}]}],
                         'typography_cues': [{'id': 'half_day', 'shot_id': 'S506', 'start_seconds': 0,
                                              'end_seconds': 2, 'text': '半日后'}]})
            write(blueprint, {'entries': [{'shot_id': 'S506', 'retain_entire_source': True,
                                          'speech_start_constraint': {'must_follow_cue_id': 'half_day',
                                                                      'minimum_gap_seconds': .2}}]})
            take = plan.parent / 'takes/selected/take.json'
            receipt = {'technical_qc': {'frames': 168}, 'speech_screening': {'passed': True,
                       'speech_gate': {'speech_segments': [{'start': 3.3, 'end': 6.8}]}}}
            write(take, receipt)
            result = chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)
            self.assertEqual(result['typography'][0]['end_frame'], 48)
            self.assertEqual(result['subtitles'][0]['start_frame'], 79)
            self.assertFalse(result['release_approved'])
            receipt['speech_screening']['speech_gate']['speech_segments'][0]['start'] = 2.1
            write(take, receipt)
            with self.assertRaisesRegex(ValueError, 'clean dialogue handle'):
                chapter_timeline(root, plan, {'S506': 'selected'}, blueprint)


if __name__ == '__main__': unittest.main()
