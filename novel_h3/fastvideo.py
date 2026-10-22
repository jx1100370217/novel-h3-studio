"""FastVideo's native NVFP4 QAD HTTP route and immutable chapter candidates."""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from .project import file_hash, inside, locked, read, write


def default_profile():
    runtime = Path(__file__).resolve().parents[1] / 'runtime'
    return {'backend': 'fastvideo', 'model_repo': 'FastVideo/FastH3-Omni-NVFP4-QAD',
            'revision': 'f01e6a23ac6066aa9eb622cf94b6259442e70ec2',
            'runtime_commit': 'fa2d1324c60050cd65209c6aaeac470e7fb412f5',
            'model_dir': str(runtime / 'models/FastH3-Omni-NVFP4-QAD'),
            'adaln_table': str(runtime / 'models/FastH3-Omni-NVFP4-QAD/adaln_table.pt'),
            'download_manifest': str(runtime / 'fastvideo-model-download.json'),
            'api_url': 'http://127.0.0.1:8195', 'production_enabled': True,
            'input_mode': 'ref2va', 'steps': 8,
            'scheduler_shift_video': 12.0, 'scheduler_shift_audio': 3.0}


def selected(cfg):
    return cfg.get('video_engine') == 'fast_h3_omni' and cfg.get('fast_h3_omni', {}).get('backend') == 'fastvideo'


def available(cfg):
    p = cfg.get('fast_h3_omni', {})
    root = Path(p.get('model_dir', '/nonexistent'))
    return (p.get('backend') == 'fastvideo' and p.get('production_enabled') is True
            and all((root / name).is_file() for name in (
                'fastvideo_inference.json', 'transformer_ref/nvfp4_weights.safetensors',
                'text_encoder/model.safetensors.index.json',
                'vae_decoder_nvfp4/decoder-nvfp4.safetensors'))
            and Path(p.get('adaln_table', '/nonexistent')).is_file())


