"""Continuation replay audit.

A video-reference take sometimes starts by re-performing the action it was
given as a continuation hint, instead of starting on the previous shot's
ending state. This compares the first seconds of a take with the previous
take: if the opening frame matches an early moment of the previous shot, the
take is replaying, and the report suggests where the new action actually
starts so the lead-in can be trimmed.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

SIGNATURE = (48, 27)


def _frames(path: Path, *, fps: int, start: float = 0.0, duration: float | None = None) -> list[tuple[float, list[float]]]:
    """Grab low-resolution grayscale signatures at ``fps`` from ``start``."""
    import numpy as np
    from PIL import Image

    out: list[tuple[float, list[float]]] = []
    with tempfile.TemporaryDirectory() as tmp:
        args = ['ffmpeg', '-v', 'error', '-ss', f'{start:.3f}', '-i', str(path),
                '-vf', f'fps={fps},scale={SIGNATURE[0]}:{SIGNATURE[1]},format=gray']
        if duration:
            args += ['-t', f'{duration:.3f}']
        args += [str(Path(tmp) / 'f_%04d.png')]
        subprocess.run(args, check=True)
        for index, frame in enumerate(sorted(Path(tmp).glob('*.png'))):
            with Image.open(frame) as image:
                out.append((start + index / fps, list(np.asarray(image, dtype=float).ravel())))
    return out


def _distance(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def audit_pair(prev: Path, take: Path, *, fps: int = 4) -> dict:
    prev_frames = _frames(prev, fps=fps)
    head = _frames(take, fps=fps, start=0.0, duration=3.0)
    if not prev_frames or not head:
        return {'replay': False, 'reason': 'no frames'}
    first = head[0][1]
    best_time, best_distance = min(
        ((time, _distance(first, sig)) for time, sig in prev_frames), key=lambda item: item[1])
    prev_end_time = prev_frames[-1][0]
    # The take opens on an early moment of the previous shot instead of its end.
    replay = bool(best_distance < 18 and best_time < prev_end_time - 0.8)
    trim_seconds = 0.0
    if replay:
        target = prev_frames[-1][1]
        for time, sig in head:
            if _distance(sig, target) < 18:
                trim_seconds = max(0.0, time)
                break
    return {'replay': replay, 'first_matches_prev_at': round(float(best_time), 3),
            'previous_end': round(float(prev_end_time), 3), 'distance': round(float(best_distance), 2),
            'suggested_trim_seconds': round(float(trim_seconds), 3)}


def audit(project: Path, *, takes_subdir: str = 'takes_all') -> dict:
    project = Path(project)
    scene_plan = json.loads((project / 'artifacts/scene_plan.json').read_text(encoding='utf-8'))
    base = project / takes_subdir
    report = {}
    previous = None
    previous_section = None
    for scene in scene_plan['scenes']:
        sid = scene['id']
        take = base / sid / 'native.mp4'
        section = scene['script_section_id']
        if take.is_file() and previous is not None and section == previous_section:
            report[sid] = audit_pair(base / previous / 'native.mp4', take)
            report[sid]['previous'] = previous
        previous = sid
        previous_section = section
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Detect continuation replay at take start.')
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    report = audit(project)
    out = project / 'artifacts/continuity_audit.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    flagged = {sid: item for sid, item in report.items() if item.get('replay')}
    print(json.dumps({'pairs': len(report), 'replay': len(flagged),
                      'shots': sorted(flagged), 'output': str(out)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
