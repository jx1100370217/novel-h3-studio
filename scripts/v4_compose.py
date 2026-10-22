#!/usr/bin/env python3
"""Compose the v4 45-shot cut: picture + native H3 audio + TTS narration + music."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENMONTAGE = ROOT / 'openmontage'
sys.path.insert(0, str(OPENMONTAGE))
sys.path.insert(0, str(ROOT))

PROJECT = ROOT / 'projects/liaozhai-kaochenghuang'
FASTVIDEO = ROOT / 'projects/liaozhai-kaochenghuang-fastvideo'
V4 = PROJECT / 'v4'
BUILD = V4 / 'renders'
CLIPS = BUILD / 'clips'
AUDIO = V4 / 'audio'
FPS = 24
W, H = 1344, 768
TARGET = 298.833333
GRAPHICS = {
    'A01': PROJECT / 'v2/renders/clips/V01.mp4',
    'A16': PROJECT / 'v2/renders/clips/V08.mp4',
    'A45': PROJECT / 'v4/cards/end_v4.mp4',
}


def run(cmd: list[str], **kwargs) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        print('FAILED:', ' '.join(cmd), flush=True)
        print(result.stderr[-4000:], flush=True)
        raise SystemExit(1)


def ebur128(path: Path) -> tuple[float, float]:
    result = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
                             '-filter_complex', 'ebur128=peak=true', '-f', 'null', '-'],
                            capture_output=True, text=True)
    text = result.stderr
    ints = re.findall(r'I:\s+(-?[\d.]+) LUFS', text)
    peaks = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', text)
    return float(ints[-1]), float(peaks[-1]) if peaks else float('nan')


def build_picture(order, shots) -> Path:
    CLIPS.mkdir(parents=True, exist_ok=True)
    entries = []
    for sid in order:
        src = GRAPHICS.get(sid, FASTVIDEO / 'takes' / sid / 'native.mp4')
        if not src.exists():
            raise SystemExit(f'missing picture source for {sid}: {src}')
        frames = round(float(shots[sid]['duration_seconds']) * FPS)
        out = CLIPS / f'{sid}.mp4'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(src), '-an',
             '-vf', f'scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p',
             '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', '16', '-x264-params', 'keyint=48:min-keyint=48:scenecut=0',
             '-video_track_timescale', '24000', str(out)])
        print('PIC', sid, frames, flush=True)
        entries.append(out)
    listing = BUILD / 'concat_v4.txt'
    listing.write_text(''.join(f"file '{p.resolve()}'\n" for p in entries))
    silent = BUILD / 'film_silent_v4.mp4'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
         '-i', str(listing), '-c', 'copy', '-fflags', '+genpts', '-movflags', '+faststart', str(silent)])
    return silent


def build_audio(order, shots, lines, bounds) -> Path:
    AUDIO.mkdir(parents=True, exist_ok=True)
    VO = PROJECT / 'v3/audio/mix_v3/vo'
    tracks = []
    for sid in order:
        duration = float(shots[sid]['duration_seconds'])
        if sid in GRAPHICS:
            silence = AUDIO / f'{sid}_silence.wav'
            run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi',
                 '-i', 'anullsrc=r=48000:cl=stereo', '-t', f'{duration:.6f}', str(silence)])
            tracks.append({'path': str(silence), 'role': 'sfx', 'volume': 1.0,
                           'start_seconds': round(bounds[sid], 4)})
            continue
        native = FASTVIDEO / 'takes' / sid / 'native.mp4'
        raw = AUDIO / f'{sid}_native_raw.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(native), '-vn',
             '-af', f'atrim=0:{duration:.6f},asetpts=PTS-STARTPTS', '-ar', '48000', '-ac', '2', str(raw)])
        level, _ = ebur128(raw)
        gain = max(-6.0, min(6.0, -24.0 - level))
        leveled = AUDIO / f'{sid}_native.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw),
             '-af', f'volume={gain:.2f}dB,alimiter=limit=0.95:level=0', '-ar', '48000', '-ac', '2', str(leveled)])
        tracks.append({'path': str(leveled), 'role': 'sfx', 'volume': 1.0,
                       'start_seconds': round(bounds[sid], 4)})
        print('AUD', sid, f'gain={gain:+.1f}dB', flush=True)
    for line in lines:
        if line['role'] != 'narrator':
            continue
        wav = Path(line['wav'])
        if not wav.exists():
            raise SystemExit(f'missing narrator wav: {wav}')
        tracks.append({'path': str(wav), 'role': 'speech', 'volume': 1.0,
                       'start_seconds': round(bounds[line['shot']] + float(line['offset']), 4)})
    bed = PROJECT / 'v3/audio/mix_v3/music_bed_v3.wav'
    if not bed.exists():
        raise SystemExit(f'missing music bed: {bed}')
    tracks.append({'path': str(bed), 'role': 'music', 'volume': 1.0, 'start_seconds': 0.0})
    config = {
        'operation': 'full_mix', 'tracks': tracks,
        'ducking': {'enabled': True, 'music_volume_during_speech': 0.30,
                    'attack_ms': 150, 'release_ms': 450},
        'normalize': False, 'target_duration': TARGET,
        'output_path': str(AUDIO / 'v4_mix_flat.wav'),
    }
    (AUDIO / 'v4_mix_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    from tools.audio.audio_mixer import AudioMixer
    result = AudioMixer().execute(config)
    if not result.success:
        raise SystemExit(f'AudioMixer failed: {result.error}')
    flat = AUDIO / 'v4_mix_flat.wav'
    level, _ = ebur128(flat)
    final = AUDIO / 'v4_mix.wav'
    gain = -16.0 - level
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(flat),
         '-af', f'volume={gain:.2f}dB,alimiter=limit=0.891:level=0,apad=whole_dur={TARGET},atrim=0:{TARGET}',
         '-ar', '48000', '-ac', '2', str(final)])
    final_level, peak = ebur128(final)
    if abs(final_level + 16.0) > 0.3:
        correction = -16.0 - final_level
        tmp = AUDIO / 'v4_mix_master_tmp.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(final),
             '-af', f'volume={correction:.2f}dB,alimiter=limit=0.891:level=0,apad=whole_dur={TARGET},atrim=0:{TARGET}',
             '-ar', '48000', '-ac', '2', str(tmp)])
        tmp.replace(final)
        final_level, peak = ebur128(final)
    (AUDIO / 'v4_mix_report.json').write_text(json.dumps({
        'output': str(final), 'duration': TARGET, 'lufs': final_level,
        'true_peak_dbfs': peak, 'flat_lufs': level, 'gain_db': gain,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('MIX', final, f'{final_level:.1f} LUFS / {peak:.1f} dBFS', flush=True)
    return final


def main() -> int:
    script = json.loads((V4 / 'script_v4.json').read_text(encoding='utf-8'))
    order = [s for section in script['sections'] for s in section['shots']]
    shots = {sid: json.loads((V4 / 'shots_v4' / f'{sid}.json').read_text(encoding='utf-8')) for sid in order}
    lines = json.loads((V4 / 'voiceover/vo_lines_v4.json').read_text(encoding='utf-8'))['lines']
    bounds, cursor = {}, 0.0
    for sid in order:
        bounds[sid] = cursor
        cursor += float(shots[sid]['duration_seconds'])
    silent = build_picture(order, shots)
    mix = build_audio(order, shots, lines, bounds)
    out = PROJECT / 'exports/kaochenghuang_v4.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(silent), '-i', str(mix),
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
         '-b:a', '192k', '-ar', '48000', '-ac', '2', '-t', f'{TARGET:.6f}',
         '-movflags', '+faststart', str(out)])
    print('EXPORT', out, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
