#!/usr/bin/env python3
"""Write the v4 45-shot plan as OpenMontage canonical artifacts + checkpoints.

Backlot reads projects/<id>/artifacts/{script,scene_plan}.json and the
checkpoint_*.json files. The old 14-scene VDN plan is superseded here by the
approved v4 45-shot dialogue cut so the board shows the real production.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENMONTAGE = ROOT / 'openmontage'
sys.path.insert(0, str(OPENMONTAGE))
sys.path.insert(0, str(ROOT))

PROJECT = ROOT / 'projects/liaozhai-kaochenghuang'


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def build_script(order, shots, lines) -> dict:
    sections = []
    cursor = 0.0
    by_shot = {}
    for line in lines:
        by_shot.setdefault(line['shot'], []).append(line)
    for sid in order:
        shot = shots[sid]
        duration = float(shot['duration_seconds'])
        spoken = sorted(by_shot.get(sid, []), key=lambda item: item['offset'])
        text = ' '.join(f"{line['role']}: {line['text']}" for line in spoken) or (shot.get('title') or sid)
        sections.append({
            'id': sid,
            'label': shot.get('title') or sid,
            'text': text,
            'start_seconds': round(cursor, 6),
            'end_seconds': round(cursor + duration, 6),
        })
        cursor += duration
    return {
        'version': '1.0',
        'title': '考城隍 v4',
        'total_duration_seconds': round(cursor, 6),
        'sections': sections,
    }


def build_scene_plan(order, shots, script) -> dict:
    by_id = {section['id']: section for section in script['sections']}
    scenes = []
    for sid in order:
        shot = shots[sid]
        section = by_id[sid]
        scene_type = 'text_card' if sid in {'A01', 'A16', 'A45'} else 'generated'
        scenes.append({
            'id': sid,
            'type': scene_type,
            'description': shot.get('title') or sid,
            'start_seconds': section['start_seconds'],
            'end_seconds': section['end_seconds'],
            'script_section_id': sid,
            'framing': 'authored 16:9 period-drama framing',
            'movement': 'restrained locked-off or slow push-in per shot spec',
            'shot_intent': 'Faithful beat of the v4 dialogue cut.',
            'narrative_role': 'emotional_beat',
            'required_assets': [{
                'type': 'video',
                'description': f'FastH3-Omni NVFP4 QAD take for {sid} (1344x768, native H3 dialogue/SFX)'
                               if scene_type == 'generated' else f'Designed graphic insert for {sid}',
                'source': 'generate' if scene_type == 'generated' else 'provided',
            }],
        })
    return {'version': '1.0', 'style_playbook': 'clean-professional', 'scenes': scenes}


def main() -> int:
    import jsonschema
    from lib.checkpoint import write_checkpoint

    script_src = _load(PROJECT / 'v4/script_v4.json')
    order = [sid for section in script_src['sections'] for sid in section['shots']]
    shots = {sid: _load(PROJECT / 'v4/shots_v4' / f'{sid}.json') for sid in order}
    lines = _load(PROJECT / 'v4/voiceover/vo_lines_v4.json')['lines']
    script = build_script(order, shots, lines)
    scene_plan = build_scene_plan(order, shots, script)

    for name, data in (('script', script), ('scene_plan', scene_plan)):
        schema = _load(OPENMONTAGE / 'schemas/artifacts' / f'{name}.schema.json')
        jsonschema.validate(data, schema)
        out = PROJECT / 'artifacts' / f'{name}.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        print('wrote', out)

    write_checkpoint(PROJECT.parent, PROJECT.name, 'breakdown', 'completed',
                     {'script': script}, human_approved=True,
                     metadata={'note': 'v4 45-shot dialogue cut approved by the user as full plan B.'})
    write_checkpoint(PROJECT.parent, PROJECT.name, 'scene_plan', 'completed',
                     {'scene_plan': scene_plan}, human_approved=True,
                     metadata={'note': 'v4 45-shot scene plan derived from the approved script.'})
    print('checkpoints written')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
