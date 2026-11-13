#!/usr/bin/env python3
"""Build the cinematic edit timeline, per-shot gains, and captions.

The edit is derived from project data only: ``scene_plan.json`` for the shot
list and dialogue, ``asset_qc.json`` for measured loudness, ``asr.json`` for
line-level dialogue timing, and ``edit_decisions.json`` for trims/transitions.
It writes ``public/props.json`` (Remotion) and ``artifacts/edit_timing.json``.
It never rewrites ``public/shots``; the render and caption-crop steps own those
files.
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

FPS = 24


def log(message: str) -> None:
    print(message, flush=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def split_caption(caption: dict, words: list[dict] | None = None,
                  limit: int = 28) -> list[dict]:
    text = caption['text']
    if len(text) <= limit:
        return [caption]
    parts = re.split(r'(?<=[，。；？！])', text)
    chunks: list[str] = []
    buffer = ''
    for part in parts:
        if buffer and len(buffer) + len(part) > limit:
            chunks.append(buffer)
            buffer = part
        else:
            buffer += part
    if buffer:
        chunks.append(buffer)
    proportional = []
    total_chars = sum(len(chunk) for chunk in chunks) or 1
    duration = caption['end'] - caption['start']
    cursor = caption['start']
    for chunk in chunks:
        span = duration * len(chunk) / total_chars
        proportional.append({'text': chunk, 'start': round(cursor, 3),
                             'end': round(cursor + span, 3)})
        cursor += span

    if not words:
        return proportional
    line_norm = ''.join(re.findall(r'[\u4e00-\u9fff]', text))
    char_word: list[int] = []
    heard = ''
    for index, word in enumerate(words):
        clean = ''.join(re.findall(r'[\u4e00-\u9fff]', word.get('text', '')))
        heard += clean
        char_word.extend([index] * len(clean))
    if not line_norm or not heard:
        return proportional

    # Whisper may hear a homophone (e.g. 河/合). Map script characters onto
    # the heard characters so the word timings still apply when the text is
    # not an exact match.
    mapping = [-1] * len(line_norm)
    matcher = SequenceMatcher(None, line_norm, heard, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for offset in range(i2 - i1):
                mapping[i1 + offset] = j1 + offset
        elif tag == 'replace':
            heard_span = j2 - j1
            script_span = i2 - i1
            for offset in range(script_span):
                if heard_span:
                    mapping[i1 + offset] = j1 + min(heard_span - 1,
                                                    int(offset * heard_span / script_span))
                else:
                    mapping[i1 + offset] = min(j1, len(heard) - 1)
        elif tag == 'delete':
            for offset in range(i1, i2):
                mapping[offset] = min(j1, len(heard) - 1)

    output = []
    search_from = 0
    for chunk, fallback in zip(chunks, proportional):
        clean = ''.join(re.findall(r'[\u4e00-\u9fff]', chunk))
        start_char = line_norm.find(clean, search_from)
        end_char = start_char + len(clean) - 1
        if start_char < 0 or end_char >= len(mapping):
            output.append(fallback)
            continue
        heard_indices = [index for index in mapping[start_char:end_char + 1] if index >= 0]
        if not heard_indices:
            output.append(fallback)
            continue
        first = char_word[min(heard_indices)]
        last = char_word[max(heard_indices)]
        output.append({'text': chunk,
                       'start': round(float(words[first]['start']), 3),
                       'end': round(float(words[last]['end']), 3)})
        search_from = end_char + 1
    return output


def shot_gain(lufs: float | None, has_dialogue: bool) -> float:
    if lufs is None:
        return 1.0
    target = -20.0 if has_dialogue else -33.0
    cap = 2.0 if has_dialogue else 8.0
    return round(min(cap, max(1.0, 10 ** ((target - lufs) / 20))), 3)


def shot_seconds(shot: dict) -> float:
    """Duration in seconds, tolerating older scene plans without the field."""
    if shot.get('duration_seconds') is not None:
        return float(shot['duration_seconds'])
    if shot.get('frames') is not None:
        return float(shot['frames']) / FPS
    return float(shot['end_seconds']) - float(shot['start_seconds'])


def srt_time(seconds: float) -> str:
    milliseconds = int(round(max(0.0, seconds) * 1000))
    hours, rest = divmod(milliseconds, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    whole, milliseconds = divmod(rest, 1000)
    return f'{hours:02d}:{minutes:02d}:{whole:02d},{milliseconds:03d}'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()

    scene_plan = load(project / 'artifacts/scene_plan.json')
    takes = load(project / 'assets/take_manifest.json')
    qc = load(project / 'artifacts/asset_qc.json')
    asr = load(project / 'artifacts/asr.json')
    edit_decisions = load(project / 'artifacts/edit_decisions.json')
    existing_path = project / 'public/props.json'
    existing = load(existing_path) if existing_path.is_file() else {}

    qc_by_shot = {row['shot']: row for row in qc.get('shots', [])}
    cuts = {cut['id']: cut for cut in edit_decisions.get('cuts', [])}
    grades = {shot['id']: shot.get('grade', 'neutral')
              for shot in existing.get('shots', [])}
    existing_by_id = {shot['id']: shot for shot in existing.get('shots', [])}

    shots = []
    cursor = 0.0
    for spec in scene_plan['metadata']['shots']:
        sid = spec['id']
        take = takes.get(sid) or {}
        video = Path(take.get('path') or project / 'assets/shots' / f'{sid}.mp4')
        if not video.is_file():
            raise SystemExit(f'missing take: {sid}')
        cut = cuts.get(sid) or {}
        duration = float(cut.get('out_seconds') or shot_seconds(spec))
        duration -= float(cut.get('in_seconds') or 0.0)
        frames = int(round(duration * FPS))
        fade_in = int(round(float(cut.get('transition_duration') or 0) * FPS)) \
            if cut.get('transition_in') == 'fade' else 0
        fade_out = int(round(float(cut.get('transition_duration') or 0) * FPS)) \
            if cut.get('transition_out') == 'fade' else 0
        previous = existing_by_id.get(sid) or {}
        fade_in = int(previous.get('fadeInFrames', fade_in))
        fade_out = int(previous.get('fadeOutFrames', fade_out))
        shots.append({
            'id': sid,
            'src': f'shots/{sid}.mp4',
            'startFrame': int(round(cursor * FPS)),
            'durationInFrames': frames,
            'duration': round(duration, 3),
            'grade': grades.get(sid, 'neutral'),
            'gain': shot_gain((qc_by_shot.get(sid) or {}).get('lufs'), bool(spec.get('lines'))),
            'fadeInFrames': fade_in,
            'fadeOutFrames': fade_out,
            'start': round(cursor, 3),
        })
        cursor += duration
    total = cursor

    captions = []
    for shot, spec in zip(shots, scene_plan['metadata']['shots']):
        sid = shot['id']
        if sid in asr:
            for line in asr[sid].get('lines', []):
                start = float(line['global_start'])
                end = min(float(line['global_end']), shot['start'] + shot['duration'] - 0.15)
                if end > start:
                    words = [{'text': word['text'],
                              'start': shot['start'] + float(word['local_start']),
                              'end': shot['start'] + float(word['local_end'])}
                             for word in line.get('words', [])]
                    captions.append({'text': line['text'], 'start': round(start, 3),
                                     'end': round(end, 3), 'words': words})
            continue
        for line in spec.get('lines') or []:
            start = shot['start'] + float(line['start'])
            end = shot['start'] + min(float(line['end']), shot['duration'] - 0.15)
            if end > start:
                captions.append({'text': line['text'], 'start': round(start, 3),
                                 'end': round(end, 3)})

    captions = [part for caption in captions
                for part in split_caption(caption, caption.pop('words', None))]
    for caption in captions:
        caption.pop('words', None)
        caption['startFrame'] = int(round(caption['start'] * FPS))
        caption['endFrame'] = int(round(caption['end'] * FPS))

    title_cards = []
    for card in existing.get('titleCards', []):
        updated = dict(card)
        updated['startFrame'] = int(round(float(card['start']) * FPS))
        updated['durationInFrames'] = int(round(float(card['duration']) * FPS))
        title_cards.append(updated)

    props = {
        'fps': FPS,
        'width': 1344,
        'height': 768,
        'totalFrames': int(round(total * FPS)),
        'shots': [{key: value for key, value in shot.items()
                   if key not in ('duration', 'start')} for shot in shots],
        'titleCards': title_cards,
        'captions': captions,
        'showCaptions': True,
    }
    dump(project / 'public/props.json', props)
    dump(project / 'artifacts/edit_timing.json',
         {'total_seconds': round(total, 3), 'shots': shots, 'captions': captions})
    srt = []
    for index, caption in enumerate(captions, 1):
        srt.append(f'{index}\n{srt_time(caption["start"])} --> '
                   f'{srt_time(caption["end"])}\n{caption["text"]}\n')
    (project / 'assets/subtitles.srt').write_text('\n'.join(srt), encoding='utf-8')
    gains = {shot['id']: shot['gain'] for shot in shots if shot['gain'] != 1.0}
    log(f'total={total:.3f}s shots={len(shots)} captions={len(captions)}')
    log(f'gains={gains}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
