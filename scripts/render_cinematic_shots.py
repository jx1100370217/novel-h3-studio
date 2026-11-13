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
import re
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


def voice_binding_errors(sid: str, request: dict) -> list[str]:
    """Every H3 shot with spoken dialogue must bind each line to a voice reference.

    This is a hard contract, not a repair step after a lip-sync failure.  A
    dialogue prompt without ``reference_audio_paths`` or without an explicit
    ``(Sx) <Audio N>`` binding immediately before every ``<d>`` line is rejected
    before the GPU service is touched.
    """
    prompt = str(request.get('prompt') or '')
    if '<d>' not in prompt:
        return []
    problems: list[str] = []
    paths = [str(p) for p in (request.get('reference_audio_paths') or [])]
    labels = sorted({int(n) for n in re.findall(r'<Audio (\d+)>', prompt)})
    if not paths:
        problems.append(f'{sid}: dialogue prompt has no reference_audio_paths')
    if not labels:
        problems.append(f'{sid}: dialogue prompt has no <Audio N> labels')
    if paths and labels and max(labels) > len(paths):
        problems.append(
            f'{sid}: <Audio {max(labels)}> exceeds {len(paths)} reference audio file(s)'
        )
    for raw in paths:
        if not Path(raw).expanduser().is_file():
            problems.append(f'{sid}: reference audio does not exist: {raw}')

    definitions = prompt.split('subject_definitions:', 1)[-1].split('summary:', 1)[0]
    summary = prompt.split('summary:', 1)[-1].split('retention_analysis:', 1)[0]
    if 'audio reference' not in summary.lower() and 'audio reuse' not in summary.lower():
        problems.append(f'{sid}: summary lacks the [audio reference] task marker')
    for number in labels:
        if f'<Audio {number}>' not in definitions:
            problems.append(f'{sid}: <Audio {number}> is not defined in subject_definitions')
        if not re.search(
            rf'<Audio {number}>: (?:fully_copy|partially_copy|reference|weak_reference) - ',
            prompt,
        ):
            problems.append(f'{sid}: <Audio {number}> has no retention relationship')

    for index, match in enumerate(re.finditer(r'<d>', prompt), 1):
        prefix = prompt[max(0, match.start() - 320):match.start()]
        if not re.search(r'\((S\d+)\)\s*<Audio (\d+)>[^\n]{0,140}$', prefix):
            problems.append(
                f'{sid}: dialogue line {index} lacks an explicit (Sx) <Audio N> binding'
            )
    return problems



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
    binding_problems: list[str] = []
    for sid in wanted:
        if sid not in requests:
            binding_problems.append(f'{sid}: missing from assets/requests.json')
            continue
        binding_problems.extend(voice_binding_errors(sid, requests[sid]))
    if binding_problems:
        for problem in binding_problems:
            log('VOICE-BINDING ' + problem)
        raise SystemExit(
            'Refusing to render: every shot with spoken dialogue must define '
            'reference_audio_paths and bind each <d> line to (Sx) <Audio N>.'
        )
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
