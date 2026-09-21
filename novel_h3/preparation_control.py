"""Start/pause a single preparation worker; never control the video renderer."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from .project import read, write, locked
REPO = Path(__file__).resolve().parents[1]


def _activity_path(root, episode=None):
    root = Path(root)
    return root/'analysis'/(f'preparation_activity_{episode}.json' if episode else 'preparation_activity.json')


def status(root, episode=None):
    path = _activity_path(root, episode)
    result = read(path) if path.exists() else {'status':'paused'}
    pid = result.get('worker_pid')
    try:
        cmdline = Path(f'/proc/{pid}/cmdline').read_bytes() if pid else b''
        live = str(REPO/'preparation_worker.py').encode() in cmdline
        if episode:
            live = live and episode.encode() in cmdline
    except OSError:
        live = False
    if result.get('status') in ('running','starting','pausing') and not live:
        result.update(status='stopped', message='准备执行进程已停止，可点击开始任务继续。')
    result['worker_alive'] = bool(live)
    return result


def control(root, action, episode=None):
    root = Path(root).resolve()
    if action not in ('start','pause'):
        raise ValueError('不支持的任务操作')
    if episode:
        valid = {'chapter_' + c['id'] for c in read(root/'book.json').get('chapters', []) if c.get('kind') == 'story'}
        if episode not in valid:
            raise ValueError('章节不存在或不是正文章节')
    with locked(root,'preparation_control'):
        parallel_path = root/'analysis/parallel_preparation.json'
        parallel = read(parallel_path) if parallel_path.exists() else {}
        parallel_job = (parallel.get('chapters') or {}).get(episode) if episode else None
        parallel_pid = parallel_job.get('pid') if isinstance(parallel_job, dict) else None
        try:
            parallel_cmd = Path(f'/proc/{parallel_pid}/cmdline').read_bytes() if parallel_pid else b''
        except OSError:
            parallel_cmd = b''
        if episode and parallel_pid and (b'codex' in parallel_cmd or b'preparation_worker.py' in parallel_cmd):
            if action == 'start':
                return dict(status='running', worker_pid=parallel_pid, worker_alive=True,
                            message='该章节的并行准备任务已在运行。', episode=episode, parallel=True)
            try:
                os.killpg(os.getpgid(int(parallel_pid)), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    os.kill(int(parallel_pid), signal.SIGTERM)
                except OSError:
                    pass
            parallel_job['status'] = 'paused'
            parallel_job['paused_at'] = time.time()
            write(parallel_path, parallel)
            result = dict(status='paused', worker_pid=parallel_pid, worker_alive=False,
                          message='章节并行准备任务已暂停；已落盘内容保留。', episode=episode, parallel=True)
            write(_activity_path(root, episode), result)
            return result
        current = status(root, episode)
        stop = root/'analysis'/(f'PREPARATION_PAUSED_{episode}' if episode else 'PREPARATION_PAUSED')
        if action == 'pause':
            stop.write_text('用户暂停准备任务')
            current.update(status='pausing' if current['worker_alive'] else 'paused', updated_at=time.time(), message='正在停止准备执行；已保存的文件保留。' if current['worker_alive'] else '准备任务已暂停。')
            write(_activity_path(root, episode),current)
            return current
        if current['worker_alive']:
            return current
        stop.unlink(missing_ok=True)
        logs = root/'analysis/preparation_runs';logs.mkdir(exist_ok=True)
        log_path = logs/(f'worker_{episode}.log' if episode else 'worker.log')
        with log_path.open('a') as log:
            command = [sys.executable, str(REPO/'preparation_worker.py'), str(root)]
            if episode:
                command += ['--episode', episode]
            process = subprocess.Popen(command,cwd=REPO,stdout=log,stderr=log,start_new_session=True)
        scope = f'章节 {episode} 制作准备' if episode else '全书制作准备'
        result = dict(status='starting',worker_pid=process.pid,updated_at=time.time(),message=f'正在启动{scope}；视频生成不受影响。', episode=episode, scope='chapter' if episode else 'book')
        write(_activity_path(root, episode),result)
        return result
