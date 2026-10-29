"""Dialogue alignment audit: where each authored line actually lands.

H3 places native speech where it wants, not at the nominal offset the Ref2VA
builder wrote. This module transcribes a take with timestamps, matches each
authored line to the segment that actually says it, and records the real
onset/end. The compose stage uses those times for subtitles, and the voice
audit uses the same segments to check which reference timbre was used.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

CJK = re.compile(r'[\u3400-\u9fff]')
LINE_RE = re.compile(r'^([\u4e00-\u9fff]{1,6})(?:（[^）]*）)?：(.+)$')
WHISPER_MODEL = Path(
    '/home/jx/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/'
    'snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
)


def authored_lines(shot: dict) -> list[dict]:
    lines = []
    for raw in (shot.get('dialogue') or '').splitlines():
        match = LINE_RE.match(raw.strip())
        if match:
            lines.append({'speaker': match.group(1), 'text': match.group(2).strip()})
    return lines


def normalise(text: str) -> str:
    return ''.join(CJK.findall(text))


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def transcribe(path: Path, model) -> list[dict]:
    import numpy as np

    raw = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    segments, _info = model.transcribe(audio, language='zh', vad_filter=True)
    return [{'start': round(seg.start, 3), 'end': round(seg.end, 3), 'text': seg.text.strip()}
            for seg in segments]


def match_segments(lines: list[dict], segments: list[dict]) -> list[dict]:
    """Attach the best-matching transcript segment to each authored line."""
    used: set[int] = set()
    out = []
    for line in lines:
        target = normalise(line['text'])
        best = (-1.0, None)
        for index, segment in enumerate(segments):
            if index in used:
                continue
            score = similarity(target, normalise(segment['text']))
            if score > best[0]:
                best = (score, index)
        score, index = best
        if index is None or score < 0.3:
            out.append({**line, 'start': None, 'end': None, 'similarity': round(score, 3), 'heard': None})
            continue
        used.add(index)
        segment = segments[index]
        out.append({**line, 'start': segment['start'], 'end': segment['end'],
                    'similarity': round(score, 3), 'heard': segment['text']})
    return out


def segment_f0(path: Path, start: float, end: float) -> float | None:
    import numpy as np
    import torch
    import torchaudio

    raw = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-to', f'{end:.3f}', '-i', str(path),
         '-vn', '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    if audio.size < 1600:
        return None
    wave = torch.from_numpy(audio).unsqueeze(0)
    freq = torchaudio.functional.detect_pitch_frequency(wave, 16000, win_length=10, freq_low=60, freq_high=600)
    voiced = freq[freq > 0].numpy()
    return float(np.median(voiced)) if voiced.size else None


def audit(project: Path, *, takes_subdir: str = 'takes_all') -> dict:
    project = Path(project)
    scene_plan = json.loads((project / 'artifacts/scene_plan.json').read_text(encoding='utf-8'))
    from faster_whisper import WhisperModel
    model = WhisperModel(str(WHISPER_MODEL), device='cpu', compute_type='int8')
    base = project / takes_subdir
    report = {}
    for scene in scene_plan['scenes']:
        sid = scene['id']
        video = base / sid / 'native.mp4'
        shot_path = project / 'shots' / f'{sid}.json'
        if not video.is_file() or not shot_path.is_file():
            continue
        shot = json.loads(shot_path.read_text(encoding='utf-8'))
        lines = authored_lines(shot)
        if not lines:
            continue
        segments = transcribe(video, model)
        matched = match_segments(lines, segments)
        for line in matched:
            if line['start'] is not None:
                line['f0_hz'] = round(segment_f0(video, line['start'], line['end']) or 0.0, 1) or None
        report[sid] = {'video': str(video), 'segments': segments, 'lines': matched}
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Align authored dialogue to the rendered take.')
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    report = audit(project)
    out = project / 'artifacts/dialogue_timing.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    weak = [sid for sid, item in report.items()
            if any(line['start'] is None or line['similarity'] < 0.45 for line in item['lines'])]
    print(json.dumps({'shots': len(report), 'weak_match': weak, 'output': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
