#!/usr/bin/env python3
"""Fetch exact upstream commits on a fresh checkout without changing existing repos."""
from pathlib import Path
import subprocess

from novel_h3.project import read

root = Path(__file__).resolve().parent
names = {"motion_context": "ComfyUI-H3-Motion-Context", "arcreel": "ArcReel", "vdn": "ComfyUI-VDN-H3"}
for key, item in read(root / "upstream.json").items():
    target = root / "vendor" / names[key]
    if target.exists():
        result = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], check=True, text=True, capture_output=True)
        if result.stdout.strip() != item["commit"]:
            raise SystemExit(f"{target} 版本不符；保留现有目录，请先检查")
        print(f"保留固定版本：{target}")
        continue
    target.parent.mkdir(exist_ok=True)
    subprocess.run(["git", "clone", "--no-checkout", item["url"], str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "checkout", "--detach", item["commit"]], check=True)
