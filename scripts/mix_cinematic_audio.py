#!/usr/bin/env python3
"""Mix the cinematic picture's native H3 audio with the project music bed.

Pipeline:
1. Extract the picture's native audio.
2. Apply the per-shot gain values from ``public/props.json``.
3. Mix speech + music through the OpenMontage ``audio_mixer`` full_mix
   operation with sidechain ducking and -16 LUFS normalisation.
4. Remux the mixed audio onto the untouched picture with a peak limiter.

This is the step that adds the authored background music; Remotion renders
picture plus native audio only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'openmontage'))

from tools.tool_registry import registry  # noqa: E402


def log(message: str) -> None:
    print(message, flush=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def probe_duration(path: Path) -> float:
    return float(subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'default=nw=1:nk=1', str(path)], text=True).strip())


def loudness(path: Path) -> tuple[float | None, float | None]:
    stderr = subprocess.run(
        ['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'ebur128=peak=true',
         '-f', 'null', '-'], capture_output=True, text=True).stderr
    integrated = re.findall(r'I:\s+(-?[\d.]+) LUFS', stderr)
    peak = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', stderr)
    return (float(integrated[-1]) if integrated else None,
            float(peak[-1]) if peak else None)


def gain_expression(shots: list[dict], fps: float) -> str:
    expression = f"{float(shots[-1]['gain'])}"
    for shot in reversed(shots[:-1]):
        start = float(shot['startFrame']) / fps
        end = (float(shot['startFrame']) + float(shot['durationInFrames'])) / fps
        expression = f"if(between(t,{start:.3f},{end:.3f}),{float(shot['gain'])},{expression})"
    return expression


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--picture', type=Path, default=None)
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--music', type=Path, default=None)
    parser.add_argument('--target-lufs', type=float, default=None)
    parser.add_argument('--music-volume', type=float, default=None)
    parser.add_argument('--duck-volume', type=float, default=None)
    parser.add_argument('--attack-ms', type=float, default=None)
    parser.add_argument('--release-ms', type=float, default=None)
    args = parser.parse_args()

    project = args.project.resolve()
    props = load(project / 'public/props.json')
    edit_path = project / 'artifacts/edit_decisions.json'
    edit_decisions = load(edit_path) if edit_path.is_file() else {}
    music_config = ((edit_decisions.get('audio') or {}).get('music') or {})
    duck_config = music_config.get('ducking') or {}
    music_volume = (args.music_volume if args.music_volume is not None
                    else float(music_config.get('volume', 0.55)))
    duck_volume = (args.duck_volume if args.duck_volume is not None
                   else float(duck_config.get('music_volume_during_speech', 0.22)))
    attack_ms = (args.attack_ms if args.attack_ms is not None
                 else float(duck_config.get('attack_ms', 250)))
    release_ms = (args.release_ms if args.release_ms is not None
                  else float(duck_config.get('release_ms', 700)))
    target_lufs = (args.target_lufs if args.target_lufs is not None
                   else float((edit_decisions.get('metadata') or {}).get('loudnorm_target', -16)))
    picture = (args.picture or project / 'renders/wangliulang_picture.mp4').resolve()
    music = (args.music or project / 'assets/music/music_bed.wav').resolve()
    output = (args.output or project / 'renders/wangliulang_final.mp4').resolve()
    if not picture.is_file():
        raise SystemExit(f'missing picture render: {picture}')
    if not music.is_file():
        raise SystemExit(f'missing music bed: {music}')

    renders = project / 'renders'
    native = renders / 'native.wav'
    gained = renders / 'native_gained.wav'
    mix_path = renders / 'final_mix.wav'
    fps = float(props.get('fps', 24))
    expression = gain_expression(props['shots'], fps)
    log(f'gain expression: {len(expression)} chars')

    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(picture), '-vn',
         '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(native)], check=True)
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(native), '-af',
         f"volume='{expression}':eval=frame", '-ac', '2', '-ar', '48000',
         '-c:a', 'pcm_s16le', str(gained)], check=True)

    registry.discover()
    mixer = registry.get('audio_mixer')
    if mixer is None:
        raise SystemExit('audio_mixer tool is not registered')
    result = mixer.execute({
        'operation': 'full_mix',
        'tracks': [
            {'path': str(gained), 'role': 'primary'},
            {'path': str(music), 'role': 'music', 'volume': music_volume},
        ],
        'ducking': {
            'enabled': True,
            'music_volume_during_speech': duck_volume,
            'attack_ms': attack_ms,
            'release_ms': release_ms,
        },
        'normalize': True,
        'loudnorm_target': target_lufs,
        'output_path': str(mix_path),
    })
    if not result.success:
        raise SystemExit(f'audio_mixer failed: {result.error}')
    log(f'mixed: {mix_path} ({probe_duration(mix_path):.3f}s)')

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(picture), '-i', str(mix_path),
         '-map', '0:v', '-map', '1:a', '-c:v', 'copy',
         '-af', 'alimiter=limit=0.70:level=false',
         '-c:a', 'aac', '-b:a', '192k', '-shortest', str(output)], check=True)

    lufs, peak = loudness(output)
    report = {
        'version': '1.0',
        'output': str(output),
        'picture': str(picture),
        'music_bed': str(music),
        'duration_seconds': round(probe_duration(output), 3),
        'music_volume': music_volume,
        'ducking': {'music_volume_during_speech': duck_volume,
                    'attack_ms': attack_ms, 'release_ms': release_ms},
        'loudnorm_target': target_lufs,
        'integrated_lufs': lufs,
        'true_peak_dbfs': peak,
        'limiter': 'alimiter=limit=0.70:level=false',
    }
    dump(project / 'artifacts/audio_mix_report.json', report)
    log(f'FINAL {output} {report["duration_seconds"]:.3f}s '
        f'{lufs} LUFS / {peak} dBFS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
