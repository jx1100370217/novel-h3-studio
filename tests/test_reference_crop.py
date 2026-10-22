import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from novel_h3.comfy import generation_reference
from novel_h3.project import file_hash, read, write


def fixture_png(path, red=30):
    def chunk(kind, data):
        return (struct.pack('>I', len(data)) + kind + data
                + struct.pack('>I', zlib.crc32(kind + data)))
    pixels = b''.join(b'\x00' + bytes([red, y * 10, 100]) * 12 for y in range(10))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'
                     + chunk(b'IHDR', struct.pack('>IIBBBBB', 12, 10, 8, 2, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


class ReviewedSceneCropTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'scene.png'
        fixture_png(self.source)
        self.source_hash = file_hash(self.source)
        write(self.root / 'config.json', {})
        write(self.root / 'bible/assets.json', {
            'characters': {}, 'scenes': {'Hall': {
                'id': 'hall', 'generation_crop': {
                    'source_sha256': self.source_hash, 'box': [1, 2, 9, 8],
                    'reason': 'Exclude an unintended human-shaped statue at the right edge.',
                }}},
        })
        self.asset = patch('novel_h3.comfy.asset_for',
                           side_effect=lambda root, asset_id: (self.source, file_hash(self.source)))
        self.asset.start()
        self.addCleanup(self.asset.stop)

    def test_cpu_crop_has_reviewed_dimensions_and_preserves_original(self):
        with patch('novel_h3.comfy.subprocess.run', wraps=subprocess.run) as run:
            result = generation_reference(self.root, {'asset_id': 'hall'})
        cropped = self.root / result['generation_path']
        self.assertEqual(struct.unpack('>II', cropped.read_bytes()[16:24]), (8, 6))
        self.assertEqual(result['variant'], 'reviewed_scene_crop')
        self.assertEqual(result['crop_box'], [1, 2, 9, 8])
        self.assertEqual(result['source_sha256'], self.source_hash)
        self.assertEqual(result['generation_sha256'], file_hash(cropped))
        self.assertEqual(file_hash(self.source), self.source_hash)
        command = next(call.args[0] for call in run.call_args_list if call.args[0][0] == 'ffmpeg')
        self.assertEqual(command[command.index('-hwaccel') + 1], 'none')
        self.assertNotEqual(cropped, self.source)
        self.assertEqual(generation_reference(self.root, {'asset_id': 'hall'}), result)

    def test_changed_source_invalidates_the_reviewed_crop(self):
        fixture_png(self.source, red=40)
        with patch('novel_h3.comfy.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, '(?i)source hash'):
                generation_reference(self.root, {'asset_id': 'hall'})
            run.assert_not_called()
        self.assertFalse((self.root / 'assets/video_refs').exists())

    def test_invalid_crop_box_is_rejected_before_derivative_is_created(self):
        inventory_path = self.root / 'bible/assets.json'
        inventory = read(inventory_path)
        for box in ([-1, 0, 9, 8], [0, 0, 13, 8], [4, 0, 3, 8],
                    [0, 2, 9, 2], [True, 2, 9, 8], [1.5, 2, 9, 8], [1, 2, 9]):
            with self.subTest(box=box):
                inventory['scenes']['Hall']['generation_crop']['box'] = box
                write(inventory_path, inventory)
                with self.assertRaisesRegex(ValueError, '(?i)box'):
                    generation_reference(self.root, {'asset_id': 'hall'})
                self.assertFalse((self.root / 'assets/video_refs').exists())


if __name__ == '__main__':
    unittest.main()