def api(cfg, route, payload=None):
    base = cfg['fast_h3_omni']['api_url'].rstrip('/')
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(base + route, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def model_lock(root, cfg):
    p = cfg['fast_h3_omni']
    model = Path(p['model_dir'])
    manifest = read(p['download_manifest'])
    if manifest['model_repo'] != p['model_repo'] or manifest['revision'] != p['revision']:
        raise ValueError('FastVideo checkpoint revision differs from the download manifest')
    cache_path = Path(root) / 'production_v2/fastvideo_model_lock.json'
    previous = read(cache_path) if cache_path.exists() else {}
    files = {}
    paths = [(row['path'], model / row['path'], row) for row in manifest['files']
             if row['path'] != '.gitattributes']
    paths.append(('adaln_table', Path(p['adaln_table']), {}))
    for name, path, expected in paths:
        stat = path.stat()
        identity = {'path': str(path.resolve()), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}
        old = previous.get('files', {}).get(name, {})
        sha = old.get('sha256') if old.get('identity') == identity else file_hash(path)
        if expected.get('size') is not None and expected['size'] != stat.st_size:
            raise ValueError('Incomplete FastVideo component: ' + name)
        if expected.get('sha256') and sha != expected['sha256']:
            raise ValueError('FastVideo component SHA-256 mismatch: ' + name)
        files[name] = {'identity': identity, 'sha256': sha}
    result = {'model_repo': p['model_repo'], 'revision': p['revision'], 'actual_model': p['model_repo'],
              'runtime': 'FastVideo', 'runtime_commit': p['runtime_commit'],
              'runtime_launcher_sha256': file_hash(Path(__file__).resolve().parents[1] / 'start_fastvideo.py'),
              'quantization': 'NVFP4 QAD', 'attention_prefix': 'fp8', 'files': files}
    if result != previous:
        write(cache_path, result)
    return result


def request_payload(root, request):
    root = Path(root)
    from .ref2va import validate
    validate(request['prompt'], request['visuals'], request['voices'], request['shot'].get('spoken_lines', []),
             duration_seconds=request['frames'] / 24, single_shot=True, no_music=True,
             additional_visible_people=request['shot'].get('additional_visible_people', []), require_population=True)
    if request['generation']['width'] * request['generation']['height'] > 1032192:
        raise ValueError('FastVideo MiniMax-H3 canvas exceeds the official 1032192-pixel limit')
    return {'model': 'fasth3-omni-nvfp4-qad', 'task': 'ref2va', 'prompt': request['prompt'],
            'width': request['generation']['width'], 'height': request['generation']['height'],
            'num_frames': request['frames'], 'fps': 24, 'num_inference_steps': 8,
            'guidance_scale': 1.0, 'seed': request['seed'],
            'image_reference': [{'image_url': str(inside(root, ref['generation_path']))}
                                for ref in request['visuals']],
            'audio_reference': [{'audio_url': str(inside(root, ref['path']))}
                                for ref in request['voices']]}


def run(root, plan_path, shot_ids, seed, *, screening=True):
    from .comfy import config
    from .media import technical_qc
    from .safety import check_paused, check_power_cap
    from .v2.compiler import compile_shot
    from .v2.runner import complete_screening, verify_cached_media
    from .v2.narrative import preflight
    from .v2.cinematization import require

    check_paused()
    root, plan_path = Path(root).resolve(), Path(plan_path).resolve()
    if not plan_path.is_relative_to(root):
        raise ValueError('The plan must belong to the project')
    cfg, plan = config(root), read(plan_path)
    preflight(root, plan_path)
    require(root, plan)
    if not available(cfg):
        raise ValueError('The complete FastVideo NVFP4 QAD stack is not installed')
    api(cfg, '/health')
    loaded = api(cfg, '/v1/model_info')
    if (Path(loaded['model_path']).resolve() != Path(cfg['fast_h3_omni']['model_dir']).resolve()
            or loaded['served_model_name'] != 'fasth3-omni-nvfp4-qad'):
        raise ValueError('The running FastVideo service has a different model loaded')
    shots = [s for s in plan['shots'] if not shot_ids or s['id'] in shot_ids]
    if not shots or shot_ids and set(shot_ids) != {s['id'] for s in shots}:
        raise ValueError('Unknown or empty shot selection')
    base = plan_path.parent
    manifest = base / 'runs' / f'seed_{int(seed)}.json'
    with locked(root, 'batch'):
        records = read(manifest).get('takes', {}) if manifest.exists() else {}
        for position, shot in enumerate(shots):
            check_paused()
            check_power_cap(450)
            request = compile_shot(root, plan, shot, seed + plan['shots'].index(shot))
            take_id = 'f_' + request['request_sha256'][:16]
            folder = base / 'takes' / take_id
            folder.mkdir(parents=True, exist_ok=True)
            receipt_path = folder / 'take.json'
            receipt = read(receipt_path) if receipt_path.exists() else {}
            if receipt.get('video_sha256'):
                verify_cached_media(folder, receipt)
                if screening:
                    complete_screening(folder, receipt)
                records[shot['id']] = take_id
                continue
            write(folder / 'request.json', request)
            (folder / 'prompt.txt').write_text(request['prompt'], encoding='utf-8')
            payload = request_payload(root, request)
            write(folder / 'fastvideo_request.json', payload)
            if receipt.get('status') == 'submitting' and not receipt.get('prompt_id'):
                raise RuntimeError('Submission outcome unknown; reconcile the FastVideo job before retrying')
            if receipt.get('status') == 'failed':
                previous = api(cfg, '/v1/videos/' + receipt['prompt_id'])
                if previous['status'] != 'failed' or (folder / 'native.mp4').exists():
                    raise RuntimeError('The previous candidate needs reconciliation before retrying')
                write(folder / 'submission_history' / (str(time.time_ns()) + '.json'),
                      dict(receipt, fastvideo_history=previous))
                receipt = {}
            if not receipt.get('prompt_id'):
                receipt = {'id': take_id, 'shot_id': shot['id'], 'plan_id': plan['id'],
                           'status': 'submitting', 'created_at': time.time(),
                           'request_sha256': request['request_sha256'], 'audio_route': 'h3_native_joint',
                           'video_engine': request['video_engine'], 'release_approved': False}
                write(receipt_path, receipt)
                try:
                    response = api(cfg, '/v1/videos', payload)
                except urllib.error.HTTPError as error:
                    if 400 <= error.code < 500:
                        receipt.update(status='rejected_before_enqueue', error=error.read().decode())
                        write(receipt_path, receipt)
                    raise
                receipt.update(status='submitted', prompt_id=response['id'])
                write(receipt_path, receipt)
            write(base / 'progress.json', {'status': 'generating', 'shot': shot['id'], 'take_id': take_id,
                'prompt_id': receipt['prompt_id'], 'completed': position, 'total': len(shots),
                'worker_pid': os.getpid(), 'backend': 'fastvideo', 'steps_total': 8,
                'first_cut': not screening, 'started_at': receipt['created_at'],
                'plan_path': str(plan_path.relative_to(root)), 'updated_at': time.time()})
            print('SUBMITTED_FASTVIDEO', shot['id'], receipt['prompt_id'], flush=True)
            started = time.monotonic()
            while True:
                check_paused()
                status = api(cfg, '/v1/videos/' + receipt['prompt_id'])
                write(folder / 'fastvideo_history.json', status)
                if status['status'] == 'completed':
                    break
                if status['status'] == 'failed':
                    receipt.update(status='failed', error=status.get('error'))
                    write(receipt_path, receipt)
                    raise RuntimeError('FastVideo generation failed: ' + str(status.get('error')))
                if time.monotonic() - started > 3600:
                    raise TimeoutError('FastVideo candidate exceeded one hour; job ID retained')
                time.sleep(5)
            url = cfg['fast_h3_omni']['api_url'].rstrip('/') + '/v1/videos/' + receipt['prompt_id'] + '/content'
            with urllib.request.urlopen(url, timeout=120) as source, (folder / 'native.mp4').open('wb') as target:
                import shutil
                shutil.copyfileobj(source, target)
            subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'native.mp4'), '-vn',
                            '-c:a', 'flac', str(folder / 'native_audio.flac')], check=True, timeout=120)
            qc = technical_qc(folder / 'native.mp4', request['frames'],
                              request['generation']['width'], request['generation']['height'])
            write(folder / 'technical_qc.json', qc)
            receipt.update(status='rendered_pending_review', completed_at=time.time(),
                           video_sha256=file_hash(folder / 'native.mp4'),
                           native_audio_sha256=file_hash(folder / 'native_audio.flac'), technical_qc=qc,
                           native_audio_provenance='decoded original FastVideo MP4 soundtrack',
                           human_listened=False, av_sync_review={'status': 'not_evaluated'},
                           narrative_review={'status': 'not_evaluated'})
            write(receipt_path, receipt)
            if not qc['passed']:
                raise RuntimeError('FastVideo technical QC failed: ' + str(qc['errors']))
            if screening:
                complete_screening(folder, receipt)
            else:
                receipt['speech_screening'] = {'passed': None, 'status': 'deferred_until_full_first_cut'}
                write(receipt_path, receipt)
            records[shot['id']] = take_id
            write(manifest, {'plan_id': plan['id'], 'takes': records, 'release_approved': False})
            print('FASTVIDEO_CANDIDATE', shot['id'], take_id, flush=True)
        write(manifest, {'plan_id': plan['id'], 'takes': records, 'release_approved': False})
        write(base / 'progress.json', {'status': 'candidates_ready', 'completed': len(shots),
            'total': len(shots), 'plan_path': str(plan_path.relative_to(root)),
            'updated_at': time.time(), 'release_approved': False})
    return manifest


