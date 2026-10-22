from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from novel_h3.character_views import _panel_boundaries


class CharacterViewCropTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed")

    def image(self, folder, width, height, pixel):
        path = Path(folder) / "master.pgm"
        path.write_bytes(f"P5\n{width} {height}\n255\n".encode() +
                         bytes(pixel(x, y) for y in range(height) for x in range(width)))
        return path

    def test_unequal_gutters_win_over_large_portrait_edge(self):
        width, height = 1000, 240
        bands = [(235, 245), (475, 485), (675, 695)]
        def pixel(x, y):
            if any(a <= x < b for a, b in bands):
                return 180
            return 30 + y % 60 + (150 if x >= 775 else 0)
        with tempfile.TemporaryDirectory() as folder:
            path = self.image(folder, width, height, pixel)
            boundaries = _panel_boundaries(path, width, height)
        self.assertEqual(boundaries, [0, 240, 480, 685, 1000])
        self.assertLess(boundaries[3], 750)  # The old 75% window selected the face edge at 775.
        self.assertTrue(all(b - a >= width * .15 for a, b in zip(boundaries, boundaries[1:])))

    def test_discontinuous_single_flat_column_is_not_a_gutter(self):
        width, height = 1000, 240
        def pixel(x, y):
            if x in (280, 520, 780):
                return 60 + (x // 250) * 35
            return 30 + y % 60 + (x // 250) * 35
        with tempfile.TemporaryDirectory() as folder:
            path = self.image(folder, width, height, pixel)
            self.assertEqual(_panel_boundaries(path, width, height), [0, 250, 500, 750, 1000])

    def test_uniform_image_uses_balanced_boundaries(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.image(folder, 1000, 200, lambda x, y: 120)
            self.assertEqual(_panel_boundaries(path, 1000, 200), [0, 250, 500, 750, 1000])

    def test_existing_discontinuity_fallback_and_minimum_width(self):
        width, height = 1000, 240
        def pixel(x, y):
            return 20 + y % 60 + (30 if x >= 300 else 0) + (30 if x >= 440 else 0) + (30 if x >= 750 else 0)
        with tempfile.TemporaryDirectory() as folder:
            path = self.image(folder, width, height, pixel)
            # The recovered gradient seams 300/440/750 make a 140 px panel;
            # retaining the existing 15% minimum must force equal quarters.
            self.assertEqual(_panel_boundaries(path, width, height), [0, 250, 500, 750, 1000])

    def test_real_mother_master_crops_keep_side_and_face_separate(self):
        path = Path("/home/jx/.codex/generated_images/01a10a48-5a3c-7a22-ab72-2b0f1c1f8972/exec-0f640a6d-d83e-40e1-9491-a30da2858f59.png")
        if not path.is_file():
            self.skipTest("The real mother regression fixture is unavailable")
        boundaries = _panel_boundaries(path, 1774, 887)
        self.assertEqual(boundaries, [0, 432, 849, 1214, 1774])
        self.assertTrue(all(b - a >= 1774 * .15 for a, b in zip(boundaries, boundaries[1:])))
        with tempfile.TemporaryDirectory() as folder:
            for name, left, right in zip(("front", "back", "side", "face"), boundaries, boundaries[1:]):
                target = Path(folder) / f"{name}.gray"
                raw = subprocess.check_output([
                    "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
                    "-vf", f"crop={right-left}:887:{left}:0,format=gray", "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "gray", "-"], timeout=60)
                target.write_bytes(raw)
                self.assertEqual(len(raw), (right-left) * 887)
            side = (Path(folder) / "side.gray").read_bytes()
            face = (Path(folder) / "face.gray").read_bytes()
            # Both adjoining edges are actual uniform gutters, not skin/hair.
            for raw, width, edge in ((side, 365, 364), (face, 560, 0)):
                column = raw[edge::width]
                mean = sum(column) / len(column)
                variance = sum(v*v for v in column) / len(column) - mean*mean
                self.assertLess(variance, 4)


if __name__ == "__main__":
    unittest.main()
