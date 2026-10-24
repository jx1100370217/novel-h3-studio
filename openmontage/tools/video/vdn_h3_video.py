"""Render one continuous shot with MiniMax H3 + VDN-H3 Turbo on local ComfyUI.

The tool owns the ComfyUI graph so pipeline skills never hand-build nodes:
adapters (UNETLoader -> ApplyVDNH3 -> SigmaShift), reference images uploaded to
the ComfyUI input directory under content-hashed names, a single
MiniMaxH3ReferenceToVideo conditioning node, 8-step er_sde/beta sampling, and
native joint audio (CreateVideo + SaveVideo / SaveAudio).

Requires a running ComfyUI with the MiniMax H3 custom nodes and the VDN
checkpoint. Defaults target http://127.0.0.1:8191.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
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

DEFAULT_MODELS = {
    "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "video_vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
}
DEFAULT_VDN_CHECKPOINT = "vdn-minimax-h3-int8-convrot-comfyui"


def _api(base: str, route: str, payload: dict | None = None, timeout: float = 30.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        base.rstrip("/") + route,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise ValueError(f"ComfyUI {exc.code} on {route}: {exc.read().decode()[:1500]}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"ComfyUI unreachable at {base}: {exc}") from exc


def _upload_image(base: str, path: Path, name: str) -> str:
    boundary = "----vdn" + uuid.uuid4().hex
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(
        base.rstrip("/") + "/upload/image",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"ComfyUI upload failed ({exc.code}): {exc.read().decode()[:800]}") from exc
    subfolder = payload.get("subfolder") or ""
    return f"{subfolder}/{payload.get('name', name)}".lstrip("/")


def _download_output(base: str, record: dict, destination: Path) -> Path:
    query = urllib.parse.urlencode({
        "filename": record["filename"],
        "subfolder": record.get("subfolder", ""),
        "type": record.get("type", "output"),
    })
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{base.rstrip('/')}/view?{query}", timeout=600) as response:
        destination.write_bytes(response.read())
    return destination


def _history_output(history: dict, node_id: str, extensions: tuple[str, ...]) -> dict:
    outputs = history.get("outputs", {}).get(str(node_id), {})
    for values in outputs.values():
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, dict) and str(value.get("filename", "")).endswith(extensions):
                return value
    raise ValueError(f"Comfy history has no {extensions} output from node {node_id}")


def _build_graph(
    *,
    prompt: str,
    uploaded: list[tuple[str, str]],
    audio_uploaded: list[tuple[str, str]],
    width: int,
    height: int,
    frames: int,
    fps: float,
    seed: int,
    steps: int,
    shift_video: float,
    shift_audio: float,
    filename_prefix: str,
    models: dict[str, str],
    vdn_checkpoint: str,
) -> dict:
    nodes: dict[str, dict] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": models["ref2va"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": models["clip"], "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["video_vae"]}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": models["audio_vae"]}},
        "5": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["21", 0], "shift_video": shift_video, "shift_audio": shift_audio}},
        "6": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "clip": ["2", 0],
                "vae": ["3", 0],
                "audio_vae": ["4", 0],
                "prompt": prompt,
                "width": width,
                "height": height,
                "length": frames,
                "ref_image_size": "match",
            },
        },
        "9": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "10": {"class_type": "BasicGuider", "inputs": {"model": ["5", 0], "conditioning": ["6", 0]}},
        "11": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}},
        "12": {"class_type": "BasicScheduler", "inputs": {"model": ["5", 0], "scheduler": "beta", "steps": steps, "denoise": 1.0}},
        "13": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["9", 0],
                "guider": ["10", 0],
                "sampler": ["11", 0],
                "sigmas": ["12", 0],
                "latent_image": ["6", 1],
            },
        },
        "15": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["3", 0]}},
        "16": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["13", 0], "vae": ["4", 0]}},
        "17": {"class_type": "SaveAudio", "inputs": {"audio": ["16", 0], "filename_prefix": f"{filename_prefix}/native_audio"}},
        "18": {"class_type": "MiniMaxH3MotionContextTrim", "inputs": {"images": ["15", 0], "audio": ["16", 0], "trim_frames": 0, "fps": fps, "match_tail": True}},
        "19": {"class_type": "CreateVideo", "inputs": {"images": ["18", 0], "audio": ["18", 1], "fps": fps}},
        "20": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["19", 0],
                "filename_prefix": f"{filename_prefix}/native_video",
                "format": "mp4",
                "format.codec": "h264",
            },
        },
        "21": {
            "class_type": "ApplyVDNH3",
            "inputs": {
                "model": ["1", 0],
                "vdn_checkpoint": vdn_checkpoint,
                "apply_turbo_adapter": True,
                "strength": 1.0,
                "lora_mode": "merge",
                "branch_weights": "auto",
                "retain_buffers": "auto",
                "verbose": True,
                "attention_backend": "grouped",
            },
        },
    }
    for index, (staged_name, _asset_id) in enumerate(uploaded):
        node_id = str(100 + index)
        nodes[node_id] = {"class_type": "LoadImage", "inputs": {"image": staged_name}}
        nodes["6"]["inputs"][f"ref_images.ref_image_{index}"] = [node_id, 0]
    for index, (staged_name, _asset_id) in enumerate(audio_uploaded):
        node_id = str(200 + index)
        nodes[node_id] = {"class_type": "LoadAudio", "inputs": {"audio": staged_name}}
        nodes["6"]["inputs"][f"ref_audios.ref_audio_{index}"] = [node_id, 0]
    return nodes


class VdnH3VideoTool(BaseTool):
    name = "vdn_h3_video"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.SEEDED
    runtime = ToolRuntime.LOCAL_GPU

    capability = "video_generation"
    provider = "local_comfyui"
    capabilities = ["video_generation", "native_audio", "reference_to_video", "image_to_video"]

    input_schema = {
        "type": "object",
        "required": ["prompt", "reference_images", "output_path"],
        "properties": {
            "prompt": {"type": "string", "description": "Full MiniMax H3 shot prompt"},
            "reference_images": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "asset_id": {"type": "string"},
                        "kind": {"type": "string", "enum": ["character", "scene", "prop"]},
                    },
                },
                "description": "Ordered references; index maps to <Picture N> / <Subject N>",
            },
            "output_path": {"type": "string", "description": "Destination .mp4 path"},
            "audio_output_path": {"type": "string", "description": "Optional .flac destination"},
            "audio_references": {
                "type": "array", "maxItems": 3,
                "items": {"type": "object", "required": ["path"], "properties": {
                    "path": {"type": "string"}, "asset_id": {"type": "string"}}},
                "description": "Optional standalone audio references (max 3), in the same order as <Audio 1..N> in the prompt.",
            },
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 576},
            "duration_seconds": {"type": "number", "default": 5.166666},
            "fps": {"type": "number", "default": 24},
            "frames": {"type": "integer", "description": "Overrides duration_seconds when set"},
            "seed": {"type": "integer"},
            "steps": {"type": "integer", "default": 8},
            "shift_video": {"type": "number", "default": 12.0},
            "shift_audio": {"type": "number", "default": 3.0},
            "comfy_url": {"type": "string", "default": "http://127.0.0.1:8191"},
            "filename_prefix": {"type": "string", "default": "openmontage/vdn_h3"},
            "models": {"type": "object", "description": "Override model filenames"},
            "vdn_checkpoint": {"type": "string", "default": DEFAULT_VDN_CHECKPOINT},
            "timeout_seconds": {"type": "integer", "default": 1800},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "output_path": {"type": "string"},
            "audio_output_path": {"type": "string"},
            "prompt_id": {"type": "string"},
            "frames": {"type": "integer"},
            "fps": {"type": "number"},
            "duration_seconds": {"type": "number"},
            "seed": {"type": "integer"},
            "sha256": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=4, ram_mb=4096, vram_mb=24000, disk_mb=4000, network_required=False
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timed out", "did not complete"])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["prompt", "reference_images", "audio_references", "duration_seconds", "seed", "width", "height"]

    side_effects = ["writes an mp4 (and optional flac) to disk", "occupies the local GPU"]
    best_for = [
        "Photorealistic period-drama shots with native ambience audio",
        "Identity-preserving coverage across many shots",
        "Long single-take actions (5-30 seconds)",
    ]
    not_good_for = ["Text rendering inside the frame", "Anything needing two H3 jobs at once"]
    user_visible_verification = [
        "Play the clip: identity, cast count, action completion, and audio",
    ]

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        duration = float(inputs.get("duration_seconds", 5.166666))
        return 90.0 + duration * 40.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        output_path = Path(inputs["output_path"]).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path = output_path.resolve()

        fps = float(inputs.get("fps", 24))
        frames = int(inputs.get("frames") or round(float(inputs.get("duration_seconds", 5.166666)) * fps))
        if frames < 9:
            return ToolResult(success=False, error=f"Requested duration produces too few frames: {frames}")

        seed = inputs.get("seed")
        if seed is None:
            seed = int(time.time()) % 2_000_000_000

        references = inputs.get("reference_images") or []
        audio_references = inputs.get("audio_references") or []
        if len(audio_references) > 3:
            return ToolResult(success=False, error="audio_references supports at most 3 files")
        if not references:
            return ToolResult(success=False, error="reference_images must contain at least one image")
        for ref in references:
            if not Path(ref["path"]).expanduser().is_file():
                return ToolResult(success=False, error=f"Reference image not found: {ref.get('path')}")
        for ref in audio_references:
            if not Path(ref["path"]).expanduser().is_file():
                return ToolResult(success=False, error=f"Audio reference not found: {ref.get('path')}")

        base = str(inputs.get("comfy_url") or "http://127.0.0.1:8191").rstrip("/")
        prefix = str(inputs.get("filename_prefix") or f"openmontage/vdn_h3/{output_path.stem}")
        timeout = float(inputs.get("timeout_seconds", 1800))

        try:
            _api(base, "/system_stats", timeout=10)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        uploaded: list[tuple[str, str]] = []
        for ref in references:
            path = Path(ref["path"]).expanduser().resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            staged = _upload_image(base, path, f"{digest}{path.suffix.lower()}")
            uploaded.append((staged, str(ref.get("asset_id") or path.stem)))
        audio_uploaded: list[tuple[str, str]] = []
        for ref in audio_references:
            path = Path(ref["path"]).expanduser().resolve()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            staged = _upload_image(base, path, f"{digest}{path.suffix.lower()}")
            audio_uploaded.append((staged, str(ref.get("asset_id") or path.stem)))

        models = dict(DEFAULT_MODELS)
        models.update(inputs.get("models") or {})
        nodes = _build_graph(
            prompt=inputs["prompt"],
            uploaded=uploaded,
            audio_uploaded=audio_uploaded,
            width=int(inputs.get("width", 1024)),
            height=int(inputs.get("height", 576)),
            frames=frames,
            fps=fps,
            seed=int(seed),
            steps=int(inputs.get("steps", 8)),
            shift_video=float(inputs.get("shift_video", 12.0)),
            shift_audio=float(inputs.get("shift_audio", 3.0)),
            filename_prefix=prefix,
            models=models,
            vdn_checkpoint=str(inputs.get("vdn_checkpoint") or DEFAULT_VDN_CHECKPOINT),
        )

        try:
            prompt_id = self._submit_and_wait(base, nodes, timeout)
            history = _api(base, f"/history/{prompt_id}", timeout=60).get(prompt_id) or {}
            if history.get("status", {}).get("status_str") not in (None, "success"):
                messages = json.dumps(history.get("status", {}), ensure_ascii=False)[:1500]
                return ToolResult(success=False, error=f"H3 execution failed: {messages}", duration_seconds=round(time.time() - start, 2))
            video_record = _history_output(history, "20", (".mp4",))
            _download_output(base, video_record, output_path)
            audio_path = None
            if inputs.get("audio_output_path"):
                audio_path = Path(inputs["audio_output_path"]).expanduser().resolve()
                try:
                    audio_record = _history_output(history, "17", (".flac", ".wav", ".mp3"))
                    _download_output(base, audio_record, audio_path)
                except ValueError:
                    audio_path = None
        except (ValueError, TimeoutError) as exc:
            return ToolResult(success=False, error=str(exc), duration_seconds=round(time.time() - start, 2))

        sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
        data = {
            "output_path": str(output_path),
            "prompt_id": prompt_id,
            "frames": frames,
            "fps": fps,
            "duration_seconds": round(frames / fps, 6),
            "seed": int(seed),
            "sha256": sha,
            "references": [asset for _staged, asset in uploaded],
            "audio_references": [asset for _staged, asset in audio_uploaded],
        }
        if audio_path:
            data["audio_output_path"] = str(audio_path)
        return ToolResult(
            success=True,
            data=data,
            artifacts=[str(output_path)] + ([str(audio_path)] if audio_path else []),
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            seed=int(seed),
            model="minimax_h3_ref2va + vdn_h3_turbo",
        )

    def _submit_and_wait(self, base: str, nodes: dict, timeout: float) -> str:
        client_id = uuid.uuid4().hex
        deadline = time.monotonic() + min(timeout, 300)
        while time.monotonic() < deadline:
            queue = _api(base, "/queue")
            if not queue.get("queue_running") and not queue.get("queue_pending"):
                break
            time.sleep(5)
        else:
            raise TimeoutError("ComfyUI queue stayed busy")

        response = _api(base, "/prompt", {"prompt": nodes, "client_id": client_id})
        prompt_id = response.get("prompt_id")
        if not prompt_id:
            raise ValueError(f"ComfyUI rejected the prompt: {response}")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            history = _api(base, f"/history/{prompt_id}", timeout=60).get(prompt_id)
            if history:
                return prompt_id
            time.sleep(5)
        raise TimeoutError(f"H3 job {prompt_id} did not complete within {timeout:.0f}s")


def register(registry) -> None:
    registry.register(VdnH3VideoTool())
