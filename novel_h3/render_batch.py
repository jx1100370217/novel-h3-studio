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
    env = os.environ.copy()
    env.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
    env.setdefault('TORCHINDUCTOR_CACHE_DIR', str(ROOT / 'runtime/torchinductor-cache'))
    with log_path.open('ab') as handle:
        subprocess.Popen(
            [str(ROOT / 'runtime/fastvideo-venv/bin/python'), str(ROOT / 'start_fastvideo.py'),
             '--project', str(service_project)],
            cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, env=env,
        )
    deadline = time.time() + 1200
    while time.time() < deadline:
        if health(DEFAULT_API):
            return
        time.sleep(2)
    raise TimeoutError('FastVideo service did not become healthy within 1200s')


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_live_asset(project: Path, board_media_dir: str, fastvideo_project: Path,
                    takes_subdir: str, shot: str) -> dict:
    """Copy a completed take into the board project with an in-project path.

    Backlot only serves media inside the project directory. A symlink to a
    sibling FastVideo project resolves outside and is rejected, so the board
    gets a lightweight copy / hardlink inside the project instead.
    """
    source = fastvideo_project / takes_subdir / shot / 'native.mp4'
    target = project / board_media_dir / f'{shot}.mp4'
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.is_file():
        raise FileNotFoundError(f'cannot publish live take, missing {source}')
    try:
        if target.exists():
            target.unlink()
        try:
            import os
            os.link(source, target)
        except OSError:
            import shutil
            shutil.copy2(source, target)
    except OSError:
        import shutil
        shutil.copy2(source, target)
    return {'path': f'{board_media_dir}/{shot}.mp4', 'sha256': _sha256(target),
            'size_bytes': target.stat().st_size, 'updated_at': time.time()}


def update_checkpoint(path: Path, done: int, total: int, current: str, phase: str,
                      extra: dict | None = None, *, live_assets: dict | None = None,
                      live_assets_active: bool = False, keep_manifest: list[str] | None = None,
                      event_name: str | None = None) -> None:
    partial = {'phase': phase, 'done': done, 'total': total, 'current': current,
               'updated_at': time.time()}
    if extra:
        partial.update(extra)
    metadata = {'partial_progress': partial,
                'live_assets_active': bool(live_assets_active),
                'live_assets': live_assets or {},
                'keep_manifest': list(keep_manifest or [])}
    checkpoint = {
        'version': '1.0', 'project_id': path.parent.name, 'pipeline_type': 'novel-cinematic',
        'stage': 'assets', 'status': 'in_progress',
        'timestamp': datetime.now(timezone.utc).isoformat(), 'artifacts': {},
        'metadata': metadata,
    }
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding='utf-8')
    event = {'ts': datetime.now(timezone.utc).isoformat(), 'tool': 'fastvideo_h3_video',
             'event': event_name or ('start' if phase == 'render' else phase),
             'scene_id': current or None, 'shot': current, 'done': done, 'total': total}
    with (path.parent / 'events.jsonl').open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')


