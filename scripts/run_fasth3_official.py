#!/usr/bin/env python3
"""Run the same controlled shots through FastVideo's official VSA-H3 API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from novel_h3.director import episode_path
from novel_h3.fastvideo_runner import preflight, run_shot
from novel_h3.project import read, write
from novel_h3.safety import bounded_worker


def main() -> None:
    # Official benchmarking is independent of the production pause marker,
    # but it must still be contained so a loader failure cannot cause a global
    # OOM that takes the workbench down with it.
    bounded_worker(ignore_pause=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--episode", default="chapter_s0004")
    parser.add_argument("--shots", default="C4D001,C4D002,C4D003")
    parser.add_argument("--model-root", type=Path, default=None,
                        help="官方 FastVideo 模型目录；默认读取项目 config.json")
    args = parser.parse_args()
    root = args.project.resolve()
    check = preflight(root, model_root=args.model_root)
    print(json.dumps({"preflight": check}, ensure_ascii=False, indent=2))
    if not check["ready"]:
        raise SystemExit(2)
    episode = read(episode_path(root, args.episode))
    shot_ids = [value.strip() for value in args.shots.split(",") if value.strip()]
    shots = [next(shot for shot in episode["shots"] if shot["id"] == shot_id) for shot_id in shot_ids]
    results = []
    out_dir = root / "benchmarks" / "fasth3" / "official_vsa_h3"
    for shot in shots:
        results.append(run_shot(root, episode, shot, output=out_dir / f"{shot['id']}.mp4",
                                model_root=args.model_root))
    summary = {"backend": "fastvideo_vsa_h3", "episode_id": args.episode,
               "shot_ids": shot_ids, "preflight": check, "results": results}
    path = root / "benchmarks" / "fasth3" / "official_vsa_h3_comparison.json"
    write(path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
