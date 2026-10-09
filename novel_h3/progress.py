"""Lightweight progress reads; never load models or mutate generation state."""
import json
import re
import subprocess
import time
from pathlib import Path

from .project import file_hash, read, sync_speech_reports
from .safety import PAUSE, REPO, user_service_env


def speech_exception(take):
    return (take.get('speech_retry_exhausted') is True
            or take.get('speech_qc_failed_retained') is True)


def execution_sheet(root, take):
    path = root / 'renders' / take['id'] / 'h3_execution_sheet.json'
    return str(path.relative_to(root)) if path.is_file() else None


def tail(path, size=32768):
    with path.open('rb') as handle:
        handle.seek(max(0, path.stat().st_size - size))
        return handle.read().decode('utf-8', errors='replace')


def parse_sampling_progress(text, total_steps=8):
    """Return the latest sampler step and whether the model is initializing."""
    clean = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text or '')
    matches = []
    for match in re.finditer(r'(?<!\d)(\d+)\s*/\s*(\d+)\s*\[', clean):
        step, total = int(match.group(1)), int(match.group(2))
        if total == total_steps:
            matches.append(step)
    if not matches:
        # Some ComfyUI/custom-node versions use prose instead of tqdm.
        for match in re.finditer(r'(?i)(?:(?:sampling\s+)?step|sampling)\s*[:#]?\s*(\d+)\s*(?:/|of)\s*(\d+)', clean):
            step, total = int(match.group(1)), int(match.group(2))
            if total == total_steps:
                matches.append(step)
    initializing = bool(re.search(r'Model Initiali(?:z|s)ing', clean, re.I))
    return (matches[-1] if matches else None), initializing


def _prefer_websocket_progress(log_steps, live):
    """Use websocket steps only when they are at least as current as the log."""
    if not live:
        return False
    live_steps = live.get('steps')
    if live_steps is not None:
        return log_steps is None or live_steps >= log_steps
    if log_steps is None:
        return True
    return live.get('stage') in {
        '保存采样结果', '解码视频与音频', '封装视频', '生成完成，等待核对',
    }


def _live_comfy_text(active):
    """Read current ComfyUI output without touching the generation queue."""
    if not active:
        return '', 'none'
    chunks = []
    source = 'none'
    # The dedicated service writes to journald. Filter by task start time so
    # older completed prompts cannot be shown as the active task.
    try:
        since = f"@{float(active['created_at']):.6f}"
        result = subprocess.run(
            ['journalctl', '--user', '-u', 'novel-h3-studio-comfy.service',
             '--since', since, '-n', '160', '--no-pager', '-o', 'json'],
            capture_output=True, text=True, timeout=1, check=False, env=user_service_env(),
        )
        if result.returncode == 0 and result.stdout:
            messages = []
            for line in result.stdout.splitlines():
                try:
                    message = json.loads(line).get('MESSAGE', '')
                except json.JSONDecodeError:
                    continue
                if isinstance(message, list):
                    message = bytes(message).decode('utf-8', errors='replace')
                messages.append(str(message))
            if messages:
                chunks.append('\n'.join(messages))
                source = 'journal'
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    # File-log fallback for installations launched outside systemd.
    for path in (REPO / 'runtime/comfy-resource-optimized.log',
                 REPO / 'runtime/comfy-vdn.log',
                 REPO / 'runtime/comfy-vdn-retry.log',
                 REPO / 'runtime/liaozhai_comfy_start.log'):
        try:
            if path.exists() and path.stat().st_mtime >= float(active['created_at']):
                text = tail(path)
                if path.name == 'liaozhai_comfy_start.log':
                    prompts = list(re.finditer(r'(?m)^.*got prompt.*$', text))
                    if prompts:
                        text = text[prompts[-1].start():]
                chunks.append(text)
                source = 'file'
        except (OSError, ValueError):
            continue
    return '\n'.join(chunks), source


