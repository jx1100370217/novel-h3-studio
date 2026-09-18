import unittest
from unittest.mock import patch
from pathlib import Path

from novel_h3.video_control import require_ready


class TaskControlTests(unittest.TestCase):
    def test_video_denied_when_current_chapter_is_not_ready(self):
        blockers = [{'reason': 'image_review_pending', 'asset': 'character_1'}]
        with patch('novel_h3.video_control.next_pending_episode', return_value='chapter_s0003'), \
             patch('start_next_chapter_when_ready._chapter_requirements', return_value=(None, None, blockers, set(), set())):
            with self.assertRaisesRegex(ValueError, '当前待生成章节 chapter_s0003'):
                require_ready(Path('/unused'))

    def test_video_allowed_when_current_chapter_is_ready_even_if_book_is_incomplete(self):
        with patch('novel_h3.video_control.next_pending_episode', return_value='chapter_s0003'), \
             patch('start_next_chapter_when_ready._chapter_requirements', return_value=(None, None, [], set(), set())), \
             patch('novel_h3.preparation_progress.summary', return_value={'ready_to_generate': False}):
            self.assertEqual(require_ready(Path('/unused')), 'chapter_s0003')
