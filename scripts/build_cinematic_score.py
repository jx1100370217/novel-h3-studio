#!/usr/bin/env python3
"""Assemble a cinematic project's custom score from authored cue and SFX specs.

``assets/music/score_cues.json`` places music excerpts on shot boundaries::

    {"file": "assets/music/incompetech/Final Count.mp3", "source_start": 0.0,
     "duration": 44.0, "shot": "S25A", "offset": 0.0, "gain": 0.85}

``artifacts/sfx_cues.json`` places one-shot effects inside a shot::

    {"S25B": [{"file": "openmontage/.agents/skills/hyperframes-media/assets/sfx/whoosh-short.mp3",
               "at": 1.4, "gain": 0.4}]}

Paths that start with ``openmontage/`` are repository-relative; others are
project-relative. Shots are read from ``artifacts/edit_timing.json``, so the
score follows any re-timing. The bed is written to ``assets/music/music_bed_real_raw.wav``,
loudness-normalised to ``assets/music/music_bed.wav`` (-20 LUFS, 48 kHz). The
cue layout is authored project data; the builder itself is generic.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf
import librosa

ROOT = Path(__file__).resolve().parents[1]
SR = 48000


def load(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding='utf-8'))


def resolve(raw: str, project: Path) -> Path:
    path = (ROOT / raw) if raw.startswith('openmontage/') else (project / raw)
    if not path.is_file():
        raise SystemExit(f'missing audio: {path}')
    return path


def read(path: Path, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    y, _ = librosa.load(str(path), sr=SR, mono=False, offset=start, duration=duration)
    if y.ndim == 1:
        y = np.stack([y, y])
    if y.shape[0] == 1:
        y = np.stack([y[0], y[0]])
    return y


def normalise(y: np.ndarray, peak: float) -> np.ndarray:
    m = np.max(np.abs(y))
    return y / m * peak if m > 1e-9 else y


def place(bed: np.ndarray, y: np.ndarray, at: float, gain: float, fade_in: float, fade_out: float) -> None:
    n = y.shape[1]
    env = np.ones(n)
    fi = min(int(fade_in * SR), n // 2)
    fo = min(int(fade_out * SR), n // 2)
    if fi:
        env[:fi] = np.linspace(0, 1, fi)
    if fo:
        env[-fo:] *= np.linspace(1, 0, fo)
    y = y * env[None, :] * gain
    i = int(at * SR)
    j = min(bed.shape[1], i + n)
    if j > i:
        bed[:, i:j] += y[:, :j - i]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()

    timing = load(project / 'artifacts/edit_timing.json')
    total = float(timing['total_seconds'])
    starts = {shot['id']: float(shot['start']) for shot in timing['shots']}
    bed = np.zeros((2, int(total * SR)))

    for cue in load(project / 'assets/music/score_cues.json'):
        source = resolve(cue['file'], project)
        y = normalise(read(source, float(cue.get('source_start', 0.0)), float(cue['duration'])), 0.62)
        fade = float(cue.get('fade', 2.0))
        place(bed, y, starts[cue['shot']] + float(cue.get('offset', 0.0)), float(cue['gain']), fade, fade)

    sfx_path = project / 'artifacts/sfx_cues.json'
    sfx = load(sfx_path) if sfx_path.is_file() else {}
    for sid, events in sfx.items():
        for event in events:
            source = resolve(event['file'], project)
            duration = event.get('duration')
            y = normalise(read(source, 0.0, float(duration) if duration else None), float(event.get('peak', 0.6)))
            place(bed, y, starts[sid] + float(event['at']), float(event.get('gain', 0.3)),
                  float(event.get('fade_in', 0.02)), float(event.get('fade_out', 0.2)))

    delay = int(0.004 * SR)
    bed[1, delay:] = 0.94 * bed[1, delay:] + 0.06 * bed[0, :-delay]
    bed = np.tanh(bed * 1.05) / 1.05
    raw = project / 'assets/music/music_bed_real_raw.wav'
    sf.write(raw, bed.T.astype(np.float32), SR, subtype='PCM_16')
    print(f'wrote {raw} total {total:.3f}s peak {float(np.max(np.abs(bed))):.3f}', flush=True)

    bed_path = project / 'assets/music/music_bed.wav'
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(raw),
                    '-af', 'loudnorm=I=-20:TP=-3:LRA=9', '-ar', str(SR), '-c:a', 'pcm_s16le', str(bed_path)],
                   check=True)
    print(f'wrote {bed_path}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
