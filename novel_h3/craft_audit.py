"""Seven-dimension craft audit for novel-cinematic treatments (craft v5+).

The earlier screenplay audit answered "is this faithful and shootable?".
This module answers the harder question: "is this dramatically excellent?".

It is deliberately data-driven. A treatment opts into the strict gate with
``metadata.craft_version >= 5.0`` (or by carrying ``metadata.seven_dimensions``)
and must then prove, scene by scene, that:

1. literary texture: a specific moral question, not a theme slogan;
2. motif design: every motif changes meaning at least three times;
3. object narrative: at least three objects carry a visible state change;
4. dramatic conflict: an active opposing force, not only atmosphere;
5. protagonist arc: the protagonist, not a supporting character, owns the
   costly midpoint choice and ends in a different state;
6. mid-section escalation: pressure rises to a midpoint crisis, and no two
   consecutive scenes do the same job;
7. ending aftermath: the climax is followed by at most two scenes and the
   final action echoes an earlier object/scene.

The checks are structural, not a substitute for human reading. They catch the
failure modes that made a technically finished cut feel inert: a passive
protagonist, repeated river-drinking scenes, a late or abstract stake, two
farewells, and a theme spoken aloud.
"""
from __future__ import annotations

import math
import re
from typing import Any

DIMENSIONS = {
    "literary_texture": "文学质感",
    "motif_design": "母题设计",
    "object_narrative": "物件叙事",
    "dramatic_conflict": "戏剧冲突",
    "protagonist_arc": "主角弧光",
    "mid_section_escalation": "中段节奏",
    "ending_aftermath": "结尾余波",
}

SCENE_JOBS = {
    "hook", "meet", "intimacy", "foreshadow", "discovery", "revelation",
    "crisis", "loss", "opposition", "journey", "audience", "climax",
    "test", "aftermath", "transition",
}

# A film may use a job more than once only when the repeat is a deliberate
# escalation. These caps make a second farewell or a third drinking scene
# fail the gate instead of hiding in a long scene list.
JOB_LIMITS = {
    "hook": 1,
    "meet": 1,
    "discovery": 1,
    "revelation": 1,
    "crisis": 1,
    "loss": 1,
    "climax": 1,
    "test": 1,
    "aftermath": 1,
    "journey": 1,
    "audience": 1,
    "foreshadow": 2,
    "intimacy": 2,
    "opposition": 2,
    "transition": 2,
}

PHASES = {"setup", "turn", "payoff"}
ANTAGONIST_KINDS = {"human", "rule", "internal", "environment", "institution"}
DIALOGUE_RE = re.compile(r"(?:^|\n)\s*[\u4e00-\u9fffA-Za-z][^：:\n]{0,12}[：:]")
VISUAL_LABELS = {
    "insert", "cut", "shot", "visual", "montage", "transition", "sound",
    "note", "action", "close", "wide", "medium", "title", "card",
    "场景", "画面", "动作", "光", "声", "连续", "镜头", "转场", "插入",
    "特写", "中景", "全景", "近景", "远景", "构图", "调度", "字幕",
}


def craft_v5_required(treatment: dict[str, Any]) -> bool:
    """Whether this treatment must pass the seven-dimension craft gate."""
    meta = treatment.get("metadata") or {}
    if isinstance(meta.get("seven_dimensions"), dict) and meta["seven_dimensions"]:
        return True
    raw = str(meta.get("craft_version") or "").strip()
    try:
        return float(raw.split()[0]) >= 5.0
    except (ValueError, IndexError):
        return False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s，。！？；：、“”‘’（）()《》〈〉—…,.!?;:\-]", "", _text(value))


def _ids(sections: list[dict]) -> list[str]:
    return [str(section.get("id", "")) for section in sections]


def _duration(section: dict) -> float:
    try:
        return max(0.0, float(section.get("end_seconds", 0)) - float(section.get("start_seconds", 0)))
    except (TypeError, ValueError):
        return 0.0


def _has_dialogue(section: dict) -> bool:
    text = _text(section.get("text"))
    for match in DIALOGUE_RE.finditer(text):
        label = match.group(0).strip().rstrip("：:").strip()
        if label.lower() not in VISUAL_LABELS and label not in VISUAL_LABELS:
            return True
    return False


