"""Explicit video controls gated by the next chapter's preparation."""
import os,signal,subprocess,sys,time
from pathlib import Path
from .project import read,write,locked,update_state,load_state,inside
from .safety import PAUSE,REPO
from .comfy import api,config


class ChapterGateError(ValueError):
    """A chapter is not ready; carries the actions needed by the workbench."""

    def __init__(self, episode_id, blockers, assets=(), speakers=(), message=''):
        self.gate = {
            'status': 'waiting',
            'episode': episode_id,
            'blockers': blockers,
            'required_assets': len(assets),
            'required_speakers': sorted(speakers),
            'time': time.time(),
        }
        super().__init__(message)


def status(root):
    path=Path(root)/'analysis/video_activity.json'
    result=read(path) if path.exists() else {'status':'paused','message':'视频生成尚未启动。'}
    pid=result.get('worker_pid')
    try:
        # The worker may be launched with either an absolute path (the web
        # button) or a repository-relative path (manual/service restart).
        # Match the executable name so a live worker is not reported as
        # stopped merely because its argv spelling differs.
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='ignore')
        live = bool(pid and 'video_worker.py' in cmdline)
    except OSError:
        live=False
    result['worker_alive']=bool(live)
    if result.get('status') in ('running','starting') and not live:result.update(status='stopped',message='视频进程已停止。')
    return result

def _chapter_complete(root, episode_id):
    """Return whether every shot of a compiled chapter has a usable take."""
    episode_path = Path(root) / 'episodes' / f'{episode_id}.json'
    if not episode_path.exists():
        return False
    episode = read(episode_path)
    shots = episode.get('shots', [])
    if not shots:
        return False
    latest = {}
    for take in sorted(load_state(root).get('takes', {}).values(), key=lambda item: item.get('created_at', 0)):
        if take.get('episode') == episode_id and not take.get('retired'):
            latest[take.get('shot')] = take
    for shot in shots:
        take = latest.get(shot.get('id'))
        if not take or take.get('status') not in ('rendered', 'approved') or not take.get('video'):
            return False
        try:
            if not inside(root, take['video']).is_file():
                return False
        except (OSError, ValueError):
            return False
    return True


def next_pending_episode(root):
    """Select the first story chapter not fully rendered, preserving book order."""
    root = Path(root)
    for chapter in read(root / 'book.json').get('chapters', []):
        if chapter.get('kind') != 'story':
            continue
        episode_id = 'chapter_' + chapter['id']
        if not _chapter_complete(root, episode_id):
            return episode_id
    return None


def _publish_gate(episode_id, blockers, assets=(), speakers=()):
    """Publish the latest chapter gate so the workbench can render actions."""
    path = REPO / 'runtime' / 'asset_gate' / f'{episode_id}.json'
    from .project import write
    write(path, {
        'status': 'waiting',
        'episode': episode_id,
        'blockers': blockers,
        'required_assets': len(assets),
        'required_speakers': sorted(speakers),
        'time': time.time(),
    })


def require_ready(root, episode_id=None):
    """Require only the selected/next chapter's script, assets and voice bindings."""
    root = Path(root).resolve()
    episode_id = episode_id or next_pending_episode(root)
    if not episode_id:
        raise ValueError('没有待生成的视频章节')
    from start_next_chapter_when_ready import _chapter_requirements
    try:
        _, _, blockers, required_assets, required_speakers = _chapter_requirements(root, episode_id)
    except (FileNotFoundError, KeyError, ValueError, OSError) as exc:
        blockers = [{'reason': 'chapter_material_missing', 'details': str(exc)}]
        required_assets, required_speakers = set(), set()
    if not blockers:
        from .project import digest
        ep = read(root / "episodes" / f"{episode_id}.json")
        approval = load_state(root).get("approvals", {}).get(episode_id, {})
        if approval.get("sha256") != digest(ep):
            blockers.append({"reason": "storyboard_review_pending", "details": "当前版本分镜尚未确认，请核对后通过分镜审核"})
    if blockers:
        _publish_gate(episode_id, blockers, required_assets, required_speakers)
        details = []
        for blocker in blockers[:12]:
            label = blocker.get('reason', 'chapter_material_missing')
            if blocker.get('name'):
                label += f"({blocker['name']})"
            if blocker.get('speaker'):
                label += f"({blocker['speaker']})"
            details.append(label)
        suffix = '；'.join(details)
        if len(blockers) > 12:
            suffix += f'；另有 {len(blockers) - 12} 项'
        raise ChapterGateError(episode_id, blockers, required_assets, required_speakers,
                               f'当前待生成章节 {episode_id} 资料未齐，视频未启动：{suffix}')
    return episode_id

def control(root,action,episode=None,retake_only=False):
    root=Path(root).resolve()
    if action not in ('start','pause'):raise ValueError('不支持的任务操作')
    with locked(root,'video_control'):
        current=status(root)
        if action=='start':
            if current['worker_alive']:return current
            episode_id = require_ready(root, episode)
            q=api(config(root)['comfy_url'],'/queue')
            if q['queue_running'] or q['queue_pending']:raise ValueError('视频队列非空，不能重复启动')
            PAUSE.unlink(missing_ok=True)
            logs=root/'analysis/video_runs';logs.mkdir(exist_ok=True)
            with (logs/'worker.log').open('a') as log:
                child=subprocess.Popen([sys.executable,str(REPO/'video_worker.py'),str(root)] + ([episode_id] if episode else []) + (['--rework-only'] if retake_only else []),cwd=REPO,stdout=log,stderr=log,start_new_session=True)
            result=dict(status='starting',worker_pid=child.pid,episode=episode_id,updated_at=time.time(),message=(f'仅生成 {episode_id}；完成后停止，其余章节保持暂停。' if episode else f'{episode_id} 章节资料检查通过，启动视频生成；后续章节按各自资料完成情况继续。'))
        else:
            PAUSE.write_text('用户在工作台暂停视频生成。')
            if current['worker_alive']:
                os.killpg(current['worker_pid'],signal.SIGTERM)
                api(config(root)['comfy_url'],'/interrupt',{})
                def retire_interrupted(state):
                    for take in state['takes'].values():
                        if take.get('status') in ('submitted','submitting'):
                            take.update(status='rejected',retired=True,interrupted_by_user=True)
                update_state(root,retire_interrupted)
            result=dict(status='paused',updated_at=time.time(),message='视频生成已暂停；已完成视频保留。')
        write(root/'analysis/video_activity.json',result);return result


def start_retake_if_idle(root):
    """A user retake after chapter completion starts only the retake queue."""
    from .rework_queue import snapshot
    if status(root)['worker_alive']:
        return
    items = snapshot(root)['items']
    if items:
        return control(root, 'start', episode=items[0]['episode'], retake_only=True)
