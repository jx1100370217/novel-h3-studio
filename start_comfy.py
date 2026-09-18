#!/usr/bin/env python3
"""Start the isolated H3 service with pinned Motion Context and VDN-H3 nodes."""
import os
from pathlib import Path
import subprocess
import sys

from novel_h3.cli import DEFAULT_PROJECT, REPO
from novel_h3.comfy import config, api
from novel_h3.safety import bounded_worker, check_power_cap

# A pause marker stops generation workers, but must not prevent the model
# service itself from starting and serving health checks.
bounded_worker(ignore_pause=True)

cfg = config(DEFAULT_PROJECT)
check_power_cap(cfg.get("resource_policy", {}).get("max_gpu_power_w", 450))
try:
    stats = api(cfg["comfy_url"], "/system_stats", timeout=2)
except OSError:
    stats = None
if stats:
    print("8191 已有服务，请先检查 doctor；不会终止其他进程。")
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
if cfg.get("vdn", {}).get("enabled"):
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
for folder in (cfg["input_dir"], cfg["output_dir"], str(runtime / "comfy-user")):
    Path(folder).mkdir(parents=True, exist_ok=True)
args = [str(comfy / ".venv/bin/python"), "main.py", "--listen", "127.0.0.1", "--port", "8191",
        "--input-directory", cfg["input_dir"], "--output-directory", cfg["output_dir"],
        "--user-directory", str(runtime / "comfy-user"),
        "--database-url", "sqlite:///" + str(runtime / "comfyui.db"),
        "--disable-api-nodes", "--cache-ram", "4", "8", "--fast-disk", "--disable-pinned-memory",
        "--reserve-vram", "4", "--disable-async-offload",
        "--disable-all-custom-nodes", "--whitelist-custom-nodes", *whitelist]
os.chdir(comfy)
os.execv(args[0], args)
