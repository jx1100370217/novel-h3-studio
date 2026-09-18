"""Durable review rework queue. Only real executor output advances a job."""
import hashlib
import threading
import time
from pathlib import Path
from .project import read, write, locked, load_state, safe_id, file_hash

PENDING = {'queued', 'running', 'awaiting_codex_image_tool', 'awaiting_video_worker'}


def tasks(root):
    root = Path(root)
    rows = []
    with locked(root, 'regeneration'):
        for path in (root/'regeneration').glob('*.json'):
            job = read(path)
            if job['status'] == 'awaiting_codex_image_tool':
                item = load_state(root)['assets'].get(job['target'], {})
                if item.get('sha256') and item['sha256'] != job.get('previous_hash'):
                    # Scene/prop images are governed by the technical
                    # precheck policy: once a new tool output is registered,
                    # validate it and auto-approve. Character images keep the
                    # existing manual review requirement.
                    bucket = None
                    try:
                        from .arcreel import inventory
                        inv = inventory(root)
                        for candidate in ('scenes', 'props'):
                            if any(v.get('id') == job['target'] for v in inv.get(candidate, {}).values()):
                                bucket = candidate
                                break
                    except Exception:
                        bucket = None
                    if bucket:
                        try:
                            from .comfy import asset_for
                            asset_for(root, job['target'], require_approval=False)
                            now = time.time()
                            from .project import update_state
                            update_state(root, lambda s: s['assets'][job['target']].update(
                                approved=True, reviewer='system',
                                approval_method='auto_after_technical_regeneration',
                                approved_at=now,
                                note='技术预检失败后由图片工具重新生成，自动核验通过',
                                precheck={'status': 'already_approved',
                                          'reason': '新图片已通过技术预检并自动确认',
                                          'checked_at': now,
                                          'scope': 'scene_and_prop_only',
                                          'auto_regeneration': {'id': job['id'], 'status': 'approved'}}))
                            job.update(status='approved', output=item['path'],
                                       message='新图片已通过技术预检并自动确认。', updated_at=now)
                        except Exception as exc:
                            job.update(message='新图片仍未通过技术预检：'+str(exc), updated_at=time.time())
                        write(path, job)
                    else:
                        job.update(status='awaiting_review', output=item['path'], message='新图片已登记，等待审阅。', updated_at=time.time())
                        write(path, job)
            if job['status'] == 'awaiting_video_worker':
                state = load_state(root)
                old = state['takes'].get(job['target'], {})
                newer = [t for t in state['takes'].values() if t.get('episode') == old.get('episode') and t.get('shot') == old.get('shot') and t.get('created_at',0) > job['created_at'] and not t.get('retired')]
                if newer:
                    take = max(newer,key=lambda t:t['created_at'])
                    if take['status'] in ('rendered','approved'):
                        job.update(status='awaiting_review',output=take['video'],updated_at=time.time());write(path,job)
                    else:
                        job['message']='视频生成器已提交重拍：'+take['id']
            if job['status']=='awaiting_review' and job['kind'] in ('image','voice'):
                item = load_state(root)['assets'].get(job['target'],{}) if job['kind']=='image' else read(root/'bible/voices.json').get(job['target'],{})
                if item.get('approved'):
                    job.update(status='approved',message='生成结果已确认。',updated_at=time.time());write(path,job)
            if job['status'] == 'approved':
                job['message'] = '生成结果已确认。'
            rows.append(job)
    return sorted(rows, key=lambda j:j['created_at'], reverse=True)


def enqueue(root, kind, target, episode=None):
    root = Path(root)
    if kind not in ('image','voice','script','storyboard','video','chapter'):
        raise ValueError('不支持的重新生成类型')
    state = load_state(root)
    if kind == 'chapter':
        from .preparation import chapter_id
        chapter_id(root,target)
        ids=[t['id'] for t in state['takes'].values() if t.get('episode')==target and not t.get('retired') and t.get('status') in ('rendered','approved','rejected','failed')]
        if not ids:
            raise ValueError('本章尚无可重拍的完成镜头')
        return {'status':'queued','jobs':[enqueue(root,'video',tid,target)['id'] for tid in ids]}
    if kind == 'image':
        safe_id(target)
        read(root/'jobs'/f'image_{target}.json')
    elif kind == 'voice':
        if target not in read(root/'bible/voices.json'):
            raise ValueError('请先登记角色声音档案')
    elif kind == 'video':
        take = state['takes'].get(target)
        if not take or take['status'] not in ('rendered','approved','rejected','failed'):
            raise ValueError('仅已完成或失败的视频可以重新生成')
        episode = take['episode']
    else:
        from .preparation import chapter_id
        chapter_id(root, target)
        episode = target
    key = hashlib.sha256((kind+':'+target).encode()).hexdigest()[:20]
    with locked(root, 'regeneration'):
        path = root/'regeneration'/f'{key}.json'
        old = read(path) if path.exists() else {}
        if old.get('status') in PENDING:
            return old
        job = dict(id=key, kind=kind, target=target, episode=episode,
                   status='queued', created_at=time.time(), updated_at=time.time(),
                   attempt=old.get('attempt',0)+1,
                   previous_hash=state['assets'].get(target,{}).get('sha256'))
        write(path, job)
    threading.Thread(target=execute, args=(root,key), daemon=True).start()
    return job


def execute(root, key):
    path = root/'regeneration'/f'{key}.json'
    job = read(path)
    def update(**fields):
        job.update(fields, updated_at=time.time());write(path, job)
    try:
        update(status='running')
        if job['kind'] == 'image':
            update(status='awaiting_codex_image_tool',
                   output=f"jobs/image_{job['target']}.json",
                   message='已入队，等待当前 Codex 对话图片工具执行；网页不能直接调用订阅图片工具。')
        elif job['kind'] in ('script','storyboard'):
            from .preparation import prepare
            result = prepare(root, job['target'], 'script')
            update(status='awaiting_editor', output=result['path'], message='候选剧本、视觉工作单和灵活时长已生成；待逐句说话人及导演核对。')
        elif job['kind'] == 'voice':
            import subprocess
            repo = Path(__file__).resolve().parents[1]
            result = subprocess.run([str(repo/'.venv-audio/bin/python'),str(repo/'regenerate_voice.py'),str(root),job['target']],capture_output=True,text=True,timeout=180)
            if result.returncode:
                raise ValueError(result.stderr[-1200:] or result.stdout[-1200:])
            voice = read(root/'bible/voices.json')[job['target']]
            update(status='awaiting_review', output=voice['path'], message='新试音已生成并挂回角色卡，等待审听；未自动确认声音身份。')
        else:
            from .comfy import review_take
            review_take(root,job['target'],False,'用户点击重新生成','user',{})
            update(status='awaiting_video_worker', message='已标记重拍，等待当前批次释放资源后重新提交。')
            # The serial video worker owns the GPU. The review queue is
            # drained ahead of ordinary shots; never launch a competing
            # renderer for a manual regeneration request.
    except Exception as exc:
        update(status='failed', message=str(exc))


def recover(root):
    """Recover interrupted local jobs after a workbench restart."""
    root=Path(root)
    for path in (root/'regeneration').glob('*.json'):
        job=read(path)
        if job['status']=='running':
            job.update(status='failed',message='工作台重启中断了执行，请重新提交。',updated_at=time.time())
            write(path,job)
        elif job['status']=='queued':
            threading.Thread(target=execute,args=(root,job['id']),daemon=True).start()
