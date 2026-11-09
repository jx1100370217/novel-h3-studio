#!/usr/bin/env python3
"""Audit a treatment or shot plan for repeated dialogue/exposition."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.dialogue_repetition import audit_lines, lines_from_sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--treatment', type=Path)
    parser.add_argument('--shots-dir', type=Path)
    parser.add_argument('--window', type=int, default=6)
    args = parser.parse_args()
    rows: list[dict] = []
    if args.treatment:
        treatment = json.loads(args.treatment.read_text(encoding='utf-8'))
        rows.extend(lines_from_sections(treatment.get('enhanced_sections') or []))
    if args.shots_dir:
        for index, path in enumerate(sorted(args.shots_dir.glob('S*.json'))):
            shot = json.loads(path.read_text(encoding='utf-8'))
            raw = shot.get('dialogue')
            if not raw:
                continue
            if isinstance(raw, str):
                parsed = lines_from_sections([{'id': shot.get('id', path.stem), 'text': raw}])
                for row in parsed:
                    row['section_index'] = index
                rows.extend(parsed)
                continue
            speaker, text = (raw[0], raw[1]) if isinstance(raw, (list, tuple)) else (shot.get('id'), raw)
            rows.append({'section': shot.get('id', path.stem), 'section_index': index,
                         'speaker': speaker, 'text': text})
    if not rows:
        parser.error('give --treatment or --shots-dir')
    report = audit_lines(rows, section_window=args.window)
    report['sources'] = [str(args.treatment) if args.treatment else None,
                         str(args.shots_dir) if args.shots_dir else None]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
