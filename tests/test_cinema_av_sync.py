import unittest
from pathlib import Path

from novel_h3.v2.av_sync import COMMIT, cpu_environment, interpretation, smoke_result, validate_smoke


class CinemaAVSyncTests(unittest.TestCase):
    def test_author_example_is_required_before_interpretation(self):
        self.assertTrue(smoke_result('AV offset: 3\nMin dist: 5.353\nConfidence: 10.021')['passed'])
        self.assertFalse(smoke_result('AV offset: 0\nMin dist: 5.353\nConfidence: 10.021')['passed'])
        self.assertFalse(smoke_result('incomplete output')['passed'])

    def test_missing_validation_small_faces_and_low_confidence_are_unknown(self):
        for size, confidence, duration, smoke_passed in ((200, 10, 4, False), (70, 10, 4, True),
                                                       (200, 2, 4, True), (200, 10, 1, True)):
            result = interpretation(0, confidence, size, duration, smoke_passed)
            self.assertEqual(result['status'], 'not_evaluated')
            self.assertFalse(result['can_approve_av_sync'])

    def test_strong_measurement_still_is_not_approval_or_audio_repair(self):
        result = interpretation(3, 10, 200, 4, True)
        self.assertEqual(result['status'], 'measured_needs_review')
        self.assertEqual(result['offset_seconds'], .12)
        self.assertFalse(result['release_approved'])
        self.assertFalse(result['human_listened'])
        self.assertFalse(result['can_approve_av_sync'])

    def test_subprocess_environment_cannot_select_gpu(self):
        environment = cpu_environment(Path('/isolated'))
        self.assertEqual(environment['CUDA_VISIBLE_DEVICES'], '')
        self.assertEqual(environment['OMP_NUM_THREADS'], '4')
        self.assertEqual(environment['PYTHONPATH'], '/isolated/deps')

    def test_invalid_confidence_and_saturated_offset_cannot_be_interpreted(self):
        self.assertEqual(interpretation(0, float('nan'), 200, 4, True)['status'], 'not_evaluated')
        self.assertEqual(interpretation(15, 10, 200, 4, True)['status'], 'not_evaluated')

    def test_old_smoke_cannot_authorize_changed_weights_or_environment(self):
        assets = {'files': [{'path': 'data/syncnet_v2.model', 'sha256': 'weights'},
                            {'path': 'data/example.avi', 'sha256': 'example'}]}
        evidence = {'passed': True, 'source_commit': COMMIT, 'versions': {'torch': 'tested'}, 'asset_receipt': assets}
        validate_smoke(evidence, assets, {'torch': 'tested'})
        with self.assertRaisesRegex(ValueError, 'environment changed'):
            validate_smoke(evidence, assets, {'torch': 'different'})
        with self.assertRaisesRegex(ValueError, 'weights or demo changed'):
            validate_smoke(evidence, {'files': [{'path': 'syncnet_v2.model', 'sha256': 'different'}]}, {'torch': 'tested'})


if __name__ == '__main__':
    unittest.main()
