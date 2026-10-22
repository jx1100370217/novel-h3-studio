"""Render one strict-Ref2VA shot with the local FastH3-Omni NVFP4 QAD service.

The model runtime and the official Ref2VA validator live in the host
repository's ``novel_h3`` package. This tool is the OpenMontage entry point:
it reads a shot spec authored as the six-section Ref2VA format, submits it to
the local FastVideo service (default 127.0.0.1:8195), and returns the native
take (picture + H3 native dialogue/sound effects).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    RetryPolicy,
    ResumeSupport,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

DEFAULT_API = "http://127.0.0.1:8195"
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768


class FastVideoH3Video(BaseTool):
    name = "fastvideo_h3_video"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "video_generation"
    provider = "local_fastvideo"
    stability = ToolStability.EXPERIMENTAL
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = []
    install_instructions = (
        "Start the local FastVideo NVFP4 QAD service from the host repository:\n"
        "  python start_fastvideo.py --project <project>/config.json\n"
        "The service listens on 127.0.0.1:8195 by default."
    )
    agent_skills: list[str] = []
    best_for = [
        "strict six-section Ref2VA shots",
        "native H3 character dialogue and sound effects",
        "FastH3-Omni NVFP4 QAD 768P production",
    ]
    not_good_for = [
        "cloud rendering without the local service",
        "shots that need the legacy VDN-H3 Turbo checkpoint",
    ]
    fallback_tools = ["vdn_h3_video"]

    capabilities = ["strict_ref2va", "native_h3_audio", "batch_shot"]

    input_schema = {
        "type": "object",
        "required": ["shot_spec_path", "project"],
        "properties": {
            "shot_spec_path": {"type": "string", "description": "Path to the strict Ref2VA shot JSON spec."},
            "project": {"type": "string", "description": "Monorepo project directory that owns takes/."},
            "output_path": {"type": "string", "description": "Optional final path for the native mp4."},
            "api_url": {"type": "string", "default": DEFAULT_API},
            "width": {"type": "integer", "default": DEFAULT_WIDTH},
            "height": {"type": "integer", "default": DEFAULT_HEIGHT},
            "force": {"type": "boolean", "default": False},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "shot": {"type": "string"},
            "native_path": {"type": "string"},
            "output_path": {"type": "string"},
            "frames": {"type": "integer"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "seed": {"type": "integer"},
            "sha256": {"type": "string"},
            "inference_time_s": {"type": "number"},
            "wall_seconds": {"type": "number"},
        },
    }
    resume_support = ResumeSupport.FROM_CHECKPOINT
    idempotency_key_fields = ["shot_spec_path", "width", "height", "seed"]
    side_effects = ["writes native take under the project takes/ directory"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=2048, vram_mb=0, disk_mb=2048, network_required=False)
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=5)
    user_visible_verification = [
        "ffprobe the native take",
        "watch the take for cast count, identity and native dialogue",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from novel_h3.fastvideo_batch import load_spec, run_shot

        start = time.time()
        spec_path = Path(inputs["shot_spec_path"]).expanduser()
        if not spec_path.is_absolute():
            spec_path = (Path.cwd() / spec_path).resolve()
        if not spec_path.is_file():
            return ToolResult(success=False, error=f"shot spec not found: {spec_path}")
        project = Path(inputs["project"]).expanduser()
        if not project.is_absolute():
            project = (Path.cwd() / project).resolve()
        project.mkdir(parents=True, exist_ok=True)
        try:
            spec = load_spec(spec_path)
            receipt = run_shot(
                _REPO_ROOT,
                project,
                spec,
                api=str(inputs.get("api_url") or DEFAULT_API),
                force=bool(inputs.get("force")),
                width=int(inputs.get("width") or DEFAULT_WIDTH),
                height=int(inputs.get("height") or DEFAULT_HEIGHT),
            )
        except Exception as exc:  # noqa: BLE001 - surface the runtime error to the agent
            return ToolResult(success=False, error=str(exc))
        native = project / "takes" / spec["shot"] / "native.mp4"
        if not native.is_file():
            return ToolResult(success=False, error=f"native take missing after render: {native}")
        final = native
        if inputs.get("output_path"):
            final = Path(inputs["output_path"]).expanduser()
            if not final.is_absolute():
                final = (Path.cwd() / final).resolve()
            final.parent.mkdir(parents=True, exist_ok=True)
            if final != native:
                shutil.copy2(native, final)
        data = {
            "shot": spec["shot"],
            "native_path": str(native),
            "output_path": str(final),
            "frames": int(receipt.get("frames") or spec["frames"]),
            "width": int(receipt.get("width") or inputs.get("width") or DEFAULT_WIDTH),
            "height": int(receipt.get("height") or inputs.get("height") or DEFAULT_HEIGHT),
            "seed": int(receipt.get("seed") or spec["seed"]),
            "sha256": receipt.get("sha256") or hashlib.sha256(final.read_bytes()).hexdigest(),
            "inference_time_s": receipt.get("inference_time_s"),
            "wall_seconds": round(time.time() - start, 2),
        }
        return ToolResult(success=True, data=data, artifacts=[str(final)],
                          duration_seconds=data["wall_seconds"], seed=data["seed"],
                          model="fasth3-omni-nvfp4-qad")
