"""Serial chapter handoff; reuse the same per-chapter readiness gate."""
from pathlib import Path
from novel_h3.project import read, load_state, locked
from novel_h3.safety import check_paused
from start_next_chapter_when_ready import run

ROOT = Path(__file__).resolve().parent/'projects/rendao-wuji'


def complete(root, episode):
    path = root/'episodes'/f'{episode}.json'
    if not path.exists():
        return False
    latest = {}
    for take in sorted(load_state(root)['takes'].values(), key=lambda t:t.get('created_at',0)):
        if take.get('episode') == episode and not take.get('retired'):
            latest[take['shot']] = take
    shots = read(path)['shots']
    return bool(shots) and all(latest.get(s['id'],{}).get('status') in ('rendered','approved')
                              and (root/latest[s['id']].get('video','')).is_file() for s in shots)


if __name__ == '__main__':
    with locked(ROOT, 'book_sequence'):
        # Existing chapter renderer owns this lock; do not interrupt its GPU work.
        with locked(ROOT, 'batch'):
            pass
        for chapter in read(ROOT/'book.json')['chapters']:
            if chapter.get('kind') != 'story':
                continue
            check_paused()
            episode = 'chapter_'+chapter['id']
            if complete(ROOT,episode):
                continue
            run(ROOT,episode)
