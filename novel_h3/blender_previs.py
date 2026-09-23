"""Render a silent Blender blockout guide for H3 Ref2VA shots."""

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .project import digest, file_hash, read, write


VERSION = "blender_spatial_guide_v2"
REPO = Path(__file__).resolve().parents[1]
RENDER_SCRIPT = REPO / "scripts" / "render_blender_previs.py"
GUIDE_POLICY = (
    "The silent grayscale Blender reference <Video 1> is a spatial and camera guide only. "
    "Match its scene geometry, registered-actor count and blocking, screen direction, camera path, "
    "and timing. Do not copy proxy appearance, gray materials, lighting, or sound. "
    "Use approved <Picture> references for final character identity and photorealistic set appearance. "
    "No audio is attached to <Video 1>; only explicit dialogue events and their bound audio references may speak."
)


def binary_path(cfg):
    settings = cfg.get("blender_previs", {})
    configured = settings.get("binary") or os.environ.get("NOVEL_H3_BLENDER_BIN")
    candidates = [configured, shutil.which("blender"),
                  str(Path.home() / ".local/share/novel-h3-studio/blender-5.2.2/blender")]
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return str(Path(candidate).resolve())
    raise ValueError("Blender 白模预演已启用，但找不到 Blender；请运行 scripts/install_blender.sh 或设置 NOVEL_H3_BLENDER_BIN")


@lru_cache(maxsize=4)
def blender_version(binary):
    result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30, check=True)
    first = (result.stdout or result.stderr).splitlines()[0]
    return first.strip()


def _index(root):
    assets_path = Path(root) / "bible" / "assets.json"
    data = read(assets_path) if assets_path.exists() else {}
    result = {}
    for bucket in ("scenes", "characters", "props"):
        for name, item in data.get(bucket, {}).items():
            result[item["id"]] = {**item, "name": name, "bucket": bucket}
    return result


def _scene_kind(scene_id, scene):
    # The asset's own name is authoritative. A hall description can mention
    # the palace exterior as a style reference; that incidental phrase must
    # never turn the council room into an exterior blockout.
    canonical_name = str(scene.get("name", "")).strip()
    if canonical_name == "太微殿" or scene_id == "scene_a1c8c45145a6":
        return "hall"
    if canonical_name in {"太微宫", "紫微宫", "太微宫外云路"} or scene_id in {
        "scene_fe9e4aaa2c30", "scene_f85db3db040c", "scene_taiwei_exterior"
    }:
        return "celestial_exterior"
    name = " ".join((canonical_name, scene_id)).lower()
    if any(x in name for x in ("东海", "河谷", "河岸", "洪水", "海水", "海岸", "sea", "river", "flood", "ocean")):
        return "water"
    if any(x in name for x in ("灾变", "山崩", "地裂", "废墟", "damaged", "disaster", "ruins")):
        return "disaster"
    if any(x in name for x in ("云路", "天外", "高空", "云海", "宫外", "exterior", "cloud", "celestial platform")):
        return "celestial_exterior"
    if any(x in name for x in ("宫", "殿", "厅", "府", "庙", "hall", "palace", "temple", "court")):
        return "hall"

    description = " ".join((scene.get("design_description", ""), scene.get("source_facts", ""),
                             scene.get("evidence", ""))).lower()
    first_clause = re.split(r"[；;。\n]", str(scene.get("design_description", "")), maxsplit=1)[0].lower()
    if any(x in first_clause for x in ("外景", "宫阙外", "palace exterior", "exterior of the palace")):
        return "celestial_exterior"

    if any(x in description for x in ("议事大殿", "大殿内", "内景", "hall interior", "interior of the palace")):
        return "hall"
    if any(x in description for x in ("东海", "河谷", "河岸", "洪水", "海水", "海岸", "sea", "river", "flood", "ocean")):
        return "water"
    if any(x in description for x in ("灾变", "山崩", "地裂", "废墟", "damaged", "disaster", "ruins")):
        return "disaster"
    if any(x in description for x in ("云路", "天外", "高空", "云海", "宫外", "exterior", "cloud", "celestial platform")):
        return "celestial_exterior"
    if any(x in description for x in ("宫", "殿", "厅", "府", "庙", "hall", "palace", "temple", "court")):
        return "hall"
    if any(x in description for x in ("室", "房", "屋", "洞府", "interior", "room", "chamber", "cave")):
        return "interior"
    return "landscape"


