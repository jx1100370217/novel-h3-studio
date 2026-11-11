#!/usr/bin/env python3
"""QC a cinematic project's FastH3 takes before the edit is locked.

For every take this measures integrated loudness / true peak, samples three
frames for visual inspection, and transcribes the native audio so the heard
dialogue can be compared with the scripted lines. The resulting
``artifacts/asset_qc.json`` is the source for the per-shot gain values used by
the edit and the final audio mix.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = Path(
    '/home/jx/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/'
    'snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
)
CJK = re.compile(r'[^\u4e00-\u9fff]')


def log(message: str) -> None:
    print(message, flush=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def probe_duration(path: Path) -> float:
    return float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(path)], text=True).strip())


def transcribe(path: Path, model: WhisperModel) -> list[str]:
    with tempfile.TemporaryDirectory(prefix='cine_qc_') as tmp:
        wav = Path(tmp) / 'audio.wav'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-y', '-i', str(path),
             '-ac', '1', '-ar', '16000', str(wav)], check=True)
        with wave.open(str(wav), 'rb') as handle:
            raw = handle.readframes(handle.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, language='zh', vad_filter=True)
    return [segment.text for segment in segments]


def loudness(path: Path) -> tuple[float | None, float | None]:
    stderr = subprocess.run(
        ['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'ebur128=peak=true',
         '-f', 'null', '-'], capture_output=True, text=True).stderr
    integrated = re.findall(r'I:\s+(-?[\d.]+) LUFS', stderr)
    peak = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', stderr)
    return (float(integrated[-1]) if integrated else None,
            float(peak[-1]) if peak else None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--shots', default='', help='comma-separated ids; default all')
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    project = args.project.resolve()
    scene_plan = load(project / 'artifacts/scene_plan.json')
    takes = load(project / 'assets/take_manifest.json')
    shots = {shot['id']: shot for shot in scene_plan['metadata']['shots']}
    wanted = [sid.strip() for sid in args.shots.split(',') if sid.strip()] or sorted(shots)
    frames_dir = project / 'artifacts/qc_frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(str(args.model) if args.model.is_dir() else 'large-v3-turbo',
                         device='cpu', compute_type='int8')

    qc_path = project / 'artifacts/asset_qc.json'
    existing = load(qc_path) if qc_path.is_file() else {'shots': []}
    existing_shots = existing.get('shots', [])
    if isinstance(existing_shots, dict):
        existing_shots = list(existing_shots.values())
    rows = {row['shot']: row for row in existing_shots if 'shot' in row}

    for index, sid in enumerate(wanted, 1):
        shot = shots[sid]
        take = takes.get(sid) or {}
        video = Path(take.get('path') or project / 'assets/shots' / f'{sid}.mp4')
        if not video.is_file():
            log(f'MISSING {sid} ({index}/{len(wanted)}) {video}')
            continue
        duration = probe_duration(video)
        frame_paths = []
        for number, timestamp in enumerate((1.0, duration / 2, max(0.2, duration - 1.0))):
            frame = frames_dir / f'{sid}_{number}.jpg'
            subprocess.run(
                ['ffmpeg', '-v', 'error', '-y', '-ss', f'{timestamp:.3f}',
                 '-i', str(video), '-frames:v', '1', '-vf', 'scale=448:256', str(frame)],
                check=True)
            frame_paths.append(str(frame))
        expected = ''.join(line['text'] for line in shot.get('lines') or [])
        heard = ''.join(transcribe(video, model))
        ratio = (SequenceMatcher(None, CJK.sub('', expected), CJK.sub('', heard)).ratio()
                 if expected else None)
        lufs, peak = loudness(video)
        row = {
            'shot': sid,
            'duration': round(duration, 3),
            'expected': expected,
            'heard': heard,
            'text_ratio': round(ratio, 3) if ratio is not None else None,
            'lufs': lufs,
            'true_peak': peak,
            'frames': frame_paths,
            'status': 'ok' if ((ratio is None or ratio >= 0.75)
                               and (lufs is None or -32 <= lufs <= -10)) else 'review',
        }
        rows[sid] = row
        log(f'{sid} {row["status"]} ratio={row["text_ratio"]} lufs={lufs} '
            f'peak={peak} ({index}/{len(wanted)})')

    ordered = [rows[sid] for sid in sorted(rows)]
    dump(qc_path, {'version': '1.0', 'shots': ordered})
    review = [row['shot'] for row in ordered if row['status'] != 'ok']
    log(f'DONE shots={len(ordered)} review={review}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
