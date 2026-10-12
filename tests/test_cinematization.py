from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.project import file_hash, read, write
from novel_h3.v2.cinematization import accept, prepare, require, validate
from novel_h3.v2.production import produce


class CinematizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'old/chapter_plan.json'
        self.directory = self.root / 'new'
        write(self.root / 'paragraphs.json', [{'id': 'p1', 'section': 's1', 'text': '病卧。'},
            {'id': 'p2', 'section': 's1', 'text': '守约而去。'}])
        self.plan = {'id': 'film', 'chapter_id': 'chapter_s1', 'source_paragraph_ids': ['p1', 'p2'],
            'source_fact_ledger': [{'id': 'F1'}, {'id': 'F2'}], 'scenes': [{
                'id': 'SC1', 'title': '赴约', 'source_paragraph_ids': ['p1', 'p2'],
                'goal': '照顾母亲', 'conflict': '任命临身', 'turn': '获准缓任',
                'change': '守约赴任', 'causal_transition': '期满而去', 'script': '母终后，宋焘赴约。'}],
            'shots': []}
        for i in range(2):
            self.plan['shots'].append({'id': f'S{i}', 'scene_id': 'room', 'narrative_scene_id': 'SC1',
                'source_paragraph_ids': [f'p{i+1}'], 'facts': [f'F{i+1}'], 'cast': ['actor'],
                'action': 'He walks toward the door.' if i == 0 else 'He leaves through the door.',
                'start_state': 'Seated.' if i == 0 else 'Standing at the door.',
                'end_state': 'Standing at the door.' if i == 0 else 'Outside.',
                'camera': 'Fixed eye-level frame.', 'eyeline': 'Toward the door.', 'soundscape': 'Footsteps.',
                'spoken_lines': [], 'duration_seconds': 5, 'cinematic_execution': {
                    'beat_id': f'B{i}', 'axis_id': 'bed_door', 'screen_direction': 'left to right',
                    'transition': {'type': 'opening' if i == 0 else 'continuous',
                        'previous_shot_id': None if i == 0 else 'S0',
                        'reason': 'Finish the farewell.', 'audience_cue': 'The same open doorway remains visible.'}}})
        write(self.source, self.plan)
        self.request_path = prepare(self.root, self.source, self.directory)
        self.request = read(self.request_path)

    def accept(self):
        return accept(self.root, self.directory, {'request_sha256': file_hash(self.request_path),
            'plan': self.plan, 'editorial_notes': '读完两段，按告别行动连续编排，成片尚待审阅。'})

    def test_complete_source_is_required_before_preparation(self):
        changed = deepcopy(self.plan); changed['source_paragraph_ids'] = ['p1']
        write(self.source, changed)
        with self.assertRaisesRegex(ValueError, 'complete chapter'):
            prepare(self.root, self.source, self.root / 'other')

    def test_continuous_action_cannot_reset_or_reverse_axis(self):
        for field, value in [('start_state', 'Seated.'), ('scene_id', 'different_room')]:
            changed = deepcopy(self.plan); changed['shots'][1][field] = value
            with self.assertRaises(ValueError): validate(self.request, changed)
        changed = deepcopy(self.plan)
        changed['shots'][1]['cinematic_execution']['screen_direction'] = 'right to left'
        with self.assertRaisesRegex(ValueError, 'axis'): validate(self.request, changed)

    def test_transition_must_identify_the_real_predecessor(self):
        self.plan['shots'][1]['cinematic_execution']['transition']['previous_shot_id'] = 'unrelated'
        with self.assertRaisesRegex(ValueError, 'previous shot'): validate(self.request, self.plan)

    def test_missing_ending_scene_or_empty_cue_is_rejected(self):
        changed = deepcopy(self.plan); changed['scenes'][0]['source_paragraph_ids'] = ['p1']
        with self.assertRaisesRegex(ValueError, 'ending'): validate(self.request, changed)
        changed = deepcopy(self.plan); changed['shots'][1]['cinematic_execution']['transition']['audience_cue'] = ''
        with self.assertRaisesRegex(ValueError, 'nonempty'): validate(self.request, changed)

    def test_frozen_audio_timing_is_allowed_but_changed_action_and_words_are_not(self):
        plan = read(self.accept())
        plan['shots'][0]['duration_seconds'] = 7
        plan['shots'][0]['audio_target'] = {'path': 'audio.wav'}
        self.assertTrue(require(self.root, plan)['passed'])
        plan['shots'][0]['action'] = 'He unexpectedly jumps out of a window.'
        with self.assertRaisesRegex(ValueError, 'action or dialogue'): require(self.root, plan)

    def test_source_or_artifact_change_invalidates_the_handoff(self):
        plan = read(self.accept())
        write(self.source, dict(self.plan, title='Changed adaptation'))
        with self.assertRaisesRegex(ValueError, 'Source changed'): require(self.root, plan)
        write(self.source, self.plan)
        write(self.directory / 'cinematic_screenplay.json', {})
        with self.assertRaisesRegex(ValueError, 'binding is stale'): require(self.root, plan)

    def test_reference_scope_cannot_change_after_the_screenplay_binding(self):
        plan = read(self.accept())
        plan['shots'][0]['visual_reference_scope'] = 'props_only'
        with self.assertRaisesRegex(ValueError, 'action or dialogue'):
            require(self.root, plan)

    def test_static_prompt_focus_cannot_change_after_the_screenplay_binding(self):
        plan = read(self.accept())
        plan['shots'][0]['generation_prompt_focus'] = 'static_prop'
        with self.assertRaisesRegex(ValueError, 'action or dialogue'):
            require(self.root, plan)

    def test_missing_handoff_blocks_production_before_gpu_or_audio(self):
        write(self.root / 'config.json', {})
        with patch('novel_h3.v2.narrative.preflight'), patch('novel_h3.v2.production.api') as api, \
                patch('novel_h3.v2.production.job') as job:
            with self.assertRaisesRegex(ValueError, 'Missing filmable screenplay'):
                produce(self.root, self.source, 1)
            api.assert_not_called(); job.assert_not_called()

    def test_structure_does_not_claim_viewer_comprehension(self):
        plan = read(self.accept())
        report = require(self.root, plan)
        self.assertFalse(report['human_understood_story'])
        self.assertFalse(report['release_approved'])

    def test_direct_chapter_render_cannot_skip_the_filmable_handoff(self):
        from novel_h3.v2.runner import run
        plan = dict(self.plan, narrative_contract_required=True)
        write(self.source, plan)
        with patch('novel_h3.v2.narrative.preflight'), \
                patch('novel_h3.v2.runner.config', return_value={'comfy_url': 'unused'}), \
                patch('novel_h3.v2.runner.api') as api:
            with self.assertRaisesRegex(ValueError, 'Missing filmable screenplay'):
                run(self.root, self.source, None, 1)
            api.assert_not_called()

    def test_compiler_cannot_bypass_binding_with_a_separate_changed_shot(self):
        from novel_h3.v2.compiler import compile_shot
        plan = read(self.accept())
        changed = deepcopy(plan['shots'][0]); changed['action'] = 'Unrelated action.'
        with self.assertRaisesRegex(ValueError, 'Requested shot differs'):
            compile_shot(self.root, plan, changed, 1)


if __name__ == '__main__': unittest.main()
