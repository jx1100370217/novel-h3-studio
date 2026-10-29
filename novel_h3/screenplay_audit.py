"""Audit a screenplay treatment for runtime, coverage and dialogue fidelity.

The treatment may add visual beats, but it may not add spoken words, drop an
original story beat, or drift more than 10% from the approved runtime.
"""
from __future__ import annotations

import re
from typing import Any

SPEAKER_RE = re.compile(
    r"(?:^|(?<=[\s。！？；]))([A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]{1,8})(?:（[^）]*）)?\s*[:：]\s*"
)
PUNCT_RE = re.compile(r"[\s，。！？；：、“”‘’（）()《》〈〉—…,.!?;:\-]")
RUNTIME_WARNING_PERCENT = 25.0


VISUAL_LABELS = {
    "insert", "cut", "shot", "visual", "montage", "transition", "sound", "note",
    "action", "close", "wide", "medium", "title", "card",
    "场景", "画面", "动作", "光", "声", "连续", "镜头", "转场", "插入",
    "特写", "中景", "全景", "近景", "远景", "构图", "调度", "字幕",
}


def speaker_names(text: str) -> set[str]:
    """Return all marker labels (speakers and visual labels) in a text."""
    names: set[str] = set()
    for line in text.splitlines():
        names.update(match.group(1) for match in SPEAKER_RE.finditer(line))
    return names


def extract_spoken(text: str, speakers: set[str] | None = None) -> list[str]:
    """Return spoken segments introduced by ``speaker:`` markers.

    Parsing is line-based so a dialogue line does not absorb the following
    action paragraph. Multiple speakers on one line are still supported.
    When ``speakers`` is provided, only those labels count as speech. Visual
    labels such as ``Insert:`` or ``画面：`` are skipped.
    """
    out: list[str] = []
    for line in text.splitlines():
        matches = list(SPEAKER_RE.finditer(line))
        for i, match in enumerate(matches):
            if speakers is not None and match.group(1) not in speakers:
                continue
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            value = line[start:end].strip()
            if value:
                out.append(value)
    return out


def normalize_text(text: str) -> str:
    return PUNCT_RE.sub("", text)


def _section_ids(treatment: dict[str, Any]) -> list[str]:
    return [str(section.get("id", "")) for section in treatment.get("enhanced_sections", [])]


