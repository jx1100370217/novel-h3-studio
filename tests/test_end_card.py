import subprocess
import tempfile
import unittest
from pathlib import Path

from novel_h3.end_card import PROJECT_CREDIT, build_end_card, render_card_image


class EndCardTests(unittest.TestCase):
    def test_default_credit_is_project_repository(self):
        self.assertEqual(PROJECT_CREDIT, 'https://github.com/jx1100370217/novel-h3-studio')

    def test_card_still_matches_delivery_canvas(self):
        with tempfile.TemporaryDirectory() as tmp:
            still = render_card_image(Path(tmp) / 'end.png', title='王六郎',
                                      source='聊斋志异·蒲松龄', credits=('画面 FastH3-Omni NVFP4 QAD',))
            from PIL import Image
            with Image.open(still) as image:
                self.assertEqual(image.size, (1344, 768))

    def test_card_clip_is_silent_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = build_end_card(Path(tmp) / 'end.mp4', title='王六郎', duration_seconds=1.0)
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height',
                 '-of', 'csv=p=0', str(clip)], capture_output=True, text=True, check=True).stdout
            self.assertIn('1344,768', probe)
            self.assertNotIn('audio', probe)


if __name__ == '__main__':
    unittest.main()
