import copy
import subprocess
import tempfile
import unittest
from pathlib import Path

from novel_h3.fastvideo_batch import (
    build_payload, frame_grid_valid, load_spec, prepare_video_reference,
)


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
            'voices': [
                {'asset_id': 'voice_zhang', 'audio': '<Audio 1>', 'subject': '<Subject 1>',
                 'path': 'projects/p/assets/voices/zhang.wav'},
                {'asset_id': 'voice_song', 'audio': '<Audio 2>', 'subject': '<Subject 2>',
                 'path': 'projects/p/assets/voices/song.wav'},
            ],
            'spoken_lines': [
                {'speaker': 'zhang', 'text': '兄台也是来应考的？', 'speaker_subject': '<Subject 1>'},
                {'speaker': 'song', 'text': '长山宋焘。', 'speaker_subject': '<Subject 2>'},
            ],
            'sections': {
                'subject_definitions': '<Subject 1> is Zhang in <Picture 1>.\n'
                                       '<Subject 2> is Song in <Picture 2>.\n'
                                       '<Subject 3> is the hall in <Picture 3>.\n'
                                       '<Audio 1> is the voice reference for <Subject 1> (S1), Zhang.\n'
                                       '<Audio 2> is the voice reference for <Subject 2> (S2), Song.',
                'summary': '[reference generation + audio reference] <Subject 1> and <Subject 2> meet in <Subject 3>.',
                'retention_analysis': '<Subject 1> (appears in [Shot 1]): fully_preserved - Keep him.\n'
                                      '<Subject 2> (appears in [Shot 1]): fully_preserved - Keep him.\n'
                                      '<Subject 3> (appears in [Shot 1]): fully_preserved - Keep it.\n'
                                      '<Audio 1>: partially_copy - Copy timbre only.\n'
                                      '<Audio 2>: partially_copy - Copy timbre only.',
                'detailed_description': 'A period drama in <Subject 3>.\n[Shot 1] <Subject 1> (S1) speaks '
                                        'with <Audio 1>, <d>[Chinese] 兄台也是来应考的？</d> '
                                        '<Subject 2> (S2) speaks with <Audio 2>, '
                                        '<d>[Chinese] 长山宋焘。</d>',
                'overall_soundscape': 'Stone hall reverb and robes.',
                'non_diegetic_music': 'N/A',
            },
        }

    def test_video_reference_is_sent_to_fasth3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = copy.deepcopy(self.spec(root))
            (root / 'projects/p/assets/refs/prev.mp4').write_bytes(b'video')
            spec['videos'] = [{
                'asset_id': 'prev_A12', 'video': '<Video 1>',
                'path': 'projects/p/assets/refs/prev.mp4',
            }]
            spec['sections']['summary'] = spec['sections']['summary'].replace(
                '[reference generation + audio reference]',
                '[video continuation + reference generation + audio reference]')
            spec['sections']['subject_definitions'] += (
                '\n<Video 1> is the final 3 seconds of shot A12, the immediately preceding shot.')
            spec['sections']['retention_analysis'] += (
                '\n<Video 1> (appears in [Shot 1]): partially_preserved - keep the ending state only.')
            spec['sections']['detailed_description'] = spec['sections']['detailed_description'].replace(
                '\n[Shot 1]', '\nThe opening continues from <Video 1>.\n[Shot 1]', 1)
            payload = build_payload(root, spec)
            self.assertEqual(payload['video_reference'][0]['video_url'],
                             str((root / 'projects/p/assets/refs/prev.mp4').resolve()))

    def test_prepare_video_reference_trims_tail_and_drops_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source.mp4'
            subprocess.run(
                ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                 '-f', 'lavfi', '-i', 'testsrc=size=64x64:rate=24', '-t', '2',
                 '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-shortest',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)],
                check=True,
            )
            dest = Path(prepare_video_reference(root, {
                'asset_id': 'prev_A01', 'path': str(source),
                'tail_seconds': 0.5, 'cache_dir': str(root / 'cache'),
            }))
            self.assertTrue(dest.is_file())
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=nw=1:nk=1', str(dest)],
                capture_output=True, text=True, check=True,
            )
            self.assertAlmostEqual(float(probe.stdout.strip()), 0.5, places=2)
            streams = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type',
                 '-of', 'csv=p=0', str(dest)],
                capture_output=True, text=True, check=True,
            ).stdout.split()
            self.assertEqual(streams, ['video'])

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

    def test_unbound_speaker_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = copy.deepcopy(self.spec(root))
            spec['voices'] = []
            spec['sections']['summary'] = spec['sections']['summary'].replace(' + audio reference', '')
            with self.assertRaises(ValueError):
                build_payload(root, spec)

    def test_load_spec_requires_grid_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'A99.json'
            path.write_text('{"shot": "A99", "seed": 1, "frames": 150, "visuals": [], "sections": {}}')
            with self.assertRaisesRegex(ValueError, '17n\\+5'):
                load_spec(path)


if __name__ == '__main__':
    unittest.main()
