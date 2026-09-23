import unittest

from novel_h3.blender_previs import GUIDE_POLICY, environment_motion_cues


class BlenderEnvironmentMotionTests(unittest.TestCase):
    def test_disaster_action_beats_become_visible_ordered_cues(self):
        shot = {"action_beats": [
            {"start_frame": 0, "end_frame": 26, "action": "A lightning flash reveals the damaged roofline."},
            {"start_frame": 26, "end_frame": 42, "action": "Tiles shake and fall once."},
            {"start_frame": 42, "end_frame": 73, "action": "Dust settles after impact."},
        ]}
        cues = environment_motion_cues("disaster", shot)
        self.assertEqual([cue["kind"] for cue in cues],
                         ["lightning_flash", "roof_tile_fall", "dust_plume"])
        self.assertEqual([(cue["start_frame"], cue["end_frame"]) for cue in cues],
                         [(0, 26), (26, 42), (42, 73)])

    def test_water_and_geological_actions_are_distinct_single_events(self):
        wave = {"action_beats": [
            {"start_frame": 0, "end_frame": 27, "action": "Establish coast and distant waterline."},
            {"start_frame": 27, "end_frame": 66, "action": "The wave advances toward camera in one continuous front."},
            {"start_frame": 66, "end_frame": 107, "action": "Foam reaches shore."},
        ]}
        self.assertEqual([cue["kind"] for cue in environment_motion_cues("water", wave)], ["water_surge"])
        quake = {"action_beats": [
            {"start_frame": 0, "end_frame": 37, "action": "Hairline fracture runs across the slope."},
            {"start_frame": 37, "end_frame": 67, "action": "One slab slides into the opening."},
            {"start_frame": 67, "end_frame": 107, "action": "Dust expands and fills the far background."},
        ]}
        self.assertEqual([cue["kind"] for cue in environment_motion_cues("disaster", quake)],
                         ["mountain_fracture", "rock_slab_slide", "dust_plume"])

    def test_subject_from_shot_action_carries_across_pronoun_beat(self):
        shot = {
            "action": "Two separate gold trails descend from opposite quadrants toward the human horizon.",
            "action_beats": [
                {"start_frame": 0, "end_frame": 30, "action": "Two separate trails enter the upper frame."},
                {"start_frame": 30, "end_frame": 80, "action": "They descend on separate paths toward the horizon."},
            ],
        }
        cues = environment_motion_cues("disaster", shot)
        self.assertEqual([cue["kind"] for cue in cues], ["descending_light_trails"])
        self.assertEqual((cues[0]["start_frame"], cues[0]["end_frame"]), (30, 80))

    def test_reference_policy_requires_event_trajectory_and_timing(self):
        self.assertIn("start-to-end timing and trajectory", GUIDE_POLICY)
        self.assertIn("do not omit, replay, or invent", GUIDE_POLICY)


if __name__ == "__main__":
    unittest.main()