def _parallel_preparation(root):
    """Expose targeted preparation batches launched outside the serial worker."""
    manifest_path = root / 'analysis' / 'parallel_preparation.json'
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None

    jobs = []
    for key, raw in (manifest.get('chapters') or {}).items():
        raw = raw if isinstance(raw, dict) else {}
        pid = raw.get('pid')
        try:
            proc_cmdline = Path(f'/proc/{pid}/cmdline').read_bytes() if pid else b''
        except OSError:
            proc_cmdline = b''
        alive = bool(proc_cmdline and (b'codex' in proc_cmdline or b'preparation_worker.py' in proc_cmdline))
        events_rel = raw.get('events')
        result_rel = raw.get('result')
        events_path = root / events_rel if events_rel else None
        result_path = root / result_rel if result_rel else None
        last_event = None
        if events_path and events_path.is_file():
            try:
                for line in reversed(events_path.read_bytes()[-131072:].splitlines()):
                    try:
                        event = json.loads(line.decode('utf-8', errors='replace'))
                    except json.JSONDecodeError:
                        continue
                    item = event.get('item', event) if isinstance(event, dict) else {}
                    text = item.get('title') or item.get('text') or item.get('type') or event.get('type', '')
                    if item.get('type') == 'command_execution' and item.get('command'):
                        state = '执行中' if item.get('status') == 'in_progress' else '已完成'
                        text = f"{state}：{item['command']}"
                    if text:
                        last_event = str(text).replace('\n', ' ')[:240]
                        break
            except OSError:
                pass
        result_bytes = result_path.stat().st_size if result_path and result_path.is_file() else 0
        status = 'running' if alive else ('completed' if result_bytes else 'stopped')
        jobs.append({
            'chapter': key,
            'episode': raw.get('episode', 'chapter_' + key),
            'pid': pid,
            'status': status,
            'status_label': {'running': '运行中', 'completed': '已完成', 'stopped': '已停止'}.get(status, status),
            'batch_dir': raw.get('batch_dir'),
            'events': events_rel,
            'result': result_rel,
            'events_bytes': events_path.stat().st_size if events_path and events_path.is_file() else 0,
            'result_bytes': result_bytes,
            'events_updated_at': events_path.stat().st_mtime if events_path and events_path.is_file() else None,
            'last_event': last_event,
        })
    return {
        'status': 'running' if any(job['status'] == 'running' for job in jobs) else 'idle',
        'started_at': manifest.get('started_at'),
        'policy': manifest.get('policy'),
        'jobs': jobs,
    }


def _preparation_targets(root, parallel):
    from .preparation_control import status as preparation_status
    book = read(root / 'book.json')
    parallel_by_episode = {job['episode']: job for job in (parallel or {}).get('jobs', [])}
    targets = []
    for chapter in book.get('chapters', []):
        if chapter.get('kind') != 'story':
            continue
        episode = 'chapter_' + chapter['id']
        activity = preparation_status(root, episode)
        parallel_job = parallel_by_episode.get(episode)
        if parallel_job and parallel_job.get('status') == 'running':
            activity = dict(activity, status='running', worker_alive=True,
                            message='定向并行准备任务正在运行。', parallel=True,
                            pid=parallel_job.get('pid'))
        targets.append({'episode': episode, 'title': chapter.get('title', episode),
                        'status': activity.get('status', 'paused'),
                        'worker_alive': bool(activity.get('worker_alive')),
                        'message': activity.get('message'),
                        'parallel': bool(activity.get('parallel'))})
    return targets


def book_progress(root, takes):
    chapters = read(root / 'book.json')['chapters']
    latest = {}
    for take in takes:
        latest[(take['episode'], take['shot'])] = take
    generated = set()
    composed = set()
    planned = 0
    for chapter in chapters:
        eid = 'chapter_' + chapter['id']
        path = root / 'episodes' / (eid + '.json')
        if path.exists():
            shots = read(path).get('shots', [])
            planned += bool(shots)
            if shots and all(latest.get((eid, shot['id']), {}).get('status') in ('rendered', 'approved')
                             and (root / latest[(eid, shot['id'])].get('video', '')).is_file() for shot in shots):
                generated.add(chapter['id'])
                if (root / 'chapter_videos' / (eid + '.mp4')).is_file():
                    composed.add(chapter['id'])
    return dict(total=len(chapters), story_total=sum(c.get('kind') == 'story' for c in chapters),
                reference_total=sum(c.get('kind') == 'reference' for c in chapters),
                generated=len(generated), composed=len(composed), planned=planned)


