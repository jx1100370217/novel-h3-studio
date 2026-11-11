#!/usr/bin/env python3
"""Build the cinematic project's music bed from the locked edit timing.

The cue layout is project data in ``assets/music/cues.json``. Each cue is
trimmed, faded, normalised to -30 LUFS, placed on the timeline at a shot
boundary, and summed without amix normalisation so the authored levels survive.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--cues', type=Path, default=None)
    parser.add_argument('--output', type=Path, default=None)
    args = parser.parse_args()

    project = args.project.resolve()
    cues_path = args.cues or project / 'assets/music/cues.json'
    output = args.output or project / 'assets/music/music_bed.wav'
    cues = load(cues_path)
    timing = load(project / 'artifacts/edit_timing.json')
    total = float(timing['total_seconds'])
    starts = {shot['id']: float(shot['start']) for shot in timing['shots']}

    def boundary(value: str) -> float:
        return total if str(value).upper() == 'END' else starts[value]

    payload = []
    for cue in cues:
        asset = project / 'assets/music' / cue['asset']
        if not asset.is_file():
            raise SystemExit(f'missing music cue: {asset}')
        start = boundary(cue['start_shot'])
        end = boundary(cue['end_shot'])
        if end <= start:
            raise SystemExit(f'invalid cue window {cue["start_shot"]}..{cue["end_shot"]}')
        payload.append((asset, start, end, float(cue.get('fade_in', 0)),
                        float(cue.get('fade_out', 0))))

    inputs, filters = [], []
    for index, (asset, start, end, fade_in, fade_out) in enumerate(payload):
        inputs += ['-i', str(asset)]
        duration = end - start
        filters.append(
            f'[{index}:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,'
            f'afade=t=in:st=0:d={fade_in:.3f},'
            f'afade=t=out:st={max(0.0, duration - fade_out):.3f}:d={fade_out:.3f},'
            f'loudnorm=I=-30:TP=-6:LRA=11,'
            f'adelay={int(start * 1000)}|{int(start * 1000)}[c{index}]'
        )
    labels = ''.join(f'[c{index}]' for index in range(len(payload)))
    filters.append(f'{labels}amix=inputs={len(payload)}:duration=longest:normalize=0,'
                   f'atrim=0:{total:.3f},asetpts=PTS-STARTPTS[out]')

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', *inputs,
         '-filter_complex', ';'.join(filters), '-map', '[out]',
         '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(output)], check=True)
    print(f'wrote {output} ({total:.3f}s, {len(payload)} cues)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
