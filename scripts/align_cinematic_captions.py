#!/usr/bin/env python3
"""Re-align a cinematic project's Remotion captions to newly rendered takes.

The project's approved caption text/chunking lives in ``public/props.json``.
When a take is re-rendered its dialogue timing can move by a few hundred
milliseconds even with the same prompt and seed. This script transcribes the new
take, matches each old ASR line to the new speech, and shifts each approved
caption proportionally inside its line window. It does not rewrite the authored
text or re-chunk captions.
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import subprocess
from faster_whisper import WhisperModel

WHISPER_MODEL = Path(
    '/home/jx/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/'
    'snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
)
CJK = re.compile(r'[\u3400-\u9fff]')


def normalise(text: str) -> str:
    return ''.join(CJK.findall(text or ''))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def transcribe(video: Path, model: WhisperModel) -> list[dict]:
    raw = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-i', str(video), '-vn', '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    segments, _ = model.transcribe(audio, language='zh', vad_filter=True)
    return [{'start': float(s.start), 'end': float(s.end), 'text': s.text.strip()} for s in segments]


def match_lines(lines: list[dict], segments: list[dict]) -> list[dict]:
    used: set[int] = set()
    out = []
    for line in lines:
        target = normalise(line.get('text', ''))
        best = (-1.0, None)
        for index, segment in enumerate(segments):
            if index in used:
                continue
            score = SequenceMatcher(None, target, normalise(segment['text'])).ratio()
            if score > best[0]:
                best = (score, index)
        score, index = best
        if index is None or score < 0.30:
            out.append({**line, 'new_start': line.get('local_start'), 'new_end': line.get('local_end'),
                        'match': round(score, 3)})
            continue
        used.add(index)
        out.append({**line, 'new_start': segments[index]['start'], 'new_end': segments[index]['end'],
                    'match': round(score, 3), 'heard': segments[index]['text']})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--takes', type=Path, default=None)
    args = parser.parse_args()
    project = args.project.resolve()
    takes = (args.takes or (project / 'assets/shots')).resolve()
    asr = load(project / 'artifacts/asr.json')
    props_path = project / 'public/props.json'
    props = load(props_path)
    timing_path = project / 'artifacts/edit_timing.json'
    timing = load(timing_path) if timing_path.is_file() else {}
    model = WhisperModel(str(WHISPER_MODEL), device='cpu', compute_type='int8')
    new_windows: dict[str, dict[str, dict]] = {}
    for sid, record in sorted(asr.items()):
        video = takes / f'{sid}.mp4'
        if not video.is_file():
            continue
        segments = transcribe(video, model)
        matched = match_lines(record.get('lines') or [], segments)
        new_windows[sid] = {str(line.get('text')): line for line in matched}
        print(sid, [(line.get('text'), line.get('new_start'), line.get('new_end'), line.get('match'))
                    for line in matched], flush=True)

    captions = props.get('captions') or []
    changed = 0
    for caption in captions:
        start = float(caption.get('start', 0))
        # Find the old ASR line whose global window contains this caption.
        owner = None
        for sid, record in asr.items():
            for line in record.get('lines') or []:
                if float(line.get('global_start', -1)) - 0.05 <= start <= float(line.get('global_end', -1)) + 0.05:
                    owner = (sid, line)
                    break
            if owner:
                break
        if not owner:
            continue
        sid, old_line = owner
        new_line = new_windows.get(sid, {}).get(str(old_line.get('text')))
        if not new_line or new_line.get('new_start') is None:
            continue
        old_start = float(old_line.get('global_start', 0))
        old_end = float(old_line.get('global_end', 0))
        shot = next((s for s in props.get('shots', []) if s.get('id') == sid), None)
        if shot is None:
            continue
        shot_start = float(shot['startFrame']) / float(props.get('fps', 24))
        new_start = shot_start + float(new_line['new_start'])
        new_end = shot_start + float(new_line['new_end'])
        old_dur = max(0.05, old_end - old_start)
        new_dur = max(0.05, new_end - new_start)
        rel0 = (float(caption['start']) - old_start) / old_dur
        rel1 = (float(caption['end']) - old_start) / old_dur
        caption['start'] = round(new_start + rel0 * new_dur, 3)
        caption['end'] = round(new_start + rel1 * new_dur, 3)
        caption['startFrame'] = round(caption['start'] * float(props.get('fps', 24)))
        caption['endFrame'] = round(caption['end'] * float(props.get('fps', 24)))
        changed += 1
    props['captions'] = captions
    dump(props_path, props)
    if timing:
        timing['captions'] = captions
        dump(timing_path, timing)
    # Delivery SRT from the same captions.
    def srt_time(seconds: float) -> str:
        ms = int(round(max(0.0, seconds) * 1000))
        h, rest = divmod(ms, 3600000)
        m, rest = divmod(rest, 60000)
        s, ms = divmod(rest, 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    srt = []
    for index, caption in enumerate(captions, 1):
        srt.append(f'{index}\n{srt_time(caption["start"])} --> {srt_time(caption["end"])}\n{caption["text"]}\n')
    (project / 'assets/subtitles.srt').write_text('\n'.join(srt), encoding='utf-8')
    print(json.dumps({'captions': len(captions), 'shifted': changed}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
