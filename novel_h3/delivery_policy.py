"""Normal shots auto-pass; retakes and assembled chapters have separate reviews."""
from pathlib import Path
import time
from .project import read, write, inside, file_hash, load_state, update_state, locked


def finish_shot(root, take_id, retake=False):
    root = Path(root)
    take = load_state(root)['takes'][take_id]
    if retake:
        update_state(root, lambda s: s['takes'][take_id].update(review_required='manual_retake', approval_method=None))
        return None
    if take.get('status') not in ('rendered', 'approved') or not take.get('qc', {}).get('passed'):
        raise ValueError('普通镜头需完成媒体技术检查后才能自动通过')
    if file_hash(inside(root, take['video'])) != take['video_sha256']:
        raise ValueError('镜头文件已变化')
    update_state(root, lambda s: s['takes'][take_id].update(
        status='approved', approval_method='automatic_normal_queue',
        review={'reviewer':'automatic_normal_queue', 'note':'用户指定普通队列自动通过；保留转写异常记录，章节成片待用户观看验收。', 'checks':{}},
        automatically_approved_at=time.time()))
    return maybe_assemble(root, take['episode'])


def maybe_assemble(root, episode_id):
    from .comfy import current_takes
    from .media import assemble_chapter
    root = Path(root)
    with locked(root, 'delivery'):
        ep = read(root/'episodes'/f'{episode_id}.json')
        rows = current_takes(root, ep)
        if not rows or any(not t or t.get('status') != 'approved' for _, _, t in rows):
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
            if old.get('take_ids') == ids and old.get('sha256') == file_hash(media):
                return str(media)
        return assemble_chapter(root, section)


def approve_chapter_video(root, section, sha256, reviewer='user'):
    from .media import assemble_latest
    root = Path(root)
    from .project import safe_id
    section = safe_id(section)
    with locked(root, 'delivery'):
        receipt = root/'chapter_videos'/f'chapter_{section}.json'
        video = receipt.with_suffix('.mp4')
        data = read(receipt)
        if not sha256 or data.get('sha256') != sha256 or file_hash(video) != sha256:
            raise ValueError('章节视频已更新，请观看最新版本后验收')
        data.update(chapter_review={'approved':True, 'reviewer':reviewer, 'sha256':sha256, 'time':time.time()}, release_approved=True)
        write(receipt, data)
        receipts = list((root/'chapter_videos').glob('*.json'))
        if not load_state(root).get('invalidated_chapters') and all(read(p).get('chapter_review',{}).get('approved') and read(p).get('chapter_review',{}).get('sha256') == read(p).get('sha256') for p in receipts):
            return {'approved':True, 'cumulative':assemble_latest(root)}
        return {'approved':True, 'cumulative':'等待其余章节视频人工验收'}
