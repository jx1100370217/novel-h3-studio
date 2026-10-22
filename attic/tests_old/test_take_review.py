import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3.comfy import REVIEW_ITEMS, review_take, review_chapter
from novel_h3.project import file_hash, load_state, update_state, write


class TakeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        video = self.root / 'renders/t/video.mp4'
        video.parent.mkdir(parents=True)
        video.write_bytes(b'review candidate')
        sha = file_hash(video)
        self.take = {
            'id': 't', 'episode': 'chapter_s1', 'shot': 'S1', 'status': 'rendered',
            'video': 'renders/t/video.mp4', 'video_sha256': sha, 'qc': {'passed': True},
            'review_required': 'pending_reviews', 'pending_reviews': ['av_sync_review'],
            'speech_check': {'passed': True, 'video_sha256': sha,
                             'speech_window_alignment': {'status': 'passed'},
                             'av_sync_review': {'status': 'not_evaluated', 'measurement': 'audio_only'}},
        }
        write(self.root / 'state.json', {'takes': {'t': self.take}, 'assets': {}, 'approvals': {}})
        self.checks = {key: True for key in REVIEW_ITEMS}

    def test_explicit_human_av_review_is_recorded_before_assembly(self):
        def assemble(root, episode):
            take = load_state(root)['takes']['t']
            self.assertEqual(take['status'], 'approved')
            self.assertEqual(take['av_sync_review']['video_sha256'], self.take['video_sha256'])
            self.assertEqual(take['av_sync_review']['method'], 'human')
            self.assertTrue(take['av_sync_review']['video_examined'])
            self.assertTrue(take['review_gates']['av_sync_review']['can_approve_av_sync'])
            self.assertEqual(take['pending_reviews'], [])
            self.assertEqual(take['approval_method'], 'human_viewing_and_listening')
        with patch('novel_h3.delivery_policy.maybe_assemble', side_effect=assemble) as compose:
            result = review_take(self.root, 't', True, '已实际看片听音，口型和动作音效正确', 'user', self.checks)
        self.assertEqual(result['status'], 'approved')
        compose.assert_called_once_with(self.root, 'chapter_s1')

    def test_legacy_eight_checks_fail_without_state_change(self):
        checks = dict(self.checks)
        checks.pop('av_sync')
        before = (self.root / 'state.json').read_bytes()
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            with self.assertRaisesRegex(ValueError, 'av_sync'):
                review_take(self.root, 't', True, '已看', 'user', checks)
            compose.assert_not_called()
        self.assertEqual((self.root / 'state.json').read_bytes(), before)

    def test_machine_reviewer_cannot_attest_human_review(self):
        for reviewer in ['Codex', 'Codex visual sampling', 'automatic_normal_queue', 'assistant']:
            with self.subTest(reviewer=reviewer), self.assertRaisesRegex(ValueError, '人工'):
                review_take(self.root, 't', True, '检查通过', reviewer, self.checks)
        self.assertEqual(load_state(self.root)['takes']['t']['status'], 'rendered')

    def test_failed_evidence_is_checked_before_approval_write(self):
        for field, value in [('speech_check', {'passed': False}), ('qc', {'passed': False}),
                             ('video_sha256', 'stale'), ('retired', True)]:
            with self.subTest(field=field):
                take = dict(self.take, **{field: value})
                update_state(self.root, lambda s: s['takes'].__setitem__('t', take))
                before = (self.root / 'state.json').read_bytes()
                with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
                    with self.assertRaises(ValueError):
                        review_take(self.root, 't', True, '已看', 'user', self.checks)
                    compose.assert_not_called()
                self.assertEqual((self.root / 'state.json').read_bytes(), before)

    def test_rejection_needs_no_av_or_transcript_approval_and_keeps_media(self):
        update_state(self.root, lambda s: s['takes']['t'].update(speech_check={'passed': False}))
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            result = review_take(self.root, 't', False, '口型错误，重拍', 'Codex visual sampling', {})
            compose.assert_not_called()
        self.assertEqual(result['status'], 'rework_queued')
        take = load_state(self.root)['takes']['t']
        self.assertEqual(take['status'], 'rejected')
        self.assertTrue(take['media_retained'])
        self.assertEqual(file_hash(self.root / take['video']), self.take['video_sha256'])

    def chapter_fixture(self):
        take = dict(self.take, id='t2', shot='S2')
        update_state(self.root, lambda s: s['takes'].__setitem__('t2', take))
        write(self.root / 'episodes/chapter_s1.json', {'id': 'chapter_s1', 'shots': [{'id': 'S1'}, {'id': 'S2'}]})

    def test_bulk_validates_last_take_before_any_approval_is_written(self):
        self.chapter_fixture()
        update_state(self.root, lambda s: s['takes']['t2'].update(speech_check={'passed': False}))
        before = (self.root / 'state.json').read_bytes()
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            with self.assertRaisesRegex(ValueError, '转写'):
                review_chapter(self.root, 'chapter_s1', True, '已看完', 'user', self.checks)
            compose.assert_not_called()
        self.assertEqual((self.root / 'state.json').read_bytes(), before)

    def test_bulk_human_approval_records_current_evidence_for_every_take(self):
        self.chapter_fixture()
        with patch('novel_h3.delivery_policy.maybe_assemble') as compose:
            review_chapter(self.root, 'chapter_s1', True, '逐镜观看并听音确认同步', 'user', self.checks)
            compose.assert_called_once_with(self.root, 'chapter_s1')
        state = load_state(self.root)
        for take in state['takes'].values():
            self.assertEqual(take['status'], 'approved')
            self.assertEqual(take['review']['scope'], 'chapter')
            self.assertEqual(take['av_sync_review']['method'], 'human')
            self.assertEqual(take['av_sync_review']['video_sha256'], take['video_sha256'])
            self.assertTrue(take['review']['checks']['av_sync'])
        self.assertIn('chapter:chapter_s1', state['approvals'])

    def test_bulk_legacy_or_machine_review_cannot_partially_approve(self):
        self.chapter_fixture()
        before = (self.root / 'state.json').read_bytes()
        legacy = dict(self.checks)
        legacy.pop('av_sync')
        for reviewer, checks in [('user', legacy), ('Codex', self.checks)]:
            with self.subTest(reviewer=reviewer), self.assertRaises(ValueError):
                review_chapter(self.root, 'chapter_s1', True, '审阅', reviewer, checks)
            self.assertEqual((self.root / 'state.json').read_bytes(), before)

    def test_not_applicable_requires_explicit_human_choice_and_note(self):
        self.chapter_fixture()
        checks = dict(self.checks, av_sync='not_applicable')
        with self.assertRaisesRegex(ValueError, '意见'):
            review_chapter(self.root, 'chapter_s1', True, '', 'user', checks)
        with patch('novel_h3.delivery_policy.maybe_assemble'):
            review_chapter(self.root, 'chapter_s1', True, '实际观看，本章是无人物的静默风景，无口型可审核', 'user', checks)
        for take in load_state(self.root)['takes'].values():
            self.assertEqual(take['av_sync_review']['status'], 'not_applicable')
            self.assertEqual(take['av_sync_review']['method'], 'human')
            self.assertTrue(take['av_sync_review']['video_examined'])
        # An audio detector's finding never creates this manual exemption.
        take = dict(self.take, speech_check={**self.take['speech_check'], 'speech_gate': {'speech_detected': False}})
        update_state(self.root, lambda s: s['takes'].__setitem__('t', take))
        old_checks = dict(self.checks)
        old_checks.pop('av_sync')
        with self.assertRaisesRegex(ValueError, 'av_sync'):
            review_take(self.root, 't', True, 'ASR无声音', 'user', old_checks)


if __name__ == '__main__':
    unittest.main()
