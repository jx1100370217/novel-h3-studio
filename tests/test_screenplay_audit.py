import copy

from novel_h3.screenplay_audit import audit_treatment, extract_spoken


def base_script():
    return {
        "version": "1.0",
        "title": "Test",
        "total_duration_seconds": 10,
        "sections": [
            {"id": "A01", "text": "narrator: 那年冬天，我病了很久。", "start_seconds": 0, "end_seconds": 5},
            {"id": "A02", "text": "wife: 谁在门外？", "start_seconds": 5, "end_seconds": 10},
        ],
    }


def base_treatment():
    return {
        "version": "1.0",
        "title": "Test",
        "source_script": "artifacts/script.json",
        "logline": "A sick man hears a knock in the winter.",
        "dramatic_question": "Who is outside?",
        "theme": "Illness and duty.",
        "visual_motifs": [
            {"id": "M1", "name": "Cold lamp", "description": "The lamp wick shortens.", "setup_sections": ["A01"], "payoff_sections": ["A02"]},
            {"id": "M2", "name": "Frosted window", "description": "Frost spreads across the paper window.", "setup_sections": ["A01B"], "payoff_sections": ["A02"]},
            {"id": "M3", "name": "Threshold", "description": "The door line separates inside and outside.", "setup_sections": ["A01"], "payoff_sections": ["A01B"]},
        ],
        "beat_map": [
            {"beat_id": "B1", "section_ids": ["A01"], "function": "illness"},
            {"beat_id": "B2", "section_ids": ["A01B"], "function": "visual pause"},
            {"beat_id": "B3", "section_ids": ["A02"], "function": "the question"},
        ],
        "added_beats": [
            {"id": "A01B", "after_section": "A01", "source_paragraph_ids": ["s0001_p0001"], "type": "insert",
             "description": "Insert on the frost and the shortening lamp wick.", "why_cinematic": "Makes the long illness physical.",
             "fidelity_risk": "low", "extra_seconds": 2, "absorbed_from": "A01 and A02 each lose one second"}
        ],
        "enhanced_sections": [
            {"id": "A01", "original_section_id": "A01", "text": "narrator: 那年冬天，我病了很久。",
             "start_seconds": 0, "end_seconds": 4, "source_paragraph_ids": ["s0001_p0001"],
             "cinematic_function": "establish illness", "visual_motif": "M1", "added": False},
            {"id": "A01B", "original_section_id": "A01", "text": "Insert: frost on the paper window; the lamp wick shortens.",
             "start_seconds": 4, "end_seconds": 6, "source_paragraph_ids": ["s0001_p0001"],
             "cinematic_function": "visual pause", "visual_motif": "M2", "added": True},
            {"id": "A02", "original_section_id": "A02", "text": "wife: 谁在门外？",
             "start_seconds": 6, "end_seconds": 10, "source_paragraph_ids": ["s0001_p0002"],
             "cinematic_function": "the question", "visual_motif": "M3", "added": False},
        ],
        "fidelity_ledger": [
            {"source_fact": "Song Tao is ill for a long winter.", "treatment": "Frost and a shortening lamp wick.", "status": "visualized"},
            {"source_fact": "The wife asks who is outside.", "treatment": "Kept verbatim in A02.", "status": "preserved"},
        ],
        "production_constraints": ["1344x768, 24fps, exact cast, no duplicate people"],
        "approval_questions": ["Is the frost insert too much for the source's plain room?"],
        "metadata": {"runtime_target_seconds": 10, "runtime_after_seconds": 10,
                     "added_section_count": 1, "fidelity_status": "pass"},
    }


def test_extract_spoken_handles_narrator_and_character():
    lines = extract_spoken("narrator: 第一句。 wife: 第二句。")
    assert lines == ["第一句。", "第二句。"]


def test_valid_treatment_passes():
    report = audit_treatment(base_treatment(), base_script())
    assert report["status"] == "pass", report["issues"]
    assert report["metrics"]["added_section_count"] == 1


def test_new_spoken_words_fail():
    treatment = copy.deepcopy(base_treatment())
    treatment["enhanced_sections"][2]["text"] = "wife: 你是谁？"
    report = audit_treatment(treatment, base_script())
    assert report["status"] == "revise"
    assert any("not in the base script" in issue for issue in report["issues"])


def test_runtime_drift_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["enhanced_sections"][2]["end_seconds"] = 12
    treatment["metadata"]["runtime_after_seconds"] = 12
    report = audit_treatment(treatment, base_script())
    assert report["status"] == "revise"
    assert any("runtime" in issue for issue in report["issues"])


def test_new_speaker_marker_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["enhanced_sections"][1]["text"] = "stranger: 开门。"
    report = audit_treatment(treatment, base_script())
    assert report["status"] == "revise"
    assert any("new speaker" in issue for issue in report["issues"])


def test_missing_source_ref_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["added_beats"][0]["source_paragraph_ids"] = []
    report = audit_treatment(treatment, base_script())
    assert report["status"] == "revise"
    assert any("source_paragraph_ids" in issue for issue in report["issues"])


def test_dropped_original_section_fails():
    treatment = copy.deepcopy(base_treatment())
    treatment["enhanced_sections"] = [s for s in treatment["enhanced_sections"] if s["id"] != "A02"]
    treatment["beat_map"] = [b for b in treatment["beat_map"] if "A02" not in b["section_ids"]]
    report = audit_treatment(treatment, base_script())
    assert report["status"] == "revise"
    assert any("A02" in issue and "not represented" in issue for issue in report["issues"])
