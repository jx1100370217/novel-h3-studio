#!/usr/bin/env python3
"""Batch strict-Ref2VA shots against the official FastVideo NVFP4 QAD service.

This is the multi-speaker companion to ``novel_h3.fastvideo.run`` for projects
that author shots directly as strict six-section Ref2VA specs instead of the
full narrative/cinematization chapter plan. It uses the same official
``novel_h3.ref2va`` validator and ``novel_h3.fastvideo.request_payload``
translation, then submits/polls/downloads through the service HTTP API.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .fastvideo import request_payload
from .ref2va import validate, with_population
from .safety import check_paused, check_power_cap

DEFAULT_API = 'http://127.0.0.1:8195'
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768


def frame_grid_valid(frames: int) -> bool:
    return isinstance(frames, int) and frames >= 5 and (frames - 5) % 17 == 0


def load_spec(path: Path) -> dict:
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    for key in ('shot', 'seed', 'frames', 'visuals', 'sections'):
        if key not in spec:
            raise ValueError(f'{path}: missing {key}')
    if not frame_grid_valid(int(spec['frames'])):
        raise ValueError(f"{path}: num_frames must be on the 17n+5 grid, got {spec['frames']}")
    return spec


def build_payload(root: Path, spec: dict, *, width: int | None = None, height: int | None = None) -> dict:
    root = Path(root).resolve()
    visuals = []
    for ref in spec['visuals']:
        ref = dict(ref)
        gp = Path(ref['generation_path'])
        ref['generation_path'] = str(gp.relative_to(root)) if gp.is_absolute() else str(gp)
        visuals.append(ref)
    voices = spec.get('voices', [])
    spoken = spec.get('spoken_lines', [])
    sections = spec['sections']
    prompt = '\n\n'.join(k + ':\n' + v.strip() for k, v in sections.items())
    prompt = with_population(prompt, visuals, spec.get('additional_visible_people', []))
    validate(prompt, visuals, voices, spoken, duration_seconds=spec['frames'] / 24,
             single_shot=True, no_music=True,
             additional_visible_people=spec.get('additional_visible_people', []),
             require_population=True)
    request = {
        'prompt': prompt,
        'visuals': visuals,
        'voices': voices,
        'shot': {'spoken_lines': spoken,
                 'additional_visible_people': spec.get('additional_visible_people', [])},
        'frames': int(spec['frames']),
        'generation': {'width': int(width or spec.get('width') or DEFAULT_WIDTH),
                       'height': int(height or spec.get('height') or DEFAULT_HEIGHT)},
        'seed': int(spec['seed']),
    }
    payload = request_payload(root, request)
    payload['_prompt_sha256'] = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    return payload


def _http_json(url: str, payload: dict | None = None, timeout: float = 180.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def run_shot(root: Path, project: Path, spec: dict, *, api: str, force: bool = False,
             width: int | None = None, height: int | None = None) -> dict:
    shot = spec['shot']
    outdir = project / 'takes' / shot
    outdir.mkdir(parents=True, exist_ok=True)
    native = outdir / 'native.mp4'
    receipt_path = outdir / 'receipt.json'
    payload = build_payload(root, spec, width=width, height=height)
    prompt = payload.pop('_prompt_sha256', None)
    expected = {'prompt_sha256': prompt, 'width': payload['width'], 'height': payload['height'],
                'frames': payload['num_frames'], 'seed': payload['seed']}
    if native.exists() and receipt_path.exists() and not force:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if all(receipt.get(key) == value for key, value in expected.items()):
            return receipt
        # Stale take from a different prompt/resolution/seed: keep it for audit
        # and render the current spec.
        rejected = outdir / 'rejected'
        rejected.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time())
        native.replace(rejected / f'native_{stamp}.mp4')
        receipt_path.replace(rejected / f'receipt_{stamp}.json')
    (outdir / 'prompt.txt').write_text(payload['prompt'], encoding='utf-8')
    (outdir / 'fastvideo_request.json').write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    if native.exists():
        native.unlink()
    started = time.time()
    try:
        job = _http_json(api.rstrip('/') + '/v1/videos', payload)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors='replace')
        (outdir / 'error.json').write_text(body, encoding='utf-8')
        raise RuntimeError(f'{shot}: submit HTTP {exc.code}: {body[:1500]}') from exc
    job_id = job['id']
    (outdir / 'job_id.txt').write_text(job_id, encoding='utf-8')
    deadline = time.monotonic() + 2400
    status = job
    while time.monotonic() < deadline:
        try:
            status = _http_json(api.rstrip('/') + '/v1/videos/' + job_id)
        except (TimeoutError, socket.timeout, urllib.error.URLError):
            time.sleep(5)
            continue
        if status.get('status') == 'completed':
            break
        if status.get('status') == 'failed':
            (outdir / 'error.json').write_text(
                json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
            raise RuntimeError(f"{shot}: generation failed: {status.get('error')}")
        time.sleep(5)
    else:
        raise TimeoutError(f'{shot}: timed out; job {job_id}')
    url = api.rstrip('/') + '/v1/videos/' + job_id + '/content'
    with urllib.request.urlopen(url, timeout=600) as source, native.open('wb') as target:
        shutil.copyfileobj(source, target)
    receipt = {
        'shot': shot, 'job_id': job_id, 'status': status.get('status'),
        'inference_time_s': status.get('inference_time_s'),
        'frames': int(spec['frames']), 'width': payload['width'], 'height': payload['height'],
        'seed': int(spec['seed']),
        'sha256': hashlib.sha256(native.read_bytes()).hexdigest(),
        'prompt_sha256': prompt,
        'wall_seconds': round(time.time() - started, 2),
    }
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=None,
                        help='repository root that contains the project (default: project parent parent)')
    parser.add_argument('--shots', default='')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--api', default=DEFAULT_API)
    parser.add_argument('--width', type=int, default=None)
    parser.add_argument('--height', type=int, default=None)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    root = (args.root or project.parents[1]).resolve()
    if args.all:
        paths = sorted((project / 'shots').glob('*.json'))
    else:
        paths = [project / 'shots' / f'{s.strip()}.json' for s in args.shots.split(',') if s.strip()]
    if not paths:
        parser.error('pass --shots A08,A13 or --all')
    check_power_cap(450)
    for path in paths:
        check_paused()
        spec = load_spec(path)
        receipt = run_shot(root, project, spec, api=args.api, force=args.force,
                           width=args.width, height=args.height)
        print(f"DONE {spec['shot']} {receipt.get('wall_seconds')}s "
              f"{receipt.get('width')}x{receipt.get('height')}", flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