def snapshot(root):
    state = sync_speech_reports(root)
    takes = sorted((t for t in state['takes'].values() if not t.get('retired')), key=lambda t: t['created_at'])
    latest = takes[-1] if takes else None
    episode = read(root/'episodes'/f"{latest['episode']}.json") if latest else {'shots': []}
    current = {t['shot']: t for t in takes if latest and t['episode'] == latest['episode']}
    shots = [current[s['id']] for s in episode['shots'] if s['id'] in current]
    completed = [t for t in shots if t['status'] in ('rendered', 'approved')]
    active = next((t for t in reversed(shots) if t['status'] in ('submitted', 'submitting')), None)
    samples = list((root/'renders').glob('batch_*/resources.jsonl'))
    samples += list((REPO/'runtime/resource-check').glob('samples.jsonl'))
    resources = None
    if samples:
        for line in reversed(tail(max(samples, key=lambda p: p.stat().st_mtime)).splitlines()):
            try:
                resources = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    cfg = read(root/'config.json')
    total_steps = int(cfg.get('generation', {}).get('steps', 8))
    live_text, progress_source = _live_comfy_text(active)
    steps, model_initializing = parse_sampling_progress(live_text, total_steps)
    if not active:
        stage = None
    elif steps is not None and model_initializing and steps == 0:
        stage = '加载模型'
        steps = None
    elif steps is not None and steps < total_steps:
        stage = '采样'
    elif steps is not None:
        stage = '封装视频'
    elif 'Requested to load' in live_text:
        stage = '加载模型'
    elif 'Model MiniMaxH3 prepared' in live_text:
        stage = '复用缓存模型'
    elif 'got prompt' in live_text or 'layout:' in live_text:
        stage = '准备采样'
    else:
        stage = '等待 ComfyUI 进度'
    from .live_progress import listener
    live = listener(root).get(active.get('prompt_id') if active else None)
    if live:
        # Comfy's websocket can miss intermediate progress events for H3's
        # long sampler. Prefer the larger current-step count from the process
        # log, while still accepting websocket stage transitions and newer
        # step counts immediately.
        if _prefer_websocket_progress(steps, live):
            steps, stage = live.get('steps'), live['stage']
            total_steps = live.get('steps_total', total_steps)
            progress_source = 'websocket'
    generation = cfg.get('generation', {})
    delivery = cfg.get('delivery', generation)
    resolution_label = (f"成片 {delivery.get('width', '—')} × {delivery.get('height', '—')}"
                        f" · 镜头生成 {generation.get('width', '—')} × {generation.get('height', '—')}")
    video_engine = {
        'name': 'VDN-H3 Turbo' if cfg.get('vdn', {}).get('enabled') else 'MiniMax H3',
        'steps': int(generation.get('steps', total_steps)),
        'generation': generation,
    }
    from .video_control import next_pending_episode, status as video_status
    # Gate reports are per chapter.  Selecting the newest file globally can
    # surface an obsolete blocker from a completed chapter after the queue has
    # already advanced.  Resolve the next pending chapter first, then read
    # only that chapter's report.
    pending = next_pending_episode(root)
    gate_path = (REPO / 'runtime' / 'asset_gate' / f'{pending}.json') if pending else None
    gate = read(gate_path) if gate_path and gate_path.exists() else None
    video_activity = video_status(root)
    if not video_activity.get('worker_alive'):
        # A waiting report can be left behind by an older preparation batch.
        # Recheck the current chapter so links and reasons never point at stale data.
        if pending:
            try:
                from start_next_chapter_when_ready import _chapter_requirements
                _, _, blockers, required_assets, required_speakers = _chapter_requirements(root, pending)
            except (FileNotFoundError, KeyError, ValueError, OSError) as exc:
                blockers = [{'reason': 'chapter_material_missing', 'details': str(exc)}]
                required_assets, required_speakers = set(), set()
            gate = ({'status': 'waiting', 'episode': pending, 'blockers': blockers,
                     'required_assets': len(required_assets),
                     'required_speakers': sorted(required_speakers), 'time': time.time()}
                    if blockers else None)
    from .preparation_progress import summary as preparation_summary
    from .rework_queue import snapshot as rework_snapshot
    from .media import assembly_progress
    parallel_preparation = _parallel_preparation(root)
    return {'cinema_v2': cinema_progress(root), 'video_control': video_activity, 'preparation_progress': preparation_summary(root), 'parallel_preparation': parallel_preparation, 'preparation_targets': _preparation_targets(root, parallel_preparation), 'book_progress': book_progress(root, takes), 'chapter_assembly': assembly_progress(root), 'video_engine': video_engine, 'resolution_label': resolution_label, 'updated_at': time.time(), 'paused': PAUSE.exists(),
            'pause_reason': PAUSE.read_text() if PAUSE.exists() else None,
            'chapter': episode.get('title', '尚无任务'), 'episode': latest['episode'] if latest else None,
            'total': len(episode['shots']), 'completed': len(completed),
            'approved': sum(t['status'] == 'approved' for t in shots),
            'failed': sum(t['status'] == 'failed' for t in shots),
            'speech_exceptions': sum(speech_exception(t) for t in shots),
            'active': active and {'shot': active['shot'], 'started_at': active['created_at']},
            'steps': steps, 'steps_total': total_steps, 'stage': stage,
            'progress_source': progress_source, 'resources': resources,
            'asset_gate': gate,
            'rework_queue': rework_snapshot(root),
            'recent': [{'shot': t['shot'], 'status': t['status'], 'approval_method': t.get('approval_method'), 'video': t.get('video'),
                        'execution_sheet': execution_sheet(root, t),
                        'audio_cleanup': t.get('speech_check', {}).get('audio_cleanup', {}).get('status'),
                        'lip_sync_gate': t.get('speech_check', {}).get('lip_sync_gate'),
                        'speech_exception': speech_exception(t),
                        'speech_exception_label': '转写核对失败·已保留' if speech_exception(t) else None}
                       for t in list(reversed(shots))[:8]]}


