"""Keep the sequential first-frame chain alive across transient stops.

The chain is intentionally sequential: each shot's keyframe comes from the
previous take's last frame. A proxy hiccup, a killed desktop session or a
single-shot test must not lose the round. This watchdog waits while a chain
process is already alive, then resumes ``chain_render`` at the first
unfinished shot recorded in the round checkpoint. It never runs two chains at
once and stops after repeated resumes without progress.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .spec_audit import audit_spec

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-openmontage' / 'bin' / 'python'
DEFAULT_ROUND = ROOT / 'projects/liaozhai-wangliulang/v1'


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    print(f'{stamp} {message}', flush=True)


def active_pids(round_dir: Path) -> list[int]:
    """Return chain or render processes already working on this round."""
    wanted = str(round_dir)
    out = subprocess.run(['ps', '-eo', 'pid,stat,args'], capture_output=True, text=True).stdout
    pids: list[int] = []
    for line in out.splitlines()[1:]:
        pid, stat, args = line.strip().split(None, 2)
        if stat.startswith('Z'):
            continue
        if '-m novel_h3.chain_render' in args:
            # chain_render defaults to this project; an explicit --round must match.
            if '--round' in args and wanted not in args:
                continue
            if '--round' not in args and str(DEFAULT_ROUND) != wanted:
                continue
            pids.append(int(pid))
        elif '-m novel_h3.render_batch' in args and wanted in args:
            pids.append(int(pid))
    return pids


def load_order(round_dir: Path) -> list[str]:
    authoring = json.loads((round_dir / 'authoring/authoring.json').read_text(encoding='utf-8'))
    return [str(item) for item in authoring['shot_order']]


def read_progress(round_dir: Path) -> tuple[int, str]:
    checkpoint = round_dir / 'checkpoint_assets.json'
    if not checkpoint.is_file():
        return 0, ''
    data = json.loads(checkpoint.read_text(encoding='utf-8'))
    progress = (data.get('metadata') or {}).get('partial_progress') or {}
    return int(progress.get('done') or 0), str(progress.get('current') or '')


def next_shot(done: int, current: str, order: list[str]) -> str | None:
    """First unfinished shot.

    ``done`` counts finished takes. A checkpoint written at the start of a
    take has ``done == index`` and ``current`` equal to that take; a
    checkpoint written at the finish has ``done == index + 1``.
    """
    if current in order:
        index = order.index(current)
        if done <= index:
            return current
    if done < len(order):
        return order[done]
    return None


def audit_next(round_dir: Path, sid: str) -> list[str]:
    spec_path = round_dir / 'specs' / f'{sid}.json'
    if not spec_path.is_file():
        return [f'missing spec {spec_path}']
    return audit_spec(json.loads(spec_path.read_text(encoding='utf-8')))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--round', type=Path, default=DEFAULT_ROUND)
    parser.add_argument('--interval', type=float, default=30.0,
                        help='seconds between checks while a chain is alive')
    parser.add_argument('--retry-delay', type=float, default=60.0,
                        help='seconds before resuming after a failed chain')
    parser.add_argument('--max-stalled', type=int, default=3,
                        help='stop after this many resumes without new progress')
    parser.add_argument('--dry-run', action='store_true',
                        help='print the next action and exit')
    args = parser.parse_args(argv)
    round_dir = args.round.resolve()
    order = load_order(round_dir)
    done, current = read_progress(round_dir)
    sid = next_shot(done, current, order)
    if args.dry_run:
        print(json.dumps({
            'round': str(round_dir), 'done': done, 'total': len(order),
            'current': current, 'next': sid, 'active_pids': active_pids(round_dir),
        }, ensure_ascii=False, indent=2))
        return 0

    lock_path = ROOT / 'runtime/v1_chain_watchdog.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('another watchdog is already running')
        return 1

    log(f'watching {round_dir} ({len(order)} shots)')
    stalled = 0
    last_done = -1
    waiting = False
    while True:
        pids = active_pids(round_dir)
        if pids:
            if not waiting:
                log('chain active (' + ','.join(str(pid) for pid in pids) + '); waiting')
                waiting = True
            time.sleep(args.interval)
            continue
        waiting = False
        done, current = read_progress(round_dir)
        sid = next_shot(done, current, order)
        if sid is None:
            log(f'all {len(order)} shots complete')
            return 0
        if done <= last_done:
            stalled += 1
            if stalled >= args.max_stalled:
                log(f'no progress after {stalled} resumes; stopping at {sid} ({done}/{len(order)})')
                return 1
        else:
            stalled = 0
        last_done = done
        issues = audit_next(round_dir, sid)
        if issues:
            log(f'{sid}: spec audit failed before resume: ' + '; '.join(issues))
            return 1
        log(f'resuming at {sid} ({done}/{len(order)})')
        log_path = ROOT / 'runtime/v1_chain.log'
        with log_path.open('a', encoding='utf-8') as chain_log:
            chain = subprocess.Popen(
                [str(PYTHON), '-m', 'novel_h3.chain_render', '--round', str(round_dir), '--start', sid],
                cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                stdout=chain_log, stderr=subprocess.STDOUT, start_new_session=True,
            )
            code = chain.wait()
        if code != 0:
            log(f'chain exited {code}; retrying in {args.retry_delay:.0f}s')
            time.sleep(args.retry_delay)


if __name__ == '__main__':
    raise SystemExit(main())
