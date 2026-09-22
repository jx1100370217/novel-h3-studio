"""A location-level continuity contract shared by every shot and future compile."""
from pathlib import Path
from .project import read, digest


def contract(root, shot):
    path = Path(root)/'bible/scene_staging.json'
    staging = read(path).get('locations', {}) if path.exists() else {}
    location = staging.get(shot.get('scene_id'), {})
    refs = shot.get('references', [])
    subjects = {r['asset_id']:f'<Subject {i}>' for i,r in enumerate(refs,1)}
    scene = subjects.get(shot.get('scene_id'), 'the bound environment')
    lines = [f'{scene} is the sole set for the entire scene. Retain its architecture, surface materials, daylight direction, weather and color temperature across every cut. Character portrait backgrounds are not sets.',
             'Maintain the established entrance-to-rear axis and screen travel direction. Cuts change camera coverage, never set geography. Match the end action to the next beginning; no repeated entrance or lingering portrait hold.']
    if location.get('layout'):
        lines.append(location['layout'])
    visible_dialogue = any(
        line.get('kind') != 'voiceover' and str(line.get('text', '')).strip()
        for line in shot.get('dialogue', [])
    )
    if visible_dialogue:
        lines.append(
            'Dialogue coverage is one uninterrupted take: keep the assigned speaking subject face and upper torso in frame from the first to the last dialogue window. '
            'The environment plate is background only and must never replace the speaker. Never cut to an empty hall, empty room, throne-only, prop-only, ceiling, floor, corridor, listener-only or wide establishing frame while dialogue is present.'
        )
    marks = {}
    for aid, label in subjects.items():
        mark = location.get('characters',{}).get(aid)
        if mark:
            marks[aid] = mark
            lines.append(f'{label}: {mark}. Return to this same seat, eyeline and background for later dialogue; do not teleport or mirror the room.')
    return {'version':1,'location_id':shot.get('scene_id'), 'layout_sha256':digest(location),
            'blocking':marks,'prompt':' '.join(lines)}
