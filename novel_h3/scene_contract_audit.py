"""Audit the explicit scene / time / prop contract on delivery artifacts.

`screenplay_audit` checks the treatment. This audit checks the files the
director and the shot planner actually hand to production: the delivery
`script.json` and the `scene_plan.json`. For craft v4+ every scene and every
shot must name:

- `location`
- `time_of_day`
- `props` (non-empty list; use ``["none"]`` for a deliberately empty set)
- `set_dressing`

The final H3 prompt gate (`build_ref2va_specs`) separately requires `props`
on every shot, so a missing declaration cannot reach the render queue even
when this audit is skipped.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .screenplay_audit import scene_contract_issues, scene_contract_required


def audit_contract(
    treatment: dict[str, Any],
    script: dict[str, Any] | None = None,
    scene_plan: dict[str, Any] | None = None,
    *,
    strict: bool | None = None,
) -> dict[str, Any]:
    """Return ``status``/``issues``/``metrics`` for the physical scene contract."""
    if strict is None:
        strict = scene_contract_required(treatment)
    if not strict:
        return {
            'status': 'pass',
            'skipped': True,
            'issues': [],
            'metrics': {'strict': False},
        }

    issues: list[str] = []
    treatment_sections = treatment.get('enhanced_sections') or []
    script_sections = (script or {}).get('sections') or []
    scene_plan_scenes = (scene_plan or {}).get('scenes') or []

    for section in treatment_sections:
        sid = section.get('id', '?')
        issues.extend(scene_contract_issues(section, f'treatment {sid}'))
    for section in script_sections:
        sid = section.get('id', '?')
        issues.extend(scene_contract_issues(section, f'script {sid}'))

    script_ids = {str(section.get('id')) for section in script_sections}
    for scene in scene_plan_scenes:
        sid = scene.get('id', '?')
        issues.extend(scene_contract_issues(scene, f'scene_plan {sid}'))
        section_id = scene.get('script_section_id')
        if script_ids and section_id is not None and str(section_id) not in script_ids:
            issues.append(f'scene_plan {sid}: script_section_id {section_id!r} is not in the script')

    return {
        'status': 'pass' if not issues else 'revise',
        'skipped': False,
        'issues': issues,
        'metrics': {
            'strict': True,
            'treatment_sections': len(treatment_sections),
            'script_sections': len(script_sections),
            'scene_plan_scenes': len(scene_plan_scenes),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--treatment', type=Path, required=True)
    parser.add_argument('--script', type=Path)
    parser.add_argument('--scene-plan', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--strict', action='store_true',
                        help='audit even when the treatment is older than craft v4')
    args = parser.parse_args(argv)

    treatment = json.loads(args.treatment.read_text(encoding='utf-8'))
    script = json.loads(args.script.read_text(encoding='utf-8')) if args.script else None
    scene_plan = (json.loads(args.scene_plan.read_text(encoding='utf-8'))
                  if args.scene_plan else None)
    report = audit_contract(
        treatment, script, scene_plan,
        strict=True if args.strict else None,
    )
    report['treatment'] = str(args.treatment)
    report['script'] = str(args.script) if args.script else None
    report['scene_plan'] = str(args.scene_plan) if args.scene_plan else None
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
