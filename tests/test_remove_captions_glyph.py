import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/remove_captions_glyph.py'
spec = importlib.util.spec_from_file_location('remove_captions_glyph', SCRIPT)
cleaner = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(cleaner)
except ModuleNotFoundError as exc:
    if exc.name not in {'cv2', 'numpy', 'PIL', 'simple_lama_inpainting', 'torch'}:
        raise
    cleaner = None


def video_frames(path):
    return int(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
        '-show_entries', 'stream=nb_read_frames', '-of', 'default=nw=1:nk=1', str(path),
    ], text=True).strip())


def audio_hash(path):
    return subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
        '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-',
    ], text=True).strip()


@unittest.skipUnless(cleaner and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'requires the dialogue environment and ffmpeg')
class CaptionCleanupTests(unittest.TestCase):
    def test_preserves_video_when_audio_ends_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'source.mp4'
            output = Path(tmp) / 'clean.mp4'
            subprocess.run([
                'ffmpeg', '-v', 'error', '-y',
                '-f', 'lavfi', '-i', 'color=white:size=160x96:rate=24:duration=2',
                '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source),
            ], check=True)
            args = SimpleNamespace(top_fraction=0.8, threshold=165, saturation=85,
                                   dilate=9, min_pixels=80, crf=16)
            result = cleaner.clean_video(source, output, lambda image, mask: image, args)

            self.assertEqual(result['method'], 'lama_glyph')
            self.assertEqual(video_frames(source), 48)
            self.assertEqual(video_frames(output), video_frames(source))
            self.assertEqual(audio_hash(output), audio_hash(source))


if __name__ == '__main__':
    unittest.main()
