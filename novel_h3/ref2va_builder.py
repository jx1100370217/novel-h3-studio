"""Global strict-Ref2VA shot builder with locked cast, voices and blocking.

This is the reusable production path for novel-cinematic shots. A project
supplies data (cast refs, scene refs, voice refs, visible extras, previs path,
opening/closing states); this module writes the six-section spec and validates
it with the official ``novel_h3.ref2va`` contract before it reaches FastVideo.

The builder never invents a speaker binding. If a line has no matching voice
reference, construction fails instead of letting H3 guess a voice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .ref2va import SECTIONS, population_text, render
from .voice_refs import VoiceRef


@dataclass(frozen=True)
class CastMember:
    asset_id: str
    name: str
    definition: str
    image_path: str
    instances: int = 1
    kind: str = 'character'
    x: float = 0.0
    y: float = 0.0
    pose: str = 'standing'


@dataclass(frozen=True)
class SceneRef:
    asset_id: str
    name: str
    definition: str
    image_path: str


@dataclass(frozen=True)
class VoiceBinding:
    role: str
    ref: VoiceRef
    subject_asset: str | None


@dataclass(frozen=True)
class VideoRef:
    """A source clip used as a continuation or motion reference.

    ``asset_id`` is the project-level identity (for example the previous shot
    id). ``path`` must point at a real clip under the repository root.
    ``retention`` follows the official Ref2VA visual markers.
    """
    asset_id: str
    path: str
    definition: str
    retention: str = 'partially_preserved'
    retention_detail: str = (
        'preserve the ending state, identity, costume, hand and prop position, light direction '
        'and screen direction; do not copy the reference framing, cut points, camera movement, '
        'old dialogue or audio'
    )
    task_type: str = 'video continuation'
    tail_seconds: float = 0.0
    cache_dir: str = 'runtime/video-refs'


@dataclass(frozen=True)
class AnchorImage:
    """A concrete first-frame/keyframe anchor, not a style reference."""
    asset_id: str
    path: str
    definition: str
    retention: str = 'fully_preserved'
    retention_detail: str = (
        'the target video starts exactly on this composition; preserve the opening pose, '
        'costume, prop placement, light direction and screen direction'
    )


@dataclass(frozen=True)
class ShotLine:
    speaker: str
    text: str
    offset: float
    subject_asset: str | None


@dataclass(frozen=True)
class LockedShot:
    shot_id: str
    title: str
    frames: int
    seed: int
    visual_core: str
    soundscape: str
    cast: tuple[CastMember, ...]
    scene: SceneRef
    extras: tuple[str, ...] = ()
    voices: tuple[VoiceBinding, ...] = ()
    videos: tuple[VideoRef, ...] = ()
    anchor_image: AnchorImage | None = None
    lines: tuple[ShotLine, ...] = ()
    previs_path: str | None = None
    open_state: str = ''
    close_state: str = ''
    framing: str = ''
    blocking: str = ''
    eyeline: str = ''
    camera_move: str = ''
    props: str = ''
    strong_no_text: bool = False
    allow_multi_speaker: bool = False
    post_dialogue: bool = False
    continuity_required: bool = False
    width: int = 1344
    height: int = 768


def visual_core(detailed_description: str, fallback: str = '') -> str:
    """Strip v4 population/dialogue/old-text blocks from an authored description."""
    text = detailed_description
    if '[Shot 1]' in text:
        text = text.split('[Shot 1]', 1)[1]
    text = re.sub(r'<Subject \d+> is present in the frame\.', '', text)
    text = re.sub(r'At \d{2}:\d{2}\.\d{3}.*?</d>', '', text, flags=re.S)
    text = re.sub(r'The line is heard only.*?(?:screen|overlays)\.', '', text, flags=re.S | re.I)
    text = re.sub(r'No subtitles.*?overlays\.', '', text, flags=re.I)
    text = re.sub(r'No dialogue, no voice, no music\.', '', text, flags=re.I)
    text = re.sub(r'No dialogue, no lip movement, no voice, no music\.', '', text, flags=re.I)
    text = re.sub(r'No speech or human voice[^.]*\.', '', text, flags=re.I)
    text = re.sub(r'\s+', ' ', text).strip()
    return text or fallback


def _positions(cast: Iterable[CastMember], extras: Iterable[str]) -> str:
    parts = []
    for item in cast:
        side = 'camera-left' if item.x < -0.35 else 'camera-right' if item.x > 0.35 else 'center'
        depth = 'foreground' if item.y < 0.8 else 'midground' if item.y < 2.4 else 'background'
        parts.append(f'{item.name} is {side} in the {depth}, {item.pose}')
    parts.extend(extras)
    return '; '.join(parts)


def _people(count: int) -> str:
    return 'one person' if count == 1 else f'{count} people'


def build_spec(shot: LockedShot, *, require_props: bool = False) -> dict:
    """Build and officially validate one locked Ref2VA shot spec.

    ``require_props`` is the production gate: every new shot must name its
    exact props and set elements, so H3 cannot invent a table, room or food
    service. Legacy callers can omit it while re-rendering an approved take.
    """
    if require_props and not str(shot.props or '').strip():
        raise ValueError(
            f'{shot.shot_id}: every shot must declare props and set elements; '
            'use a non-empty props string, or "none" for a deliberately empty set')
    if shot.continuity_required and not shot.videos and not shot.previs_path:
        raise ValueError(
            f'{shot.shot_id}: a same-scene continuation needs a <Video N> tail or a '
            'previs blocking guide; a bare cast/scene reference lets positions jump')
    lines = sorted(shot.lines, key=lambda item: item.offset)
    by_role = {voice.role: voice for voice in shot.voices}
    speaking = list(dict.fromkeys(line.speaker for line in lines))
    for role in speaking:
        if role not in by_role:
            raise ValueError(f'{shot.shot_id}: speaker {role!r} has no voice reference')
    speaker_assets: list[str] = []
    for role in speaking:
        asset = by_role[role].subject_asset
        if asset and asset not in speaker_assets:
            speaker_assets.append(asset)
    # H3 pairs the Nth audio reference with the Nth visible subject. Put the
    # speaking cast first, in first-vocal order, so <Audio N> and <Subject N>
    # always describe the same person; silent visible cast follows, and
    # off-screen voices are appended after the visible cast.
    def _cast_key(item: CastMember) -> tuple[int, int]:
        if item.kind == 'character' and item.asset_id in speaker_assets:
            return (0, speaker_assets.index(item.asset_id))
        return (1, 0)

    cast = tuple(sorted(shot.cast, key=_cast_key))
    subject: dict[str, str] = {}
    visuals: list[dict] = []
    defs: list[str] = []
    retention: list[str] = []
    for i, item in enumerate(cast, 1):
        label, picture = f'<Subject {i}>', f'<Picture {i}>'
        subject[item.asset_id] = label
        visuals.append({
            'asset_id': item.asset_id, 'subject': label, 'picture': picture,
            'kind': item.kind, 'instances': int(item.instances), 'visible': True,
            'generation_path': item.image_path,
        })
        defs.append(f'{label} is {item.name} in {picture}; {item.definition}')
        if item.kind == 'prop':
            retention.append(
                f'{label} (appears in [Shot 1]): attribute_transfer - transfer only the hand/forearm '
                f'appearance; do not create a face, head, torso or full body from this reference.'
            )
        else:
            retention.append(
                f'{label} (appears in [Shot 1]): fully_preserved - preserve face, age, hair, costume and '
                f'identity; {'exactly one body, appearing once' if item.instances == 1 else f'exactly {item.instances} distinct bodies, each appearing once'}.'
            )
    scene_label = f'<Subject {len(cast) + 1}>'
    scene_picture = f'<Picture {len(cast) + 1}>'
    visuals.append({
        'asset_id': shot.scene.asset_id, 'subject': scene_label, 'picture': scene_picture,
        'kind': 'scene', 'visible': True, 'generation_path': shot.scene.image_path,
    })
    defs.append(f'{scene_label} is {shot.scene.name} in {scene_picture}; {shot.scene.definition}')
    retention.append(
        f'{scene_label} (appears in [Shot 1]): fully_preserved - preserve architecture, materials and '
        f'motivated light; do not add people seen in the reference.'
    )

    previs_label = None
    if shot.previs_path:
        previs_label = f'<Subject {len(cast) + 2}>'
        previs_picture = f'<Picture {len(cast) + 2}>'
        count = sum(item.instances for item in cast if item.kind == 'character') + len(shot.extras)
        visuals.append({
            'asset_id': f'previs_{shot.shot_id}', 'subject': previs_label, 'picture': previs_picture,
            'kind': 'prop', 'visible': True, 'generation_path': shot.previs_path,
        })
        defs.append(
            f'{previs_label} is the silent grayscale blocking guide in {previs_picture}; it contains exactly '
            f'{_people(count)} in the authored positions. It is a reference diagram, not a physical object in '
            f'the scene. Match only body count, placement, pose, screen direction and camera; ignore its gray '
            f'materials, blank faces and studio lighting.'
        )
        retention.append(
            f'{previs_label} (appears in [Shot 1]): attribute_transfer - transfer only body count, placement, '
            f'pose, screen direction and camera; do not transfer gray materials or mannequin appearance.'
        )

    anchor_label = anchor_picture = None
    if shot.anchor_image:
        index = len(cast) + (3 if shot.previs_path else 2)
        anchor_label, anchor_picture = f'<Subject {index}>', f'<Picture {index}>'
        visuals.append({
            'asset_id': shot.anchor_image.asset_id, 'subject': anchor_label,
            'picture': anchor_picture, 'kind': 'prop', 'visible': True,
            'generation_path': shot.anchor_image.path,
        })
        defs.append(
            f'{anchor_label} and {anchor_picture} are the exact first-frame composition for [Shot 1]: '
            f'{shot.anchor_image.definition} It is a concrete frame anchor, not a style reference.'
        )
        retention.append(
            f'{anchor_label} (appears in [Shot 1]): {shot.anchor_image.retention} - '
            f'{shot.anchor_image.retention_detail}.'
        )

    video_payload: list[dict] = []
    video_defs: list[str] = []
    video_ret: list[str] = []
    allowed_retention = ('fully_preserved', 'partially_preserved', 'attribute_transfer', 'weak_reference')
    for i, ref in enumerate(shot.videos, 1):
        if ref.retention not in allowed_retention:
            raise ValueError(f'{shot.shot_id}: invalid video retention {ref.retention!r}')
        if ref.task_type not in ('video continuation', 'video editing', 'reference generation'):
            raise ValueError(f'{shot.shot_id}: invalid video task_type {ref.task_type!r}')
        label = f'<Video {i}>'
        video_payload.append({'asset_id': ref.asset_id, 'video': label, 'path': ref.path,
                              'tail_seconds': ref.tail_seconds, 'cache_dir': ref.cache_dir})
        video_defs.append(f'{label} is {ref.definition}')
        video_ret.append(f'{label} (appears in [Shot 1]): {ref.retention} - {ref.retention_detail}.')
    defs.extend(video_defs)
    retention.extend(video_ret)

    cast_roles = [item.asset_id for item in cast if item.kind == 'character']
    speaker_order = [role for role in speaking if by_role[role].subject_asset in cast_roles]
    speaker_order += [role for role in speaking if role not in speaker_order]
    off_screen_only = bool(lines) and all(not line.subject_asset for line in lines)
    visible_speakers = [role for role in speaker_order if by_role[role].subject_asset in cast_roles]
    if len(speaker_order) > 1 and not shot.allow_multi_speaker:
        raise ValueError(
            f'{shot.shot_id}: {len(speaker_order)} speaking characters in one take; '
            'split the dialogue into single-speaker shots (shot/reverse-shot) or set '
            'allow_multi_speaker=True only for a legacy take that passed voice_audit')
    # The official contract keeps (S1), (S2) in actual first-vocal order even
    # when the audio references are numbered by subject.
    vocal_order = list(dict.fromkeys(line.speaker for line in lines))
    role_sid = {role: index for index, role in enumerate(vocal_order, 1)}
    voice_payload: list[dict] = []
    voice_defs: list[str] = []
    voice_ret: list[str] = []
    role_audio: dict[str, str] = {}
    role_subject: dict[str, str | None] = {}
    for i, role in enumerate(speaker_order, 1):
        binding = by_role[role]
        audio = f'<Audio {i}>'
        role_audio[role] = audio
        role_subject[role] = subject.get(binding.subject_asset) if binding.subject_asset else None
        voice_payload.append({
            'asset_id': binding.ref.asset_id, 'audio': audio,
            'subject': role_subject[role], 'path': str(binding.ref.path), 'role': role,
        })
        if role_subject[role]:
            name = next(item.name for item in cast if item.asset_id == binding.subject_asset)
            voice_defs.append(
                f'{audio} is the voice reference for {role_subject[role]} (S{role_sid[role]}), '
                f'{name}; preserve this exact timbre only for {name} and never for another character.'
            )
        else:
            voice_defs.append(
                f'{audio} is the off-screen voice for {role}; no body for this speaker is visible in this shot.'
            )
        voice_ret.append(
            f'{audio}: partially_copy - copy only the vocal timbre and delivery; do not copy the reference\'s '
            f'spoken words or language.'
        )
    defs.extend(voice_defs)
    retention.extend(voice_ret)

    detail = shot.visual_core
    if off_screen_only and cast_roles:
        detail = (
            'Off-screen voice lock: no visible character speaks in this shot. The voice comes from an '
            'unseen speaker outside the frame; every visible mouth stays closed, the jaw stays still, '
            'there is no lip-sync, no speaking expression and no speech-shaped breathing for the entire '
            'shot. Do not assign the voice to any visible face. ' + detail
        )
    if anchor_picture:
        detail = (
            f'The first frame of the target video is exactly {anchor_picture}: open on that composition, '
            f'with the same pose, costume, prop placement, light and screen direction; never open on a '
            f'lying, standing or off-screen state. '
            + detail
        )
    if video_payload:
        detail = (
            'Continuity source: the target video opens from the exact ending state of '
            + ', '.join(item['video'] for item in video_payload)
            + '. Match the ending pose, hand and prop position, costume, light direction and screen '
              'direction; do not copy the reference framing, cut points, camera movement, old dialogue '
              'or audio. Do not replay, re-enact or restart the actions shown in the reference: begin on '
              'its final pose and continue the new beat forward. '
            + detail
        )
    if shot.open_state:
        detail = shot.open_state + ' ' + detail
    if shot.close_state:
        detail = detail.rstrip() + ' ' + shot.close_state
    count = sum(item.instances for item in cast if item.kind == 'character') + len(shot.extras)
    if shot.blocking:
        blocking = 'Blocking lock: ' + shot.blocking
    else:
        blocking = f'Blocking lock: exactly {_people(count)}. {_positions(cast, shot.extras)}. ' \
                   f'No other people, no duplicates, no reflections, no background extras.'
    if previs_label and not shot.blocking:
        blocking = (f'Blocking lock: the grayscale guide {previs_label} shows exactly {_people(count)}. '
                    f'{_positions(cast, shot.extras)}. No other people, no duplicates, no reflections, '
                    f'no background extras. The guide is a reference diagram only; do not reproduce its gray '
                    f'mannequin materials or studio light.')
    elif previs_label and shot.blocking:
        blocking += (f' The grayscale guide {previs_label} shows exactly {_people(count)}; use only its body '
                     f'count, placement, poses and camera, never its gray materials or mannequin appearance.')
    detail += ' ' + blocking
    if shot.eyeline:
        detail += ' Eyeline lock: ' + shot.eyeline
    elif shot.lines and count >= 2:
        detail += (' Eyeline lock: every visible character looks at the other character\'s eyes; '
                   'the speaker looks at the listener, the listener looks back at the speaker; '
                   'no one looks at the camera or off-frame.')
    elif shot.lines and count < 2:
        raise ValueError(f'{shot.shot_id}: a single-character dialogue shot needs an explicit eyeline')
    if shot.camera_move:
        detail += ' Camera movement lock: ' + shot.camera_move
    if shot.props:
        detail += (' Prop lock: only these props and set elements may appear: ' + shot.props
                   + ' Do not invent any additional table, chair, bench, interior furniture, window, wall, '
                     'food, bowl, plate, chopstick, vessel or decorative object.')
    else:
        detail += (' Prop lock: only the props and set elements explicitly named in this description may '
                   'appear; do not invent any additional table, chair, bench, interior furniture, window, '
                   'wall, food, bowl, plate, chopstick, vessel or decorative object.')
    detail += (' Instance lock: every named person is exactly one physical body. A close-up face and a '
               'full-body or seated view of the same person are one person, never two. Do not add a second '
               'copy in the background, doorway, reflection, portrait, statue, silhouette, as a servant, '
               'guard, candidate, neighbor or any other unlisted person.')
    detail += (' Costume continuity lock: every named person wears exactly the costume defined by their '
               'reference image; do not change robe colour, collar, belt, hat or hair between shots unless '
               'the description explicitly requests an authored costume change.')
    if count >= 2 or shot.extras:
        detail += (' Screen-direction lock: preserve each person\'s camera side and hand ownership across '
                   'cuts; do not mirror the action. A hand entering from camera-right belongs to the person '
                   'on camera-right, and a hand entering from camera-left belongs to the person on camera-left.')
    if re.search(r'\b(hand|hands|finger|fingers|forearm|wrist|palm)\b', detail, re.I):
        detail += (' Hand anatomy lock: each visible hand has exactly five fingers and one thumb, with one '
                   'wrist; no extra, fused, duplicated, missing or branching digits and no second hand.')
    if re.search(r'\bdesk\b', detail, re.I) and re.search(r'\b(behind|seated|sits|sitting)\b', detail, re.I):
        detail += (' Lower-body occlusion lock: the desk is solid and hides the seated person\'s lap, legs '
                   'and feet; no legs, knees, feet, stool or green cloth may appear below or under the desk.')
    if shot.framing:
        detail += ' Framing lock: ' + shot.framing
    if count >= 2:
        detail += (' Head-room lock: every visible head, including the top of the hair, stays fully '
                   'inside the frame; never crop a forehead, eyes, chin or shoulders at the frame edge.')
    if count >= 2 and 'wide' in str(shot.framing).lower():
        detail += (' Full-body staging lock: both people are visible head-to-toe; do not crop feet or '
                   'lower body; keep the camera far enough back to show the whole body.')
    detail += ' Reference bindings: ' + ' '.join(item['subject'] for item in visuals) + '.'
    # The spec JSON is what FastVideo actually receives. Insert the visible
    # population lock here (not only in the validation prompt) so the cast
    # count and the "ignore other people in a reference image" rule reach the
    # model. Validation reuses the same text and will not duplicate it.
    population = population_text(visuals, shot.extras)
    if population:
        detail = population + ' ' + detail
    if speaker_order:
        locks = []
        for role in speaker_order:
            audio = role_audio[role]
            if role_subject[role]:
                name = next(item.name for item in cast if item.asset_id == by_role[role].subject_asset)
                locks.append(f'{name} uses {audio} only')
            else:
                locks.append(f'the off-screen {role} uses {audio}')
        if visible_speakers:
            detail += (' Voice casting is locked: ' + '; '.join(locks) + '. Each line belongs only to the named '
                       'speaker; never swap voices, never let one character speak another character\'s line, and '
                       'match the moving lips only to the visible named speaker.')
        else:
            detail += (' Voice casting is locked: ' + '; '.join(locks) + '. All dialogue in this shot is '
                       'off-screen; no visible character speaks, and no visible mouth moves for any line.')
        if len(speaker_order) > 1:
            detail += (' Voice return lock: when a character speaks again after another character, switch back '
                       'to that character\'s own audio reference; never carry the previous speaker\'s timbre '
                       'into the next line.')
        for line in lines:
            audio = role_audio[line.speaker]
            label = role_subject[line.speaker]
            sid = role_sid[line.speaker]
            speaker = f'{label} (S{sid})' if label else f'the off-screen voice of {line.speaker} (S{sid})'
            mm = int(line.offset // 60); ss = int(line.offset % 60)
            ms = int(round((line.offset - int(line.offset)) * 1000))
            detail += f' At {mm:02d}:{ss:02d}.{ms:03d}, {speaker} speaks with {audio}, <d>[Chinese] {line.text}</d>'
            if not line.subject_asset:
                detail += (' The visible characters do not move their lips for this line; the voice has no '
                           'visible speaker in frame.')
            if shot.strong_no_text:
                detail += ' The line is heard only and is never written on screen.'
        silent = [item for item in cast
                  if item.kind == 'character' and item.asset_id not in speaker_order]
        if silent:
            detail += (' Silent-character lock: ' + '; '.join(
                f'{subject[item.asset_id]} ({item.name}) does not speak in this shot'
                for item in silent) + '; lips stay closed, no voice, no dialogue, no lip movement.')
    if shot.post_dialogue:
        detail += (' Silent reaction lock: this is a post-dialogue reaction take; no character speaks, '
                   'no character moves their lips, and no voice is generated in this take.')
    if not lines:
        detail += (' No dialogue, no voice, no speech, no lip movement; only the listed soundscape.')
    detail += (' No subtitles, no captions, no on-screen text, no text overlays. Do not paint the spoken words or any Chinese character anywhere in the frame.')
    soundscape = shot.soundscape
    if shot.post_dialogue and 'no human voice' not in soundscape.lower():
        soundscape = soundscape.rstrip('.') + '; no human voice, no speech, no lip movement.'

    spoken_lines = [
        {'speaker': line.speaker, 'text': line.text,
         'speaker_subject': subject.get(line.subject_asset) if line.subject_asset else None}
        for line in lines
    ]
    task_types = ['reference generation']
    if any(ref.task_type == 'video continuation' for ref in shot.videos):
        task_types.insert(0, 'video continuation')
    elif any(ref.task_type == 'video editing' for ref in shot.videos):
        task_types.insert(0, 'video editing')
    if shot.anchor_image:
        task_types.insert(0, 'keyframe completion')
    if voice_payload:
        task_types.append('audio reference')
    tasks = '[' + ' + '.join(dict.fromkeys(task_types)) + ']'
    sections = {
        'subject_definitions': '\n'.join(defs),
        'summary': f'{tasks} One continuous photorealistic Chinese period drama shot. {shot.title}.',
        'retention_analysis': '\n'.join(retention),
        'detailed_description': (
            'The target video is a photorealistic Chinese period drama shot on 35mm film, with period-drama '
            f'lighting and a restrained camera.\n[Shot 1] {detail}'
        ),
        'overall_soundscape': soundscape,
        'non_diegetic_music': 'N/A',
    }
    # Official validation includes the population contract and speaker/audio
    # ownership checks. Fail here, before the FastVideo submission.
    render(sections, visuals, voice_payload, spoken_lines, videos=video_payload,
           duration_seconds=shot.frames / 24,
           single_shot=True, no_music=True, additional_visible_people=shot.extras)
    return {
        'shot': shot.shot_id, 'seed': shot.seed, 'width': shot.width, 'height': shot.height,
        'frames': shot.frames, 'visuals': visuals, 'voices': voice_payload,
        'videos': video_payload,
        'spoken_lines': spoken_lines, 'additional_visible_people': list(shot.extras),
        'props': shot.props,
        'off_screen_voice': off_screen_only,
        'sections': sections,
    }
