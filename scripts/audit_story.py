#!/usr/bin/env python3
"""CLI for the story-contract gate (action coverage, blocking, time, props)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.story_contract import main

if __name__ == '__main__':
    raise SystemExit(main())
