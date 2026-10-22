#!/usr/bin/env python3
"""Build strict six-section Ref2VA shot specs for the v4 full render.

Reads the v3/v2/v1 authored prompts and the v4 dialogue timeline, then writes
one strict Ref2VA JSON per shot under the FastVideo project. The official
novel_h3.ref2va validator is the source of truth; this script only assembles
the authored material into the six-section contract.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT = ROOT / 'projects/liaozhai-kaochenghuang'
DEFAULT_OUT = ROOT / 'projects/liaozhai-kaochenghuang-fastvideo/shots'
DEFAULT_NATIVE = ROOT / 'projects/liaozhai-kaochenghuang-fastvideo/takes'

CHARACTERS = {'songtao', 'songtao_mother', 'zhang_sheng', 'guandi', 'in_law_relatives'}
GRAPHICS = {'A01', 'A16', 'A45'}  # designed title/quote/end cards, not model shots
ROLE_ASSET = {
    'songtao': 'songtao',
    'mother': 'songtao_mother',
    'zhang': 'zhang_sheng',
    'guandi': 'guandi',
    'wife': 'in_law_relatives',
}

# Hand-authored English descriptions for the shots whose source prompts are in
# Chinese. A18 is already authored in the pilot spec and is reused as-is.
CHINESE_OVERRIDES = {
    'A02': {
        'visual': ('A weak Song Tao lies on the wooden bed, takes the summons handed in by the unseen clerk, '
                   'and pushes himself up to look toward the white-foreheaded horse outside the door. '
                   'Only the clerk\'s sleeve enters the frame; his face is never shown.'),
        'sound': 'Quiet sickroom tone, paper and cloth movement, the oil lamp hiss, a distant horse breath. No music.',
    },
    'A11': {
        'visual': ('Song Tao rides the white-foreheaded horse along a cold road at dawn, passing bare trees and '
                   'low stone walls. The camera tracks beside him as the road opens toward a distant gate.'),
        'sound': 'Hoofbeats on packed earth, cold wind in bare branches, leather creak. No music.',
    },
    'A12': {
        'visual': ('Song Tao dismounts outside a vast hall, leads the horse to a post, and walks toward the '
                   'stone steps where other candidates wait. The hall doors stand open, red columns receding into shadow.'),
        'sound': 'Courtyard wind, distant voices of candidates, horse breath and harness, stone underfoot. No music.',
    },
    'A15': {
        'visual': ('Song Tao sits at the left desk, writes his answer, and passes the paper toward the hall. '
                   'Zhang Sheng sits at the right desk; two blank exam papers and ink are laid out. '
                   'The camera pushes slowly from the brush and paper up to Song Tao\'s face.'),
        'sound': 'Brush on paper, inkstone scrape, paper rustle, a large hall reverb. No music.',
    },
    'A20': {
        'visual': ('Guandi opens the ledger of lifespans on the high desk and reads the entry. '
                   'The camera holds on the turning pages and then rises to his stern face.'),
        'sound': 'Dry paper, a low hall reverb, candle crackle, a distant bronze bell. No music.',
    },
    'A22': {
        'visual': ('Outside the hall, Zhang Sheng takes Song Tao\'s hand in farewell. The white-foreheaded horse '
                   'waits behind them; the stone road leads away into cold mist.'),
        'sound': 'Open-air wind, cloth and harness, a horse stamping once, distant birds. No music.',
    },
    'A18': {
        'visual': ('The camera begins in a medium-wide low angle inside the hall. Guandi sits behind the high '
                   'judge\'s desk, his green and gold robe filling the upper center of the frame, his long black '
                   'beard and severe face lit by candles. Song Tao stands below him on the stone floor, small '
                   'against the desk, his hands at his sides and his eyes lifted toward Guandi. Red columns frame '
                   'both figures and incense smoke crosses the warm light. The camera pushes in slowly.'),
        'sound': 'A vast stone hall with low natural reverb, candle crackle, faint wind outside the columns, and '
                 'the rustle of heavy robes. No music.',
    },
    'A44': {
        'visual': ('The camera begins in a wide shot inside the hall at dawn. Rows of dark wooden desks recede '
                   'into the incense smoke; red columns rise on both sides and dim lanterns hang above the stone '
                   'floor. One red-robed city god stands on the dais with his back to camera, a black gauze hat on '
                   'his head and gold embroidery catching the lantern light. The camera pushes in almost '
                   'imperceptibly as the incense smoke drifts across the frame.'),
        'sound': 'A vast empty temple at dawn, low wind beyond the columns, a faint temple bell, the dry tick of '
                 'incense coils, and the soft flutter of a hanging lantern. No music.',
    },
}

EN_TITLES = {
    'A02': 'The summons at the sickbed',
    'A11': 'The road to the examination',
    'A12': 'Waiting outside the hall',
    'A15': 'The exam question',
    'A18': "The city god's appointment",
    'A20': 'The ledger of lifespans',
    'A22': 'Farewell outside the hall',
    'A44': 'The city god watches the world',
}

ADDITIONAL_VISIBLE = {
    'A04': ['one tall faceless messenger in a black robe, his face wrapped in shadow'],
    'A05': ['one pale hand holding the folded summons'],
    'A07': ['one tall faceless messenger in a black robe and high hat, only his jaw visible'],
    'A26': ['one middle-aged neighbor in a plain robe'],
    'A44': ['one red-robed city god seen from behind, standing on the dais'],
}


def _load(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def _source_prompt(project: Path, shot: dict) -> str:
    if not shot.get('source'):
        return shot.get('prompt') or ''
    match = re.search(r'(V\d+)\.mp4', shot['source'])
    if not match:
        return ''
    v2 = _load(project / 'v2' / 'shots_v2' / f'{match.group(1)}.json')
    prompt = v2.get('prompt') or ''
    if prompt.startswith('REUSE_V1:'):
        s1 = prompt.split(':', 1)[1].strip()
        prompt = _load(project / 'shots' / f'{s1}.json').get('prompt') or ''
    return prompt


def _source_refs(project: Path, shot: dict) -> list[dict]:
    if not shot.get('source'):
        return list(shot.get('references') or [])
    match = re.search(r'(V\d+)\.mp4', shot['source'])
    if not match:
        return []
    v2 = _load(project / 'v2' / 'shots_v2' / f'{match.group(1)}.json')
    prompt = v2.get('prompt') or ''
    if prompt.startswith('REUSE_V1:'):
        s1 = prompt.split(':', 1)[1].strip()
        return list(_load(project / 'shots' / f'{s1}.json').get('references') or [])
    return list(v2.get('references') or [])


def _extract_section(prompt: str, name: str) -> str:
    pattern = rf'(?ms)^{re.escape(name)}:\s*(.*?)(?=^[a-z_]+:\s*$|^negative:|\Z)'
    match = re.search(pattern, prompt)
    return match.group(1).strip() if match else ''


def _clean_visual(text: str, has_dialogue: bool) -> str:
    text = re.sub(r'No speech or human voice.*?(?=(?:\n[A-Z][a-z]+:|$))', '', text, flags=re.S | re.I)
    text = re.sub(r'\bNo music, no subtitles, no captions, no on-screen text\.?', '', text, flags=re.I)
    text = re.sub(r'\bno on-screen text\b', '', text, flags=re.I)
    text = re.sub(r'\n{2,}', '\n', text).strip()
    if not text.startswith('[Shot 1]'):
        text = '[Shot 1] ' + text
    return text


def _frames(duration: float) -> int:
    import math
    frames = round(float(duration) * 24)
    return 5 + 17 * max(0, math.ceil((frames - 5) / 17))


def _voice_label(role: str) -> str:
    return {
        'messenger': 'the faceless messenger',
        'neighbor': 'the neighbor',
    }.get(role, f'the {role}')


def build_spec(project: Path, shot: dict, lines: list[dict]) -> dict:
    sid = shot['id']
    duration = float(shot['duration_seconds'])
    frames = _frames(duration)
    refs = _source_refs(project, shot)
    visuals = []
    subjects = {}
    subject_index = 0
    cast_count = 0
    for ref in refs:
        asset = ref['asset_id']
        subject_index += 1
        label = f'<Subject {subject_index}>'
        picture = f'<Picture {subject_index}>'
        kind = 'character' if asset in CHARACTERS else 'scene'
        if kind == 'character':
            cast_count += 1
            if asset == 'in_law_relatives':
                definition = (f'{label} is the young wife in {picture}; use only the young woman and ignore '
                              f'the other family members in the reference.')
            else:
                definition = (f'{label} is the registered character in {picture}; preserve face, age, hair, '
                              f'costume and identity.')
        else:
            definition = (f'{label} is the location in {picture}; preserve architecture, materials and motivated light.')
        visuals.append({
            'asset_id': asset,
            'subject': label,
            'picture': picture,
            'kind': kind,
            'instances': 1 if kind == 'character' else None,
            'visible': True,
            'generation_path': f'projects/liaozhai-kaochenghuang-fastvideo/assets/refs/{asset}.png',
        })
        subjects[asset] = (label, picture, definition)

    prompt = _source_prompt(project, shot)
    override = CHINESE_OVERRIDES.get(sid)
    if override:
        visual = override['visual']
        if not visual.startswith('[Shot 1]'):
            visual = '[Shot 1] ' + visual
        sound = override['sound']
        summary = f'One continuous photorealistic Chinese period drama shot. {EN_TITLES.get(sid, sid)}.'
    else:
        visual = _clean_visual(_extract_section(prompt, 'detailed_description') or shot.get('title', sid), bool(lines))
        sound = _extract_section(prompt, 'overall_soundscape') or (
            'Natural period-drama ambience, cloth movement and synchronous physical sounds. No music.')
        summary = _extract_section(prompt, 'summary') or f'One continuous photorealistic Chinese period drama shot. {shot.get("title", sid)}.'
        summary = re.sub(r'\bno on-screen text\b', '', summary, flags=re.I).strip().rstrip('.') + '.'

    spoken_lines = [line for line in lines if line['shot'] == sid and line['role'] != 'narrator']
    # Assign speaker IDs by first vocal order in the shot.
    speaker_ids = {}
    dialogue_blocks = []
    for line in sorted(spoken_lines, key=lambda item: item['offset']):
        role = line['role']
        if role not in speaker_ids:
            speaker_ids[role] = len(speaker_ids) + 1
        sid_num = speaker_ids[role]
        subject_label = None
        if role in ROLE_ASSET and ROLE_ASSET[role] in subjects:
            subject_label = subjects[ROLE_ASSET[role]][0]
        speaker = f'{subject_label} ' if subject_label else f'{_voice_label(role)} '
        stamp = line['offset']
        mm = int(stamp // 60)
        ss = int(stamp % 60)
        ms = int(round((stamp - int(stamp)) * 1000))
        dialogue_blocks.append(
            f'At {mm:02d}:{ss:02d}.{ms:03d}, {speaker}(S{sid_num}) speaks, '
            f'<d>[Chinese] {line["text"]}</d>'
        )
        line['_speaker_subject'] = subject_label
        line['_sid'] = sid_num
    for asset, (label, picture, definition) in subjects.items():
        if label not in visual:
            visual += f' {label} is present in the frame.'
    if dialogue_blocks:
        visual = visual.rstrip() + ' ' + ' '.join(dialogue_blocks)

    subject_definitions = '\n'.join(item[2] for item in subjects.values())
    if not subject_definitions:
        subject_definitions = '<Subject 1> is the location in <Picture 1>; preserve architecture, materials and light.'
    retention = '\n'.join(
        f'{label} (appears in [Shot 1]): {"fully_preserved" if asset in CHARACTERS else "fully_preserved"} - '
        f'preserve the defined characteristics.'
        for asset, (label, picture, definition) in subjects.items()
    ) or '<Subject 1> (appears in [Shot 1]): fully_preserved - preserve the location.'

    spoken = []
    for line in sorted(spoken_lines, key=lambda item: item['offset']):
        entry = {'speaker': line['role'], 'text': line['text']}
        if line.get('_speaker_subject'):
            entry['speaker_subject'] = line['_speaker_subject']
        spoken.append(entry)

    return {
        'shot': sid,
        'seed': int(shot.get('seed') or (2026102500 + int(re.sub(r'\D', '', sid) or 0))),
        'width': 1344,
        'height': 768,
        'frames': frames,
        'visuals': visuals,
        'voices': [],
        'spoken_lines': spoken,
        'additional_visible_people': list(ADDITIONAL_VISIBLE.get(sid, [])),
        'sections': {
            'subject_definitions': subject_definitions,
            'summary': f'[reference generation] {summary}',
            'retention_analysis': retention,
            'detailed_description': f'The target video is a photorealistic Chinese period drama shot on 35mm film, with period-drama lighting and a restrained camera. No subtitles, no captions, no on-screen text, no text overlays.\n{visual}',
            'overall_soundscape': sound,
            'non_diegetic_music': 'N/A',
        },
    }


def update_progress(project: Path, done: int, total: int, current: str, phase: str) -> None:
    checkpoint = {
        'version': '1.0',
        'project_id': project.name,
        'pipeline_type': 'novel-cinematic',
        'stage': 'assets',
        'status': 'in_progress',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'artifacts': {},
        'metadata': {
            'partial_progress': {
                'phase': phase,
                'done': done,
                'total': total,
                'current': current,
                'updated_at': time.time(),
            }
        },
    }
    (project / 'checkpoint_assets.json').write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
    event = {
        'ts': datetime.now(timezone.utc).isoformat(),
        'tool': 'fastvideo_h3_video',
        'event': 'start' if phase == 'render' else 'progress',
        'shot': current,
        'done': done,
        'total': total,
    }
    with (project / 'events.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=DEFAULT_PROJECT)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--shots', default='')
    parser.add_argument('--include-graphics', action='store_true')
    args = parser.parse_args()
    project = args.project.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    script = _load(project / 'v4/script_v4.json')
    order = [shot for section in script['sections'] for shot in section['shots']]
    wanted = [s.strip() for s in args.shots.split(',') if s.strip()] or [s for s in order if s not in GRAPHICS]
    lines = _load(project / 'v4/voiceover/vo_lines_v4.json')['lines']
    if not args.include_graphics:
        wanted = [s for s in wanted if s not in GRAPHICS]
    for index, sid in enumerate(wanted, 1):
        shot = _load(project / 'v4/shots_v4' / f'{sid}.json')
        spec = build_spec(project, shot, lines)
        (out / f'{sid}.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        update_progress(project, index, len(wanted), sid, 'specs')
        print(f'{index}/{len(wanted)} {sid} {spec["frames"]}f', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
