"""Cut-boundary extraction and transition audit (global).

The audit samples the last frame before and the first frame after every cut,
renders a contact sheet, and merges authored verdicts. It is deliberately
generic: shot order/durations and per-cut verdicts are project data.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Iterable


def load_script_order(script: dict) -> list[str]:
    return [shot for section in script['sections'] for shot in section['shots']]


def bounds(order: Iterable[str], durations: dict[str, float]) -> list[tuple[str, float, float]]:
    result, cursor = [], 0.0
    for shot in order:
        duration = float(durations[shot])
        result.append((shot, cursor, cursor + duration))
        cursor += duration
    return result


def extract_boundaries(video_path: Path, order: list[str], durations: dict[str, float],
                       out_dir: Path) -> list[dict]:
    video_path = Path(video_path).resolve()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    shot_bounds = bounds(order, durations)
    for i in range(len(shot_bounds) - 1):
        a, _sa, ea = shot_bounds[i]
        b, sb, _eb = shot_bounds[i + 1]
        last = out_dir / f'{i + 1:02d}_{a}_last.png'
        first = out_dir / f'{i + 1:02d}_{b}_first.png'
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{max(0.0, ea - 0.002):.4f}',
                        '-i', str(video_path), '-frames:v', '1', str(last)], check=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{sb + 0.002:.4f}',
                        '-i', str(video_path), '-frames:v', '1', str(first)], check=True)
        rows.append({'index': i + 1, 'from': a, 'to': b, 'cut_time': round(sb, 3),
                     'last_frame': str(last), 'first_frame': str(first)})
    return rows


def build_sheet(rows: list[dict], out_path: Path, *, cols: int = 5, width: int = 336, height: int = 192) -> str:
    from PIL import Image, ImageDraw, ImageFont
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_per_image = (len(rows) + cols - 1) // cols
    pair_w, pair_h = width * 2 + 12, height + 40
    sheet = Image.new('RGB', (cols * pair_w, rows_per_image * pair_h), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc', 24)
    except OSError:
        font = ImageFont.load_default()
    for idx, row in enumerate(rows):
        r, c = divmod(idx, cols)
        x, y = c * pair_w, r * pair_h
        draw.text((x + 6, y + 4), f"{row['index']:02d}  {row['from']} → {row['to']}", font=font, fill=(230, 220, 205))
        left = Image.open(row['last_frame']).convert('RGB').resize((width, height))
        right = Image.open(row['first_frame']).convert('RGB').resize((width, height))
        sheet.paste(left, (x + 4, y + 36))
        sheet.paste(right, (x + 8 + width, y + 36))
        draw.rectangle([x + 4, y + 36, x + 4 + width - 1, y + 36 + height - 1], outline=(120, 100, 60))
        draw.rectangle([x + 8 + width, y + 36, x + 8 + 2 * width - 1, y + 36 + height - 1], outline=(120, 100, 60))
    sheet.save(out_path, quality=92)
    return str(out_path)


def build_report(video_path: Path, order: list[str], durations: dict[str, float],
                 out_dir: Path, verdicts: dict | None = None,
                 *, sheet: bool = True) -> dict:
    out_dir = Path(out_dir)
    rows = extract_boundaries(video_path, order, durations, out_dir / 'transitions')
    verdicts = verdicts or {}
    for row in rows:
        item = verdicts.get(str(row['index'])) or verdicts.get(row['index']) or {}
        row['verdict'] = item.get('verdict', 'unreviewed')
        row['category'] = item.get('category', '')
        row['observation'] = item.get('observation', '')
        row['action'] = item.get('action', '')
    counts: dict[str, int] = {}
    for row in rows:
        counts[row['verdict']] = counts.get(row['verdict'], 0) + 1
    report = {
        'version': '1.0', 'source': str(Path(video_path).resolve()),
        'method': 'last frame before cut / first frame after cut, reviewed against shot prompts and state handoffs',
        'cut_count': len(rows), 'counts': counts, 'cuts': rows,
        'needs_fix_cuts': [row['index'] for row in rows if row['verdict'] == 'needs_fix'],
    }
    if sheet:
        report['sheet'] = build_sheet(rows, out_dir / 'transition_sheet.jpg')
    (out_dir / 'transition_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
