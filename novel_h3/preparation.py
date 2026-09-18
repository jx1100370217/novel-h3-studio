"""Chapter preparation actions; drafts never masquerade as reviewed material."""
from pathlib import Path
import time
from .project import read, write, safe_id, locked


def chapter_id(root, episode):
    cid = safe_id(episode.removeprefix('chapter_'))
    if cid not in {c['id'] for c in read(Path(root)/'book.json')['chapters']}:
        raise ValueError('章节不存在')
    return cid


def _review_payload(root, episode):
    """Return the concrete script and storyboard material shown at the gate."""
    root = Path(root)
    plan_path = root / 'content_plans' / f'{episode}.json'
    if not plan_path.exists():
        return None
    plan = read(plan_path)
    visual_path = root / 'analysis' / f'{episode}_speaker_visual.json'
    visual = read(visual_path) if visual_path.exists() else {}
    visual_by_id = {row.get('scene_id'): row for row in visual.get('scenes', [])}
    episode_path = root / 'episodes' / f'{episode}.json'
    compiled = read(episode_path) if episode_path.exists() else {}
    shot_by_id = {row.get('id'): row for row in compiled.get('shots', [])}
    audit = plan.get('speaker_audit', {}).get('scenes', {})
    rows = []
    dialogue_count = 0
    durations = []
    speakers = set()
    for scene in plan.get('script', {}).get('scenes', []):
        sid = scene.get('scene_id')
        visual_row = visual_by_id.get(sid, {})
        h3 = visual_row.get('h3', {}) if isinstance(visual_row, dict) else {}
        shot = shot_by_id.get(sid, {})
        shot_frames = shot.get('frames')
        continuity = shot.get('continuity')
        actual_seconds = None
        if isinstance(shot_frames, (int, float)):
            actual_seconds = (shot_frames - (22 if continuity == 'continue' else 0)) / 24
        utterances = []
        for index, line in enumerate(scene.get('utterances', [])):
            speaker = line.get('speaker') or '未确认'
            if line.get('kind') == 'dialogue':
                dialogue_count += 1
                speakers.add(speaker)
            record = (audit.get(sid) or [])[index] if index < len(audit.get(sid, [])) else {}
            utterances.append({
                'kind': line.get('kind'), 'speaker': speaker,
                'text': line.get('text', ''), 'reason': record.get('reason', '')
            })
        duration = scene.get('duration_seconds')
        if isinstance(duration, (int, float)):
            durations.append(float(duration))
        rows.append({
            'scene_id': sid,
            'duration_seconds': duration,
            'actual_seconds': round(actual_seconds, 2) if actual_seconds is not None else None,
            'source_text': scene.get('source_text', ''),
            'scene_description': scene.get('scene_description', ''),
            'visual_narration': scene.get('visual_narration', ''),
            'characters': scene.get('characters_in_scene', []),
            'scenes': scene.get('scenes', []),
            'props': scene.get('props', []),
            'action': h3.get('action') or shot.get('action', ''),
            'camera': h3.get('camera') or shot.get('camera', {}),
            'continuity': h3.get('continuity') or continuity or 'cut',
            'soundscape': h3.get('soundscape') or shot.get('soundscape', ''),
            'utterances': utterances,
        })
    return {
        'title': plan.get('script', {}).get('title', episode),
        'dramatic_question': plan.get('dramatic_question', ''),
        'turning_point': plan.get('turning_point', ''),
        'scene_count': len(rows),
        'dialogue_count': dialogue_count,
        'speakers': sorted(speakers),
        'planned_seconds': round(sum(durations), 2),
        'max_planned_seconds': max(durations, default=0),
        'audio_policy': '仅生成人物对白；旁白和 visual_narration 只作画面参考，不生成声音。',
        'rhythm_review': plan.get('rhythm_review', {}),
        'speaker_audit': plan.get('speaker_audit', {}),
        'rows': rows,
    }


