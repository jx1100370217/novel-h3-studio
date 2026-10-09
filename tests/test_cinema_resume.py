from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import file_hash, read, write
from novel_h3.v2.runner import (complete_screening, reconcile_failed_submission,
                              release_between_shots, reuse_candidate, verify_cached_media)


class CinemaResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'native.mp4').write_bytes(b'immutable-video')
        (self.root / 'native_audio.flac').write_bytes(b'immutable-native-audio')
        self.receipt = {'technical_qc': {'passed': True},
                        'video_sha256': file_hash(self.root / 'native.mp4'),
                        'native_audio_sha256': file_hash(self.root / 'native_audio.flac')}

    def test_failed_technical_qc_is_never_reused(self):
        self.receipt['technical_qc']['passed'] = False
        with self.assertRaisesRegex(ValueError, 'failed technical QC'):
            verify_cached_media(self.root, self.receipt)

    def test_native_audio_must_match_even_when_video_matches(self):
        (self.root / 'native_audio.flac').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'native_audio.flac'):
            verify_cached_media(self.root, self.receipt)

    def test_interrupted_screening_is_resumed_without_generation(self):
        def inspect(folder):
            write(folder / 'analysis/speech.json', {'passed': True, 'video_sha256': self.receipt['video_sha256']})
            return 0
        with patch('novel_h3.v2.runner.screen', side_effect=inspect) as mock:
            complete_screening(self.root, self.receipt)
            mock.assert_called_once()
        with patch('novel_h3.v2.runner.screen') as mock:
            complete_screening(self.root, self.receipt)
            mock.assert_not_called()
        self.assertTrue(read(self.root / 'take.json')['speech_screening']['passed'])

    def test_reuse_preserves_original_and_rejects_changed_creative_input(self):
        original = {'schema': 'v2', 'shot_sha256': 'same-shot', 'prompt_sha256': 'same-prompt',
                    'visuals': [{'generation_sha256': 'image', 'staged_name': 'staged.png'}]}
        write(self.root / 'request.json', original)
        self.receipt['speech_screening'] = {'passed': True}
        write(self.root / 'take.json', self.receipt)
        requested = dict(original, visuals=[{'generation_sha256': 'image'}])
        before = file_hash(self.root / 'take.json')
        folder, _ = reuse_candidate(self.root, '.', requested)
        self.assertEqual(folder, self.root)
        self.assertEqual(file_hash(self.root / 'take.json'), before)
        requested['prompt_sha256'] = 'different-camera-or-dialogue'
        with self.assertRaisesRegex(ValueError, 'different shot inputs'):
            reuse_candidate(self.root, '.', requested)

    def test_failed_job_missing_after_server_restart_is_archived_for_resubmission(self):
        folder = self.root / 'failed'
        folder.mkdir()
        receipt = {'status': 'failed', 'prompt_id': 'old', 'error': 'resource guard'}
        with patch('novel_h3.v2.runner.api', side_effect=[
                {'queue_running': [], 'queue_pending': []}, {}]):
            self.assertEqual(reconcile_failed_submission(folder, receipt, {'comfy_url': 'unused'}), {})
        archives = list((folder / 'submission_history').glob('*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(read(archives[0])['prompt_id'], 'old')

    def test_active_failed_job_is_never_submitted_twice(self):
        folder = self.root / 'failed'
        folder.mkdir()
        with patch('novel_h3.v2.runner.api', return_value={'queue_running': [[0, 'old']], 'queue_pending': []}) as api:
            with self.assertRaisesRegex(RuntimeError, 'still active'):
                reconcile_failed_submission(folder, {'status': 'failed', 'prompt_id': 'old'}, {'comfy_url': 'unused'})
            api.assert_called_once()
        self.assertFalse((folder / 'submission_history').exists())

    def test_successful_old_job_is_collected_instead_of_resubmitted(self):
        folder = self.root / 'failed'
        folder.mkdir()
        receipt = {'status': 'failed', 'prompt_id': 'old'}
        with patch('novel_h3.v2.runner.api', side_effect=[
                {'queue_running': [], 'queue_pending': []}, {'old': {'status': {'status_str': 'success'}}}]):
            self.assertEqual(reconcile_failed_submission(folder, receipt, {'comfy_url': 'unused'}), receipt)

    def test_cache_release_does_not_touch_another_job(self):
        with patch('novel_h3.v2.runner.api', return_value={'queue_running': [[0, 'other']], 'queue_pending': []}) as api:
            with self.assertRaisesRegex(RuntimeError, 'became busy'):
                release_between_shots({'comfy_url': 'unused'})
            api.assert_called_once()


if __name__ == '__main__': unittest.main()
