import copy
import unittest

from novel_h3.director import h3_prompt
from novel_h3.fastvideo import request_payload
from novel_h3.ref2va import render, validate
from novel_h3.v2.compiler import graph


class GlobalRef2VATests(unittest.TestCase):
    def setUp(self):
        self.visuals = [dict(asset_id='actor', subject='<Subject 1>', picture='<Picture 1>', kind='character'),
                        dict(asset_id='room', subject='<Subject 2>', picture='<Picture 2>', kind='scene')]
        self.voices = [dict(asset_id='actor', audio='<Audio 1>', subject='<Subject 1>')]
        self.lines = [dict(speaker='actor', text='请进.')]
        self.sections = {
            'subject_definitions': '{subject:actor} is the man in {picture:actor}.\n{subject:room} is the room in {picture:room}.\n{audio:actor} is the voice-timbre reference for {subject:actor} (S1).',
            'summary': '[reference generation + audio reference] {subject:actor} invites the visitor inside.',
            'retention_analysis': '{subject:actor} (appears in [Shot 1]): fully_preserved - Retain identity.\n{subject:room} (appears in [Shot 1]): fully_preserved - Retain architecture.\n{audio:actor}: reference - Retain the voice.',
            'detailed_description': 'The target video is a realistic period drama.\n[Shot 1] {subject:actor} stands in {subject:room}. At 00:00.500, {subject:actor} (S1) says <d>[Chinese] 请进.</d> using the voice from {audio:actor}.',
            'overall_soundscape': 'Quiet indoor air.', 'non_diegetic_music': 'N/A'}

    def prompt(self, sections=None):
        return render(sections or self.sections, self.visuals, self.voices, self.lines, duration_seconds=5)

    def test_legacy_ref2va_uses_the_same_authored_contract(self):
        shot = dict(mode='ref2va', frames=124, references=[dict(asset_id='actor'), dict(asset_id='room')],
                    asset_package=dict(visual_assets=self.visuals),
                    speech_bindings=[dict(asset_id='actor', speaker='actor', picture=1, audio=1)],
                    dialogue=self.lines, ref2va_sections=self.sections)
        self.assertEqual(h3_prompt(shot, 'unused style'), self.prompt())

    def test_chinese_visible_text_is_allowed_but_chinese_directions_are_not(self):
        sections = copy.deepcopy(self.sections)
        sections['detailed_description'] += ' A sign reading "营业中" hangs by the door.'
        self.prompt(sections)
        sections['detailed_description'] += ' 他走向门口.'
        with self.assertRaisesRegex(ValueError, 'English'):
            self.prompt(sections)

    def test_audio_type_cannot_be_claimed_without_real_audio(self):
        with self.assertRaisesRegex(ValueError, 'actual audio inputs'):
            validate(self.prompt(), self.visuals, [], self.lines)

    def test_wrong_vocal_subject_and_inconsistent_audio_ids_are_rejected(self):
        sections = copy.deepcopy(self.sections)
        sections['detailed_description'] = sections['detailed_description'].replace('{subject:actor} (S1)', '{subject:room} (S1)')
        with self.assertRaisesRegex(ValueError, 'declared subject'):
            self.prompt(sections)
        sections = copy.deepcopy(self.sections)
        sections['subject_definitions'] = sections['subject_definitions'].replace('(S1)', '(S2)')
        with self.assertRaisesRegex(ValueError, 'speaker ID disagree'):
            self.prompt(sections)

    def test_cut_timing_and_retention_must_refer_to_actual_shots(self):
        sections = copy.deepcopy(self.sections)
        sections['detailed_description'] += '\n[Shot 2] At 00:06.000, the same doorway remains visible.'
        with self.assertRaisesRegex(ValueError, 'duration'):
            self.prompt(sections)
        sections = copy.deepcopy(self.sections)
        sections['retention_analysis'] = sections['retention_analysis'].replace('[Shot 1]', '[Shot 9]')
        with self.assertRaisesRegex(ValueError, 'absent shot'):
            self.prompt(sections)

    def test_both_runtime_boundaries_reject_tampering_before_loading_or_http(self):
        request = dict(prompt=self.prompt() + '\n伪造内容', visuals=self.visuals, voices=self.voices,
                       shot=dict(spoken_lines=self.lines), frames=124)
        with self.assertRaisesRegex(ValueError, 'English'):
            request_payload('/tmp', request)
        with self.assertRaisesRegex(ValueError, 'English'):
            graph(request, 'test')

    def test_unknown_task_and_unresolved_placeholders_are_rejected(self):
        sections = copy.deepcopy(self.sections)
        sections['summary'] = '[reference generation + invented task] A greeting.'
        with self.assertRaisesRegex(ValueError, 'task-type'):
            self.prompt(sections)
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            validate(self.prompt() + '\n{subject:missing}', self.visuals, self.voices, self.lines)


if __name__ == '__main__':
    unittest.main()
