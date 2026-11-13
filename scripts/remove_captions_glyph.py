#!/usr/bin/env python3
"""Remove FastH3's burned-in captions with a glyph mask + LaMa inpainting.

FastH3 often renders the spoken line as white Chinese text in the lower third.
A full-width subtitle band hides too much of the frame. This script detects the
white glyphs only, dilates the mask a few pixels, and inpaints just those
pixels with LaMa. Frames without detected glyphs are copied untouched.

The raw takes in ``assets/shots`` are never modified. Cleaned composition
copies are written to ``public/shots`` (the directory Remotion serves through
``staticFile("shots/...")``).

Usage:
  .venv-dialogue/bin/python scripts/remove_captions_glyph.py \
      --project projects/<id>
  .venv-dialogue/bin/python scripts/remove_captions_glyph.py \
      --project projects/<id> --shots S01,S02 --force
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from simple_lama_inpainting import SimpleLama


def log(message: str) -> None:
    print(message, flush=True)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_fps(video: Path) -> float:
    value = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "default=nw=1:nk=1", str(video)],
        text=True,
    ).strip()
    num, den = value.split("/") if "/" in value else (value, "1")
    return float(num) / float(den or 1)


def probe_duration(video: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)], text=True).strip())


def glyph_mask(frame: np.ndarray, top_fraction: float, threshold: int,
               saturation: int, dilate: int) -> np.ndarray:
    h, w = frame.shape[:2]
    y0 = int(h * top_fraction)
    crop = frame[y0:]
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    mask = ((gray > threshold) & (hsv[:, :, 1] < saturation)).astype(np.uint8) * 255
    kernel = np.ones((dilate, dilate), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    full = np.zeros((h, w), np.uint8)
    full[y0:] = mask
    return full


def clean_video(video: Path, output: Path, lama: SimpleLama, args: argparse.Namespace) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    fps = probe_fps(video)
    duration = probe_duration(video)
    with tempfile.TemporaryDirectory(prefix="glyph_caption_") as tmp:
        tmp = Path(tmp)
        frames = tmp / "frames"
        frames.mkdir()
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video),
             "-vsync", "0", "-start_number", "0", str(frames / "%06d.png")],
            check=True,
        )
        frame_paths = sorted(frames.glob("*.png"))
        cleaned = 0
        for index, frame_path in enumerate(frame_paths):
            image = Image.open(frame_path).convert("RGB")
            arr = np.array(image)
            mask = glyph_mask(arr, args.top_fraction, args.threshold,
                              args.saturation, args.dilate)
            if int(mask.sum() // 255) < args.min_pixels:
                continue
            image = lama(image, Image.fromarray(mask))
            image.save(frame_path)
            cleaned += 1
        if cleaned == 0:
            log(f"  no glyphs found; copying original video")
            shutil.copy2(video, output)
            return {"shot": video.stem, "frames": len(frame_paths), "cleaned_frames": 0,
                    "method": "copy"}
        tmp_out = output.with_suffix(".tmp.mp4")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
             "-i", str(frames / "%06d.png"), "-i", str(video),
             "-map", "0:v:0", "-map", "1:a:0?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
             "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest",
             "-movflags", "+faststart", str(tmp_out)],
            check=True,
        )
        tmp_out.replace(output)
    return {"shot": video.stem, "frames": len(frame_paths), "cleaned_frames": cleaned,
            "method": "lama_glyph", "duration": round(duration, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--shots", default="", help="comma-separated ids; default all")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="default: <project>/public/shots")
    parser.add_argument("--top-fraction", type=float, default=0.80,
                        help="search for glyphs in the bottom (1 - this) of the frame")
    parser.add_argument("--threshold", type=int, default=165,
                        help="grayscale threshold for white glyphs")
    parser.add_argument("--saturation", type=int, default=85,
                        help="maximum HSV saturation for glyph pixels")
    parser.add_argument("--dilate", type=int, default=9,
                        help="dilation kernel size around glyphs")
    parser.add_argument("--min-pixels", type=int, default=80,
                        help="skip frames with fewer glyph pixels than this")
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--force", action="store_true",
                        help="reprocess even when the output is newer than the source")
    args = parser.parse_args()

    project = args.project.resolve()
    shots_dir = project / "assets/shots"
    out_dir = (args.out_dir or project / "public/shots").resolve()
    wanted = [s.strip() for s in args.shots.split(",") if s.strip()] or sorted(
        p.stem for p in shots_dir.glob("S*.mp4")
    )
    lama = SimpleLama()
    rows = []
    for index, sid in enumerate(wanted, 1):
        video = shots_dir / f"{sid}.mp4"
        if not video.is_file():
            log(f"MISSING {sid} ({index}/{len(wanted)})")
            continue
        output = out_dir / f"{sid}.mp4"
        marker_dir = out_dir / ".caption_cleanup"
        marker = marker_dir / f"{sid}.json"
        source_stat = video.stat()
        if marker.is_file() and not args.force:
            try:
                previous = json.loads(marker.read_text(encoding="utf-8"))
            except Exception:
                previous = {}
            if (previous.get("source_size") == source_stat.st_size
                    and previous.get("source_mtime") == source_stat.st_mtime
                    and output.is_file()):
                log(f"SKIP {sid} (already cleaned for this source take)")
                rows.append({"shot": sid, "method": "skip"})
                continue
        log(f"CLEAN {sid} ({index}/{len(wanted)})")
        result = clean_video(video, output, lama, args)
        rows.append(result)
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({
            "shot": sid,
            "source": str(video),
            "source_size": source_stat.st_size,
            "source_mtime": source_stat.st_mtime,
            "output": str(output),
            "method": result.get("method"),
            "cleaned_frames": result.get("cleaned_frames"),
            "frames": result.get("frames"),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log(f"  cleaned {result.get('cleaned_frames', 0)}/{result.get('frames', 0)} frames")
    report = project / "artifacts/caption_cleanup.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"version": "1.0", "shots": rows}, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    log(f"DONE {len(rows)} shots -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
