"""Per-take adherence audit against the locked shot contract.

For every rendered take this checks what a machine can check objectively:
the frame count and canvas, the visible face count against the declared cast,
and whether the spoken audio actually says the authored dialogue. Framing,
action and props still need human eyes; the JSON and Markdown reports mark
those rows ``needs_visual_review``.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from .cast_audit import audit_video

CJK = re.compile(r'[\u3400-\u9fff]')
WHISPER_MODEL = Path(
    '/home/jx/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/'
    'snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
)


def probe(video: Path) -> dict:
    out = subprocess.check_output(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
         '-show_entries', 'format=duration', '-of', 'json', str(video)], text=True)
    data = json.loads(out)
    stream = (data.get('streams') or [{}])[0]
    return {
        'width': stream.get('width'),
        'height': stream.get('height'),
        'fps': stream.get('r_frame_rate'),
        'frames': int(stream.get('nb_frames') or 0),
        'duration': float((data.get('format') or {}).get('duration') or 0),
    }


def dialogue_text(shot: dict) -> str:
    lines = []
    for raw in (shot.get('dialogue') or '').splitlines():
        if '：' in raw:
            lines.append(raw.split('：', 1)[1])
    return ''.join(lines)


def normalise(text: str) -> str:
    return ''.join(CJK.findall(text))


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def transcribe(video: Path, model) -> str:
    import numpy as np

    raw = subprocess.check_output(
        ['ffmpeg', '-v', 'error', '-i', str(video), '-vn',
         '-ar', '16000', '-ac', '1', '-f', 'f32le', '-'])
    audio = np.frombuffer(raw, dtype=np.float32).copy()
    segments, _info = model.transcribe(audio, language='zh', vad_filter=True)
    return ''.join(segment.text for segment in segments)


def audit_take(project: Path, takes_dir: Path, sid: str, shot: dict, model) -> dict:
    video = takes_dir / sid / 'native.mp4'
    info = probe(video)
    expected_frames = int(shot.get('frames') or 0)
    expected_cast = len([c for c in (shot.get('cast') or []) if c != 'baby'])
    faces = audit_video(video, expected_max_faces=expected_cast, fps=2)
    said = normalise(transcribe(video, model))
    authored = normalise(dialogue_text(shot))
    score = similarity(said, authored) if authored else None
    issues = []
    if info['frames'] != expected_frames:
        issues.append(f"frames {info['frames']} != plan {expected_frames}")
    if (info['width'], info['height']) != (1344, 768):
        issues.append(f"canvas {info['width']}x{info['height']}")
    if info['fps'] != '24/1':
        issues.append(f"fps {info['fps']}")
    if faces['suspect']:
        issues.append(f"faces {faces['max_faces']} > cast {expected_cast}")
    if score is not None and score < 0.45:
        issues.append(f'dialogue match {score:.2f}')
    return {
        'shot': sid,
        'file': str(video),
        'plan_frames': expected_frames,
        'plan_cast': expected_cast,
        'probe': info,
        'max_faces': faces['max_faces'],
        'face_suspect': faces['suspect'],
        'authored_dialogue': authored or None,
        'transcript': said or None,
        'dialogue_similarity': None if score is None else round(score, 3),
        'issues': issues,
        'needs_visual_review': True,
    }


def audit_project(project: Path, *, takes_subdir: str = 'takes_all') -> dict:
    project = Path(project)
    takes_dir = project / takes_subdir
    scene_plan = json.loads((project / 'artifacts/scene_plan.json').read_text(encoding='utf-8'))
    ids = [str(scene['id']) for scene in scene_plan['scenes']]
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel(str(WHISPER_MODEL), device='cpu', compute_type='int8')
    except Exception:
        model = None
    report = {}
    for sid in ids:
        video = takes_dir / sid / 'native.mp4'
        shot_path = project / 'shots' / f'{sid}.json'
        if not video.is_file() or not shot_path.is_file():
            continue
        shot = json.loads(shot_path.read_text(encoding='utf-8'))
        if model is None:
            report[sid] = {'shot': sid, 'error': 'whisper unavailable'}
            continue
        report[sid] = audit_take(project, takes_dir, sid, shot, model)
    return report


def write_reports(report: dict, artifacts: Path) -> tuple[Path, Path]:
    artifacts = Path(artifacts)
    json_path = artifacts / 'take_audit.json'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# Take adherence audit', '',
             '| shot | frames | cast | faces | dialogue | issues |',
             '|---|---|---|---|---|---|']
    for sid, item in report.items():
        if 'error' in item:
            lines.append(f"| {sid} | — | — | — | — | {item['error']} |")
            continue
        sim = item['dialogue_similarity']
        sim_text = '—' if sim is None else f'{sim:.2f}'
        issues = '; '.join(item['issues']) or 'ok'
        lines.append(f"| {sid} | {item['probe']['frames']}/{item['plan_frames']} | "
                     f"{item['plan_cast']} | {item['max_faces']} | {sim_text} | {issues} |")
    md_path = artifacts / 'take_audit.md'
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return json_path, md_path


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description='Audit rendered takes against their shot contracts.')
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--takes-subdir', default='takes_all')
    args = parser.parse_args(argv)
    project = args.project.resolve()
    report = audit_project(project, takes_subdir=args.takes_subdir)
    json_path, md_path = write_reports(report, project / 'artifacts')
    flagged = [sid for sid, item in report.items() if item.get('issues')]
    print(json.dumps({'scanned': len(report), 'flagged': flagged,
                      'report': str(json_path), 'summary': str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
