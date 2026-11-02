"""Frame-level native-caption detector for H3 takes.

The per-shot OCR audit samples only a few frames and can miss short captions;
this scanner walks the take at a fixed rate, looks for white text-like
components in the lower subtitle band, and confirms candidates with Tesseract.
It is deliberately conservative: a shot is marked ``native`` only when OCR
finds at least two CJK characters on a text-like row. Strong-but-unreadable
rows are recorded as ``suspect`` for human review.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

CJK = re.compile(r"[\u3400-\u9fff]")
BAND_TOP = 0.74
BAND_BOTTOM = 0.99


def _text_rows(band: np.ndarray) -> list[tuple[int, int, int, int]]:
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
    comps = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if 8 <= h <= 55 and 3 <= w <= 110 and area >= 12:
            comps.append((int(x), int(y), int(w), int(h)))
    rows = []
    for comp in comps:
        cy = comp[1] + comp[3] / 2
        placed = False
        for row in rows:
            if abs(row["cy"] - cy) <= 9:
                row["items"].append(comp)
                row["cy"] = (row["cy"] * (len(row["items"]) - 1) + cy) / len(row["items"])
                placed = True
                break
        if not placed:
            rows.append({"cy": cy, "items": [comp]})
    out = []
    for row in rows:
        items = sorted(row["items"])
        if len(items) < 3:
            continue
        left = min(item[0] for item in items)
        right = max(item[0] + item[2] for item in items)
        top = min(item[1] for item in items)
        bottom = max(item[1] + item[3] for item in items)
        if right - left >= 60 and bottom - top >= 10:
            out.append((left, top, right - left, bottom - top))
    return out


def _ocr_band(band: np.ndarray, workdir: Path) -> str:
    path = workdir / "band.png"
    cv2.imwrite(str(path), cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
    result = subprocess.run(
        ["tesseract", str(path), "-", "-l", "chi_sim", "--psm", "6"],
        capture_output=True, text=True,
    )
    return "".join(CJK.findall(result.stdout))


def audit_video(video: Path, *, step: int = 3) -> dict:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    hits = []
    suspects = []
    index = 0
    with tempfile.TemporaryDirectory(prefix="native_sub_") as tmp:
        tmp = Path(tmp)
        while index < frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            top = int(h * BAND_TOP)
            bottom = int(h * BAND_BOTTOM)
            band = frame[top:bottom, int(w * 0.10):int(w * 0.90)]
            rows = _text_rows(band)
            if rows:
                text = _ocr_band(band, tmp)
                t = round(index / fps, 3)
                if len(text) >= 2:
                    hits.append({"at_seconds": t, "text": text, "rows": len(rows)})
                else:
                    suspects.append({"at_seconds": t, "rows": len(rows)})
            index += step
    cap.release()
    return {
        "path": str(video),
        "fps": round(float(fps), 3),
        "sampled_every": step,
        "native": bool(hits),
        "hits": hits,
        "suspects": suspects,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--takes-dir", type=Path, required=True)
    parser.add_argument("--shots", default="", help="Comma-separated shot ids")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--step", type=int, default=3, help="Scan every Nth frame")
    parser.add_argument("--native-shots-out", type=Path, default=None,
                        help="Optional JSON list of native shot ids")
    args = parser.parse_args(argv)
    wanted = [s.strip() for s in args.shots.split(",") if s.strip()]
    if not wanted:
        wanted = sorted(p.name for p in args.takes_dir.iterdir() if p.is_dir())
    report = {}
    for sid in wanted:
        video = args.takes_dir / sid / "native.mp4"
        if not video.is_file():
            continue
        report[sid] = audit_video(video, step=args.step)
        print(sid, "native" if report[sid]["native"] else "clean",
              len(report[sid]["hits"]), "hits", len(report[sid]["suspects"]), "suspects")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.native_shots_out:
        args.native_shots_out.write_text(
            json.dumps([sid for sid, item in report.items() if item["native"]], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
