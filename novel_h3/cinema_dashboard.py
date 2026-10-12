"""Project the current chapter and its repair batches into read-only UI data."""
import json
import time
from pathlib import Path

from .project import inside, read


def _optional(path):
    return read(path) if path.is_file() else {}


def _artifact(root, label, path):
    if path is None:
        return None
    path = Path(path)
    if not path.is_file():
        return None
    try:
        relative = path.resolve().relative_to(Path(root).resolve())
    except ValueError:
        return None
    return {'label': label, 'path': relative.as_posix(), 'format': path.suffix.lower().lstrip('.')}


def _last_resource(path):
    if not path.is_file():
        return None
    with path.open('rb') as source:
        source.seek(max(0, path.stat().st_size - 8192))
        lines = source.read().decode(errors='replace').splitlines()
    for line in reversed(lines):
        try:
            data = json.loads(line)
            if 'time' in data:
                return data
        except ValueError:
            continue
    return None


def enrich(root, progress_path, active_plan, data):
    root, base = Path(root).resolve(), Path(progress_path).resolve().parent
    worker_alive = None
    if data.get('worker_pid'):
        try:
            command = Path(f"/proc/{int(data['worker_pid'])}/cmdline").read_bytes()
            worker_alive = str(root.resolve()).encode() in command
        except (FileNotFoundError, ProcessLookupError):
            worker_alive = False
        if worker_alive is False and data['status'] in ('generating', 'speech_screening', 'editing',
                'dialogue_preparation', 'dialogue_screening', 'audio_roundtrip'):
            data.update(status='interrupted', stage='制作进程已停止，状态记录尚未完成',
                        error='制作进程已退出，请查看执行日志。')
    state = _optional(base / 'production.json')
    canonical_path = inside(root, state['plan_path']) if state.get('plan_path') else base / 'chapter_production_plan.json'
    if not canonical_path.is_file() and data.get('plan_path'):
        canonical_path = inside(root, data['plan_path'])
    canonical = _optional(canonical_path) or active_plan
    canonical_id, active_id = canonical['id'], active_plan['id']
    is_repair = active_id != canonical_id and bool(state)
    selected = {}
    runs = sorted((base / 'runs').glob('*.json'), key=lambda p: p.stat().st_mtime)
    for path in runs:
        run = read(path)
        if run.get('plan_id') == canonical_id:
            selected.update(run.get('takes', {}))
    selected.update(state.get('takes', {}))
    for path in runs:
        run = read(path)
        if run.get('plan_id') == active_id and is_repair:
            selected.update(run.get('takes', {}))
    for sid, relative in canonical.get('reused_takes', {}).items():
        selected.setdefault(sid, Path(relative).name)
    receipts = {}
    attempts = {}
    accepted_plans = {canonical_id, active_id}
    for path in (base / 'takes').glob('*/take.json'):
        item = read(path)
        if item.get('plan_id') not in accepted_plans and item.get('id') not in selected.values():
            continue
        receipts[item['id']] = (path.parent, item)
        attempts[item['shot_id']] = attempts.get(item['shot_id'], 0) + 1
    for relative in canonical.get('reused_takes', {}).values():
        folder = inside(root, relative)
        if (folder / 'take.json').is_file():
            item = read(folder / 'take.json')
            if item['id'] not in receipts:
                receipts[item['id']] = (folder, item)
                attempts[item['shot_id']] = attempts.get(item['shot_id'], 0) + 1
    scenes = {s.get('id'): s.get('title', s.get('id')) for s in canonical.get('scenes', [])}
    blueprint = _optional(base / 'editorial_blueprint.json')
    descriptions = {s['shot_id']: s for s in blueprint.get('entries', [])}
    rows = []
    for order, shot in enumerate(canonical['shots'], 1):
        sid, tid = shot['id'], selected.get(shot['id'])
        folder, receipt = receipts.get(tid, (None, {}))
        video = folder / 'native.mp4' if folder else None
        saved = bool(video and video.is_file() and receipt.get('technical_qc', {}).get('passed') is True)
        checked = receipt.get('speech_screening', {}).get('passed') if saved else None
        visual_rework = saved and receipt.get('visual_review', {}).get('status') == 'needs_rework'
        active = data.get('status') in ('generating', 'speech_screening') and data.get('shot') == sid
        row_status = ('generating' if active and data['status'] == 'generating' else
                      'screening' if active else 'needs_rework' if saved and (checked is False or visual_rework) else
                      'checked' if saved and checked is True else 'saved' if saved else
                      'failed' if receipt.get('status') == 'failed' else 'pending')
        scene_id = shot.get('narrative_scene_id', shot.get('scene_id'))
        title = descriptions.get(sid, {}).get('title') or shot.get('title') or shot.get('beat') or sid
        rows.append({'shot': sid, 'order': order, 'title': title, 'scene': scenes.get(scene_id, scene_id),
            'status': row_status, 'saved': saved, 'speech_passed': checked, 'visual_rework': visual_rework,
            'take_id': tid, 'attempts': attempts.get(sid, 0),
            'video': str(video.relative_to(root)) if saved else None,
            'contact': str((folder / 'analysis/contact.jpg').relative_to(root))
                       if folder and (folder / 'analysis/contact.jpg').is_file() else None,
            'report': str((folder / 'analysis/speech.json').relative_to(root))
                       if folder and (folder / 'analysis/speech.json').is_file() else None,
            'dialogue': ''.join(line['text'] for line in shot.get('spoken_lines', [])),
            'seconds': receipt.get('technical_qc', {}).get('seconds'),
            'completed_at': receipt.get('completed_at'), 'active': active,
            'error': receipt.get('error') if receipt.get('status') == 'failed' else None,
            'human_approved': receipt.get('release_approved') is True and receipt.get('human_listened') is True})
    counts = {'planned': len(rows), 'saved': sum(r['saved'] for r in rows),
        'sound_passed': sum(r['speech_passed'] is True for r in rows),
        'needs_rework': sum(r['speech_passed'] is False or r['visual_rework'] for r in rows),
        'sound_pending': sum(r['saved'] and r['speech_passed'] is None for r in rows),
        'human_approved': sum(r['human_approved'] for r in rows)}
    review = state.get('review', {})
    review_path = inside(root, review['video']) if review.get('video') else None
    review_ready = bool(review_path and review_path.is_file() and review.get('technical_qc', {}).get('passed') is True)
    narrative_review = state.get('narrative_review', {})
    rejected = (narrative_review.get('status') == 'rejected'
                and bool(narrative_review.get('video_sha256'))
                and narrative_review.get('video_sha256') == review.get('video_sha256'))
    review_approved = review_ready and not rejected and review.get('release_approved') is True and review.get('human_listened') is True
    phase = ('narrative_rework' if rejected or data['status'] == 'narrative_rework' else
             'shot_repair' if is_repair and data['status'] in ('generating','speech_screening') else
             'review_pending' if review_ready and not review_approved else
             'delivery' if review_approved else data['status'])
    phase_label = {'narrative_rework': '故事完整性返修 · 后续章节暂停', 'shot_repair': '定点重拍', 'review_pending': '整章待人工审片',
                  'cinematization': '剧本影视化 · 场景与动作承接',
                  'cinematization_ready': '影视化稿已准备 · 等待拍摄',
                  'delivery': '整章已验收', 'generating': '镜头拍摄', 'speech_screening': '声音核对',
                  'editing': '剪辑与文字合成', 'failed': '制作已停止', 'interrupted': '制作进程已停止',
                  'dialogue_preparation': '对白制作', 'dialogue_screening': '对白核对',
                  'audio_roundtrip': 'H3音频验证', 'candidates_ready': '候选待检查',
                  'quality_review': '制作质量复核', 'chapter_review_ready': '整章待人工审片'}.get(phase, phase)
    audio = _optional(base / 'chapter_audio/manifest.json')
    audio_prepared = sum(bool(e.get('target', {}).get('path')) for e in audio.get('entries', []))
    audio_total = audio.get('dialogue_shots', sum(bool(s.get('spoken_lines')) for s in canonical['shots']))
    audio_passed = data.get('audio_passed', 0)
    film_check = {}
    if canonical.get('cinematization_required'):
        from .v2.cinematization import require
        try:
            film_check = require(root, canonical)
        except (ValueError, OSError, KeyError) as exc:
            film_check = {'passed': False, 'error': str(exc)}
    stages = [
        {'id': 'script', 'title': '改编与故事完整性', 'status': 'active' if rejected else 'done', 'current': 0 if rejected else 1, 'total': 1, 'detail': '开场、关键因果与结尾需落实到观众交付；资料齐全不等于故事合格'},
        {'id': 'cinematization', 'title': '剧本影视化', 'status': 'done' if film_check.get('passed') else 'active' if data['status'] == 'cinematization' else 'failed' if film_check else 'pending', 'current': int(film_check.get('passed', False)), 'total': 1, 'detail': '场景目标、动作首尾、空间轴线和转场承接；生成使用绑定后的影视剧本'},
        {'id': 'dialogue', 'title': '角色与对白准备', 'status': 'done' if audio_passed == audio_total and audio_total else 'active', 'current': audio_passed, 'total': audio_total, 'detail': '对白目标与H3重建自动核对'},
        {'id': 'shots', 'title': '镜头拍摄', 'status': 'done' if counts['saved'] == len(rows) else 'active', 'current': counts['saved'], 'total': len(rows), 'detail': '保存候选，不等同影视验收'},
        {'id': 'checks', 'title': '声音复核与重拍', 'status': 'done' if counts['sound_passed'] == len(rows) else 'active', 'current': counts['sound_passed'], 'total': len(rows), 'detail': '仅针对问题镜头重拍，保留全部素材'},
        {'id': 'edit', 'title': '剪辑与文字合成', 'status': 'done' if review_ready else 'active' if data['status'] == 'editing' else 'failed' if data['status'] in ('failed','interrupted') and counts['sound_passed'] == len(rows) else 'pending', 'current': int(review_ready), 'total': 1, 'detail': '按实际帧与对白剪辑，准确合成原文文字'},
        {'id': 'review', 'title': '整章人工审片', 'status': 'failed' if rejected else 'done' if review_approved else 'active' if review_ready else 'pending', 'current': int(review_approved), 'total': 1, 'detail': '故事完整性已退回' if rejected else '剧情、表演、连贯性、声音与读屏审核'},
    ]
    active_folder = base / 'takes' / str(data.get('take_id', ''))
    resources = _last_resource(active_folder / 'resource_samples.jsonl')
    if not resources:
        paths = list((base / 'takes').glob('*/resource_samples.jsonl'))
        if paths:
            resources = _last_resource(max(paths, key=lambda p:p.stat().st_mtime))
    audit = _optional(base / 'narrative_audit.json')
    revised_script = inside(root, audit['revised_script']) if audit.get('revised_script') else None
    revised_check = _optional(inside(root, audit['revised_check'])) if audit.get('revised_check') else {}
    chapter_id = canonical.get('chapter_id', data.get('chapter_id', ''))
    episode_path = root / 'episodes' / f'{chapter_id}.json' if chapter_id else None
    film_path = None
    request_path = None
    source_plan_path = None
    source_script_path = None
    film_binding = canonical.get('cinematization', {})
    if film_binding.get('path'):
        try:
            film_path = inside(root, film_binding['path'])
            request_path = film_path.parent / 'cinematization_request.json'
            request = _optional(request_path)
            if request.get('source_plan_path'):
                source_plan_path = inside(root, request['source_plan_path'])
            if request.get('source_script_path'):
                source_script_path = inside(root, request['source_script_path'])
        except (ValueError, OSError):
            film_path = request_path = source_plan_path = source_script_path = None
    section_id = chapter_id.removeprefix('chapter_') if chapter_id else ''
    source_excerpt = base / 'source_text.md'
    if not source_excerpt.is_file() and source_plan_path:
        source_excerpt = source_plan_path.parent / 'source_text.md'
    if not source_excerpt.is_file() and section_id:
        source_excerpt = root / 'analysis' / f'{section_id}.md'
    narrative_files = [
        _artifact(root, '本章原文节选', source_excerpt),
        _artifact(root, '完整白话剧本', source_script_path or base / 'screenplay.md'),
        _artifact(root, '白话剧本故事结构', source_plan_path),
        _artifact(root, '原文事实与故事结构', root / 'analysis' / f'{section_id}.json' if section_id else base / 'story.json'),
        _artifact(root, '叙事合同', base / 'narrative_contract.json'),
        _artifact(root, '叙事预检报告', base / 'narrative_script_check.json'),
    ]
    cinematic_files = [
        _artifact(root, '影视化交接请求', request_path or base / 'cinematization_request.json'),
        _artifact(root, '影视化交接响应', film_path.parent / 'cinematization_response.json' if film_path else base / 'cinematization_response.json'),
        _artifact(root, '影视化剧本（Markdown）', film_path.parent / 'cinematic_screenplay.md' if film_path else base / 'cinematic_screenplay.md'),
        _artifact(root, '影视化剧本（JSON）', film_path),
        _artifact(root, '影视化绑定检查', film_path.parent / 'cinematization_check.json' if film_path else base / 'cinematization_check.json'),
        _artifact(root, '绑定后的全章拍摄计划', canonical_path),
        _artifact(root, '导演剪辑方案', base / 'editorial_blueprint.json'),
        _artifact(root, '实际执行分镜', episode_path) if episode_path else None,
        _artifact(root, '工作台进度记录', Path(progress_path)),
    ]
    model_files = [
        _artifact(root, 'VDN-H3 / Blender 配置快照', base / 'model_profile.json'),
        _artifact(root, '单轮生成记录', base / 'run_manifest.json'),
        _artifact(root, '单轮 worker 脚本', root / 'runtime/erzhongren_vdn_r2_video_worker.py'),
    ]
    shot_artifacts = []
    legacy_state = _optional(root / 'state.json').get('takes', {})
    legacy_by_shot = {}
    for take in legacy_state.values():
        if take.get('episode') == chapter_id and not take.get('retired'):
            old = legacy_by_shot.get(take.get('shot'))
            if old is None or take.get('created_at', 0) > old.get('created_at', 0):
                legacy_by_shot[take.get('shot')] = take
    row_by_shot = {row['shot']: row for row in rows}
    for shot in canonical.get('shots', []):
        sid = shot['id']
        row = row_by_shot.get(sid, {})
        shot_files = [_artifact(root, '绑定资产与最终 H3 提示词', root / 'execution_sheets' / str(chapter_id) / f'{sid}.json')]
        folder = receipts.get(row.get('take_id'), (None, {}))[0]
        folders = [folder] if folder else []
        if legacy_by_shot.get(sid):
            folders.append(root / 'renders' / legacy_by_shot[sid]['id'])
        for folder in folders:
            for label, name in (('本次 H3 执行单', 'h3_execution_sheet.json'),
                                ('实际 ComfyUI 输入图', 'prompt.json'),
                                ('语音绑定清单', 'speech_manifest.json'),
                                ('生成状态', 'status.json')):
                shot_files.append(_artifact(root, label, folder / name))
        preview_dir = root / 'previews' / 'blender_previs' / str(chapter_id) / sid
        if preview_dir.is_dir():
            for guide_dir in sorted(preview_dir.iterdir()):
                for name, label in (('scene_spec.json', 'Blender 白模场景规格'),
                                    ('guide.json', 'Blender 白模记录'),
                                    ('guide.mp4', 'Blender 白模视频')):
                    shot_files.append(_artifact(root, label, guide_dir / name))
        shot_files = list({item['path']: item for item in shot_files if item}.values())
        if shot_files:
            shot_artifacts.append({'shot': sid, 'title': row.get('title') or shot.get('title') or sid,
                                   'files': shot_files})
    blender_enabled = bool(_optional(root / 'config.json').get('blender_previs', {}).get('enabled'))
    spatial_files = []
    for shot in canonical.get('shots', []):
        sid = shot.get('id')
        preview_dir = root / 'previews' / 'blender_previs' / str(chapter_id) / str(sid)
        if preview_dir.is_dir():
            for guide_dir in sorted(preview_dir.iterdir()):
                for name, label in (('scene_spec.json', f'{sid} 白模场景规格'),
                                    ('guide.json', f'{sid} 白模记录'),
                                    ('guide.mp4', f'{sid} 白模参考视频')):
                    item = _artifact(root, label, guide_dir / name)
                    if item:
                        spatial_files.append(item)
    artifact_groups = [
        {'title': '原文与白话改编', 'files': [item for item in narrative_files if item]},
        {'title': '影视化剧本与镜头绑定', 'files': [item for item in cinematic_files if item]},
        {'title': '模型与空间参考', 'files': [item for item in model_files if item] + spatial_files,
         'note': ('Blender 白模预演已启用；下方镜头文件会列出实际输入 H3 的参考视频。'
                  if blender_enabled else '本章未启用 Blender 白模预演；H3 使用绑定的场景、人物与声音参考。')},
        {'title': '逐镜模型输入', 'shots': shot_artifacts},
    ]
    data.update(schema='cinema_dashboard_v1', available=True, title=canonical.get('title', canonical_id),
        chapter_id=canonical.get('chapter_id', base.name), plan_id=canonical_id,
        planned_total=len(rows), generated_shots=counts['saved'], counts=counts,
        phase=phase, phase_label=phase_label, stages=stages, shots=rows,
        active_batch={'title': active_plan.get('title', active_id), 'total': len(active_plan['shots']),
                      'completed': sum(r['saved'] and r['speech_passed'] is True for r in rows
                           if r['shot'] in {s['id'] for s in active_plan['shots']}), 'is_repair': is_repair},
        review={'ready': review_ready, 'approved': review_approved, 'video': review.get('video') if review_ready else None,
                'seconds': review.get('seconds'), 'subtitles': review.get('subtitles'),
                'technical_passed': review.get('technical_qc', {}).get('passed'), 'narrative_rejected': rejected},
        narrative={'review': narrative_review, 'issues': audit.get('issues', []),
                   'repair_summary': audit.get('repair_summary'), 'revised_check': revised_check},
        source_files={key: str(path.relative_to(root)) for key,path in {
            'script':base/'screenplay.md','story':base/'story.json','plan':canonical_path,
            'edit':base/'editorial_blueprint.json','timeline':base/'chapter_review_timeline.json',
            'cinematic_script':base/'cinematic_screenplay.md',
            'cinematic_check':base/'cinematization_check.json',
            'narrative_audit':base/'narrative_audit.json',
            **({'revised_script': revised_script} if revised_script else {})}.items() if path.is_file()},
        recent=sorted([r for r in rows if r['saved']], key=lambda r:r['completed_at'] or 0, reverse=True)[:6],
        audio_prepared=audio_prepared, audio_total=audio_total, audio_passed=audio_passed, resources=resources,
        resources_stale=bool(resources and time.time()-resources['time'] > 30),
        worker_alive=worker_alive, edit_progress=_optional(root / 'review_exports/progress.json'),
        cinematization=film_check,
        artifact_groups=artifact_groups,
        observed_at=time.time(), service_role='workbench', release_approved=review_approved)
    return data
