"""Per-chapter exports for review and publishing.

A chapter is one screenplay scene: all of its shots composed with the same
picture/audio rules as the full film (native dialogue, music bed, burned
subtitles), written as a stand-alone MP4. The compilation is the full cut.
"""
from __future__ import annotations

import json
from pathlib import Path

from .compose_cut import compose
from .dialogue_audit import align_words, authored_lines, normalise, similarity, transcribe_words
from .subtitles import shot_cues
from .subtitle_audit import scan_take
from .visual_qc import audit_take as audit_visual


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
        duration = shot['frames'] / 24
        aligned = align_words(lines, transcribe_words(video, model), duration)
        nominal = shot_cues(shot)
        cues = []
        for index, cue in enumerate(nominal):
            found = aligned[index] if index < len(aligned) else None
            cues.append(list(found) if found else [cue['start'], cue['end']])
        # Keep cues ordered and non-overlapping; never cap a cue before the
        # speech ends, or the subtitle vanishes while the actor is still talking.
        cues.sort(key=lambda cue: cue[0])
        for index, cue in enumerate(cues):
            limit = cues[index + 1][0] - 0.1 if index + 1 < len(cues) else duration - 0.1
            cue[1] = max(cue[0] + 0.6, min(cue[1], limit))
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
    skip_lines: dict[str, list[int]] = {}
    for sid in ids:
        take = takes_dir / sid / 'native.mp4'
        if take.is_file():
            try:
                scan = scan_take(take, duration=int(shots[sid]['frames']) / 24, samples=96)
                if scan['verdict'] == 'text':
                    lines = authored_lines(shots[sid])
                    native = ''.join(normalise(hit['text']) for hit in scan['hits'])
                    covered = []
                    for index, line in enumerate(lines):
                        target = normalise(line['text'])
                        if not target:
                            continue
                        best = max((similarity(target, normalise(hit['text']))
                                    for hit in scan['hits']), default=0.0)
                        partial = any(len(normalise(hit['text'])) >= 2
                                      and normalise(hit['text']) in target
                                      for hit in scan['hits'])
                        if target in native or partial or best >= 0.5:
                            covered.append(index)
                    if lines and len(covered) >= len(lines):
                        skip.append(sid)
                    elif covered:
                        skip_lines[sid] = covered
            except Exception:
                pass
    override_path = work / 'skip_override.json'
    if override_path.is_file():
        override = json.loads(override_path.read_text(encoding='utf-8'))
        forced = [str(sid) for sid in override.get('skip_shots', [])]
        skip = sorted(set(skip) | set(forced))
        for sid in forced:
            skip_lines.pop(sid, None)
        for sid, indices in (override.get('skip_lines') or {}).items():
            skip_lines[str(sid)] = [int(index) for index in indices]
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
                      'skip_shots': skip, 'skip_lines': skip_lines},
    }
    spec_path = work / 'compose.json'
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    result = compose(spec_path)
    visual = {sid: audit_visual(takes_dir / sid / 'native.mp4') for sid in ids}
    visual_verdict = 'review' if any(item['verdict'] == 'review' for item in visual.values()) else 'pass'
    (work / 'visual_qc.json').write_text(
        json.dumps({'verdict': visual_verdict, 'takes': visual}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print('VISUAL QC', visual_verdict,
          [sid for sid, item in visual.items() if item['verdict'] == 'review'], flush=True)
    from .subtitle_qc import scan_duplicate_captions
    qc = scan_duplicate_captions(Path(result['output']), duration=float(result['duration']))
    (work / 'subtitle_qc.json').write_text(
        json.dumps(qc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('SUBTITLE QC', qc['verdict'],
          f"{len(qc['hits'])} duplicate frames" if qc['hits'] else '', flush=True)
    result['subtitle_qc'] = qc
    result['visual_qc'] = visual_verdict
    return result
