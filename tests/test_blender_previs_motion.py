import unittest

from novel_h3.blender_previs import GUIDE_POLICY, _blocking, _scene_kind, environment_motion_cues


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

    def test_grounded_city_light_and_courtyard_do_not_become_cloud_road_or_hall(self):
        self.assertEqual(_scene_kind("city", {"name": "异境城郭",
                         "design_description": "Walled city, cloud-filtered light and palace roofs."}), "landscape")
        self.assertEqual(_scene_kind("washing", {"name": "宋家洗濯处",
                         "design_description": "Family home courtyard, basin beside room threshold."}), "interior")
        self.assertEqual(_scene_kind("cloud", {"name": "太微宫外云路"}), "celestial_exterior")

    def test_pose_transition_and_group_positions_survive_spec_blocking(self):
        plan = {"asset_id": "scholars", "start_position": {"x": 0, "y": -6, "z": 0},
                "pose": "standing", "pose_out": "seated", "heading": 3.141592653589793,
                "pose_transition": {"start_frame": 30, "end_frame": 42}, "instances": 2,
                "pose_keyframes": [{"frame": 0, "pose": "standing"}, {"frame": 42, "pose": "seated"}],
                "heading_keyframes": [{"frame": 0, "heading": 3.141592653589793}, {"frame": 42, "heading": 0}],
                "instance_layout": [{"offset": {"x": -1, "y": 0, "z": 0}},
                                    {"offset": {"x": 1, "y": 0, "z": 0}}]}
        actor = _blocking({}, [{"id": "scholars", "name": "秀才"}], "hall",
                          {"blocking_plan": {"actors": [plan]}})[0]
        self.assertEqual(actor["pose_out"], "seated")
        self.assertEqual(actor["heading"], plan["heading"])
        self.assertEqual(actor["pose_transition"], plan["pose_transition"])
        self.assertEqual(actor["pose_keyframes"], plan["pose_keyframes"])
        self.assertEqual(actor["heading_keyframes"], plan["heading_keyframes"])
        self.assertEqual(actor["instance_layout"], plan["instance_layout"])


if __name__ == "__main__":
    unittest.main()
