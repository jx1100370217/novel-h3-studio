"""Build a 480p coverage animatic from a V6 scene plan.

The animatic is the edit gate: stills/previs or frozen anchor frames, authored
shot durations, temp subtitles, and optional temp music. It is intentionally
cheap; a missing anchor frame is reported, not silently replaced by a pretty
placeholder.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .subtitles import build_shot_ass

FONT = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"


def _placeholder(path: Path, shot: dict, width: int, height: int) -> Path:
    image = Image.new("RGB", (width, height), (14, 14, 16))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 26, index=2)
    small = ImageFont.truetype(FONT, 18, index=2)
    draw.text((width // 2, height // 2 - 40), shot.get("id", "?"), font=font,
              fill=(238, 232, 220), anchor="mm")
    draw.text((width // 2, height // 2 + 6), str(shot.get("shot_intent") or shot.get("description") or ""),
              font=small, fill=(190, 185, 175), anchor="mm")
    draw.text((width // 2, height // 2 + 40), "NO ANCHOR FRAME", font=small,
              fill=(220, 120, 100), anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _pick_image(project: Path, shot: dict, fallback_dir: Path, width: int, height: int) -> tuple[Path, bool]:
    sid = str(shot.get("id"))
    for folder in ("anchor_frames", "previs", "keyframes"):
        for suffix in (".png", ".jpg", ".jpeg"):
            candidate = project / folder / f"{sid}{suffix}"
            if candidate.is_file():
                return candidate, True
    return _placeholder(fallback_dir / f"{sid}.png", shot, width, height), False


def build(project: Path, out: Path, report_path: Path, *, width: int = 854, height: int = 480,
          music: Path | None = None) -> dict:
    project = Path(project)
    scene_plan = json.loads((project / "artifacts/scene_plan.json").read_text(encoding="utf-8"))
    shots_dir = project / "shots"
    work = project / "animatic" / "work"
    work.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    cuts: list[dict] = []
    issues: list[str] = []
    warnings: list[str] = []
    cursor = 0.0
    previous = None
    for scene in scene_plan.get("scenes") or []:
        sid = str(scene.get("id"))
        shot = json.loads((shots_dir / f"{sid}.json").read_text(encoding="utf-8"))
        duration = float(shot.get("frames") or 0) / 24.0
        image, has_anchor = _pick_image(project, shot, work, width, height)
        if not has_anchor:
            issues.append(f"{sid}: missing anchor/previs/keyframe")
        clip = work / f"{sid}.mp4"
        ass = work / f"{sid}.ass"
        subtitle_filter = ""
        if shot.get("dialogue"):
            build_shot_ass(shot, ass, width=width, height=height)
            if ass.is_file():
                subtitle_filter = ",ass=" + str(ass).replace("\\", "/").replace(":", "\\:")
        vf = f"scale={width}:{height}:flags=lanczos,fps=24,format=yuv420p{subtitle_filter}"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image),
             "-t", f"{duration:.6f}", "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-x264-params", "keyint=24:min-keyint=24:scenecut=0",
             "-video_track_timescale", "24000", str(clip)], check=True)
        clips.append(clip)
        if previous is not None:
            cuts.append({"from_shot": previous, "to_shot": sid, "at_seconds": round(cursor, 3),
                         "verdict": "review" if not has_anchor else "pass"})
        previous = sid
        cursor += duration
    listing = work / "concat.txt"
    listing.write_text("".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8")
    silent = work / "animatic_silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(silent)],
                   check=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    if music and Path(music).is_file():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
                        "-stream_loop", "-1", "-i", str(music), "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                        "-movflags", "+faststart", str(out)], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v:0",
                        "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-shortest", "-movflags", "+faststart", str(out)], check=True)
    shot_counts: dict[str, int] = {}
    for scene in scene_plan.get("scenes") or []:
        key = str(scene.get("script_section_id") or scene.get("id"))
        shot_counts[key] = shot_counts.get(key, 0) + 1
    for key, count in shot_counts.items():
        if count > 8:
            warnings.append(f"{key}: {count} shots; consider fewer, longer takes")
    report = {
        "version": "1.0", "project_id": project.name,
        "animatic": str(out.resolve()), "duration_seconds": round(cursor, 3),
        "cuts": cuts, "issues": issues, "warnings": warnings,
        "verdict": "revise" if issues else "pass",
        "reviewer": "auto", "notes": "Human review required before assets.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--width", type=int, default=854)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--music", type=Path)
    args = parser.parse_args(argv)
    report = build(args.project.resolve(), args.out.resolve(), args.report.resolve(),
                   width=args.width, height=args.height, music=args.music)
    print(json.dumps({"animatic": report["animatic"], "duration": report["duration_seconds"],
                      "verdict": report["verdict"], "issues": len(report["issues"]),
                      "warnings": len(report["warnings"])}, ensure_ascii=False))
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
