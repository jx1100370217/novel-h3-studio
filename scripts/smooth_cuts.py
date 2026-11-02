#!/usr/bin/env python3
"""Apply a subtitle-safe two-frame blend at hard cuts."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.cut_smooth import main

if __name__ == '__main__':
    raise SystemExit(main())
