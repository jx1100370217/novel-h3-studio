"""Cheap visual-quality gate for rendered takes.

H3 can drift into a dark, blue, noisy or soft look in the middle of a scene
even when the prompt, cast and references are unchanged. This audit samples
frames and flags takes whose median luminance or Laplacian sharpness is far
below the rest of the chapter, so a blurry take is caught before compose.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_W, SAMPLE_H = 672, 384


def _duration(video: Path) -> float:
    return float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(video)], text=True).strip())


def _frame(video: Path, seconds: float) -> np.ndarray:
    raw = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-ss', f'{seconds:.3f}', '-i', str(video),
         '-frames:v', '1', '-vf', f'scale={SAMPLE_W}:{SAMPLE_H},format=gray',
         '-f', 'rawvideo', '-pix_fmt', 'gray', '-'])
    return np.frombuffer(raw, dtype=np.uint8).reshape(SAMPLE_H, SAMPLE_W).astype(np.float64)


def _sharpness(image: np.ndarray) -> float:
    lap = (-4.0 * image
           + np.roll(image, 1, 0) + np.roll(image, -1, 0)
           + np.roll(image, 1, 1) + np.roll(image, -1, 1))
    return float(lap.var())


def audit_take(video: Path, *, samples: int = 8,
               min_luminance: float = 18.0, min_sharpness: float = 25.0) -> dict:
    duration = _duration(video)
    metrics = []
    for index in range(samples):
        seconds = duration * (index + 0.5) / samples
        image = _frame(video, seconds)
        metrics.append({'at_seconds': round(seconds, 2),
                        'luminance': round(float(image.mean()), 2),
                        'sharpness': round(_sharpness(image), 2)})
    luminance = float(np.median([item['luminance'] for item in metrics]))
    sharpness = float(np.median([item['sharpness'] for item in metrics]))
    issues = []
    if luminance < min_luminance:
        issues.append(f'dark (median luminance {luminance:.1f})')
    if sharpness < min_sharpness:
        issues.append(f'soft (median sharpness {sharpness:.1f})')
    return {'verdict': 'review' if issues else 'pass',
            'luminance': round(luminance, 2), 'sharpness': round(sharpness, 2),
            'issues': issues, 'frames': metrics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Audit take luminance and sharpness.')
    parser.add_argument('--takes-dir', type=Path, required=True)
    parser.add_argument('--shots', default='')
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--samples', type=int, default=8)
    args = parser.parse_args(argv)
    wanted = [item.strip() for item in args.shots.split(',') if item.strip()]
    ids = wanted or sorted(path.name for path in args.takes_dir.iterdir() if path.is_dir())
    report = {}
    for sid in ids:
        video = args.takes_dir / sid / 'native.mp4'
        if not video.is_file():
            continue
        report[sid] = audit_take(video, samples=args.samples)
        report[sid]['path'] = str(video)
    output = args.output or args.takes_dir.parent / 'visual_qc.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    flagged = [sid for sid, item in report.items() if item['verdict'] == 'review']
    print(json.dumps({'audited': len(report), 'review': flagged}, ensure_ascii=False))
    return 1 if flagged else 0


if __name__ == '__main__':
    raise SystemExit(main())