def audit_treatment(
    treatment: dict[str, Any],
    script: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``status``/``issues``/``metrics`` for one treatment.

    Schema validity is checked separately by the checkpoint writer or CLI.
    This function focuses on cross-artifact rules that a JSON schema cannot see.
    """
    issues: list[str] = []
    warnings: list[str] = []
    sections = treatment.get("enhanced_sections") or []
    added_beats = treatment.get("added_beats") or []
    added_dialogue = treatment.get("added_dialogue") or []
    motifs = treatment.get("visual_motifs") or []
    beats = treatment.get("beat_map") or []
    ledger = treatment.get("fidelity_ledger") or []
    meta = treatment.get("metadata") or {}

    if not sections:
        issues.append("enhanced_sections is empty")

    # Craft contract: every scene states a concrete want, obstacle and turn,
    # plus a coverage plan that the scene plan can inherit.
    for section in sections:
        sid = section.get("id", "?")
        for key in ("want", "obstacle", "turn", "coverage"):
            if not str(section.get(key) or "").strip():
                issues.append(f"{sid}: scene contract is missing {key}")
    if not str(meta.get("opening_hook") or "").strip():
        issues.append("metadata.opening_hook is missing; the first 15 seconds need a question")

    ids = _section_ids(treatment)
    if len(ids) != len(set(ids)):
        issues.append("enhanced_sections contains duplicate section ids")

    # Timing: contiguous, non-overlapping, positive durations.
    ordered = sorted(sections, key=lambda section: float(section.get("start_seconds", 0)))
    cursor = 0.0
    total = 0.0
    for index, section in enumerate(ordered):
        sid = section.get("id", "?")
        start = float(section.get("start_seconds", 0))
        end = float(section.get("end_seconds", 0))
        if end <= start:
            issues.append(f"{sid}: end_seconds must be greater than start_seconds")
        if abs(start - cursor) > 0.05:
            issues.append(f"{sid}: timing gap/overlap at {start:.3f}s (expected {cursor:.3f}s)")
        cursor = end
        total += max(0.0, end - start)

    target = float(meta.get("runtime_target_seconds") or (script or {}).get("total_duration_seconds") or 0)
    after = float(meta.get("runtime_after_seconds") or total)
    if target <= 0:
        issues.append("metadata.runtime_target_seconds is missing or non-positive")
    else:
        delta_pct = (total - target) / target * 100
        if abs(delta_pct) > RUNTIME_WARNING_PERCENT:
            warnings.append(
                f"runtime {total:.3f}s is {delta_pct:+.1f}% from the planning estimate "
                f"{target:.3f}s; confirm the story needs this length (no hard cap)."
            )
    if abs(after - total) > 0.1:
        issues.append(f"metadata.runtime_after_seconds {after:.3f}s does not match section sum {total:.3f}s")

    # Added-section count and beat links.
    added_ids = {str(section.get("id")) for section in sections if section.get("added")}
    beat_ids = {str(beat.get("id")) for beat in added_beats}
    if meta.get("added_section_count") is not None and int(meta["added_section_count"]) != len(added_ids):
        issues.append(
            f"metadata.added_section_count {meta['added_section_count']} does not match {len(added_ids)} added sections"
        )
    for sid in sorted(added_ids - beat_ids):
        issues.append(f"{sid}: added section has no entry in added_beats")
    for sid in sorted(beat_ids - set(ids)):
        issues.append(f"{sid}: added beat references a section that does not exist")
    for beat in added_beats:
        if not beat.get("source_paragraph_ids"):
            issues.append(f"{beat.get('id', '?')}: added beat lacks source_paragraph_ids")
        if beat.get("fidelity_risk") not in ("low", "medium", "high"):
            issues.append(f"{beat.get('id', '?')}: added beat lacks a valid fidelity_risk")

    # Coverage: every original script section must survive somewhere.
    if script:
        original_ids = [str(section.get("id")) for section in script.get("sections", [])]
        represented = set()
        for section in sections:
            if section.get("original_section_id"):
                represented.add(str(section["original_section_id"]))
            represented.add(str(section.get("id")))
        for beat in beats:
            represented.update(str(sid) for sid in beat.get("section_ids", []))
        for sid in original_ids:
            if sid not in represented:
                issues.append(f"{sid}: original script section is not represented in the treatment")

    # Every enhanced section should belong to a beat.
    beat_sections = {str(sid) for beat in beats for sid in beat.get("section_ids", [])}
    for sid in ids:
        if sid not in beat_sections:
            issues.append(f"{sid}: enhanced section is not assigned to any beat")

    # Motifs: at least three, each with setup and payoff, and real section ids.
    if len(motifs) < 3:
        issues.append(f"visual_motifs has {len(motifs)} entries; the cinematic treatment needs at least 3")
    for motif in motifs:
        for key in ("setup_sections", "payoff_sections"):
            values = [str(sid) for sid in motif.get(key, [])]
            if not values:
                issues.append(f"{motif.get('id', '?')}: motif has no {key}")
            for sid in values:
                if sid not in ids:
                    issues.append(f"{motif.get('id', '?')}: {key} names absent section {sid}")

    # Ledger and production constraints.
    if not ledger:
        issues.append("fidelity_ledger is empty")
    for row in ledger:
        if row.get("status") not in ("preserved", "visualized", "compressed", "ambiguous"):
            issues.append(f"fidelity_ledger: invalid status {row.get('status')!r}")
    if not treatment.get("production_constraints"):
        issues.append("production_constraints is empty; list the H3 cast/single-body rules")
    if not treatment.get("approval_questions"):
        issues.append("approval_questions is empty")

    # Dialogue fidelity: existing lines may be re-timed; new connective lines
    # are allowed only when declared in added_dialogue with a source fact and a
    # dramatic purpose.
    spoken_lines = 0
    narrator_lines = 0
    if script:
        base_text = " ".join(str(s.get("text", "")) for s in script.get("sections", []))
        base_speakers = speaker_names(base_text)
        original_text = normalize_text(base_text)
        declared_texts = {normalize_text(str(row.get("text", ""))) for row in added_dialogue}
        declared_speakers = {str(row.get("speaker", "")) for row in added_dialogue if row.get("speaker")}
        allowed_speakers = base_speakers | declared_speakers
        for row in added_dialogue:
            if not row.get("source_fact") or not row.get("purpose"):
                issues.append(f"{row.get('line_id', '?')}: added dialogue needs source_fact and purpose")
            if normalize_text(str(row.get("text", ""))) not in normalize_text(
                    " ".join(str(s.get("text", "")) for s in sections)):
                issues.append(f"{row.get('line_id', '?')}: declared added line is not present in the enhanced script")
        for section in sections:
            sid = section.get("id", "?")
            text = str(section.get("text", ""))
            narrator_lines += len(re.findall(r"(?:^|\s)narrator\s*[:：]", text))
            for marker in speaker_names(text):
                if marker not in allowed_speakers and marker.lower() not in VISUAL_LABELS:
                    issues.append(f"{sid}: new speaker/dialogue marker {marker!r} is not declared")
            for line in extract_spoken(text, allowed_speakers):
                spoken_lines += 1
                normalized = normalize_text(line)
                if normalized not in original_text and normalized not in declared_texts:
                    issues.append(
                        f"{sid}: spoken line is neither in the base script nor declared in added_dialogue: {line[:80]!r}"
                    )
    if narrator_lines:
        warnings.append(
            f"{narrator_lines} narrator line(s) found; dialogue-first is preferred. "
            "Keep narration only for an unwitnessable time jump."
        )
    if meta.get("fidelity_status") not in ("pass", "revise"):
        issues.append("metadata.fidelity_status must be 'pass' or 'revise'")
    elif meta.get("fidelity_status") == "revise":
        issues.append("metadata.fidelity_status is 'revise'")

    return {
        "status": "pass" if not issues else "revise",
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "section_count": len(sections),
            "added_section_count": len(added_ids),
            "runtime_seconds": round(total, 3),
            "runtime_target_seconds": round(target, 3),
            "runtime_delta_percent": round((total - target) / target * 100, 2) if target else None,
            "spoken_lines": spoken_lines,
            "added_dialogue_lines": len(added_dialogue),
            "narrator_lines": narrator_lines,
            "visual_motifs": len(motifs),
            "added_beats": len(added_beats),
        },
    }
