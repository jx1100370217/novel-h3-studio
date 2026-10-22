"""Produce one complete chapter as immutable candidates and an unapproved edit."""
import copy
import os
import shutil
import subprocess
import time
from pathlib import Path

from ..comfy import api, config, schema_check
from ..project import digest, file_hash, inside, locked, read, write
from ..safety import REPO, check_paused, user_service_env
from .compiler import compile_shot, pinned_models
from .runner import output_file, run, reuse_candidate


def phase(root, base, source_plan, status, **details):
    write(base / 'progress.json', dict(status=status,
        worker_pid=os.getpid(),
        plan_path=str(source_plan.relative_to(root)), audio_route='h3_audio_conditioned',
        updated_at=time.time(), release_approved=False, **details))


def job(command, log, *, cpu=False, timeout=1800):
    log.parent.mkdir(parents=True, exist_ok=True)
    if cpu:
        command = ['systemd-run', '--user', '--wait', '--collect', '--pipe',
            '--unit', 'novel-h3-chapter-audio-' + str(time.time_ns()),
            '--slice', 'novel-h3-audio.slice', '--property=MemoryMax=12G',
            '--property=OOMPolicy=kill', '--setenv=CUDA_VISIBLE_DEVICES=',
            '--working-directory', str(REPO), '--', *map(str, command)]
    with log.open('w') as output:
        result = subprocess.run(list(map(str, command)), cwd=REPO, env=user_service_env(),
            stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
    return result.returncode


def roundtrip(root, manifest_path):
    """Resume one small Comfy batch without resubmitting an uncertain job."""
    cfg = config(root)
    manifest = read(manifest_path)
    avae_sha = pinned_models(root, cfg)['audio_vae']['sha256']
    pending = []
    for entry in manifest['entries']:
        target, previous = entry['target'], entry.get('audio_vae_roundtrip', {})
        if (previous.get('source_target_sha256') == target['sha256']
                and previous.get('audio_vae_sha256') == avae_sha
                and previous.get('path') and inside(root, previous['path']).is_file()
                and file_hash(inside(root, previous['path'])) == previous.get('sha256')):
            continue
        pending.append(entry)
    if not pending:
        return
    nodes = {'1': {'class_type': 'VAELoader', 'inputs': {'vae_name': cfg['models']['audio_vae']}}}
    outputs = {}
    for index, entry in enumerate(pending):
        target = entry['target']
        source = inside(root, target['path'])
        if file_hash(source) != target['sha256']:
            raise ValueError('Target source changed before roundtrip')
        staged = 'novel_h3/cinema_v2/dialogue/' + target['sha256'] + '.wav'
        destination = inside(cfg['input_dir'], staged)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(source, destination)
        if file_hash(destination) != target['sha256']:
            raise ValueError('Staged target hash mismatch')
        a, b, c, d = [str(index * 10 + i) for i in (11, 12, 13, 14)]
        nodes.update({
            a: {'class_type': 'LoadAudio', 'inputs': {'audio': staged}},
            b: {'class_type': 'VAEEncodeAudio', 'inputs': {'audio': [a, 0], 'vae': ['1', 0]}},
            c: {'class_type': 'VAEDecodeAudio', 'inputs': {'samples': [b, 0], 'vae': ['1', 0]}},
            d: {'class_type': 'SaveAudio', 'inputs': {'audio': [c, 0], 'filename_prefix':
                f"novel_h3/cinema_v2/chapter_roundtrip/{entry['shot_id']}_{target['sha256'][:16]}"}},
        })
        outputs[entry['shot_id']] = d
    errors = schema_check(nodes, api(cfg['comfy_url'], '/object_info'))
    if errors:
        raise ValueError('Roundtrip graph invalid: ' + str(errors))
    receipt_path = manifest_path.parent / ('roundtrip_' + digest(nodes)[:16] + '.json')
    receipt = read(receipt_path) if receipt_path.exists() else {}
    with locked(root, 'batch'):
        check_paused()
        if not receipt.get('prompt_id'):
            if receipt.get('status') == 'submitting':
                raise RuntimeError('Audio submission outcome unknown; inspect Comfy history before retrying')
            queue = api(cfg['comfy_url'], '/queue')
            if queue['queue_running'] or queue['queue_pending']:
                raise RuntimeError('Comfy queue is busy')
            write(receipt_path, {'status': 'submitting', 'graph': nodes})
            response = api(cfg['comfy_url'], '/prompt', {'prompt': nodes, 'client_id': receipt_path.stem})
            receipt = {'status': 'submitted', 'prompt_id': response['prompt_id'], 'graph': nodes}
            write(receipt_path, receipt)
        deadline = time.monotonic() + 1200
        try:
            while True:
                check_paused()
                history = api(cfg['comfy_url'], '/history/' + receipt['prompt_id']).get(receipt['prompt_id'])
                if history:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError('Chapter audio VAE batch deadline exceeded')
                time.sleep(5)
        except BaseException:
            queue = api(cfg['comfy_url'], '/queue')
            if any(row[1] == receipt['prompt_id'] for row in queue.get('queue_running', [])):
                api(cfg['comfy_url'], '/interrupt', {})
            raise
        receipt.update(history=history, status=history.get('status', {}).get('status_str'))
        write(receipt_path, receipt)
        if receipt['status'] != 'success':
            raise RuntimeError('Chapter audio VAE batch failed')
        for entry in pending:
            destination = manifest_path.parent / 'roundtrip' / (
                entry['shot_id'] + '_' + entry['target']['sha256'][:16] + '.flac')
            destination.parent.mkdir(exist_ok=True)
            shutil.copy2(output_file(cfg, history, outputs[entry['shot_id']], '.flac'), destination)
            entry['audio_vae_roundtrip'] = {'path': str(destination.relative_to(root)),
                'sha256': file_hash(destination), 'source_target_sha256': entry['target']['sha256'],
                'audio_vae_sha256': avae_sha, 'prompt_id': receipt['prompt_id'], 'human_listened': False}
        write(manifest_path, manifest)


def freeze_plan(root, source_path, audio_manifest):
    source = read(source_path)
    audio = read(audio_manifest)
    entries = {e['shot_id']: e for e in audio['entries']}
    has_dialogue = any(shot.get('spoken_lines') for shot in source['shots'])
    plan = copy.deepcopy(source)
    plan.update(id=source.get('production_id', source['id'] + '_production'), status='production_candidates',
        native_dialogue_required=False,
        audio_route='h3_audio_conditioned' if has_dialogue else 'h3_native_joint',
        source_plan_sha256=file_hash(source_path), release_approved=False,
        reused_takes=dict(source.get('reused_takes', {})))
    pilot_path = source_path.parent / 'p03_audio_conditioned_canary.json'
    pilot = read(pilot_path) if pilot_path.is_file() else None
    for index, shot in enumerate(plan['shots']):
        lines = shot.get('spoken_lines', [])
        if not lines:
            continue
        if shot['id'] in plan['reused_takes']:
            # compile_shot/reuse_candidate below verify the unchanged input and native media.
            continue
        entry = entries[shot['id']]
        expected = ''.join(line['text'] for line in lines)
        if expected != entry['expected_text'] or {l['speaker'] for l in lines} != {entry['speaker_asset_id']}:
            raise ValueError('Dialogue target differs from the final script: ' + shot['id'])
        if shot['id'] == 'P03' and pilot and entry.get('reused_from_manifest'):
            replacement = copy.deepcopy(pilot['shots'][0])
            if replacement['audio_target']['sha256'] == entry['target']['sha256']:
                plan['shots'][index] = replacement
                plan['reused_takes']['P03'] = 'production_v2/chapter_s0002/takes/c_8b11a7017faaf8a9'
                continue
        shot['duration_seconds'] = entry['timing']['generated_clip_seconds']
        for line in lines:
            line['start_seconds'] = entry['timing']['lead_seconds']
        shot['audio_target'] = dict(entry['target'], text=expected, speaker=entry['speaker_asset_id'],
            provenance=entry['provenance'], source_reference=entry['source_reference'],
            source_manifest=str(audio_manifest.relative_to(root)))
    return plan


def produce(root, source_plan, seed):
    from ..fastvideo import selected, produce as produce_fastvideo
    if selected(config(root)):
        return produce_fastvideo(root, source_plan, seed)
    root, source_plan = Path(root).resolve(), Path(source_plan).resolve()
    if not source_plan.is_relative_to(root):
        raise ValueError('Chapter plan must belong to this project')
    base, cfg = source_plan.parent, config(root)
    audio = base / 'chapter_audio/manifest.json'
    logs = base / 'production_logs'
    state_path = base / 'production.json'
    state = {'status': 'starting', 'started_at': time.time(), 'seed': seed, 'source_plan': str(source_plan.relative_to(root)),
             'release_approved': False, 'human_listened': False}
    with locked(root, 'cinema_production'):
        from .narrative import preflight
        preflight(root, source_plan)
        from .cinematization import require
        require(root, read(source_plan))
        write(state_path, state)
        try:
            check_paused()
            queue = api(cfg['comfy_url'], '/queue')
            if queue['queue_running'] or queue['queue_pending']:
                raise RuntimeError('Another Comfy generation is active')
            source = read(source_plan)
            if not any(shot.get('spoken_lines') for shot in source['shots']):
                write(audio, {'schema': 'cinema_chapter_audio_v1',
                    'plan_path': str(source_plan.relative_to(root)), 'plan_sha256': file_hash(source_plan),
                    'plan_id': source['id'], 'status': 'no_dialogue', 'total_shots': len(source['shots']),
                    'dialogue_shots': 0, 'entries': [], 'audio_route': 'h3_native_joint',
                    'approved': False, 'human_listened': False, 'release_approved': False})
            else:
                for attempt in range(3):
                    checks = audio.with_name('manifest.speech_check.json')
                    if checks.exists():
                        archive = audio.parent / 'checks' / f'speech_check_{time.time_ns()}.json'
                        archive.parent.mkdir(exist_ok=True)
                        shutil.copy2(checks, archive)
                    queue = api(cfg['comfy_url'], '/queue')
                    if queue['queue_running'] or queue['queue_pending']:
                        raise RuntimeError('Another Comfy generation is active before voice preparation')
                    api(cfg['comfy_url'], '/free', {'unload_models': True, 'free_memory': True})
                    time.sleep(3)
                    phase(root, base, source_plan, 'dialogue_preparation', note='逐角色准备全章白话对白，保留原始音频；P03可复用。')
                    needed = [s['id'] for s in source['shots'] if s.get('spoken_lines')
                              and s['id'] not in source.get('reused_takes', {})]
                    command = [REPO / '.venv-dialogue/bin/python', REPO / 'scripts/prepare_chapter_audio.py',
                        '--project', root, '--plan', source_plan, '--execute', '--seed', seed + attempt * 100]
                    if source.get('reused_takes') and needed:
                        command += ['--shots', *needed]
                    if source.get('reused_takes') and not needed:
                        if not audio.is_file():
                            raise ValueError('Reused dialogue needs its existing audio manifest')
                        result = 0
                    else:
                        result = job(command, logs / f'tts_{attempt}.log')
                    if result:
                        if attempt == 2:
                            raise RuntimeError('Dialogue preparation failed; original audio retained, see production logs')
                        continue
                    phase(root, base, source_plan, 'audio_roundtrip', note='使用同一H3音频VAE核对全章对白重建。')
                    roundtrip(root, audio)
                    phase(root, base, source_plan, 'dialogue_screening', note='CPU一次加载识别模型核对全部目标与H3重建对白。')
                    result = job([REPO / '.venv-audio/bin/python', REPO / 'scripts/check_dialogue_batch_strict.py', root, audio],
                        logs / f'audio_screen_{attempt}.log', cpu=True)
                    if result == 0:
                        break
                    if attempt == 2:
                        raise RuntimeError('Dialogue checks remain unresolved; not rendering known incorrect words')
            plan_path = base / 'chapter_production_plan.json'
            plan = freeze_plan(root, source_plan, audio)
            if plan_path.exists() and read(plan_path) != plan:
                raise ValueError('Frozen production plan changed; start an explicit new revision')
            write(plan_path, plan)
            require(root, plan)
            preflight(root, plan_path)
            # Validate every actual reference/model input before the first expensive shot.
            for index, shot in enumerate(plan['shots']):
                request = compile_shot(root, plan, shot, seed + index)
                if shot['id'] in plan['reused_takes']:
                    reuse_candidate(root, plan['reused_takes'][shot['id']], request)
            state.update(status='shooting', plan_path=str(plan_path.relative_to(root)), total=len(plan['shots']))
            write(state_path, state)
            selected = {}
            pending = None
            for attempt in range(3):
                batch = read(run(root, plan_path, pending, seed + attempt * 1000))
                selected.update(batch['takes'])
                pending = [s['id'] for s in plan['shots']
                    if s.get('spoken_lines') and read((inside(root, plan['reused_takes'][s['id']])
                        if s['id'] in plan['reused_takes'] else base / 'takes' / selected[s['id']])
                        / 'take.json')['speech_screening'].get('passed') is not True]
                audio_warnings = [s['id'] for s in plan['shots'] if not s.get('spoken_lines')
                    and read((inside(root, plan['reused_takes'][s['id']])
                        if s['id'] in plan['reused_takes'] else base / 'takes' / selected[s['id']])
                        / 'take.json')['speech_screening'].get('passed') is not True]
                state.update(takes=selected, unresolved_speech=pending, render_attempt=attempt + 1)
                state['audio_screening_warnings'] = audio_warnings
                write(state_path, state)
                if not pending:
                    break
                if attempt == 2:
                    raise RuntimeError('Rendered speech checks need targeted rework: ' + ', '.join(pending))
            phase(root, base, plan_path, 'editing', note='依据实际对白和动作帧构建初剪；未批准电影质量。')
            from .chapter_edit import chapter_timeline
            from .edit import export_review
            timeline = chapter_timeline(root, plan_path, selected, base / 'editorial_blueprint.json')
            if 'narrative_check' not in timeline:
                timeline['narrative_check'] = preflight(root, plan_path, timeline)
            write(base / 'chapter_review_timeline.json', timeline)
            review = export_review(root, timeline)
            state.update(status='chapter_review_ready', review=review,
                         audio_screening_warnings=timeline.get('audio_screening_warnings', []),
                         narrative_check=timeline.get('narrative_check'),
                         narrative_review_status=timeline.get('narrative_review_status', 'passed'),
                         completed_at=time.time())
            write(state_path, state)
            phase(root, base, plan_path, 'chapter_review_ready', completed=len(plan['shots']),
                total=len(plan['shots']), review_video=review['video'],
                audio_screening_warnings=timeline.get('audio_screening_warnings', []),
                narrative_review_status=timeline.get('narrative_review_status', 'passed'),
                note='全章审片版已导出；叙事帧区间或视觉证据未通过的项目保留为审片警示，无对白镜头的语音筛查警示待人工判断；剧情、表演、连续性、声音与文字读屏均未验收。')
            return review
        except BaseException as exc:
            state.update(status='failed', error=str(exc), updated_at=time.time())
            write(state_path, state)
            active_plan = base / 'chapter_production_plan.json'
            phase(root, base, active_plan if active_plan.exists() else source_plan, 'failed', error=str(exc))
            raise