def readiness(root, episode):
    from start_next_chapter_when_ready import _chapter_requirements
    root = Path(root)
    cid = chapter_id(root, episode)
    episode = 'chapter_' + cid
    missing = []
    for path, reason in [(root/'content_plans'/f'{episode}.json', 'script_missing'),
                         (root/'analysis'/f'{episode}_speaker_visual.json', 'visual_missing')]:
        if not path.exists():
            missing.append({'reason': reason})
    if not missing:
        try:
            missing = _chapter_requirements(root, episode)[2]
        except (ValueError, KeyError, OSError) as exc:
            missing = [{'reason': 'chapter_material_missing', 'details': str(exc)}]
    # Include candidate asset/voice gaps even before the formal script exists.
    if any(b['reason'] == 'script_missing' for b in missing):
        draft = root/'analysis/full_book_workorders'/f'{cid}.json'
        if draft.exists():
            value = read(draft)
            from .project import load_state
            state = load_state(root)
            for aid in sorted({a for s in value['scenes'] for a in s.get('asset_ids', [])}):
                if aid not in state['assets']:
                    missing.append({'asset': aid, 'reason': 'image_not_registered'})
            if value.get('speaker_unresolved_quotes'):
                missing.append({'reason': 'speaker_audit_pending', 'details': f"{value['speaker_unresolved_quotes']} 处对白需对照原文确认说话人"})
    return {'episode': episode, 'status': 'waiting' if missing else 'ready',
            'blockers': missing, 'time': time.time(),
            'review': _review_payload(root, episode),
            'draft': f'analysis/full_book_workorders/{cid}.json' if (root/'analysis/full_book_workorders'/f'{cid}.json').exists() else None}


def prepare(root, episode, kind, asset=None):
    """Create a real draft or an auditable image-tool handoff, idempotently."""
    root = Path(root)
    cid = chapter_id(root, episode)
    with locked(root, 'preparation'):
        if kind == 'script':
            from continue_preparation import _write_candidate
            chapters = read(root/'book.json')['chapters']
            chapter = next(c for c in chapters if c['id'] == cid)
            paragraphs = [p for p in read(root/'paragraphs.json') if p['section'] == cid]
            _write_candidate(chapter, paragraphs, read(root/'bible/assets.json'), read(root/'bible/voices.json'), output_dir=root/'analysis/full_book_workorders')
            return {'status': 'draft_created', 'message': '已生成原文、说话人候选、灵活时长及视觉工作单；待逐句核对后进入正式生成。',
                    'path': f'analysis/full_book_workorders/{cid}.json'}
        if kind != 'image':
            raise ValueError('不支持的补充类型')
        aid = safe_id(asset or '')
        inventory = read(root/'bible/assets.json')
        found = [(bucket, name, item) for bucket in ('characters','scenes','props')
                 for name,item in inventory.get(bucket, {}).items() if item['id'] == aid]
        if not found:
            raise ValueError('请先登记该资产的原文依据与设计')
        from .director import image_job, gender_prompt
        bucket, name, item = found[0]
        job_path = root/'jobs'/f'image_{aid}.json'
        if not job_path.exists():
            refs = [item['identity_reference_asset_id']] if item.get('identity_reference_asset_id') else []
            gender = (f"\nVisual-only gender lock: {gender_prompt(item.get('gender', '未知'))}. "
                       "Never speak or subtitle this metadata.") if bucket == 'characters' else ''
            image_job(root, aid, f"{read(root/'config.json')['style']}\nAsset: {name}\nSource: {item['source_facts']}\nDesign: {item['design_description']}" + gender + "\nSingle cinematic reference image. No text or watermark.", refs, {'characters':'character','scenes':'scene','props':'prop'}[bucket])
        job = read(job_path)
        request = {'asset': aid, 'episode': 'chapter_'+cid, 'status': 'awaiting_codex_image_tool',
                   'requested_at': time.time(), 'job': job,
                   'instruction': '请在当前 Codex 对话调用 image_gen，记录实际提示词、工具返回文件和真实模型元数据。网页不能自行调用订阅工具。'}
        write(root/'preparation_requests'/f'image_{aid}.json', request)
        return {'status': request['status'], 'message': '已登记图片补充任务，等待当前 Codex 图片工具执行；尚未生成图片。',
                'path': f'preparation_requests/image_{aid}.json', 'job': job}
