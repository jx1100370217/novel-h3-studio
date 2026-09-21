"""Four-view character assets used as exact H3 image references."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .director import image_job, gender_prompt
from .project import file_hash, inside, load_state, read, register_asset, safe_id, write


VIEW_SPECS = {
    "front": {"label": "正面", "model_label": "front full-body"},
    "back": {"label": "背面", "model_label": "back full-body"},
    "side": {"label": "侧面", "model_label": "left-profile full-body"},
    "face": {"label": "脸部特写", "model_label": "face close-up"},
}


def _records(root):
    path = Path(root) / "bible/assets.json"
    if not path.exists():
        return
    inventory = read(path)
    for name, card in inventory.get("characters", {}).items():
        yield name, card["id"], card, None
        for variant, derivative in card.get("derivatives", {}).items():
            combined = dict(card)
            combined.update(derivative)
            combined["design_description"] = (
                f"{card.get('design_description', '')} Variant {variant}: "
                f"{derivative.get('description', '')}"
            )
            yield f"{name}{variant}", derivative["id"], combined, card["id"]


def character_asset_ids(root):
    return {asset_id for _, asset_id, _, _ in _records(root)}


def turnaround_id(asset_id):
    return f"{safe_id(asset_id)}__turnaround"


def registry(root):
    path = Path(root) / "bible/character_views.json"
    return read(path) if path.exists() else {"schema": "character_four_views_v1", "characters": {}}


def ensure_jobs(root):
    """Create one Images 2.5 four-panel master job for each appearance."""
    root = Path(root)
    cfg = read(root / "config.json")
    state = load_state(root)
    book = registry(root)
    for name, asset_id, card, parent_id in _records(root):
        master_id = turnaround_id(asset_id)
        preferred = card.get("identity_reference_asset_id")
        candidates = [preferred, asset_id, parent_id]
        references = [candidate for candidate in candidates
                      if candidate and state.get("assets", {}).get(candidate, {}).get("approved")]
        references = references[:1]
        prompt = (
            "Use case: live-action Chinese mythological period film character continuity turnaround. "
            f"Character: {name}. Source facts: {card.get('source_facts', card.get('evidence', ''))} "
            f"Locked design: {card.get('design_description', card.get('description', ''))} "
            f"Visual-only gender lock: {gender_prompt(card.get('gender', '未知'))}. Never speak or subtitle this metadata. "
            "Create one clean landscape master containing exactly four clearly separated vertical panels of "
            "the same single identity, same age, same face, same hair, same costume, same body proportions "
            "and same accessories. Panel order from left to right must be: front full-body standing neutral; "
            "back full-body standing neutral; left-profile full-body standing neutral; face close-up in a "
            "neutral three-quarter expression. Use wide plain gutters and a neutral grey studio background. "
            "No text, labels, borders, weapons not present in the locked design, extra people, duplicate body "
            "inside a panel, mirror, inset portrait, scenery, watermark, anime or game rendering. "
            f"Overall finish: {cfg.get('style', '')}"
        )
        job_path = root / "jobs" / f"image_{master_id}.json"
        if not job_path.exists():
            image_job(root, master_id, prompt, references, role="character_four_view_turnaround_master")
        current = book["characters"].get(asset_id, {})
        book["characters"][asset_id] = {
            **current,
            "asset_id": asset_id,
            "name": name,
            "master_asset_id": master_id,
            "required_views": list(VIEW_SPECS),
            "source_reference_asset_ids": references,
            "status": current.get("status", "waiting_for_images_2_5"),
        }
    write(root / "bible/character_views.json", book)
    return book


def _safe_display_name(value):
    return re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip() or "角色"


def _panel_boundaries(path, width, height):
    """Find the full-height background discontinuities between generated panels."""
    raw = subprocess.check_output([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-vf", "format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ], timeout=60)
    if len(raw) != width * height:
        raise ValueError("无法读取人物四视总图像素")
    seams = []
    radius = max(8, round(width * 0.06))
    for fraction in (0.25, 0.5, 0.75):
        target = round(width * fraction)
        candidates = []
        for x in range(max(1, target-radius), min(width-1, target+radius)):
            score = sum(abs(raw[y*width+x] - raw[y*width+x-1]) for y in range(height)) / height
            candidates.append((score, x))
        seams.append(max(candidates)[1])
    boundaries = [0, *seams, width]
    if any(b-a < width * 0.15 for a, b in zip(boundaries, boundaries[1:])):
        return [round(width * i / 4) for i in range(5)]
    return boundaries


def register_turnaround(root, character_asset_id, source, receipt):
    """Register an image_gen master, then split it into four independent PNGs."""
    root = Path(root)
    character_asset_id = safe_id(character_asset_id)
    book = ensure_jobs(root)
    entry = book["characters"].get(character_asset_id)
    if not entry:
        raise ValueError(f"角色资产不存在：{character_asset_id}")
    master_id = entry["master_asset_id"]
    receipt = dict(receipt, job_sha256=receipt["job_sha256"])
    master = register_asset(root, master_id, source, receipt)
    master_path = inside(root, master["path"])

    from .media import probe
    streams = [s for s in probe(master_path)["streams"] if s.get("codec_type") == "video"]
    width, height = int(streams[0]["width"]), int(streams[0]["height"])
    # Images 2.5 may return either 1792x1024 or 1536x1024 for a requested
    # landscape contact sheet. Both contain four usable vertical panels.
    if width < 800 or height < 400 or width / height < 1.4:
        raise ValueError("人物四视总图必须是清晰的横向四栏图片")
    out_dir = root / "assets/character_views" / character_asset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    display = _safe_display_name(entry["name"])
    views = {}
    boundaries = _panel_boundaries(master_path, width, height)
    for index, (view, spec) in enumerate(VIEW_SPECS.items()):
        left, right = boundaries[index], boundaries[index + 1]
        output = out_dir / f"{display}{spec['label']}.png"
        pending = output.with_name(f".{output.stem}.pending.png")
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(master_path),
            "-vf", f"crop={right-left}:{height}:{left}:0", "-frames:v", "1", str(pending),
        ], check=True, timeout=60, capture_output=True)
        pending.replace(output)
        views[view] = {
            "label": spec["label"],
            "model_label": spec["model_label"],
            "display_name": f"{display}{spec['label']}",
            "path": str(output.relative_to(root)),
            "sha256": file_hash(output),
            "crop": {"left": left, "top": 0, "width": right-left, "height": height},
        }
    entry.update({
        "status": "waiting_for_manual_review",
        "master_path": master["path"],
        "master_sha256": master["sha256"],
        "views": views,
    })
    write(root / "bible/character_views.json", book)
    return entry


def select_view(shot, ref, speech_bindings=None):
    """Choose the exact independent reference image used for this subject."""
    explicit = ref.get("view")
    if explicit:
        if explicit not in VIEW_SPECS:
            raise ValueError(f"未知人物参考视角：{explicit}")
        return explicit, "storyboard_explicit"
    camera = shot.get("camera", {})
    text = " ".join(str(camera.get(key, "")) for key in ("size", "movement", "angle"))
    action = str(shot.get("action", ""))
    combined = f"{text} {action}".lower()
    if any(word in combined for word in ("rear view", "from behind", "背影", "背面", "后方跟随")):
        return "back", "camera_or_blocking_rear"
    if any(word in combined for word in ("profile", "side view", "侧面", "侧脸")):
        return "side", "camera_or_blocking_profile"
    if ("over-the-shoulder" in combined or "过肩" in combined
            or "rear shoulder" in combined or "back-of-head" in combined):
        speakers = {item.get("asset_id") for item in (speech_bindings or [])}
        if ref.get("asset_id") not in speakers:
            # The listener is rendered as a partial rear shoulder/back in an
            # over-the-shoulder shot. Sending a front image here creates a
            # contradictory identity/composition instruction and lets H3
            # invent a second or gender-swapped listener. Bind the actual
            # approved back view so the image and blocking describe one body.
            return "back", "over_shoulder_listener_rear_identity_anchor"
        return "front", "over_shoulder_speaker_facing_camera"
    if any(word in combined for word in ("close-up", "close up", "extreme close", "特写", "近景")):
        return "face", "camera_closeup"
    return "front", "default_identity_view"


def resolve_view(root, character_asset_id, view):
    """Resolve and validate an approved four-view master and one split file."""
    from .comfy import asset_for

    root = Path(root)
    character_asset_id = safe_id(character_asset_id)
    value = registry(root).get("characters", {}).get(character_asset_id)
    if not value or not value.get("views"):
        raise ValueError(f"人物 {character_asset_id} 缺少四视参考图")
    master_path, master_sha = asset_for(root, value["master_asset_id"])
    if master_sha != value.get("master_sha256") or file_hash(master_path) != master_sha:
        raise ValueError(f"人物 {character_asset_id} 的四视总图已变化")
    record = value["views"].get(view)
    if not record:
        raise ValueError(f"人物 {character_asset_id} 缺少 {view} 视角")
    path = inside(root, record["path"])
    if not path.is_file() or file_hash(path) != record.get("sha256"):
        raise ValueError(f"人物 {character_asset_id} 的 {view} 参考图缺失或已变化")
    return {
        "asset_id": character_asset_id,
        "source_sha256": master_sha,
        "generation_path": str(path.relative_to(root)),
        "generation_sha256": record["sha256"],
        "variant": view,
        "selected_view": view,
        "selected_view_label": record["label"],
        "selected_view_reason": None,
        "master_asset_id": value["master_asset_id"],
    }


def readiness_blockers(root, character_asset_id, name=None):
    value = registry(root).get("characters", {}).get(character_asset_id)
    label = name or character_asset_id
    if not value or not value.get("views"):
        return [{"asset": character_asset_id, "name": label, "reason": "character_views_missing"}]
    state = load_state(root).get("assets", {}).get(value["master_asset_id"], {})
    if not state.get("approved"):
        return [{"asset": character_asset_id, "name": label, "reason": "character_views_review_pending",
                 "details": "正面、背面、侧面、脸部特写必须作为同一身份人工审阅通过"}]
    problems = []
    for view in VIEW_SPECS:
        record = value.get("views", {}).get(view, {})
        path = inside(root, record.get("path", "")) if record.get("path") else None
        if not path or not path.is_file() or file_hash(path) != record.get("sha256"):
            problems.append(view)
    if problems:
        return [{"asset": character_asset_id, "name": label, "reason": "character_views_file_invalid",
                 "details": "缺失或变化的视角：" + "、".join(problems)}]
    return []
