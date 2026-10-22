import copy
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from novel_h3.comfy import bound_shot, compile_execution_sheet
from novel_h3.director import character_visibility_policy, h3_prompt, soundscape_for
from novel_h3.project import read, write
from novel_h3.shot_package import compile_package


class CastSoundscapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        write(self.root / 'config.json', {'style': 'photorealistic period cinema', 'blender_previs': {'enabled': False}})
        write(self.root / 'bible/assets.json', {
            'characters': {'Song': {'id': 'song', 'gender': '男'},
                           'Officials': {'id': 'officials', 'gender': '群体'}},
            'scenes': {'Room': {'id': 'room'}}, 'props': {},
        })

    def shot(self, count=1, with_character=True):
        aid = 'officials' if count > 1 else 'song'
        refs = ([{'asset_id': aid, 'description': 'registered character', 'lock': 'same approved appearance'}]
                if with_character else [])
        refs.append({'asset_id': 'room', 'description': 'period room', 'lock': 'same room'})
        return {'id': 'S001', 'mode': 'ref2va', 'scene_id': 'room', 'continuity': 'cut', 'frames': 124,
                'action': 'The registered actor lies on the bed, remaining motionless.',
                'visual_narration': '', 'soundscape': 'Quiet room tone, breathing and small cloth movements.',
                'camera': {'size': 'wide', 'lens_mm': 35, 'movement': 'locked tripod', 'motivation': 'illness'},
                'timeline': [{'start_frame': 0, 'end_frame': 124, 'description': 'Hold the authored pose.'}],
                'handoff_in': 'Actor rests on bed.', 'handoff_out': 'The same actor rests on bed.',
                'dialogue': [], 'references': refs,
                'blocking_plan': {'actors': ([{'asset_id': aid, 'subject_label': 'bound reference slot 1',
                                             'instances': count, 'pose': 'reclining', 'path': []}]
                                            if with_character else [])}}

    def resolved(self, ref, *args):
        return {'asset_id': ref['asset_id'], 'source_sha256': 'a' * 64,
                'generation_path': ref['asset_id'] + '.png', 'generation_sha256': ref['asset_id'] + '-hash',
                'variant': 'front', 'selected_view': 'front', 'selected_view_label': '正面'}

    def package(self, shot):
        visuals = [self.resolved(ref) for ref in shot['references']]
        return compile_package(self.root, shot, visuals, []), visuals

    def test_explicit_indoor_soundscape_ignores_classical_says_prose(self):
        excerpts = ['见吏人持牒，牵白颠马来，云：“请赴试。”',
                    '俄题纸飞下，视之有八字，云：“一人二人，有心无心。”',
                    '公文中有云：“有心为善，虽善不赏。无心为恶，虽恶不罚。”',
                    '二公文成，呈殿上。公文中有云：“有心为善，虽善不赏。”诸神传赞不已。']
        for prose in excerpts:
            with self.subTest(prose=prose):
                brief = soundscape_for({'action': 'A question paper flies down once.', 'visual_narration': prose,
                                        'soundscape': 'Quiet indoor room tone and soft paper rustle.', 'dialogue': []})
                self.assertIn('Quiet indoor room tone and soft paper rustle', brief)
                self.assertNotIn('high-altitude', brief)
                self.assertNotIn('energy whoosh', brief)
                self.assertNotIn(prose, brief)

    def test_explicit_real_cloud_flight_soundscape_is_retained(self):
        cue = 'High-altitude wind rush and one focused non-musical energy whoosh.'
        self.assertIn(cue, soundscape_for({'action': '腾云一次', 'soundscape': cue, 'dialogue': []}))

    def test_fallback_uses_visible_action_not_source_quotation(self):
        brief = soundscape_for({'action': 'The clerk holds the summons.',
                                'visual_narration': '云：“请赴试。”', 'dialogue': []})
        self.assertNotIn('high-altitude', brief)
        self.assertNotIn('energy whoosh', brief)
        self.assertIn('high-altitude', soundscape_for({'action': '腾云离去', 'dialogue': []}))

    def test_silent_bound_one_forbids_any_background_or_foreground_extra(self):
        shot = self.shot()
        package, visuals = self.package(shot)
        prompt_shot = dict(shot, speech_bindings=[], asset_package=package)
        prompt = h3_prompt(prompt_shot, 'cinema')
        self.assertEqual(package['visible_body_count'], 1)
        self.assertFalse(package['interaction_contract']['unregistered_humans_allowed'])
        self.assertTrue(package['character_identity_lock']['no_unbound_or_duplicate_bodies'])
        self.assertIn('exactly 1 bound character bodies in the entire frame', prompt)
        self.assertIn('even if distant, silent or non-identifiable', prompt)
        self.assertNotIn('if visually motivated', prompt)
        self.assertNotIn('complete foreground cast', prompt)
        with patch('novel_h3.comfy.bound_shot', return_value=(prompt_shot, visuals, package)):
            _, _, sheet, _ = compile_execution_sheet(self.root, {'id': 'episode'}, shot, persist=False)
        self.assertEqual(sheet['quality_gate']['exact_visible_human_body_count'], 1)
        self.assertTrue(sheet['quality_gate']['unregistered_humans_forbidden'])
        self.assertFalse(sheet['quality_gate']['non_dialogue_extras_must_be_silent_and_background_only'])

    def test_zero_bound_people_cannot_become_unregistered_background_people(self):
        shot = self.shot(with_character=False)
        package, _ = self.package(shot)
        self.assertEqual(package['visible_body_count'], 0)
        self.assertFalse(package['interaction_contract']['unregistered_humans_allowed'])
        self.assertIn('zero character bodies', character_visibility_policy(0, False))

    def test_spatial_guide_preserves_geography_without_copying_proxy_joint_motion(self):
        shot = self.shot()
        package, _ = self.package(shot)
        shot.update(speech_bindings=[], asset_package=package,
                    spatial_guide={'guide_policy': 'Retain authored camera and actor roots.'})
        prompt = h3_prompt(shot, 'cinema')
        self.assertIn('Retain authored camera and actor roots.', prompt)
        self.assertIn('do not copy idle hands, rigid legs, sliding feet or proxy joint mechanics', prompt)
        self.assertIn('exactly once per authored action beat while preserving cast and root geography', prompt)
        del shot['spatial_guide']
        self.assertNotIn('proxy joint mechanics', h3_prompt(shot, 'cinema'))

    def test_dialogue_prompt_removes_chinese_production_labels_without_placeholder(self):
        shot = self.shot()
        text = '文宗未临，何遽得考？'
        shot.update(storyboard_schema='cinematic_storyboard_v2', beat_function='疑问反应',
                    transition={'type': '直接切', 'reason': '承接宋焘提问'}, state_in='宋焘卧床',
                    state_out='宋焘提出疑问', action_beats=[{'start_frame': 0, 'end_frame': 124,
                    'action': 'The actor raises his eyes once. 中文节奏标签'}],
                    scene_continuity_contract={'prompt': 'Fixed mark (-1.5, 1, 0); 宋焘; same eyeline.'},
                    dialogue=[{'speaker': '宋焘', 'text': text, 'start_frame': 24, 'end_frame': 96}])
        shot['blocking_plan']['actors'][0]['path'] = [{'mark': '病床南侧'}, {'mark': '保持宋焘原位'}]
        original = copy.deepcopy(shot)
        package, _ = self.package(shot)
        prompt = h3_prompt(dict(shot, asset_package=package, speech_bindings=[{
            'speaker': '宋焘', 'speaker_label': 'S1', 'picture': 1, 'audio': 1}]), 'cinema')
        self.assertEqual(re.findall(r'<d>\[Chinese\] (.*?)</d>', prompt), [text])
        self.assertEqual(prompt.count(text), 1)
        self.assertNotIn('visual metadata', prompt.lower())
        self.assertNotRegex(re.sub(r'<d>.*?</d>', '', prompt), r'[\u3400-\u9fff]')
        self.assertIn('The actor raises his eyes once.', prompt)
        self.assertIn('Fixed mark (-1.5, 1, 0)', prompt)
        self.assertEqual(shot, original)

    def test_silent_prompt_removes_chinese_beats_and_marks_without_speech_source(self):
        shot = self.shot()
        shot.update(storyboard_schema='cinematic_storyboard_v2', beat_function='沉默反应',
                    transition={'type': '直接切', 'reason': '承接病卧'}, state_in='宋焘卧床',
                    state_out='宋焘保持沉默', action_beats=[{'start_frame': 0, 'end_frame': 124,
                    'action': 'The actor lifts his eyes once. 中文节奏标签'}],
                    visual_narration='俄题纸飞下，视之有八字，云：“一人二人，有心无心。”',
                    scene_continuity_contract={'prompt': 'Fixed mark (-1.5, 1, 0); 宋焘; same eyeline.'})
        shot['blocking_plan']['actors'][0]['path'] = [{'mark': '病床南侧'}, {'mark': '保持宋焘原位'}]
        original = copy.deepcopy(shot)
        package, _ = self.package(shot)
        prompt = h3_prompt(dict(shot, asset_package=package, speech_bindings=[]), 'cinema')
        self.assertNotRegex(prompt, r'[\u3400-\u9fff]')
        self.assertNotIn('<d>', prompt)
        self.assertNotIn('visual metadata', prompt.lower())
        self.assertIn('HUMAN_VOICE_ALLOWLIST=[]', prompt)
        self.assertIn('The actor lifts his eyes once.', prompt)
        self.assertIn('Fixed mark (-1.5, 1, 0)', prompt)
        self.assertEqual(shot, original)

    def test_real_package_group_keeps_nine_in_identity_and_camera_contracts(self):
        shot = self.shot(count=9)
        package, _ = self.package(shot)
        prompt = h3_prompt(dict(shot, speech_bindings=[], asset_package=package), 'cinema')
        self.assertEqual(package['visible_body_count'], 9)
        self.assertEqual(package['identity_bindings'][0]['expected_instances'], 9)
        self.assertEqual(package['interaction_contract']['mode'], 'multi_character')
        self.assertIn('exactly 9 bound character bodies', package['character_visibility_policy'])
        self.assertIn('exactly 9 distinct members', prompt)
        self.assertIn('exactly 9 distinct member bodies, each once', prompt)
        self.assertNotIn('one body only', prompt)
        self.assertNotIn('one silent listener body', prompt)
        self.assertNotIn('single bound character visibly present', prompt)

    def test_scene_reorder_updates_geometry_subject_labels_only_in_generated_copy(self):
        for count in (1, 9):
            with self.subTest(count=count):
                shot = self.shot(count=count)
                original = copy.deepcopy(shot)
                with patch('novel_h3.comfy.generation_reference', side_effect=lambda root, ref, *args: self.resolved(ref)), \
                     patch('novel_h3.voices.bindings', return_value=[]), \
                     patch('novel_h3.scene_continuity.contract', return_value={}):
                    generated, _, package = bound_shot(self.root, shot)
                self.assertEqual([r['asset_id'] for r in generated['references']], ['room', 'officials' if count > 1 else 'song'])
                self.assertEqual(generated['blocking_plan']['actors'][0]['subject_label'], 'Subject 2')
                self.assertEqual(package['identity_bindings'][0]['subject_label'], 'Subject 2')
                self.assertEqual(package['identity_bindings'][0]['picture_label'], 'Picture 2')
                self.assertEqual(shot, original)
                generated['storyboard_schema'] = 'cinematic_storyboard_v2'
                prompt = h3_prompt(generated, 'cinema')
                self.assertIn('Subject 2: exactly', prompt)
                self.assertNotIn('bound reference slot 1:', prompt)

    def test_sixth_group_slot_becomes_actual_seventh_subject_after_scene_reorder(self):
        inventory = read(self.root / 'bible/assets.json')
        for index in range(4):
            inventory['characters'][f'Extra {index}'] = {'id': f'extra_{index}', 'gender': '男'}
        write(self.root / 'bible/assets.json', inventory)
        shot = self.shot(count=9)
        ids = ['song', 'extra_0', 'extra_1', 'extra_2', 'extra_3', 'officials', 'room']
        shot['references'] = [{'asset_id': aid, 'description': 'approved reference', 'lock': 'same identity'} for aid in ids]
        shot['blocking_plan']['actors'] = [
            {'asset_id': aid, 'subject_label': f'bound reference slot {index}',
             'instances': 9 if aid == 'officials' else 1, 'pose': 'seated', 'path': []}
            for index, aid in enumerate(ids[:-1], 1)]
        original = copy.deepcopy(shot)
        with patch('novel_h3.comfy.generation_reference', side_effect=lambda root, ref, *args: self.resolved(ref)), \
             patch('novel_h3.voices.bindings', return_value=[]), \
             patch('novel_h3.scene_continuity.contract', return_value={}):
            generated, _, package = bound_shot(self.root, shot)
        group = next(a for a in generated['blocking_plan']['actors'] if a['asset_id'] == 'officials')
        self.assertEqual(group['subject_label'], 'Subject 7')
        self.assertEqual(package['visible_body_count'], 14)
        self.assertEqual(shot, original)


if __name__ == '__main__':
    unittest.main()
