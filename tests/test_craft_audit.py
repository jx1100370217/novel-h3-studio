import copy

from novel_h3.craft_audit import audit_craft


def base_treatment():
    sections = []
    jobs = ["hook", "meet", "foreshadow", "discovery", "revelation",
            "crisis", "loss", "climax", "aftermath"]
    pressures = [2, 2, 3, 3, 4, 5, 5, 4, 2]
    choices = ["none"] * 9
    choices[1] = "offer the cup"
    choices[4] = "agree to witness"
    choices[5] = "withdraw the hand"
    choices[7] = "apologise"
    choices[8] = "pour the wine into the river"
    for i, (job, pressure, choice) in enumerate(zip(jobs, pressures, choices), 1):
        sections.append({
            "id": f"S{i:02d}", "text": f"Xu：line {i}.",
            "start_seconds": (i - 1) * 60.0, "end_seconds": i * 60.0,
            "source_paragraph_ids": ["p1"], "cinematic_function": job, "added": False,
            "scene_job": job, "stakes": f"stakes {i}", "opposition": f"force {i}",
            "pressure": pressure, "subtext": f"subtext {i}", "reaction_shot": f"reaction {i}",
            "protagonist_choice": choice,
            "choice_cost": "" if choice == "none" else f"cost {i}",
            "motif_beats": [{"motif_id": "M1", "phase": "setup", "meaning": f"meaning {i}"}],
            "object_beats": [{"object": "cup", "before": "full", "after": "empty"}],
            "ending_echo": "the cup from S01" if i == 9 else "",
        })
    return {
        "version": "1.0", "title": "Craft test",
        "source_script": "artifacts/script.json",
        "logline": "A fisherman must choose between a friend and a stranger.",
        "dramatic_question": "Will he reach out?",
        "theme": "Compassion is a hand that keeps reaching.",
        "protagonist": {
            "name": "Xu", "want": "keep the friend", "need": "let the friend go",
            "flaw": "possessiveness", "start_state": "alone", "midpoint_state": "withdrawn",
            "end_state": "released", "moral_question": "Will he save the mother?",
            "choice_scenes": ["S02", "S05", "S06", "S08", "S09"],
        },
        "antagonism": [
            {"force": "wife", "kind": "human", "scenes": ["S08", "S09"], "pressure": "blocks him"},
            {"force": "river rule", "kind": "rule", "scenes": ["S05", "S06", "S07"], "pressure": "deadline"},
            {"force": "possessiveness", "kind": "internal", "scenes": ["S02", "S06"], "pressure": "temptation"},
        ],
        "stakes_clock": {
            "public": "a mother and child", "private": "his friend and marriage",
            "deadline": "noon", "consequence": "a death or a loss",
            "planted_in": ["S03", "S04", "S05"], "paid_in": ["S06", "S07", "S08"],
        },
        "pacing": {"midpoint_scene": "S06", "climax_scene": "S08",
                   "aftermath_scenes": ["S09"], "escalation_curve": pressures},
        "ending": {"final_action": "pour the wine into the river", "echo_scene": "S01",
                   "echo_object": "cup", "meaning": "release"},
        "dialogue_policy": {"theme_lines": [], "subtext_scenes": [f"S{i:02d}" for i in range(1, 10)],
                             "silence_scenes": ["S06"]},
        "visual_motifs": [
            {"id": "M1", "name": "cup", "description": "cup", "object": True,
             "setup_sections": ["S01"], "payoff_sections": ["S09"],
             "beats": [
                 {"section_id": "S01", "phase": "setup", "meaning": "ritual"},
                 {"section_id": "S06", "phase": "turn", "meaning": "refusal"},
                 {"section_id": "S09", "phase": "payoff", "meaning": "release"},
             ]},
            {"id": "M2", "name": "hand", "description": "hand", "object": False,
             "setup_sections": ["S01"], "payoff_sections": ["S09"],
             "beats": [
                 {"section_id": "S01", "phase": "setup", "meaning": "habit"},
                 {"section_id": "S06", "phase": "turn", "meaning": "withdrawal"},
                 {"section_id": "S09", "phase": "payoff", "meaning": "steadiness"},
             ]},
            {"id": "M3", "name": "fog", "description": "fog", "object": False,
             "setup_sections": ["S01"], "payoff_sections": ["S09"],
             "beats": [
                 {"section_id": "S01", "phase": "setup", "meaning": "hiding"},
                 {"section_id": "S06", "phase": "turn", "meaning": "exposure"},
                 {"section_id": "S09", "phase": "payoff", "meaning": "return"},
             ]},
        ],
        "object_arcs": [
            {"object": "cup", "final_state": "empty", "states": [
                {"section_id": "S01", "state": "full"},
                {"section_id": "S06", "state": "set down"},
                {"section_id": "S09", "state": "empty"},
            ]},
            {"object": "hand", "final_state": "steady", "states": [
                {"section_id": "S01", "state": "reaching"},
                {"section_id": "S06", "state": "withdrawn"},
                {"section_id": "S09", "state": "pouring"},
            ]},
            {"object": "shoes", "final_state": "by the door", "states": [
                {"section_id": "S02", "state": "hidden"},
                {"section_id": "S05", "state": "given"},
                {"section_id": "S09", "state": "off"},
            ]},
        ],
        "enhanced_sections": sections,
        "metadata": {
            "runtime_target_seconds": 540, "runtime_after_seconds": 540,
            "added_section_count": 0, "fidelity_status": "pass",
            "opening_hook": "a voice answers from the fog", "craft_version": "5.0",
            "seven_dimensions": {
                key: {"score": 5, "evidence": "a concrete scene-level action proves this dimension"}
                for key in ("literary_texture", "motif_design", "object_narrative",
                            "dramatic_conflict", "protagonist_arc", "mid_section_escalation",
                            "ending_aftermath")
            },
        },
    }


def test_valid_craft_treatment_passes():
    report = audit_craft(base_treatment())
    assert report["issues"] == [], report["issues"]


def test_passive_protagonist_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["protagonist"]["choice_scenes"] = ["S02", "S05", "S08"]
    treatment["enhanced_sections"][5]["protagonist_choice"] = "none"
    treatment["enhanced_sections"][5]["choice_cost"] = ""
    report = audit_craft(treatment)
    assert any("choice_scenes" in issue or "midpoint" in issue for issue in report["issues"])


def test_repeated_scene_job_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["enhanced_sections"][6]["scene_job"] = "crisis"
    report = audit_craft(treatment)
    assert any("consecutive" in issue or "appears" in issue for issue in report["issues"])


def test_motif_repeating_one_meaning_fails():
    treatment = copy.deepcopy(base_treatment())
    for beat in treatment["visual_motifs"][0]["beats"]:
        beat["meaning"] = "the same idea"
    report = audit_craft(treatment)
    assert any("distinct meanings" in issue for issue in report["issues"])


def test_theme_spoken_verbatim_fails():
    treatment = copy.deepcopy(base_treatment())
    theme = treatment["theme"]
    treatment["enhanced_sections"][0]["text"] = f"Xu：{theme}"
    report = audit_craft(treatment)
    assert any("theme sentence" in issue for issue in report["issues"])


def test_object_must_reach_final_scene():
    treatment = copy.deepcopy(base_treatment())
    for arc in treatment["object_arcs"]:
        for state in arc["states"]:
            if state["section_id"] == "S09":
                state["section_id"] = "S08"
    report = audit_craft(treatment)
    assert any("object arc must reach the final scene" in issue for issue in report["issues"])
