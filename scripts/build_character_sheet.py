#!/usr/bin/env python3
"""Build a two-view lead character-sheet prompt from a JSON spec."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.character_sheet import CharacterSheetSpec, build_character_sheet_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True, help="CharacterSheetSpec JSON")
    parser.add_argument("--out", type=Path, help="Write the prompt here; default stdout")
    args = parser.parse_args()
    data = json.loads(args.spec.read_text(encoding="utf-8"))
    spec = CharacterSheetSpec.from_dict(data)
    prompt = build_character_sheet_prompt(spec)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(prompt, encoding="utf-8")
        print(args.out)
    else:
        print(prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
