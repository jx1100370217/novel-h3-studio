#!/usr/bin/env python3
"""Build per-character voice references from a project voice plan (global CLI)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from novel_h3.voice_refs import build_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    parser.add_argument('--out-dir', default='')
    args = parser.parse_args()
    import json
    plan_path = ROOT / args.plan
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    line_manifest = ROOT / plan['line_manifest']
    output_dir = ROOT / (args.out_dir or plan['output_dir'])
    manifest = build_manifest(line_manifest, plan, output_dir)
    print(f"wrote {output_dir / 'voice_manifest.json'} ({len(manifest['references'])} voices)")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
