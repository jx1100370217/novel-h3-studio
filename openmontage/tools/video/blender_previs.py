"""Render a silent grayscale Blender blocking guide for a Ref2VA shot.

This is the official previs tool: it fixes body count, positions, poses,
screen direction and camera. It never supplies final appearance, materials or
identity; those come from the approved picture references.
"""
from __future__ import annotations

import hashlib
import json
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


class BlenderPrevis(BaseTool):
    name = "blender_previs"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "previs"
    provider = "local_blender"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = ["blender"]
    install_instructions = (
        "Install Blender 5.x and set NOVEL_H3_BLENDER_BIN, or keep it at "
        "~/.local/share/novel-h3-studio/blender-5.2.2/blender."
    )
    agent_skills: list[str] = []
    best_for = [
        "locking visible body count and blocking",
        "multi-person Ref2VA shots with duplicate-person risk",
        "camera height, screen direction and start-state composition",
    ]
    not_good_for = [
        "final character identity, costume or lighting",
        "shots that need photoreal production design",
    ]
    fallback_tools: list[str] = []

    capabilities = ["previs", "blocking_guide", "cast_count_lock"]

    input_schema = {
        "type": "object",
        "required": ["spec_path", "shot", "output_path"],
        "properties": {
            "spec_path": {"type": "string", "description": "Project previs spec JSON containing shots."},
            "shot": {"type": "string", "description": "Shot id, e.g. A13."},
            "output_path": {"type": "string", "description": "Destination PNG."},
            "blender_bin": {"type": "string", "description": "Optional Blender binary override."},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "shot": {"type": "string"}, "path": {"type": "string"},
            "sha256": {"type": "string"}, "size_bytes": {"type": "integer"},
            "blender": {"type": "string"},
        },
    }
    resume_support = ResumeSupport.FROM_CHECKPOINT
    idempotency_key_fields = ["spec_path", "shot"]
    side_effects = ["writes a grayscale PNG blocking guide"]
    resource_profile = ResourceProfile(cpu_cores=2, ram_mb=1024, vram_mb=0, disk_mb=50)
    retry_policy = RetryPolicy(max_retries=1, backoff_seconds=2)
    user_visible_verification = [
        "open the guide and count the gray bodies",
        "confirm the named cast are in the authored screen positions",
        "confirm no extra bodies or duplicates",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from novel_h3.previs import render_previs

        start = time.time()
        spec_path = Path(inputs["spec_path"]).expanduser()
        if not spec_path.is_absolute():
            spec_path = (_REPO_ROOT / spec_path).resolve()
        output_path = Path(inputs["output_path"]).expanduser()
        if not output_path.is_absolute():
            output_path = (_REPO_ROOT / output_path).resolve()
        try:
            data = render_previs(spec_path, str(inputs["shot"]), output_path,
                                 blender_bin=inputs.get("blender_bin"))
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=str(exc))
        data["sha256"] = hashlib.sha256(output_path.read_bytes()).hexdigest()
        data["wall_seconds"] = round(time.time() - start, 2)
        return ToolResult(success=True, data=data, artifacts=[str(output_path)],
                          duration_seconds=data["wall_seconds"])


if __name__ == "__main__":
    print(json.dumps(BlenderPrevis().get_info(), indent=2, ensure_ascii=False))
