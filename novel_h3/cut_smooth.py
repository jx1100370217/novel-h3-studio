"""Soften micro-jumps at hard cuts without changing duration or audio.

Adjacent H3 takes are independent generations: a video continuation preserves
the ending pose, but not the exact camera position, so two near-identical
coverages can shift the boat, lantern or a shoulder by a few pixels at the cut.
This pass blends the upper picture across the cut (default two frames) while
leaving the subtitle band on a hard cut, so captions never double-expose. The
frame count, timeline and audio stream are unchanged.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np


def blend_pair(previous: np.ndarray, current: np.ndarray, *, alpha: float = 0.33,
               subtitle_band: float = 0.72) -> tuple[np.ndarray, np.ndarray]:
    """Return the two replacement frames for a cut.

    ``alpha`` is the weight of the incoming frame in the first blend. The top
    ``subtitle_band`` of the picture is cross-blended; the bottom stays on the
    outgoing frame for the first replacement and on the incoming frame for the
    second, so burned captions keep a clean hard cut.
    """
    if previous.shape != current.shape:
        raise ValueError('cut frames must have the same shape')
    height = previous.shape[0]
    band = max(0, min(height, int(round(height * subtitle_band))))
    first = previous.copy()
    second = current.copy()
    if band:
        first[:band] = (previous[:band].astype(np.float32) * (1.0 - alpha)
                        + current[:band].astype(np.float32) * alpha).clip(0, 255).astype(np.uint8)
        second[:band] = (previous[:band].astype(np.float32) * alpha
                         + current[:band].astype(np.float32) * (1.0 - alpha)).clip(0, 255).astype(np.uint8)
    return first, second


def smooth_video(video: Path, cuts: list[float], output: Path, *,
                 subtitle_band: float = 0.72, crf: int = 16) -> dict:
    import cv2

    video = Path(video)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f'cannot open {video}')
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cut_frames = sorted({int(round(float(t) * fps)) for t in cuts if float(t) > 0})
    hold_at = {frame - 1 for frame in cut_frames if frame > 0}
    cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{width}x{height}', '-r', str(fps),
        '-i', '-',
        '-i', str(video),
        '-map', '0:v:0', '-map', '1:a?',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(crf),
        '-pix_fmt', 'yuv420p', '-video_track_timescale', '24000',
        '-c:a', 'copy', '-shortest', '-movflags', '+faststart',
        str(output),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    held: np.ndarray | None = None
    index = 0
    blended = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if index in hold_at:
                held = frame
            elif held is not None:
                first, second = blend_pair(held, frame, subtitle_band=subtitle_band)
                proc.stdin.write(first.tobytes())
                proc.stdin.write(second.tobytes())
                held = None
                blended += 1
            else:
                proc.stdin.write(frame.tobytes())
            index += 1
        if held is not None:
            proc.stdin.write(held.tobytes())
    finally:
        cap.release()
        proc.stdin.close()
    returncode = proc.wait()
    if returncode != 0:
        raise RuntimeError(f'ffmpeg cut smoothing failed with {returncode}')
    return {'video': str(video), 'output': str(output), 'cuts': cut_frames,
            'blended_cuts': blended, 'fps': fps, 'frames': index,
            'width': width, 'height': height}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--cuts', required=True,
                        help='Comma-separated cut times in seconds (first frame of the next shot)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--subtitle-band', type=float, default=0.72,
                        help='Bottom fraction kept on a hard cut (default 0.72 starts the band)')
    parser.add_argument('--crf', type=int, default=16)
    args = parser.parse_args(argv)
    cuts = [float(item) for item in args.cuts.split(',') if item.strip()]
    if not cuts:
        parser.error('at least one cut time is required')
    result = smooth_video(args.video, cuts, args.output,
                          subtitle_band=args.subtitle_band, crf=args.crf)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
