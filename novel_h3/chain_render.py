"""Sequential first-frame chain for one production round.

Shot by shot: build the keyframe (ChatGPT images 2.5), render the take with
FastH3-Omni (Ref2VA, keyframe as the first frame), then keep the take's final
frame for the next shot. Progress goes to the same checkpoint and events file
that the Backlot board reads.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from . import first_frame as ff

ROOT = ff.ROOT
DEFAULT_ROUND = ROOT / 'projects/liaozhai-wangliulang/v1'
PROJECT = ROOT / 'projects/liaozhai-wangliulang'


def _load(round_dir: Path) -> tuple[dict, dict]:
    authoring = json.loads((round_dir / 'authoring/authoring.json').read_text(encoding='utf-8'))
    plan = json.loads((round_dir / 'artifacts/scene_plan.json').read_text(encoding='utf-8'))
    return authoring, {scene['id']: scene for scene in plan['scenes']}


def _mad(a: Image.Image, b: Image.Image) -> float:
    size = (160, 90)
    diff = ImageChops.difference(a.convert('L').resize(size), b.convert('L').resize(size))
    return ImageStat.Stat(diff).mean[0]


def build_keyframe(round_dir: Path, authoring: dict, plan_by: dict, sid: str,
                   mode: str, prev: str | None) -> None:
    shot = authoring['shots'][sid]
    characters = authoring['characters']
    keyframe = round_dir / 'anchor_frames' / f'{sid}.png'
    keyframe.parent.mkdir(parents=True, exist_ok=True)
    open_cast = shot.get('open_cast', shot['cast'])
    people = [(characters[c]['name'], characters[c]['definition']) for c in open_cast]
    size_en = ff.SIZE_EN.get(plan_by[sid]['shot_language']['shot_size'], 'medium shot')
    light = ff.LIGHT_EN.get(plan_by[sid].get('time_of_day', ''), 'period natural light')
    cast_refs = [Path(characters[c]['image_path']) for c in open_cast]
    prompt = ''
    refs: list[Path] = []
    if mode == 'copy':
        shutil.copy2(round_dir / 'last_frames' / f'{prev}.png', keyframe)
    elif mode == 'start':
        scene = authoring['scenes'][shot['scene']]
        refs = cast_refs + [Path(scene['image_path'])]
        prompt = ff.start_prompt(shot, people, size_en, light, ff.scene_text(scene['definition']))
        ff.codex_image(prompt, refs, keyframe)
    else:
        refs = [round_dir / 'last_frames' / f'{prev}.png'] + cast_refs
        prompt = ff.reframe_prompt(shot, people, size_en, light)
        ff.codex_image(prompt, refs, keyframe)
    keyframe.with_suffix('.keyframe.json').write_text(json.dumps({
        'shot': sid, 'mode': mode, 'previous': prev, 'open_cast': open_cast,
        'refs': [str(path) for path in refs[:ff.MAX_REFS]], 'prompt': prompt,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def render_shot(round_dir: Path, sid: str, done: int, total: int) -> None:
    cmd = [str(ff.PYTHON), '-m', 'novel_h3.render_batch',
           '--project', str(round_dir), '--fastvideo-project', str(round_dir),
           '--specs-dir', str(round_dir / 'specs'), '--takes-subdir', 'takes',
           '--shots', sid, '--total', str(total), '--base-done', str(done),
           '--restart-every', '1', '--retry', '1',
           '--service-project', str(PROJECT),
           '--service-log', str(ROOT / 'runtime/v1_chain_service.log'),
           '--failure-file', str(round_dir / 'chain_failures.json')]
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    with (ROOT / 'runtime/v1_chain_render.log').open('a', encoding='utf-8') as log:
        code = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    if code != 0 or not (round_dir / 'takes' / sid / 'native.mp4').is_file():
        raise RuntimeError(f'render failed for {sid} (exit {code})')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=Path, default=DEFAULT_ROUND)
    parser.add_argument('--start', default='', help='first shot id; default is the first shot of the round')
    parser.add_argument('--dry-run', action='store_true', help='print the chain plan and exit')
    args = parser.parse_args(argv)

    round_dir = args.round.resolve()
    authoring, plan_by = _load(round_dir)
    order = authoring['shot_order']
    modes = ff.shot_modes(authoring, plan_by)
    if args.dry_run:
        for sid in order:
            mode, prev = modes[sid]
            cast = authoring['shots'][sid].get('open_cast', authoring['shots'][sid]['cast'])
            print(f"{sid:<5} {mode:<8} {prev or '-':<5} {','.join(cast) or '-':<16} "
                  f"{plan_by[sid]['shot_language']['shot_size']}")
        return 0

    start = order.index(args.start) if args.start else 0
    (round_dir / 'last_frames').mkdir(exist_ok=True)
    total = len(order)
    for index, sid in enumerate(order):
        if index < start:
            continue
        mode, prev = modes[sid]
        began = time.time()
        build_keyframe(round_dir, authoring, plan_by, sid, mode, prev)
        render_shot(round_dir, sid, index, total)
        take = round_dir / 'takes' / sid / 'native.mp4'
        ff.last_frame(take, round_dir / 'last_frames' / f'{sid}.png')
        cut = None
        if prev:
            before = Image.open(round_dir / 'last_frames' / f'{prev}.png').convert('RGB')
            first = round_dir / 'last_frames' / f'{sid}.first.png'
            ff.first_frame(take, first)
            cut = _mad(before, Image.open(first).convert('RGB'))
        cut_text = '-' if cut is None else f'{cut:.1f}'
        print(f"[{index + 1}/{total}] {sid} {mode}{'(' + prev + ')' if prev else ''} "
              f"cut={cut_text} {time.time() - began:.0f}s", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
