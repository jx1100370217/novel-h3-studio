#!/usr/bin/env python3
"""Tighten action takes: trim dead time, speed up slow beats, add camera shake.

``artifacts/pacing.json`` maps a shot id to ordered segments, each
``{"in": seconds, "out": seconds, "speed": 1.0, "shake": false}``, read from the
caption-clean take. Segments are joined as hard jump cuts; audio is
time-stretched with the picture so pitch is kept. The result replaces
``public/shots/<id>.mp4``; the raw take in ``assets/shots`` is never touched.
A shot with dialogue may only keep its start and trim its tail, because its
captions are timed from the take start; anything else is refused.

The shot's duration is then written back to ``scene_plan.json`` (and to
``edit_decisions.json`` when the shot has a cut), so later shots, cards and the
music bed follow. Rebuild the edit, the music bed and the compose payload after
running this script. A take that was re-rendered or re-cleaned since the last
run is detected by hash and its clean copy is refreshed first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

FPS = 24
SIZE = '1344:768'


def log(message: str) -> None:
    print(message, flush=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    data = json.loads(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
         '-of', 'json', str(path)], text=True))
    return {'duration': float(data['format']['duration']),
            'audio': any(stream.get('codec_type') == 'audio' for stream in data.get('streams', []))}


def count_frames(path: Path) -> int:
    out = subprocess.check_output(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
         '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', str(path)], text=True)
    return int(out.strip())


def validate_segments(sid: str, segments: list[dict], source_seconds: float,
                      dialogue_end: float | None) -> None:
    if not segments:
        raise SystemExit(f'{sid}: no segments')
    for seg in segments:
        a, b = float(seg['in']), float(seg['out'])
        speed = float(seg.get('speed', 1.0))
        if not (0 <= a < b <= source_seconds + 0.001):
            raise SystemExit(f'{sid}: segment {a}-{b} is outside the {source_seconds:.3f}s take')
        if not (0.5 <= speed <= 2.0):
            raise SystemExit(f'{sid}: speed {speed} is outside 0.5-2.0')
    if dialogue_end is not None:
        only = segments[0]
        if (len(segments) != 1 or float(only['in']) != 0.0 or float(only.get('speed', 1.0)) != 1.0
                or float(only['out']) < dialogue_end + 0.2):
            raise SystemExit(f'{sid}: has dialogue; only a tail trim after {dialogue_end + 0.2:.2f}s is allowed '
                             '(captions are timed from the take start)')


def dialogue_end(shot: dict, asr_shot: dict) -> float | None:
    lines = shot.get('lines') or asr_shot.get('lines') or []
    if not lines:
        return None
    return max(float(line.get('end', line.get('local_end', line.get('start', 0.0)))) for line in lines)


def build_filter(segments: list[dict], has_audio: bool) -> str:
    chains, joins = [], []
    for index, seg in enumerate(segments):
        a, b = float(seg['in']), float(seg['out'])
        speed = float(seg.get('speed', 1.0))
        length = (b - a) / speed
        video = f'[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{speed:.4f}'
        if seg.get('shake'):
            video += (f",crop=iw*0.962:ih*0.962:x='(iw-ow)/2+11*sin(t*31)':"
                      f"y='(ih-oh)/2+8*sin(t*23+1)',scale={SIZE}")
        chains.append(video + f'[v{index}]')
        if has_audio:
            fade = min(0.03, length / 3)
            chains.append(
                f'[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,atempo={speed:.4f},'
                f'afade=t=in:st=0:d={fade:.3f},afade=t=out:st={max(0.0, length - fade):.3f}:d={fade:.3f}'
                f'[a{index}]')
        joins.append(f'[v{index}][a{index}]' if has_audio else f'[v{index}]')
    count = len(segments)
    if has_audio:
        chains.append(''.join(joins) + f'concat=n={count}:v=1:a=1[vc][ac]')
        chains.append(f'[vc]fps={FPS},format=yuv420p[vout]')
        chains.append('[ac]anull[aout]')
    else:
        chains.append(''.join(joins) + f'concat=n={count}:v=1:a=0[vc]')
        chains.append(f'[vc]fps={FPS},format=yuv420p[vout]')
    return ';'.join(chains)


def render(source: Path, target: Path, segments: list[dict], has_audio: bool) -> None:
    command = ['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-filter_complex',
               build_filter(segments, has_audio), '-map', '[vout]']
    if has_audio:
        command += ['-map', '[aout]', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
    command += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p',
                '-movflags', '+faststart', str(target)]
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--shots', default='', help='comma-separated ids; default every id in pacing.json')
    parser.add_argument('--dry-run', action='store_true', help='print the planned durations only')
    args = parser.parse_args()

    project = args.project.resolve()
    recipe = load(project / 'artifacts/pacing.json')
    report_path = project / 'artifacts/pacing_report.json'
    report = load(report_path) if report_path.is_file() else {}
    scene_path = project / 'artifacts/scene_plan.json'
    scene = load(scene_path)
    edit_path = project / 'artifacts/edit_decisions.json'
    edit = load(edit_path) if edit_path.is_file() else {}
    cuts = {cut['id']: cut for cut in edit.get('cuts', [])}
    shots_by_id = {shot['id']: shot for shot in scene['metadata']['shots']}
    asr_path = project / 'artifacts/asr.json'
    asr = load(asr_path) if asr_path.is_file() else {}
    shots_dir = project / 'public/shots'
    clean_dir = project / 'assets/shots_clean'
    clean_dir.mkdir(parents=True, exist_ok=True)

    wanted = [s.strip() for s in args.shots.split(',') if s.strip()] or sorted(recipe)
    durations: dict[str, float] = {}
    for sid in wanted:
        if sid not in recipe:
            raise SystemExit(f'{sid}: missing from artifacts/pacing.json')
        public = shots_dir / f'{sid}.mp4'
        clean = clean_dir / f'{sid}.mp4'
        if not public.is_file():
            raise SystemExit(f'{sid}: missing public take {public}')
        prior = report.get(sid, {})
        if not clean.is_file() or prior.get('output_sha256') != sha256(public):
            if not args.dry_run:
                shutil.copy2(public, clean)
        source = clean if clean.is_file() else public
        info = probe(source)
        segments = recipe[sid]['segments']
        validate_segments(sid, segments, info['duration'],
                          dialogue_end(shots_by_id.get(sid, {}), asr.get(sid, {})))
        planned = sum((float(s['out']) - float(s['in'])) / float(s.get('speed', 1.0)) for s in segments)
        if args.dry_run:
            log(f'PLAN {sid}: source {info["duration"]:.3f}s -> {planned:.3f}s, {len(segments)} segment(s)')
            continue
        temp = shots_dir / f'.{sid}.paced.mp4'
        render(source, temp, segments, info['audio'])
        frames = count_frames(temp)
        temp.replace(public)
        seconds = frames / FPS
        durations[sid] = seconds
        report[sid] = {
            'source': str(clean.relative_to(project)),
            'segments': segments,
            'note': recipe[sid].get('note', ''),
            'output_frames': frames,
            'output_seconds': round(seconds, 4),
            'output_sha256': sha256(public),
        }
        log(f'PACED {sid}: {info["duration"]:.3f}s -> {seconds:.3f}s ({frames} frames, {len(segments)} segment(s))')

    if args.dry_run:
        return 0
    dump(report_path, report)
    if durations:
        for shot in scene['metadata']['shots']:
            if shot['id'] in durations:
                frames = round(durations[shot['id']] * FPS)
                shot['frames'] = frames
                shot['duration_seconds'] = round(frames / FPS, 6)
        cursor = 0.0
        for shot in scene['metadata']['shots']:
            shot['start_seconds'] = round(cursor, 3)
            cursor += float(shot['duration_seconds'])
            shot['end_seconds'] = round(cursor, 3)
        scene['metadata']['target_duration_seconds'] = round(cursor, 3)
        dump(scene_path, scene)
        for sid, seconds in durations.items():
            if sid in cuts:
                cuts[sid]['in_seconds'] = 0.0
                cuts[sid]['out_seconds'] = round(seconds, 3)
        if edit:
            dump(edit_path, edit)
        log(f'scene plan updated: total {scene["metadata"]["target_duration_seconds"]:.3f}s; '
            'rebuild the edit, the music bed and the compose payload next')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