def main(argv: list[str] | None = None) -> int:
    from .fastvideo_batch import load_spec, run_shot
    from .memory_guard import MemoryGuard, read_available_gb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True, help='OpenMontage project that owns the checkpoint.')
    parser.add_argument('--fastvideo-project', type=Path, required=True)
    parser.add_argument('--specs-dir', type=Path, default=None)
    parser.add_argument('--takes-subdir', default='takes')
    parser.add_argument('--service-project', type=Path, default=None,
                        help='Project config for the FastVideo service; defaults to --fastvideo-project.')
    parser.add_argument('--shots', default='')
    parser.add_argument('--restart-every', type=int, default=1)
    parser.add_argument('--retry', type=int, default=1,
                        help='Re-run a failed shot this many times after restarting the service.')
    parser.add_argument('--min-available-gb', type=float, default=6.0,
                        help='Wait for this much free host memory before submitting a take.')
    parser.add_argument('--abort-available-gb', type=float, default=0.6,
                        help='Abort a take (and stop the service) below this much free memory.')
    parser.add_argument('--abort-pressure', type=float, default=60.0,
                        help='Abort a take when memory PSI avg10 stays above this percent.')
    parser.add_argument('--api', default=DEFAULT_API)
    parser.add_argument('--width', type=int, default=1344)
    parser.add_argument('--height', type=int, default=768)
    parser.add_argument('--total', type=int, default=0)
    parser.add_argument('--base-done', type=int, default=0)
    parser.add_argument('--checkpoint', type=Path, default=None)
    parser.add_argument('--failure-file', type=Path, default=None)
    parser.add_argument('--service-log', type=Path, default=ROOT / 'runtime/render_service.log')
    parser.add_argument('--board-media-dir', default='', help='Project-relative media dir Backlot can serve; copies each completed take there.')
    parser.add_argument('--board-keep-manifest', default='A01,A16,A45', help='Scene ids that keep the previous graphic from asset_manifest.')
    args = parser.parse_args(argv)
    project = args.project.resolve()
    fastvideo_project = args.fastvideo_project.resolve()
    specs_dir = (args.specs_dir or fastvideo_project / 'shots').resolve()
    checkpoint = (args.checkpoint or project / 'checkpoint_assets.json').resolve()
    failure_file = (args.failure_file or project / 'render_failures.json').resolve()
    board_active = bool(args.board_media_dir)
    keep_manifest = [x.strip() for x in args.board_keep_manifest.split(',') if x.strip()]
    live_assets: dict = {}
    if board_active and checkpoint.is_file():
        try:
            old = json.loads(checkpoint.read_text(encoding='utf-8'))
            live_assets = dict(((old.get('metadata') or {}).get('live_assets') or {}))
        except Exception:
            live_assets = {}
    specs = sorted(specs_dir.glob('*.json'))
    if args.shots:
        wanted = {s.strip() for s in args.shots.split(',') if s.strip()}
        specs = [p for p in specs if p.stem in wanted]
    if not specs:
        parser.error('no shot specs found')
    total = args.total or len(specs)
    guard = MemoryGuard(min_available_gb=args.abort_available_gb,
                        max_pressure_avg10=args.abort_pressure)
    failures, rendered = [], args.base_done
    for index, path in enumerate(specs, 1):
        spec = load_spec(path)
        sid = spec['shot']
        update_checkpoint(checkpoint, rendered, total, sid, 'render', live_assets=live_assets,
                          live_assets_active=board_active, keep_manifest=keep_manifest,
                          event_name='start')
        receipt = None
        for attempt in range(1, max(0, args.retry) + 2):
            if not health(args.api):
                start_service((args.service_project or fastvideo_project).resolve(), args.service_log)
            if not guard.wait_for_headroom(args.min_available_gb):
                print(f'{sid} SKIPPED: only {read_available_gb():.1f} GiB available', flush=True)
                failures.append({'shot': sid, 'error': 'insufficient host memory before submit'})
                update_checkpoint(checkpoint, rendered, total, sid, 'render',
                                  {'error': 'insufficient host memory'}, live_assets=live_assets,
                                  live_assets_active=board_active, keep_manifest=keep_manifest,
                                  event_name='error')
                break
            try:
                with MemoryGuard(min_available_gb=args.abort_available_gb,
                                 max_pressure_avg10=args.abort_pressure,
                                 on_abort=stop_service):
                    receipt = run_shot(ROOT, fastvideo_project, spec, api=args.api,
                                       width=args.width, height=args.height,
                                       takes_subdir=args.takes_subdir)
                break
            except Exception as exc:  # noqa: BLE001
                if attempt <= args.retry:
                    # Host-memory OOM and provider hickups are transient; a
                    # fresh service plus one retry is cheaper than a re-plan.
                    print(f'RETRY {sid} ({attempt}/{args.retry}): {exc}', flush=True)
                    stop_service()
                    continue
                failures.append({'shot': sid, 'error': str(exc), 'attempts': attempt})
                update_checkpoint(checkpoint, rendered, total, sid, 'render', {'error': str(exc)},
                                  live_assets=live_assets, live_assets_active=board_active,
                                  keep_manifest=keep_manifest, event_name='error')
                print(f'[{index}/{total}] {sid} FAILED: {exc}', flush=True)
        if receipt is not None:
            rendered += 1
            if board_active:
                try:
                    live_assets[sid] = copy_live_asset(project, args.board_media_dir, fastvideo_project,
                                                       args.takes_subdir, sid)
                except Exception as exc:  # board copy must not fail the render
                    print(f'BOARD COPY WARNING {sid}: {exc}', flush=True)
            update_checkpoint(checkpoint, rendered, total, sid, 'render', {
                'inference_time_s': receipt.get('inference_time_s'), 'sha256': receipt.get('sha256')},
                live_assets=live_assets, live_assets_active=board_active, keep_manifest=keep_manifest,
                event_name='finish')
            print(f'[{index}/{total}] {sid} {receipt.get("inference_time_s")}s', flush=True)
        if args.restart_every and index % args.restart_every == 0 and index < total:
            stop_service()
    if args.restart_every:
        stop_service()
    failure_file.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding='utf-8')
    update_checkpoint(checkpoint, rendered, total, '', 'render_done', {'failures': len(failures)},
                      live_assets=live_assets, live_assets_active=board_active,
                      keep_manifest=keep_manifest, event_name='finish')
    print(f'RENDER DONE {rendered}/{total} failures={len(failures)}', flush=True)
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
