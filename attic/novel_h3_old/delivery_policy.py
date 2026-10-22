"""Keep rendered candidates separate from actual viewing and listening approval."""
from pathlib import Path
import time
from .project import read, write, inside, file_hash, load_state, update_state, locked


def take_review_gates(take):
    report = take.get('speech_check', {})
    timing = dict(report.get('speech_window_alignment') or {})
    if not timing and report.get('lip_sync_gate'):
        timing = dict(report['lip_sync_gate'])
        timing.update(measurement='legacy_audio_window_estimate', can_approve_av_sync=False)
    timing.setdefault('status', 'not_evaluated')
    av_sync = dict(take.get('av_sync_review') or report.get('av_sync_review') or {})
    av_reviewer = str(av_sync.get('reviewer', '')).strip()
    manual_av_sync = (
        av_sync.get('status') in ('passed', 'not_applicable')
        and av_sync.get('method') == 'human'
        and bool(av_reviewer) and not av_reviewer.startswith(('automatic_', 'auto_'))
        and bool(str(av_sync.get('note', '')).strip())
        and bool(take.get('video_sha256'))
        and av_sync.get('video_sha256') == take.get('video_sha256')
        and av_sync.get('video_examined') is True
        and av_sync.get('measurement') != 'audio_only'
    )
    av_sync['can_approve_av_sync'] = bool(manual_av_sync)
    if not manual_av_sync and av_sync.get('status') in ('passed', 'not_applicable'):
        av_sync['status'] = 'not_evaluated'
    av_sync.setdefault('status', 'not_evaluated')
    transcript_current = (bool(take.get('video_sha256'))
                          and report.get('video_sha256') == take.get('video_sha256'))
    return {
        'technical': {'status': 'passed' if take.get('qc', {}).get('passed') is True else 'blocked'},
        'transcript': {'status': 'passed' if report.get('passed') is True and transcript_current else 'blocked'},
        'speech_window_alignment': timing,
        'av_sync_review': av_sync,
    }


def require_final_reviews(take):
    """Validate evidence; callers must still verify the current media file hash."""
    from .comfy import REVIEW_ITEMS
    gates = take_review_gates(take)
    if gates['technical']['status'] != 'passed' or gates['transcript']['status'] != 'passed':
        raise ValueError('最终验收需要当前视频的技术检查和声音转写通过')
    if gates['speech_window_alignment']['status'] == 'blocked':
        raise ValueError('对白时间窗检查未通过，不能最终验收')
    if not gates['av_sync_review']['can_approve_av_sync']:
        raise ValueError('需要实际观看并听音的音画同步审核；音频时间窗检查不能证明嘴型正确')
    review = take.get('review', {})
    reviewer = str(review.get('reviewer', '')).strip()
    checks = review.get('checks', {})
    av_checked = (checks.get('av_sync') is True and gates['av_sync_review']['status'] == 'passed'
                  or checks.get('av_sync') == 'not_applicable' and gates['av_sync_review']['status'] == 'not_applicable')
    if (not reviewer or reviewer.startswith(('automatic_', 'auto_'))
            or not review.get('note')
            or not av_checked or not all(checks.get(k) is True for k in REVIEW_ITEMS if k != 'av_sync')):
        raise ValueError('最终验收需要全部实际观看和听音检查及审核人记录')
    return gates