def _score(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= 5 else None


def audit_craft(
    treatment: dict[str, Any],
    script: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return issues/warnings/metrics for the seven-dimension gate."""
    issues: list[str] = []
    warnings: list[str] = []
    sections = [s for s in (treatment.get("enhanced_sections") or []) if isinstance(s, dict)]
    ids = _ids(sections)
    id_set = set(ids)
    if not sections:
        return {"issues": ["craft v5: enhanced_sections is empty"], "warnings": [],
                "metrics": {"craft_version": 5.0}}

    if not 8 <= len(sections) <= 14:
        issues.append(f"craft v5 needs 8-14 dramatic scenes, got {len(sections)}")

    meta = treatment.get("metadata") or {}
    pacing = treatment.get("pacing") or {}
    final_id = ids[-1]
    final = sections[-1]
    total_runtime = sum(_duration(section) for section in sections)

    # 1. Seven dimension evidence ------------------------------------------------
    dimensions = meta.get("seven_dimensions") or {}
    if not isinstance(dimensions, dict):
        issues.append("metadata.seven_dimensions must be an object")
        dimensions = {}
    for key, label in DIMENSIONS.items():
        item = dimensions.get(key)
        if not isinstance(item, dict):
            issues.append(f"seven_dimensions.{key} ({label}) is missing")
            continue
        score = _score(item.get("score"))
        if score is None:
            issues.append(f"seven_dimensions.{key} ({label}) needs an integer score 1-5")
        elif score < 4:
            issues.append(
                f"seven_dimensions.{key} ({label}) scores {score}/5; craft v5 needs at least 4")
        elif score == 4:
            warnings.append(
                f"seven_dimensions.{key} ({label}) is 4/5; the target for a delivery cut is 5/5")
        if len(_text(item.get("evidence"))) < 24:
            issues.append(f"seven_dimensions.{key} ({label}) needs specific evidence, not a label")

    # 2. Protagonist arc ---------------------------------------------------------
    protagonist = treatment.get("protagonist") or {}
    if not isinstance(protagonist, dict) or not protagonist:
        issues.append("protagonist is missing; the film needs one owned point of view")
        protagonist = {}
    for key in ("name", "want", "need", "flaw", "start_state", "midpoint_state",
                "end_state", "moral_question"):
        if not _text(protagonist.get(key)):
            issues.append(f"protagonist.{key} is missing")
    if protagonist:
        if _norm(protagonist.get("want")) == _norm(protagonist.get("need")):
            issues.append("protagonist.want and protagonist.need are identical; there is no arc")
        if _norm(protagonist.get("start_state")) == _norm(protagonist.get("end_state")):
            issues.append("protagonist.start_state and end_state are identical; there is no arc")
    choice_scenes = [str(sid) for sid in (protagonist.get("choice_scenes") or [])]
    if len(set(choice_scenes)) < 3:
        issues.append("protagonist.choice_scenes needs at least 3 distinct scenes where the protagonist chooses")
    for sid in choice_scenes:
        if sid not in id_set:
            issues.append(f"protagonist.choice_scenes names absent section {sid}")

    # 3. Active antagonism -------------------------------------------------------
    antagonism = [a for a in (treatment.get("antagonism") or []) if isinstance(a, dict)]
    if len(antagonism) < 2:
        issues.append("antagonism needs at least two forces (external and internal)")
    human_or_rule = 0
    internal = 0
    long_running = 0
    for force in antagonism:
        label = _text(force.get("force")) or "?"
        kind = _text(force.get("kind"))
        scenes = [str(sid) for sid in (force.get("scenes") or [])]
        if kind not in ANTAGONIST_KINDS:
            issues.append(f"antagonism {label!r}: invalid kind {kind!r}")
        if not scenes:
            issues.append(f"antagonism {label!r}: no scenes")
        for sid in scenes:
            if sid not in id_set:
                issues.append(f"antagonism {label!r}: names absent section {sid}")
        if kind in ("human", "institution", "rule"):
            human_or_rule += 1
        if kind == "internal":
            internal += 1
        if len(scenes) >= 2:
            long_running += 1
    if not human_or_rule:
        issues.append("antagonism needs a human, institution or rule force, not only weather or mood")
    if not internal:
        issues.append("antagonism needs an internal force; the protagonist must fight something in himself")
    if not long_running:
        issues.append("antagonism needs at least one force that pressures more than one scene")

    # 4. Stakes clock ------------------------------------------------------------
    stakes = treatment.get("stakes_clock") or {}
    for key in ("public", "private", "deadline", "consequence"):
        if not _text(stakes.get(key)):
            issues.append(f"stakes_clock.{key} is missing")
    planted = [str(sid) for sid in (stakes.get("planted_in") or [])]
    paid = [str(sid) for sid in (stakes.get("paid_in") or [])]
    if len(set(planted)) < 2:
        issues.append("stakes_clock.planted_in needs at least two scenes before the crisis")
    for sid in planted + paid:
        if sid not in id_set:
            issues.append(f"stakes_clock names absent section {sid}")
    midpoint = _text(pacing.get("midpoint_scene"))
    climax = _text(pacing.get("climax_scene"))
    if not midpoint:
        crisis = next((s for s in sections if s.get("scene_job") == "crisis"), None)
        midpoint = str(crisis.get("id")) if crisis else ""
    if not climax:
        climax_scene = next((s for s in sections if s.get("scene_job") == "climax"), None)
        climax = str(climax_scene.get("id")) if climax_scene else ""
    if not midpoint:
        issues.append("pacing.midpoint_scene is missing and no scene is marked 'crisis'")
    else:
        if midpoint not in paid:
            issues.append("stakes_clock.paid_in must include the midpoint crisis")
        if midpoint not in choice_scenes:
            issues.append(
                f"protagonist.choice_scenes must include the midpoint crisis {midpoint}")
    if not climax:
        issues.append("pacing.climax_scene is missing and no scene is marked 'climax'")
    elif climax not in paid:
        warnings.append("stakes_clock.paid_in does not explicitly include the climax")

    # 5. Pacing and escalation ---------------------------------------------------
    jobs = [_text(section.get("scene_job")) for section in sections]
    for sid, job in zip(ids, jobs):
        if not job:
            issues.append(f"{sid}: scene_job is missing")
        elif job not in SCENE_JOBS:
            issues.append(f"{sid}: unknown scene_job {job!r}")
    for i in range(1, len(jobs)):
        if jobs[i] and jobs[i] == jobs[i - 1]:
            issues.append(f"{ids[i]}: consecutive scenes share the job {jobs[i]!r}; escalate or merge")
    counts: dict[str, int] = {}
    for job in jobs:
        if job:
            counts[job] = counts.get(job, 0) + 1
    for job, count in counts.items():
        limit = JOB_LIMITS.get(job)
        if limit is not None and count > limit:
            issues.append(f"scene_job {job!r} appears {count} times; the craft limit is {limit}")

    pressures: list[int] = []
    for section in sections:
        value = section.get("pressure")
        score = _score(value)
        if score is None:
            issues.append(f"{section.get('id', '?')}: pressure must be an integer 1-5")
            pressures.append(0)
        else:
            pressures.append(score)
    if midpoint in id_set and climax in id_set:
        mid_index = ids.index(midpoint)
        climax_index = ids.index(climax)
        mid_ratio = mid_index / max(1, len(ids) - 1)
        climax_ratio = climax_index / max(1, len(ids) - 1)
        if not 0.40 <= mid_ratio <= 0.65:
            issues.append(f"midpoint {midpoint} sits at {mid_ratio:.0%}; it must land in the 40-65% band")
        if not 0.75 <= climax_ratio <= 0.95:
            issues.append(f"climax {climax} sits at {climax_ratio:.0%}; it must land in the 75-95% band")
        if climax_index <= mid_index:
            issues.append("climax must come after the midpoint crisis")
        if pressures[mid_index] < 5:
            issues.append(f"midpoint {midpoint} pressure is {pressures[mid_index]}; the crisis must be 5/5")
        if pressures[climax_index] < 4:
            issues.append(f"climax {climax} pressure is {pressures[climax_index]}; it needs at least 4/5")
        if not any(value == 5 for value in pressures[mid_index + 1:]):
            issues.append("nothing after the midpoint reaches pressure 5/5; the film sags after the crisis")
    aftermath = [str(sid) for sid in (pacing.get("aftermath_scenes") or [])]
    if len(aftermath) > 2:
        issues.append("pacing.aftermath_scenes has more than two scenes; compress the ending")
    for sid in aftermath:
        if sid not in id_set:
            issues.append(f"pacing.aftermath_scenes names absent section {sid}")
    if aftermath:
        after_runtime = sum(_duration(s) for s in sections if str(s.get("id")) in set(aftermath))
        if total_runtime and after_runtime / total_runtime > 0.20:
            issues.append(
                f"aftermath is {after_runtime / total_runtime:.0%} of runtime; the cap is 20%")

    # 6. Motifs ----------------------------------------------------------------
    motifs = [m for m in (treatment.get("visual_motifs") or []) if isinstance(m, dict)]
    if len(motifs) < 3:
        issues.append(f"visual_motifs has {len(motifs)} entries; craft v5 needs at least 3")
    motif_ids = {str(m.get("id")) for m in motifs}
    has_object_motif = False
    motif_in_final = False
    for motif in motifs:
        mid = str(motif.get("id", "?"))
        beats = [b for b in (motif.get("beats") or []) if isinstance(b, dict)]
        if len(beats) < 3:
            issues.append(f"{mid}: motif needs at least 3 beats that change meaning")
        phases = {_text(b.get("phase")) for b in beats}
        if not PHASES <= phases:
            issues.append(f"{mid}: motif beats must include setup, turn and payoff phases")
        meanings = [_norm(b.get("meaning")) for b in beats if _text(b.get("meaning"))]
        if len(set(meanings)) < 3:
            issues.append(f"{mid}: motif needs at least 3 distinct meanings, not one idea repeated")
        for beat in beats:
            sid = _text(beat.get("section_id"))
            if sid not in id_set:
                issues.append(f"{mid}: motif beat names absent section {sid!r}")
            if _text(beat.get("phase")) not in PHASES:
                issues.append(f"{mid}: motif beat has invalid phase {beat.get('phase')!r}")
        if motif.get("object") is True:
            has_object_motif = True
        if any(_text(b.get("section_id")) == final_id for b in beats):
            motif_in_final = True
    if not has_object_motif:
        issues.append("at least one visual motif must be a physical object that changes state")
    if not motif_in_final:
        issues.append("at least one motif must return in the final scene")

    # 7. Object arcs ------------------------------------------------------------
    arcs = [a for a in (treatment.get("object_arcs") or []) if isinstance(a, dict)]
    if len(arcs) < 3:
        issues.append(f"object_arcs has {len(arcs)} entries; craft v5 needs at least 3")
    arc_names = set()
    object_in_final = False
    for arc in arcs:
        name = _text(arc.get("object"))
        if not name:
            issues.append("object_arcs entry has no object name")
            continue
        arc_names.add(_norm(name))
        states = [s for s in (arc.get("states") or []) if isinstance(s, dict)]
        if len(states) < 3:
            issues.append(f"object {name!r}: needs at least 3 visible states")
        state_texts = [_norm(s.get("state")) for s in states if _text(s.get("state"))]
        if len(set(state_texts)) < 3:
            issues.append(f"object {name!r}: states do not change enough")
        for state in states:
            sid = _text(state.get("section_id"))
            if sid not in id_set:
                issues.append(f"object {name!r}: state names absent section {sid!r}")
            if sid == final_id:
                object_in_final = True
        if not _text(arc.get("final_state")):
            issues.append(f"object {name!r}: final_state is missing")
    if not object_in_final:
        issues.append("at least one object arc must reach the final scene")

    # 8. Dialogue and subtext ---------------------------------------------------
    dialogue_policy = treatment.get("dialogue_policy") or {}
    theme_lines = [str(line) for line in (dialogue_policy.get("theme_lines") or [])]
    if len(theme_lines) > 1:
        issues.append("dialogue_policy.theme_lines has more than one line; the theme must not be spoken twice")
    all_text = "\n".join(_text(section.get("text")) for section in sections)
    for line in theme_lines:
        if _norm(line) and _norm(line) not in _norm(all_text):
            issues.append(f"declared theme line is not in the script: {line[:40]!r}")
    theme = _text(treatment.get("theme"))
    if theme and _norm(theme) and _norm(theme) in _norm(all_text):
        issues.append("the theme sentence is spoken verbatim; move it into action or subtext")
    dialogue_scenes = {str(s.get("id")) for s in sections if _has_dialogue(s)}
    subtext_scenes = {str(sid) for sid in (dialogue_policy.get("subtext_scenes") or [])}
    missing_subtext = sorted(dialogue_scenes - subtext_scenes)
    if missing_subtext:
        issues.append(
            "dialogue_policy.subtext_scenes is missing dialogue scenes: " + ", ".join(missing_subtext))
    silence_scenes = [str(sid) for sid in (dialogue_policy.get("silence_scenes") or [])]
    if not silence_scenes:
        warnings.append("dialogue_policy.silence_scenes is empty; at least one scene should trust silence")
    for section in sections:
        sid = str(section.get("id"))
        if _has_dialogue(section):
            subtext = _text(section.get("subtext"))
            if not subtext:
                issues.append(f"{sid}: dialogue scene needs a subtext line")
            elif _norm(subtext) in {_norm(section.get("want")), _norm(section.get("turn"))}:
                issues.append(f"{sid}: subtext repeats want/turn; it is not subtext")

    # 9. Ending ----------------------------------------------------------------
    ending = treatment.get("ending") or {}
    for key in ("final_action", "echo_scene", "echo_object", "meaning"):
        if not _text(ending.get(key)):
            issues.append(f"ending.{key} is missing")
    echo_scene = _text(ending.get("echo_scene"))
    if echo_scene and echo_scene not in id_set:
        issues.append(f"ending.echo_scene names absent section {echo_scene!r}")
    elif echo_scene and ids.index(echo_scene) >= len(ids) - 1:
        issues.append("ending.echo_scene must point to an earlier scene, not the final scene")
    echo_object = _norm(ending.get("echo_object"))
    if echo_object and echo_object not in arc_names:
        issues.append(f"ending.echo_object {ending.get('echo_object')!r} is not one of the object arcs")
    if not _text(final.get("protagonist_choice")):
        issues.append("the final scene needs an explicit protagonist choice")
    if not _text(final.get("ending_echo")):
        issues.append("the final scene needs an ending_echo naming the earlier action it answers")
    if re.search(r"(?:^|\n)\s*narrator\s*[:：]", _text(final.get("text")), re.I):
        issues.append("the final scene uses narration; end on an action instead")

    # 10. Scene-level contract --------------------------------------------------
    owned_choices = 0
    for section in sections:
        sid = str(section.get("id", "?"))
        for key in ("stakes", "opposition", "subtext", "reaction_shot", "scene_job"):
            if not _text(section.get(key)):
                issues.append(f"{sid}: craft v5 requires {key}")
        if section.get("pressure") is None:
            issues.append(f"{sid}: craft v5 requires pressure")
        choice = _text(section.get("protagonist_choice"))
        if not choice:
            issues.append(f"{sid}: protagonist_choice is missing (use 'none' only when the scene truly acts on the protagonist)")
        elif _norm(choice) not in ("none", "无", "不是他"):
            owned_choices += 1
            if not _text(section.get("choice_cost")):
                issues.append(f"{sid}: a protagonist choice needs a visible cost")
        motif_beats = [b for b in (section.get("motif_beats") or []) if isinstance(b, dict)]
        if not motif_beats:
            issues.append(f"{sid}: motif_beats is empty; every scene should move a motif")
        for beat in motif_beats:
            mid = _text(beat.get("motif_id"))
            if mid not in motif_ids:
                issues.append(f"{sid}: motif beat names absent motif {mid!r}")
            if _text(beat.get("phase")) not in PHASES:
                issues.append(f"{sid}: motif beat has invalid phase {beat.get('phase')!r}")
            if not _text(beat.get("meaning")):
                issues.append(f"{sid}: motif beat has no meaning")
        object_beats = [b for b in (section.get("object_beats") or []) if isinstance(b, dict)]
        if not object_beats:
            issues.append(f"{sid}: object_beats is empty; every scene should change an object")
        for beat in object_beats:
            for key in ("object", "before", "after"):
                if not _text(beat.get(key)):
                    issues.append(f"{sid}: object beat is missing {key}")
    if owned_choices < 3:
        issues.append(f"only {owned_choices} scenes give the protagonist a costly choice; at least 3 are required")

    return {
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "craft_version": 5.0,
            "scene_count": len(sections),
            "runtime_seconds": round(total_runtime, 3),
            "midpoint_scene": midpoint or None,
            "midpoint_ratio": round(ids.index(midpoint) / max(1, len(ids) - 1), 3)
            if midpoint in id_set else None,
            "climax_scene": climax or None,
            "climax_ratio": round(ids.index(climax) / max(1, len(ids) - 1), 3)
            if climax in id_set else None,
            "pressure_curve": pressures,
            "scene_jobs": dict(counts),
            "protagonist_choices": owned_choices,
            "dimension_scores": {
                key: (_score((dimensions.get(key) or {}).get("score"))
                      if isinstance(dimensions.get(key), dict) else None)
                for key in DIMENSIONS
            },
            "motifs": len(motifs),
            "object_arcs": len(arcs),
        },
    }
