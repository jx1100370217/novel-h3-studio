#!/usr/bin/env python3
"""Register one completed Codex image_gen four-view master."""
import argparse
import datetime
from pathlib import Path

from novel_h3.character_views import register_turnaround
from novel_h3.project import digest, read


REPO = Path(__file__).resolve().parent
DEFAULT_ROOT = REPO / "projects/rendao-wuji"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("asset_id")
    parser.add_argument("source", type=Path)
    parser.add_argument("--project", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    root = args.project.resolve()
    job = read(root / "jobs" / f"image_{args.asset_id}__turnaround.json")
    receipt = {
        "tool": "image_gen",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "prompt": job["prompt"],
        "actual_model": "unknown",
        "model_verified": False,
        "tool_output_file": str(args.source.resolve()),
        "job_sha256": digest(job),
        "requested_model": "ChatGPT Images 2.5",
        "subscription": "ChatGPT 5x",
    }
    result = register_turnaround(root, args.asset_id, args.source, receipt)
    print(result["master_path"])


if __name__ == "__main__":
    main()
