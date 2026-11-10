#!/usr/bin/env python3
"""Asset QC for cinematic shots: sample frames and flag burned-in captions.

The cinematic composition burns approved captions in Remotion. A take that
already contains a generated caption would therefore show two caption rows.
This scanner samples three frames per shot, OCRs the lower caption band, and
reports shots that should be inspected/cropped before composition.

Use ``--crop`` only for a flagged shot whose caption is in the bottom band; it
crops 130 px, rescales to the delivery canvas, and writes the composition copy
to ``public/shots`` while leaving the raw take untouched.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
import numpy as np

CJK = re.compile(r'[\u3400-\u9fff]')


def probe_duration(video: Path) -> float:
    return float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(video)], text=True).strip())


def ocr_band(video: Path, seconds: float, work: Path) -> str:
    band = work / 'band.png'
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-ss', f'{seconds:.3f}', '-i', str(video),
         '-frames:v', '1', '-vf', 'crop=iw*0.8:ih*0.28:iw*0.1:ih*0.70,scale=iw*2:ih*2,format=gray',
         str(band)], check=True)
    pixels = np.asarray(Image.open(band).convert('L'), dtype=np.uint8)
    if float((pixels > 200).mean()) < 0.003:
        return ''
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
        if confidence < 55 or not CJK.search(word):
            continue
        key = (parts[2], parts[3], parts[4])
        row = rows.setdefault(key, {'height': 0, 'text': ''})
        row['height'] = max(row['height'], int(parts[8]))
        row['text'] += word
    return ''.join(row['text'] for row in rows.values()
                   if len(CJK.findall(row['text'])) >= 3 and row['height'] >= 18)


def scan(video: Path) -> dict:
    duration = probe_duration(video)
    hits = []
    with tempfile.TemporaryDirectory(prefix='cine_qc_') as tmp:
        work = Path(tmp)
        for fraction in (0.2, 0.35, 0.5, 0.65, 0.8):
            text = ocr_band(video, duration * fraction, work)
            if len(text) >= 2:
                hits.append({'at': round(duration * fraction, 2), 'text': text})
    return {'video': str(video), 'duration': round(duration, 3),
            'verdict': 'caption' if hits else 'clean', 'hits': hits}


def crop_for_composition(video: Path, public: Path) -> None:
    tmp = public.with_suffix('.tmp.mp4')
    public.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(video),
         '-vf', 'crop=iw:ih-130:0:0,scale=1344:768:flags=lanczos',
         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
         '-c:a', 'copy', '-movflags', '+faststart', str(tmp)], check=True)
    tmp.replace(public)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--shots', default='', help='comma-separated ids; default all')
    parser.add_argument('--crop', action='store_true', help='crop flagged shots into public/shots')
    args = parser.parse_args()
    project = args.project.resolve()
    shots_dir = project / 'assets/shots'
    public_dir = project / 'public/shots'
    wanted = [s.strip() for s in args.shots.split(',') if s.strip()] or sorted(
        p.stem for p in shots_dir.glob('S*.mp4'))
    report = {}
    for sid in wanted:
        video = shots_dir / f'{sid}.mp4'
        if not video.is_file():
            continue
        result = scan(video)
        report[sid] = result
        if result['verdict'] == 'caption' and args.crop:
            crop_for_composition(video, public_dir / f'{sid}.mp4')
            result['cropped_for_composition'] = True
        print(sid, result['verdict'], [hit['text'] for hit in result['hits']], flush=True)
    out = project / 'artifacts/asset_qc.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({'version': '1.0', 'shots': report,
                               'caption_shots': [k for k, v in report.items() if v['verdict'] == 'caption']},
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'caption_shots': [k for k, v in report.items() if v['verdict'] == 'caption']},
                     ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
