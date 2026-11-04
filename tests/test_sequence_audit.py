import copy

from novel_h3.sequence_audit import audit_sequence


def base_treatment():
    sections = []
    for i in range(1, 9):
        sections.append({
            "id": f"S{i:02d}", "text": f"Xu：line {i}.",
            "scene_sequel": ({"scene_type": "scene", "goal": "goal", "conflict": "conflict",
                              "disaster": "disaster"} if i % 2 else
                             {"scene_type": "sequel", "reaction": "reaction", "dilemma": "dilemma",
                              "decision": "decision"}),
        })
    seqs = []
    previous = "start"
    for i in range(1, 9):
        seqs.append({
            "sequence_id": f"Q{i}", "purpose": f"purpose {i}", "section_ids": [f"S{i:02d}"],
            "goal": "goal", "obstacle": "obstacle", "turn": "turn",
            "opening_state": previous, "end_state": f"end {i}",
        })
        previous = f"end {i}"
    return {"enhanced_sections": sections, "sequence_map": seqs,
            "metadata": {"craft_version": "6.0"}}


def test_valid_sequence_map_passes():
    report = audit_sequence(base_treatment())
    assert report["status"] == "pass", report["issues"]


def test_missing_scene_sequel_fails():
    treatment = copy.deepcopy(base_treatment())
    del treatment["enhanced_sections"][0]["scene_sequel"]
    report = audit_sequence(treatment)
    assert report["status"] == "revise"
    assert any("scene_sequel" in issue for issue in report["issues"])


def test_broken_sequence_handoff_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["sequence_map"][1]["opening_state"] = "not the previous end"
    report = audit_sequence(treatment)
    assert report["status"] == "revise"
    assert any("opening_state" in issue for issue in report["issues"])


def test_section_assigned_twice_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["sequence_map"][1]["section_ids"] = ["S01"]
    report = audit_sequence(treatment)
    assert report["status"] == "revise"
    assert any("already in" in issue for issue in report["issues"])
