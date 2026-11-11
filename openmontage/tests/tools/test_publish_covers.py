"""Tests for the publish_covers publisher tool.

Generates a synthetic poster/video with ffmpeg, then checks the Douyin 4:3 and
3:4 cover contract, the manifest, the vertical minimum, and registry discovery.
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.publishers.publish_covers import PublishCovers
from tools.tool_registry import ToolRegistry


def _make_poster(path: Path, width: int = 1344, height: int = 768) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x334455:s={width}x{height}",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
    )


def _make_video(path: Path, width: int = 1344, height: int = 768) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={width}x{height}:rate=24",
            "-t",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def test_contract_metadata():
    tool = PublishCovers()
    info = tool.get_info()
    assert info["name"] == "publish_covers"
    assert info["capability"] == "publish"
    assert info["tier"] == "publish"
    assert info["provider"] == "ffmpeg"
    assert info["resource_profile"]["network_required"] is False
    assert tool.estimate_cost({}) == 0.0


def test_missing_source_errors():
    result = PublishCovers().execute({})
    assert result.success is False
    assert "poster_path" in (result.error or "")


def test_douyin_covers_from_poster(tmp_path):
    poster = tmp_path / "demo_poster.jpg"
    _make_poster(poster)

    result = PublishCovers().execute(
        {
            "poster_path": str(poster),
            "output_dir": str(tmp_path / "exports"),
            "base_name": "demo",
            "platform": "douyin",
            "horizontal_focus": "left",
            "vertical_focus": "center",
        }
    )
    assert result.success is True, result.error

    covers = {cover["name"]: cover for cover in result.data["covers"]}
    assert (covers["horizontal"]["width"], covers["horizontal"]["height"]) == (1440, 1080)
    assert (covers["vertical"]["width"], covers["vertical"]["height"]) == (1080, 1440)
    assert Path(covers["horizontal"]["path"]).is_file()
    assert Path(covers["vertical"]["path"]).is_file()

    manifest = json.loads(Path(result.data["manifest_path"]).read_text())
    assert manifest["platform"] == "douyin"
    assert manifest["focus"] == {"horizontal": "left", "vertical": "center"}
    assert [cover["name"] for cover in manifest["covers"]] == ["horizontal", "vertical"]


def test_douyin_vertical_minimum(tmp_path):
    poster = tmp_path / "demo_poster.jpg"
    _make_poster(poster)

    result = PublishCovers().execute(
        {
            "poster_path": str(poster),
            "output_dir": str(tmp_path / "exports"),
            "platform": "douyin",
            "horizontal_size": "600x450",
            "vertical_size": "600x800",
        }
    )
    assert result.success is False
    assert "600x800" in (result.error or "")


def test_custom_size_must_keep_platform_aspect(tmp_path):
    poster = tmp_path / "demo_poster.jpg"
    _make_poster(poster)

    result = PublishCovers().execute(
        {
            "poster_path": str(poster),
            "output_dir": str(tmp_path / "exports"),
            "platform": "douyin",
            "horizontal_size": "1920x1080",
        }
    )
    assert result.success is False
    assert "aspect ratio" in (result.error or "")


def test_generic_platform_uses_16x9_names(tmp_path):
    poster = tmp_path / "demo_poster.jpg"
    _make_poster(poster)

    result = PublishCovers().execute(
        {
            "poster_path": str(poster),
            "output_dir": str(tmp_path / "exports"),
            "base_name": "demo",
            "platform": "generic",
        }
    )
    assert result.success is True, result.error
    names = [Path(cover["path"]).name for cover in result.data["covers"]]
    assert names == ["demo_cover_16x9.jpg", "demo_cover_9x16.jpg"]


def test_poster_frame_from_video(tmp_path):
    video = tmp_path / "renders" / "final.mp4"
    _make_video(video)

    result = PublishCovers().execute(
        {
            "video_path": str(video),
            "poster_time": 1,
            "output_dir": str(tmp_path / "exports"),
            "base_name": "demo",
        }
    )
    assert result.success is True, result.error
    poster = Path(result.data["poster"])
    assert poster.is_file()
    assert poster.name == "demo_poster.jpg"
    assert len(result.data["covers"]) == 2


def test_registry_discovers_publish_covers():
    registry = ToolRegistry()
    registry.discover()
    tool = registry.get("publish_covers")
    assert tool is not None
    assert tool.name == "publish_covers"
    assert registry.get_by_capability("publish")
