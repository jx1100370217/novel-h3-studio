"""Controlled FastH3 vs VDN-H3 ComfyUI benchmark for one existing shot."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .comfy import api, graph, schema_check
from .director import episode_path
from .media import technical_qc
from .project import digest, file_hash, read, write


def _gpu_snapshot() -> dict:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"], text=True, timeout=5)
        row = out.strip().splitlines()[0].split(",")
        return {"gpu_mib": float(row[0]), "gpu_total_mib": float(row[1]),
                "temperature_c": float(row[2]), "power_w": float(row[3])}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {}


def _wait_history(base: str, prompt_id: str, timeout: float = 1800.0) -> dict:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        history = api(base, "/history")
        if prompt_id in history:
            record = history[prompt_id]
            status = record.get("status", {})
            if status.get("completed") or status.get("status_str") == "error":
                return record
        time.sleep(2)
    raise TimeoutError(f"ComfyUI 基准任务超时: {prompt_id}")


def run_case(root: Path, episode: dict, shot: dict, label: str, engine: dict) -> dict:
    cfg = read(root / "config.json")
    info = api(cfg["comfy_url"], "/object_info")
    take_id = "b_" + uuid.uuid4().hex[:12]
    nodes, prefix, sheet = graph(root, episode, shot, take_id, stage_assets=False,
                                 return_package=True, benchmark_engine=dict(engine, label=label))
    errors = schema_check(nodes, info)
    if errors:
        raise ValueError("基准图 schema 错误: " + "\n".join(errors))
    out_dir = root / "benchmarks" / "fasth3" / shot["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet_path = out_dir / f"{label}_execution_sheet.json"
    write(sheet_path, sheet)
    prompt_path = out_dir / f"{label}_prompt.json"
    write(prompt_path, nodes)
    started = time.time()
    before = _gpu_snapshot()
    response = api(cfg["comfy_url"], "/prompt", {"prompt": nodes, "client_id": take_id,
                                                     "extra_data": {"novel_h3_benchmark": label,
                                                                    "benchmark_take": take_id}})
    record = _wait_history(cfg["comfy_url"], response["prompt_id"])
    ended = time.time()
    status = record.get("status", {})
    if status.get("status_str") == "error":
        raise RuntimeError(json.dumps(status.get("messages", []), ensure_ascii=False))
    folder = Path(cfg["output_dir"]) / prefix
    videos = sorted(folder.glob("video*.mp4"))
    if len(videos) != 1:
        raise RuntimeError(f"基准输出不是唯一视频: {folder}")
    dest = out_dir / f"{label}.mp4"
    shutil.copy2(videos[0], dest)
    after = _gpu_snapshot()
    qc = technical_qc(dest, shot["frames"], cfg["generation"]["width"], cfg["generation"]["height"])
    result = {
        "label": label,
        "engine": engine,
        "shot_id": shot["id"],
        "episode_id": episode["id"],
        "prompt_sha256": sheet["model_input"]["prompt_sha256"],
        "seed": shot["seed"],
        "width": cfg["generation"]["width"], "height": cfg["generation"]["height"],
        "frames_requested": shot["frames"], "fps": cfg["generation"]["fps"],
        "steps": cfg["generation"]["steps"],
        "started_at": started, "ended_at": ended, "elapsed_seconds": ended - started,
        "gpu_before": before, "gpu_after": after,
        "comfy_prompt_id": response["prompt_id"],
        "output": str(dest.relative_to(root)), "output_sha256": file_hash(dest),
        "technical_qc": qc,
        "compatibility": engine.get("compatibility_note"),
    }
    write(out_dir / f"{label}_result.json", result)
    return result
