#!/usr/bin/env python3
"""Build locked strict-Ref2VA specs for a production project.

This is the single global entry point. Project-specific decisions live in an
``authoring.json`` data file; all prompt construction and voice/cast/previs
enforcement lives in :mod:`novel_h3.ref2va_builder`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novel_h3.ref2va_builder import CastMember, LockedShot, SceneRef, ShotLine, VoiceBinding, build_spec, visual_core
from novel_h3.voice_refs import VoiceRef, load_manifest


def load(path: str | Path) -> dict:
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authoring', required=True, help='project authoring.json')
    parser.add_argument('--out', default='', help='override output directory')
    parser.add_argument('--shots', default='', help='comma-separated shot ids')
    args = parser.parse_args()
    authoring_path = Path(args.authoring)
    authoring = json.loads(authoring_path.read_text(encoding='utf-8'))
    script = load(authoring['script'])
    order = [s for section in script['sections'] for s in section['shots']]
    lines = load(authoring['lines'])['lines']
    manifest = load_manifest(ROOT / authoring['voice_manifest'])
    previs_specs = load(authoring['previs_specs'])['shots']
    out = ROOT / (args.out or authoring['output_dir'])
    out.mkdir(parents=True, exist_ok=True)
    wanted = {s.strip() for s in args.shots.split(',') if s.strip()} or set(order)
    voice_role = authoring['voice_role']
    for sid in order:
        if sid not in authoring['shots'] or sid not in wanted:
            continue
        shot_data = authoring['shots'][sid]
        source_shot = load(Path(authoring['shots_dir']) / f'{sid}.json')
        previs_cast = {item['id']: item for item in previs_specs[sid]['cast']}
        cast = []
        for asset in shot_data['cast']:
            info = authoring['characters'][asset]
            pos = previs_cast.get(asset, {})
            cast.append(CastMember(
                asset_id=asset, name=info['name'], definition=info['definition'],
                image_path=info['image_path'], instances=1,
                x=float(pos.get('x', 0.0)), y=float(pos.get('y', 0.0)),
                pose=pos.get('pose', 'standing'),
            ))
        scene_info = authoring['scenes'][shot_data['scene']]
        scene = SceneRef(asset_id=shot_data['scene'], name=scene_info['name'],
                         definition=scene_info['definition'], image_path=scene_info['image_path'])
        spoken = sorted([line for line in lines if line['shot'] == sid and line['role'] != 'narrator'],
                        key=lambda item: item['offset'])
        voice_bindings = []
        seen = set()
        for line in spoken:
            role = line['role']
            if role in seen:
                continue
            seen.add(role)
            asset = voice_role[role][0]
            ref_info = manifest['references'][asset]
            path = Path(ref_info['path'])
            if not path.is_absolute():
                path = (ROOT / path).resolve()
            voice_bindings.append(VoiceBinding(
                role=role, subject_asset=asset if role != 'neighbor' else None,
                ref=VoiceRef(role=role, asset_id=f'voice_{asset}', path=path,
                             source_line_ids=tuple(ref_info.get('source_line_ids', ())),
                             duration_seconds=float(ref_info.get('duration_seconds', 0)),
                             median_f0_hz=ref_info.get('median_f0_hz')),
            ))
        shot_lines = [ShotLine(speaker=line['role'], text=line['text'], offset=float(line['offset']),
                               subject_asset=voice_role[line['role']][0] if line['role'] != 'neighbor' else None)
                      for line in spoken]
        previs_path = None
        if shot_data.get('previs'):
            previs_path = str(Path(authoring['previs_dir']) / f'{sid}.png')
        locked = LockedShot(
            shot_id=sid, title=source_shot.get('title') or sid, frames=int(source_shot['frames']),
            seed=int(source_shot['seed']) + int(shot_data.get('seed_offset', authoring.get('seed_offset', 0))),
            visual_core=shot_data.get('visual_override') or visual_core(source_shot['sections']['detailed_description'], source_shot.get('title', sid)),
            soundscape=source_shot['sections'].get('overall_soundscape') or 'Natural period ambience, cloth movement and synchronous physical sounds. No music.',
            cast=tuple(cast), scene=scene, extras=tuple(shot_data.get('extras', [])),
            voices=tuple(voice_bindings), lines=tuple(shot_lines), previs_path=previs_path,
            open_state=shot_data.get('open', ''), close_state=shot_data.get('close', ''),
            framing=shot_data.get('framing', ''),
            strong_no_text=bool(shot_data.get('strong_no_text', False)),
        )
        spec = build_spec(locked)
        (out / f'{sid}.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(sid, 'voices', len(spec['voices']), 'visuals', len(spec['visuals']), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
