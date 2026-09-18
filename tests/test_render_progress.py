import unittest
from pathlib import Path

class RenderContinuationTests(unittest.TestCase):
    def test_cleanup_path_continues_without_fixed_cooldown(self):
        text=Path("render_chapter.py").read_text()
        self.assertIn("AUDIO_CLEANED_CONTINUING", text)
        self.assertIn("time.sleep(0.5)", text)
        self.assertNotIn("time.sleep(20)", text)
        self.assertIn("SPEECH_FAILED_RETAINED_CONTINUING", text)
        self.assertNotIn("SPEECH_FAILED_RETRYING", text)
