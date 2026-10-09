import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audio_review import decode_audio
from novel_h3.audio_cleanup import (
    alignment_evidence, clean_unbound_speech, decode_audio_master,
    normalize_diegetic_mix, timing_alignment,
)
from novel_h3.project import file_hash
from novel_h3.speech_qc import run


class AudioMasterIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'stereo.mov'
        self.rate = 48000
        t = np.arange(self.rate * 2) / self.rate
        # Distinct channels and components above the ASR proxy's Nyquist limit.
        signal = np.column_stack((.015 * np.sin(2 * np.pi * 1000 * t) + .01 * np.sin(2 * np.pi * 12000 * t),
                                  .012 * np.sin(2 * np.pi * 2000 * t) + .008 * np.sin(2 * np.pi * 10000 * t)))
        wav = self.root / 'master.wav'
        sf.write(wav, signal, self.rate, subtype='FLOAT')
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=size=64x64:rate=24:duration=2', '-i', str(wav),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                        '-c:a', 'pcm_f32le', '-shortest', str(self.source)], check=True, capture_output=True)

    def assert_stereo_high_frequencies(self, path):
        data, rate, metadata = decode_audio_master(path)
        self.assertEqual(rate, 48000)
        self.assertEqual(metadata['input_channels'], 2)
        self.assertGreater(float(np.sqrt(np.mean((data[:, 0] - data[:, 1]) ** 2))), .004)
        data = data[rate // 4:rate * 7 // 4]
        freqs = np.fft.rfftfreq(len(data), 1 / rate)
        spectrum = np.abs(np.fft.rfft(data, axis=0)) / len(data)
        left = spectrum[np.abs(freqs - 12000).argmin()]
        right = spectrum[np.abs(freqs - 10000).argmin()]
        self.assertGreater(left[0], .001)
        self.assertGreater(left[0], left[1] * 5)
        self.assertGreater(right[1], .001)
        self.assertGreater(right[1], right[0] * 5)

    def test_proxy_and_master_decode_never_change_source(self):
        before = file_hash(self.source)
        proxy = self.root / 'proxy.wav'
        result = decode_audio(self.source, proxy)
        samples, rate = sf.read(proxy)
        self.assertEqual(rate, 16000)
        self.assertEqual(samples.ndim, 1)
        self.assertFalse(result['eligible_for_master'])
        self.assert_stereo_high_frequencies(self.source)
        self.assertEqual(file_hash(self.source), before)
        with self.assertRaisesRegex(ValueError, '不能覆盖'):
            decode_audio(self.source, self.source)
        self.assertEqual(file_hash(self.source), before)

    def test_normalization_ignores_mono_proxy_and_preserves_master(self):
        before = file_hash(self.source)
        # Intentionally unusable proxy: writing it would erase the entire track.
        result = normalize_diegetic_mix(self.source, self.root, np.zeros(32000), 16000)
        self.assertEqual(result['status'], 'applied')
        self.assertFalse(result['production_audio']['uses_asr_proxy'])
        backup = result['original_audio_master']
        self.assertEqual(backup['source_video_sha256'], before)
        self.assertEqual(file_hash(self.root / backup['path']), backup['sha256'])
        self.assert_stereo_high_frequencies(self.root / backup['path'])
        self.assert_stereo_high_frequencies(self.source)

    def test_center_cleanup_uses_real_stereo_not_mono_proxy(self):
        result = clean_unbound_speech(
            self.source, self.root, {'text': 'unwanted', 'chunks': [{'text': 'unwanted', 'timestamp': [0, 1.9]}]},
            np.zeros(32000), 16000, aggressive=True)
        self.assertEqual(result['status'], 'applied')
        self.assertFalse(result['production_audio']['uses_asr_proxy'])
        self.assertEqual(result['production_audio']['processing_sample_rate'], 48000)
        self.assert_stereo_high_frequencies(self.source)

    def test_master_decode_failure_leaves_media_bytes_unchanged(self):
        before = file_hash(self.source)
        with patch('novel_h3.audio_cleanup.decode_audio_master', side_effect=ValueError('bad master')):
            result = normalize_diegetic_mix(self.source, self.root, np.zeros(32000), 16000)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(file_hash(self.source), before)

    def test_matching_audio_windows_do_not_pass_visual_sync(self):
        evidence = alignment_evidence(timing_alignment([[0, 1]], [{'start_frame': 0, 'end_frame': 24}]))
        self.assertEqual(evidence['speech_window_alignment']['status'], 'passed')
        self.assertEqual(evidence['av_sync_review']['status'], 'not_evaluated')
        self.assertFalse(evidence['av_sync_review']['video_examined'])
        self.assertFalse(evidence['lip_sync_gate']['can_approve_av_sync'])
        self.assertEqual(evidence['lip_sync_gate']['status'], 'not_evaluated')

    def test_failed_analysis_and_exception_preserve_production_media_and_policy(self):
        before = file_hash(self.source)
        out = self.root / 'renders' / 'take1'
        out.mkdir(parents=True)
        policy = out / 'audio_policy.json'
        original_policy = b'{"status":"original"}'
        state = {'takes': {'take1': {'video': 'stereo.mov'}}}
        for raise_error in (False, True):
            policy.write_bytes(original_policy)

            def failed_analysis(root, take_id, source_override):
                source_override.write_bytes(b'invalid candidate after processing')
                policy.write_text('{"status":"candidate"}')
                if raise_error:
                    raise RuntimeError('simulated ASR failure')
                return {'passed': False}

            with patch('novel_h3.project.load_state', return_value=state), patch('novel_h3.speech_qc._run', side_effect=failed_analysis):
                result = run(self.root, 'take1')
            self.assertFalse(result['passed'])
            self.assertFalse(result['audio_processing_committed'])
            self.assertEqual(result['video_sha256'], before)
            self.assertEqual(file_hash(self.source), before)
            self.assertEqual(policy.read_bytes(), original_policy)
            self.assertFalse(list(out.glob('.speech_qc_*')))

    def test_native_dialogue_asr_uses_proxy_without_rewriting_master(self):
        before = file_hash(self.source)
        episode_dir = self.root / 'episodes'
        episode_dir.mkdir()
        (episode_dir / 'e1.json').write_text(json.dumps({'shots': [
            {'id': 's1', 'dialogue': [{'text': '您好', 'speaker': 'speaker1', 'start_frame': 0, 'end_frame': 24}]}]}))
        (self.root / 'config.json').write_text(json.dumps({'speech_policy': {'dialogue_audio_source': 'h3_native'}}))
        state = {'takes': {'take1': {'video': 'stereo.mov', 'episode': 'e1', 'shot': 's1'}}}
        processor = SimpleNamespace(tokenizer=None, feature_extractor=None)
        fake_transformers = SimpleNamespace(
            WhisperForConditionalGeneration=SimpleNamespace(from_pretrained=lambda *a, **kw: None),
            WhisperProcessor=SimpleNamespace(from_pretrained=lambda *a, **kw: processor),
            pipeline=lambda *a, **kw: lambda audio, **options: {'text': '您好'})
        fake_torch = SimpleNamespace(set_num_threads=lambda n: None, float32=None)
        vad = {'available': True, 'speech_detected': True, 'speech_segments': [{'start': 0, 'end': 1}]}
        with patch.dict(sys.modules, {'torch': fake_torch, 'transformers': fake_transformers}), \
                patch('novel_h3.project.load_state', return_value=state), \
                patch('novel_h3.voice_gate.detect_speech', return_value=vad), \
                patch('audio_review.model_path', return_value='unused-stub-model'):
            result = run(self.root, 'take1')
        self.assertTrue(result['passed'])
        self.assertFalse(result['audio_processing_committed'])
        self.assertNotIn('audio_normalization', result)
        self.assertEqual(result['av_sync_review']['status'], 'not_evaluated')
        self.assertEqual(file_hash(self.source), before)
        self.assert_stereo_high_frequencies(self.source)


if __name__ == '__main__':
    unittest.main()
