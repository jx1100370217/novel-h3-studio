"""Character voice-reference construction and binding for Ref2VA.

A voice reference is a short, clean, single-speaker WAV assembled from
approved dialogue takes. It is not narration and it must never contain a
second character. The manifest is the single source of truth used by the
global Ref2VA builder, so a speaker's timbre is bound to a subject before the
prompt is written.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class VoiceRef:
    role: str
    asset_id: str
    path: Path
    source_line_ids: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    median_f0_hz: float | None = None
    audio: str = ''

    def with_audio(self, label: str) -> 'VoiceRef':
        return VoiceRef(self.role, self.asset_id, self.path, self.source_line_ids,
                        self.duration_seconds, self.median_f0_hz, label)


def duration(path: Path) -> float:
    out = subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', str(path)],
        text=True,
    )
    return round(float(out.strip()), 3)


def median_f0(path: Path) -> float | None:
    import numpy as np
    raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-ar', '16000',
                                   '-ac', '1', '-f', 'f32le', '-'])
    x = np.frombuffer(raw, dtype=np.float32)
    sr, win, hop = 16000, 640, 320
    pitches = []
    for i in range(0, len(x) - win, hop):
        seg = x[i:i + win]
        if float(np.sqrt((seg ** 2).mean())) < 0.008:
            continue
        seg = seg - seg.mean()
        corr = np.correlate(seg, seg, 'full')[win - 1:]
        lo, hi = sr // 400, sr // 70
        if hi >= len(corr):
            continue
        lag = lo + int(np.argmax(corr[lo:hi]))
        if corr[lag] > 0.25 * corr[0]:
            pitches.append(sr / lag)
    return round(float(np.median(pitches)), 1) if pitches else None


def build_reference(paths: Iterable[Path], output_path: Path, *, target_lufs: float = -23.0,
                    gap_seconds: float = 0.15) -> dict:
    """Concatenate single-speaker clips and normalize them to one reference level."""
    paths = [Path(path) for path in paths]
    if not paths:
        raise ValueError('a voice reference needs at least one source clip')
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    filters: list[str] = []
    for i, path in enumerate(paths):
        inputs += ['-i', str(path)]
        filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]')
    silence = 'aevalsrc=0:d=0.15:s=48000'
    for i in range(len(paths) - 1):
        inputs += ['-f', 'lavfi', '-i', silence]
    parts: list[str] = []
    for i in range(len(paths)):
        parts.append(f'[a{i}]')
        if i != len(paths) - 1:
            parts.append(f'[{len(paths) + i}:a]')
    graph = ';'.join(filters) + ';' + ''.join(parts) + \
            f'concat=n={len(paths) * 2 - 1}:v=0:a=1[cat];' \
            f'[cat]loudnorm=I={target_lufs}:TP=-2:LRA=7[out]'
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', *inputs, '-filter_complex', graph,
                    '-map', '[out]', '-ar', '48000', '-ac', '1', str(output_path)], check=True)
    return {'path': str(output_path), 'duration_seconds': duration(output_path),
            'median_f0_hz': median_f0(output_path), 'level_lufs': target_lufs}


def build_manifest(line_manifest_path: Path, plan: dict, output_dir: Path) -> dict:
    """Build every voice reference described by a project voice plan.

    ``plan`` shape::

        {"references": {"songtao": {"asset_id": "songtao",
                                     "line_ids": ["S01", "S03"],
                                     "file": "songtao_ref.wav"}}}
    """
    line_manifest_path = Path(line_manifest_path)
    lines = {line['id']: line for line in json.loads(line_manifest_path.read_text(encoding='utf-8'))['lines']}
    output_dir = Path(output_dir)
    manifest = {'version': '1.0', 'source': str(line_manifest_path), 'references': {}}
    for role, spec in plan.get('references', {}).items():
        paths = []
        for line_id in spec['line_ids']:
            line = lines.get(line_id)
            if line is None:
                raise ValueError(f'voice plan references missing line {line_id}')
            wav = Path(line['wav'])
            if not wav.is_absolute():
                wav = (line_manifest_path.parent / wav).resolve()
            if not wav.is_file():
                raise ValueError(f'voice plan references missing wav {wav}')
            paths.append(wav)
        info = build_reference(paths, output_dir / spec.get('file', f'{role}_ref.wav'))
        manifest['references'][role] = {
            'asset_id': spec.get('asset_id', role),
            'path': info['path'],
            'source_line_ids': list(spec['line_ids']),
            'duration_seconds': info['duration_seconds'],
            'median_f0_hz': info['median_f0_hz'],
            'level_lufs': info['level_lufs'],
        }
    (output_dir / 'voice_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def load_manifest(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    for role, item in data.get('references', {}).items():
        item.setdefault('asset_id', role)
        item.setdefault('audio', '')
    return data


def manifest_refs(manifest: dict, role_to_asset: dict[str, str]) -> dict[str, VoiceRef]:
    result = {}
    for role, item in manifest.get('references', {}).items():
        result[role] = VoiceRef(
            role=role,
            asset_id=item.get('asset_id', role),
            path=Path(item['path']),
            source_line_ids=tuple(item.get('source_line_ids', ())),
            duration_seconds=float(item.get('duration_seconds', 0)),
            median_f0_hz=item.get('median_f0_hz'),
        )
    return result
