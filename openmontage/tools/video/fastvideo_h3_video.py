"""FastH3-Omni NVFP4 QAD video generation through a local FastVideo service.

The service exposes the official MiniMax-H3 Ref2VA HTTP contract on loopback:
``POST /v1/videos``, ``GET /v1/videos/{id}`` and
``GET /v1/videos/{id}/content``.  Every clip is generated with synchronized
native audio, so dialogue and diegetic sound come from the model rather than a
separate TTS pass.

The service is Ref2VA-only: at least one image reference is required, and the
canvas must stay within 1,032,192 pixels (1344x768 by default).  Frame counts
must land on the causal-VAE grid ``17n + 5``.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ResumeSupport,
    RetryPolicy,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

DEFAULT_API_URL = "http://127.0.0.1:8195"
DEFAULT_MODEL = "fasth3-omni-nvfp4-qad"
DEFAULT_WIDTH = 1344
DEFAULT_HEIGHT = 768
DEFAULT_FRAMES = 192
MIN_FRAMES = 124
MAX_FRAMES = 362
MAX_PIXELS = 1032192
MAX_REFERENCE_IMAGES = 3
MAX_REFERENCE_AUDIOS = 3
MAX_REFERENCE_VIDEOS = 1
FPS = 24


def _frames_on_grid(frames: int) -> bool:
    return isinstance(frames, int) and 124 <= frames <= 362 and (frames - 5) % 17 == 0


def _frames_for_duration(seconds: float) -> int:
    """Smallest legal frame count that covers ``seconds`` at 24 fps."""
    target = max(MIN_FRAMES, int(round(float(seconds) * FPS)))
    steps = max(0, (target - 5 + 16) // 17)
    return min(MAX_FRAMES, 5 + 17 * steps)


class FastVideoH3Video(BaseTool):
    name = "fastvideo_h3_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    capability = "video_generation"
    provider = "fastvideo"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU
    resume_support = ResumeSupport.FROM_CHECKPOINT
    quality_score = 0.95

    dependencies: list[str] = []
    install_instructions = (
        "Start the local FastH3-Omni NVFP4 QAD service on an RTX 5090.\n"
        "  The service must accept POST /v1/videos with task='ref2va'.\n"
        "  Set FASTVIDEO_H3_API_URL to override the default http://127.0.0.1:8195.\n"
        "  Image, audio and video reference files must live under the service's\n"
        "  configured server.media_roots."
    )
    agent_skills = ["minimax-h3", "ai-video-gen"]

    capabilities = ["reference_to_video"]
    supports = {
        "reference_to_video": True,
        "reference_image": True,
        "reference_video": True,
        "reference_audio": True,
        "native_audio": True,
        "offline": True,
        "seed": True,
        "custom_size": True,
    }
    best_for = [
        "local MiniMax-H3 Ref2VA generation with synchronized native audio",
        "1344x768 / 24 fps period-drama shots with consistent character references",
        "zero per-clip API cost on a single RTX 5090",
    ]
    not_good_for = [
        "text-only generation (the service is Ref2VA-only)",
        "clips shorter than 124 frames or longer than 362 frames",
        "machines without the 68.9 GB NVFP4 QAD model and AdaLN table",
    ]
    fallback_tools = ["minimax_video", "pika_video", "seedance_video"]

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=44000, vram_mb=30000, disk_mb=5000, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=0)
    side_effects = [
        "runs the local FastVideo GPU service for several minutes per clip",
        "writes an MP4, prompt, request and receipt JSON to the project workspace",
    ]
    user_visible_verification = [
        "Watch the clip with sound: identity, motion, dialogue and lip sync",
        "Check the receipt frame count, canvas, seed and prompt hash",
    ]

    input_schema = {
        "type": "object",
        "required": ["prompt", "reference_image_paths", "output_path"],
        "properties": {
            "prompt": {
                "type": "string",
                "minLength": 1,
                "description": (
                    "MiniMax-H3 Ref2VA prompt. Use the six-section structure: "
                    "subject_definitions, summary, retention_analysis, "
                    "detailed_description, overall_soundscape, non_diegetic_music. "
                    "Chinese dialogue goes inside <d>[Chinese] ...</d>."
                ),
            },
            "operation": {
                "type": "string",
                "enum": ["reference_to_video"],
                "default": "reference_to_video",
            },
            "reference_image_paths": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": MAX_REFERENCE_IMAGES,
                "description": "Local character/scene reference images, in <Picture N> order.",
            },
            "reference_audio_paths": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_REFERENCE_AUDIOS,
                "description": "Local voice-reference WAVs, in <Audio N> order.",
            },
            "reference_video_paths": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": MAX_REFERENCE_VIDEOS,
                "description": "Optional previous-take tail for shot-to-shot continuation.",
            },
            "width": {"type": "integer", "default": DEFAULT_WIDTH},
            "height": {"type": "integer", "default": DEFAULT_HEIGHT},
            "num_frames": {
                "type": "integer",
                "description": "Frame count on the 17n+5 grid (124-362, 5.2-15.1 seconds).",
            },
            "duration": {
                "type": ["integer", "number"],
                "description": "Seconds; rounded up to the next legal frame count. Alias for num_frames.",
            },
            "seed": {"type": "integer", "minimum": 0},
            "output_path": {
                "type": "string",
                "description": "Explicit project-workspace MP4 path.",
            },
            "job_path": {
                "type": "string",
                "description": "Optional path to persist the submitted job id for resume.",
            },
            "resume_job_id": {
                "type": "string",
                "description": "Poll an already-submitted job instead of submitting a new one.",
            },
            "timeout_seconds": {"type": "integer", "default": 2700},
        },
    }

    # ---- HTTP helpers -------------------------------------------------

    def base_url(self) -> str:
        return (
            os.environ.get("FASTVIDEO_H3_API_URL", "").strip()
            or DEFAULT_API_URL
        ).rstrip("/")

    def get_status(self):
        try:
            with urllib.request.urlopen(self.base_url() + "/health", timeout=0.6) as response:
                if response.status == 200:
                    from tools.base_tool import ToolStatus

                    return ToolStatus.AVAILABLE
        except (OSError, urllib.error.URLError):
            pass
        from tools.base_tool import ToolStatus

        return ToolStatus.UNAVAILABLE

    @staticmethod
    def _json_request(url: str, payload: dict | None = None, timeout: float = 180.0) -> dict:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    # ---- Request construction -----------------------------------------

    @staticmethod
    def _resolve_files(paths: list[str] | None, label: str) -> list[str]:
        resolved = []
        for raw in paths or []:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve()
            if not path.is_file():
                raise ValueError(f"{label} does not exist: {raw}")
            resolved.append(str(path))
        return resolved

    def _build_payload(self, inputs: dict[str, Any]) -> tuple[dict, dict]:
        prompt = str(inputs.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("prompt is required")

        images = self._resolve_files(inputs.get("reference_image_paths"), "reference image")
        if not images:
            raise ValueError("at least one reference image is required (Ref2VA-only service)")
        if len(images) > MAX_REFERENCE_IMAGES:
            raise ValueError(f"at most {MAX_REFERENCE_IMAGES} reference images are supported")
        audios = self._resolve_files(inputs.get("reference_audio_paths"), "reference audio")
        videos = self._resolve_files(inputs.get("reference_video_paths"), "reference video")

        width = int(inputs.get("width") or DEFAULT_WIDTH)
        height = int(inputs.get("height") or DEFAULT_HEIGHT)
        if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
            raise ValueError(
                f"canvas {width}x{height} exceeds the {MAX_PIXELS}-pixel FastVideo limit"
            )
        if width % 32 or height % 32:
            raise ValueError("width and height must be 32-aligned")

        frames = inputs.get("num_frames")
        if frames is None and inputs.get("duration") is not None:
            frames = _frames_for_duration(float(inputs["duration"]))
        frames = int(frames or DEFAULT_FRAMES)
        if not _frames_on_grid(frames):
            raise ValueError(f"num_frames must be on the 17n+5 grid, got {frames}")
        if frames > MAX_FRAMES:
            raise ValueError(f"num_frames must be <= {MAX_FRAMES} (about 15.1 seconds)")

        seed = inputs.get("seed")
        seed = int(seed) if seed is not None else int.from_bytes(os.urandom(4), "big") % 2_147_483_647

        payload = {
            "model": DEFAULT_MODEL,
            "task": "ref2va",
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_frames": frames,
            "fps": FPS,
            "num_inference_steps": 8,
            "guidance_scale": 1.0,
            "seed": seed,
            "image_reference": [{"image_url": path} for path in images],
            "audio_reference": [{"audio_url": path} for path in audios],
        }
        if videos:
            payload["video_reference"] = [{"video_url": path} for path in videos]
        meta = {
            "frames": frames,
            "duration_seconds": round(frames / FPS, 4),
            "width": width,
            "height": height,
            "seed": seed,
            "reference_images": images,
            "reference_audios": audios,
            "reference_videos": videos,
        }
        return payload, meta

    # ---- Execution -----------------------------------------------------

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        started = time.time()
        output_path = inputs.get("output_path")
        if not output_path:
            return ToolResult(success=False, error="output_path is required")
        output = Path(output_path).expanduser()
        if not output.is_absolute():
            output = Path.cwd() / output
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)

        job_id = str(inputs.get("resume_job_id") or "").strip()
        payload: dict = {}
        meta: dict = {}
        try:
            if not job_id:
                payload, meta = self._build_payload(inputs)
                submitted = self._json_request(self.base_url() + "/v1/videos", payload)
                job_id = submitted["id"]
                if inputs.get("job_path"):
                    job_path = Path(str(inputs["job_path"])).expanduser().resolve()
                    job_path.parent.mkdir(parents=True, exist_ok=True)
                    job_path.write_text(job_id, encoding="utf-8")
            else:
                meta = {
                    "frames": int(inputs.get("num_frames") or 0),
                    "width": int(inputs.get("width") or DEFAULT_WIDTH),
                    "height": int(inputs.get("height") or DEFAULT_HEIGHT),
                    "seed": inputs.get("seed"),
                }
                payload, built = self._build_payload({**inputs, "resume_job_id": ""})
                meta = built
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            return ToolResult(
                success=False,
                error=f"FastVideo submit HTTP {exc.code}: {body[:1200]}",
                duration_seconds=round(time.time() - started, 2),
                model=DEFAULT_MODEL,
            )
        except (ValueError, KeyError) as exc:
            return ToolResult(success=False, error=str(exc))

        deadline = time.monotonic() + int(inputs.get("timeout_seconds") or 2700)
        status: dict = {}
        while time.monotonic() < deadline:
            try:
                status = self._json_request(self.base_url() + "/v1/videos/" + job_id, timeout=60)
            except (TimeoutError, socket.timeout, urllib.error.URLError,
                    ConnectionError, http.client.HTTPException):
                time.sleep(5)
                continue
            if status.get("status") == "completed":
                break
            if status.get("status") == "failed":
                error_path = output.with_suffix(".error.json")
                error_path.write_text(
                    json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return ToolResult(
                    success=False,
                    error=f"FastVideo job {job_id} failed: {status.get('error')}",
                    duration_seconds=round(time.time() - started, 2),
                    model=DEFAULT_MODEL,
                )
            time.sleep(5)
        else:
            return ToolResult(
                success=False,
                error=f"FastVideo job {job_id} timed out; resume with resume_job_id={job_id}",
                duration_seconds=round(time.time() - started, 2),
                model=DEFAULT_MODEL,
            )

        content_url = self.base_url() + "/v1/videos/" + job_id + "/content"
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(content_url, timeout=600) as response, output.open("wb") as target:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    target.write(chunk)
        except (OSError, http.client.HTTPException, urllib.error.URLError) as exc:
            return ToolResult(
                success=False,
                error=f"FastVideo download failed: {exc}",
                duration_seconds=round(time.time() - started, 2),
                model=DEFAULT_MODEL,
            )

        receipt = {
            "tool": self.name,
            "model": DEFAULT_MODEL,
            "job_id": job_id,
            "status": status.get("status"),
            "inference_time_s": status.get("inference_time_s"),
            "frames": meta.get("frames"),
            "duration_seconds": meta.get("duration_seconds"),
            "width": meta.get("width"),
            "height": meta.get("height"),
            "fps": FPS,
            "seed": meta.get("seed"),
            "sha256": digest.hexdigest(),
            "prompt_sha256": hashlib.sha256(payload.get("prompt", "").encode()).hexdigest(),
            "reference_images": meta.get("reference_images", []),
            "reference_audios": meta.get("reference_audios", []),
            "reference_videos": meta.get("reference_videos", []),
            "wall_time_s": round(time.time() - started, 2),
        }
        receipt_path = output.with_suffix(".receipt.json")
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if payload:
            output.with_suffix(".prompt.txt").write_text(payload["prompt"], encoding="utf-8")
            output.with_suffix(".request.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        return ToolResult(
            success=True,
            data={
                "video_path": str(output),
                "receipt_path": str(receipt_path),
                "job_id": job_id,
                "frames": meta.get("frames"),
                "duration_seconds": meta.get("duration_seconds"),
                "width": meta.get("width"),
                "height": meta.get("height"),
                "fps": FPS,
                "seed": meta.get("seed"),
                "inference_time_s": status.get("inference_time_s"),
                "sha256": digest.hexdigest(),
                "provider": self.provider,
                "model": DEFAULT_MODEL,
            },
            artifacts=[str(output), str(receipt_path)],
            cost_usd=0.0,
            duration_seconds=round(time.time() - started, 2),
            seed=meta.get("seed"),
            model=DEFAULT_MODEL,
        )
