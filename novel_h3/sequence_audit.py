"""Sequence-map and scene/sequel audit for V6+ treatments.

The seven-dimension gate asks whether the film is dramatically alive. This
gate asks whether the scenes form a causal chain: each sequence has a goal and
an end state, each scene is either an action (goal/conflict/disaster) or a
reaction (reaction/dilemma/decision), and the end state of one sequence is the
opening state of the next.
"""
from __future__ import annotations

import re
from typing import Any


def sequence_required(treatment: dict[str, Any]) -> bool:
    meta = treatment.get("metadata") or {}
    if isinstance(meta.get("sequence_map"), list) or isinstance(treatment.get("sequence_map"), list):
        return True
    raw = str(meta.get("craft_version") or "").strip()
    try:
        return float(raw.split()[0]) >= 6.0
    except (ValueError, IndexError):
        return False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s，。！？；：、“”‘’（）()《》〈〉—…,.!?;:\-]", "", _text(value))


def audit_sequence(treatment: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    sections = [s for s in (treatment.get("enhanced_sections") or []) if isinstance(s, dict)]
    section_ids = [str(s.get("id")) for s in sections]
    section_set = set(section_ids)
    sequences = [s for s in (treatment.get("sequence_map") or []) if isinstance(s, dict)]
    if len(sequences) != 8:
        issues.append(f"sequence_map must have exactly 8 sequences, got {len(sequences)}")
    assigned: dict[str, str] = {}
    previous_end = None
    for index, sequence in enumerate(sequences, 1):
        sid = _text(sequence.get("sequence_id")) or f"Q{index}"
        for key in ("purpose", "goal", "obstacle", "turn", "opening_state", "end_state"):
            if not _text(sequence.get(key)):
                issues.append(f"{sid}: sequence is missing {key}")
        ids = [str(x) for x in (sequence.get("section_ids") or [])]
        if not ids:
            issues.append(f"{sid}: sequence has no section_ids")
        for section in ids:
            if section not in section_set:
                issues.append(f"{sid}: names absent section {section}")
            elif section in assigned:
                issues.append(f"{sid}: section {section} is already in {assigned[section]}")
            else:
                assigned[section] = sid
        if previous_end is not None and _norm(previous_end) != _norm(sequence.get("opening_state")):
            issues.append(
                f"{sid}: opening_state does not continue the previous end_state "
                f"({previous_end!r} -> {sequence.get('opening_state')!r})")
        previous_end = sequence.get("end_state")
    missing = sorted(section_set - set(assigned))
    if missing:
        issues.append("sections not assigned to a sequence: " + ", ".join(missing))

    scene_types: list[str] = []
    for section in sections:
        sid = str(section.get("id", "?"))
        scene_sequel = section.get("scene_sequel") or {}
        if not isinstance(scene_sequel, dict) or not scene_sequel:
            issues.append(f"{sid}: scene_sequel is missing")
            scene_types.append("")
            continue
        scene_type = _text(scene_sequel.get("scene_type"))
        if scene_type not in ("scene", "sequel"):
            issues.append(f"{sid}: scene_sequel.scene_type must be 'scene' or 'sequel'")
        scene_types.append(scene_type)
        if scene_type == "scene":
            for key in ("goal", "conflict", "disaster"):
                if not _text(scene_sequel.get(key)):
                    issues.append(f"{sid}: scene needs {key}")
            if _text(scene_sequel.get("goal")) == _text(scene_sequel.get("disaster")):
                issues.append(f"{sid}: goal and disaster are identical; the scene does not turn")
        elif scene_type == "sequel":
            for key in ("reaction", "dilemma", "decision"):
                if not _text(scene_sequel.get(key)):
                    issues.append(f"{sid}: sequel needs {key}")
            if _text(scene_sequel.get("reaction")) == _text(scene_sequel.get("decision")):
                issues.append(f"{sid}: reaction and decision are identical; the sequel does not decide")
    for index in range(2, len(scene_types)):
        if scene_types[index] == scene_types[index - 1] == scene_types[index - 2] == "sequel":
            warnings.append(f"{sections[index].get('id')}: three consecutive sequels; consider cutting one")
    return {
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "sequences": len(sequences),
            "sections": len(sections),
            "scene_count": scene_types.count("scene"),
            "sequel_count": scene_types.count("sequel"),
            "assigned_sections": len(assigned),
        },
        "status": "pass" if not issues else "revise",
    }
