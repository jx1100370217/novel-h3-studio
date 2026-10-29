"""Burn-in subtitle audit for H3 takes.

H3 sometimes paints the spoken line onto the picture even when the prompt
forbids it. A subtitle is a delivery defect (the film is not subtitled), so
every take is scanned before it enters the cut: sample frames, OCR the
subtitle band and flag any line with enough confident CJK characters.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

# Normalised subtitle band: the lower third of the frame. H3 does not always
# paint captions at the same height, so the band covers everything from just
# below the faces to the bottom edge; OCR still requires several confident CJK
# characters, so sleeves and scenery do not trigger it.
ZONE_X, ZONE_Y, ZONE_W, ZONE_H = 0.22, 0.78, 0.56, 0.20
CJK = re.compile(r'[\u3400-\u9fff]')


def _ocr_frame(video: Path, seconds: float, workdir: Path) -> list[tuple[str, float]]:
    """Return confident characters found in one frame's subtitle band."""
    frame = workdir / 'frame.png'
    band = workdir / 'band.png'
    crop = (f'crop=iw*{ZONE_W}:ih*{ZONE_H}:iw*{ZONE_X}:ih*{ZONE_Y},'
            f'scale=iw*2:ih*2,format=gray')
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-ss', f'{seconds:.3f}', '-i', str(video), '-frames:v', '1',
                    '-vf', crop, str(band)], check=True)
    if not _band_has_bright_text(band):
        frame.unlink(missing_ok=True)
        return []
    result = subprocess.run(
        ['tesseract', str(band), '-', '-l', 'chi_sim', '--psm', '6', 'tsv'],
        capture_output=True, text=True)
    frame.unlink(missing_ok=True)
    return parse_tsv(result.stdout)


def _band_has_bright_text(band: Path) -> bool:
    """Cheap prefilter: H3 captions are near-white on a darker plate."""
    import numpy as np
    from PIL import Image

    pixels = np.asarray(Image.open(band).convert('L'), dtype=np.uint8)
    return float((pixels > 200).mean()) >= 0.005


def parse_tsv(output: str, *, min_confidence: float = 50.0) -> list[tuple[str, float]]:
    """Confident CJK words from tesseract TSV; low-confidence noise is dropped."""
    chars: list[tuple[str, float]] = []
    for line in output.splitlines()[1:]:
        parts = line.split('\t')
        if len(parts) < 12 or not parts[11].strip():
            continue
        try:
            confidence = float(parts[10])
        except ValueError:
            continue
        word = parts[11].strip()
        if confidence >= min_confidence and CJK.search(word):
            chars.append((word, confidence))
    return chars


def scan_take(video: Path, *, duration: float, samples: int = 48) -> dict:
    """Sample ``samples`` frames and report subtitle-like text lines."""
    hits = []
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for index in range(samples):
            seconds = duration * (index + 0.5) / samples
            chars = _ocr_frame(video, seconds, workdir)
            # A subtitle line carries several characters; one stray glyph is
            # background texture, not a caption.
            cjk_count = sum(len(CJK.findall(word)) for word, _ in chars)
            if cjk_count >= 3:
                hits.append({'at_seconds': round(seconds, 2),
                             'text': ''.join(word for word, _ in chars)[:40]})
    return {'verdict': 'text' if hits else 'clean', 'hits': hits}


def audit_takes(takes_dir: Path, shot_ids: Iterable[str]) -> dict:
    """Scan every shot that has a rendered take."""
    takes_dir = Path(takes_dir)
    report: dict[str, dict] = {}
    for sid in shot_ids:
        video = takes_dir / sid / 'native.mp4'
        if not video.is_file():
            continue
        duration = float(subprocess.check_output(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=nw=1:nk=1', str(video)], text=True).strip())
        report[sid] = scan_take(video, duration=duration)
        report[sid]['path'] = str(video)
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Scan takes for burned-in subtitles.')
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--takes-subdir', default='takes_all')
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    scene_plan = json.loads((project / 'artifacts/scene_plan.json').read_text(encoding='utf-8'))
    ids = [str(scene['id']) for scene in scene_plan['scenes']]
    report = audit_takes(project / args.takes_subdir, ids)
    output = args.output or project / 'artifacts/subtitle_audit.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    flagged = [sid for sid, item in report.items() if item['verdict'] == 'text']
    print(json.dumps({'scanned': len(report), 'flagged': flagged}, ensure_ascii=False))
    return 1 if flagged else 0


if __name__ == '__main__':
    raise SystemExit(main())