def produce(root, plan_path, seed):
    from .v2.chapter_edit import chapter_timeline
    from .v2.edit import export_review
    from .v2.narrative import preflight
    from .safety import check_paused
    check_paused()
    root, plan_path = Path(root).resolve(), Path(plan_path).resolve()
    base = plan_path.parent
    with locked(root, 'cinema_production'):
        state = {'status': 'shooting', 'runtime': 'FastVideo NVFP4 QAD',
                 'plan_path': str(plan_path.relative_to(root)), 'worker_pid': os.getpid(),
                 'release_approved': False, 'started_at': time.time()}
        write(base / 'production.json', state)
        try:
            selected_takes = read(run(root, plan_path, None, seed, screening=False))['takes']
            progress = read(base / 'progress.json')
            progress.update(status='editing', worker_pid=os.getpid(), backend='fastvideo', updated_at=time.time())
            write(base / 'progress.json', progress)
            timeline = chapter_timeline(root, plan_path, selected_takes, base / 'editorial_blueprint.json', first_cut=True)
            timeline['narrative_check'] = preflight(root, plan_path, timeline)
            write(base / 'chapter_review_timeline.json', timeline)
            review = export_review(root, timeline)
            state.update(status='chapter_review_ready', review=review, takes=selected_takes,
                completed_at=time.time(), audio_screening_warnings=timeline.get('audio_screening_warnings', []),
                human_listened=False, human_understood_story=False)
            write(base / 'production.json', state)
            progress.update(status='chapter_review_ready', updated_at=time.time())
            write(base / 'progress.json', progress)
            return review
        except Exception as error:
            state.update(status='failed', error=str(error)[-4000:], updated_at=time.time())
            write(base / 'production.json', state)
            progress_path = base / 'progress.json'
            progress = read(progress_path) if progress_path.exists() else {}
            progress.update(status='failed', error=state['error'], plan_path=state['plan_path'],
                            backend='fastvideo', updated_at=time.time())
            write(progress_path, progress)
            raise
