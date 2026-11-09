"""First-frame keyframes for Ref2VA shots.

Every keyframe is generated with ChatGPT images 2.5 through the Codex
subscription (the ``codex_image`` tool). A continuation keyframe starts from
the previous take's real final frame, so the cut keeps the same people, props,
costumes and light; only the camera framing follows the approved plan.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-openmontage' / 'bin' / 'python'
PROXY = 'http://127.0.0.1:7897'
CANVAS = (1344, 768)
IMAGE_MODEL = 'gpt-6-luna'  # Codex model whose built-in image tool returns gpt-image-2.5
MAX_REFS = 4

SIZE_EN = {
    'wide': 'wide shot',
    'medium_wide': 'medium wide shot',
    'medium': 'medium shot',
    'medium_close': 'medium close-up',
    'close_up': 'close-up',
    'insert': 'insert close-up',
    'extreme_close': 'extreme close-up',
}
LIGHT_EN = {
    '夜': 'low-key moonlight and warm lantern light',
    '正午': 'flat overcast noon light',
    '白日': 'soft daylight',
    '白日到夜': 'late afternoon turning to dusk',
    '白日到傍晚': 'late afternoon light',
    '清晨': 'cold dawn light',
    '黄昏': 'dusk light',
}
GENERIC_OPEN = re.compile(r'is in the opening position\.$')


def scene_text(definition: str) -> str:
    for cut in ('; no boat', '; no people', '; the shot supplies'):
        definition = definition.split(cut)[0]
    return definition.strip()


def opening_text(shot: dict) -> str:
    text = (shot.get('open') or '').strip()
    if not text or GENERIC_OPEN.search(text):
        return shot['visual_override']
    return text


def cast_sentence(people: list[tuple[str, str]]) -> str:
    if not people:
        return 'No people in the frame.'
    listed = '; '.join(f'{name} ({definition})' for name, definition in people)
    return (f'The visible cast is exactly {len(people)} people: {listed}. '
            'No other people, no duplicate person, no background figures, no reflections or portraits of people.')


def start_prompt(shot: dict, people: list[tuple[str, str]], size_en: str, light: str, scene: str) -> str:
    framing = shot.get('open_framing') or shot['framing']
    return (f'Photorealistic Chinese period film still, 16:9, {size_en}, {framing}. {scene}. '
            f'The first frame of the shot: {opening_text(shot)} {cast_sentence(people)} '
            f'Set and props: {shot["props"]}. Cinematic 35mm film, {light}, natural skin texture, '
            'restrained period drama, clean frame, no text, no subtitles, no watermark, no logo, no modern objects.')


def reframe_prompt(shot: dict, people: list[tuple[str, str]], size_en: str, light: str) -> str:
    framing = shot.get('open_framing') or shot['framing']
    return (f'Photorealistic Chinese period film still, 16:9, {size_en}, same continuous scene, {light}. '
            'Reference image 1 is the exact final frame of the previous shot. Use it as the state of the same moment: '
            'keep identical faces, hair, beards, costumes and colours of every person in it, the same props, boat, '
            'lantern, reeds and river, and the same positions of the people relative to the boat and bank. '
            f'Only the camera changes: {framing}. The first frame of the next shot: {opening_text(shot)} '
            f'{cast_sentence(people)} Set and props: {shot["props"]}. '
            'Cinematic 35mm film, natural skin texture, restrained period drama, clean frame, no text, no subtitles, '
            'no watermark, no logo.')


def shot_modes(authoring: dict, plan_by: dict) -> dict[str, tuple[str, str | None]]:
    """Return ``{shot: (mode, previous_shot)}`` with mode ``start``, ``copy`` or ``reframe``.

    ``start``: a new scene, a new section, or people entering or leaving the
    frame; the keyframe comes from the cast and scene references alone.
    ``copy``: same people and same shot size as the previous shot; the previous
    final frame is the keyframe, so the cut is frame-matched.
    ``reframe``: same people, new framing; the previous final frame is the
    state reference for a new keyframe.
    """
    modes: dict[str, tuple[str, str | None]] = {}
    previous = None
    for sid in authoring['shot_order']:
        shot = authoring['shots'][sid]
        section = sid[:3]
        if previous is None or previous['section'] != section or previous['scene'] != shot['scene']:
            modes[sid] = ('start', None)
        else:
            prev_cast = set(previous['cast'])
            open_cast = set(shot.get('open_cast', shot['cast']))
            if not prev_cast or not open_cast or prev_cast != open_cast:
                modes[sid] = ('start', None)
            else:
                same_size = (plan_by[previous['id']]['shot_language']['shot_size']
                             == plan_by[sid]['shot_language']['shot_size'])
                mode = 'copy' if same_size and open_cast == prev_cast else 'reframe'
                modes[sid] = (mode, previous['id'])
        previous = {'id': sid, 'section': section, 'scene': shot['scene'], 'cast': shot['cast']}
    return modes


def _proxy_ready() -> bool:
    for _ in range(10):
        result = subprocess.run(
            ['curl', '-sS', '-o', '/dev/null', '-x', PROXY, '--max-time', '20', 'https://chatgpt.com/'],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True
        time.sleep(15)
    return False


def normalise(path: Path) -> None:
    with Image.open(path) as opened:
        image = opened.convert('RGB')
    if image.size != CANVAS:
        image = image.resize(CANVAS, Image.LANCZOS)
    image.save(path)


def codex_image(prompt: str, refs: list[Path], out: Path, attempts: int = 3) -> None:
    """Generate one keyframe with ChatGPT images 2.5 and write it at 1344x768."""
    if not _proxy_ready():
        raise RuntimeError('chatgpt.com is not reachable through the local proxy; keyframes cannot be generated')
    out.parent.mkdir(parents=True, exist_ok=True)
    request = out.with_suffix('.request.json')
    request.write_text(json.dumps({
        'prompt': prompt,
        'output_path': str(out),
        'reference_paths': [str(path) for path in refs[:MAX_REFS]],
        'timeout_seconds': 900,
        'model': IMAGE_MODEL,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    env = dict(os.environ, HTTPS_PROXY=PROXY, HTTP_PROXY=PROXY, ALL_PROXY=PROXY)
    error = ''
    for _ in range(attempts):
        out.unlink(missing_ok=True)
        result = subprocess.run(
            [str(PYTHON), str(ROOT / 'studio.py'), 'tool', 'codex_image', f'@{request}'],
            capture_output=True, text=True, cwd=ROOT, env=env, timeout=1200,
        )
        if out.is_file():
            normalise(out)
            return
        error = (result.stdout + result.stderr)[-600:]
        time.sleep(60)
    raise RuntimeError(f'codex_image failed for {out.name} after {attempts} attempts: {error}')


def _duration(take: Path) -> float:
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                          '-of', 'default=nw=1:nk=1', str(take)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def last_frame(take: Path, out: Path) -> None:
    """Write the final decoded frame of a take. The seek stays inside the last frame."""
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    '-ss', f'{_duration(take) - 0.06:.3f}', '-i', str(take),
                    '-frames:v', '1', str(out)], check=True)
    normalise(out)


def first_frame(take: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', '0',
                    '-i', str(take), '-frames:v', '1', str(out)], check=True)
    normalise(out)
