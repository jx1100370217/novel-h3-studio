"""Headless Blender blocking-guide orchestration (global)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def find_blender() -> str:
    candidates = [
        os.environ.get('NOVEL_H3_BLENDER_BIN'),
        shutil.which('blender'),
        str(Path.home() / '.local/share/novel-h3-studio/blender-5.2.2/blender'),
        str(Path.home() / '.local/share/novel-h3-studio/blender-5.0.1/blender'),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise FileNotFoundError('Blender not found; set NOVEL_H3_BLENDER_BIN or install Blender')


def render_previs(spec_path: Path, shot: str, out_path: Path, *, blender_bin: str | None = None,
                  timeout: float = 180.0) -> dict:
    spec_path = Path(spec_path).resolve()
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    binary = blender_bin or find_blender()
    renderer = Path(__file__).with_name('previs_render.py')
    cmd = [binary, '--background', '--factory-startup', '--python-exit-code', '1',
           '--python', str(renderer), '--', '--spec', str(spec_path), '--shot', shot,
           '--out', str(out_path)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0 or not out_path.is_file():
        raise RuntimeError(f'Blender previs failed for {shot}: {result.stderr[-2000:] or result.stdout[-2000:]}')
    return {'shot': shot, 'path': str(out_path), 'blender': binary,
            'renderer': str(renderer), 'size_bytes': out_path.stat().st_size}


def render_all(spec_path: Path, out_dir: Path, shots: list[str] | None = None,
               *, blender_bin: str | None = None) -> list[dict]:
    data = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    ids = shots or sorted(data['shots'])
    return [render_previs(spec_path, sid, Path(out_dir) / f'{sid}.png', blender_bin=blender_bin) for sid in ids]
