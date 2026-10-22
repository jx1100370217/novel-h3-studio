#!/usr/bin/env python3
"""Render the v4 strict-Ref2VA shot list with live Backlot progress.

The driver uses the official novel_h3.fastvideo_batch runner, writes an
OpenMontage in-progress assets checkpoint after every shot, and restarts the
FastVideo service between heavy shots so its host-memory working set cannot
accumulate. It never touches the archived old workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DEFAULT_API = 'http://127.0.0.1:8195'
DEFAULT_PROJECT = ROOT / 'projects/liaozhai-kaochenghuang'
DEFAULT_FASTVIDEO_PROJECT = ROOT / 'projects/liaozhai-kaochenghuang-fastvideo'
DEFAULT_SERVICE_PROJECT = ROOT / 'projects/liaozhai-zhiyi-video-comparison'


def _health(api: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(api.rstrip('/') + '/health', timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def _service_pids() -> list[int]:
    out = subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        if 'fastvideo serve --config' in line:
            pids.append(int(line.strip().split()[0]))
    return pids


def stop_service() -> None:
    for pid in _service_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(5)


def start_service(service_project: Path) -> None:
    log = ROOT / 'runtime' / 'v4_fastvideo_service.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('ab') as handle:
        subprocess.Popen(
            [str(ROOT / 'runtime/fastvideo-venv/bin/python'), str(ROOT / 'start_fastvideo.py'),
             '--project', str(service_project)],
            cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    deadline = time.time() + 240
    while time.time() < deadline:
        if _health(DEFAULT_API):
            return
        time.sleep(2)
    raise TimeoutError('FastVideo service did not become healthy within 240s')


def update_checkpoint(project: Path, done: int, total: int, current: str, phase: str, extra: dict | None = None) -> None:
    partial = {'phase': phase, 'done': done, 'total': total, 'current': current, 'updated_at': time.time()}
    if extra:
        partial.update(extra)
    checkpoint = {
        'version': '1.0',
        'project_id': project.name,
        'pipeline_type': 'novel-cinematic',
        'stage': 'assets',
        'status': 'in_progress',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'artifacts': {},
        'metadata': {'partial_progress': partial},
    }
    (project / 'checkpoint_assets.json').write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
    event = {'ts': datetime.now(timezone.utc).isoformat(), 'tool': 'fastvideo_h3_video',
             'event': phase, 'shot': current, 'done': done, 'total': total}
    with (project / 'events.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')


def main() -> int:
    from novel_h3.fastvideo_batch import load_spec, run_shot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=DEFAULT_PROJECT)
    parser.add_argument('--fastvideo-project', type=Path, default=DEFAULT_FASTVIDEO_PROJECT)
    parser.add_argument('--service-project', type=Path, default=DEFAULT_SERVICE_PROJECT)
    parser.add_argument('--shots', default='')
    parser.add_argument('--restart-every', type=int, default=1,
                        help='restart the FastVideo service after this many shots (0 = never)')
    parser.add_argument('--api', default=DEFAULT_API)
    parser.add_argument('--width', type=int, default=1344)
    parser.add_argument('--height', type=int, default=768)
    parser.add_argument('--total', type=int, default=0, help='override total for a retry batch')
    parser.add_argument('--base-done', type=int, default=0, help='completed count before this retry batch')
    args = parser.parse_args()
    project = args.project.resolve()
    fastvideo_project = args.fastvideo_project.resolve()
    service_project = args.service_project.resolve()
    specs_dir = fastvideo_project / 'shots'
    specs = sorted(specs_dir.glob('*.json'))
    if args.shots:
        wanted = {s.strip() for s in args.shots.split(',') if s.strip()}
        specs = [p for p in specs if p.stem in wanted]
    if not specs:
        parser.error('no shot specs found')
    total = args.total or len(specs)
    failures = []
    rendered = args.base_done
    for index, path in enumerate(specs, 1):
        spec = load_spec(path)
        sid = spec['shot']
        update_checkpoint(project, rendered, total, sid, 'render', {'phase': 'render'})
        if not _health(args.api):
            start_service(service_project)
        try:
            receipt = run_shot(ROOT, fastvideo_project, spec, api=args.api,
                               width=args.width, height=args.height)
            rendered += 1
            update_checkpoint(project, rendered, total, sid, 'render', {
                'inference_time_s': receipt.get('inference_time_s'),
                'sha256': receipt.get('sha256'),
            })
            print(f'[{index}/{total}] {sid} {receipt.get("inference_time_s")}s', flush=True)
        except Exception as exc:  # noqa: BLE001
            failures.append({'shot': sid, 'error': str(exc)})
            print(f'[{index}/{total}] {sid} FAILED: {exc}', flush=True)
        if args.restart_every and index % args.restart_every == 0 and index < total:
            stop_service()
    if args.restart_every:
        stop_service()
    (project / 'v4_render_failures.json').write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    update_checkpoint(project, rendered, total, '', 'render_done', {'failures': len(failures)})
    print(f'RENDER DONE {rendered}/{total} failures={len(failures)}', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
