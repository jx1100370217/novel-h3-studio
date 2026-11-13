#!/usr/bin/env python3
"""Align each scripted dialogue line to the regenerated take's native audio.

FastH3 dialogue timing moves when a take is re-rendered even with the same
prompt and seed. This transcribes every dialogue take with Whisper, then finds
the best grouping of ASR segments for the shot's scripted lines. The resulting
``artifacts/asr.json`` holds line-level global timings; the edit builder turns
those lines into captions.
"""
from __future__ import annotations

import argparse
import itertools
import json
import re
import subprocess
import tempfile
import wave
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

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


def normalise(text: str) -> str:
    return CJK.sub('', text or '')


def transcribe(path: Path, model: WhisperModel) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix='cine_align_') as tmp:
        wav = Path(tmp) / 'audio.wav'
        subprocess.run(
            ['ffmpeg', '-v', 'error', '-y', '-i', str(path),
             '-ac', '1', '-ar', '16000', str(wav)], check=True)
        with wave.open(str(wav), 'rb') as handle:
            raw = handle.readframes(handle.getnframes())
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, language='zh', vad_filter=True,
                                   word_timestamps=True)
    output = []
    for segment in segments:
        words = [{'text': word.word, 'start': float(word.start), 'end': float(word.end)}
                 for word in (segment.words or [])]
        output.append({'text': segment.text,
                       'start': float(segment.start), 'end': float(segment.end),
                       'words': words})
    return output


def segment_span(segment: dict) -> tuple[float, float]:
    words = segment.get('words') or []
    if words:
        return words[0]['start'], words[-1]['end']
    return segment['start'], segment['end']


def align(lines: list[str], segments: list[dict]) -> list[dict] | None:
    if not segments:
        return None
    count = len(lines)
    available = len(segments)
    if available < count:
        total_chars = sum(len(line) for line in lines) or 1
        start = segment_span(segments[0])[0]
        end = segment_span(segments[-1])[1]
        spans, cursor = [], start
        for line in lines:
            duration = (end - start) * len(line) / total_chars
            spans.append({'start': cursor, 'end': cursor + duration, 'words': []})
            cursor += duration
        return spans
    best: list[dict] | None = None
    best_score = -1.0
    for cuts in itertools.combinations(range(1, available), count - 1):
        bounds = (0,) + cuts + (available,)
        groups = [segments[bounds[i]:bounds[i + 1]] for i in range(count)]
        score = sum(
            SequenceMatcher(None, normalise(line),
                            normalise(''.join(segment['text'] for segment in group))).ratio()
            for line, group in zip(lines, groups)
        )
        if score > best_score:
            best_score = score
            best = []
            for group in groups:
                words = [word for segment in group for word in (segment.get('words') or [])]
                best.append({'start': segment_span(group[0])[0],
                             'end': segment_span(group[-1])[1],
                             'words': words})
    return best


def shot_seconds(shot: dict) -> float:
    """Duration in seconds, tolerating older scene plans without the field."""
    if shot.get('duration_seconds') is not None:
        return float(shot['duration_seconds'])
    if shot.get('frames') is not None:
        return float(shot['frames']) / 24.0
    return float(shot['end_seconds']) - float(shot['start_seconds'])


def shot_durations(scene_plan: dict, edit_decisions: dict | None) -> dict[str, float]:
    durations = {shot['id']: shot_seconds(shot)
                 for shot in scene_plan['metadata']['shots']}
    cuts = (edit_decisions or {}).get('cuts') or []
    for cut in cuts:
        out_seconds = cut.get('out_seconds')
        if out_seconds is None:
            continue
        durations[cut['id']] = float(out_seconds) - float(cut.get('in_seconds') or 0.0)
    return durations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()

    project = args.project.resolve()
    scene_plan = load(project / 'artifacts/scene_plan.json')
    takes = load(project / 'assets/take_manifest.json')
    edit_path = project / 'artifacts/edit_decisions.json'
    edit_decisions = load(edit_path) if edit_path.is_file() else None
    durations = shot_durations(scene_plan, edit_decisions)
    model = WhisperModel(str(args.model) if args.model.is_dir() else 'large-v3-turbo',
                         device='cpu', compute_type='int8')

    aligned: dict[str, dict] = {}
    start = 0.0
    for shot in scene_plan['metadata']['shots']:
        sid = shot['id']
        duration = durations[sid]
        take = takes.get(sid) or {}
        video = Path(take.get('path') or project / 'assets/shots' / f'{sid}.mp4')
        if shot.get('lines') and take.get('status') == 'ok' and video.is_file():
            segments = transcribe(video, model)
            spans = align([line['text'] for line in shot['lines']], segments)
            lines = []
            for line, span in zip(shot['lines'], spans or []):
                lines.append({
                    'speaker': line['speaker'],
                    'text': line['text'],
                    'local_start': round(span['start'], 3),
                    'local_end': round(span['end'], 3),
                    'global_start': round(start + span['start'], 3),
                    'global_end': round(start + span['end'], 3),
                    'words': [{'text': word['text'],
                               'local_start': round(word['start'], 3),
                               'local_end': round(word['end'], 3)}
                              for word in span.get('words', [])],
                })
            aligned[sid] = {'segments': segments, 'lines': lines}
            log(f'{sid} {[(line["global_start"], line["global_end"]) for line in lines]}')
        start += duration

    dump(project / 'artifacts/asr.json', aligned)
    log(f'DONE dialogue_shots={len(aligned)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