def cinema_progress(root):
    """Show the new production revision without counting old approved clips as new work."""
    paths = list(Path(root).glob('production_v2/*/progress.json'))
    if not paths:
        return None
    path = max(paths, key=lambda p: p.stat().st_mtime)
    data = read(path)
    plan_path = Path(root) / data['plan_path'] if data.get('plan_path') else path.parent / 'pilot.json'
    plan = read(plan_path)
    data.update(title=plan.get('title', plan['id']), planned_total=len(plan['shots']),
                script=str((path.parent / 'screenplay.md').relative_to(root)),
                model=('MiniMax H3 · 对白驱动表演' if data.get('audio_route') == 'h3_audio_conditioned'
                       else 'MiniMax H3 · 原生音画'), release_approved=False)
    data['stage'] = {'generating': '正在生成原生音画', 'speech_screening': '正在核对台词',
                     'narrative_rework': '正在修正故事完整性，后续章节尚未启动',
                     'candidates_ready': '候选完成，待审片', 'failed': '本次任务已停止',
                     'quality_review': '质量复核与对白方案验证',
                     'dialogue_preparation': '正在制作全章白话对白',
                     'audio_roundtrip': '正在验证H3对白音频',
                     'dialogue_screening': '正在核对全章对白',
                     'editing': '正在剪辑全章审片版',
                     'chapter_review_ready': '全章审片版已生成，待影视质量审核'}.get(data['status'], data['status'])
    if data['status'] == 'generating':
        live_text, source = _live_comfy_text({'created_at': data['started_at']})
        steps, _ = parse_sampling_progress(live_text, 20)
        data.update(steps=steps, steps_total=20, progress_source=source)
        from .live_progress import listener
        live = listener(root).get(data.get('prompt_id'))
        if _prefer_websocket_progress(steps, live):
            data.update(steps=live.get('steps'), stage=live['stage'], progress_source='websocket')
    rows = []
    reused_ids = {Path(p).name for p in plan.get('reused_takes', {}).values()}
    for receipt in path.parent.glob('takes/*/take.json'):
        take = read(receipt)
        take_plan = take.get('plan_id')
        if not take_plan and (receipt.parent / 'request.json').exists():
            take_plan = read(receipt.parent / 'request.json').get('plan_id')
        if take_plan != plan['id'] and take['id'] not in reused_ids:
            continue
        media = receipt.parent / 'native.mp4'
        if take.get('technical_qc', {}).get('passed') is True and media.exists():
            rows.append({'shot': take['shot_id'], 'take_id': take['id'],
                         'video': str(media.relative_to(root)), 'status': take['status'],
                         'transcript_passed': take.get('speech_screening', {}).get('passed'),
                         'completed_at': take.get('completed_at', 0)})
    data['generated_shots'] = len({row['shot'] for row in rows})
    data['recent'] = sorted(rows, key=lambda r: r['completed_at'], reverse=True)[:6]
    audio_manifest = path.parent / 'chapter_audio/manifest.json'
    if audio_manifest.exists():
        audio = read(audio_manifest)
        data['audio_prepared'] = sum(bool(e.get('target', {}).get('path')) for e in audio.get('entries', []))
        data['audio_total'] = audio.get('dialogue_shots', 0)
        check_path = audio_manifest.with_name('manifest.speech_check.json')
        if check_path.exists():
            checks = read(check_path)
            if checks.get('manifest_sha256') == file_hash(audio_manifest):
                data['audio_checked'] = checks['counts']['entries']
                data['audio_passed'] = checks['counts']['passed']
    from .cinema_dashboard import enrich
    return enrich(root, path, plan, data)
