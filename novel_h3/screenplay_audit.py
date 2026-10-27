"""Audit a screenplay treatment for runtime, coverage and dialogue fidelity.

The treatment may add visual beats, but it may not add spoken words, drop an
original story beat, or drift more than 10% from the approved runtime.
"""
from __future__ import annotations

import re
from typing import Any

SPEAKER_RE = re.compile(
    r"(?:^|(?<=[\s。！？；]))([A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]{1,8})\s*[:：]\s*"
)
PUNCT_RE = re.compile(r"[\s，。！？；：、“”‘’（）()《》〈〉—…,.!?;:\-]")
RUNTIME_TOLERANCE = 0.10


VISUAL_LABELS = {
    "insert", "cut", "shot", "visual", "montage", "transition", "sound", "note",
    "action", "close", "wide", "medium", "title", "card",
}


def speaker_names(text: str) -> set[str]:
    """Return all marker labels (speakers and visual labels) in a text."""
    return {match.group(1) for match in SPEAKER_RE.finditer(text)}


def extract_spoken(text: str, speakers: set[str] | None = None) -> list[str]:
    """Return spoken segments introduced by ``speaker:`` markers.

    When ``speakers`` is provided, only those labels count as speech. Visual
    labels such as ``Insert:`` or ``Cut:`` are skipped, so an added visual beat
    is not mistaken for a new line of dialogue.
    """
    matches = list(SPEAKER_RE.finditer(text))
    if not matches:
        return []
    out: list[str] = []
    for i, match in enumerate(matches):
        if speakers is not None and match.group(1) not in speakers:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[start:end].strip()
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
    *,
    runtime_tolerance: float = RUNTIME_TOLERANCE,
) -> dict[str, Any]:
    """Return ``status``/``issues``/``metrics`` for one treatment.

    Schema validity is checked separately by the checkpoint writer or CLI.
    This function focuses on cross-artifact rules that a JSON schema cannot see.
    """
    issues: list[str] = []
    sections = treatment.get("enhanced_sections") or []
    added_beats = treatment.get("added_beats") or []
    motifs = treatment.get("visual_motifs") or []
    beats = treatment.get("beat_map") or []
    ledger = treatment.get("fidelity_ledger") or []
    meta = treatment.get("metadata") or {}

    if not sections:
        issues.append("enhanced_sections is empty")

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
        if abs(delta_pct) > runtime_tolerance * 100:
            issues.append(
                f"runtime {total:.3f}s is {delta_pct:+.1f}% from target {target:.3f}s "
                f"(tolerance ±{runtime_tolerance * 100:.0f}%)"
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

    # Spoken-word fidelity: no new dialogue or narration words.
    spoken_lines = 0
    if script:
        base_text = " ".join(str(s.get("text", "")) for s in script.get("sections", []))
        base_speakers = speaker_names(base_text)
        original_text = normalize_text(base_text)
        for section in sections:
            sid = section.get("id", "?")
            for marker in speaker_names(str(section.get("text", ""))):
                if marker not in base_speakers and marker.lower() not in VISUAL_LABELS:
                    issues.append(f"{sid}: new speaker/dialogue marker {marker!r} is not in the base script")
            for line in extract_spoken(str(section.get("text", "")), base_speakers):
                spoken_lines += 1
                if normalize_text(line) not in original_text:
                    issues.append(
                        f"{sid}: spoken line is not in the base script: {line[:80]!r}"
                    )
    if meta.get("fidelity_status") not in ("pass", "revise"):
        issues.append("metadata.fidelity_status must be 'pass' or 'revise'")
    elif meta.get("fidelity_status") == "revise":
        issues.append("metadata.fidelity_status is 'revise'")

    return {
        "status": "pass" if not issues else "revise",
        "issues": issues,
        "metrics": {
            "section_count": len(sections),
            "added_section_count": len(added_ids),
            "runtime_seconds": round(total, 3),
            "runtime_target_seconds": round(target, 3),
            "runtime_delta_percent": round((total - target) / target * 100, 2) if target else None,
            "spoken_lines": spoken_lines,
            "visual_motifs": len(motifs),
            "added_beats": len(added_beats),
        },
    }
