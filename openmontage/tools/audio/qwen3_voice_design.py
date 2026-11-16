"""Local Qwen3 voice design for character audio references."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, ResourceProfile, ToolResult, ToolRuntime, ToolStability, ToolStatus, ToolTier


ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv-dialogue/bin/python"
SNAPSHOTS = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-TTS-12Hz-1.7B-VoiceDesign/snapshots"
MODEL = "Qwen3-TTS-12Hz-1.7B-VoiceDesign"


class Qwen3VoiceDesign(BaseTool):
    name = "qwen3_voice_design"
    version = "0.1.0"
    tier = ToolTier.VOICE
    capability = "voice_reference"
    provider = "qwen_local"
    stability = ToolStability.EXPERIMENTAL
    runtime = ToolRuntime.LOCAL_GPU
    agent_skills = ["text-to-speech"]
    capabilities = ["voice_reference", "offline_generation"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=12000, vram_mb=12000, network_required=False)
    input_schema = {
        "type": "object",
        "required": ["text", "instruct", "output_path"],
        "properties": {
            "text": {"type": "string", "minLength": 1},
            "instruct": {"type": "string", "minLength": 1},
            "output_path": {"type": "string"},
        },
    }
    side_effects = ["writes one new WAV audio reference to output_path"]
    user_visible_verification = ["Listen to the reference before using it for character dialogue"]

    def get_status(self) -> ToolStatus:
        if PYTHON.is_file() and any(SNAPSHOTS.glob("*/config.json")):
            return ToolStatus.AVAILABLE
        return ToolStatus.UNAVAILABLE

    def estimate_cost(self, inputs: dict[str, Any]) -> float:
        return 0.0

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        if self.get_status() != ToolStatus.AVAILABLE:
            return ToolResult(success=False, error="Local Qwen3 voice-design runtime or model snapshot is unavailable.")
        if not all(isinstance(inputs.get(k), str) and inputs[k].strip() for k in ("text", "instruct", "output_path")):
            return ToolResult(success=False, error="text, instruct and output_path are required.")
        output = Path(inputs["output_path"]).absolute()
        if output.exists() or output.is_symlink():
            return ToolResult(success=False, error=f"Output already exists: {output}")
        snapshots = sorted(p.parent for p in SNAPSHOTS.glob("*/config.json"))
        payload = {**inputs, "output_path": str(output), "model_path": str(snapshots[-1])}
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1"
        env["TRANSFORMERS_OFFLINE"] = "1"
        env["PYTHONPATH"] = str(ROOT / "openmontage") + os.pathsep + env.get("PYTHONPATH", "")
        try:
            proc = subprocess.run(
                [str(PYTHON), str(Path(__file__).resolve()), "--worker"],
                input=json.dumps(payload, ensure_ascii=False), text=True, capture_output=True,
                env=env, timeout=900, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ToolResult(success=False, error=f"Local voice generation failed: {exc}")
        if proc.returncode or not output.is_file():
            return ToolResult(success=False, error=f"Local voice generation failed: {proc.stderr[-1200:]}")
        return ToolResult(success=True, data={"output_path": str(output), "provider": self.provider, "model": MODEL},
                          artifacts=[str(output)], model=MODEL)


def _worker() -> None:
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    payload = json.load(sys.stdin)
    output = Path(payload["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    model = Qwen3TTSModel.from_pretrained(
        payload["model_path"], device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    wavs, sample_rate = model.generate_voice_design(
        text=payload["text"], instruct=payload["instruct"], language="Chinese", non_streaming_mode=True
    )
    fd, temporary = tempfile.mkstemp(prefix=".voice-", suffix=".wav", dir=output.parent)
    os.close(fd)
    try:
        sf.write(temporary, wavs[0], sample_rate)
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    _worker()
