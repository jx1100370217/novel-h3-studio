"""Per-chapter exports for review and publishing.

A chapter is one screenplay scene: all of its shots composed with the same
picture/audio rules as the full film (native dialogue, music bed, burned
subtitles), written as a stand-alone MP4. The compilation is the full cut.
"""
from __future__ import annotations

import json
from pathlib import Path

from .compose_cut import compose
from .dialogue_audit import authored_lines, match_segments, normalise, similarity, transcribe
from .subtitles import shot_cues
from .subtitle_audit import scan_take


def _align_scene(project: Path, ids: list[str], takes_dir: Path, out: Path) -> dict:
    """ASR-align each shot's authored lines to the native speech."""
    from faster_whisper import WhisperModel
    from .dialogue_audit import WHISPER_MODEL

    model = WhisperModel(str(WHISPER_MODEL), device='cpu', compute_type='int8')
    timing = {}
    for sid in ids:
        shot = json.loads((project / 'shots_v3' / f'{sid}.json').read_text(encoding='utf-8'))
        lines = authored_lines(shot)
        video = takes_dir / sid / 'native.mp4'
        if not lines or not video.is_file():
            continue
        matched = match_segments(lines, transcribe(video, model))
        nominal = shot_cues(shot)
        cues = []
        texts = [line['text'] for line in lines]
        for index, cue in enumerate(nominal):
            line = matched[index] if index < len(matched) else None
            if line and line.get('start') is not None and line.get('similarity', 0) >= 0.45:
                start = max(0.0, line['start'] - 0.05)
                end = min(shot['frames'] / 24 - 0.1, line['end'] + 0.25)
                if end - start >= 0.6:
                    cues.append([round(start, 3), round(end, 3)])
                    continue
            cues.append([cue['start'], cue['end']])
        # Subtitles are a reading task: cap each cue and keep them ordered
        # and non-overlapping even when ASR returns a long merged segment.
        cues.sort(key=lambda cue: cue[0])
        for index, cue in enumerate(cues):
            read_time = min(4.5, max(1.6, 1.2 + 0.25 * len(texts[index])))
            cue[1] = min(cue[1], cue[0] + read_time)
            if index + 1 < len(cues):
                cue[1] = min(cue[1], cues[index + 1][0] - 0.15)
            if cue[1] < cue[0] + 1.2:
                # Keep a subtitle readable even when ASR clips the segment.
                limit = cues[index + 1][0] - 0.1 if index + 1 < len(cues) else cue[0] + 1.2
                cue[1] = max(cue[0] + 0.6, min(cue[0] + 1.2, limit))
        timing[sid] = cues
    out.write_text(json.dumps(timing, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return timing


def compose_chapter(project: Path, scene_id: str, *, takes_subdir: str = 'takes_v3',
                    shots_subdir: str = 'shots_v3', output_dir: str = 'exports/chapters',
                    music: str | None = 'assets/music/bed.wav', align: bool = True) -> dict:
    project = Path(project).resolve()
    plan = json.loads((project / 'v3/scene_plan.json').read_text(encoding='utf-8'))
    scene = next(item for item in plan['scenes'] if item['id'] == scene_id)
    ids = list(scene['shots'])
    shots = {sid: json.loads((project / shots_subdir / f'{sid}.json').read_text(encoding='utf-8')) for sid in ids}
    duration = sum(int(shot['frames']) for shot in shots.values()) / 24
    takes_dir = project / takes_subdir
    work = project / 'v3/chapters' / scene_id
    work.mkdir(parents=True, exist_ok=True)
    timing_path = work / 'timing.json'
    if align:
        try:
            timing = _align_scene(project, ids, takes_dir, timing_path)
        except Exception as exc:  # whisper is optional in the compose venv
            print(f'TIMING ALIGN SKIPPED: {exc}', flush=True)
            timing = {}
    else:
        timing = json.loads(timing_path.read_text(encoding='utf-8')) if timing_path.is_file() else {}
    script_path = work / 'script.json'
    script_path.write_text(json.dumps({'sections': [{'id': scene_id, 'shots': ids}]}, ensure_ascii=False), encoding='utf-8')
    lines_path = work / 'lines.json'
    if not lines_path.is_file():
        lines_path.write_text(json.dumps({'lines': []}, ensure_ascii=False), encoding='utf-8')
    skip = []
    for sid in ids:
        take = takes_dir / sid / 'native.mp4'
        if take.is_file():
            try:
                scan = scan_take(take, duration=int(shots[sid]['frames']) / 24, samples=12)
                if scan['verdict'] == 'text':
                    skip.append(sid)
            except Exception:
                pass
    out = project / output_dir / f"{scene_id}_{scene.get('title', '').replace(' ', '')}.mp4"
    spec = {
        'version': '1.0', 'tag': f'chapter_{scene_id}',
        'script': str(script_path), 'shots_dir': str(project / shots_subdir),
        'takes_dir': str(takes_dir), 'graphics': {}, 'lines': str(lines_path),
        'music': str(project / music) if music else '',
        'work_dir': str(work / 'work'), 'audio_dir': str(work / 'audio'),
        'output': str(out), 'width': 1344, 'height': 768, 'fps': 24,
        'target_duration': round(duration, 6), 'music_volume': 0.55,
        'ducking': {'enabled': True, 'music_volume_during_speech': 0.22,
                    'attack_ms': 250, 'release_ms': 700},
        'subtitles': {'style': {}, 'timing': str(timing_path) if timing else '',
                      'skip_shots': skip},
    }
    spec_path = work / 'compose.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return compose(spec_path)
