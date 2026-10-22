import copy
import unittest
from unittest.mock import patch

from novel_h3.fastvideo import request_payload
from novel_h3.ref2va import render, validate, with_population
from novel_h3.v2.compiler import graph


class Ref2VAPopulationTests(unittest.TestCase):
    def setUp(self):
        self.visuals = [
            dict(asset_id='actor', subject='<Subject 1>', picture='<Picture 1>',
                 kind='character', instances=1, generation_sha256='actor-pixels'),
            dict(asset_id='room', subject='<Subject 2>', picture='<Picture 2>',
                 kind='scene', generation_sha256='room-pixels'),
        ]
        self.sections = {
            'subject_definitions': '<Subject 1> is the man in <Picture 1>.\n'
                                   '<Subject 2> is the empty room in <Picture 2>.',
            'summary': '[reference generation] <Subject 1> waits in <Subject 2>.',
            'retention_analysis': '<Subject 1> (appears in [Shot 1]): fully_preserved - Retain identity.\n'
                                  '<Subject 2> (appears in [Shot 1]): fully_preserved - Retain architecture.',
            'detailed_description': 'The target video is a realistic period drama.\n'
                                    '[Shot 1] <Subject 1> waits beside the window in <Subject 2>.',
            'overall_soundscape': 'Quiet indoor air and soft cloth movement.',
            'non_diegetic_music': 'N/A',
        }

    def prompt(self, visuals=None, sections=None, additional_visible_people=()):
        return render(sections or self.sections, self.visuals if visuals is None else visuals,
                      [], [], duration_seconds=5,
                      additional_visible_people=additional_visible_people)

    def assert_population(self, prompt, count):
        expected = (f'Visible population: exactly {count} people in this shot, '
                    'including partly visible bodies.')
        self.assertIn(expected, prompt.split('detailed_description:\n', 1)[1])
        self.assertEqual(prompt.count(expected), 1)

    def test_authored_sections_always_receive_single_person_population(self):
        prompt = self.prompt()
        self.assert_population(prompt, 1)
        self.assertIn('<Subject 1> waits beside the window in <Subject 2>.', prompt)
        self.assertIn('non_diegetic_music:\nN/A', prompt)

    def test_ensemble_counts_member_bodies_instead_of_reference_images(self):
        visuals = copy.deepcopy(self.visuals)
        visuals[0]['instances'] = 3
        sections = copy.deepcopy(self.sections)
        sections['subject_definitions'] = sections['subject_definitions'].replace(
            'the man in', 'the three distinct relatives in')
        self.assert_population(self.prompt(visuals, sections), 3)

    def test_offscreen_identity_reference_does_not_add_a_visible_person(self):
        visuals = copy.deepcopy(self.visuals)
        visuals[0]['visible'] = False
        sections = copy.deepcopy(self.sections)
        sections['detailed_description'] = ('The target video is a realistic period drama.\n'
            '[Shot 1] <Subject 2> remains empty; <Subject 1> stays entirely outside the frame.')
        self.assert_population(self.prompt(visuals, sections), 0)

    def test_authored_partial_body_is_counted_once(self):
        extras = ['one messenger whose hand extends from the left edge']
        prompt = self.prompt(additional_visible_people=extras)
        self.assert_population(prompt, 2)
        validate(prompt, self.visuals, [], [], duration_seconds=5,
                 additional_visible_people=extras)

    def test_missing_population_is_rejected_at_fastvideo_submission_boundary(self):
        # Reproduce the old authored-prompt bypass by removing its generated
        # paragraph without changing the otherwise valid official sections.
        prompt = self.prompt()
        paragraph = ('Visible population: exactly 1 people in this shot, '
                     'including partly visible bodies.')
        request = dict(prompt=prompt.replace(paragraph, ''), visuals=self.visuals,
                       voices=[], shot=dict(spoken_lines=[]), frames=124)
        with patch('urllib.request.urlopen') as http:
            with self.assertRaisesRegex(ValueError, '(?i)population'):
                request_payload('/tmp', request)
            http.assert_not_called()

    def test_population_cannot_be_changed_by_tampering_with_authored_text(self):
        prompt = self.prompt().replace('exactly 1 people', 'exactly 2 people')
        with self.assertRaisesRegex(ValueError, '(?i)population'):
            validate(prompt, self.visuals, [], [])

    def test_repeated_asset_and_repeated_pixels_are_rejected(self):
        prompt = self.prompt()
        visuals = copy.deepcopy(self.visuals)
        visuals[1]['asset_id'] = visuals[0]['asset_id']
        with self.assertRaisesRegex(ValueError, '(?i)(duplicate|repeated)'):
            validate(prompt, visuals, [], [])
        visuals = copy.deepcopy(self.visuals)
        visuals[1]['generation_sha256'] = visuals[0]['generation_sha256']
        with self.assertRaisesRegex(ValueError, '(?i)(duplicate|repeated)'):
            validate(prompt, visuals, [], [])

    def test_population_can_be_applied_again_without_duplicate_paragraphs(self):
        prompt = self.prompt()
        self.assertEqual(with_population(prompt, self.visuals), prompt)

    def test_submission_cannot_skip_population_by_removing_kind(self):
        request = dict(prompt=self.prompt(), visuals=copy.deepcopy(self.visuals), voices=[],
                       shot=dict(spoken_lines=[]), frames=124)
        for kind in (None, 'visual'):
            request['visuals'][0]['kind'] = kind
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, 'population metadata'):
                    request_payload('/tmp', request)
                with self.assertRaisesRegex(ValueError, 'population metadata'):
                    graph(request, 'test')

    def test_population_labels_do_not_substitute_for_actual_body_binding(self):
        sections = copy.deepcopy(self.sections)
        sections['detailed_description'] = 'A realistic period drama.\n[Shot 1] The empty <Subject 2> remains still.'
        with self.assertRaisesRegex(ValueError, 'actual appearance'):
            self.prompt(sections=sections)


if __name__ == '__main__':
    unittest.main()
