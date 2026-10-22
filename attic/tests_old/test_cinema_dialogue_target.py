import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare_dialogue_target.py'
spec = importlib.util.spec_from_file_location('cinema_dialogue_target', SCRIPT)
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


class CinemaDialogueTargetTests(unittest.TestCase):
    def prepare_fixture(self, shot_id='P03', bank_changes=None, lines=None):
        plan = {'shots': [
            {'id': 'P03', 'spoken_lines': [{'speaker': 'song', 'text': '这份恩典，我不敢推辞。'}]},
            {'id': 'P06', 'spoken_lines': [{'speaker': 'clerk', 'text': '她还能活九年。'}]},
            {'id': 'P02', 'spoken_lines': []},
        ]}
        bank = {name: {'asset_id': asset, 'path': f'voices/{asset}.wav', 'sha256': 'sha',
                       'approved': True, 'strict_asr_passed': True, 'transcript': f'{name}的既有参考文字。'}
                for name, asset in [('宋焘', 'song'), ('长须吏', 'clerk')]}
        if bank_changes:
            bank['宋焘'].update(bank_changes)
        if lines is not None:
            plan['shots'][0]['spoken_lines'] = lines
        with patch.object(target, 'read', side_effect=[plan, bank]), \
             patch.object(target, 'file_hash', return_value='sha'), \
             patch.object(Path, 'is_file', return_value=True):
            return target.prepare(123) if shot_id is None else target.prepare(123, shot_id)

    def test_default_p03_keeps_exact_text_and_original_reference(self):
        prepared = self.prepare_fixture(shot_id=None)
        self.assertEqual(prepared['shot_id'], 'P03')
        self.assertEqual(prepared['speaker_asset_id'], 'song')
        self.assertEqual(prepared['expected_text'], '这份恩典，我不敢推辞。')
        self.assertEqual(prepared['source_reference']['path'], 'voices/song.wav')
        self.assertEqual(prepared['seed'], 123)
        self.assertFalse(prepared['human_listened'])

    def test_selected_shot_uses_its_registered_voice_not_song_tao(self):
        prepared = self.prepare_fixture('P06')
        self.assertEqual(prepared['shot_id'], 'P06')
        self.assertEqual(prepared['speaker_asset_id'], 'clerk')
        self.assertEqual(prepared['expected_text'], '她还能活九年。')
        self.assertEqual(prepared['source_reference']['path'], 'voices/clerk.wav')
        self.assertEqual(prepared['source_reference']['transcript'], '长须吏的既有参考文字。')

    def test_silent_unknown_and_multiple_speakers_are_rejected(self):
        for shot in ['P02', 'P99']:
            with self.subTest(shot=shot), self.assertRaises(ValueError):
                self.prepare_fixture(shot)
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            self.prepare_fixture(lines=[{'speaker': 'song', 'text': '请等等。'}, {'speaker': 'clerk', 'text': '好。'}])

    def test_unapproved_or_unverified_reference_is_rejected(self):
        for changes in [{'approved': False}, {'strict_asr_passed': False}, {'strict_asr_passed': None}, {'transcript': ''}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare_fixture(bank_changes=changes)

    def test_multiple_lines_from_same_speaker_keep_original_order(self):
        prepared = self.prepare_fixture(lines=[{'speaker': 'song', 'text': '请等等。'}, {'speaker': 'song', 'text': '我还有话要说。'}])
        self.assertEqual(prepared['expected_text'], '请等等。我还有话要说。')

    def test_prepare_retains_authored_s506_lead_and_default_minimum(self):
        prepared = self.prepare_fixture(lines=[{'speaker': 'song', 'text': '娘，帮我问问长山。', 'start_seconds': 2.6}])
        self.assertEqual(prepared['lead_seconds'], 2.6)
        self.assertEqual(self.prepare_fixture()['lead_seconds'], 0.5)
        early = self.prepare_fixture(lines=[{'speaker': 'song', 'text': '等一等。', 'start_seconds': 0.1}])
        self.assertEqual(early['lead_seconds'], 0.5)

    def test_natural_duration_drives_legal_h3_frame_count(self):
        for seconds in [0.6, 4.2, 8.48, 12.5]:
            frames = target.choose_frames(seconds)
            self.assertEqual(frames % 17, 5)
            self.assertGreaterEqual(frames / 24, max(4, seconds + 1.5))
            self.assertLessEqual(frames / 24, 15)
        for seconds in [0, -1, float('nan'), float('inf'), 14.0]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                target.choose_frames(seconds)

    def test_authored_action_handles_survive_short_dialogue(self):
        import numpy as np
        audio, timing = target.pad_target_audio(np.zeros(32000, dtype=np.float32), 32000, min_seconds=11)
        self.assertGreaterEqual(timing['generated_clip_seconds'], 11)
        self.assertEqual(timing['speech_end_sample_exclusive'], 48000)
        self.assertGreater(len(audio) / 32000, timing['editorial_handles']['speech_plus_tail_seconds'])
        self.assertTrue(timing['editorial_handles']['full_padded_duration_is_not_required_edit_length'])
        self.assertEqual(target.choose_frames(12.8, min_seconds=14), 345)
        with self.assertRaisesRegex(ValueError, 'never accelerate'):
            target.choose_frames(12.9, min_seconds=14)

    def test_padding_keeps_every_original_sample_and_duplicates_stereo(self):
        import numpy as np
        raw = np.linspace(-0.3, 0.3, 32000, dtype=np.float32)
        audio, timing = target.pad_target_audio(raw, 32000)
        start, end = timing['speech_start_sample'], timing['speech_end_sample_exclusive']
        np.testing.assert_array_equal(audio[start:end, 0], raw)
        np.testing.assert_array_equal(audio[:, 0], audio[:, 1])
        self.assertTrue(np.all(audio[:start] == 0))
        self.assertTrue(np.all(audio[end:] == 0))
        self.assertEqual(start, 16000)
        self.assertGreaterEqual(timing['tail_seconds'], 1)
        self.assertGreaterEqual(len(audio) / 32000, timing['generated_clip_seconds'])
        self.assertFalse(timing['speech_trimmed'])
        self.assertFalse(timing['time_stretch_applied'])

    def test_resampling_preserves_natural_duration_without_truncation(self):
        import numpy as np
        raw = np.sin(2 * np.pi * 400 * np.arange(24000) / 24000).astype(np.float32) * 0.2
        audio, timing = target.pad_target_audio(raw, 24000)
        self.assertEqual(timing['raw_duration_seconds'], 1)
        self.assertEqual(timing['resampled_speech_seconds'], 1)
        self.assertEqual(timing['speech_end_sample_exclusive'] - timing['speech_start_sample'], 32000)
        self.assertEqual(audio.shape[1], 2)

    def test_s506_padding_preserves_title_lead_and_raw_leading_pause(self):
        import numpy as np
        raw = np.concatenate([np.zeros(6400, dtype=np.float32), np.full(32000, 0.2, dtype=np.float32)])
        audio, timing = target.pad_target_audio(raw, 32000, min_seconds=8, lead_seconds=2.6)
        start = round(2.6 * 32000)
        self.assertEqual(timing['speech_start_sample'], start)
        self.assertEqual(timing['lead_seconds'], 2.6)
        self.assertGreaterEqual(timing['generated_clip_seconds'], 8)
        np.testing.assert_array_equal(audio[start:start + len(raw), 0], raw)
        self.assertTrue(np.all(audio[:start + 6400] == 0))
        self.assertAlmostEqual(timing['editorial_handles']['speech_plus_tail_seconds'], 4.8)
        self.assertEqual(target.choose_frames(10.7, min_seconds=14, lead_seconds=2.6), 345)
        with self.assertRaisesRegex(ValueError, 'never accelerate'):
            target.choose_frames(10.9, min_seconds=14, lead_seconds=2.6)

    def test_busy_comfy_queue_blocks_before_gpu_probe(self):
        with patch('novel_h3.comfy.config', return_value={'comfy_url': 'http://unused'}), \
             patch('novel_h3.comfy.api', return_value={'queue_running': [['busy']], 'queue_pending': []}), \
             patch.object(target.subprocess, 'run') as probe:
            with self.assertRaisesRegex(RuntimeError, 'queue is not empty'):
                target.require_idle_gpu()
            probe.assert_not_called()

    def test_loaded_or_busy_gpu_is_rejected_without_loading_a_model(self):
        from types import SimpleNamespace
        for reading in ['0, 24000', '90, 24000']:
            with self.subTest(reading=reading), \
                 patch('novel_h3.comfy.config', return_value={'comfy_url': 'http://unused'}), \
                 patch('novel_h3.comfy.api', return_value={'queue_running': [], 'queue_pending': []}), \
                 patch.object(target.subprocess, 'run', return_value=SimpleNamespace(stdout=reading)):
                with self.assertRaisesRegex(RuntimeError, 'GPU is not idle'):
                    target.require_idle_gpu()

    def test_desktop_utilization_does_not_block_an_empty_memory_safe_queue(self):
        from types import SimpleNamespace
        with patch('novel_h3.comfy.config', return_value={'comfy_url': 'http://unused'}), \
             patch('novel_h3.comfy.api', return_value={'queue_running': [], 'queue_pending': []}), \
             patch.object(target.subprocess, 'run', return_value=SimpleNamespace(stdout='35, 5096')):
            result = target.require_idle_gpu()
        self.assertTrue(result['queue_empty'])
        self.assertFalse(result['utilization_used_as_inference_gate'])


if __name__ == '__main__':
    unittest.main()
