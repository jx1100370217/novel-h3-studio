"""Cut-boundary transition audit tool (global)."""
from __future__ import annotations

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


class TransitionAudit(BaseTool):
    name = "transition_audit"
    version = "1.0.0"
    tier = ToolTier.CORE
    capability = "analysis"
    provider = "local_ffmpeg"
    stability = ToolStability.PRODUCTION
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies: list[str] = ["ffmpeg"]
    install_instructions = "Install ffmpeg."
    agent_skills: list[str] = []
    best_for = [
        "checking every cut's last/first frame",
        "finding jump cuts, missing action beats and continuity errors",
        "producing a review sheet before compose approval",
    ]
    not_good_for = ["judging performance, sound or subjective pacing"]
    fallback_tools: list[str] = []
    capabilities = ["transition_audit", "continuity_review"]

    input_schema = {
        "type": "object",
        "required": ["video_path", "script_path", "shots_dir", "output_dir"],
        "properties": {
            "video_path": {"type": "string"},
            "script_path": {"type": "string"},
            "shots_dir": {"type": "string"},
            "output_dir": {"type": "string"},
            "verdicts_path": {"type": "string", "description": "Optional per-cut verdict JSON."},
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "report_path": {"type": "string"}, "sheet_path": {"type": "string"},
            "cut_count": {"type": "integer"}, "counts": {"type": "object"},
            "needs_fix_cuts": {"type": "array", "items": {"type": "integer"}},
        },
    }
    resume_support = ResumeSupport.FROM_CHECKPOINT
    idempotency_key_fields = ["video_path", "script_path"]
    side_effects = ["writes boundary frames, a contact sheet and a JSON/Markdown report"]
    resource_profile = ResourceProfile(cpu_cores=1, ram_mb=512, vram_mb=0, disk_mb=300)
    retry_policy = RetryPolicy(max_retries=0)
    user_visible_verification = ["open transition_sheet.jpg", "read transition_report.md", "confirm every needs_fix cut has a v5 handoff"]

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        from novel_h3.transition_audit import build_report, load_script_order

        start = time.time()
        def resolve(value: str) -> Path:
            path = Path(value).expanduser()
            return path if path.is_absolute() else (_REPO_ROOT / path).resolve()
        video = resolve(inputs['video_path'])
        script = json.loads(resolve(inputs['script_path']).read_text(encoding='utf-8'))
        order = load_script_order(script)
        shots_dir = resolve(inputs['shots_dir'])
        durations = {sid: json.loads((shots_dir / f'{sid}.json').read_text(encoding='utf-8'))['duration_seconds']
                     for sid in order}
        verdicts = {}
        if inputs.get('verdicts_path'):
            verdicts = json.loads(resolve(inputs['verdicts_path']).read_text(encoding='utf-8')).get('verdicts', {})
        out = resolve(inputs['output_dir'])
        try:
            report = build_report(video, order, durations, out, verdicts)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(success=False, error=str(exc))
        data = {
            'report_path': str(out / 'transition_report.json'),
            'sheet_path': report.get('sheet', ''),
            'cut_count': report['cut_count'], 'counts': report['counts'],
            'needs_fix_cuts': report['needs_fix_cuts'],
            'wall_seconds': round(time.time() - start, 2),
        }
        return ToolResult(success=True, data=data, artifacts=[data['report_path'], data['sheet_path']],
                          duration_seconds=data['wall_seconds'])


if __name__ == "__main__":
    print(json.dumps(TransitionAudit().get_info(), indent=2, ensure_ascii=False))
