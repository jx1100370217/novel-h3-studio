"""Consume explicitly requested video reworks after the active GPU batch."""
from pathlib import Path
import sys
from novel_h3.project import locked
from novel_h3.regeneration import tasks
from start_next_chapter_when_ready import run

root=Path(sys.argv[1]).resolve()
with locked(root,'video_reworks'):
    with locked(root,'batch'):
        pass
    for episode in dict.fromkeys(j['episode'] for j in tasks(root) if j['status']=='awaiting_video_worker'):
        run(root,episode)