def finish_shot(root, take_id, retake=False):
    root = Path(root)
    take = load_state(root)['takes'][take_id]
    if take.get('status') not in ('rendered', 'approved') or not take.get('qc', {}).get('passed'):
        raise ValueError('镜头需完成媒体技术检查后才能进入审阅')
    if file_hash(inside(root, take['video'])) != take['video_sha256']:
        raise ValueError('镜头文件已变化')
    gates = take_review_gates(take)
    if take.get('status') == 'approved':
        try:
            require_final_reviews(take)
        except ValueError:
            pass
        else:
            return maybe_assemble(root, take['episode'])
    pending = ['visual_review', 'audio_review', 'av_sync_review']
    reason = 'pending_reviews'
    if gates['transcript']['status'] != 'passed':
        pending.insert(0, 'transcript')
        reason = 'speech_qc_not_passed'
    if gates['speech_window_alignment']['status'] == 'blocked':
        pending.insert(0, 'speech_window_alignment')
        reason = 'speech_window_alignment_blocked'
    update_state(root, lambda s: s['takes'][take_id].update(
        status='rendered', approval_method=None, release_approved=False,
        review_required=reason, pending_reviews=pending, review_gates=gates,
        retake_review_required=bool(retake),
        retention_note='保留候选视频及诊断；技术和转写通过不代替实际观看、听音与音画同步审核。'))
    return {'take': take_id, 'status': 'rendered_pending_review', 'reason': reason,
            'pending_reviews': pending}


def maybe_assemble(root, episode_id):
    from .comfy import current_takes
    from .media import assemble_chapter
    root = Path(root)
    with locked(root, 'delivery'):
        ep = read(root/'episodes'/f'{episode_id}.json')
        rows = current_takes(root, ep)
        if not rows or any(not t or t.get('status') != 'approved' for _, _, t in rows):
            return None
        try:
            for _, _, take in rows:
                require_final_reviews(take)
        except ValueError:
            return None
        state = load_state(root)
        if any(q.get('episode') == episode_id and q.get('status') in ('queued','running') for q in state.get('rework_queue',{}).values()):
            return None
        section = episode_id.removeprefix('chapter_')
        receipt = root/'chapter_videos'/f'chapter_{section}.json'
        media = receipt.with_suffix('.mp4')
        ids = [t['id'] for _, _, t in rows]
        if receipt.exists() and media.exists():
            old = read(receipt)
            if not old.get('invalidated') and old.get('take_ids') == ids and old.get('sha256') == file_hash(media):
                return str(media)
        return assemble_chapter(root, section)


def approve_chapter_video(root, section, sha256, reviewer='user'):
    from .media import assemble_latest
    root = Path(root)
    from .project import safe_id
    section = safe_id(section)
    if not str(reviewer).strip() or str(reviewer).startswith(('automatic_', 'auto_')):
        raise ValueError('章节验收需记录实际审核人')
    with locked(root, 'delivery'):
        receipt = root/'chapter_videos'/f'chapter_{section}.json'
        video = receipt.with_suffix('.mp4')
        data = read(receipt)
        if data.get('invalidated') or section in load_state(root).get('invalidated_chapters', {}):
            raise ValueError('章节视频已因重拍失效，请审核重新合成的版本')
        state = load_state(root)
        if not data.get('take_ids'):
            raise ValueError('章节缺少可核验的镜头记录')
        for take_id in data.get('take_ids', []):
            take = state.get('takes', {}).get(take_id)
            if not take or take.get('status') != 'approved' or take.get('retired'):
                raise ValueError('章节包含未完成最终审核或已失效的镜头')
            require_final_reviews(take)
            if file_hash(inside(root, take['video'])) != take['video_sha256']:
                raise ValueError('章节源镜头已变化，请重新检查和合成')
        if not sha256 or data.get('sha256') != sha256 or file_hash(video) != sha256:
            raise ValueError('章节视频已更新，请观看最新版本后验收')
        data.update(chapter_review={'approved':True, 'reviewer':reviewer, 'sha256':sha256, 'time':time.time()}, release_approved=True)
        write(receipt, data)
        receipts = list((root/'chapter_videos').glob('*.json'))
        if not load_state(root).get('invalidated_chapters') and all(read(p).get('chapter_review',{}).get('approved') and read(p).get('chapter_review',{}).get('sha256') == read(p).get('sha256') for p in receipts):
            return {'approved':True, 'cumulative':assemble_latest(root)}
        return {'approved':True, 'cumulative':'等待其余章节视频人工验收'}
