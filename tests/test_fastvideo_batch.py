import copy
import tempfile
import unittest
from pathlib import Path

from novel_h3.fastvideo_batch import build_payload, frame_grid_valid, load_spec


class FastVideoBatchTests(unittest.TestCase):
    def spec(self, root: Path):
        (root / 'projects/p/assets/refs').mkdir(parents=True, exist_ok=True)
        for name in ('zhang.png', 'song.png', 'hall.png'):
            (root / 'projects/p/assets/refs' / name).write_bytes(b'x')
        return {
            'shot': 'A13', 'seed': 1, 'frames': 158,
            'visuals': [
                {'asset_id': 'zhang', 'subject': '<Subject 1>', 'picture': '<Picture 1>',
                 'kind': 'character', 'instances': 1, 'visible': True,
                 'generation_path': 'projects/p/assets/refs/zhang.png'},
                {'asset_id': 'song', 'subject': '<Subject 2>', 'picture': '<Picture 2>',
                 'kind': 'character', 'instances': 1, 'visible': True,
                 'generation_path': 'projects/p/assets/refs/song.png'},
                {'asset_id': 'hall', 'subject': '<Subject 3>', 'picture': '<Picture 3>',
                 'kind': 'scene', 'visible': True,
                 'generation_path': 'projects/p/assets/refs/hall.png'},
            ],
            'voices': [],
            'spoken_lines': [
                {'speaker': 'zhang', 'text': '兄台也是来应考的？', 'speaker_subject': '<Subject 1>'},
                {'speaker': 'song', 'text': '长山宋焘。', 'speaker_subject': '<Subject 2>'},
            ],
            'sections': {
                'subject_definitions': '<Subject 1> is Zhang in <Picture 1>.\n'
                                       '<Subject 2> is Song in <Picture 2>.\n'
                                       '<Subject 3> is the hall in <Picture 3>.',
                'summary': '[reference generation] <Subject 1> and <Subject 2> meet in <Subject 3>.',
                'retention_analysis': '<Subject 1> (appears in [Shot 1]): fully_preserved - Keep him.\n'
                                      '<Subject 2> (appears in [Shot 1]): fully_preserved - Keep him.\n'
                                      '<Subject 3> (appears in [Shot 1]): fully_preserved - Keep it.',
                'detailed_description': 'A period drama in <Subject 3>.\n[Shot 1] <Subject 1> (S1) asks '
                                        '<d>[Chinese] 兄台也是来应考的？</d> <Subject 2> (S2) answers '
                                        '<d>[Chinese] 长山宋焘。</d>',
                'overall_soundscape': 'Stone hall reverb and robes.',
                'non_diegetic_music': 'N/A',
            },
        }

    def test_frame_grid(self):
        self.assertTrue(frame_grid_valid(124))
        self.assertTrue(frame_grid_valid(158))
        self.assertFalse(frame_grid_valid(150))

    def test_multi_speaker_strict_ref2va_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = self.spec(root)
            payload = build_payload(root, spec)
            self.assertEqual(payload['width'], 1344)
            self.assertEqual(payload['height'], 768)
            self.assertEqual(payload['num_frames'], 158)
            self.assertIn('<d>[Chinese] 兄台也是来应考的？</d>', payload['prompt'])
            self.assertIn('<d>[Chinese] 长山宋焘。</d>', payload['prompt'])
            self.assertIn('Visible population: exactly 2 people', payload['prompt'])

    def test_resolution_override_is_respected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = build_payload(root, self.spec(root), width=1024, height=576)
            self.assertEqual((payload['width'], payload['height']), (1024, 576))

    def test_chinese_outside_dialogue_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = self.spec(root)
            spec = copy.deepcopy(spec)
            spec['sections']['summary'] += ' 他说话。'
            with self.assertRaisesRegex(ValueError, 'English'):
                build_payload(root, spec)

    def test_population_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = copy.deepcopy(self.spec(root))
            spec['visuals'][0]['kind'] = None
            with self.assertRaisesRegex(ValueError, 'population metadata'):
                build_payload(root, spec)

    def test_load_spec_requires_grid_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'A99.json'
            path.write_text('{"shot": "A99", "seed": 1, "frames": 150, "visuals": [], "sections": {}}')
            with self.assertRaisesRegex(ValueError, '17n\\+5'):
                load_spec(path)


if __name__ == '__main__':
    unittest.main()
