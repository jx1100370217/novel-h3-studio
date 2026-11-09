"""Global picture + native-audio + narration + music compose module.

The cut is described by a JSON ComposeSpec, so new revisions do not need a
new ``v5_compose.py``. Native H3 dialogue/SFX stay in the takes; only narrator
lines are added as TTS, and the approved music bed is ducked underneath.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENMONTAGE = ROOT / 'openmontage'
if str(OPENMONTAGE) not in sys.path:
    sys.path.insert(0, str(OPENMONTAGE))


def resolve(path: str | Path) -> Path:
    path = Path(path)
    return path if path.is_absolute() else (ROOT / path).resolve()


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{result.stderr[-4000:]}")


def ebur128(path: Path) -> tuple[float, float]:
    result = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', str(path),
                             '-filter_complex', 'ebur128=peak=true', '-f', 'null', '-'],
                            capture_output=True, text=True)
    ints = re.findall(r'I:\s+(-?[\d.]+) LUFS', result.stderr)
    peaks = re.findall(r'Peak:\s+(-?[\d.]+) dBFS', result.stderr)
    return float(ints[-1]), float(peaks[-1]) if peaks else float('nan')


def video_frames(path: Path) -> int:
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
         'stream=nb_frames', '-of', 'default=nw=1:nk=1', str(path)],
        capture_output=True, text=True)
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return -1


def build_picture(spec: dict, order: list[str], shots: dict) -> Path:
    work = resolve(spec['work_dir']); clips = work / 'clips'; clips.mkdir(parents=True, exist_ok=True)
    graphics = {k: resolve(v) for k, v in spec.get('graphics', {}).items()}
    takes = resolve(spec['takes_dir'])
    fps, width, height = int(spec.get('fps', 24)), int(spec.get('width', 1344)), int(spec.get('height', 768))
    entries = []
    expected_frames = 0
    for sid in order:
        source = graphics.get(sid, takes / sid / 'native.mp4')
        if not source.is_file():
            raise FileNotFoundError(f'missing picture source for {sid}: {source}')
        frames = round(float(shots[sid]['duration_seconds']) * fps)
        out = clips / f'{sid}.mp4'
        filters = f'scale={width}:{height}:flags=lanczos,fps={fps},format=yuv420p'
        subtitles = spec.get('subtitles')
        if subtitles is not None and sid not in (subtitles.get('skip_shots') or []) and sid not in graphics:
            from .subtitles import build_shot_ass
            timing = None
            if subtitles.get('timing'):
                timing_map = json.loads(resolve(subtitles['timing']).read_text(encoding='utf-8'))
                timing = timing_map.get(sid)
            skip_lines = tuple((subtitles.get('skip_lines') or {}).get(sid) or ())
            ass = build_shot_ass(shots[sid], work / 'subs' / f'{sid}.ass',
                                 width=width, height=height, style=subtitles.get('style'),
                                 timing=timing, skip_lines=skip_lines)
            if ass is not None:
                filters += ',ass=' + str(ass).replace('\\', '/').replace(':', '\\:')
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(source), '-an',
             '-vf', filters,
             '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'veryfast',
             '-crf', '16', '-x264-params', 'keyint=48:min-keyint=48:scenecut=0',
             '-video_track_timescale', '24000', str(out)])
        print('PIC', sid, frames, flush=True)
        expected_frames += frames
        entries.append(out)
    listing = work / f'concat_{spec.get("tag", "cut")}.txt'
    listing.write_text(''.join(f"file '{p.resolve()}'\n" for p in entries), encoding='utf-8')
    silent = work / f'film_silent_{spec.get("tag", "cut")}.mp4'
    run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
         '-c', 'copy', '-fflags', '+genpts', '-movflags', '+faststart', str(silent)])
    actual = video_frames(silent)
    if actual != expected_frames:
        print(f'CONCAT REENCODE {actual} != {expected_frames} frames', flush=True)
        run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
             '-x264-params', 'keyint=48:min-keyint=48:scenecut=0',
             '-video_track_timescale', '24000', '-fflags', '+genpts',
             '-movflags', '+faststart', str(silent)])
    return silent


def build_audio(spec: dict, order: list[str], shots: dict, lines: list[dict], bounds: dict) -> Path:
    audio = resolve(spec['audio_dir']); audio.mkdir(parents=True, exist_ok=True)
    takes = resolve(spec['takes_dir'])
    graphics = {k: resolve(v) for k, v in spec.get('graphics', {}).items()}
    target = float(spec['target_duration'])
    tracks = []
    for sid in order:
        duration = float(shots[sid]['duration_seconds'])
        if sid in graphics:
            silence = audio / f'{sid}_silence.wav'
            run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                 '-t', f'{duration:.6f}', str(silence)])
            tracks.append({'path': str(silence), 'role': 'sfx', 'volume': 1.0,
                           'start_seconds': round(bounds[sid], 4)})
            continue
        native = takes / sid / 'native.mp4'
        raw = audio / f'{sid}_native_raw.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(native), '-vn',
             '-af', f'atrim=0:{duration:.6f},asetpts=PTS-STARTPTS', '-ar', '48000', '-ac', '2', str(raw)])
        level, _ = ebur128(raw)
        gain = max(-6.0, min(6.0, -24.0 - level))
        leveled = audio / f'{sid}_native.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(raw),
             '-af', f'volume={gain:.2f}dB,alimiter=limit=0.95:level=0', '-ar', '48000', '-ac', '2', str(leveled)])
        # Native dialogue and SFX form the speech bus so the music bed ducks
        # under every spoken take, not only under narration.
        tracks.append({'path': str(leveled), 'role': 'speech', 'volume': 1.0,
                       'start_seconds': round(bounds[sid], 4)})
        print('AUD', sid, f'gain={gain:+.1f}dB', flush=True)
    for line in lines:
        # A line with a wav path is intentionally post-layered: narration, or
        # an off-screen voice whose take was generated silent so H3 cannot
        # lip-sync the only visible listener.
        if not line.get('wav'):
            continue
        if line.get('role') not in ('narrator', 'off_screen'):
            continue
        wav = resolve(line['wav'])
        if not wav.is_file():
            raise FileNotFoundError(f'missing post dialogue wav: {wav}')
        # An off-screen post line joins the native SFX bus. The mixer's
        # speech+music ducking branch can truncate the whole mix at the end of
        # the short speech key when native SFX run longer; native dialogue is
        # already mixed as SFX, so this keeps the full programme and the low
        # music bed unchanged.
        role = 'speech' if line['role'] == 'narrator' else 'sfx'
        tracks.append({'path': str(wav), 'role': role, 'volume': 1.0,
                       'start_seconds': round(bounds[line['shot']] + float(line['offset']), 4)})
    def add_music(path: Path, start_seconds: float, volume: float,
                  fade_in: float = 0.0, fade_out: float = 0.0) -> None:
        tracks.append({'path': str(path), 'role': 'music', 'volume': volume,
                       'start_seconds': round(float(start_seconds), 4),
                       'fade_in_seconds': float(fade_in), 'fade_out_seconds': float(fade_out)})

    cues = spec.get('music_cues') or []
    if cues:
        for index, cue in enumerate(cues):
            source = resolve(cue['path'])
            duration = float(cue['duration_seconds'])
            source_start = float(cue.get('source_start_seconds', 0.0))
            trimmed = audio / f'music_{index:02d}.wav'
            run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', f'{source_start:.3f}',
                 '-t', f'{duration:.3f}', '-i', str(source), '-ar', '48000', '-ac', '2', str(trimmed)])
            level, _ = ebur128(trimmed)
            gain = -30.0 - level
            normalized = audio / f'music_{index:02d}_norm.wav'
            run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(trimmed),
                 '-af', f'volume={gain:.2f}dB,alimiter=limit=0.95:level=0',
                 '-ar', '48000', '-ac', '2', str(normalized)])
            add_music(normalized, float(cue.get('start_seconds', 0.0)),
                      float(cue.get('volume', spec.get('music_volume', 1.0))),
                      float(cue.get('fade_in_seconds', 0.0)),
                      float(cue.get('fade_out_seconds', 0.0)))
            print('MUSIC', index, f'{source_start:.1f}s', f'{duration:.1f}s',
                  f'{level:.1f}->{gain:+.1f}dB', flush=True)
    else:
        music = resolve(spec['music'])
        add_music(music, 0.0, float(spec.get('music_volume', 1.0)))
    tag = spec.get('tag', 'cut')
    ducking = spec.get('ducking') or {
        'enabled': True, 'music_volume_during_speech': 0.30,
        'attack_ms': 150, 'release_ms': 450,
    }
    config = {
        'operation': 'full_mix', 'tracks': tracks,
        'ducking': ducking,
        'normalize': False, 'target_duration': target,
        'output_path': str(audio / f'{tag}_mix_flat.wav'),
    }
    (audio / f'{tag}_mix_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    from tools.audio.audio_mixer import AudioMixer
    result = AudioMixer().execute(config)
    if not result.success:
        raise RuntimeError(f'AudioMixer failed: {result.error}')
    flat = audio / f'{tag}_mix_flat.wav'
    level, _ = ebur128(flat)
    final = audio / f'{tag}_mix.wav'
    gain = -16.0 - level
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(flat),
         '-af', f'volume={gain:.2f}dB,alimiter=limit=0.72:level=0,apad=whole_dur={target},atrim=0:{target}',
         '-ar', '48000', '-ac', '2', str(final)])
    final_level, peak = ebur128(final)
    if abs(final_level + 16.0) > 0.3:
        correction = -16.0 - final_level
        tmp = audio / f'{tag}_mix_master_tmp.wav'
        run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(final),
             '-af', f'volume={correction:.2f}dB,alimiter=limit=0.72:level=0,apad=whole_dur={target},atrim=0:{target}',
             '-ar', '48000', '-ac', '2', str(tmp)])
        tmp.replace(final)
        final_level, peak = ebur128(final)
    (audio / f'{tag}_mix_report.json').write_text(json.dumps({
        'output': str(final), 'duration': target, 'lufs': final_level,
        'true_peak_dbfs': peak, 'flat_lufs': level, 'gain_db': gain,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print('MIX', final, f'{final_level:.1f} LUFS / {peak:.1f} dBFS', flush=True)
    return final


def compose(spec_path: Path) -> dict:
    spec = json.loads(Path(spec_path).read_text(encoding='utf-8'))
    script = json.loads(resolve(spec['script']).read_text(encoding='utf-8'))
    order = [s for section in script['sections'] for s in section['shots']]
    shots = {sid: json.loads((resolve(spec['shots_dir']) / f'{sid}.json').read_text(encoding='utf-8')) for sid in order}
    lines = json.loads(resolve(spec['lines']).read_text(encoding='utf-8'))['lines']
    scene_cards = spec.get('scene_cards') or []
    for index, item in enumerate(scene_cards):
        from .scene_card import build_scene_card
        key = f'__scene_card_{index}__'
        card_path = resolve(spec['work_dir']) / f'scene_card_{index}.mp4'
        build_scene_card(
            card_path, act=item.get('act', ''), title=item.get('title', ''),
            place=item.get('place', ''), time=item.get('time', ''),
            duration_seconds=float(item.get('duration_seconds', 1.5)),
            fade_seconds=float(item.get('fade_seconds', 0.25)),
            width=int(spec.get('width', 1344)), height=int(spec.get('height', 768)),
            fps=int(spec.get('fps', 24)),
        )
        before = item.get('before_shot')
        if before not in order:
            raise ValueError(f'scene card before_shot {before!r} is not in the script order')
        spec.setdefault('graphics', {})[key] = str(card_path)
        shots[key] = {'duration_seconds': float(item.get('duration_seconds', 1.5))}
        order.insert(order.index(before), key)
        spec['target_duration'] = float(spec['target_duration']) + float(item.get('duration_seconds', 1.5))
        print('SCENE CARD', key, before, item.get('title', ''), flush=True)
    card = spec.get('end_card')
    if card:
        from .end_card import PROJECT_CREDIT, build_end_card
        card_seconds = float(card.get('duration_seconds', 3.0))
        card_path = resolve(spec['work_dir']) / f'end_card_{spec.get("tag", "cut")}.mp4'
        build_end_card(
            card_path, title=card['title'], source=card.get('source', ''),
            credits=tuple(card.get('credits') or ()),
            credit=card.get('credit') or PROJECT_CREDIT,
            duration_seconds=card_seconds,
            fade_in_seconds=float(card.get('fade_in_seconds', 0.0)),
            width=int(spec.get('width', 1344)), height=int(spec.get('height', 768)),
            fps=int(spec.get('fps', 24)),
        )
        spec.setdefault('graphics', {})['__end_card__'] = str(card_path)
        order = [*order, '__end_card__']
        shots['__end_card__'] = {'duration_seconds': card_seconds}
        spec['target_duration'] = float(spec['target_duration']) + card_seconds
        print('CARD', card_path, f'{card_seconds:.1f}s', flush=True)
    bounds, cursor = {}, 0.0
    for sid in order:
        bounds[sid] = cursor
        cursor += float(shots[sid]['duration_seconds'])
    silent = build_picture(spec, order, shots)
    mix = build_audio(spec, order, shots, lines, bounds)
    target = float(spec['target_duration'])
    output = resolve(spec['output']); output.parent.mkdir(parents=True, exist_ok=True)
    run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(silent), '-i', str(mix),
         '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
         '-ar', '48000', '-ac', '2', '-t', f'{target:.6f}', '-movflags', '+faststart', str(output)])
    print('EXPORT', output, flush=True)
    return {'output': str(output), 'silent': str(silent), 'mix': str(mix), 'duration': target}
