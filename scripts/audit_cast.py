#!/usr/bin/env python3
"""Run the global face-count audit on a takes directory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from novel_h3.cast_audit import audit_batch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--takes-dir', required=True)
    parser.add_argument('--expected', default='', help='JSON map shot -> maximum expected faces')
    parser.add_argument('--out', required=True)
    parser.add_argument('--fps', type=int, default=1)
    args = parser.parse_args()
    expected = {}
    if args.expected:
        expected = json.loads((ROOT / args.expected).read_text(encoding='utf-8'))
    result = audit_batch(ROOT / args.takes_dir, expected, ROOT / args.out, fps=args.fps)
    print(json.dumps({'suspect_shots': result['suspect_shots'], 'report': str(ROOT / args.out / 'cast_audit.json')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
