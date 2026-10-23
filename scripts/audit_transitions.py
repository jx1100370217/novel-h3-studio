#!/usr/bin/env python3
"""Global CLI for the cut-boundary transition audit."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from novel_h3.transition_audit import build_report, load_script_order


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video', required=True)
    p.add_argument('--script', required=True)
    p.add_argument('--shots-dir', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--verdicts', default='')
    args = p.parse_args()
    script = json.loads((ROOT / args.script).read_text(encoding='utf-8'))
    order = load_script_order(script)
    durations = {sid: json.loads((ROOT / args.shots_dir / f'{sid}.json').read_text(encoding='utf-8'))['duration_seconds']
                 for sid in order}
    verdicts = {}
    if args.verdicts:
        verdicts = json.loads((ROOT / args.verdicts).read_text(encoding='utf-8')).get('verdicts', {})
    report = build_report(ROOT / args.video, order, durations, ROOT / args.out, verdicts)
    md = ['# 逐切点衔接审查', '', f"- 切点：{report['cut_count']}", f"- 统计：{report['counts']}", '',
          '| # | 切点 | 判定 | 问题 | 观察 | 修正 |', '|---|---|---|---|---|---|']
    for row in report['cuts']:
        md.append(f"| {row['index']} | {row['from']} → {row['to']} | {row['verdict']} | {row['category']} | {row['observation']} | {row['action']} |")
    (ROOT / args.out / 'transition_report.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(json.dumps({'cut_count': report['cut_count'], 'counts': report['counts'],
                      'needs_fix': report['needs_fix_cuts'], 'report': str(ROOT / args.out / 'transition_report.json')},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
