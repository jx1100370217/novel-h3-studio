#!/usr/bin/env python3
"""Audit explicit scene/time/prop fields on script and scene plan artifacts."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.scene_contract_audit import main

if __name__ == '__main__':
    raise SystemExit(main())
