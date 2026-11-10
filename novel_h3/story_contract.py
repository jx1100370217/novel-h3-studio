"""Story-contract gate: action coverage, blocking guides, time jumps, props.

The earlier screenplay/continuity gates checked dialogue fidelity, scene
contracts and anchor framing. They did not check whether a written action beat
actually has a shot that can show it, whether a multi-person scene has a
persistent set map/blocking guide, or whether a time jump has a visual marker.
This module is the missing pre-production gate.

A project supplies ``story_contract.json`` (or builds one from its scene plan):

{
  "scenes": [
    {"id": "S01", "set_map": "river_night",
     "prop_manifest": {"allowed": ["boat", "bank", "lantern", "cup", "jar", "net"],
                       "forbidden": ["table", "bench", "canopy"]},
     "action_beats": [
       {"id": "S01-B1", "description": "Wang drives fish",
        "visual": "Wang raises his arms at the water; fish ripple toward Xu's net",
        "shots": ["S01D"]}
     ],
     "time_jump": null, "time_jump_visual": "", "transition": "cut"},
    ...
  ],
  "shots": [
    {"id": "S01D", "scene": "S01", "cast": ["xu", "wang"],
     "covers_beats": ["S01-B1"], "blocking_guide": "previs/S01D.png",
     "blocking_waiver": "", "props": ["boat", "net", "fish"],
     "blocking": "Xu on the boat camera-left; Wang on the bank camera-right"}
  ]
}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TIME_TRANSITIONS = {"fade", "card", "montage", "dissolve", "cut"}
REACTION_ROLES = {"reaction", "insert", "plate", "transition"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _norm(value: Any) -> str:
    return _text(value).lower()


def audit_contract(contract: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = Path(root) if root else Path.cwd()
    issues: list[str] = []
    warnings: list[str] = []
    scenes = [s for s in (contract.get("scenes") or []) if isinstance(s, dict)]
    shots = [s for s in (contract.get("shots") or []) if isinstance(s, dict)]
    if not scenes:
        issues.append("story contract has no scenes")
    if not shots:
        issues.append("story contract has no shots")

    scene_ids = [_text(s.get("id")) for s in scenes]
    if len(scene_ids) != len(set(scene_ids)):
        issues.append("scene ids are not unique")
    shot_ids = [_text(s.get("id")) for s in shots]
    if len(shot_ids) != len(set(shot_ids)):
        issues.append("shot ids are not unique")
    shot_by_id = {item["id"]: item for item in shots}
    scene_by_id = {item["id"]: item for item in scenes}

    beat_total = 0
    for scene in scenes:
        sid = _text(scene.get("id")) or "?"
        if not _text(scene.get("set_map")):
            issues.append(f"{sid}: set_map is missing")
        manifest = scene.get("prop_manifest") or {}
        if not isinstance(manifest, dict):
            issues.append(f"{sid}: prop_manifest must be an object")
            manifest = {}
        allowed = {_norm(x) for x in (manifest.get("allowed") or []) if _text(x)}
        forbidden = {_norm(x) for x in (manifest.get("forbidden") or []) if _text(x)}
        if not allowed:
            issues.append(f"{sid}: prop_manifest.allowed is empty")
        beats = [b for b in (scene.get("action_beats") or []) if isinstance(b, dict)]
        if not beats:
            issues.append(f"{sid}: action_beats is empty")
        local_beats = {_text(b.get("id")) for b in beats}
        beat_total += len(beats)
        for beat in beats:
            bid = _text(beat.get("id")) or "?"
            if not _text(beat.get("description")):
                issues.append(f"{bid}: action beat has no description")
            if not _text(beat.get("visual")):
                issues.append(f"{bid}: action beat needs a visible action, not only a fact")
            covered_by = [str(x) for x in (beat.get("shots") or [])]
            if not covered_by:
                issues.append(f"{bid}: action beat is not assigned to any shot")
            for shot_id in covered_by:
                shot = shot_by_id.get(shot_id)
                if shot is None:
                    issues.append(f"{bid}: names absent shot {shot_id}")
                elif _text(shot.get("scene")) != sid:
                    issues.append(f"{bid}: shot {shot_id} belongs to {shot.get('scene')}, not {sid}")
                elif bid not in {str(x) for x in (shot.get("covers_beats") or [])}:
                    issues.append(f"{bid}: shot {shot_id} does not declare covers_beats {bid}")

        jump = scene.get("time_jump")
        if jump not in (None, "", "none", "continuous"):
            if not _text(scene.get("time_jump_visual")):
                issues.append(f"{sid}: time jump needs a visual marker (time_jump_visual)")
            transition = _norm(scene.get("transition"))
            if transition not in TIME_TRANSITIONS:
                issues.append(
                    f"{sid}: time jump transition {transition!r} is not one of {sorted(TIME_TRANSITIONS)}")

        for shot in shots:
            if _text(shot.get("scene")) != sid:
                continue
            shid = _text(shot.get("id")) or "?"
            props = [_norm(x) for x in (shot.get("props") or []) if _text(x)]
            if not props:
                issues.append(f"{shid}: props is empty; declare the actual set/props")
            for prop in props:
                if prop in forbidden:
                    issues.append(f"{shid}: forbidden prop {prop!r} is declared")
                elif allowed and prop not in allowed:
                    # The manifest may use broader names; report as a warning so
                    # a project can still use a precise prop name.
                    warnings.append(f"{shid}: prop {prop!r} is not in the scene allow-list")
            cast = [str(x) for x in (shot.get("cast") or [])]
            extras = [str(x) for x in (shot.get("extras") or [])]
            if len(cast) + len(extras) >= 2:
                guide = _text(shot.get("blocking_guide"))
                waiver = _text(shot.get("blocking_waiver"))
                if not guide and not waiver:
                    issues.append(f"{shid}: multi-person shot needs blocking_guide or blocking_waiver")
                if guide:
                    path = Path(guide)
                    if not path.is_absolute():
                        path = root / path
                    if not path.is_file():
                        issues.append(f"{shid}: blocking guide is missing: {path}")
            covers = [str(x) for x in (shot.get("covers_beats") or [])]
            if not covers and _norm(shot.get("role")) not in REACTION_ROLES:
                warnings.append(f"{shid}: covers_beats is empty; mark it as reaction/insert/transition if intentional")
            for bid in covers:
                if bid not in local_beats:
                    issues.append(f"{shid}: covers unknown action beat {bid}")

    # Every shot must belong to a scene.
    for shot in shots:
        sid = _text(shot.get("scene"))
        if sid not in scene_by_id:
            issues.append(f"{shot.get('id', '?')}: unknown scene {sid!r}")

    metrics = {
        "scenes": len(scenes), "shots": len(shots), "action_beats": beat_total,
        "multi_person_shots": sum(
            1 for s in shots if len(s.get("cast") or []) + len(s.get("extras") or []) >= 2),
        "guided_shots": sum(1 for s in shots if _text(s.get("blocking_guide"))),
        "waived_shots": sum(1 for s in shots if _text(s.get("blocking_waiver"))),
        "time_jumps": sum(
            1 for s in scenes if s.get("time_jump") not in (None, "", "none", "continuous")),
    }
    return {
        "status": "pass" if not issues else "revise",
        "issues": issues,
        "warnings": warnings,
        "metrics": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    report = audit_contract(contract, root=args.root or args.contract.parent)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
