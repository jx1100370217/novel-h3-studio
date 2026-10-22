from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from audio_review import MODELS
from novel_h3.project import file_hash, read, write
from novel_h3.v2.speech import compare_spoken
from scripts.check_dialogue_batch_strict import check_batch


class StrictDialogueBatchCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / 'manifest.json'
        self.report = self.root / 'manifest.speech_check.json'
        self.vad = {'available': True, 'speech_detected': True, 'speech_segments': [{'start': 0, 'end': .2}]}

    def create_source(self, name, amplitude=.1):
        t = np.arange(8000) / 32000
        waveform = np.column_stack((amplitude * np.sin(2 * np.pi * 440 * t),
                                    amplitude * np.sin(2 * np.pi * 660 * t)))
        path = self.root / name
        sf.write(path, waveform, 32000, subtype='FLOAT')
        return {'path': name, 'sha256': file_hash(path)}

    def fixture(self, count=1):
        entries, old_entries = [], []
        for index in range(count):
            text = f'原句{index}'
            target = self.create_source(f'{index}_target.wav', .1 + index * .002)
            roundtrip = self.create_source(f'{index}_roundtrip.wav', .1 + index * .002)
            entry = {'shot_id': f'S{index:03}', 'expected_text': text, 'target': target,
                     'audio_vae_roundtrip': roundtrip}
            entries.append(entry)
            sources = []
            for role, item in [('audio_target', target), ('audio_vae_roundtrip', roundtrip)]:
                row = dict(compare_spoken(text, text), role=role, path=item['path'], sha256=item['sha256'],
                           transcript_passed=True, source_hash_matches_manifest=True, original_unchanged=True,
                           native_audio={'samples_finite': True, 'sample_peak_check_passed': True},
                           speech_gate=deepcopy(self.vad))
                sources.append(row)
            old_entries.append({'shot_id': entry['shot_id'], 'expected_text': text, 'passed': True, 'sources': sources})
        previous = {'asr_model': {'id': MODELS['speech'][0], 'revision': MODELS['speech'][1]}, 'entries': old_entries}
        write(self.manifest, {'entries': entries})
        write(self.report, previous)
        return entries, previous

    def run_check(self, texts):
        pipe = Mock(side_effect=[{'text': text, 'chunks': []} for text in texts])
        with patch('scripts.check_dialogue_batch_strict.load_transcriber', return_value=pipe) as load, \
                patch('novel_h3.voice_gate.detect_speech', return_value=self.vad):
            result, _ = check_batch(self.root, self.manifest)
        return result, load, pipe

    def test_unchanged_pass_reuses_both_sources_without_model_or_pipe(self):
        self.fixture()
        old_bytes, old_hash = self.report.read_bytes(), file_hash(self.report)
        result, load, pipe = self.run_check([])
        self.assertTrue(result['passed'])
        load.assert_not_called()
        pipe.assert_not_called()
        self.assertEqual(result['asr_model']['loads'], 0)
        self.assertEqual(result['counts']['asr_reused_sources'], 2)
        self.assertTrue(all(row['asr_reused'] for row in result['entries'][0]['sources']))
        self.assertEqual((self.root / 'strict_check_history' / (old_hash + '.json')).read_bytes(), old_bytes)
        self.assertEqual(result['previous_report_sha256'], old_hash)
        self.assertTrue(result['code_sources_unchanged'])
        self.assertGreaterEqual(len(result['code_sources']), 6)
        self.assertFalse(result['human_listened'])
        self.assertFalse(result['secondary_evidence_consumed'])

    def test_changed_text_cannot_borrow_old_pass(self):
        entries, _ = self.fixture()
        entries[0]['expected_text'] = '新的正式对白'
        write(self.manifest, {'entries': entries})
        result, load, pipe = self.run_check(['原句0', '原句0'])
        self.assertFalse(result['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(pipe.call_count, 2)
        self.assertEqual(result['counts']['asr_reused_sources'], 0)

    def test_changed_source_hash_checks_only_that_source_again(self):
        entries, _ = self.fixture()
        entries[0]['target'] = self.create_source('0_target.wav', amplitude=.2)
        write(self.manifest, {'entries': entries})
        result, load, pipe = self.run_check(['原句0'])
        self.assertTrue(result['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(pipe.call_count, 1)
        self.assertFalse(result['entries'][0]['sources'][0]['asr_reused'])
        self.assertTrue(result['entries'][0]['sources'][1]['asr_reused'])

    def test_failed_old_schema_bad_technical_and_changed_rules_are_not_cached(self):
        _, previous = self.fixture()
        changes = [lambda row: row.update(passed=False),
                   lambda row: row.update(comparison_schema='old_schema'),
                   lambda row: row.update(original_unchanged=False),
                   lambda row: row.update(source_hash_matches_manifest=False),
                   lambda row: row['native_audio'].update(sample_peak_check_passed=False),
                   lambda row: row['native_audio'].update(samples_finite=False),
                   lambda row: row['speech_gate'].update(available=False),
                   lambda row: row['phonetic_comparison'].update(transcript_syllables=['changed4'])]
        for alter in changes:
            with self.subTest(change=alter):
                old = deepcopy(previous)
                alter(old['entries'][0]['sources'][0])
                write(self.report, old)
                result, load, pipe = self.run_check(['原句0'])
                self.assertTrue(result['passed'])
                self.assertEqual(load.call_count, 1)
                self.assertEqual(pipe.call_count, 1)
                self.assertEqual(result['counts']['asr_reused_sources'], 1)

    def test_six_rewritten_entries_do_twelve_new_checks_and_keep_fifteen_cached(self):
        entries, _ = self.fixture(count=21)
        fresh_texts = []
        for index in range(15, 21):
            entries[index]['expected_text'] = f'修订后的正式对白{index}'
            entries[index]['target'] = self.create_source(f'{index}_target.wav', amplitude=.3)
            entries[index]['audio_vae_roundtrip'] = self.create_source(f'{index}_roundtrip.wav', amplitude=.3)
            fresh_texts.extend([entries[index]['expected_text']] * 2)
        write(self.manifest, {'entries': entries})
        result, load, pipe = self.run_check(fresh_texts)
        self.assertTrue(result['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(pipe.call_count, 12)
        self.assertEqual(result['counts']['asr_reused_sources'], 30)
        self.assertEqual(result['counts']['new_sources_checked'], 12)
        self.assertTrue(all(all(source['asr_reused'] for source in entry['sources']) for entry in result['entries'][:15]))
        self.assertTrue(all(all(not source['asr_reused'] for source in entry['sources']) for entry in result['entries'][15:]))
        self.assertTrue(result['originals_unchanged'])

    def test_unknown_secondary_fields_are_not_used(self):
        entries, old = self.fixture()
        entries[0]['secondary_transcripts'] = {'audio_target': {'path': 'unprovided.json', 'sha256': 'invalid'}}
        old['entries'][0]['sources'][0]['passed'] = False
        write(self.manifest, {'entries': entries})
        write(self.report, old)
        result, load, pipe = self.run_check(['不相同的台词'])
        self.assertFalse(result['passed'])
        self.assertEqual(load.call_count, 1)
        self.assertEqual(pipe.call_count, 1)
        self.assertFalse(result['secondary_evidence_consumed'])
        self.assertNotIn('secondary_transcription', result['entries'][0]['sources'][0])


if __name__ == '__main__':
    unittest.main()
