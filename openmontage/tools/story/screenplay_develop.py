"""Develop a skeleton story into a production-ready screenplay artifact.

The agent authors the screenplay (acts, scenes, beats, dialogue, motifs,
narration); this tool validates the structure and writes both the canonical
JSON and a human-readable Markdown screenplay. It is deliberately local and
deterministic: no model call, no hidden rewriting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)


class ScreenplayDevelop(BaseTool):
    name = "screenplay_develop"
    version = "0.1.0"
    tier = ToolTier.CORE
    capability = "screenplay"
    provider = "openmontage"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = []
    install_instructions = ""
    agent_skills = ["screenplay-development"]

    capabilities = ["validate_screenplay", "render_screenplay_markdown"]
    supports = {"local_offline": True, "free": True, "no_model_call": True}

    best_for = [
        "expanding a short source story into a complete cinematic screenplay",
        "locking acts, scenes, beats, dialogue, motifs and sparse narration before storyboarding",
        "producing a screenplay that the scene plan can be derived from, instead of improvising shots",
    ]
    not_good_for = [
        "writing the creative text itself (the agent authors it)",
        "replacing the script artifact consumed by the pipeline",
    ]

    input_schema = {
        "type": "object",
        "required": ["screenplay", "output_dir"],
        "properties": {
            "screenplay": {
                "type": "object",
                "description": "Complete screenplay object; validated against schemas/artifacts/screenplay.schema.json.",
            },
            "output_dir": {
                "type": "string",
                "description": "Project artifacts directory (screenplay.json + screenplay.md).",
            },
            "write_markdown": {"type": "boolean", "default": True},
        },
    }

    output_schema = {
        "type": "object",
        "properties": {
            "screenplay_path": {"type": "string"},
            "markdown_path": {"type": "string"},
            "acts": {"type": "integer"},
            "scenes": {"type": "integer"},
            "dialogue_lines": {"type": "integer"},
        },
    }

    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=10)
    side_effects = ["writes screenplay.json and screenplay.md"]
    user_visible_verification = [
        "Read the Markdown once: does every scene turn, and does the ending land?",
        "Check that every named character has a want, an obstacle and an arc.",
    ]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        screenplay = inputs.get("screenplay")
        output_dir = inputs.get("output_dir")
        if not isinstance(screenplay, dict):
            return ToolResult(success=False, error="screenplay must be an object")
        if not output_dir:
            return ToolResult(success=False, error="output_dir is required")

        try:
            from schemas.artifacts import validate_artifact
            validate_artifact("screenplay", screenplay)
        except Exception as exc:
            return ToolResult(success=False, error=f"screenplay schema validation failed: {exc}")

        out = Path(output_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)
        json_path = out / "screenplay.json"
        json_path.write_text(json.dumps(screenplay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        markdown_path = None
        if inputs.get("write_markdown", True):
            markdown_path = out / "screenplay.md"
            markdown_path.write_text(self._render(screenplay), encoding="utf-8")

        scenes = sum(len(act.get("scenes", [])) for act in screenplay["acts"])
        dialogue = sum(
            len(scene.get("dialogue", []))
            for act in screenplay["acts"]
            for scene in act.get("scenes", [])
        )
        return ToolResult(
            success=True,
            data={
                "screenplay_path": str(json_path),
                "markdown_path": str(markdown_path) if markdown_path else None,
                "acts": len(screenplay["acts"]),
                "scenes": scenes,
                "dialogue_lines": dialogue,
            },
            artifacts=[str(json_path)] + ([str(markdown_path)] if markdown_path else []),
            cost_usd=0.0,
        )

    @staticmethod
    def _render(s: dict[str, Any]) -> str:
        lines = [f"# {s['title']}", "", f"> {s['logline']}", "", f"**主题：** {s['theme']}", ""]
        if s.get("tone"):
            lines += [f"**调性：** {s['tone']}", ""]
        lines += [f"**预计时长：** {s['runtime_seconds']:.0f} 秒", ""]

        lines += ["## 人物", ""]
        for c in s["characters"]:
            lines.append(
                f"- **{c['name']}**（{c['role']}）：想要 {c['want']}；阻碍 {c['obstacle']}；弧线 {c['arc']}。"
            )
        lines.append("")

        if s.get("motifs"):
            lines += ["## 视觉母题", ""]
            for m in s["motifs"]:
                appear = "、".join(m.get("appearances", [])) or "贯穿"
                lines.append(f"- **{m['name']}**：{m['meaning']}（{appear}）")
            lines.append("")

        lines += ["## 分幕", ""]
        for act in s["acts"]:
            lines += [f"### {act['id']} · {act['title']}", "", f"*{act['purpose']}*", ""]
            for scene in act["scenes"]:
                lines += [
                    f"#### {scene['id']} · {scene['slug']}",
                    "",
                    f"**{scene['time']} / {scene['location']}**",
                    "",
                    scene["action"],
                    "",
                ]
                if scene.get("beats"):
                    lines.append("**节拍：**")
                    lines += [f"- {b}" for b in scene["beats"]]
                    lines.append("")
                if scene.get("dialogue"):
                    lines.append("**对白：**")
                    for d in scene["dialogue"]:
                        sub = f"（{d['subtext']}）" if d.get("subtext") else ""
                        lines.append(f"- **{d['speaker']}**：{d['line']}{sub}")
                    lines.append("")
                if scene.get("transition"):
                    lines += [f"*转场：{scene['transition']}*", ""]

        if s.get("narration"):
            lines += ["## 旁白", ""]
            for n in s["narration"]:
                purpose = f" —— {n['purpose']}" if n.get("purpose") else ""
                lines.append(f"- **{n['time']}**：{n['text']}{purpose}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def register(registry) -> None:
    registry.register(ScreenplayDevelop())
