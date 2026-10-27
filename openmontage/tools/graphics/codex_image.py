"""Generate or edit raster images through the operator's Codex subscription.

This tool drives `codex exec` (ChatGPT/Codex plan) and the built-in `image_gen`
tool. It does not need OPENAI_API_KEY and does not use the OpenAI API directly.
The subprocess is instructed to generate exactly one image and copy the PNG to
the requested output path; the tool verifies the file exists before returning.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
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


class CodexImageTool(BaseTool):
    name = "codex_image"
    version = "0.1.0"
    tier = ToolTier.GENERATE
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.STOCHASTIC
    runtime = ToolRuntime.API
    dependencies = ["cmd:codex"]
    install_instructions = (
        "Install the Codex CLI and sign in with a ChatGPT/Codex plan: "
        "https://github.com/openai/codex"
    )

    capability = "image_generation"
    provider = "codex_subscription"
    capabilities = ["image_generation", "image_edit", "subscription_billing"]

    input_schema = {
        "type": "object",
        "required": ["prompt", "output_path"],
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Full image description or edit instruction.",
            },
            "output_path": {
                "type": "string",
                "description": "Absolute or project-relative path the PNG must land at.",
            },
            "reference_paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Local reference images. They are attached with codex exec -i "
                    "and labelled as references (not edit targets) in the prompt."
                ),
            },
            "timeout_seconds": {"type": "integer", "default": 900},
            "codex_bin": {"type": "string", "default": "codex"},
            "extra_instructions": {"type": "string"},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "output_path": {"type": "string"},
            "bytes": {"type": "integer"},
            "sha256": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=200, network_required=True
    )
    retry_policy = RetryPolicy(max_retries=1, retryable_errors=["timeout", "exit code"])
    resume_support = ResumeSupport.FROM_START
    idempotency_key_fields = ["prompt", "reference_paths"]

    side_effects = ["writes an image file to output_path", "consumes Codex plan credits"]
    best_for = [
        "Character and location references for novel-to-film pipelines",
        "Posters and title art on a ChatGPT/Codex subscription",
        "Image edits that keep a previously approved identity",
    ]
    not_good_for = ["Deterministic asset builds", "Headless CI without an interactive Codex login"]
    user_visible_verification = ["Open the image and confirm subject, style and text"]

    def estimate_runtime(self, inputs: dict[str, Any]) -> float:
        return float(inputs.get("timeout_seconds", 900)) * 0.5

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        start = time.time()
        prompt = inputs.get("prompt")
        if not prompt:
            return ToolResult(success=False, error="prompt is required")
        output_path_value = inputs.get("output_path")
        if not output_path_value:
            return ToolResult(success=False, error="output_path is required")
        output_path = Path(output_path_value).expanduser()
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        references = [
            str(Path(p).expanduser().resolve())
            for p in inputs.get("reference_paths", [])
        ]
        for ref in references:
            if not Path(ref).is_file():
                return ToolResult(success=False, error=f"Reference image not found: {ref}")

        codex_bin = inputs.get("codex_bin") or shutil.which("codex") or "codex"
        timeout = int(inputs.get("timeout_seconds", 900))

        instruction = self._build_instruction(
            prompt, output_path, bool(references), inputs.get("extra_instructions")
        )

        workdir = output_path.parent if os.access(output_path.parent, os.W_OK) else Path("/tmp")
        cmd = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "-s",
            "workspace-write",
            "-C",
            str(workdir),
            "--add-dir",
            str(workdir),
        ]
        for ref in references:
            cmd += ["-i", ref]

        # The prompt goes through stdin: `-i` is variadic and would otherwise
        # swallow a trailing positional argument as another image path.
        try:
            proc = subprocess.run(
                cmd,
                input=instruction,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"codex exec timed out after {timeout}s",
                duration_seconds=round(time.time() - start, 2),
            )

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[-2000:]
            return ToolResult(
                success=False,
                error=f"codex exec failed (exit {proc.returncode}): {detail}",
                duration_seconds=round(time.time() - start, 2),
            )

        if not output_path.is_file() or output_path.stat().st_size < 1024:
            return ToolResult(
                success=False,
                error=(
                    f"codex exec finished but no image was saved at {output_path}. "
                    f"Last output: {(proc.stdout or '').strip()[-800:]}"
                ),
                duration_seconds=round(time.time() - start, 2),
            )

        try:
            data = self._verify_png(output_path)
        except ValueError as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                duration_seconds=round(time.time() - start, 2),
            )
        return ToolResult(
            success=True,
            data={
                "output_path": str(output_path),
                "bytes": output_path.stat().st_size,
                "sha256": data,
                "provider": "codex_subscription",
                "model": "gpt-image-2.5",
                "reference_count": len(references),
            },
            artifacts=[str(output_path)],
            cost_usd=0.0,
            duration_seconds=round(time.time() - start, 2),
            model="gpt-image-2.5",
        )

    def _build_instruction(
        self,
        prompt: str,
        output_path: Path,
        has_references: bool,
        extra: str | None,
    ) -> str:
        lines = [
            "Use the built-in image_gen tool to produce exactly one image.",
            f"Image prompt: {prompt}",
        ]
        if has_references:
            lines.append(
                "The attached images are style/identity references, not edit targets. "
                "Preserve the identity, age, hair and costume of any person in them."
            )
        lines += [
            f"After generation, copy the selected PNG to this exact path: {output_path}",
            "Write the PNG bytes unchanged (no conversion, no renaming).",
            "Do not modify any other file. Do not create extra images.",
            "Reply with only the absolute path of the saved file.",
        ]
        if extra:
            lines.append(str(extra))
        return "\n".join(lines)

    def _verify_png(self, path: Path) -> str:
        with open(path, "rb") as f:
            header = f.read(8)
            sha = hashlib.sha256(header)
            for chunk in iter(lambda: f.read(1 << 20), b""):
                sha.update(chunk)
        if header[:4] != b"\x89PNG":
            raise ValueError(f"Generated file is not a PNG: {path}")
        return sha.hexdigest()


def register(registry) -> None:
    registry.register(CodexImageTool())
