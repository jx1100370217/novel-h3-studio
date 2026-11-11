"""Platform cover generator for the publish stage.

Cinematic projects already produce an approved poster image (the hero frame
with title treatment). Social platforms need additional aspect ratios that
cannot be derived on the upload screen without hand-cropping:

- Douyin: horizontal 4:3 + vertical 3:4 (vertical must be larger than 600x800)
- Generic: horizontal 16:9 + vertical 9:16

This tool crops the approved poster (or extracts a poster frame from the final
video) and writes deterministic, dimension-checked cover files plus a manifest.
It never invents a new design; it only reframes the approved artwork.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.base_tool import (
    BaseTool,
    Determinism,
    ExecutionMode,
    ResourceProfile,
    ToolCommandError,
    ToolResult,
    ToolRuntime,
    ToolStability,
    ToolTier,
)

PLATFORM_SPECS: dict[str, dict[str, tuple[int, int]]] = {
    "douyin": {"horizontal": (1440, 1080), "vertical": (1080, 1440)},
    "generic": {"horizontal": (1920, 1080), "vertical": (1080, 1920)},
}

_SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


class PublishCovers(BaseTool):
    name = "publish_covers"
    version = "0.1.0"
    tier = ToolTier.PUBLISH
    capability = "publish"
    provider = "ffmpeg"
    stability = ToolStability.BETA
    execution_mode = ExecutionMode.SYNC
    determinism = Determinism.DETERMINISTIC
    runtime = ToolRuntime.LOCAL

    dependencies = ["cmd:ffmpeg", "cmd:ffprobe"]
    install_instructions = "Install FFmpeg (includes ffprobe): https://ffmpeg.org/download.html"

    agent_skills = []

    capabilities = ["generate_publish_covers", "reframe_poster"]
    supports = {
        "local_offline": True,
        "free": True,
        "uploads": False,
    }
    best_for = [
        "turning one approved poster into platform-ready horizontal and vertical covers",
        "Douyin 4:3 and 3:4 covers that satisfy the >600x800 vertical minimum",
        "keeping poster artwork and title treatment consistent across aspect ratios",
    ]
    not_good_for = [
        "designing a new cover from scratch (author the poster first)",
        "text-aware reframing that must keep a specific title inside a safe area",
    ]

    input_schema = {
        "type": "object",
        "anyOf": [
            {"required": ["poster_path"]},
            {"required": ["video_path"]},
        ],
        "properties": {
            "poster_path": {
                "type": "string",
                "description": "Approved poster image. Preferred source for covers.",
            },
            "video_path": {
                "type": "string",
                "description": "Final video; used to extract a poster frame when poster_path is absent.",
            },
            "poster_time": {
                "type": "number",
                "description": "Seconds to seek when extracting a poster frame from video_path. Default 0.",
                "default": 0,
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for covers and manifest. Defaults to the poster/video parent directory.",
            },
            "base_name": {
                "type": "string",
                "description": "Output file prefix. Defaults to the poster stem without _poster/_thumbnail, or the video stem.",
            },
            "platform": {
                "type": "string",
                "enum": ["douyin", "generic"],
                "description": "Cover size preset. Douyin = 4:3 + 3:4; generic = 16:9 + 9:16.",
                "default": "douyin",
            },
            "horizontal_size": {
                "type": "string",
                "description": "Override horizontal size as WIDTHxHEIGHT (e.g. 1440x1080).",
            },
            "vertical_size": {
                "type": "string",
                "description": "Override vertical size as WIDTHxHEIGHT (e.g. 1080x1440).",
            },
            "horizontal_focus": {
                "type": "string",
                "enum": ["left", "center", "right"],
                "description": "Horizontal crop anchor. Use left when the title is left-aligned.",
                "default": "center",
            },
            "vertical_focus": {
                "type": "string",
                "enum": ["top", "center", "bottom"],
                "description": "Vertical crop anchor when the source is taller than the target.",
                "default": "center",
            },
        },
    }
    output_schema = {
        "type": "object",
        "properties": {
            "poster": {"type": "string"},
            "covers": {"type": "array", "items": {"type": "object"}},
            "manifest_path": {"type": "string"},
            "files_written": {"type": "array", "items": {"type": "string"}},
        },
    }

    resource_profile = ResourceProfile(
        cpu_cores=1, ram_mb=128, vram_mb=0, disk_mb=100, network_required=False
    )
    side_effects = ["writes horizontal/vertical cover images and a covers manifest to disk"]
    user_visible_verification = [
        "Open both cover images and confirm the title/cast is not cropped out",
        "Check the manifest dimensions: Douyin vertical must be larger than 600x800",
    ]

    # ---- Helpers ----

    def _probe_image_size(self, path: Path) -> tuple[int, int]:
        result = self.run_command(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(path),
            ]
        )
        data = json.loads(result.stdout)
        stream = (data.get("streams") or [{}])[0]
        width, height = stream.get("width"), stream.get("height")
        if not width or not height:
            raise ValueError(f"could not read image dimensions: {path}")
        return int(width), int(height)

    @staticmethod
    def _parse_size(value: str) -> tuple[int, int]:
        match = _SIZE_RE.match(value.strip())
        if not match:
            raise ValueError(f"size must be WIDTHxHEIGHT, got {value!r}")
        width, height = int(match.group(1)), int(match.group(2))
        if width < 2 or height < 2:
            raise ValueError(f"size must be positive, got {value!r}")
        return width, height

    @staticmethod
    def _crop_box(
        source: tuple[int, int],
        target: tuple[int, int],
        horizontal_focus: str,
        vertical_focus: str,
    ) -> tuple[int, int, int, int]:
        src_w, src_h = source
        target_w, target_h = target
        source_ar = src_w / src_h
        target_ar = target_w / target_h

        if source_ar > target_ar:
            crop_h = src_h
            crop_w = min(src_w, int(round(src_h * target_ar)))
            max_x = src_w - crop_w
            x = 0 if horizontal_focus == "left" else max_x if horizontal_focus == "right" else max_x // 2
            y = 0
        else:
            crop_w = src_w
            crop_h = min(src_h, int(round(src_w / target_ar)))
            max_y = src_h - crop_h
            y = 0 if vertical_focus == "top" else max_y if vertical_focus == "bottom" else max_y // 2
            x = 0

        # JPEG chroma subsampling prefers even dimensions.
        crop_w = max(2, crop_w - crop_w % 2)
        crop_h = max(2, crop_h - crop_h % 2)
        x = min(x, src_w - crop_w)
        y = min(y, src_h - crop_h)
        return crop_w, crop_h, x, y

    @staticmethod
    def _default_base_name(source: Path) -> str:
        stem = source.stem
        for suffix in ("_poster", "-poster", "_thumbnail", "-thumbnail"):
            if stem.endswith(suffix):
                return stem[: -len(suffix)]
        return stem

    def _write_cover(
        self,
        source: Path,
        target: tuple[int, int],
        output: Path,
        *,
        horizontal_focus: str,
        vertical_focus: str,
    ) -> dict[str, Any]:
        src_w, src_h = self._probe_image_size(source)
        target_w, target_h = target
        crop_w, crop_h, x, y = self._crop_box(
            (src_w, src_h), target, horizontal_focus, vertical_focus
        )
        scale = f"crop={crop_w}:{crop_h}:{x}:{y},scale={target_w}:{target_h}:flags=lanczos"
        if target_w > crop_w or target_h > crop_h:
            scale += ",unsharp=5:5:0.4"
        self.run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-vf",
                scale,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(output),
            ]
        )
        actual = self._probe_image_size(output)
        if actual != target:
            raise ValueError(
                f"cover dimension mismatch for {output.name}: expected {target}, got {actual}"
            )
        return {
            "name": output.stem,
            "path": str(output),
            "width": actual[0],
            "height": actual[1],
            "crop": {"width": crop_w, "height": crop_h, "x": x, "y": y},
        }

    # ---- Execution ----

    def execute(self, inputs: dict[str, Any]) -> ToolResult:
        poster_in = inputs.get("poster_path")
        video_in = inputs.get("video_path")
        if not poster_in and not video_in:
            return ToolResult(
                success=False,
                error="provide poster_path (preferred) or video_path to generate covers",
            )

        platform = inputs.get("platform", "douyin")
        if platform not in PLATFORM_SPECS:
            return ToolResult(success=False, error=f"unsupported platform: {platform}")

        spec = PLATFORM_SPECS[platform]
        default_horizontal = spec["horizontal"]
        default_vertical = spec["vertical"]
        try:
            horizontal_size = (
                self._parse_size(inputs["horizontal_size"])
                if inputs.get("horizontal_size")
                else default_horizontal
            )
            vertical_size = (
                self._parse_size(inputs["vertical_size"])
                if inputs.get("vertical_size")
                else default_vertical
            )
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc))

        expected_aspects = (
            (4 / 3, 3 / 4) if platform == "douyin" else (16 / 9, 9 / 16)
        )
        actual_aspects = (
            horizontal_size[0] / horizontal_size[1],
            vertical_size[0] / vertical_size[1],
        )
        for label, actual, expected in zip(
            ("horizontal_size", "vertical_size"), actual_aspects, expected_aspects
        ):
            if abs(actual - expected) > 0.01:
                return ToolResult(
                    success=False,
                    error=f"{label} must keep the {platform} aspect ratio; got {actual:.3f}",
                )

        if platform == "douyin" and (
            vertical_size[0] <= 600 or vertical_size[1] <= 800
        ):
            return ToolResult(
                success=False,
                error=(
                    "Douyin vertical cover must be larger than 600x800; "
                    f"got {vertical_size[0]}x{vertical_size[1]}"
                ),
            )

        horizontal_focus = inputs.get("horizontal_focus", "center")
        vertical_focus = inputs.get("vertical_focus", "center")
        if horizontal_focus not in {"left", "center", "right"}:
            return ToolResult(success=False, error=f"invalid horizontal_focus: {horizontal_focus}")
        if vertical_focus not in {"top", "center", "bottom"}:
            return ToolResult(success=False, error=f"invalid vertical_focus: {vertical_focus}")

        poster_path = Path(poster_in).expanduser() if poster_in else None
        video_path = Path(video_in).expanduser() if video_in else None
        if poster_path and not poster_path.is_file():
            return ToolResult(success=False, error=f"poster_path not found: {poster_path}")
        if not poster_path and (not video_path or not video_path.is_file()):
            return ToolResult(success=False, error=f"video_path not found: {video_path}")

        output_dir = (
            Path(inputs["output_dir"]).expanduser()
            if inputs.get("output_dir")
            else (poster_path.parent if poster_path else video_path.parent)
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        base_name = inputs.get("base_name") or self._default_base_name(
            poster_path or video_path  # type: ignore[arg-type]
        )
        files_written: list[str] = []
        poster_out: Path | None = None

        if poster_path is None:
            poster_out = output_dir / f"{base_name}_poster.jpg"
            self.run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    str(float(inputs.get("poster_time") or 0)),
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(poster_out),
                ]
            )
            poster_path = poster_out
            files_written.append(str(poster_out))

        cover_suffixes = (
            ("_cover_4x3.jpg", "_cover_3x4.jpg")
            if platform == "douyin"
            else ("_cover_16x9.jpg", "_cover_9x16.jpg")
        )
        targets = [
            ("horizontal", horizontal_size, f"{base_name}{cover_suffixes[0]}"),
            ("vertical", vertical_size, f"{base_name}{cover_suffixes[1]}"),
        ]
        covers: list[dict[str, Any]] = []
        try:
            for name, size, filename in targets:
                out_path = output_dir / filename
                cover = self._write_cover(
                    poster_path,
                    size,
                    out_path,
                    horizontal_focus=horizontal_focus,
                    vertical_focus=vertical_focus,
                )
                cover["name"] = name
                cover["aspect"] = f"{size[0]}:{size[1]}"
                covers.append(cover)
                files_written.append(str(out_path))
        except (ValueError, OSError, ToolCommandError) as exc:
            return ToolResult(success=False, error=str(exc))

        manifest = {
            "version": "1.0",
            "platform": platform,
            "source": {
                "path": str(poster_path),
                "width": self._probe_image_size(poster_path)[0],
                "height": self._probe_image_size(poster_path)[1],
            },
            "focus": {"horizontal": horizontal_focus, "vertical": vertical_focus},
            "covers": covers,
        }
        manifest_path = output_dir / f"{base_name}_covers.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files_written.append(str(manifest_path))

        return ToolResult(
            success=True,
            data={
                "poster": str(poster_out or poster_path),
                "covers": covers,
                "manifest_path": str(manifest_path),
                "files_written": files_written,
            },
            artifacts=[cover["path"] for cover in covers] + [str(manifest_path)],
        )
