"""Start/pause a single preparation worker; never control the video renderer."""
import os
import subprocess
import sys
import time
from pathlib import Path
from .project import read, write, locked
REPO = Path(__file__).resolve().parents[1]


def status(root):
    path = Path(root)/'analysis/preparation_activity.json'
    result = read(path) if path.exists() else {'status':'paused'}
    pid = result.get('worker_pid')
    try:
        live = pid and str(REPO/'preparation_worker.py').encode() in Path(f'/proc/{pid}/cmdline').read_bytes()
    except OSError:
        live = False
    if result.get('status') in ('running','starting','pausing') and not live:
        result.update(status='stopped', message='准备执行进程已停止，可点击开始任务继续。')
    result['worker_alive'] = bool(live)
    return result


def control(root, action):
    root = Path(root).resolve()
    if action not in ('start','pause'):
        raise ValueError('不支持的任务操作')
    with locked(root,'preparation_control'):
        current = status(root)
        stop = root/'analysis/PREPARATION_PAUSED'
        if action == 'pause':
            stop.write_text('用户暂停准备任务')
            current.update(status='pausing' if current['worker_alive'] else 'paused', updated_at=time.time(), message='正在停止准备执行；已保存的文件保留。' if current['worker_alive'] else '准备任务已暂停。')
            write(root/'analysis/preparation_activity.json',current)
            return current
        if current['worker_alive']:
            return current
        stop.unlink(missing_ok=True)
        logs = root/'analysis/preparation_runs';logs.mkdir(exist_ok=True)
        with (logs/'worker.log').open('a') as log:
            process = subprocess.Popen([sys.executable,str(REPO/'preparation_worker.py'),str(root)],cwd=REPO,stdout=log,stderr=log,start_new_session=True)
        result = dict(status='starting',worker_pid=process.pid,updated_at=time.time(),message='正在启动全书准备任务；视频保持暂停。')
        write(root/'analysis/preparation_activity.json',result)
        return result
