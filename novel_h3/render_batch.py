"""Global FastVideo shot-batch driver with checkpoint progress and restarts.

Any project can use this instead of copying a per-version render script:
  python -m novel_h3.render_batch --project projects/<id> \
      --fastvideo-project projects/<id>-fastvideo \
      --specs-dir projects/<id>-fastvideo/shots_v5 \
      --takes-subdir takes_v5 --shots A13,A18 --restart-every 1
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_API = 'http://127.0.0.1:8195'
DEFAULT_SERVICE_PROJECT = ROOT / 'projects/liaozhai-zhiyi-video-comparison'


def health(api: str, timeout: float = 3.0) -> bool:
    try:
        with urllib.request.urlopen(api.rstrip('/') + '/health', timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


def service_pids() -> list[int]:
    out = subprocess.run(['ps', '-eo', 'pid,args'], capture_output=True, text=True).stdout
    return [int(line.split()[0]) for line in out.splitlines() if 'fastvideo serve --config' in line]


def stop_service() -> None:
    for pid in service_pids():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(5)


def start_service(service_project: Path, log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('ab') as handle:
        subprocess.Popen(
            [str(ROOT / 'runtime/fastvideo-venv/bin/python'), str(ROOT / 'start_fastvideo.py'),
             '--project', str(service_project)],
            cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    deadline = time.time() + 240
    while time.time() < deadline:
        if health(DEFAULT_API):
            return
        time.sleep(2)
    raise TimeoutError('FastVideo service did not become healthy within 240s')


def update_checkpoint(path: Path, done: int, total: int, current: str, phase: str,
                      extra: dict | None = None) -> None:
    partial = {'phase': phase, 'done': done, 'total': total, 'current': current,
               'updated_at': time.time()}
    if extra:
        partial.update(extra)
    checkpoint = {
        'version': '1.0', 'project_id': path.parent.name, 'pipeline_type': 'novel-cinematic',
        'stage': 'assets', 'status': 'in_progress',
        'timestamp': datetime.now(timezone.utc).isoformat(), 'artifacts': {},
        'metadata': {'partial_progress': partial},
    }
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
    event = {'ts': datetime.now(timezone.utc).isoformat(), 'tool': 'fastvideo_h3_video',
             'event': phase, 'shot': current, 'done': done, 'total': total}
    with (path.parent / 'events.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')


def main(argv: list[str] | None = None) -> int:
    from .fastvideo_batch import load_spec, run_shot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='OpenMontage project that owns the checkpoint.')
    parser.add_argument('--fastvideo-project', type=Path, required=True)
    parser.add_argument('--specs-dir', type=Path, default=None)
    parser.add_argument('--takes-subdir', default='takes')
    parser.add_argument('--service-project', type=Path, default=DEFAULT_SERVICE_PROJECT)
    parser.add_argument('--shots', default='')
    parser.add_argument('--restart-every', type=int, default=1)
    parser.add_argument('--api', default=DEFAULT_API)
    parser.add_argument('--width', type=int, default=1344)
    parser.add_argument('--height', type=int, default=768)
    parser.add_argument('--total', type=int, default=0)
    parser.add_argument('--base-done', type=int, default=0)
    parser.add_argument('--checkpoint', type=Path, default=None)
    parser.add_argument('--failure-file', type=Path, default=None)
    parser.add_argument('--service-log', type=Path, default=ROOT / 'runtime/render_service.log')
    args = parser.parse_args(argv)
    project = args.project.resolve()
    fastvideo_project = args.fastvideo_project.resolve()
    specs_dir = (args.specs_dir or fastvideo_project / 'shots').resolve()
    checkpoint = (args.checkpoint or project / 'checkpoint_assets.json').resolve()
    failure_file = (args.failure_file or project / 'render_failures.json').resolve()
    specs = sorted(specs_dir.glob('*.json'))
    if args.shots:
        wanted = {s.strip() for s in args.shots.split(',') if s.strip()}
        specs = [p for p in specs if p.stem in wanted]
    if not specs:
        parser.error('no shot specs found')
    total = args.total or len(specs)
    failures, rendered = [], args.base_done
    for index, path in enumerate(specs, 1):
        spec = load_spec(path)
        sid = spec['shot']
        update_checkpoint(checkpoint, rendered, total, sid, 'render')
        if not health(args.api):
            start_service(args.service_project.resolve(), args.service_log)
        try:
            receipt = run_shot(ROOT, fastvideo_project, spec, api=args.api,
                               width=args.width, height=args.height,
                               takes_subdir=args.takes_subdir)
            rendered += 1
            update_checkpoint(checkpoint, rendered, total, sid, 'render', {
                'inference_time_s': receipt.get('inference_time_s'), 'sha256': receipt.get('sha256')})
            print(f'[{index}/{total}] {sid} {receipt.get("inference_time_s")}s', flush=True)
        except Exception as exc:  # noqa: BLE001
            failures.append({'shot': sid, 'error': str(exc)})
            print(f'[{index}/{total}] {sid} FAILED: {exc}', flush=True)
        if args.restart_every and index % args.restart_every == 0 and index < total:
            stop_service()
    if args.restart_every:
        stop_service()
    failure_file.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    update_checkpoint(checkpoint, rendered, total, '', 'render_done', {'failures': len(failures)})
    print(f'RENDER DONE {rendered}/{total} failures={len(failures)}', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
