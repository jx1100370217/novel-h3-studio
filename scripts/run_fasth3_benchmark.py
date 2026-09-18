#!/usr/bin/env python3
"""Run one controlled VDN-H3 vs FastH3-8-Step-V2 benchmark in ComfyUI.

The caller must keep the production video worker paused. ComfyUI is restarted
between cases so its model cache cannot contaminate timing or memory readings.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_h3.fastvideo_benchmark import run_case
from novel_h3.project import read, write
from novel_h3.director import episode_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--episode", default="chapter_s0004")
    parser.add_argument("--shots", default="C4D001,C4D002,C4D003", help="逗号分隔的镜头 ID")
    parser.add_argument("--case", choices=("vdn", "fast"), required=True)
    args = parser.parse_args()
    root = args.project.resolve()
    episode = read(episode_path(root, args.episode))
    shot_ids = [x.strip() for x in args.shots.split(",") if x.strip()]
    shots = [next(s for s in episode["shots"] if s["id"] == shot_id) for shot_id in shot_ids]
    cfg = read(root / "config.json")
    common = {"model_mode": "fl2va", "shift_audio": 3.0}
    cases = []
    if args.case in ("vdn", "both"):
        cases.append(("vdn_h3", dict(common, model_filename=cfg["models"]["fl2va"],
                                       vdn_enabled=True, shift_video=12.0,
                                       compatibility_note="生产 VDN-H3 Turbo 基准路径。")))
    if args.case in ("fast", "both"):
        fast = cfg.get("fastvideo", {})
        cases.append(("fasth3_8step_v2", dict(common,
            model_filename=fast["model_filename"], vdn_enabled=False,
            shift_video=float(fast.get("scheduler_shift_video", 10.0)),
            compatibility_note=fast.get("compatibility_note"))))
    results = []
    for shot in shots:
        for label, engine in cases:
            results.append(run_case(root, episode, shot, label, engine))
    by_shot = {}
    for row in results:
        by_shot.setdefault(row["shot_id"], []).append(row)
    summary = {"episode_id": args.episode, "shot_ids": shot_ids, "results": results,
               "comparison": {shot_id: {"same_prompt": len({r["prompt_sha256"] for r in rows}) == 1,
                                    "same_seed": len({r["seed"] for r in rows}) == 1,
                                    "same_frames": len({r["frames_requested"] for r in rows}) == 1}
                              for shot_id, rows in by_shot.items()}}
    out = root / "benchmarks" / "fasth3" / f"{args.case}_comparison.json"
    write(out, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
