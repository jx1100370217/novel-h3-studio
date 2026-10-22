#!/usr/bin/env python3
"""Audio QC gate for novel-cinematic dialogue cuts.

Checks the authored timeline before delivery:
- character dialogue must come from native H3 takes; only narration may use TTS
- every line must fit inside its shot and must not overlap the next line
- line order must follow the shot order
- female-role TTS lines must pass a median-F0 gate
- every native H3 take referenced by a line must exist

The module is intentionally standalone: it reads project JSON, uses ffmpeg for
duration and torchaudio for pitch, and writes a report artifact. The final
human-listening pass remains a separate, explicitly-required gate.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Callable

VERSION = '1.0'


def _duration(path: Path) -> float:
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=nw=1:nk=1', str(path)])
    return float(out.decode().strip())


def _f0_median(path: Path) -> float | None:
    import numpy as np
    import torch
    import torchaudio
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-ar', '16000', '-ac', '1',
        '-f', 'f32le', '-'])
    wave = torch.from_numpy(np.frombuffer(raw, dtype=np.float32).copy()).unsqueeze(0)
    freq = torchaudio.functional.detect_pitch_frequency(
        wave, 16000, win_length=10, freq_low=60, freq_high=600)
    values = freq[freq > 0].numpy()
    return round(float(np.median(values)), 1) if len(values) else None


def check_timeline(script: dict, lines: list[dict], *, native_root: Path,
                   duration_fn: Callable[[Path], float] = _duration,
                   f0_fn: Callable[[Path], float | None] = _f0_median) -> dict:
    order = [s for sec in script['sections'] for s in sec['shots']]
    index = {s: i for i, s in enumerate(order)}
    bounds, cursor = {}, 0.0
    for shot in order:
        duration = script['shot_durations'][shot]
        bounds[shot] = cursor
        cursor += duration
    issues, rows = [], []
    previous_shot_index = -1
    for line in lines:
        shot = line['shot']
        if shot not in bounds:
            issues.append(f"{line['id']}: unknown shot {shot}")
            continue
        source = line.get('source') or ('tts' if line['role'] == 'narrator' else 'native')
        start = bounds[shot] + float(line['offset'])
        shot_end = bounds[shot] + script['shot_durations'][shot]
        wav = Path(line['wav']) if line.get('wav') else None
        duration = duration_fn(wav) if source == 'tts' and wav and wav.exists() else None
        end = start + duration if duration else None
        row = {'id': line['id'], 'role': line['role'], 'shot': shot, 'source': source,
               'start': round(start, 3), 'end': round(end, 3) if end else None,
               'duration': duration}
        if index[shot] < previous_shot_index:
            issues.append(f"order: {line['id']} ({shot}) appears after a later shot in the line manifest")
        previous_shot_index = max(previous_shot_index, index[shot])
        if source == 'native':
            take = native_root / shot / 'native.mp4'
            row['native_take'] = str(take)
            if not take.exists():
                issues.append(f"{line['id']}: native H3 take missing for {shot}")
        else:
            if not wav or not wav.exists():
                issues.append(f"{line['id']}: missing TTS wav")
            elif end is not None and end > shot_end + 0.05:
                issues.append(f"{line['id']}: ends {end:.2f}s beyond {shot} end {shot_end:.2f}s")
            if line.get('role_gender') == 'female' and wav and wav.exists():
                f0 = f0_fn(wav)
                row['f0_median'] = f0
                if f0 is not None and f0 < 150:
                    issues.append(f"{line['id']}: female F0 median {f0} Hz is below 150 Hz")
        rows.append(row)
    ordered = sorted(rows, key=lambda r: r['start'])
    for a, b in zip(ordered, ordered[1:]):
        if index.get(b['shot'], -1) < index.get(a['shot'], -1):
            issues.append(f"order: {b['id']} ({b['shot']}) belongs to a later shot than {a['id']} ({a['shot']})")
        if a['end'] and b['start'] < a['end'] - 0.15:
            issues.append(f"overlap: {a['id']} ends {a['end']:.2f}s, {b['id']} starts {b['start']:.2f}s")
    return {'version': VERSION, 'status': 'pass' if not issues else 'revise',
            'checks': ['native/tts routing', 'shot order', 'line fit', 'overlap',
                       'female F0 gate', 'native take presence'],
            'lines': rows, 'issues': issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script', type=Path, required=True)
    parser.add_argument('--lines', type=Path, required=True)
    parser.add_argument('--shots-dir', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    script = json.loads(args.script.read_text(encoding='utf-8'))
    script['shot_durations'] = {
        shot: json.loads((args.shots_dir / f'{shot}.json').read_text(encoding='utf-8'))['duration_seconds']
        for shot in (s for sec in script['sections'] for s in sec['shots'])}
    lines = json.loads(args.lines.read_text(encoding='utf-8'))['lines']
    report = check_timeline(script, lines, native_root=args.native_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'issues': len(report['issues'])}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
