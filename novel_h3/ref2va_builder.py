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

from .ref2va import SECTIONS, render
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
    strong_no_text: bool = False
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


def build_spec(shot: LockedShot) -> dict:
    """Build and officially validate one locked Ref2VA shot spec."""
    subject: dict[str, str] = {}
    visuals: list[dict] = []
    defs: list[str] = []
    retention: list[str] = []
    for i, item in enumerate(shot.cast, 1):
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
    scene_label = f'<Subject {len(shot.cast) + 1}>'
    scene_picture = f'<Picture {len(shot.cast) + 1}>'
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
        previs_label = f'<Subject {len(shot.cast) + 2}>'
        previs_picture = f'<Picture {len(shot.cast) + 2}>'
        count = sum(item.instances for item in shot.cast if item.kind == 'character') + len(shot.extras)
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
        index = len(shot.cast) + (3 if shot.previs_path else 2)
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

    lines = sorted(shot.lines, key=lambda item: item.offset)
    by_role = {voice.role: voice for voice in shot.voices}
    speaker_order = list(dict.fromkeys(line.speaker for line in lines))
    for role in speaker_order:
        if role not in by_role:
            raise ValueError(f'{shot.shot_id}: speaker {role!r} has no voice reference')
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
            voice_defs.append(
                f'{audio} is the voice reference for {role_subject[role]} (S{i}), '
                f'{next(item.name for item in shot.cast if item.asset_id == binding.subject_asset)}; '
                f'preserve this exact timbre only for {next(item.name for item in shot.cast if item.asset_id == binding.subject_asset)} and never for another character.'
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
              'or audio. '
            + detail
        )
    if shot.open_state:
        detail = shot.open_state + ' ' + detail
    if shot.close_state:
        detail = detail.rstrip() + ' ' + shot.close_state
    count = sum(item.instances for item in shot.cast if item.kind == 'character') + len(shot.extras)
    if shot.blocking:
        blocking = 'Blocking lock: ' + shot.blocking
    else:
        blocking = f'Blocking lock: exactly {_people(count)}. {_positions(shot.cast, shot.extras)}. ' \
                   f'No other people, no duplicates, no reflections, no background extras.'
    if previs_label and not shot.blocking:
        blocking = (f'Blocking lock: the grayscale guide {previs_label} shows exactly {_people(count)}. '
                    f'{_positions(shot.cast, shot.extras)}. No other people, no duplicates, no reflections, '
                    f'no background extras. The guide is a reference diagram only; do not reproduce its gray '
                    f'mannequin materials or studio light.')
    elif previs_label and shot.blocking:
        blocking += (f' The grayscale guide {previs_label} shows exactly {_people(count)}; use only its body '
                     f'count, placement, poses and camera, never its gray materials or mannequin appearance.')
    detail += ' ' + blocking
    detail += (' Instance lock: every named person is exactly one physical body. A close-up face and a '
               'full-body or seated view of the same person are one person, never two. Do not add a second '
               'copy in the background, doorway, reflection, portrait, statue, silhouette, as a servant, '
               'guard, candidate, neighbor or any other unlisted person.')
    if shot.framing:
        detail += ' Framing lock: ' + shot.framing
    detail += ' Reference bindings: ' + ' '.join(item['subject'] for item in visuals) + '.'
    if speaker_order:
        locks = []
        for role in speaker_order:
            audio = role_audio[role]
            if role_subject[role]:
                name = next(item.name for item in shot.cast if item.asset_id == by_role[role].subject_asset)
                locks.append(f'{name} uses {audio} only')
            else:
                locks.append(f'the off-screen {role} uses {audio}')
        detail += (' Voice casting is locked: ' + '; '.join(locks) + '. Each line belongs only to the named '
                   'speaker; never swap voices, never let one character speak another character\'s line, and '
                   'match the moving lips to the named speaker.')
        for line in lines:
            sid = speaker_order.index(line.speaker) + 1
            audio = role_audio[line.speaker]
            label = role_subject[line.speaker]
            speaker = f'{label} (S{sid})' if label else f'the off-screen {line.speaker} (S{sid})'
            mm = int(line.offset // 60); ss = int(line.offset % 60)
            ms = int(round((line.offset - int(line.offset)) * 1000))
            detail += f' At {mm:02d}:{ss:02d}.{ms:03d}, {speaker} speaks with {audio}, <d>[Chinese] {line.text}</d>'
            if shot.strong_no_text:
                detail += ' The line is heard only and is never written on screen.'
    detail += ' No subtitles, no captions, no on-screen text, no text overlays.'

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
        'overall_soundscape': shot.soundscape,
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
        'sections': sections,
    }
