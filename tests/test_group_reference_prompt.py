import copy
import unittest
from pathlib import Path

from novel_h3.director import h3_prompt
from novel_h3.project import read


class GroupReferencePromptTests(unittest.TestCase):
    def prompt_for(self, count, with_individual=False):
        root = Path(__file__).resolve().parents[1]
        shot = copy.deepcopy(read(root / 'examples/proof_tongtian.json')['shots'][0])
        shot.update(mode='ref2va', dialogue=[], references=[{
            'asset_id': 'officials', 'description': 'court officials',
            'lock': 'preserve approved identities and costumes',
        }], asset_package={'visual_assets': [{
            'kind': 'character', 'asset_id': 'officials', 'gender': '群体',
            'subject_label': 'Subject 1', 'picture_label': 'Picture 1',
            'selected_character_view': 'front', 'expected_instances': count,
        }]})
        if with_individual:
            shot['references'].append({'asset_id': 'scholar', 'description': 'one scholar', 'lock': 'same face'})
            shot['asset_package']['visual_assets'].append({
                'kind': 'character', 'asset_id': 'scholar', 'gender': '男',
                'subject_label': 'Subject 2', 'picture_label': 'Picture 2',
                'selected_character_view': 'front', 'expected_instances': 1,
            })
        return h3_prompt(shot, 'photorealistic period cinema')

    def test_group_reference_keeps_all_nine_member_bodies(self):
        prompt = self.prompt_for(9)
        self.assertIn('exactly 9 distinct members', prompt)
        self.assertIn('render exactly 9 member bodies once each', prompt)
        self.assertIn('Visible cast count: exactly 9 distinct character(s)', prompt)
        self.assertNotIn('render one instance only', prompt)
        self.assertNotIn('exactly one group asset', prompt)

    def test_single_character_keeps_the_existing_instance_lock(self):
        prompt = self.prompt_for(1)
        self.assertIn('render one instance only', prompt)
        self.assertNotIn('member bodies once each', prompt)

    def test_group_and_individual_use_total_bodies_without_slot_conflict(self):
        prompt = self.prompt_for(9, with_individual=True)
        self.assertIn('Visible cast count: exactly 10 distinct character(s)', prompt)
        self.assertIn('Each individual or group member may appear only once', prompt)
        self.assertNotIn('Subject slots cannot be reused', prompt)


if __name__ == '__main__':
    unittest.main()
