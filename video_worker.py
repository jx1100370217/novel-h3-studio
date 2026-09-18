"""Managed entry point for the workbench video buttons."""
import os,subprocess,sys,time
from pathlib import Path
from novel_h3.project import write,locked
from novel_h3.safety import REPO, bounded_worker

# The workbench launches this entry point directly.  Re-exec it inside the
# protected user systemd slice before importing the renderer or touching a
# model, so render_chapter's resource monitor sees the same cgroup.
bounded_worker()

root=Path(sys.argv[1]).resolve()
with locked(root,'video_control'):pass
write(root/'analysis/video_activity.json',dict(status='running',worker_pid=os.getpid(),updated_at=time.time(),message='正在按原文顺序生成视频。'))
result=subprocess.run([sys.executable,str(REPO/'continue_book.py')],cwd=REPO)
write(root/'analysis/video_activity.json',dict(status='completed' if result.returncode==0 else 'failed',updated_at=time.time(),message='本轮视频队列已结束。' if result.returncode==0 else '视频队列执行失败，请查看日志。'))
