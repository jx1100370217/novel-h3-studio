"""Explicit frame-based review edits of immutable native H3 candidates.

Timeline: {"fps": 24, "tracks": [{"kind": "av", "segments": [
  {"take_dir": "production_v2/.../takes/c_...", "source_in_frame": 0,
   "source_out_frame": 48, "audio_take_dir": "...", "audio_in_frame": 24}
]}], "subtitles": [{"start_frame": 0, "end_frame": 24, "text": "..."}],
"final_loudnorm": false}. Out points are exclusive. Omitted audio follows
the same native take and source in point. Explicit audio overrides permit
J/L cuts and reaction coverage without altering a source file.
"""
from fractions import Fraction
from pathlib import Path
import os
import subprocess
import tempfile
import time

from ..media import probe, technical_qc
from ..project import digest, file_hash, inside, locked, read, write


def _integer(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(field + ' must be a non-negative integer frame')
    return value


def _timecode(frame):
    milliseconds = round(frame * 1000 / 24)
    return (f'{milliseconds // 3600000:02}:{milliseconds // 60000 % 60:02}:'
            f'{milliseconds // 1000 % 60:02},{milliseconds % 1000:03}')


def _load_take(root, relative):
    directory = inside(root, relative)
    receipt = read(inside(root, str(directory / 'take.json')))
    if receipt.get('technical_qc', {}).get('passed') is not True:
        raise ValueError('Native take has not passed technical QC: ' + str(relative))
    video, audio = directory / 'native.mp4', directory / 'native_audio.flac'
    for path, field in ((video, 'video_sha256'), (audio, 'native_audio_sha256')):
        # Resolve individual files too: a symlink must not escape the project.
        path = inside(root, str(path))
        if not path.is_file() or file_hash(path) != receipt.get(field):
            raise ValueError('Native source hash mismatch: ' + str(path))
    video_stream = next(s for s in probe(video)['streams'] if s['codec_type'] == 'video')
    audio_stream = next(s for s in probe(audio)['streams'] if s['codec_type'] == 'audio')
    if Fraction(video_stream['avg_frame_rate']) != 24:
        raise ValueError('Native source must be 24 fps')
    frames = video_stream.get('nb_frames')
    if not frames or frames == 'N/A':
        frames = subprocess.check_output([
            'ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames', '-of', 'default=nw=1:nk=1', str(video)], text=True).strip()
    audio_seconds = (int(audio_stream['duration_ts']) * Fraction(audio_stream['time_base'])
                     if audio_stream.get('duration_ts') is not None else Fraction(audio_stream['duration']))
    return {'take_dir': str(directory.relative_to(root)), 'video': video, 'audio': audio,
            'video_sha256': receipt['video_sha256'], 'native_audio_sha256': receipt['native_audio_sha256'],
            'frames': int(frames), 'audio_seconds': audio_seconds,
            'audio_tail_tolerance': (Fraction(1, 80) + Fraction(1, int(audio_stream['sample_rate']))
                if receipt.get('audio_route') in ('h3_native_joint', 'h3_audio_conditioned') else Fraction(1, int(audio_stream['sample_rate']))),
            'sample_rate': int(audio_stream['sample_rate']),
            'width': video_stream['width'], 'height': video_stream['height']}


def _run(command):
    subprocess.run(command, check=True, capture_output=True, timeout=600)


def export_review(root, timeline):
    """Return a versioned review manifest; never approve takes or rewrite media."""
    root = Path(root).resolve()
    timeline = read(inside(root, str(timeline))) if isinstance(timeline, (str, Path)) else timeline
    if type(timeline.get('fps')) is not int or timeline['fps'] != 24:
        raise ValueError('Timeline fps must be the integer 24')
    tracks = timeline.get('tracks', [])
    if len(tracks) != 1 or tracks[0].get('kind') != 'av' or not tracks[0].get('segments'):
        raise ValueError('Provide one explicit av track with non-empty segments')
    loudnorm = timeline.get('final_loudnorm', False)
    if type(loudnorm) is not bool:
        raise ValueError('final_loudnorm must be a boolean')
    takes, segments, cursor = {}, [], 0
    for spec in tracks[0]['segments']:
        picture_name = spec['take_dir']
        sound_name = spec.get('audio_take_dir', picture_name)
        for name in (picture_name, sound_name):
            if name not in takes:
                takes[name] = _load_take(root, name)
        picture, sound = takes[picture_name], takes[sound_name]
        start = _integer(spec['source_in_frame'], 'source_in_frame')
        end = _integer(spec['source_out_frame'], 'source_out_frame')
        audio_start = _integer(spec.get('audio_in_frame', start), 'audio_in_frame')
        length = end - start
        if length <= 0 or end > picture['frames']:
            raise ValueError('Picture in/out range exceeds native frames or is empty')
        audio_end = Fraction(audio_start + length, 24)
        if (audio_end > sound['audio_seconds'] + sound['audio_tail_tolerance']
                or audio_start + length > sound['frames']):
            raise ValueError('Audio in/out range exceeds the native audio duration')
        segments.append({'take_dir': picture['take_dir'], 'video_sha256': picture['video_sha256'],
                         'source_in_frame': start, 'source_out_frame': end,
                         'audio_take_dir': sound['take_dir'], 'native_audio_sha256': sound['native_audio_sha256'],
                         'audio_in_frame': audio_start, 'audio_out_frame': audio_start + length,
                         'audio_tail_padding_seconds': float(max(Fraction(0), audio_end - sound['audio_seconds'])),
                         'timeline_in_frame': cursor, 'timeline_out_frame': cursor + length,
                         'timeline_in_timecode': _timecode(cursor), 'timeline_out_timecode': _timecode(cursor + length),
                         'source_in_timecode': _timecode(start), 'source_out_timecode': _timecode(end),
                         'audio_in_timecode': _timecode(audio_start), 'audio_out_timecode': _timecode(audio_start + length)})
        cursor += length
    sizes = {(takes[spec['take_dir']]['width'], takes[spec['take_dir']]['height'])
             for spec in tracks[0]['segments']}
    if len(sizes) != 1:
        raise ValueError('Native sources must have matching picture dimensions for this review edit')
    width, height = sizes.pop()
    subtitle_lines = []
    for cue in timeline.get('subtitles', []):
        start, end = _integer(cue['start_frame'], 'subtitle start'), _integer(cue['end_frame'], 'subtitle end')
        if not 0 <= start < end <= cursor or not isinstance(cue.get('text'), str) or not cue['text'].strip():
            raise ValueError('Subtitle must contain text and a valid timeline frame range')
        subtitle_lines.append(f"{len(subtitle_lines) + 1}\n{_timecode(start)} --> {_timecode(end)}\n{cue['text'].strip()}\n")
    font_hashes = {cue['font_file']: file_hash(cue['font_file']) for cue in timeline.get('typography', [])}
    version = digest({'schema': 'cinema_edit_v1', 'exporter_sha256': file_hash(Path(__file__)),
                      'font_hashes': font_hashes, 'timeline': timeline, 'resolved_segments': segments})
    destination = root / 'review_exports' / version[:20]
    progress_path = root / 'review_exports/progress.json'
    def progress(stage, completed):
        write(progress_path, {'stage': stage, 'completed': completed, 'total': len(segments),
              'worker_pid': os.getpid(), 'updated_at': time.time(), 'version': version})
    with locked(root, 'cinema_review_export'):
        if destination.exists():
            cached = read(destination / 'manifest.json')
            if cached.get('version_sha256') != version or file_hash(destination / 'review.mp4') != cached.get('video_sha256'):
                raise ValueError('Existing versioned export has changed; refusing overwrite')
            if file_hash(destination / 'review.srt') != cached.get('subtitles_sha256'):
                raise ValueError('Existing versioned subtitles have changed; refusing overwrite')
            return cached
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.edit_', dir=destination.parent) as temporary:
            work = Path(temporary)
            intermediate = work / 'lossless'
            intermediate.mkdir()
            progress('rendering_segments', 0)
            for index, segment in enumerate(segments):
                picture = inside(root, segment['take_dir']) / 'native.mp4'
                sound = inside(root, segment['audio_take_dir']) / 'native_audio.flac'
                frames = segment['timeline_out_frame'] - segment['timeline_in_frame']
                filters = (
                    f"[0:v:0]trim=start_frame={segment['source_in_frame']}:end_frame={segment['source_out_frame']},"
                    'setpts=PTS-STARTPTS,setsar=1[v];'
                    f"[1:a:0]atrim=start={segment['audio_in_frame'] / 24:.12f}:end={segment['audio_out_frame'] / 24:.12f},"
                    'asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,'
                    f'apad=whole_len={frames * 2000},atrim=end_sample={frames * 2000}[a]')
                _run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-i', str(picture), '-i', str(sound),
                      '-filter_complex_threads', '2', '-filter_complex', filters, '-map', '[v]', '-map', '[a]',
                      '-c:v', 'ffv1', '-threads', '2', '-c:a', 'pcm_s24le', '-ar', '48000', '-ac', '2',
                      str(intermediate / f'part_{index:04d}.nut')])
                progress('rendering_segments', index + 1)
            concat = intermediate / 'concat.txt'
            # NUT retains exact rational timestamps for 24 fps, unlike the
            # millisecond rounding of Matroska at very short cut boundaries.
            concat.write_text(''.join(f"file 'part_{index:04d}.nut'\n" for index in range(len(segments))))
            video = work / 'review.mp4'
            progress('encoding_chapter', len(segments))
            from .typography import rasterize
            typography = rasterize(timeline.get('typography', []), width, height, work / 'typography', cursor)
            command = ['ffmpeg', '-nostdin', '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', str(concat),
                       ]
            for cue in typography:
                command += ['-loop', '1', '-framerate', '24', '-i', str(cue['path'])]
            if typography:
                filters, last = [], '0:v:0'
                for index, cue in enumerate(typography, 1):
                    output = f'text_{index}'
                    filters.append(f"[{last}][{index}:v:0]overlay=0:0:shortest=1:enable='between(n,{cue['start_frame']},{cue['end_frame']-1})'[{output}]")
                    last = output
                command += ['-filter_complex_threads', '2', '-filter_complex', ';'.join(filters), '-map', f'[{last}]']
            else:
                command += ['-map', '0:v:0']
            command += ['-map', '0:a:0', '-c:v', 'libx264', '-threads', '2',
                       '-crf', '18', '-preset', 'medium', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '256k',
                       '-ar', '48000', '-ac', '2', '-movflags', '+faststart']
            if loudnorm:
                command += ['-af', 'loudnorm=I=-16:TP=-1:LRA=11']
            _run(command + [str(video)])
            qc = technical_qc(video, cursor, width, height)
            if not qc['passed']:
                raise ValueError('Review edit failed technical QC: ' + str(qc['errors']))
            # Detect concurrent source mutation before publishing the review.
            for name, original in takes.items():
                current = _load_take(root, name)
                if any(current[key] != original[key] for key in ('video_sha256', 'native_audio_sha256')):
                    raise ValueError('Native source changed during review export')
            subtitles = work / 'review.srt'
            subtitles.write_text('\n'.join(subtitle_lines), encoding='utf-8')
            manifest = {'schema': 'cinema_edit_v1', 'version_sha256': version, 'timeline': timeline,
                        'output_dir': str(destination.relative_to(root)),
                        'video': str((destination / 'review.mp4').relative_to(root)), 'video_sha256': file_hash(video),
                        'subtitles': str((destination / 'review.srt').relative_to(root)), 'subtitles_sha256': file_hash(subtitles),
                        'subtitles_timing_basis': 'authored_timeline_not_verified_articulation',
                        'fps': 24, 'frames': cursor, 'seconds': cursor / 24, 'segments': segments,
                        'typography': [dict(cue, path=str((destination / 'typography' / cue['path'].name).relative_to(root))) for cue in typography],
                        'audio': {'sample_rate': 48000, 'channels': 2, 'intermediate_codec': 'pcm_s24le',
                                  'per_shot_normalization': False, 'final_loudnorm': loudnorm},
                        'technical_qc': qc, 'release_approved': False, 'human_listened': False,
                        'av_sync_review': {'status': 'not_evaluated', 'video_examined': False,
                                           'note': 'Editing and technical checks do not verify phoneme-to-mouth synchrony.'}}
            write(work / 'manifest.json', manifest)
            work.rename(destination)
            progress('completed', len(segments))
            return manifest
