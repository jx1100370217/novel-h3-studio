"""Official FastVideo/VSA-H3 runner used by the isolated benchmark.

The production worker remains on ComfyUI.  This module deliberately owns a
separate FastVideo process contract so that the upstream runtime can keep its
attention backend, distilled schedule and resident model cache without being
translated into a Comfy graph.  It is also safe to import when FastVideo is
not installed; the preflight then returns an actionable error.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _gpu_snapshot() -> dict[str, float | int] | None:
    """Read one inexpensive GPU sample for the benchmark record."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,power.draw",
             "--format=csv,noheader,nounits"],
            text=True, stderr=subprocess.DEVNULL, timeout=5,
        ).splitlines()[0].split(",")
        return {"memory_used_mib": int(float(out[0])), "memory_total_mib": int(float(out[1])),
                "temperature_c": float(out[2]), "power_w": float(out[3])}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _available_host_memory_bytes() -> int | None:
    """Return MemAvailable without importing a process-wide memory library."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _configured_scope_memory_bytes() -> int | None:
    """Read the model-worker cgroup limit, when the user service manager is available."""
    try:
        value = subprocess.check_output(
            ["systemctl", "--user", "show", "novel-h3-workloads.slice", "--property=MemoryMax", "--value"],
            text=True, stderr=subprocess.DEVNULL, timeout=3,
        ).strip()
        if value and value not in {"infinity", "max"}:
            return int(value)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _resolve_text_encoder_root(official: dict[str, Any], model_root: Path) -> Path:
    """Return the text-encoder checkpoint used by the official loader."""
    override = official.get("text_encoder_weights")
    if override:
        return Path(str(override)).expanduser().resolve()
    return (model_root / "text_encoder").resolve()


def _text_encoder_memory_report(model_root: Path, *, encoder_root: Path | None = None) -> dict[str, Any]:
    """Estimate the host-memory peak before FastVideo constructs Qwen3-VL.

    The official BF16 checkpoint is sharded on disk, but the loader still
    materializes the native conditioner while it reads those shards.  A
    serialized NVFP4 text-encoder directory is materially smaller and has a
    quantization_config marker, so it gets a separate estimate.
    """
    encoder = (encoder_root or (model_root / "text_encoder")).resolve()
    report: dict[str, Any] = {
        "checkpoint_present": encoder.is_dir(),
        "checkpoint_path": str(encoder),
        "quantized": False,
        "checkpoint_bytes": 0,
        "checkpoint_gib": 0.0,
        "available_bytes": _available_host_memory_bytes(),
        "available_gib": None,
        "scope_limit_bytes": _configured_scope_memory_bytes(),
        "scope_limit_gib": None,
        "available_for_process_gib": None,
        "estimated_peak_gib": None,
        "safe": None,
    }
    if report["available_bytes"] is not None:
        report["available_gib"] = round(report["available_bytes"] / 1024**3, 2)
    if report["scope_limit_bytes"] is not None:
        report["scope_limit_gib"] = round(report["scope_limit_bytes"] / 1024**3, 2)
    if not encoder.is_dir():
        return report
    try:
        config = json.loads((encoder / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config = {}
    report["quantized"] = bool(config.get("quantization_config"))
    try:
        index = json.loads((encoder / "model.safetensors.index.json").read_text(encoding="utf-8"))
        shard_names = sorted(set(index["weight_map"].values()))
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        shard_names = []
    report["checkpoint_bytes"] = sum(
        (encoder / name).stat().st_size
        for name in shard_names
        if (encoder / name).is_file()
    )
    report["checkpoint_gib"] = round(report["checkpoint_bytes"] / 1024**3, 2)
    if report["quantized"]:
        # Serialized NVFP4 keeps the vision/embedding tensors and loads the
        # packed language projections without the 48+ GiB BF16 resident copy.
        peak_bytes = max(20 * 1024**3, report["checkpoint_bytes"] * 1.35 + 4 * 1024**3)
    else:
        # The native 50-layer conditioner is documented at roughly 48 GiB
        # resident; leave headroom for tokenizer, allocator and VAE/DiT setup.
        peak_bytes = max(56 * 1024**3, report["checkpoint_bytes"] * 0.9)
    report["estimated_peak_gib"] = round(peak_bytes / 1024**3, 2)
    available = report["available_bytes"]
    if report["scope_limit_bytes"] is not None:
        available = min(available, report["scope_limit_bytes"]) if available is not None else report["scope_limit_bytes"]
    if available is not None:
        report["available_for_process_gib"] = round(available / 1024**3, 2)
        report["safe"] = available >= peak_bytes
    return report


def preflight(root: Path, *, model_root: Path | None = None) -> dict[str, Any]:
    """Validate the official runtime without loading a model."""
    root = Path(root).resolve()
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    fast = cfg.get("fastvideo", {})
    official = fast.get("official", {})
    selected = Path(model_root or official.get("model_root", "")).expanduser()
    runtime_python = Path(official.get("runtime_python", sys.executable)).expanduser()
    result: dict[str, Any] = {
        "backend": "fastvideo_vsa_h3",
        "repository": official.get("runtime_repo", "https://github.com/hao-ai-lab/FastVideo"),
        "model_card": fast.get("model_card"),
        "model_root": str(selected),
        "runtime_python": str(runtime_python),
        "runtime_python_present": runtime_python.is_file(),
        "runtime_repo_present": bool(official.get("runtime_repo") and Path(official["runtime_repo"]).is_dir()),
        "model_root_present": selected.is_dir(),
        "required_components": [],
        "missing_components": [],
        "gpu_count": int(official.get("num_gpus", 1)),
        "vsa_kernel": official.get("vsa_kernel", "triton"),
        "vsa_sparsity": float(official.get("vsa_sparsity", 0.8)),
        "vsa_tile_size": int(official.get("vsa_tile_size", 64)),
    }
    # The upstream runner needs the Diffusers export, not a Comfy single-file
    # repack.  In particular, the component indices and checkpoint manifest
    # are what prevent a partial/symlinked adapter from being mistaken for the
    # official VSA checkpoint.
    required = ("modular_model_index.json", "checkpoint_content.json", "fastvideo_inference.json",
                "transformer/config.json", "transformer/diffusion_pytorch_model.safetensors.index.json",
                "text_encoder/config.json", "text_encoder/model.safetensors.index.json",
                "tokenizer/tokenizer.json", "processor/preprocessor_config.json", "vae/config.json",
                "vae/diffusion_pytorch_model.safetensors.index.json", "audio_vae/config.json",
                "audio_vae/diffusion_pytorch_model.safetensors", "scheduler/scheduler_config.json",
                "audio_scheduler/scheduler_config.json")
    result["required_components"] = list(required)
    if selected.is_dir():
        result["missing_components"] = [name for name in required if not (selected / name).is_file()]
    else:
        result["missing_components"] = list(required)
    result["ready"] = bool(result["runtime_repo_present"] and result["runtime_python_present"] and result["model_root_present"]
                            and not result["missing_components"])
    if result["ready"]:
        # Validate every shard named by the three index files before spawning
        # FastVideo worker processes.  This catches interrupted downloads.
        for index_name in ("transformer/diffusion_pytorch_model.safetensors.index.json",
                           "text_encoder/model.safetensors.index.json",
                           "vae/diffusion_pytorch_model.safetensors.index.json"):
            try:
                index = json.loads((selected / index_name).read_text(encoding="utf-8"))
                shard_names = sorted(set(index["weight_map"].values()))
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                shard_names = []
            missing = [f"{Path(index_name).parent}/{name}" for name in shard_names
                       if not (selected / Path(index_name).parent / name).is_file()]
            if missing:
                result["missing_components"].extend(missing)
        result["ready"] = not result["missing_components"]
    encoder_root = _resolve_text_encoder_root(official, selected)
    result["text_encoder_weights"] = str(encoder_root)
    if not encoder_root.is_dir():
        result["missing_components"].append("text_encoder_weights/config.json")
        result["ready"] = False
    else:
        for name in ("config.json", "model.safetensors.index.json"):
            if not (encoder_root / name).is_file():
                result["missing_components"].append(f"text_encoder_weights/{name}")
        try:
            index = json.loads((encoder_root / "model.safetensors.index.json").read_text(encoding="utf-8"))
            shard_names = sorted(set(index["weight_map"].values()))
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            shard_names = []
        result["missing_components"].extend(
            f"text_encoder_weights/{name}" for name in shard_names
            if not (encoder_root / name).is_file()
        )
        result["ready"] = not result["missing_components"]
    result["host_memory"] = _text_encoder_memory_report(selected, encoder_root=encoder_root)
    guard = official.get("host_memory_guard", {})
    if result["ready"] and guard.get("enabled", True) and result["host_memory"]["safe"] is False:
        result["ready"] = False
        result["resource_error"] = (
            "官方 FastVideo 文本编码器为未量化 BF16，预计主机内存峰值 "
            f"{result['host_memory']['estimated_peak_gib']} GiB，当前可用 "
            f"{result['host_memory']['available_for_process_gib'] or result['host_memory']['available_gib']} GiB"
            "（含模型隔离组限制）；为避免再次触发系统 OOM，已拒绝加载。"
        )
        result["next_step"] = (
            "先生成并配置 FastVideo 兼容的 MiniMax-H3 NVFP4 文本编码器，"
            "或在可用内存达到预计峰值后再运行官方 VSA-H3。"
        )
    result["note"] = (
        "官方模型卡要求 VSA-H3；RTX 5090 单卡使用 Triton fallback、层级卸载和惰性组件加载，"
        "GPU 数量必须整除 56 个注意力头。"
        if result["gpu_count"] == 1 else "官方 VSA-H3 并行路径。"
    )
    if runtime_python.is_file() and Path(sys.executable).resolve() != runtime_python.resolve():
        result["runtime_python_warning"] = (
            "当前解释器不是官方 runner 专用环境；请使用 runtime_python 指向的解释器运行该 CLI。"
        )
    return result


def _configure_environment(args: Any) -> dict[str, str]:
    env = {
        "FASTVIDEO_ATTENTION_BACKEND": "VIDEO_SPARSE_ATTN_H3",
        # FastVideo's resolver otherwise may select a compiled SM100/CuTe
        # route when it is present.  The requested comparison is explicitly
        # the upstream VSA-H3 Triton kernel.
        "FASTVIDEO_VSA_TRITON": "1",
        "FASTVIDEO_VSA_SM100A": "0",
        "FASTVIDEO_VSA_CUTEDSL": "0",
        "FASTVIDEO_FA4": "0",
        "FASTVIDEO_MINIMAX_H3_FUSIONS": "0",
        "FASTVIDEO_INFERENCE_TORCH_COMPILE": "0",
        "FASTVIDEO_VAE_PARALLEL_DECODE": "0",
        "FASTVIDEO_STAGE_LOGGING": "1",
        # Upstream's eager state-dict collector briefly retains the complete
        # ~70 GB BF16 DiT in host RAM. Stream each tensor for the single-GPU
        # FSDP path so the 44 GiB workload cgroup remains a real guard.
        "FASTVIDEO_STREAM_WEIGHT_LOAD": "1",
        # FastH3-8-Step-V2 contains trained VSA compression gates. Keep them
        # by default so the official checkpoint and Triton path match. A
        # caller may explicitly set this diagnostic override to ``1`` for
        # long shots that exceed a single 32-GiB card's activation budget.
        "FASTVIDEO_H3_DISABLE_ZERO_VSA_GATE": os.environ.get(
            "FASTVIDEO_H3_DISABLE_ZERO_VSA_GATE", "0"),
    }
    os.environ.update(env)
    return env


def _build_generator_config(args: Any) -> Any:
    from fastvideo.api import (CompileConfig, ComponentConfig, EngineConfig, GeneratorConfig,
                               OffloadConfig, ParallelismConfig, PipelineSelection)

    text_encoder_weights = getattr(args, "text_encoder_weights", None)
    return GeneratorConfig(
        model_path=str(args.model_root),
        pipeline=PipelineSelection(components=ComponentConfig(text_encoder_weights=text_encoder_weights), experimental={
            "VSA_sparsity": args.vsa_sparsity,
            "VSA_tile_size": args.vsa_tile_size,
            "video_decode_backend": "h3-vae",
            "vae_parallel_decode": False,
            "vae_parallel_decode_strategy": "gather",
        }),
        engine=EngineConfig(
            num_gpus=args.num_gpus,
            execution_backend="mp",
            # The full FastH3 DiT is ~70 GB in BF16.  On a single RTX 5090,
            # FSDP inference with CPU offload is required at *load* time: the
            # layerwise hook is installed only after loading and therefore
            # cannot prevent an OOM while the 14 shards are materialised.
            use_fsdp_inference=True,
            parallelism=ParallelismConfig(tp_size=1, sp_size=args.num_gpus),
            # CPU offload is deliberately paired with FSDP (and layerwise
            # offload is disabled because FastVideo resolves the two modes as
            # mutually exclusive). Lazy component loading still prevents the
            # encoder, DiT and VAEs from overlapping.
            offload=OffloadConfig(dit=True, dit_layerwise=False, text_encoder=True, vae=True,
                                  pin_cpu_memory=False, lazy_module_load=True),
            compile=CompileConfig(enabled=False, mode=None, vae_enabled=False),
        ),
    )


def run_shot(root: Path, episode: dict[str, Any], shot: dict[str, Any], *, output: Path,
             model_root: Path | None = None) -> dict[str, Any]:
    """Generate one shot through the upstream FastVideo API and write a receipt."""
    root = Path(root).resolve()
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    official = cfg.get("fastvideo", {}).get("official", {})
    selected = Path(model_root or official.get("model_root", "")).expanduser().resolve()
    check = preflight(root, model_root=selected)
    if not check["ready"]:
        raise RuntimeError("官方 FastVideo 预检未通过: " + json.dumps(check, ensure_ascii=False))
    # Import project prompt helpers only after preflight so a missing runtime
    # never mutates state or starts a worker.
    from .director import h3_prompt
    from .project import write
    runtime_repo = Path(official.get("runtime_repo", "")).expanduser().resolve()
    if str(runtime_repo) not in sys.path:
        sys.path.insert(0, str(runtime_repo))
    from fastvideo import VideoGenerator
    from fastvideo.api import GenerationRequest, OutputConfig, SamplingConfig

    class Args:
        pass
    args = Args()
    args.model_root = selected
    args.text_encoder_weights = str(_resolve_text_encoder_root(official, selected))
    args.num_gpus = int(official.get("num_gpus", 1))
    args.vsa_sparsity = float(official.get("vsa_sparsity", 0.8))
    args.vsa_tile_size = int(official.get("vsa_tile_size", 64))
    args.height = int(cfg["generation"]["height"])
    args.width = int(cfg["generation"]["width"])
    args.steps = int(official.get("steps", 9))
    args.fps = int(cfg["generation"]["fps"])
    args.seed = int(shot["seed"])
    prompt = h3_prompt(dict(shot, references=[], asset_package={}, speech_bindings={}), cfg["style"])
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    _configure_environment(args)
    started = time.time()
    before = _gpu_snapshot()
    generator = VideoGenerator.from_config(_build_generator_config(args))
    try:
        request = GenerationRequest(
            prompt=prompt, negative_prompt="",
            sampling=SamplingConfig(height=args.height, width=args.width,
                                     num_frames=int(shot["frames"]), fps=args.fps,
                                     num_inference_steps=args.steps, guidance_scale=1.0,
                                     batch_cfg=False, seed=args.seed),
            output=OutputConfig(output_path=str(output), save_video=True, return_frames=False),
        )
        result = generator.generate(request)
        actual = Path(getattr(result, "video_path", output)).resolve()
    finally:
        generator.shutdown()
    ended = time.time()
    after = _gpu_snapshot()
    if not actual.is_file():
        raise RuntimeError(f"FastVideo 未写出视频: {actual}")
    receipt = {
        "backend": "fastvideo_vsa_h3",
        "model_root": str(selected),
        "shot_id": shot["id"], "episode_id": episode["id"],
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "seed": args.seed, "width": args.width, "height": args.height,
        "frames_requested": int(shot["frames"]), "fps": args.fps, "steps": args.steps,
        "started_at": started, "ended_at": ended, "elapsed_seconds": ended - started,
        "gpu_before": before, "gpu_after": after, "output": str(actual),
        "output_sha256": _sha256(actual), "environment": dict(_configure_environment(args)),
        "vsa": {"kernel": check["vsa_kernel"], "sparsity": check["vsa_sparsity"],
                "tile_size": check["vsa_tile_size"], "num_gpus": check["gpu_count"]},
    }
    write(output.with_suffix(".official_result.json"), receipt)
    return receipt


__all__ = ["preflight", "run_shot"]
