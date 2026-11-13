#!/usr/bin/env python3
"""Render a cinematic project's FastH3 requests one shot at a time.

This is a thin batch wrapper around the OpenMontage ``fastvideo_h3_video``
tool. It does not build prompts, anchors or continuity itself: the project's
``assets/requests.json`` is the source of truth produced by the cinematic
pipeline. It renders into ``assets/shots_new`` first, then promotes a successful
take to ``assets/shots`` and ``public/shots`` so a failed retry never destroys
the last good shot.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'openmontage'))

from tools.tool_registry import registry  # noqa: E402


def log(message: str) -> None:
    print(time.strftime('%H:%M:%S'), message, flush=True)



def restart_service(unit: str) -> None:
    if not unit:
        return
    result = subprocess.run(['systemctl', '--user', 'restart', unit],
                            capture_output=True, text=True)
    if result.returncode != 0:
        log(f'WARN could not restart {unit}: {result.stderr.strip()[:200]}')
        return
    deadline = time.time() + 300
    while time.time() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:8195/health', timeout=3) as response:
                if response.status == 200:
                    log(f'FastVideo service ready ({unit})')
                    return
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError(f'FastVideo service {unit} did not become healthy')


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--shots', default='', help='comma-separated ids; default all')
    parser.add_argument('--force', action='store_true', help='re-render even if a good take exists')
    parser.add_argument('--retry', type=int, default=2)
    parser.add_argument('--restart-every', type=int, default=1,
                        help='restart the FastVideo unit every N successful shots (0 disables)')
    parser.add_argument('--service-unit', default='om-fastvideo')
    args = parser.parse_args()

    project = args.project.resolve()
    requests = load(project / 'assets/requests.json')
    wanted = [s.strip() for s in args.shots.split(',') if s.strip()] or sorted(requests)
    staged = project / 'assets/shots_new'
    jobs = project / 'assets/jobs'
    staged.mkdir(parents=True, exist_ok=True)
    jobs.mkdir(parents=True, exist_ok=True)

    registry.discover()
    tool = registry.get('fastvideo_h3_video')
    if tool is None:
        raise SystemExit('fastvideo_h3_video is not registered')
    manifest_path = project / 'assets/take_manifest.json'
    manifest = load(manifest_path) if manifest_path.is_file() else {}
    restart_service(args.service_unit)
    failure_path = project / 'assets/render_failures.json'
    failures = []

    for index, sid in enumerate(wanted, 1):
        request = dict(requests[sid])
        final_take = project / 'assets/shots' / f'{sid}.mp4'
        final_receipt = project / 'assets/shots' / f'{sid}.receipt.json'
        if final_take.is_file() and final_receipt.is_file() and not args.force:
            log(f'SKIP {sid} ({index}/{len(wanted)})')
            manifest.setdefault(sid, {})['status'] = 'ok'
            manifest[sid]['path'] = str(final_take)
            manifest[sid]['receipt'] = str(final_receipt)
            continue
        payload = dict(request)
        payload['output_path'] = str(staged / f'{sid}.mp4')
        payload['job_path'] = str(jobs / f'{sid}.json')
        payload.setdefault('timeout_seconds', 2700)
        began = time.time()
        result = None
        for attempt in range(1, args.retry + 2):
            log(f'RENDER {sid} ({index}/{len(wanted)}) attempt {attempt}')
            result = tool.execute(payload)
            if result.success and (staged / f'{sid}.mp4').is_file():
                break
            log(f'FAIL {sid}: {result.error}')
            time.sleep(10)
        if result is None or not result.success or not (staged / f'{sid}.mp4').is_file():
            failures.append({'shot': sid, 'error': getattr(result, 'error', 'no result')})
            dump(failure_path, failures)
            if args.service_unit:
                try:
                    restart_service(args.service_unit)
                except Exception as exc:
                    log(f'WARN restart after failure failed: {exc}')
            continue
        final_take.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged / f'{sid}.mp4', final_take)
        receipt = staged / f'{sid}.receipt.json'
        if receipt.is_file():
            shutil.copy2(receipt, final_receipt)
        public = project / 'public/shots' / f'{sid}.mp4'
        public.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(final_take, public)
        except shutil.SameFileError:
            pass
        data = dict(result.data or {})
        data['status'] = 'ok'
        data['path'] = str(final_take)
        data['receipt'] = str(final_receipt)
        data['elapsed_s'] = round(time.time() - began, 1)
        manifest[sid] = data
        dump(manifest_path, manifest)
        checkpoint = project / 'checkpoint_assets.json'
        if checkpoint.is_file():
            state = load(checkpoint)
            progress = (state.get('metadata') or {}).get('partial_progress') or {}
            progress.update({'phase': 'rendering', 'done': len([k for k, v in manifest.items() if v.get('status') == 'ok']),
                             'total': len(requests), 'current': sid,
                             'updated_at': time.time(), 'takes': manifest})
            state.setdefault('metadata', {})['partial_progress'] = progress
            dump(checkpoint, state)
        log(f'OK {sid} {data.get("elapsed_s", 0)}s -> {final_take}')
        if args.restart_every and index % args.restart_every == 0 and index < len(wanted):
            restart_service(args.service_unit)

    dump(manifest_path, manifest)
    dump(failure_path, failures)
    log(f'DONE ok={len([k for k, v in manifest.items() if v.get("status") == "ok"])}/{len(requests)} failures={len(failures)}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
