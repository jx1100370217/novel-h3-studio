#!/usr/bin/env python3
"""Validate and audit a screenplay_treatment artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "openmontage"))

from novel_h3.screenplay_audit import audit_treatment
from schemas.artifacts import validate_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--treatment", type=Path, required=True)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    treatment = json.loads(args.treatment.read_text(encoding="utf-8"))
    script = json.loads(args.script.read_text(encoding="utf-8")) if args.script else None
    try:
        validate_artifact("screenplay_treatment", treatment)
    except Exception as exc:  # jsonschema.ValidationError
        print(f"SCHEMA FAIL: {exc}")
        return 1

    report = audit_treatment(treatment, script)
    report["treatment"] = str(args.treatment)
    report["script"] = str(args.script) if args.script else None
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "issues": report["issues"],
                      "warnings": report.get("warnings", []),
                      "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
