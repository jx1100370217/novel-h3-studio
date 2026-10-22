#!/usr/bin/env python3
"""Start the isolated ComfyUI service selected by this project."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from novel_h3.cli import DEFAULT_PROJECT, REPO
from novel_h3.comfy import config, api
from novel_h3.safety import bounded_worker, check_power_cap

# A paused project must not load a model just to serve health checks.
bounded_worker()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
options = parser.parse_args()
cfg = config(options.project.resolve())
from novel_h3.fastvideo import selected
if selected(cfg):
    os.execv(sys.executable, [sys.executable, str(REPO / 'start_fastvideo.py'), '--project', str(options.project.resolve())])
check_power_cap(cfg.get("resource_policy", {}).get("max_gpu_power_w", 450))
port = urlsplit(cfg["comfy_url"]).port or 8191
try:
    stats = api(cfg["comfy_url"], "/system_stats", timeout=2)
except OSError:
    stats = None
if stats:
    print(f"{port} 已有服务，请先检查 doctor；不会终止其他进程。")
    sys.exit(0)
comfy = Path(cfg["comfy_root"])
upstream = REPO / "vendor/ComfyUI-H3-Motion-Context"
if not upstream.is_dir():
    raise SystemExit("缺少 vendor，请按 README 获取固定提交")
target = comfy / "custom_nodes/ComfyUI-H3-Motion-Context"
if target.exists() or target.is_symlink():
    if target.resolve() != upstream.resolve():
        raise SystemExit("已存在另一份 Motion Context，先人工检查，避免重复加载")
else:
    target.symlink_to(upstream, target_is_directory=True)
runtime = REPO / "runtime"
whitelist = ["ComfyUI-H3-Motion-Context"]
if cfg.get("video_engine") == "vdn_h3_turbo" and cfg.get("vdn", {}).get("enabled"):
    vdn = REPO / "vendor/ComfyUI-VDN-H3"
    if not vdn.is_dir():
        raise SystemExit("缺少固定版本的 VDN-H3 扩展，请先运行 fetch_vendor.py")
    revision = subprocess.check_output(["git", "-C", str(vdn), "rev-parse", "HEAD"], text=True).strip()
    if revision != cfg["vdn"]["commit"]:
        raise SystemExit("VDN-H3 扩展版本与项目记录不符，请先核对")
    # Keep the user's original VDN install for their existing 8190 service.
    target = comfy / "custom_nodes/ComfyUI-VDN-H3-studio"
    if target.exists() or target.is_symlink():
        if target.resolve() != vdn.resolve():
            raise SystemExit("本项目 VDN-H3 节点路径被另一份安装占用")
    else:
        target.symlink_to(vdn, target_is_directory=True)
    whitelist.append("ComfyUI-VDN-H3-studio")
user_dir = cfg.get("user_dir", str(runtime / "comfy-user"))
database_url = cfg.get("database_url", "sqlite:///" + str(runtime / "comfyui.db"))
for folder in (cfg["input_dir"], cfg["output_dir"], user_dir):
    Path(folder).mkdir(parents=True, exist_ok=True)
if cfg.get("python_path"):
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (cfg["python_path"], existing)))
args = [str(comfy / ".venv/bin/python"), "main.py", "--listen", "127.0.0.1", "--port", str(port),
        "--input-directory", cfg["input_dir"], "--output-directory", cfg["output_dir"],
        "--user-directory", user_dir,
        "--database-url", database_url,
        # Evict earlier than the renderer's 4 GiB safety floor. These are
        # available-RAM thresholds, not cache-size limits.
        "--disable-api-nodes", "--cache-ram", "12", "16", "--fast-disk", "--disable-pinned-memory",
        "--reserve-vram", "4", "--disable-async-offload",
        "--disable-all-custom-nodes", "--whitelist-custom-nodes", *whitelist]
os.chdir(comfy)
os.execv(args[0], args)
