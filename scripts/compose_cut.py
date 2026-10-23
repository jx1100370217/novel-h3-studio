#!/usr/bin/env python3
"""Compose a cut from a JSON ComposeSpec (global CLI)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from novel_h3.compose_cut import compose


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True)
    args = parser.parse_args()
    print(json.dumps(compose(ROOT / args.spec), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
