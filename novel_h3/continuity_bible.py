"""Build and audit the V6+ continuity bible.

The bible is the script supervisor's machine-checkable ledger: every shot
declares its visible cast, costume/prop state, hand ownership, eyeline, axis,
screen direction, light, time, opening/closing state and anchor keyframe.

The audit is deliberately literal. It cannot understand a performance, but it
can stop the known failure modes that make independently generated takes cut
together badly.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_SCENE = (
    "scene_id", "sequence_id", "story_day", "time_of_day", "location", "cast",
    "costume", "props", "axis", "screen_direction", "light", "shots",
)
REQUIRED_SHOT = (
    "shot_id", "open_state", "close_state", "cast", "costume_state", "prop_state",
    "hand_ownership", "eyeline", "axis_side", "screen_direction", "light_state",
    "time_state", "anchor_image", "continuity_in", "continuity_out",
)


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _text(value: Any) -> str:
    return str(value or "").strip()


def bible_from_plan(scene_plan: dict[str, Any], *, project_id: str = "") -> dict[str, Any]:
    """Build a bible from a scene plan whose scenes carry continuity fields."""
    scenes: list[dict[str, Any]] = []
    by_scene: dict[str, list[dict]] = {}
    for shot in scene_plan.get("scenes") or []:
        if not isinstance(shot, dict):
            continue
        by_scene.setdefault(str(shot.get("script_section_id") or ""), []).append(shot)
    for section_id, shots in by_scene.items():
        first = shots[0]
        continuity = first.get("scene_continuity") or {}
        scene = {
            "scene_id": section_id,
            "sequence_id": str(continuity.get("sequence_id") or first.get("sequence_id") or ""),
            "story_day": int(continuity.get("story_day") or first.get("story_day") or 1),
            "time_of_day": str(first.get("time_of_day") or ""),
            "location": str(first.get("location") or ""),
            "cast": list(continuity.get("cast") or first.get("cast") or []),
            "costume": dict(continuity.get("costume") or {}),
            "props": list(first.get("props") or []),
            "axis": str(continuity.get("axis") or first.get("axis") or ""),
            "screen_direction": str(continuity.get("screen_direction") or first.get("screen_direction") or ""),
            "light": str(continuity.get("light") or first.get("light") or ""),
            "shots": [],
        }
        for shot in shots:
            c = shot.get("continuity") or {}
            scene["shots"].append({
                "shot_id": str(shot.get("id")),
                "open_state": str(c.get("open_state") or ""),
                "close_state": str(c.get("close_state") or ""),
                "cast": list(c.get("cast") or shot.get("cast") or []),
                "extras": list(c.get("extras") or shot.get("extras") or []),
                "costume_state": dict(c.get("costume_state") or {}),
                "prop_state": dict(c.get("prop_state") or {}),
                "hand_ownership": str(c.get("hand_ownership") or ""),
                "eyeline": str(c.get("eyeline") or ""),
                "axis_side": str(c.get("axis_side") or ""),
                "axis_cross": bool(c.get("axis_cross", False)),
                "screen_direction": str(c.get("screen_direction") or ""),
                "light_state": str(c.get("light_state") or ""),
                "time_state": str(c.get("time_state") or ""),
                "anchor_image": str(c.get("anchor_image") or ""),
                "continuity_in": str(c.get("continuity_in") or ""),
                "continuity_out": str(c.get("continuity_out") or ""),
                "notes": str(c.get("notes") or ""),
            })
        scenes.append(scene)
    return {"version": "1.0", "project_id": project_id, "scenes": scenes}


def audit_bible(
    bible: dict[str, Any],
    *,
    project_root: Path | None = None,
    scene_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[str] = []
    warnings: list[str] = []
    scenes = [s for s in (bible.get("scenes") or []) if isinstance(s, dict)]
    if not scenes:
        issues.append("continuity bible has no scenes")
    shot_count = 0
    for scene in scenes:
        sid = _text(scene.get("scene_id")) or "?"
        for key in REQUIRED_SCENE:
            if key == "shots":
                continue
            if key in ("cast", "props"):
                if not isinstance(scene.get(key), list) or not scene[key]:
                    issues.append(f"{sid}: scene continuity needs a non-empty {key} list")
            elif key == "costume":
                if not isinstance(scene.get(key), dict) or not scene[key]:
                    issues.append(f"{sid}: scene continuity needs a costume map")
            elif key == "story_day":
                if not isinstance(scene.get(key), int) or scene[key] < 1:
                    issues.append(f"{sid}: story_day must be a positive integer")
            elif not _text(scene.get(key)):
                issues.append(f"{sid}: scene continuity is missing {key}")
        shots = [x for x in (scene.get("shots") or []) if isinstance(x, dict)]
        if not shots:
            issues.append(f"{sid}: continuity bible has no shots")
            continue
        if len(shots) > 8:
            warnings.append(f"{sid}: {len(shots)} shots; a scene this fragmented is a continuity risk")
        if not any(_text(x.get("anchor_image")) for x in shots):
            issues.append(f"{sid}: no shot has an anchor image")
        has_master = any(
            "wide" in _norm(x.get("screen_direction")) or "establish" in _norm(x.get("eyeline"))
            or "wide" in _norm(x.get("open_state")) or "wide" in _norm(x.get("close_state"))
            for x in shots)
        if not has_master:
            warnings.append(f"{sid}: no obvious master/establishing shot in the bible")
        previous = None
        for index, shot in enumerate(shots, 1):
            shot_count += 1
            label = _text(shot.get("shot_id")) or f"{sid}#{index}"
            for key in REQUIRED_SHOT:
                if key in ("cast", "costume_state", "prop_state", "axis_cross", "extras"):
                    continue
                if not _text(shot.get(key)):
                    issues.append(f"{label}: continuity is missing {key}")
            if not isinstance(shot.get("cast"), list):
                issues.append(f"{label}: cast must be a list")
            if not isinstance(shot.get("costume_state"), dict):
                issues.append(f"{label}: costume_state must be an object")
            if not isinstance(shot.get("prop_state"), dict):
                issues.append(f"{label}: prop_state must be an object")
            anchor = _text(shot.get("anchor_image"))
            if anchor and project_root is not None:
                path = Path(anchor)
                if not path.is_absolute():
                    path = Path(project_root) / anchor
                if not path.is_file():
                    issues.append(f"{label}: anchor image is missing: {anchor}")
            if previous is not None:
                if _norm(previous.get("continuity_out")) != _norm(shot.get("continuity_in")):
                    issues.append(
                        f"{label}: continuity_in does not match previous continuity_out "
                        f"({_text(previous.get('continuity_out'))!r} -> {_text(shot.get('continuity_in'))!r})")
                if _norm(previous.get("axis_side")) != _norm(shot.get("axis_side")) \
                        and not shot.get("axis_cross"):
                    issues.append(f"{label}: axis changes without axis_cross; keep the 180° line")
                if _norm(previous.get("light_state")) != _norm(shot.get("light_state")) \
                        and "time jump" not in _norm(shot.get("notes")):
                    issues.append(f"{label}: light changes inside the scene without a time-jump note")
                if _norm(previous.get("time_state")) != _norm(shot.get("time_state")) \
                        and "time jump" not in _norm(shot.get("notes")):
                    issues.append(f"{label}: time_of_day changes inside the scene without a time-jump note")
                for person, costume in (shot.get("costume_state") or {}).items():
                    old = (previous.get("costume_state") or {}).get(person)
                    if old and _norm(old) != _norm(costume) and "costume change" not in _norm(shot.get("notes")):
                        issues.append(f"{label}: {person} changes costume without an authored costume change")
                for prop, state in (shot.get("prop_state") or {}).items():
                    old = (previous.get("prop_state") or {}).get(prop)
                    if old and _norm(old) != _norm(state) and "prop change" not in _norm(shot.get("notes")):
                        warnings.append(f"{label}: prop {prop!r} changes state; confirm the action is visible")
                if _norm(previous.get("screen_direction")) == _norm(shot.get("screen_direction")) \
                        and _norm(previous.get("eyeline")) == _norm(shot.get("eyeline")) \
                        and "intentional" not in _norm(shot.get("notes")):
                    warnings.append(f"{label}: same eyeline/screen direction as the previous shot; check for repeated coverage")
            previous = shot
    if scene_plan:
        plan_ids = {str(s.get("id")) for s in scene_plan.get("scenes") or [] if isinstance(s, dict)}
        bible_ids = {str(shot.get("shot_id")) for scene in scenes for shot in scene.get("shots") or []}
        missing = sorted(plan_ids - bible_ids)
        extra = sorted(bible_ids - plan_ids)
        if missing:
            issues.append("continuity bible is missing plan shots: " + ", ".join(missing[:12]))
        if extra:
            warnings.append("continuity bible has shots absent from the plan: " + ", ".join(extra[:12]))
    return {
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "scenes": len(scenes),
            "shots": shot_count,
            "with_anchor": sum(1 for s in scenes for x in s.get("shots") or [] if _text(x.get("anchor_image"))),
        },
        "status": "pass" if not issues else "revise",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bible", type=Path, required=True)
    parser.add_argument("--scene-plan", type=Path)
    parser.add_argument("--project-root", type=Path, default=None)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    bible = json.loads(args.bible.read_text(encoding="utf-8"))
    plan = json.loads(args.scene_plan.read_text(encoding="utf-8")) if args.scene_plan else None
    report = audit_bible(bible, project_root=args.project_root or args.bible.parent.parent,
                         scene_plan=plan)
    report["bible"] = str(args.bible)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
