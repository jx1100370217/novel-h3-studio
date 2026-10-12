"""Resumable serial native H3 candidates; media stays immutable and unapproved."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..comfy import api, config, schema_check
from ..media import technical_qc
from ..project import file_hash, inside, locked, read, write
from ..safety import REPO, check_paused, check_power_cap, user_service_env
from .compiler import compile_shot, graph


def stage(root, request):
    input_root = Path(config(root)['input_dir'])
    for items, path_key, hash_key, folder in (
        (request['visuals'], 'generation_path', 'generation_sha256', 'images'),
        (request['voices'], 'path', 'sha256', 'voices'),
        ([request['audio_target']] if request.get('audio_target') else [], 'path', 'sha256', 'dialogue'),
    ):
        for item in items:
            source = inside(root, item[path_key])
            if file_hash(source) != item[hash_key]:
                raise ValueError('Reference changed since request compilation')
            name = f"novel_h3/cinema_v2/{folder}/{item[hash_key]}{source.suffix}"
            target = inside(input_root, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)
            if file_hash(target) != item[hash_key]:
                raise ValueError('Staged reference hash mismatch')
            item['staged_name'] = name


def output_file(cfg, history, node, extension):
    outputs = history.get('outputs', {}).get(str(node), {})
    for values in outputs.values():
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict) or not value.get('filename', '').endswith(extension):
                continue
            return inside(Path(cfg['output_dir']), str(Path(value.get('subfolder', '')) / value['filename']))
    raise ValueError(f'Comfy history has no {extension} output from node {node}')


def screen(take_dir):
    unit = f'novel-h3-cinema-qc-{take_dir.name}'
    command = ['systemd-run', '--user', '--wait', '--collect', '--pipe', '--unit', unit,
               '--slice', 'novel-h3-audio.slice', '--property=MemoryMax=12G', '--property=OOMPolicy=kill',
               '--setenv=NOVEL_H3_AUDIO_QC=1', '--working-directory', str(REPO), '--',
               str(REPO / '.venv-audio/bin/python'), '-m', 'novel_h3.v2.qc', str(take_dir)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, env=user_service_env())
    (take_dir / 'analysis_process.log').write_text(result.stdout + '\n' + result.stderr)
    return result.returncode


def verify_cached_media(take_dir, receipt):
    if receipt.get('technical_qc', {}).get('passed') is not True:
        raise ValueError('Cached native candidate failed technical QC; not reusable')
    for filename, field in (('native.mp4', 'video_sha256'), ('native_audio.flac', 'native_audio_sha256')):
        path = take_dir / filename
        if not path.is_file() or file_hash(path) != receipt.get(field):
            raise ValueError('Immutable cached native media is missing or changed: ' + filename)


def reuse_candidate(root, relative, request):
    """Reuse an explicitly selected take only when its actual shot inputs match."""
    folder = inside(root, relative)
    original, receipt = read(folder / 'request.json'), read(folder / 'take.json')
    fields = ('schema', 'shot_sha256', 'mode', 'audio_route', 'frames', 'fps', 'generation',
              'models', 'model_lock', 'graph_profile', 'prompt_sha256', 'bgm', 'audio_target', 'visuals', 'voices')
    def inputs(data):
        def clean(value):
            if isinstance(value, dict):
                return {k: clean(v) for k, v in value.items() if k != 'staged_name'}
            if isinstance(value, list):
                return [clean(v) for v in value]
            return value
        return clean({key: data.get(key) for key in fields})
    if inputs(original) != inputs(request):
        raise ValueError('Selected reusable take has different shot inputs')
    verify_cached_media(folder, receipt)
    if receipt.get('speech_screening', {}).get('passed') is not True:
        raise ValueError('Selected reusable take lacks a passing speech screen')
    return folder, receipt


def complete_screening(take_dir, receipt):
    report_path = take_dir / 'analysis/speech.json'
    previous = read(report_path) if report_path.exists() else {}
    if (previous.get('video_sha256') == receipt['video_sha256']
            and previous.get('schema') == 'native_av_screening_v2'
            and previous.get('analysis_audio_sha256') == receipt['native_audio_sha256']
            and isinstance(previous.get('passed'), bool)):
        receipt['speech_screening'] = previous
    else:
        qc_returncode = screen(take_dir)
        receipt['speech_screening'] = (read(report_path)
            if report_path.exists() and qc_returncode == 0
            else {'passed': None, 'error': 'Inspection subprocess failed; native media retained'})
    verify_cached_media(take_dir, receipt)
    write(take_dir / 'take.json', receipt)


def reconcile_failed_submission(take_dir, receipt, cfg):
    """Resubmit only a recorded failure whose previous job is no longer active."""
    if receipt.get('status') != 'failed' or not receipt.get('prompt_id'):
        return receipt
    if receipt.get('video_sha256') or (take_dir / 'native.mp4').exists():
        raise ValueError('A failed submission with saved media needs explicit review; refusing overwrite')
    queue = api(cfg['comfy_url'], '/queue')
    if any(row[1] == receipt['prompt_id'] for key in ('queue_running', 'queue_pending')
           for row in queue.get(key, [])):
        raise RuntimeError('The failed submission is still active; refusing duplicate generation')
    history = api(cfg['comfy_url'], '/history/' + receipt['prompt_id']).get(receipt['prompt_id'])
    if history and history.get('status', {}).get('status_str') == 'success':
        return receipt  # Normal output collection recovers this completed job.
    archive = take_dir / 'submission_history' / (str(time.time_ns()) + '.json')
    write(archive, dict(receipt, recovered_history=history))
    return {}


def release_between_shots(cfg):
    """Saved native media is independent of Comfy's in-memory intermediates."""
    queue = api(cfg['comfy_url'], '/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise RuntimeError('Comfy became busy; refusing to clear another active job')
    api(cfg['comfy_url'], '/free', {'unload_models': True, 'free_memory': True})
    time.sleep(3)


def run(root, plan_path, shot_ids, seed):
    from render_chapter import snapshot

    root = Path(root).resolve()
    plan_path = Path(plan_path).resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError('The plan must belong to this project')
    plan, cfg = read(plan_path), config(root)
    if plan.get('narrative_contract_required'):
        from .narrative import preflight
        preflight(root, plan_path)
    if plan.get('narrative_contract_required') or plan.get('cinematization_required'):
        from .cinematization import require
        require(root, plan)
    selected = [s for s in plan['shots'] if not shot_ids or s['id'] in shot_ids]
    if not selected or (shot_ids and set(shot_ids) != {s['id'] for s in selected}):
        raise ValueError('Unknown or empty shot selection')
    base = plan_path.parent
    progress = base / 'progress.json'
    manifest = base / 'runs' / f"seed_{int(seed)}.json"
    info = api(cfg['comfy_url'], '/object_info')
    with locked(root, 'batch'):
        records = read(manifest).get('takes', {}) if manifest.exists() else {}
        for position, shot in enumerate(selected):
            check_paused()
            check_power_cap(450)
            resources = snapshot()
            if resources['temperature_c'] >= 82 or resources['available_gib'] < 4:
                raise RuntimeError('Pre-submit resource limits exceeded: ' + str(resources))
            request = compile_shot(root, plan, shot, seed + plan['shots'].index(shot))
            reused = plan.get('reused_takes', {}).get(shot['id'])
            if reused:
                reuse_dir, reuse_receipt = reuse_candidate(root, reused, request)
                records[shot['id']] = reuse_receipt['id']
                write(manifest, {'plan_id': plan['id'], 'takes': records, 'release_approved': False})
                print('REUSED_VERIFIED_INPUTS', shot['id'], reuse_receipt['id'], flush=True)
                continue
            take_id = 'c_' + request['request_sha256'][:16]
            take_dir = base / 'takes' / take_id
            take_dir.mkdir(parents=True, exist_ok=True)
            receipt_path = take_dir / 'take.json'
            receipt = read(receipt_path) if receipt_path.exists() else {}
            if receipt.get('video_sha256') and (take_dir / 'native.mp4').exists():
                verify_cached_media(take_dir, receipt)
                complete_screening(take_dir, receipt)
                records[shot['id']] = take_id
                write(manifest, {'plan_id': plan['id'], 'takes': records, 'release_approved': False})
                print('REUSED', shot['id'], take_id, flush=True)
                continue
            receipt = reconcile_failed_submission(take_dir, receipt, cfg)
            stage(root, request)
            nodes, prefix = graph(request, take_id)
            errors = schema_check(nodes, info)
            if errors:
                raise ValueError('Invalid H3 graph: ' + '; '.join(errors))
            write(take_dir / 'request.json', request)
            write(take_dir / 'graph.json', nodes)
            (take_dir / 'prompt.txt').write_text(request['prompt'])
            if receipt.get('status') == 'submitting' and not receipt.get('prompt_id'):
                raise RuntimeError('Submission outcome unknown; reconcile Comfy history before retrying')
            if not receipt.get('prompt_id'):
                queue = api(cfg['comfy_url'], '/queue')
                if queue['queue_running'] or queue['queue_pending']:
                    raise RuntimeError('Comfy has another task; refusing duplicate or overlapping submission')
                receipt = {'id': take_id, 'plan_id': plan['id'], 'shot_id': shot['id'], 'status': 'submitting',
                           'request_sha256': request['request_sha256'], 'created_at': time.time(),
                           'audio_route': request['audio_route'], 'release_approved': False}
                write(receipt_path, receipt)
                response = api(cfg['comfy_url'], '/prompt', {'prompt': nodes,
                    'client_id': take_id, 'extra_data': {'cinema_request_sha256': request['request_sha256']}})
                receipt.update(status='submitted', prompt_id=response['prompt_id'])
                write(receipt_path, receipt)
            write(progress, {'status': 'generating', 'worker_pid': os.getpid(), 'shot': shot['id'], 'take_id': take_id,
                'prompt_id': receipt['prompt_id'], 'completed': position, 'total': len(selected),
                'started_at': receipt['created_at'], 'audio_route': request['audio_route'],
                'plan_path': str(plan_path.relative_to(root)), 'updated_at': time.time()})
            print('SUBMITTED_NATIVE', shot['id'], take_id, receipt['prompt_id'], flush=True)
            try:
                started = time.monotonic()
                while True:
                    check_paused()
                    resources = snapshot()
                    with (take_dir / 'resource_samples.jsonl').open('a') as sample_log:
                        sample_log.write(json.dumps(resources) + '\n')
                    if resources['temperature_c'] >= 82 or resources['available_gib'] < 4:
                        raise RuntimeError('Generation resource safety limit exceeded: ' + str(resources))
                    if time.monotonic() - started > 3600:
                        raise TimeoutError('Single H3 candidate exceeded one hour')
                    history = api(cfg['comfy_url'], '/history/' + receipt['prompt_id']).get(receipt['prompt_id'])
                    if history:
                        write(take_dir / 'history.json', history)
                        if history.get('status', {}).get('status_str') != 'success':
                            raise RuntimeError('H3 execution did not complete successfully')
                        break
                    time.sleep(5)
            except BaseException as exc:
                queue = api(cfg['comfy_url'], '/queue')
                if any(row[1] == receipt['prompt_id'] for row in queue.get('queue_running', [])):
                    api(cfg['comfy_url'], '/interrupt', {})
                receipt.update(status='failed', error=str(exc))
                write(receipt_path, receipt)
                write(progress, {'status': 'failed', 'shot': shot['id'], 'error': str(exc), 'updated_at': time.time()})
                raise
            shutil.copy2(output_file(cfg, history, 20, '.mp4'), take_dir / 'native.mp4')
            shutil.copy2(output_file(cfg, history, 17, '.flac'), take_dir / 'native_audio.flac')
            qc = technical_qc(take_dir / 'native.mp4', request['frames'],
                              request['generation']['width'], request['generation']['height'])
            write(take_dir / 'technical_qc.json', qc)
            receipt.update(status='rendered_pending_review', video_sha256=file_hash(take_dir / 'native.mp4'),
                           native_audio_sha256=file_hash(take_dir / 'native_audio.flac'), technical_qc=qc,
                           completed_at=time.time(), av_sync_review={'status': 'not_evaluated'},
                           human_listened=False, narrative_review={'status': 'not_evaluated'})
            write(receipt_path, receipt)
            if not qc['passed']:
                raise RuntimeError('Native candidate technical QC failed: ' + str(qc['errors']))
            write(progress, {'status': 'speech_screening', 'worker_pid': os.getpid(), 'shot': shot['id'], 'take_id': take_id,
                             'completed': position, 'total': len(selected), 'audio_route': request['audio_route'],
                             'plan_path': str(plan_path.relative_to(root)), 'updated_at': time.time()})
            complete_screening(take_dir, receipt)
            records[shot['id']] = take_id
            write(manifest, {'plan_id': plan['id'], 'takes': records, 'release_approved': False})
            print('NATIVE_CANDIDATE', shot['id'], take_id, 'text_passed=', receipt['speech_screening'].get('passed'), flush=True)
            release_between_shots(cfg)
        write(progress, {'status': 'candidates_ready', 'completed': len(selected), 'total': len(selected),
                         'updated_at': time.time(), 'manifest': str(manifest.relative_to(root)),
                         'plan_path': str(plan_path.relative_to(root)), 'audio_route': request['audio_route'],
                         'release_approved': False})
    return manifest
