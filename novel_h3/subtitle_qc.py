"""Post-compose caption audit: no frame may carry two dialogue lines.

The per-take scan decides which shots keep their native caption and which get
a burned subtitle. This gate checks the finished chapter itself, so a missed
native caption or a double burn is caught before delivery.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .subtitle_audit import CJK, ZONE_H, ZONE_W, ZONE_X, ZONE_Y, _band_has_bright_text

MIN_CONF = 60.0
MIN_ROW_CHARS = 3
MIN_ROW_HEIGHT = 70


def _ocr_rows(video: Path, seconds: float, workdir: Path) -> list[dict]:
    band = workdir / 'qc_band.png'
    crop = (f'crop=iw*{ZONE_W}:ih*{ZONE_H}:iw*{ZONE_X}:ih*{ZONE_Y},'
            f'scale=iw*2:ih*2,format=gray')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-ss', f'{seconds:.3f}', '-i', str(video), '-frames:v', '1',
                    '-vf', crop, str(band)], check=True)
    if not _band_has_bright_text(band):
        return []
    result = subprocess.run(
        ['tesseract', str(band), '-', '-l', 'chi_sim', '--psm', '6', 'tsv'],
        capture_output=True, text=True)
    rows: dict[tuple[str, str, str], dict] = {}
    for line in result.stdout.splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            confidence = float(parts[10])
        except ValueError:
            continue
        word = parts[11].strip()
        if confidence < MIN_CONF or not CJK.search(word):
            continue
        key = (parts[2], parts[3], parts[4])
        row = rows.setdefault(key, {'top': int(parts[7]), 'height': int(parts[8]), 'words': []})
        row['words'].append(word)
    return [
        {'text': ''.join(row['words']), 'top': row['top'], 'height': row['height']}
        for row in rows.values()
        if len(''.join(row['words'])) >= MIN_ROW_CHARS and row['height'] >= MIN_ROW_HEIGHT
    ]


def scan_duplicate_captions(video: Path, *, duration: float, per_second: float = 2.0) -> dict:
    """Sample the subtitle band and flag frames with two separate text rows."""
    samples = max(1, int(duration * per_second))
    hits = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for index in range(samples):
            seconds = duration * (index + 0.5) / samples
            rows = _ocr_rows(video, seconds, workdir)
            if len(rows) < 2:
                continue
            rows.sort(key=lambda row: row['top'])
            for first, second in zip(rows, rows[1:]):
                if second['top'] - first['top'] >= 30:
                    hits.append({
                        'at_seconds': round(seconds, 2),
                        'rows': [first['text'], second['text']],
                    })
                    break
    return {'verdict': 'duplicate' if hits else 'clean', 'hits': hits}


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import subprocess

    parser = argparse.ArgumentParser(description='Scan a finished cut for double captions.')
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=0.0)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args(argv)
    duration = args.duration or float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(args.video)], text=True).strip())
    report = scan_duplicate_captions(args.video, duration=duration)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report['verdict'] == 'duplicate' else 0


if __name__ == '__main__':
    raise SystemExit(main())
