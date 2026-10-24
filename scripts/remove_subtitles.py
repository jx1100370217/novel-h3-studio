#!/usr/bin/env python3
"""Remove a fixed burned-in subtitle region with LaMa inpainting.

This is a last-resort cleanup for a shot where FastH3 keeps captioning a
spoken line after explicit no-text prompts. It processes only the subtitle
window, preserves the native audio, and leaves the raw take untouched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def probe(path: Path) -> dict:
    out = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                   '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
                                   '-show_entries', 'format=duration', '-of', 'json', str(path)], text=True)
    return json.loads(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--start', type=float, required=True)
    parser.add_argument('--end', type=float, required=True)
    parser.add_argument('--box', required=True, help='x0,y0,x1,y1 in source pixels')
    parser.add_argument('--fps', type=int, default=24)
    args = parser.parse_args()
    video = Path(args.video).resolve()
    out = Path(args.out).resolve()
    x0, y0, x1, y1 = [int(v) for v in args.box.split(',')]
    info = probe(video)
    duration = float(info['format']['duration'])
    total_frames = round(duration * args.fps)
    with tempfile.TemporaryDirectory(prefix='subtitle_remove_') as tmp:
        tmp = Path(tmp)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', str(video),
                        '-vsync', '0', '-start_number', '0', str(tmp / '%06d.png')], check=True)
        frames = sorted(tmp.glob('*.png'))
        if len(frames) < total_frames:
            total_frames = len(frames)
        from simple_lama_inpainting import SimpleLama
        lama = SimpleLama()
        first = max(0, int(round(args.start * args.fps)))
        last = min(len(frames), int(round(args.end * args.fps)))
        mask = Image.new('L', (info['streams'][0]['width'], info['streams'][0]['height']), 0)
        ImageDraw.Draw(mask).rectangle([x0, y0, x1, y1], fill=255)
        for index in range(first, last):
            frame = Image.open(frames[index]).convert('RGB')
            frame = lama(frame, mask)
            frame.save(frames[index])
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(args.fps),
                        '-i', str(tmp / '%06d.png'), '-i', str(video), '-map', '0:v:0', '-map', '1:a:0?',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p',
                        '-c:a', 'copy', '-shortest', '-movflags', '+faststart', str(out)], check=True)
    print(json.dumps({'out': str(out), 'frames': total_frames, 'processed': [first, last],
                      'duration': duration}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
