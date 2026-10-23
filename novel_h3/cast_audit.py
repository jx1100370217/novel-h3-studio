"""Face-count audit for duplicate-person and extra-person defects.

The detector is a triage aid, not a verdict: background portraits, statues,
horse faces and carved throne details can produce false positives. Every
suspect frame is saved for human review.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / 'runtime/models/face_detection_yunet_2023mar.onnx'


def model_path(path: str | Path | None = None) -> Path:
    p = Path(path) if path else DEFAULT_MODEL
    if not p.is_file():
        raise FileNotFoundError(
            f'YuNet face model missing: {p}; download face_detection_yunet_2023mar.onnx'
        )
    return p.resolve()


def audit_video(video_path: str | Path, *, expected_max_faces: int | None = None,
                fps: int = 1, model: str | Path | None = None,
                out_dir: str | Path | None = None) -> dict:
    import cv2
    video_path = Path(video_path).resolve()
    model = model_path(model)
    out_dir = Path(out_dir) if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cast_audit_') as tmp:
        tmp = Path(tmp)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(video_path),
                        '-vf', f'fps={fps}', str(tmp / 'f_%03d.png')], check=True)
        rows = []
        for frame in sorted(tmp.glob('*.png')):
            image = cv2.imread(str(frame))
            h, w = image.shape[:2]
            detector = cv2.FaceDetectorYN_create(str(model), '', (w, h), 0.55, 0.3, 5000)
            _, faces = detector.detect(image)
            count = 0 if faces is None else len(faces)
            timestamp = int(frame.stem.split('_')[-1]) - 1
            if faces is not None:
                for face in faces:
                    x, y, bw, bh = map(int, face[:4])
                    cv2.rectangle(image, (x, y), (x + bw, y + bh), (0, 0, 255), 3)
            annotated = None
            if out_dir:
                annotated = out_dir / f'{video_path.parent.name}_{timestamp:03d}s.jpg'
                cv2.imwrite(str(annotated), image)
            rows.append({'timestamp': timestamp, 'faces': count,
                         'annotated_frame': str(annotated) if annotated else None})
    counts = [row['faces'] for row in rows]
    max_faces = max(counts) if counts else 0
    suspect = expected_max_faces is not None and max_faces > expected_max_faces
    return {
        'video': str(video_path), 'expected_max_faces': expected_max_faces,
        'max_faces': max_faces, 'suspect': suspect,
        'frames': rows,
        'suspect_timestamps': [row['timestamp'] for row in rows
                               if expected_max_faces is not None and row['faces'] > expected_max_faces],
    }


def audit_batch(takes_dir: str | Path, expected: dict[str, int] | None, out_dir: str | Path,
                *, fps: int = 1, model: str | Path | None = None) -> dict:
    takes_dir = Path(takes_dir)
    out_dir = Path(out_dir)
    frames_dir = out_dir / 'suspect_frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    expected = expected or {}
    reports = []
    for video in sorted(takes_dir.glob('A*/native.mp4')):
        sid = video.parent.name
        report = audit_video(video, expected_max_faces=expected.get(sid), fps=fps,
                             model=model, out_dir=frames_dir)
        reports.append({'shot': sid, **report})
        print(f"{sid} expected={expected.get(sid)} max={report['max_faces']} suspect={report['suspect']}", flush=True)
    result = {'version': '1.0', 'takes_dir': str(takes_dir), 'fps': fps,
              'expected_max_faces': expected, 'shots': reports,
              'suspect_shots': [row['shot'] for row in reports if row['suspect']]}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'cast_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