def _blocking(location, cast, scene_kind, shot=None):
    marks = location.get("characters", {})
    authored = {actor.get("asset_id"): actor for actor in
                (shot or {}).get("blocking_plan", {}).get("actors", [])}
    result = []
    fallback_positions = {
        "hall": [(-5.2, -7.0), (-5.2, -2.5), (-5.2, 2.0), (-5.2, 6.5),
                 (5.2, -7.0), (5.2, -2.5), (5.2, 2.0), (5.2, 6.5)],
        "celestial_exterior": [(-4.5, 0), (-1.5, 0), (1.5, 0), (4.5, 0)],
    }.get(scene_kind, [(-2.5, 0), (2.5, 0), (-5, 3), (5, 3)])
    for i, item in enumerate(cast):
        mark = str(marks.get(item["id"], ""))
        seat = re.search(r"seat\s*(\d+)", mark, re.I)
        side = "left" if re.search(r"left row|左排|左侧", mark, re.I) else (
            "right" if re.search(r"right row|右排|右侧", mark, re.I) else "")
        # Only a hall assignment implies the Jade Emperor's throne.  The name
        # alone must not teleport him into the rear palace block on exterior
        # threshold shots; an authored doorway mark stays on the approach side.
        at_throne = "throne" in mark.lower() or "神座" in mark
        if at_throne or (scene_kind == "hall" and "玉皇" in item["name"]):
            x, y = 0.0, 13.8
            pose = "seated"
        elif seat and side:
            seat_index = max(0, min(3, int(seat.group(1)) - 1))
            x, y = ((-5.2 if side == "left" else 5.2), -7.0 + seat_index * 4.5)
            pose = "seated"
        else:
            x, y = fallback_positions[i % len(fallback_positions)]
            pose = "standing"
        plan = authored.get(item["id"], {})
        start = plan.get("start_position", {})
        x, y = float(start.get("x", x)), float(start.get("y", y))
        z = float(start.get("z", 0.0))
        pose = plan.get("pose", "flying" if scene_kind == "celestial_exterior" and plan.get("path") else pose)
        path = []
        for point in plan.get("path", []):
            position = point.get("position", {})
            path.append({"frame": int(point.get("frame", 1)),
                         "x": float(position.get("x", x)), "y": float(position.get("y", y)),
                         "z": float(position.get("z", z))})
        result.append({"id": item["id"], "name": item["name"], "x": x, "y": y, "z": z,
                       "pose": pose, "path": path, "instances": int(plan.get("instances", 1)),
                       "visible_throughout": bool(plan.get("visible_throughout", True)),
                       "blocking_source": plan.get("mark", mark or "shot-level neutral blocking")})
    return result


def render_spec(root, episode, shot, cfg):
    root = Path(root)
    inventory = _index(root)
    scene = inventory.get(shot.get("scene_id"), {})
    if scene.get("bucket") != "scenes":
        raise ValueError(f"{shot['id']}: Blender 白模预演缺少已登记场景 {shot.get('scene_id')}")
    refs = shot.get("references", [])
    cast = [inventory[ref["asset_id"]] for ref in refs
            if ref.get("asset_id") in inventory and inventory[ref["asset_id"]].get("bucket") == "characters"]
    props = [inventory[ref["asset_id"]] for ref in refs
             if ref.get("asset_id") in inventory and inventory[ref["asset_id"]].get("bucket") == "props"]
    staging_path = root / "bible" / "scene_staging.json"
    staging = read(staging_path).get("locations", {}) if staging_path.is_file() else {}
    location = staging.get(shot.get("scene_id"), {})
    settings = cfg.get("blender_previs", {})
    seconds = min(15.0, max(2.0, float(shot.get("frames", 48)) / 24.0))
    frames = min(360, max(49, round(seconds * 24)))
    width = int(settings.get("width", 512))
    height = int(settings.get("height", 288))
    if width < 256 or height < 144 or width % 16 or height % 16:
        raise ValueError("Blender 白模分辨率须至少 256×144 且为 16 的倍数")
    dialogue = []
    for line in shot.get("dialogue", []):
        speaker = next((x for x in cast if x["name"] == line.get("speaker")), None)
        if speaker:
            dialogue.append({"asset_id": speaker["id"], "start_frame": line.get("start_frame", 0),
                             "end_frame": line.get("end_frame", 0)})
    spec = {
        "version": VERSION,
        "episode_id": episode["id"],
        "shot_id": shot["id"],
        "scene_id": shot["scene_id"],
        "scene_name": scene["name"],
        "scene_kind": _scene_kind(shot["scene_id"], scene),
        "scene_design": scene.get("design_description", ""),
        "scene_facts": scene.get("source_facts", ""),
        "layout": location.get("layout", ""),
        "cast": _blocking(location, cast, _scene_kind(shot["scene_id"], scene), shot),
        "props": [{"id": p["id"], "name": p["name"]} for p in props],
        "dialogue_events": dialogue,
        "action": shot.get("action", ""),
        "blocking_plan": shot.get("blocking_plan", {}),
        "composition": shot.get("composition", {}),
        "action_beats": shot.get("action_beats", []),
        "state_in": shot.get("state_in", ""),
        "state_out": shot.get("state_out", ""),
        "sequence_id": shot.get("sequence_id", ""),
        "axis_id": shot.get("axis_id", ""),
        "screen_direction": shot.get("screen_direction", ""),
        "camera": shot.get("camera", {}),
        "continuity": shot.get("continuity", "cut"),
        "handoff_in": shot.get("handoff_in", ""),
        "handoff_out": shot.get("handoff_out", ""),
        "frames": frames,
        "fps": 24,
        "width": width,
        "height": height,
        "threads": max(1, min(2, int(settings.get("threads", 2)))),
        "audio": False,
        "guide_policy": GUIDE_POLICY,
        "scene_sha256": digest({k: scene.get(k) for k in ("id", "design_description", "source_facts")}),
        "staging_sha256": digest(location),
        "generator_sha256": file_hash(RENDER_SCRIPT),
    }
    spec["signature"] = digest(spec)
    return spec


