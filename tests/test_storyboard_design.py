import unittest

from novel_h3.storyboard_design import (fit_action_beats, fit_timeline_beats,
                                        h3_instruction, validate_scene_content,
                                        validate_shot)


class CinematicStoryboardTests(unittest.TestCase):
    def setUp(self):
        self.scene = {
            "scene_id": "E01",
            "source_ids": ["p1"],
            "source_text": "紫微走入大殿。",
            "scene_description": "The speaker reaches the marked council position and stops.",
            "characters_in_scene": ["紫微"],
            "scenes": ["太微殿"],
            "props": [],
            "utterances": [{"kind": "dialogue", "speaker": "紫微", "text": "已到。"}],
            "dramatic_function": "Complete the arrival and establish the speaker's location.",
        }
        self.shot = {
            "id": "E01",
            "frames": 73,
            "continuity": "cut",
            "dialogue": [{"kind": "dialogue", "speaker": "紫微", "text": "已到。"}],
            "references": [
                {"asset_id": "character_ziwei"},
                {"asset_id": "scene_hall"},
            ],
            "sequence_id": "council",
            "beat_function": "arrival",
            "state_in": "The speaker stands at the entrance.",
            "state_out": "The speaker stops at the left council seat.",
            "screen_direction": "forward toward the throne",
            "axis_id": "hall_center_aisle",
            "transition": "hard cut on the completed entrance",
            "blocking_plan": {
                "expected_actor_count": 1,
                "environment_only_allowed": False,
                "actors": [{"asset_id": "character_ziwei", "visible_throughout": True}],
            },
            "composition": {"primary_subject": "the bound speaker"},
            "action_beats": [
                {"start_frame": 0, "end_frame": 24, "action": "Enter."},
                {"start_frame": 24, "end_frame": 73, "action": "Stop and hold."},
            ],
        }

    def test_source_speaker_and_asset_checks_pass(self):
        paragraphs = {"p1": {"text": "紫微走入大殿。"}}
        assets = {"characters": {"紫微": {}}, "scenes": {"太微殿": {}}, "props": {}}
        self.assertEqual(validate_scene_content(self.scene, paragraphs, assets), [])
        self.assertEqual(validate_shot(self.scene, self.shot), [])

    def test_top_h3_frame_grid_is_allowed_but_oversize_is_rejected(self):
        self.shot["frames"] = 362
        self.shot["action_beats"] = [{"start_frame": 0, "end_frame": 362, "action": "Hold the authored pose."}]
        self.assertFalse(any("H3 输入不得超过" in error for error in validate_shot(self.scene, self.shot)))
        self.shot["frames"] = 363
        self.shot["action_beats"] = [{"start_frame": 0, "end_frame": 363, "action": "Hold the authored pose."}]
        self.assertTrue(any("H3 输入不得超过" in error for error in validate_shot(self.scene, self.shot)))

    def test_unbound_speaker_and_actor_count_fail(self):
        self.scene["characters_in_scene"] = []
        self.shot["blocking_plan"]["expected_actor_count"] = 0
        self.shot["blocking_plan"]["actors"] = []
        self.assertTrue(any("说话人必须绑定" in error for error in validate_scene_content(
            self.scene, {"p1": {"text": "紫微走入大殿。"}},
            {"characters": {"紫微": {}}, "scenes": {"太微殿": {}}, "props": {}}
        )))
        self.assertTrue(any("白模角色清单必须" in error for error in validate_shot(self.scene, self.shot)))

    def test_action_beats_are_rescaled_and_cover_delivery(self):
        beats = fit_action_beats([
            {"start_frame": 0, "end_frame": 48, "action": "Arrival."},
            {"start_frame": 48, "end_frame": 72, "action": "Arrival."},
            {"start_frame": 72, "end_frame": 120, "action": "Stop."},
        ], 73)
        self.assertEqual(beats[0]["start_frame"], 0)
        self.assertEqual(beats[-1]["end_frame"], 73)
        self.assertEqual([row["action"] for row in beats], ["Arrival.", "Stop."])
        self.assertEqual(h3_instruction({**self.shot, "action_beats": beats}).count("Arrival."), 1)

    def test_timeline_coalesces_repeated_description_and_retimes(self):
        beats = fit_timeline_beats([
            {"start_frame": 0, "end_frame": 24, "description": "A cloud glides forward."},
            {"start_frame": 24, "end_frame": 48, "description": "A cloud glides forward."},
            {"start_frame": 48, "end_frame": 72, "description": "The cloud settles."},
        ], 82)
        self.assertEqual([row["description"] for row in beats], ["A cloud glides forward.", "The cloud settles."])
        self.assertEqual(beats[-1]["end_frame"], 82)

    def test_repeated_adjacent_action_is_rejected(self):
        self.shot["action_beats"] = [
            {"start_frame": 0, "end_frame": 24, "action": "Enter."},
            {"start_frame": 24, "end_frame": 73, "action": "Enter."},
        ]
        self.assertTrue(any("相邻动作节拍重复" in error for error in validate_shot(self.scene, self.shot)))

    def test_group_instance_count_is_explicit_and_checked(self):
        actor = {"asset_id": "character_guards", "instances": 4, "visible_throughout": True}
        self.shot["references"] = [
            {"asset_id": "character_guards"}, {"asset_id": "character_ziwei"},
            {"asset_id": "scene_hall"},
        ]
        self.shot["dialogue"] = []
        self.shot["frames"] = 73
        self.shot["blocking_plan"] = {
            "expected_actor_count": 2, "expected_body_count": 4,
            "environment_only_allowed": False,
            "actors": [actor, {"asset_id": "character_ziwei", "instances": 1}],
        }
        self.scene["characters_in_scene"] = ["天兵", "紫微"]
        self.scene["utterances"] = []
        self.assertTrue(any("人物总数" in error for error in validate_shot(self.scene, self.shot)))
        self.shot["blocking_plan"]["expected_body_count"] = 5
        text = h3_instruction(self.shot)
        self.assertIn("exactly 4 members", text)
        self.assertIn("exact visible registered body count=5", text)

    def test_scene_fact_ids_must_belong_to_bound_source_paragraphs(self):
        scene = dict(self.scene, cinematic_storyboard_version="cinematic_storyboard_v2",
                     editorial_purpose="inciting_event", scene_goal="呈现异象",
                     turning_point="金光落地", story_beat_id="beat-1",
                     source_fact_ids=["p2"])
        errors = validate_scene_content(scene, {"p1": {"text": "紫微走入大殿。"}},
                                        {"characters": {"紫微": {}}, "scenes": {"太微殿": {}}, "props": {}})
        self.assertTrue(any("原文事实编号必须来自本镜头绑定的原文段落" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
