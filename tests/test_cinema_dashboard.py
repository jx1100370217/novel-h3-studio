import tempfile
import unittest
from pathlib import Path

from novel_h3.cinema_dashboard import enrich
from novel_h3.project import read, write


class CinemaDashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'production_v2/chapter'
        self.canonical = {'id': 'full', 'title': '考城隍', 'shots': [{'id': f'S{i:03}'} for i in range(50)]}
        self.plan_path = self.base / 'chapter_production_plan.json'
        write(self.plan_path, self.canonical)
        self.state = {'plan_path': str(self.plan_path.relative_to(self.root)), 'takes': {}}
        for shot in self.canonical['shots']:
            sid = shot['id']
            self.state['takes'][sid] = self.take(sid, 'full', True)
        write(self.base / 'production.json', self.state)

    def take(self, sid, plan, sound, name=None):
        tid = name or f'{plan}_{sid}'
        folder = self.base / 'takes' / tid
        write(folder / 'take.json', {'id': tid, 'shot_id': sid, 'plan_id': plan,
              'technical_qc': {'passed': True}, 'speech_screening': {'passed': sound},
              'status': 'rendered_pending_review', 'completed_at': 1})
        (folder / 'native.mp4').write_bytes(b'video')
        return tid

    def dashboard(self, active=None, **fields):
        data = {'status': 'editing', 'audio_passed': 0, **fields}
        return enrich(self.root, self.base / 'progress.json', active or self.canonical, data)

    def test_repair_batch_keeps_full_chapter_and_selects_actual_repair_results(self):
        for sid in ('S000', 'S001', 'S002'):
            self.state['takes'][sid] = self.take(sid, 'full', False)
        write(self.base / 'production.json', self.state)
        repair = {'id': 'repair', 'shots': self.canonical['shots'][:3]}
        repaired = {sid: self.take(sid, 'repair', True) for sid in ('S000', 'S001')}
        write(self.base / 'runs/repair.json', {'plan_id': 'repair', 'takes': repaired})
        # Unselected duplicate and old workflow material must not affect counts.
        self.take('S002', 'full', True, 'unselected_duplicate')
        self.take('S049', 'old_pilot', False)
        p = self.dashboard(repair, status='generating', shot='S002')
        self.assertEqual(p['counts']['planned'], 50)
        self.assertEqual(p['counts']['saved'], 50)
        self.assertEqual(p['counts']['sound_passed'], 49)
        self.assertEqual(p['active_batch']['total'], 3)
        self.assertEqual(p['active_batch']['completed'], 2)
        self.assertEqual(p['phase'], 'shot_repair')
        self.assertEqual(p['shots'][0]['take_id'], repaired['S000'])
        self.assertEqual(p['shots'][2]['status'], 'generating')
        self.assertEqual(p['shots'][49]['take_id'], 'full_S049')

    def test_export_and_sound_checks_never_imply_human_acceptance(self):
        video = self.root / 'review_exports/current.mp4'
        video.parent.mkdir()
        video.write_bytes(b'review')
        self.state['review'] = {'video': str(video.relative_to(self.root)),
                                'technical_qc': {'passed': True}, 'release_approved': False}
        write(self.base / 'production.json', self.state)
        p = self.dashboard()
        self.assertEqual(p['counts']['sound_passed'], 50)
        self.assertEqual(p['counts']['human_approved'], 0)
        self.assertTrue(p['review']['ready'])
        self.assertFalse(p['release_approved'])
        self.assertEqual(p['phase'], 'review_pending')
        self.assertEqual(p['stages'][-1]['current'], 0)
        video.unlink()
        self.assertFalse(self.dashboard()['review']['ready'])

    def test_visual_rework_is_reported_even_when_sound_passes_without_double_counting(self):
        for sid, sound, visual in [('S000', True, True), ('S001', False, True), ('S002', False, False)]:
            tid = self.take(sid, 'full', sound)
            path = self.base / 'takes' / tid / 'take.json'
            receipt = read(path)
            if visual:
                receipt['visual_review'] = {'status': 'needs_rework'}
            write(path, receipt)
        p = self.dashboard()
        self.assertEqual(p['counts']['sound_passed'], 48)
        self.assertEqual(p['counts']['needs_rework'], 3)
        self.assertEqual(p['shots'][0]['status'], 'needs_rework')
        self.assertTrue(p['shots'][0]['speech_passed'])
        self.assertTrue(p['shots'][0]['visual_rework'])
        self.assertEqual(p['shots'][1]['status'], 'needs_rework')
        self.assertFalse(p['shots'][2]['visual_rework'])
        self.assertEqual(p['counts']['human_approved'], 0)

    def test_missing_selected_media_does_not_count_as_saved(self):
        (self.base / 'takes/full_S000/native.mp4').unlink()
        self.assertEqual(self.dashboard()['counts']['saved'], 49)

    def test_user_rejected_story_overrides_technical_and_sound_success(self):
        video = self.root / 'review_exports/current.mp4'
        video.parent.mkdir(); video.write_bytes(b'review')
        self.state['review'] = {'video': str(video.relative_to(self.root)), 'video_sha256': 'same',
            'technical_qc': {'passed': True}, 'release_approved': True, 'human_listened': True}
        self.state['narrative_review'] = {'status': 'rejected', 'video_sha256': 'same'}
        write(self.base / 'production.json', self.state)
        p = self.dashboard()
        self.assertEqual(p['phase'], 'narrative_rework')
        self.assertTrue(p['review']['ready'])
        self.assertFalse(p['release_approved'])
        self.assertEqual(p['stages'][-1]['status'], 'failed')

    def test_old_rejection_does_not_apply_to_a_different_review_video(self):
        video = self.root / 'review_exports/current.mp4'
        video.parent.mkdir(); video.write_bytes(b'review')
        self.state['review'] = {'video': str(video.relative_to(self.root)), 'video_sha256': 'new',
            'technical_qc': {'passed': True}}
        self.state['narrative_review'] = {'status': 'rejected', 'video_sha256': 'old'}
        write(self.base / 'production.json', self.state)
        self.assertFalse(self.dashboard()['review']['narrative_rejected'])

    def test_explicit_reuse_from_a_previous_revision_is_counted_without_copying_media(self):
        folder = self.root / 'production_v2/previous/takes/old_candidate'
        write(folder / 'take.json', {'id': 'old_candidate', 'shot_id': 'S000', 'plan_id': 'previous',
              'technical_qc': {'passed': True}, 'speech_screening': {'passed': True}})
        (folder / 'native.mp4').write_bytes(b'old candidate')
        self.canonical['reused_takes'] = {'S000': str(folder.relative_to(self.root))}
        self.state['takes'].pop('S000')
        write(self.plan_path, self.canonical); write(self.base / 'production.json', self.state)
        p = self.dashboard()
        self.assertEqual(p['counts']['saved'], 50)
        self.assertEqual(p['shots'][0]['video'], str((folder / 'native.mp4').relative_to(self.root)))

    def test_dead_worker_does_not_appear_as_active_editing(self):
        p = self.dashboard(worker_pid=999999999)
        self.assertFalse(p['worker_alive'])
        self.assertEqual(p['phase'], 'interrupted')
        self.assertEqual(p['stages'][-2]['status'], 'failed')

    def test_canonical_selection_can_explicitly_reuse_a_pilot_take(self):
        tid = self.take('S000', 'pilot', True)
        self.state['takes'].pop('S000')
        self.canonical['reused_takes'] = {'S000': str((self.base / 'takes' / tid).relative_to(self.root))}
        write(self.plan_path, self.canonical)
        write(self.base / 'production.json', self.state)
        self.assertEqual(self.dashboard()['shots'][0]['take_id'], tid)
        self.assertEqual(self.dashboard()['counts']['saved'], 50)

    def test_pilot_without_canonical_production_state_still_displays(self):
        (self.base / 'production.json').unlink()
        self.plan_path.unlink()
        write(self.base / 'runs/full.json', {'plan_id': 'full', 'takes': {'S000': 'full_S000'}})
        p = self.dashboard()
        self.assertEqual(p['counts']['saved'], 1)
        self.assertFalse(p['active_batch']['is_repair'])

    def test_dashboard_lists_bound_story_and_per_shot_model_artifacts(self):
        self.canonical.update(chapter_id='chapter_s0003', cinematization={
            'path': 'production_v2/chapter/cinematic_screenplay.json'})
        write(self.plan_path, self.canonical)
        request = self.base / 'cinematization_request.json'
        source_plan = self.base / 'narrative/chapter_plan.json'
        source_script = self.base / 'narrative/screenplay.md'
        source_plan.parent.mkdir(parents=True)
        source_plan.write_text('{}', encoding='utf-8')
        source_script.write_text('# 白话剧本', encoding='utf-8')
        write(request, {'source_plan_path': str(source_plan.relative_to(self.root)),
                        'source_script_path': str(source_script.relative_to(self.root))})
        (self.base / 'cinematic_screenplay.json').write_text('{}', encoding='utf-8')
        (self.base / 'cinematic_screenplay.md').write_text('# 影视化剧本', encoding='utf-8')
        (self.base / 'cinematization_check.json').write_text('{}', encoding='utf-8')
        (self.base / 'narrative_contract.json').write_text('{}', encoding='utf-8')
        (self.base / 'narrative_script_check.json').write_text('{}', encoding='utf-8')
        (self.base / 'editorial_blueprint.json').write_text('{}', encoding='utf-8')
        (self.base / 'model_profile.json').write_text('{}', encoding='utf-8')
        (self.root / 'analysis').mkdir()
        (self.root / 'analysis/s0003.json').write_text('{}', encoding='utf-8')
        write(self.root / 'episodes/chapter_s0003.json', {'id': 'chapter_s0003', 'shots': self.canonical['shots']})
        (self.root / 'execution_sheets/chapter_s0003').mkdir(parents=True)
        (self.root / 'execution_sheets/chapter_s0003/S000.json').write_text('{}', encoding='utf-8')
        take_path = self.root / 'renders/legacy_S000'
        take_path.mkdir(parents=True)
        (take_path / 'h3_execution_sheet.json').write_text('{}', encoding='utf-8')
        (take_path / 'prompt.json').write_text('{}', encoding='utf-8')
        write(self.root / 'state.json', {'takes': {
            'legacy_S000': {'id': 'legacy_S000', 'episode': 'chapter_s0003', 'shot': 'S000',
                            'created_at': 1, 'retired': False}}})

        dashboard = self.dashboard()
        groups = {group['title']: group for group in dashboard['artifact_groups']}
        story_paths = {item['path'] for item in groups['原文与白话改编']['files']}
        shot_files = groups['逐镜模型输入']['shots'][0]['files']
        shot_paths = {item['path'] for item in shot_files}
        self.assertIn('production_v2/chapter/narrative/screenplay.md', story_paths)
        self.assertIn('production_v2/chapter/narrative/chapter_plan.json', story_paths)
        self.assertIn('execution_sheets/chapter_s0003/S000.json', shot_paths)
        self.assertIn('renders/legacy_S000/prompt.json', shot_paths)


if __name__ == '__main__':
    unittest.main()
