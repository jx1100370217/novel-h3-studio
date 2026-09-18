import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3.project import write, read, file_hash
from render_chapter import retain_speech_failure, retain_speech_qc_failure
from novel_h3.comfy import current_takes


class SpeechRetryLimitTests(unittest.TestCase):
    def test_third_failed_take_is_retained_and_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / 'state.json', {
                'assets': {}, 'approvals': {}, 'takes': {
                    't3': {'status': 'rendered', 'speech_check': {'passed': False},
                           'video_deleted': False, 'retired': False}
                }
            })
            retain_speech_failure(root, 't3')
            take = read(root / 'state.json')['takes']['t3']
            self.assertEqual(take['status'], 'rendered')
            self.assertFalse(take['retired'])
            self.assertTrue(take['speech_retry_exhausted'])
            self.assertEqual(take['speech_retry_failures'], 3)
            self.assertEqual(take['review_required'], 'speech_qc_failed_after_3_retries')

    def test_retained_take_survives_prompt_only_fingerprint_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'renders' / 'retained' / 'video.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(b'kept-video')
            shot = {'id': 'S1', 'continuity': 'cut', 'dialogue': [
                {'kind': 'dialogue', 'speaker': '盘古', 'text': '混沌初生。'}]}
            episode = {'id': 'episode', 'shots': [shot]}
            write(root / 'episodes' / 'episode.json', episode)
            write(root / 'state.json', {'assets': {}, 'approvals': {}, 'takes': {
                'retained': {'id': 'retained', 'episode': 'episode', 'shot': 'S1',
                             'fingerprint': 'old-fingerprint', 'status': 'rendered',
                             'retired': False, 'speech_retry_exhausted': True,
                             'assigned_dialogue': shot['dialogue'],
                             'video': 'renders/retained/video.mp4',
                             'video_sha256': file_hash(video), 'created_at': 1}
            }})
            with patch('novel_h3.comfy.fingerprint', return_value='new-fingerprint'):
                rows = current_takes(root, episode)
            self.assertEqual(rows[0][2]['id'], 'retained')
            self.assertTrue(rows[0][2]['speech_retry_exhausted'])

    def test_any_failed_take_is_retained_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / 'state.json', {
                'assets': {}, 'approvals': {}, 'takes': {
                    't1': {'status': 'rendered', 'speech_check': {'passed': False},
                           'video_deleted': False, 'retired': False,
                           'speech_retry_attempt': 0}
                }
            })
            retain_speech_qc_failure(root, 't1')
            take = read(root / 'state.json')['takes']['t1']
            self.assertEqual(take['status'], 'rendered')
            self.assertFalse(take['retired'])
            self.assertTrue(take['speech_qc_failed_retained'])
            self.assertEqual(take['speech_retry_attempt'], 1)
            self.assertEqual(take['review_required'], 'speech_qc_failed_retained')
            self.assertFalse(take.get('speech_retry_exhausted', False))

    def test_new_retained_marker_is_reused_after_fingerprint_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / 'renders' / 'retained' / 'video.mp4'
            video.parent.mkdir(parents=True)
            video.write_bytes(b'kept-video')
            shot = {'id': 'S1', 'continuity': 'cut', 'dialogue': [
                {'kind': 'dialogue', 'speaker': '盘古', 'text': '你好。'}]}
            episode = {'id': 'episode', 'shots': [shot]}
            write(root / 'episodes' / 'episode.json', episode)
            write(root / 'state.json', {'assets': {}, 'approvals': {}, 'takes': {
                'retained': {'id': 'retained', 'episode': 'episode', 'shot': 'S1',
                             'fingerprint': 'old-fingerprint', 'status': 'rendered',
                             'retired': False, 'speech_qc_failed_retained': True,
                             'assigned_dialogue': shot['dialogue'],
                             'video': 'renders/retained/video.mp4',
                             'video_sha256': file_hash(video), 'created_at': 1}
            }})
            with patch('novel_h3.comfy.fingerprint', return_value='new-fingerprint'):
                rows = current_takes(root, episode)
            self.assertEqual(rows[0][2]['id'], 'retained')
            self.assertTrue(rows[0][2]['speech_qc_failed_retained'])


if __name__ == '__main__':
    unittest.main()
