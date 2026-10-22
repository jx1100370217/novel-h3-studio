import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import file_hash, read, write

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/prepare_chapter_audio.py'
spec = importlib.util.spec_from_file_location('cinema_chapter_audio', SCRIPT)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


class ChapterAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'production_v2/chapter_s0002'
        self.output = self.base / 'chapter_audio'
        self.manifest = self.output / 'manifest.json'
        self.plan = self.base / 'chapter_plan.json'
        write(self.plan, {'id': 'chapter', 'shots': [
            {'id': 'S1', 'duration_seconds': 6, 'spoken_lines': [{'speaker': 'actor', 'text': '你好。'}]},
            {'id': 'S2', 'duration_seconds': 6, 'spoken_lines': [{'speaker': 'actor', 'text': '再见。'}]},
        ]})
        for obj, name, value in [(batch, 'BASE', self.base), (batch, 'OUTPUT', self.output),
                                 (batch, 'MANIFEST', self.manifest), (batch.target, 'PROJECT', self.root)]:
            patcher = patch.object(obj, name, value)
            patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(batch.target, 'resolve_plan', return_value=self.plan)
        patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(batch.target, 'prepare', side_effect=self.prepare)
        patcher.start(); self.addCleanup(patcher.stop)

    def prepare(self, seed, sid, path):
        return {'shot_id': sid, 'speaker_asset_id': 'actor', 'expected_text': '你好。' if sid in ('S1', 'P03') else '再见。',
                'source_reference': {'sha256': 'voicehash'}, 'authored_duration_seconds': 6,
                'seed': seed, 'minimum_generation_seconds': 4, 'approved': False, 'human_listened': False}

    def candidate(self, sid):
        record = self.prepare(123, sid, self.plan)
        for key in ['raw', 'target']:
            path = self.base / 'dialogue_targets' / f'{sid}_fixture' / f'{key}.wav'
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(f'{sid}-{key}'.encode())
            record[key] = {'path': str(path.relative_to(self.root)), 'sha256': file_hash(path),
                           'sample_rate': 32000, 'channels': 2, 'duration_seconds': 8}
        record.update(timing={'frames': 192, 'fps': 24}, status='generated_pending_asr_roundtrip_and_canary')
        return record

    def test_reuse_requires_exact_text_speaker_reference_and_both_media_hashes(self):
        candidate = self.candidate('S1'); specification = self.prepare(44, 'S1', self.plan)
        self.assertTrue(batch.candidate_matches(specification, candidate))
        for changes in [{'expected_text': '你好啊。'}, {'speaker_asset_id': 'other'}, {'source_reference': {'sha256': 'newvoice'}}]:
            self.assertFalse(batch.candidate_matches(specification, dict(candidate, **changes)))
        (self.root / candidate['raw']['path']).write_bytes(b'changed')
        self.assertFalse(batch.candidate_matches(specification, candidate))

    def test_lead_change_invalidates_reuse_except_validated_p03(self):
        candidate = self.candidate('S1')
        specification = dict(self.prepare(44, 'S1', self.plan), lead_seconds=2.6)
        self.assertFalse(batch.candidate_matches(specification, candidate))
        candidate['timing']['lead_seconds'] = 2.6
        self.assertTrue(batch.candidate_matches(specification, candidate))
        p03 = self.candidate('P03')
        self.assertTrue(batch.candidate_matches(dict(self.prepare(44, 'P03', self.plan), lead_seconds=2.6), p03))

    def test_verified_p03_is_referenced_without_copying_or_regeneration(self):
        candidate = self.candidate('P03')
        path = self.base / 'dialogue_targets/P03_fixture/manifest.json'
        report = path.with_name('manifest.speech_check.json')
        write(report, {'passed': True, 'speaker_asset_id': 'actor', 'expected_text': candidate['expected_text'],
                       'sources': [{'role': 'audio_target', 'passed': True, 'edit_distance': 0, 'allowed_distance': 0,
                                    'sha256': candidate['target']['sha256']}]})
        candidate['speech_check'] = {'path': str(report.relative_to(self.root)), 'sha256': file_hash(report)}
        write(path, candidate)
        files = set(self.root.rglob('*'))
        result = batch.verified_pilot_target(self.prepare(999, 'P03', self.plan))
        self.assertEqual(result['target']['path'], candidate['target']['path'])
        self.assertEqual(result['seed'], 123)
        self.assertEqual(result['requested_seed'], 999)
        self.assertEqual(set(self.root.rglob('*')), files)
        broken = read(report); broken['sources'][0]['passed'] = False; write(report, broken)
        candidate['speech_check']['sha256'] = file_hash(report); write(path, candidate)
        self.assertIsNone(batch.verified_pilot_target(self.prepare(999, 'P03', self.plan)))

    def test_selected_retry_keeps_other_successful_entries(self):
        one, two = self.candidate('S1'), self.candidate('S2')
        write(self.manifest, {'entries': [one, two]})
        planned = batch.plan_batch(shots=['S2'])
        self.assertEqual(planned['entries'][0]['target'], one['target'])
        self.assertEqual(planned['entries'][0]['action'], 'reuse')
        self.assertEqual(planned['entries'][1]['action'], 'generate')
        self.assertEqual(read(self.manifest)['entries'], [one, two])

    def test_completed_per_shot_receipt_recovers_after_batch_write_interruption(self):
        candidate = self.candidate('S1')
        saved = self.output / 'S1_fixture/manifest.json'
        write(saved, candidate)
        entry = self.prepare(123, 'S1', self.plan)
        entry.update(status='generating', manifest_path=str(saved.relative_to(self.root)))
        write(self.manifest, {'entries': [entry]})
        planned = batch.plan_batch()
        self.assertEqual(planned['entries'][0]['action'], 'reuse')
        self.assertEqual(planned['entries'][0]['target'], candidate['target'])

    def test_batch_loads_one_model_for_multiple_targets_and_records_each(self):
        def generated(specification, model, output, preflight):
            self.assertIs(model, sentinel)
            return dict(specification, action='generated', target={'path': str(output / 'target.wav'), 'sha256': 'fixture'},
                        manifest_path=str(output / 'manifest.json'))
        sentinel = object()
        with patch('novel_h3.safety.bounded_worker'), patch('novel_h3.safety.check_paused'), \
             patch('novel_h3.safety.check_power_cap'), patch.object(batch.target, 'require_idle_gpu', return_value={}), \
             patch.object(batch.target, 'load_voice_model', return_value=sentinel) as load, \
             patch.object(batch.target, 'generate_candidate', side_effect=generated) as synth:
            batch.execute_batch()
        load.assert_called_once(); self.assertEqual(synth.call_count, 2)
        result = read(self.manifest)
        self.assertEqual(result['model_loads'], 1)
        self.assertEqual([entry['shot_id'] for entry in result['entries']], ['S1', 'S2'])
        self.assertEqual(result['entries'][0]['minimum_generation_seconds'], 6)

    def test_duration_failure_keeps_partial_manifest_and_prior_success(self):
        def generated(specification, model, output, preflight):
            if specification['shot_id'] == 'S1':
                return self.candidate('S1')
            write(output / 'manifest.json', dict(specification, status='incomplete_raw_retained',
                                                raw={'path': 'kept.wav', 'sha256': 'rawhash'}))
            raise ValueError('Natural speech exceeds frame grid')
        with patch('novel_h3.safety.bounded_worker'), patch('novel_h3.safety.check_paused'), \
             patch('novel_h3.safety.check_power_cap'), patch.object(batch.target, 'require_idle_gpu', return_value={}), \
             patch.object(batch.target, 'load_voice_model'), \
             patch.object(batch.target, 'generate_candidate', side_effect=generated):
            with self.assertRaisesRegex(RuntimeError, 'S2'):
                batch.execute_batch()
        result = read(self.manifest)
        self.assertEqual(result['entries'][0]['action'], 'generated')
        self.assertIn('target', result['entries'][0])
        self.assertEqual(result['entries'][1]['raw']['sha256'], 'rawhash')
        self.assertEqual(result['status'], 'partial_failed')


if __name__ == '__main__':
    unittest.main()