def planned_guide(root, episode, shot, cfg):
    spec = render_spec(root, episode, shot, cfg)
    return {"version": VERSION, "status": "will_render_before_submission",
            "signature": spec["signature"], "reference_slot": "Video 1",
            "scene_id": shot["scene_id"], "actor_count": len(spec["cast"]),
            "frames": spec["frames"], "fps": spec["fps"],
            "width": spec["width"], "height": spec["height"], "audio_attached": False,
            "guide_policy": GUIDE_POLICY}


def build_guide(root, episode, shot, cfg):
    root = Path(root).resolve()
    binary = binary_path(cfg)
    spec = render_spec(root, episode, shot, cfg)
    spec["renderer"] = blender_version(binary)
    # Renderer version is recorded for review; the scene/layout signature remains
    # independent of the host path and is part of the content-addressed folder.
    target = root / "previews" / "blender_previs" / episode["id"] / shot["id"] / spec["signature"][:16]
    target.mkdir(parents=True, exist_ok=True)
    guide_path = target / "guide.mp4"
    manifest_path = target / "guide.json"
    if guide_path.is_file() and manifest_path.is_file():
        manifest = read(manifest_path)
        if manifest.get("signature") == spec["signature"] and manifest.get("sha256") == file_hash(guide_path):
            return manifest
    spec_path = target / "scene_spec.json"
    write(spec_path, spec)
    command = [binary, "--background", "--factory-startup", "--threads", str(spec["threads"]),
               "--python-exit-code", "1", "--python", str(RENDER_SCRIPT), "--", "--spec", str(spec_path)]
    try:
        result = subprocess.run(command, cwd=target, capture_output=True, text=True, timeout=600, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        details = getattr(exc, "stderr", "") or getattr(exc, "stdout", "") or str(exc)
        raise ValueError(f"Blender 白模预演失败：{str(details)[-2400:]}") from exc
    if not guide_path.is_file():
        raise ValueError(f"Blender 未输出空间引导视频：{guide_path}\n{result.stdout[-1200:]}")
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ValueError("缺少 ffprobe，无法核验 Blender 引导视频")
    probe = subprocess.run([ffprobe, "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate",
                            "-show_entries", "format=duration", "-of", "json", str(guide_path)],
                           capture_output=True, text=True, timeout=30, check=True)
    media = json.loads(probe.stdout)
    video = next((s for s in media.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in media.get("streams", []))
    duration = float(media.get("format", {}).get("duration", 0))
    if not video or audio or (video.get("width"), video.get("height")) != (spec["width"], spec["height"]):
        raise ValueError("Blender 引导视频未通过尺寸/无声轨校验")
    if not 1.95 <= duration <= 15.2:
        raise ValueError(f"Blender 引导视频时长异常：{duration:.2f} 秒")
    manifest = {"version": VERSION, "status": "rendered", "path": str(guide_path.relative_to(root)),
                "sha256": file_hash(guide_path), "signature": spec["signature"],
                "renderer": spec["renderer"], "scene_id": spec["scene_id"],
                "cast": [x["id"] for x in spec["cast"]], "actor_count": len(spec["cast"]),
                "camera": spec["camera"], "frames": spec["frames"], "fps": spec["fps"],
                "duration_seconds": duration, "width": spec["width"], "height": spec["height"],
                "audio_attached": False, "guide_policy": GUIDE_POLICY}
    write(manifest_path, manifest)
    return manifest
