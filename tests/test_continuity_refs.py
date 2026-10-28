import tempfile
import unittest
from pathlib import Path

from novel_h3.continuity_refs import DEFAULT_TAIL_SECONDS, continuation_ref, missing_continuations


class ContinuityRefTests(unittest.TestCase):
    def test_same_section_uses_previous_take_tail(self):
        previous = {'id': 'S01A1', 'close_state': 'Xu sits on the boat.'}
        ref = continuation_ref(previous, 'S01', 'S01', Path('/tmp/takes'))
        self.assertIsNotNone(ref)
        self.assertEqual(ref.asset_id, 'S01A1')
        self.assertEqual(ref.task_type, 'video continuation')
        self.assertEqual(ref.tail_seconds, DEFAULT_TAIL_SECONDS)
        self.assertTrue(ref.path.endswith('takes/S01A1/native.mp4'))
        self.assertIn('Xu sits on the boat.', ref.definition)

    def test_section_jump_has_no_reference(self):
        previous = {'id': 'S03F2', 'close_state': 'Dawn on the river.'}
        self.assertIsNone(continuation_ref(previous, 'S03', 'S04', Path('/tmp/takes')))

    def test_first_shot_has_no_reference(self):
        self.assertIsNone(continuation_ref(None, None, 'S01', Path('/tmp/takes')))

    def test_audit_flags_missing_continuations(self):
        entries = [
            {'id': 'A', 'section': 'S01', 'videos': []},
            {'id': 'B', 'section': 'S01', 'videos': [{'asset_id': 'A'}]},
            {'id': 'C', 'section': 'S02', 'videos': []},
            {'id': 'D', 'section': 'S02'},
        ]
        self.assertEqual(missing_continuations(entries), ['D'])


if __name__ == '__main__':
    unittest.main()
