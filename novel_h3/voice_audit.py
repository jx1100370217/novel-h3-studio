"""Post-render voice identity audit.

The structural gate in ``spec_audit`` prevents the known swap (audio order vs
subject order). This audit is the second line of defence: it compares the
timbre of each spoken line in the finished take with every approved voice
reference and flags a line whose closest reference is not its assigned speaker.

It uses MFCC mean/std statistics, so it runs on numpy alone and does not need a
speaker-embedding model. A ``review`` verdict is triage for the human listening
pass, not a replacement for it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

SR = 16000
WIN = 400
HOP = 160
N_FFT = 512
N_MELS = 26
N_CEPS = 20


def _load_audio(path: Path, start: float | None = None, end: float | None = None) -> np.ndarray:
    cmd = ['ffmpeg', '-v', 'error']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if end is not None:
        cmd += ['-to', f'{end:.3f}']
    cmd += ['-i', str(path), '-vn', '-ar', str(SR), '-ac', '1', '-f', 'f32le', '-']
    raw = subprocess.check_output(cmd)
    return np.frombuffer(raw, dtype=np.float32).astype(np.float64)


def _mel_filterbank() -> np.ndarray:
    def hz_to_mel(hz: float) -> float:
        return 2595.0 * np.log10(1.0 + hz / 700.0)

    def mel_to_hz(mel: float) -> float:
        return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

    low, high = hz_to_mel(50.0), hz_to_mel(7600.0)
    points = np.linspace(low, high, N_MELS + 2)
    bins = np.floor((N_FFT + 1) * mel_to_hz(points) / SR).astype(int)
    bank = np.zeros((N_MELS, N_FFT // 2 + 1))
    for index in range(1, N_MELS + 1):
        left, centre, right = bins[index - 1], bins[index], bins[index + 1]
        for k in range(left, centre):
            bank[index - 1, k] = (k - left) / max(1, centre - left)
        for k in range(centre, right):
            bank[index - 1, k] = (right - k) / max(1, right - centre)
    return bank


def _dct_matrix() -> np.ndarray:
    n = np.arange(N_MELS)
    k = np.arange(N_CEPS)[:, None]
    matrix = np.cos(np.pi * k * (2 * n + 1) / (2 * N_MELS))
    matrix[0] *= 1.0 / np.sqrt(2.0)
    return matrix * np.sqrt(2.0 / N_MELS)


MEL_BANK = _mel_filterbank()
DCT = _dct_matrix()


def mfcc_stats(audio: np.ndarray) -> np.ndarray | None:
    if audio.size < WIN:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(audio, WIN)[::HOP]
    if frames.shape[0] < 5:
        return None
    spectrum = np.abs(np.fft.rfft(frames * np.hamming(WIN), n=N_FFT)) ** 2
    mel = np.log(spectrum @ MEL_BANK.T + 1e-8)
    ceps = mel @ DCT.T
    ceps = ceps[:, 1:]
    stats = np.concatenate([ceps.mean(axis=0), ceps.std(axis=0)])
    norm = np.linalg.norm(stats)
    return stats / norm if norm else None


_ENCODER = None


def voice_embedding(audio: np.ndarray) -> np.ndarray | None:
    """Resemblyzer d-vector when available, MFCC statistics otherwise."""
    global _ENCODER
    try:
        from resemblyzer import VoiceEncoder, preprocess_wav
        if _ENCODER is None:
            _ENCODER = VoiceEncoder()
        return _ENCODER.embed_utterance(preprocess_wav(audio, source_sr=SR))
    except Exception:
        return mfcc_stats(audio)


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))


def _line_roles(spec: dict) -> dict[str, str]:
    """Map a voice role to its reference path from the spec payload."""
    roles = {}
    for voice in spec.get('voices') or []:
        role = voice.get('role') or voice.get('asset_id')
        if role and voice.get('path'):
            roles[role] = str(voice['path'])
    return roles


def audit_take(spec: dict, take: Path, model) -> dict:
    from .dialogue_audit import align_words, transcribe_words

    lines = spec.get('spoken_lines') or []
    if not lines:
        return {'verdict': 'pass', 'lines': []}
    duration = int(spec['frames']) / 24
    words = transcribe_words(Path(take), model)
    aligned = align_words(lines, words, duration)
    refs = {}
    for role, path in _line_roles(spec).items():
        if Path(path).is_file():
            stats = voice_embedding(_load_audio(Path(path)))
            if stats is not None:
                refs[role] = stats
    results = []
    for line, cue in zip(lines, aligned):
        role = line.get('speaker')
        if not cue or role not in refs:
            results.append({'speaker': role, 'text': line.get('text'), 'verdict': 'unknown'})
            continue
        stats = voice_embedding(_load_audio(Path(take), cue[0], cue[1]))
        if stats is None:
            results.append({'speaker': role, 'text': line.get('text'), 'verdict': 'unknown'})
            continue
        scores = {name: round(_cosine(stats, ref), 3) for name, ref in refs.items()}
        closest = max(scores, key=scores.get)
        results.append({
            'speaker': role,
            'text': line.get('text'),
            'start': round(float(cue[0]), 3),
            'end': round(float(cue[1]), 3),
            'scores': scores,
            'closest': closest,
            'verdict': 'pass' if closest == role else 'review',
        })
    verdict = 'review' if any(item['verdict'] == 'review' for item in results) else 'pass'
    backend = 'resemblyzer' if _ENCODER is not None else 'mfcc'
    return {'verdict': verdict, 'backend': backend, 'lines': results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Audit take voices against their reference WAVs.')
    parser.add_argument('--specs-dir', type=Path, required=True)
    parser.add_argument('--takes-dir', type=Path, required=True)
    parser.add_argument('--shots', default='', help='Comma-separated shot ids')
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args(argv)
    from faster_whisper import WhisperModel
    from .dialogue_audit import WHISPER_MODEL

    model = WhisperModel(str(WHISPER_MODEL), device='cpu', compute_type='int8')
    wanted = {item.strip() for item in args.shots.split(',') if item.strip()}
    report = {}
    for path in sorted(args.specs_dir.glob('*.json')):
        if wanted and path.stem not in wanted:
            continue
        take = args.takes_dir / path.stem / 'native.mp4'
        if not take.is_file():
            continue
        spec = json.loads(path.read_text(encoding='utf-8'))
        report[path.stem] = audit_take(spec, take, model)
        report[path.stem]['path'] = str(take)
    output = args.output or args.takes_dir.parent / 'voice_audit.json'
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    flagged = [sid for sid, item in report.items() if item['verdict'] == 'review']
    print(json.dumps({'audited': len(report), 'review': flagged}, ensure_ascii=False))
    return 1 if flagged else 0


if __name__ == '__main__':
    raise SystemExit(main())
