"""Per-shot review exports.

A shot can be reviewed the moment its take lands instead of waiting for the
whole film. Each export is a stand-alone MP4 with the authored dialogue burned
in, so a reviewer can judge framing, action, voice and subtitle timing in one
file.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .subtitles import build_shot_ass


def export_shot(take: Path, out: Path, shot: dict, *, width: int = 1344, height: int = 768,
                timing: list | None = None) -> Path:
    """Re-encode one take with burned subtitles for review."""
    take = Path(take)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ass = out.with_suffix('.ass')
    written = build_shot_ass(shot, ass, width=width, height=height, timing=timing)
    filters = f'scale={width}:{height}:flags=lanczos,format=yuv420p'
    if written is not None:
        filters += ',ass=' + str(written).replace('\\', '/').replace(':', '\\:')
    subprocess.run(
        ['ffmpeg', '-y', '-loglevel', 'error', '-i', str(take),
         '-vf', filters, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
         '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2',
         '-movflags', '+faststart', str(out)], check=True)
    if written is None:
        ass.unlink(missing_ok=True)
    # A small sidecar keeps the review clip self-describing.
    meta = {
        'shot': shot.get('id') or shot.get('shot'),
        'title': shot.get('title'),
        'frames': shot.get('frames'),
        'duration_seconds': shot.get('duration_seconds'),
        'camera': shot.get('camera'),
        'blocking': shot.get('blocking'),
        'dialogue': shot.get('dialogue'),
        'source_take': str(take),
    }
    out.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return out
