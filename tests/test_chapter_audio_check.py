from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from novel_h3.project import file_hash, read, write
from scripts.check_dialogue_batch import check_batch
from scripts.check_dialogue_target import check


class ChapterAudioCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.long = self.audio('target_a.wav', seconds=15.08)
        self.roundtrip = self.audio('roundtrip_a.flac', seconds=15.08)
        self.short = self.audio('target_b.wav', seconds=1.2)
        self.entries = [
            {'shot_id': 'A', 'speaker_asset_id': 'speaker_a', 'expected_text': '你好',
             'target': self.long, 'audio_vae_roundtrip': self.roundtrip},
            {'shot_id': 'B', 'speaker_asset_id': 'speaker_b', 'expected_text': '谢谢', 'target': self.short},
        ]
        self.manifest = self.root / 'manifest.json'
        write(self.manifest, {'entries': self.entries})
        self.vad = {'available': True, 'speech_detected': True, 'speech_segments': [{'start': 0, 'end': 1}]}

    def audio(self, name, seconds):
        t = np.arange(round(seconds * 32000)) / 32000
        signal = np.column_stack((.1 * np.sin(2 * np.pi * 440 * t), .08 * np.sin(2 * np.pi * 660 * t)))
        source = self.root / name
        sf.write(source, signal, 32000, subtype='PCM_24')
        return {'path': name, 'sha256': file_hash(source)}

    def run_batch(self, texts, vad=None):
        transcribe = Mock(side_effect=[{'text': text, 'chunks': []} for text in texts])
        with patch('scripts.check_dialogue_batch.load_transcriber', return_value=transcribe) as load, \
                patch('novel_h3.voice_gate.detect_speech', return_value=self.vad if vad is None else vad):
            report, output = check_batch(self.root, self.manifest)
        return report, output, load, transcribe

    def test_all_targets_and_roundtrip_share_one_model_without_reference_time_limit(self):
        originals = {p: file_hash(p) for p in self.root.iterdir() if p.is_file()}
        report, output, load, transcribe = self.run_batch(['你好', '你好', '谢谢'])
        self.assertTrue(report['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(transcribe.call_count, 3)
        self.assertEqual(report['counts'], {'entries': 2, 'passed': 2, 'failed': 0, 'targets_checked': 2, 'roundtrips_checked': 1, 'asr_reused_sources': 0, 'new_sources_checked': 3})
        native = report['entries'][0]['sources'][0]['native_audio']
        self.assertEqual(native['duration_seconds'], 15.08)
        self.assertEqual(native['sample_rate'], 32000)
        self.assertEqual(native['channels'], 2)
        self.assertAlmostEqual(native['sample_peak'], .1, places=5)
        self.assertTrue(native['sample_peak_check_passed'])
        self.assertTrue(report['originals_unchanged'])
        self.assertFalse(report['release_approved'])
        self.assertFalse(report['human_listened'])
        self.assertEqual(report['av_sync_review']['status'], 'not_evaluated')
        self.assertEqual(read(output), report)
        for path, before in originals.items():
            self.assertEqual(file_hash(path), before)

    def test_bad_hash_is_reported_while_other_entries_are_checked(self):
        entries = deepcopy(self.entries)
        entries[1]['target']['sha256'] = 'wrong'
        write(self.manifest, {'entries': entries})
        report, _, load, transcribe = self.run_batch(['你好', '你好'])
        self.assertFalse(report['passed'])
        self.assertTrue(report['entries'][0]['passed'])
        self.assertIn('hash does not match', report['entries'][1]['preflight_error'])
        self.assertEqual(transcribe.call_count, 2)
        self.assertEqual(load.call_count, 1)

    def test_bad_transcript_does_not_hide_later_successful_target(self):
        report, _, load, transcribe = self.run_batch(['你好啊', '你好', '谢谢'])
        self.assertFalse(report['passed'])
        self.assertFalse(report['entries'][0]['sources'][0]['transcript_passed'])
        self.assertTrue(report['entries'][1]['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(transcribe.call_count, 3)

    def test_native_overload_blocks_even_when_transcript_matches(self):
        source = self.root / 'target_b.wav'
        sf.write(source, np.ones((32000, 2)) * 1.1, 32000, subtype='FLOAT')
        entries = deepcopy(self.entries)
        entries[1]['target']['sha256'] = file_hash(source)
        write(self.manifest, {'entries': entries})
        before = file_hash(source)
        report, _, _, _ = self.run_batch(['你好', '你好', '谢谢'])
        row = report['entries'][1]['sources'][0]
        self.assertTrue(row['transcript_passed'])
        self.assertFalse(row['passed'])
        self.assertGreater(row['native_audio']['sample_peak'], 1)
        self.assertFalse(row['native_audio']['sample_peak_check_passed'])
        self.assertEqual(file_hash(source), before)

    def test_missing_voice_and_unverified_legacy_alias_do_not_pass(self):
        report, _, _, transcribe = self.run_batch([], vad={'available': True, 'speech_detected': False})
        self.assertFalse(report['passed'])
        transcribe.assert_not_called()
        entry = deepcopy(self.entries[1])
        entry['expected_text'] = '九年期限一到，我再召你回来。'
        write(self.manifest, {'entries': [entry]})
        report, _, _, _ = self.run_batch(['九年期限一到，我再招你回来。'])
        self.assertFalse(report['passed'])
        self.assertTrue(report['entries'][0]['sources'][0]['ignored_legacy_sentence_aliases'])

    def test_batch_preserves_written_difference_when_phonetic_spelling_passes(self):
        entry = deepcopy(self.entries[1])
        entry['expected_text'] = '关圣帝君'
        write(self.manifest, {'entries': [entry]})
        report, _, _, _ = self.run_batch(['官圣帝君'])
        self.assertTrue(report['passed'])
        row = report['entries'][0]['sources'][0]
        self.assertEqual(row['edit_distance'], 1)
        self.assertEqual(row['phonetic_comparison']['edit_distance'], 0)
        self.assertEqual(row['match_type'], 'phonetic_equivalent')
        self.assertEqual(row['expected'], '关圣帝君')
        self.assertEqual(row['transcript'], '官圣帝君')
        self.assertFalse(row['human_listened'])

    def test_single_manifest_interface_still_works(self):
        write(self.manifest, self.entries[0])
        transcribe = Mock(side_effect=[{'text': '你好'}, {'text': '你好'}])
        with patch('scripts.check_dialogue_target.load_transcriber', return_value=transcribe) as load, \
                patch('novel_h3.voice_gate.detect_speech', return_value=self.vad):
            report, _ = check(self.root, self.manifest)
        self.assertTrue(report['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertTrue(report['audio_vae_roundtrip_checked'])
        self.assertFalse(report['reference_duration_limit_applied'])


if __name__ == '__main__':
    unittest.main()
