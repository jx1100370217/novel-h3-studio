from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

import numpy as np
import soundfile as sf

from novel_h3.media import probe
from novel_h3.project import file_hash, read, write
from novel_h3.v2.edit import export_review


class CinemaEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.create_take('a', 0, 440, 660)
        self.create_take('b', 2, 1100, 1300)
        self.timeline = {'fps': 24, 'tracks': [{'kind': 'av', 'segments': [
            {'take_dir': 'a', 'source_in_frame': 12, 'source_out_frame': 36,
             'audio_take_dir': 'b', 'audio_in_frame': 24},
            {'take_dir': 'b', 'source_in_frame': 0, 'source_out_frame': 12,
             'audio_take_dir': 'a', 'audio_in_frame': 0}]}],
            'subtitles': [{'start_frame': 0, 'end_frame': 24, 'text': '审核对白'}]}

    def create_take(self, name, channel, left_frequency, right_frequency):
        folder = self.root / name
        folder.mkdir()
        rate = 32000
        t = np.arange(rate * 2) / rate
        audio = np.column_stack((.1 * np.sin(2 * np.pi * left_frequency * t * np.where(t < 1, 1, 2)),
                                 .1 * np.sin(2 * np.pi * right_frequency * t * np.where(t < 1, 1, 2))))
        sf.write(folder / 'native_audio.flac', audio, rate, subtype='PCM_24')
        frames = np.zeros((48, 32, 32, 3), dtype=np.uint8)
        for index in range(48):
            frames[index, :, :, channel] = 40 + index * 3
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24',
                        '-video_size', '32x32', '-framerate', '24', '-i', 'pipe:0',
                        '-i', str(folder / 'native_audio.flac'), '-c:v', 'libx264', '-threads', '1', '-crf', '0',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(folder / 'native.mp4')],
                       input=frames.tobytes(), check=True, capture_output=True)
        write(folder / 'take.json', {'id': name, 'technical_qc': {'passed': True},
                                     'video_sha256': file_hash(folder / 'native.mp4'),
                                     'native_audio_sha256': file_hash(folder / 'native_audio.flac')})

    def test_cross_source_picture_audio_ranges_are_exact_and_immutable(self):
        originals = {str(p): file_hash(p) for name in ('a', 'b') for p in (self.root / name).iterdir()}
        manifest = export_review(self.root, self.timeline)
        self.assertEqual(manifest['frames'], 36)
        self.assertFalse(manifest['release_approved'])
        self.assertFalse(manifest['human_listened'])
        self.assertEqual(manifest['av_sync_review']['status'], 'not_evaluated')
        self.assertFalse(manifest['audio']['per_shot_normalization'])
        self.assertFalse(manifest['audio']['final_loudnorm'])
        video = self.root / manifest['video']
        streams = probe(video)['streams']
        image_stream = next(s for s in streams if s['codec_type'] == 'video')
        audio_stream = next(s for s in streams if s['codec_type'] == 'audio')
        self.assertEqual(int(image_stream['nb_frames']), 36)
        self.assertEqual(audio_stream['sample_rate'], '48000')
        self.assertEqual(audio_stream['channels'], 2)
        rgb = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:v:0',
                                       '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
        frames = np.frombuffer(rgb, dtype=np.uint8).reshape(-1, 32, 32, 3)
        self.assertAlmostEqual(float(frames[0, :, :, 0].mean()), 76, delta=5)
        self.assertLess(float(frames[0, :, :, 2].mean()), 5)
        self.assertAlmostEqual(float(frames[24, :, :, 2].mean()), 40, delta=5)
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:a:0',
                                       '-f', 'f32le', 'pipe:1'])
        samples = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2)
        for start, end, frequencies in ((.1, .9, (2200, 2600)), (1.05, 1.45, (440, 660))):
            section = samples[int(start * 48000):int(end * 48000)]
            bins = np.fft.rfftfreq(len(section), 1 / 48000)
            spectrum = np.abs(np.fft.rfft(section, axis=0))
            for channel, frequency in enumerate(frequencies):
                self.assertAlmostEqual(bins[spectrum[:, channel].argmax()], frequency, delta=3)
        for path, before in originals.items():
            self.assertEqual(file_hash(Path(path)), before)
        self.assertIn('00:00:00,000 --> 00:00:01,000', (self.root / manifest['subtitles']).read_text())
        self.assertEqual(export_review(self.root, self.timeline), manifest)
        changed = deepcopy(self.timeline)
        changed['subtitles'][0]['text'] = '另一个审阅版本'
        second = export_review(self.root, changed)
        self.assertNotEqual(manifest['output_dir'], second['output_dir'])
        self.assertTrue(video.is_file())

    def test_invalid_ranges_and_fractional_frames_are_rejected(self):
        cases = [('source_out_frame', 49), ('source_out_frame', 12), ('audio_in_frame', 40),
                 ('source_in_frame', -1), ('source_in_frame', 0.5), ('source_in_frame', True)]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                timeline = deepcopy(self.timeline)
                timeline['tracks'][0]['segments'][0][field] = value
                with self.assertRaises(ValueError):
                    export_review(self.root, timeline)
        self.assertFalse((self.root / 'review_exports').exists())

    def test_required_visible_text_is_burned_only_inside_its_frame_window(self):
        timeline = deepcopy(self.timeline)
        baseline = export_review(self.root, timeline)
        timeline['typography'] = [{'id': 'source_text', 'text': '字', 'lines': ['字'],
            'start_frame': 6, 'end_frame': 18, 'box_xywh': [0, 0, 1, 1],
            'font_file': '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc',
            'font_size_fraction_of_frame_height': .5, 'color': '#FFFFFF'}]
        rendered = export_review(self.root, timeline)
        def frames(manifest):
            raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(self.root / manifest['video']),
                '-map', '0:v:0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'])
            return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 32, 32, 3).astype(float)
        difference = np.abs(frames(rendered) - frames(baseline)).mean(axis=(1, 2, 3))
        self.assertGreater(difference[10], 5)
        self.assertLess(difference[3], 2)
        self.assertLess(difference[22], 2)
        self.assertEqual(rendered['frames'], 36)
        self.assertFalse(rendered['release_approved'])
        self.assertEqual(rendered['typography'][0]['text'], '字')
        self.assertTrue((self.root / rendered['typography'][0]['path']).is_file())

    def test_h3_audio_vae_rounding_pads_only_the_small_native_tail(self):
        folder = self.root / 'a'
        samples, rate = sf.read(folder / 'native_audio.flac', always_2d=True)
        sf.write(folder / 'native_audio.flac', samples[:-266], rate, subtype='PCM_24')
        receipt = read(folder / 'take.json')
        receipt.update(audio_route='h3_native_joint', native_audio_sha256=file_hash(folder / 'native_audio.flac'))
        write(folder / 'take.json', receipt)
        before = file_hash(folder / 'native_audio.flac')
        timeline = {'fps': 24, 'tracks': [{'kind': 'av', 'segments': [
            {'take_dir': 'a', 'source_in_frame': 0, 'source_out_frame': 48}]}]}
        result = export_review(self.root, timeline)
        self.assertEqual(result['frames'], 48)
        self.assertAlmostEqual(result['segments'][0]['audio_tail_padding_seconds'], 266 / rate)
        self.assertEqual(file_hash(folder / 'native_audio.flac'), before)
        sf.write(folder / 'native_audio.flac', samples[:-640], rate, subtype='PCM_24')
        receipt['native_audio_sha256'] = file_hash(folder / 'native_audio.flac')
        write(folder / 'take.json', receipt)
        with self.assertRaisesRegex(ValueError, 'native audio duration'):
            export_review(self.root, timeline)

    def test_changed_audio_or_video_hash_is_rejected(self):
        for filename in ('native.mp4', 'native_audio.flac'):
            with self.subTest(filename=filename):
                path = self.root / 'a' / filename
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    export_review(self.root, self.timeline)
                path.write_bytes(original)

    def test_failed_qc_and_project_escape_are_rejected(self):
        receipt_path = self.root / 'a/take.json'
        receipt = read(receipt_path)
        receipt['technical_qc']['passed'] = False
        write(receipt_path, receipt)
        with self.assertRaisesRegex(ValueError, 'technical QC'):
            export_review(self.root, self.timeline)
        timeline = deepcopy(self.timeline)
        timeline['tracks'][0]['segments'][0]['take_dir'] = '../outside'
        with self.assertRaises(ValueError):
            export_review(self.root, timeline)

    def test_optional_loudnorm_is_final_mix_only(self):
        timeline = deepcopy(self.timeline)
        timeline['final_loudnorm'] = True
        result = export_review(self.root, timeline)
        self.assertTrue(result['technical_qc']['passed'])
        self.assertTrue(result['audio']['final_loudnorm'])
        self.assertFalse(result['audio']['per_shot_normalization'])
        self.assertEqual(result['frames'], 36)

    def test_non_round_frame_cuts_keep_integer_frame_timeline(self):
        timeline = {'fps': 24, 'tracks': [{'kind': 'av', 'segments': [
            {'take_dir': 'a', 'source_in_frame': 0, 'source_out_frame': 5},
            {'take_dir': 'b', 'source_in_frame': 1, 'source_out_frame': 8},
            {'take_dir': 'a', 'source_in_frame': 9, 'source_out_frame': 20}]}]}
        result = export_review(self.root, timeline)
        self.assertEqual(result['frames'], 23)
        self.assertEqual(result['technical_qc']['frames'], 23)
        self.assertTrue(result['technical_qc']['passed'])


if __name__ == '__main__':
    unittest.main()
