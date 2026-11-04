import copy

from novel_h3.continuity_bible import audit_bible


def base_bible(tmp_path):
    (tmp_path / "previs").mkdir()
    (tmp_path / "previs" / "S01A.png").write_bytes(b"x")
    (tmp_path / "previs" / "S01B.png").write_bytes(b"x")
    shot_a = {
        "shot_id": "S01A", "open_state": "Xu sits", "close_state": "Xu stands",
        "cast": ["xu"], "costume_state": {"xu": "gray robe"}, "prop_state": {"cup": "full"},
        "hand_ownership": "Xu's right hand", "eyeline": "Xu looks at Wang",
        "axis_side": "Xu left, Wang right", "screen_direction": "Xu rises",
        "light_state": "night lantern", "time_state": "night",
        "anchor_image": "previs/S01A.png", "continuity_in": "scene start",
        "continuity_out": "Xu stands",
    }
    shot_b = {
        "shot_id": "S01B", "open_state": "Xu stands", "close_state": "Xu turns",
        "cast": ["xu", "wang"], "costume_state": {"xu": "gray robe", "wang": "blue robe"},
        "prop_state": {"cup": "empty"}, "hand_ownership": "Wang's right hand",
        "eyeline": "Wang looks at Xu", "axis_side": "Xu left, Wang right",
        "screen_direction": "Wang enters from right", "light_state": "night lantern",
        "time_state": "night", "anchor_image": "previs/S01B.png",
        "continuity_in": "Xu stands", "continuity_out": "Xu turns",
    }
    return {
        "version": "1.0", "project_id": "test",
        "scenes": [{
            "scene_id": "S01", "sequence_id": "Q1", "story_day": 1, "time_of_day": "night",
            "location": "river", "cast": ["xu", "wang"], "costume": {"xu": "gray robe", "wang": "blue robe"},
            "props": ["one cup"], "axis": "Xu left, Wang right", "screen_direction": "Wang enters right",
            "light": "night lantern", "shots": [shot_a, shot_b],
        }],
    }


def test_valid_bible_passes(tmp_path):
    report = audit_bible(base_bible(tmp_path), project_root=tmp_path)
    assert report["status"] == "pass", report["issues"]


def test_axis_cross_without_flag_fails(tmp_path):
    bible = base_bible(tmp_path)
    bible["scenes"][0]["shots"][1]["axis_side"] = "camera crossed to the other side"
    report = audit_bible(bible, project_root=tmp_path)
    assert report["status"] == "revise"
    assert any("axis" in issue for issue in report["issues"])


def test_costume_change_without_note_fails(tmp_path):
    bible = base_bible(tmp_path)
    bible["scenes"][0]["shots"][1]["costume_state"]["xu"] = "red robe"
    report = audit_bible(bible, project_root=tmp_path)
    assert report["status"] == "revise"
    assert any("costume" in issue for issue in report["issues"])


def test_missing_anchor_fails(tmp_path):
    bible = base_bible(tmp_path)
    (tmp_path / "previs" / "S01B.png").unlink()
    report = audit_bible(bible, project_root=tmp_path)
    assert report["status"] == "revise"
    assert any("anchor image" in issue for issue in report["issues"])
