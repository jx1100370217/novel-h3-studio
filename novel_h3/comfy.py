import json
import copy
import hashlib
import math
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid

from .director import delivered_frames, episode_path, h3_prompt, validate_episode, has_visible_dialogue
from .project import read, write, digest, file_hash, inside, load_state, locked, update_state, safe_id
from .shot_package import compile_package
from .safety import native_generation


def api(base, route, payload=None, timeout=20):
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base.rstrip("/") + route, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise ValueError(f"ComfyUI {exc.code}: {exc.read().decode()[:3000]}") from exc


def config(root):
    cfg = read(Path(root) / "config.json")
    return cfg


_VISUAL_SPEAKER_RETAKE_TERMS = (
    "说话人", "人物不匹配", "角色不匹配", "画面错", "嘴型", "嘴动",
    "无极在说话", "盘古在说话", "女娲在说话", "人物错", "脸错",
    "说了对白", "说了对话", "误说", "错用对白", "对白错",
    "听者不入镜", "画面只保留说话者", "单人近景",
)


def _speaker_review_correction(note, dialogue=()):
    """Compile a human review note into a silent, model-safe identity fix."""
    text = re.sub(r"\s+", "", str(note or ""))
    explicit_mapping = re.search(r"[\u4e00-\u9fff]{1,8}说了[\u4e00-\u9fff]{1,8}(?:的)?(?:对白|对话)", text)
    if not text or (not explicit_mapping and not any(term in text for term in _VISUAL_SPEAKER_RETAKE_TERMS)):
        return None
    speakers = [str(line.get("speaker", "")).strip() for line in dialogue or []
                if line.get("kind") != "voiceover" and str(line.get("speaker", "")).strip()]
    correct = speakers[0] if len(set(speakers)) == 1 else None
    if correct and any(term in text for term in ("听者不入镜", "画面只保留说话者", "单人近景")):
        return {"wrong_visual_speaker": None, "correct_speaker": correct,
                "reason": "reviewed_single_speaker_composition", "single_subject_frame": True}
    wrong = None
    match = re.search(r"([\u4e00-\u9fff]{1,8})说了([\u4e00-\u9fff]{1,8})(?:的)?(?:对白|对话)", text)
    if match:
        wrong, mentioned = match.groups()
        wrong = re.sub(r"^(?:视频中|画面中|镜头中|视频里|画面里|镜头里)", "", wrong)
        if mentioned in speakers:
            correct = mentioned
    if correct and wrong and correct != wrong:
        return {"wrong_visual_speaker": wrong, "correct_speaker": correct,
                "reason": "reviewed_speaker_identity_mismatch"}
    if any(term in text for term in ("人物不匹配", "角色不匹配", "说话人", "嘴型", "嘴动", "画面错", "人物错", "脸错")):
        if correct:
            return {"wrong_visual_speaker": "unresolved_visible_subject", "correct_speaker": correct,
                    "reason": "reviewed_speaker_identity_mismatch"}
        return {"wrong_visual_speaker": "unresolved_visible_subject", "correct_speaker": None,
                "reason": "reviewed_speaker_identity_mismatch"}
    return None


def _speaker_visual_retake(note, dialogue=()):
    """Whether a review requires a structural visual speaker correction."""
    return _speaker_review_correction(note, dialogue) is not None


def _retake_shot_contract(shot, rework_item, root=None):
    """Apply a repeatable speaker-dominant composition for identity retakes.

    A review note alone is too weak for H3: the old rework path could submit
    the same two-shot with the same seed and produce the same wrong mouth.
    This override keeps the bound cast and audio unchanged, but makes the
    declared speaker the only fully visible face and hides the listener's
    face behind one bound shoulder/back-of-head.
    """
    dialogue = shot.get("dialogue") or []
    note = str(rework_item.get("note", "")) if rework_item else ""
    result = copy.deepcopy(shot)
    compact_note = re.sub(r"\s+", "", note)
    exact_cast = (not dialogue and rework_item and any(
        term in compact_note for term in (
            "画面只能出现宋焘和张生", "只允许宋焘和张生出镜", "不得出现第三人",
        )))
    blank_paper = (not dialogue and rework_item and any(
        term in note for term in ("纸面完全空白", "纸面必须完全空白")))
    if exact_cast:
        plan = copy.deepcopy(result.get("blocking_plan") or {})
        actors = [actor for actor in plan.get("actors", []) if actor.get("asset_id")]
        character_ids = list(dict.fromkeys(actor["asset_id"] for actor in actors))
        if len(character_ids) < 2:
            raise ValueError("精确双人重拍要求 blocking_plan 中至少绑定两位角色")
        total_frames = max(1, int(result.get("frames", 1)) -
                           (22 if result.get("continuity") == "continue" else 0))
        end_frame = total_frames - 1
        camera = dict(result.get("camera") or {})
        camera.update(
            size="balanced eye-level two-shot, both scholars chest-up and equally readable",
            lens_mm=50,
            movement="locked tripod",
            motivation="Keep both registered scholars fully visible and unobstructed; leave no foreground space for another person.",
            position={"x": 0.0, "y": -6.0, "z": 1.7},
            look_at={"x": 0.0, "y": -1.0, "z": 1.3},
        )
        camera["path"] = [
            {"frame": 0, "position": copy.deepcopy(camera["position"]),
             "look_at": copy.deepcopy(camera["look_at"])},
            {"frame": end_frame, "position": copy.deepcopy(camera["position"]),
             "look_at": copy.deepcopy(camera["look_at"])},
        ]
        result["camera"] = camera
        plan.update(expected_actor_count=len(character_ids),
                    expected_body_count=len(character_ids),
                    environment_only_allowed=False,
                    actors=actors,
                    offscreen_listeners=[])
        result["blocking_plan"] = plan
        names = [actor.get("mark", actor["asset_id"]).split(";", 1)[0] for actor in actors]
        cast_label = "、".join(names)
        first_action = f"仅出现已绑定的{cast_label}两人，两人分别坐在自己的考桌前继续书写；同一机位同时看清两人面部和上半身。不得有第三个人、监考者、差役、前景身体或遮挡张生的人。"
        second_action = f"{cast_label}仍分别坐在原位；宋焘短暂举起自己的纸，张生留在画面中。没有人走入、站到两人之间或接收纸张。全片只有这两个人。"
        if blank_paper:
            second_action = f"{cast_label}仍分别坐在原位；宋焘短暂举起完全空白的纸，张生留在画面中。纸上没有字迹、笔画、印章或标记。没有人走入、站到两人之间或接收纸张。全片只有这两个人。"
        result["action"] = first_action + " " + second_action
        split_frame = min(96, total_frames)
        result["timeline"] = [{"start_frame": 0, "end_frame": split_frame,
                                "description": first_action}]
        if split_frame < total_frames:
            result["timeline"].append({"start_frame": split_frame, "end_frame": total_frames,
                                       "description": second_action})
        result["action_beats"] = [
            {"start_frame": beat["start_frame"], "end_frame": beat["end_frame"],
             "action": beat["description"]}
            for beat in result["timeline"]
        ]
        result["handoff_out"] = "宋焘与张生仍分别坐在原考桌旁；仅二人入镜，无人接近或遮挡。"
        composition = copy.deepcopy(result.get("composition") or {})
        composition["primary_subject"] = "、".join(character_ids)
        composition["actor_readability"] = "Exactly the two registered scholars remain chest-up and unobstructed in every frame; no third body enters or stands in the foreground."
        result["composition"] = composition
        contract = {
            "mode": "exact_cast",
            "visible_character_ids": character_ids,
            "visible_body_count": len(character_ids),
            "no_unbound_people": True,
            "no_foreground_occlusion": True,
        }
        if blank_paper:
            contract["blank_paper"] = True
        result["retake_visual_contract"] = contract
        if root:
            assets = read(Path(root) / "bible" / "assets.json")
            scene_and_props = {item.get("id") for section in ("scenes", "props")
                               for item in assets.get(section, {}).values()}
            keep_ids = set(character_ids) | scene_and_props | {result.get("scene_id")}
            if blank_paper:
                essay_ids = {item.get("id") for name, item in assets.get("props", {}).items()
                             if any(word in str(name).lower() for word in ("essay", "试文"))
                             or any(word in str(item.get("name", "")) for word in ("试文", "考卷"))}
                keep_ids -= essay_ids
            result["references"] = [ref for ref in result.get("references", [])
                                     if ref.get("asset_id") in keep_ids]
            result["required_assets"] = [asset_id for asset_id in result.get("required_assets", [])
                                         if asset_id in keep_ids]
        return result
    if (not dialogue and ("纸面完全空白" in note or "纸面必须完全空白" in note)) and rework_item:
        contract = {
            "mode": "blank_paper",
            "blank_paper": True,
            "instruction": "Every manuscript page is featureless blank cream paper, with no strokes, glyphs, seals, headings or subtitles; show pages face down or turned away from camera.",
        }
        result["retake_visual_contract"] = contract
        result["action"] = (str(result.get("action", "")) +
                            " Retake visual correction: keep both manuscript pages face down or turned away; "
                            "every page surface is completely blank, with no visible ink marks, letters, seals or captions.")
        if root:
            assets = read(Path(root) / "bible" / "assets.json")
            essay_ids = {item.get("id") for name, item in assets.get("props", {}).items()
                         if any(word in str(name).lower() for word in ("essay", "试文"))
                         or any(word in str(item.get("name", "")) for word in ("试文", "考卷"))}
            result["references"] = [ref for ref in result.get("references", [])
                                     if ref.get("asset_id") not in essay_ids]
            result["required_assets"] = [asset_id for asset_id in result.get("required_assets", [])
                                         if asset_id not in essay_ids]
        return result
    correction = _speaker_review_correction(note, dialogue) if rework_item else None
    if not correction:
        return result
    result = copy.deepcopy(shot)
    speaker = correction.get("correct_speaker") or (dialogue[0].get("speaker") if dialogue else "")
    solo = correction.get("single_subject_frame") is True
    speaker_frame_prop = solo and "寿籍" in note and any(term in note for term in (
        "寿籍必须清晰入镜", "双手持寿籍", "双手持同一本寿籍", "手中寿籍可见",
        "寿籍持续显示", "册子持续显示",
    ))
    result["speaker_focus_mode"] = "speaker_only" if solo else "speaker_dominant"
    result["speaker_focus_name"] = speaker
    if speaker_frame_prop:
        result["speaker_frame_prop"] = True
    camera = dict(result.get("camera") or {})
    if solo:
        camera["size"] = (
            "medium close-up from chest to head, both hands and blank longevity register visible"
            if speaker_frame_prop else
            "tight single-speaker close-up, head and shoulders fill frame"
        )
        camera["lens_mm"] = 70
        camera["movement"] = "locked tripod"
        camera["motivation"] = (
            "Keep the only assigned speaking face large and readable while both hands and the held blank longevity register remain visible from frame zero through the line."
            if speaker_frame_prop else
            "Keep the only assigned speaking face readable from the first frame through the last dialogue window."
        )
        plan = copy.deepcopy(result.get("blocking_plan") or {})
        actors = plan.get("actors", [])
        voices = read(Path(root) / "bible" / "voices.json") if root else {}
        speaker_asset = voices.get(speaker, {}).get("asset_id")
        speaker_actor = next((actor for actor in actors
                              if actor.get("asset_id") == speaker_asset
                              or speaker in str(actor.get("mark", ""))), None)
        if speaker_actor:
            target = speaker_actor.get("start_position")
            if not target:
                path = speaker_actor.get("path") or []
                target = next((point.get("position") for point in path
                               if point.get("position") is not None), None)
            if target:
                heading = float(speaker_actor.get("heading", 0.0))
                camera_distance = 3.2 if speaker_frame_prop else 2.8
                camera["position"] = {
                    "x": float(target["x"]) + math.sin(heading) * camera_distance,
                    "y": float(target["y"]) - math.cos(heading) * camera_distance,
                    "z": float(target["z"]) + (1.5 if speaker_frame_prop else 1.65),
                }
                camera["look_at"] = {
                    "x": float(target["x"]), "y": float(target["y"]),
                    "z": float(target["z"]) + (1.05 if speaker_frame_prop else 1.35),
                }
        position, look_at = camera.get("position"), camera.get("look_at")
        if position and look_at:
            end_frame = max(0, int(result.get("frames", 1)) - 1)
            camera["path"] = [
                {"frame": 0, "position": copy.deepcopy(position), "look_at": copy.deepcopy(look_at)},
                {"frame": end_frame, "position": copy.deepcopy(position), "look_at": copy.deepcopy(look_at)},
            ]
        if plan:
            plan["offscreen_listeners"] = []
            plan["expected_actor_count"] = 1
            plan["expected_body_count"] = 1
            plan["actors"] = ([speaker_actor] if speaker_actor else actors[:1])
            result["blocking_plan"] = plan
        result["action"] = (str(result.get("action", "")) +
                            f" Retake correction: start on {speaker}'s head-and-shoulders close-up in frame zero and hold that single face throughout every line and pause; "
                            "all listeners and every other person stay fully offscreen. No empty room or court, no wide view, reverse shot, audience shoulder, silhouette, reflection or cutaway.")
        if solo:
            result["sequence_id"] = "single_speaker_closeup_retake"
            result["beat_function"] = "hold one uninterrupted close-up through the assigned line"
            result["axis_id"] = "single_speaker_camera_axis"
            result["screen_direction"] = "Keep one front-facing close-up on the assigned speaker; no interlocutor axis or shot-reverse-shot."
            result["transition"] = "No cut, reverse angle or internal reframing."
            result["action"] = (
                "One uninterrupted medium close-up of the assigned speaker from chest to head. At frame zero, the speaker is alone, facing camera; both hands hold the same aged longevity register clearly in the lower part of frame. Keep the face large, eyes and moving mouth unobstructed throughout the complete line and pauses. The register pages are blank and unreadable; no page turn, extra writing or added person. Keep every listener outside the image."
                if speaker_frame_prop else
                "One uninterrupted dialogue close-up. At frame zero, the assigned speaker is already alone in a tight head-and-shoulders frame; "
                "the face fills the composition and the eyes and mouth stay clear through the complete assigned line and pauses. "
                "Use only subtle natural facial and mouth movement; keep the speaker at the authored mark and preserve the same identity. "
                "Keep the courtroom and all other people outside the frame; no listener, foreground body, empty-room opening, wide shot, reverse shot or cutaway."
            )
            frame_count = delivered_frames(result)
            result["timeline"] = [{
                "start_frame": 0, "end_frame": frame_count,
                "description": (
                    "The assigned speaker remains alone in a steady chest-up medium close-up, both hands holding the same blank longevity register in frame while speaking the assigned line."
                    if speaker_frame_prop else
                    "The assigned speaker remains alone in a steady head-and-shoulders close-up, speaking the assigned line with subtle natural facial movement."
                ),
            }]
            result["action_beats"] = [{
                "start_frame": 0, "end_frame": frame_count,
                "action": result["timeline"][0]["description"],
            }]
            result["state_in"] = (
                "The assigned speaker stands alone, already framed chest-up with both hands holding the same blank register."
                if speaker_frame_prop else
                "The assigned speaker holds the authored mark alone before the line, already framed in close-up."
            )
            result["state_out"] = (
                "The same speaker remains alone with the register visible and closes the mouth after the line."
                if speaker_frame_prop else
                "The same speaker remains alone at the mark and closes the mouth after the line."
            )
            result["handoff_in"] = result["state_in"]
            result["handoff_out"] = result["state_out"]
            result["composition"] = {
                "primary_subject": speaker_asset or speaker,
                "actor_readability": (
                    "Exactly one assigned speaker; face and mouth remain large and unobstructed while both hands and the same blank longevity register remain visible in the lower frame throughout."
                    if speaker_frame_prop else
                    "Exactly one assigned speaker; head and shoulders fill frame from frame zero through the last dialogue beat, with eyes and mouth unobstructed."
                ),
                "scene_anchors": "The scene remains an indistinct background only and never becomes a framing target.",
                "screen_side": "preserve the authored speaker axis",
            }
        if root:
            cfg_assets = read(Path(root) / "bible" / "assets.json")
            voices = read(Path(root) / "bible" / "voices.json")
            speaker_asset = voices.get(speaker, {}).get("asset_id")
            scene_id = result.get("scene_id")
            prop_ids = {item.get("id") for item in cfg_assets.get("props", {}).values()}
            keep_ids = {speaker_asset, scene_id} | prop_ids
            if result.get("blocking_plan"):
                plan = copy.deepcopy(result["blocking_plan"])
                plan["actors"] = [actor for actor in plan.get("actors", [])
                                  if actor.get("asset_id") == speaker_asset
                                  or actor.get("name") == speaker]
                plan["offscreen_listeners"] = []
                plan["expected_actor_count"] = 1
                plan["expected_body_count"] = 1
                result["blocking_plan"] = plan
            result["references"] = [ref for ref in result.get("references", [])
                                     if ref.get("asset_id") in keep_ids]
            result["required_assets"] = [asset_id for asset_id in result.get("required_assets", [])
                                         if asset_id in keep_ids]
        frame_asset_id = rework_item.get("first_frame_asset_id") if rework_item else None
        if frame_asset_id:
            if not root:
                raise ValueError("H3 视频帧首帧必须由当前项目登记并校验来源")
            asset_for(root, frame_asset_id)
            last_frame_asset_id = (rework_item.get("last_frame_asset_id") or frame_asset_id)
            asset_for(root, last_frame_asset_id)
            result["mode"] = "fl2va"
            result["first_frame"] = frame_asset_id
            result["last_frame"] = last_frame_asset_id
            result["h3_visual_only"] = True
            result["soundscape"] = "Quiet courtroom air and subtle clothing movement only; no human voice or music."
            result["action"] = (
                "One uninterrupted silent visual performance. The registered speaker starts on the supplied close-up frame and remains alone in the same "
                "head-and-shoulders composition. Use subtle natural facial expression and mouth articulation without any written words, captions or titles; "
                "spoken dialogue is added in post-production. No other person, empty-room opening, wide shot, reverse shot or cutaway."
            )
            frame_count = delivered_frames(result)
            visual_beat = (
                "Hold the supplied close-up framing on the single speaker; animate restrained natural facial expression and mouth articulation only, "
                "without written words or captions."
            )
            result["timeline"] = [{"start_frame": 0, "end_frame": frame_count,
                                   "description": visual_beat}]
            result["action_beats"] = [{"start_frame": 0, "end_frame": frame_count,
                                       "action": visual_beat}]
    else:
        camera["size"] = "speaker-dominant medium close-up with listener rear shoulder"
        camera["motivation"] = "Correct the reviewed speaker-face mismatch; keep the assigned speaker as the visual focus."
    result["camera"] = camera
    result["retake_visual_contract"] = {
        "mode": "single_speaker_closeup" if solo else "speaker_dominant",
        "speaker": speaker,
        "listener_face": "offscreen" if solo else "hidden",
        "listener": "fully offscreen; no shoulder, silhouette or reflection" if solo
                     else "one bound rear shoulder or back-of-head only",
        "visible_body_count": 1,
        "reason": correction["reason"],
        "wrong_visual_speaker": correction.get("wrong_visual_speaker"),
    }
    result["speaker_review_correction"] = correction
    return result


def doctor(root):
    cfg = config(root)
    from .fastvideo import selected, available, api as fastvideo_api
    if selected(cfg):
        result = {'url': cfg['fast_h3_omni']['api_url'], 'reachable': False,
                  'video_engine': {'id': 'fast_h3_omni', 'runtime': 'FastVideo', 'quantization': 'NVFP4 QAD'},
                  'missing_nodes': [], 'missing_models': [] if available(cfg) else ['NVFP4 QAD components or AdaLN table']}
        try:
            result['health'] = fastvideo_api(cfg, '/health')
            result['model_info'] = fastvideo_api(cfg, '/v1/model_info')
            result['reachable'] = True
        except (OSError, ValueError) as exc:
            result['error'] = str(exc)
        result['h3_ready'] = result['reachable'] and not result['missing_models']
        return result
    result = {"url": cfg["comfy_url"], "reachable": False, "missing_nodes": [], "missing_models": []}
    previs_enabled = cfg.get("blender_previs", {}).get("enabled") is True
    if previs_enabled:
        from .blender_previs import binary_path, blender_version
        try:
            blender = binary_path(cfg)
            result["blender_previs"] = {"enabled": True, "available": True,
                                         "binary": blender, "version": blender_version(blender),
                                         "reference_mode": "silent Blender guide video -> H3 Ref2VA"}
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            result["blender_previs"] = {"enabled": True, "available": False, "error": str(exc)}
    else:
        result["blender_previs"] = {"enabled": False, "available": True}
    try:
        info = api(cfg["comfy_url"], "/object_info")
        stats = api(cfg["comfy_url"], "/system_stats")
        result.update(reachable=True, version=stats["system"]["comfyui_version"], devices=stats["devices"])
        selected_engine = cfg.get("video_engine")
        if selected_engine is None:
            selected_engine = "vdn_h3_turbo" if cfg.get("vdn", {}).get("enabled") else "minimax_h3"
        required = ["MiniMaxH3MotionContext", "MiniMaxH3MotionContextTrim", "MiniMaxH3MotionContextSaveLatent",
                    "MiniMaxH3MotionContextLoadLatent", "MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo"]
        if selected_engine == "vdn_h3_turbo" and cfg.get("vdn", {}).get("enabled"):
            required.append("ApplyVDNH3")
            stage = Path(cfg["comfy_root"]) / "models/vdn" / cfg["vdn"]["inputs"]["vdn_checkpoint"]
            for name in ("model_spec.json", "linear_branch/model_int8_convrot_comfyui.safetensors",
                         "adapters/default/adapter_model.safetensors", "adapters/turbo/adapter_model.safetensors"):
                if not (stage / name).is_file():
                    result["missing_models"].append(str(stage / name))
            result["video_engine"] = {"name": "VDN-H3 Turbo", "steps": cfg["generation"]["steps"], **cfg["vdn"]}
        if previs_enabled:
            required.extend(["LoadVideo", "GetVideoComponents"])
        fast = cfg.get("fastvideo")
        if fast:
            fast_path = Path(cfg["comfy_root"]) / "models" / "diffusion_models" / fast.get("model_filename", "")
            result["fastvideo"] = {
                "name": "FastVideo FastH3-8-Step-V2",
                "model_variant": fast.get("model_variant"),
                "model_path": str(fast_path),
                "model_present": fast_path.is_file(),
                "benchmark_only": fast.get("production_enabled") is not True,
                "input_mode": fast.get("input_mode"),
                "scheduler_shift_video": fast.get("scheduler_shift_video"),
                "scheduler_shift_audio": fast.get("scheduler_shift_audio"),
                "vsa": fast.get("vsa"),
            }
        if selected_engine == "vdn_h3_turbo":
            result["video_engine"] = {"id": selected_engine, "name": "VDN-H3 Turbo",
                                       "steps": cfg["generation"]["steps"], **cfg.get("vdn", {})}
        else:
            result["video_engine"] = {"id": "minimax_h3", "name": "MiniMax H3",
                                       "steps": cfg["generation"]["steps"]}
        result["missing_nodes"] = [n for n in required if n not in info]
        for folder, key in (("diffusion_models", "fl2va"), ("diffusion_models", "ref2va"),
                            ("text_encoders", "clip"), ("vae", "video_vae"), ("vae", "audio_vae")):
            if not (Path(cfg["comfy_root"]) / "models" / folder / cfg["models"][key]).is_file():
                result["missing_models"].append(cfg["models"][key])
        result["queue"] = api(cfg["comfy_url"], "/queue")
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)
    result["h3_ready"] = (result["reachable"] and not result["missing_nodes"] and not result["missing_models"]
                          and result.get("blender_previs", {}).get("available", True))
    result["image_provider"] = "Codex 当前对话 image_gen；本地服务只能交接任务，不能自行调用订阅工具"
    result["super_resolution"] = "VOSR2 one-step 1.4B，仅验收后的可选后期；本工程不冒充已安装超分模型"
    return result


def asset_for(root, asset_id, _seen=None, require_approval=True):
    safe_id(asset_id)
    seen = set() if _seen is None else set(_seen)
    if asset_id in seen:
        raise ValueError("图片参考存在循环依赖")
    seen.add(asset_id)
    state = load_state(root)
    item = state["assets"].get(asset_id)
    if not item or (require_approval and not item["approved"]):
        raise ValueError(f"图片 {asset_id} 尚未生成或尚未验收")
    receipt = item["receipt"]
    extracted_h3_frame = receipt.get("tool") == "h3_video_frame_extract"
    job_name = f"frame_{asset_id}.json" if extracted_h3_frame else f"image_{asset_id}.json"
    job = read(Path(root) / "jobs" / job_name)
    path = inside(root, item["path"])
    if digest(job) != item["job_sha256"] or file_hash(path) != item["sha256"]:
        raise ValueError(f"图片 {asset_id} 或提示词已变化，需要重新验收")
    if extracted_h3_frame:
        source_take = state.get("takes", {}).get(receipt.get("source_take_id"))
        if (not source_take or source_take.get("video_sha256") != receipt.get("source_video_sha256")
                or source_take.get("qc", {}).get("passed") is not True
                or job.get("source_take_id") != receipt.get("source_take_id")
                or job.get("source_video_sha256") != receipt.get("source_video_sha256")
                or job.get("frame_index") != receipt.get("frame_index")
                or job.get("frame_sha256") != item["sha256"]):
            raise ValueError(f"H3 首帧 {asset_id} 的来源镜头或帧哈希不匹配")
        return path, item["sha256"]
    verified_model = receipt.get("model_verified") is True and receipt.get("actual_model", "").startswith("gpt-image-2.5")
    # Older image work orders use the immutable ``asset_id`` shape and do not
    # carry the newer provider field.  They are still valid managed Codex
    # image jobs when the receipt binds the exact job digest, prompt and tool
    # output file.  Accept both shapes so a fresh tool output is not sent back
    # to the review queue solely because the work order schema predates the
    # provider metadata field.
    managed_job = job.get("provider") == "codex_image_gen" or job.get("asset_id") == asset_id
    managed_tool = (config(root).get("image_provider", {}).get("accept_managed_tool_model_unknown") is True
                    and managed_job and receipt.get("tool") == "image_gen"
                    and receipt.get("actual_model") == "unknown"
                    and receipt.get("tool_output_file") and receipt.get("generated_at")
                    and receipt.get("prompt") == job.get("prompt"))
    if not verified_model and not managed_tool:
        raise ValueError(f"图片 {asset_id} 的 ChatGPT 5x / Images 2.5 来源尚未核实，不能进入生成。当前内置工具无模型选择参数，需先取得可核实的 2.5 输出。")
    for ref_id in job.get("reference_asset_ids", []):
        _, current_hash = asset_for(root, ref_id, seen)
        if item.get("reference_hashes", {}).get(ref_id) != current_hash:
            raise ValueError(f"图片 {asset_id} 使用的参考 {ref_id} 已变化，需要重新生成")
    return path, item["sha256"]


def register_h3_video_frame(root, asset_id, source_take_id, frame_index, frame_path, note):
    """Register a frame extracted from a technically checked H3 take as a keyframe.

    This preserves video-frame provenance and never labels the frame as an
    Images 2.5 generation or a standalone approved character/scene image.
    """
    root = Path(root).resolve()
    asset_id = safe_id(asset_id)
    state = load_state(root)
    source_take = state.get("takes", {}).get(source_take_id)
    if (not source_take or source_take.get("qc", {}).get("passed") is not True
            or not source_take.get("video_sha256") or type(frame_index) is not int
            or frame_index < 0 or frame_index >= source_take.get("qc", {}).get("frames", 0)):
        raise ValueError("H3 首帧必须来自一条已通过媒体技术检查的有效源镜头")
    source_video = inside(root, source_take["video"])
    if file_hash(source_video) != source_take["video_sha256"]:
        raise ValueError("H3 首帧源视频已变化，不能登记")
    image_path = inside(root, frame_path)
    if not image_path.is_file() or image_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("H3 首帧文件缺失或格式不受支持")
    frame_sha = file_hash(image_path)
    receipt = {
        "tool": "h3_video_frame_extract",
        "source_take_id": source_take_id,
        "source_video_sha256": source_take["video_sha256"],
        "frame_index": frame_index,
        "frame_sha256": frame_sha,
        "extracted_at": time.time(),
    }
    job = {"schema": "h3_video_frame_extraction_v1", "asset_id": asset_id,
           "source_take_id": source_take_id, "source_video_sha256": source_take["video_sha256"],
           "frame_index": frame_index, "frame_path": str(image_path.relative_to(root)),
           "frame_sha256": frame_sha, "note": str(note).strip()}
    job_path = root / "jobs" / f"frame_{asset_id}.json"
    if asset_id in state.get("assets", {}):
        existing = state["assets"][asset_id]
        if (existing.get("sha256") == frame_sha
                and existing.get("receipt", {}).get("source_take_id") == source_take_id
                and existing.get("receipt", {}).get("frame_index") == frame_index):
            return {"asset_id": asset_id, "sha256": frame_sha, "reused": True}
        raise ValueError(f"首帧资产 {asset_id} 已存在且来源不同")
    write(job_path, job)
    update_state(root, lambda current: current.setdefault("assets", {}).__setitem__(asset_id, {
        "path": str(image_path.relative_to(root)), "sha256": frame_sha,
        "job_sha256": digest(job), "receipt": receipt, "approved": True,
        "reference_hashes": {}, "reviewer": "Codex H3 帧抽取视觉检查",
        "note": str(note).strip(),
    }))
    return {"asset_id": asset_id, "sha256": frame_sha, "reused": False}


def generation_reference(root, reference, camera=None, shot=None, speech_bindings=None):
    """Return one model-safe subject view while preserving the approved source asset."""
    root = Path(root).resolve()
    ref = reference if isinstance(reference, dict) else {"asset_id": reference}
    asset_id = ref["asset_id"]
    cfg = config(root)
    four_view_policy = cfg.get("asset_policy", {}).get("character_reference_mode") == "four_independent_views"
    if four_view_policy:
        from .character_views import character_asset_ids, resolve_view, select_view
        if asset_id in character_asset_ids(root):
            view, reason = select_view(shot or {"camera": camera or {}}, ref, speech_bindings)
            resolved = resolve_view(root, asset_id, view)
            resolved["selected_view_reason"] = reason
            return resolved
    source, source_sha = asset_for(root, asset_id)
    inventory_path = root / "bible/assets.json"
    scene = next((item for item in read(inventory_path).get("scenes", {}).values()
                  if item.get("id") == asset_id), {}) if inventory_path.exists() else {}
    if "generation_crop" in scene:
        crop = scene["generation_crop"]
        if not isinstance(crop, dict) or crop.get("source_sha256") != source_sha:
            raise ValueError("Reviewed scene crop source hash does not match the current approved image")
        box = crop.get("box")
        if (not isinstance(box, list) or len(box) != 4 or any(type(n) is not int for n in box)
                or not isinstance(crop.get("reason"), str) or not crop["reason"].strip()):
            raise ValueError("Reviewed scene crop requires an integer box and a review reason")
        probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "json", str(source)],
                               capture_output=True, text=True, check=True, timeout=15)
        dimensions = json.loads(probe.stdout)["streams"][0]
        left, top, right, bottom = box
        if not (0 <= left < right <= dimensions["width"] and 0 <= top < bottom <= dimensions["height"]):
            raise ValueError("Reviewed scene crop box falls outside the approved image")
        target = root / "assets/video_refs" / f"{asset_id}_scene_crop_v1_{source_sha[:12]}_{digest(box)[:12]}.png"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.pending.png")
            try:
                subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-hwaccel", "none",
                                "-i", str(source), "-vf", f"crop={right-left}:{bottom-top}:{left}:{top}:exact=1",
                                "-frames:v", "1", "-threads", "1", str(pending)],
                               check=True, timeout=30, capture_output=True)
                pending.replace(target)
            except (OSError, subprocess.SubprocessError) as exc:
                pending.unlink(missing_ok=True)
                raise ValueError(f"Cannot create the reviewed scene crop for {asset_id}: {exc}") from exc
        return {"asset_id": asset_id, "source_sha256": source_sha,
                "generation_path": str(target.relative_to(root)),
                "generation_sha256": file_hash(target), "variant": "reviewed_scene_crop", "crop_box": box}
    from .character_views import character_asset_ids
    if asset_id not in character_asset_ids(root):
        return {"asset_id": asset_id, "source_sha256": source_sha,
                "generation_path": str(source.relative_to(root)),
                "generation_sha256": source_sha, "variant": "approved_source"}
    job_path = root / "jobs" / f"image_{asset_id}.json"
    prompt = read(job_path).get("prompt", "") if job_path.exists() else ""
    split_sheet = re.search(r"(?:separated|clearly separated).*?(?:face|head|close)", prompt, re.I | re.S)
    try:
        source_name = str(source.relative_to(root))
    except ValueError:
        source_name = str(source)
    if not split_sheet:
        return {"asset_id": asset_id, "source_sha256": source_sha,
                "generation_path": source_name, "generation_sha256": source_sha,
                "variant": "approved_source"}
    size = (camera or {}).get("size", "").lower()
    variant = "portrait" if "close-up" in size else "fullbody"
    target = root / "assets/video_refs" / f"{asset_id}_{variant}_v3_{source_sha[:12]}.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        pending = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.pending.png")
        # Generated design sheets can let the close-up cross the nominal 50%
        # seam. Drop the middle 10% so one H3 reference contains one person.
        width = "if(gt(iw/ih\\,1.3)\\,trunc(iw*0.42/2)*2\\,trunc(iw*0.45/2)*2)"
        x = f"iw-{width}" if variant == "portrait" else "0"
        try:
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(source),
                            "-vf", f"crop={width}:ih:{x}:0", "-frames:v", "1", str(pending)],
                           check=True, timeout=30, capture_output=True)
            pending.replace(target)
        except (OSError, subprocess.SubprocessError) as exc:
            pending.unlink(missing_ok=True)
            raise ValueError(f"无法为人物资产 {asset_id} 创建单主体视频参考图: {exc}") from exc
    return {"asset_id": asset_id, "source_sha256": source_sha,
            "generation_path": str(target.relative_to(root)),
            "generation_sha256": file_hash(target), "variant": variant}


def bound_shot(root, shot):
    """Resolve visual and voice assets into the package that is sent to H3."""
    from .voices import bindings
    # H3 presents reference images in ordinal order and has no separate
    # background channel. Ordinary shots lead with their scene plate; a
    # reviewed single-speaker retake leads with the bound face so the set
    # cannot take over the first frames. Picture ordinals are recomputed below.
    inventory_path = Path(root) / "bible" / "assets.json"
    inventory = {}
    if inventory_path.exists():
        data = read(inventory_path)
        for name, item in data.get("scenes", {}).items():
            inventory[item["id"]] = ("scene", name)
        for name, item in data.get("characters", {}).items():
            inventory[item["id"]] = ("character", name)
        for name, item in data.get("props", {}).items():
            inventory[item["id"]] = ("prop", name)
    refs = list(shot.get("references", []))
    scene_refs = [ref for ref in refs if inventory.get(ref.get("asset_id"), (None,))[0] == "scene"]
    if inventory:
        scene_id = shot.get("scene_id")
        if not scene_id or scene_id not in inventory or inventory[scene_id][0] != "scene":
            raise ValueError(f"{shot['id']}: scene_id={scene_id or '<missing>'} 不存在于场景资产名册")
        declared = [ref for ref in scene_refs if ref.get("asset_id") == scene_id]
        if len(declared) != 1 or len(scene_refs) != 1:
            raise ValueError(f"{shot['id']}: 场景参考必须且只能绑定 scene_id={scene_id}")
        if shot.get("speaker_focus_mode") == "speaker_only":
            speaker_names = {str(line.get("speaker", "")) for line in shot.get("dialogue", [])}
            voice_bank = read(Path(root) / "bible" / "voices.json")
            speaker_ids = {voice_bank[name].get("asset_id") for name in speaker_names
                           if name in voice_bank and voice_bank[name].get("asset_id")}
            speaker_refs = [ref for ref in refs if ref.get("asset_id") in speaker_ids]
            refs = speaker_refs + declared + [ref for ref in refs
                                              if ref not in speaker_refs and ref not in declared]
        else:
            refs = declared + [ref for ref in refs if ref not in declared]
    ordered_shot = copy.deepcopy(shot)
    ordered_shot["references"] = refs
    subject_by_asset = {ref["asset_id"]: f"Subject {index}" for index, ref in enumerate(refs, 1)}
    for actor in ordered_shot.get("blocking_plan", {}).get("actors", []):
        if actor.get("asset_id") in subject_by_asset:
            actor["subject_label"] = subject_by_asset[actor["asset_id"]]
    from .scene_continuity import contract
    ordered_shot["scene_continuity_contract"] = contract(root, ordered_shot)
    speech_bindings = bindings(root, ordered_shot)
    if any(binding.get('offscreen') and binding.get('asset_id') in subject_by_asset
           for binding in speech_bindings):
        raise ValueError('Legacy Ref2VA offscreen speakers must use audio only; remove their visible identity image')
    visual_assets = [generation_reference(root, ref, ordered_shot.get("camera"), ordered_shot, speech_bindings)
                     for ref in refs]
    package = compile_package(root, ordered_shot, visual_assets, speech_bindings)
    return dict(ordered_shot, speech_bindings=speech_bindings, asset_package=package), visual_assets, package


def fingerprint(root, episode, shot, previous_fingerprint=None, review_note=None):
    from .arcreel import content_current
    content_current(root, episode)
    cfg = config(root)
    prompt_shot, visual_assets, package = bound_shot(root, shot)
    hashes = {item["asset_id"]: item["generation_sha256"] for item in visual_assets}
    hashes.update({shot[k]: asset_for(root, shot[k])[1]
                   for k in ("first_frame", "last_frame") if shot.get(k)})
    # Pin the source, full shot contract, models, quality settings and previous take.
    # Keep the empty-note shape byte-for-byte compatible with existing takes;
    # only a real retake note should create a new production fingerprint.
    payload = {"source": read(Path(root) / "book.json")["source_sha256"], "episode": digest(episode),
               "shot": shot, "assets": hashes, "settings": cfg["generation"], "models": cfg["models"],
               "style": cfg["style"], "upstream": cfg["upstream_commit"], "previous": previous_fingerprint,
               "vdn": cfg.get("vdn"), "speech_binding_version": 2,
               "dialogue_audio_prompt_contract_version": 5,
               "dialogue_visual_framing_contract_version": 2,
               "character_presence_contract_version": 1,
               "asset_binding_version": 5, "character_reference_policy_version": 3,
               "asset_package": package,
               "voices": prompt_shot["speech_bindings"],
               "resolved_prompt": h3_prompt(prompt_shot, cfg["style"])}
    # Keep ordinary historical fingerprints byte-compatible. The additional
    # contract is part of the fingerprint only for a real user retake.
    if shot.get("retake_visual_contract") or _speaker_visual_retake(review_note, shot.get("dialogue", [])):
        payload["retake_visual_contract"] = (shot.get("retake_visual_contract")
                                              or "speaker_dominant")
    if review_note:
        payload["review_note"] = str(review_note)
    return digest(payload)


def spatial_fingerprint(base_fingerprint, guide_signature):
    return digest({"base_fingerprint": base_fingerprint, "spatial_guide_signature": guide_signature})


def compile_execution_sheet(root, episode, shot, observed_handoff=None, persist=True, spatial_guide=None):
    """Build the exact reviewable asset-bound contract later sent to H3."""
    cfg = config(root)
    if spatial_guide is None and cfg.get("blender_previs", {}).get("enabled") is True:
        from .blender_previs import planned_guide
        spatial_guide = planned_guide(root, episode, shot, cfg)
    prompt_shot, visual_assets, asset_package = bound_shot(root, shot)
    if spatial_guide:
        prompt_shot["spatial_guide"] = spatial_guide
        asset_package["spatial_guide"] = spatial_guide
        asset_package.setdefault("storyboard", {})["environment_motion"] = spatial_guide.get("motion_cues", [])
    if observed_handoff:
        prompt_shot["handoff_in"] = observed_handoff
    model_prompt = h3_prompt(prompt_shot, cfg["style"])
    unresolved_events = [event for event in asset_package.get("dialogue_event_bindings", [])
                         if event.get("binding_status") == "unresolved"]
    if unresolved_events:
        labels = ", ".join(event.get("event_id", "D?") for event in unresolved_events)
        raise ValueError(f"对白事件缺少完整角色图片/参考音频绑定：{labels}")
    correction = _speaker_review_correction(shot.get("review_note"), shot.get("dialogue", []))
    if correction and shot.get("speaker_focus_mode") not in ("speaker_dominant", "speaker_only"):
        raise ValueError("说话人纠错重拍必须启用 speaker-dominant 构图，禁止沿用双人正面镜头")
    execution_sheet = {
        **asset_package,
        "schema": "h3_asset_bound_execution_v5",
        "episode_id": episode["id"],
        "spatial_guide": spatial_guide,
        "model_input": {
            "engine": "VDN-H3 Turbo" if cfg.get("vdn", {}).get("enabled") else "MiniMax H3",
            "mode": shot["mode"],
            "prompt": model_prompt,
            "prompt_sha256": digest(model_prompt),
            "audio_contract": asset_package.get("audio_contract", {}),
            "required_sections": (["subject_definitions", "summary", "retention_analysis",
                                   "detailed_description", "overall_soundscape", "non_diegetic_music"]
                                  if shot["mode"] == "ref2va" else
                                  ["integrated_multimodal_description", "overall_soundscape",
                                   "non_diegetic_music"]),
        },
        "quality_gate": {
            "exact_bound_asset_count": True,
            "independent_character_view_per_subject": True,
            "turnaround_master_never_sent_to_model": True,
            "single_instance_per_bound_character": True,
            "exact_visible_human_body_count": asset_package.get(
                "visible_body_count", len(asset_package.get("visible_characters", []))),
            "over_shoulder_listener_is_partial_bound_body_only": bool(
                asset_package.get("interaction_contract", {}).get("over_shoulder_foreground_listener_only")),
            "unregistered_humans_forbidden_in_dialogue": True,
            "unregistered_humans_forbidden": True,
            "dialogue_character_whitelist": bool(shot.get("dialogue")),
            "non_dialogue_extras_must_be_silent_and_background_only": False,
            "speaker_audio_one_to_one": True,
            "speaker_picture_binding_exact": all(
                event.get("kind") in ("voiceover", "offscreen_character") or bool(event.get("picture_label"))
                for event in asset_package.get("dialogue_event_bindings", [])),
            "offscreen_character_voice_has_no_picture": all(
                event.get("kind") == "offscreen_character" and event.get("mouth_owner") == "none"
                for event in asset_package.get("dialogue_event_bindings", [])
                if event.get("kind") == "offscreen_character"),
            "speaker_dominant_retake_contract": shot.get("speaker_focus_mode") == "speaker_dominant",
            "identity_binding_table_present": bool(asset_package.get("identity_bindings")),
            "present_time_dialogue_lock": bool(asset_package.get("character_identity_lock", {}).get("present_time_only")),
            "no_flashback_or_apparition": bool(asset_package.get("character_identity_lock", {}).get("no_flashback_or_apparition")),
            "dialogue_only_audio": bool(shot.get("dialogue")),
            "vocal_content_lock": bool(shot.get("dialogue")),
            "dialogue_audio_prompt_contract_version": 5 if shot.get("dialogue") else 3,
            "dialogue_visual_framing_contract_version": 2 if has_visible_dialogue(shot) else 0,
            "speaker_visible_throughout_dialogue_windows": bool(
                asset_package.get("interaction_contract", {}).get("dialogue_framing", {}).get(
                    "speaker_visible_throughout_dialogue_windows")),
            "no_environment_only_cutaway_during_dialogue": bool(
                asset_package.get("interaction_contract", {}).get("dialogue_framing", {}).get(
                    "no_environment_only_cutaway_during_dialogue")),
            "dialogue_internal_cut_policy": asset_package.get("interaction_contract", {}).get(
                "dialogue_framing", {}).get("policy", "not_applicable"),
            "review_note_excluded_from_model_prompt": True,
            "diegetic_only_audio": not bool(shot.get("dialogue")),
            "silent_bound_characters": not has_visible_dialogue(shot),
            "no_dialogue_mouth_movement": not has_visible_dialogue(shot),
            "no_human_voice_when_no_dialogue": not bool(shot.get("dialogue")),
            "bound_character_presence_every_frame": bool(
                asset_package.get("interaction_contract", {}).get("bound_character_presence_every_frame")),
            "no_background_takeover": bool(
                asset_package.get("interaction_contract", {}).get("no_background_takeover")),
            "no_reverse_or_scale_drift": bool(
                asset_package.get("interaction_contract", {}).get("no_reverse_or_scale_drift")),
            "no_environment_only_frame_with_bound_cast": bool(
                asset_package.get("interaction_contract", {}).get("character_presence_required")),
            # Keep old project configs fail-closed on the current compact
            # no-dialogue audio schema; a stale value must not resurrect the
            # long negative prompt that seeded ASR hallucinations.
            "no_dialogue_contract_version": max(3, int(cfg.get("speech_policy", {}).get("no_dialogue_contract_version", 3))),
            "no_dialogue_audio_schema": asset_package.get("audio_contract", {}).get("schema"),
            "no_dialogue_reference_audio_input": asset_package.get("audio_contract", {}).get("reference_audio_input"),
            "professional_camera_execution_present": bool(asset_package.get("camera_execution")),
            "retake_review_note_injected": bool(shot.get("review_note")),
            "speaker_event_binding_version": 1,
            "speaker_review_correction_compiled": bool(correction),
        },
    }
    if shot.get("review_note"):
        execution_sheet["retake_review_note"] = shot["review_note"]
    if correction:
        execution_sheet["speaker_review_correction"] = correction
    if persist:
        path = Path(root) / "execution_sheets" / episode["id"] / f"{shot['id']}.json"
        write(path, execution_sheet)
        execution_sheet["workbench_path"] = str(path.relative_to(root))
    return prompt_shot, visual_assets, execution_sheet, model_prompt


def _production_engine(cfg, model_mode):
    engine_id = cfg.get("video_engine")
    if engine_id is None:
        engine_id = "vdn_h3_turbo" if cfg.get("vdn", {}).get("enabled") else "minimax_h3"
    if engine_id == "vdn_h3_turbo":
        if cfg.get("vdn", {}).get("enabled") is not True:
            raise ValueError("VDN-H3 Turbo 未在项目配置中启用")
        return {"id": engine_id, "name": "VDN-H3 Turbo", "model_filename": cfg["models"][model_mode],
                "vdn_enabled": True, "shift_video": 12.0, "shift_audio": 3.0}
    if engine_id == "fast_h3_omni":
        raise ValueError("FastH3-Omni 已迁移到 FastVideo NVFP4 QAD；请使用 v2 完整章节制作入口")
    if engine_id == "minimax_h3":
        return {"id": engine_id, "name": "MiniMax H3", "model_filename": cfg["models"][model_mode],
                "vdn_enabled": False, "shift_video": 12.0, "shift_audio": 3.0}
    raise ValueError(f"未知视频生成模型：{engine_id}")


def graph(root, episode, shot, take_id, previous=None, stage_assets=False, observed_handoff=None,
          return_package=False, benchmark_engine=None, generation_override=None, spatial_guide=None):
    """Build a Comfy graph.

    ``benchmark_engine`` is deliberately an explicit, isolated override.  It
    never changes the production config or fingerprints and is used only by
    the FastH3 comparison runner.  FastH3-8-Step-V2 is a T2AV distilled
    checkpoint, so the benchmark converts the selected shot to an equivalent
    text-to-audio-video request and does not send production Ref2VA assets.
    """
    cfg = config(root)
    benchmark = benchmark_engine is not None
    if benchmark:
        engine = dict(benchmark_engine)
        if engine.get("model_filename") is None:
            raise ValueError("FastH3 基准缺少 model_filename")
        model_mode = engine.get("model_mode", "fl2va")
        benchmark_shot = copy.deepcopy(shot)
        benchmark_shot.update(mode=model_mode, references=[], first_frame=None, last_frame=None,
                              dialogue=[], speech_bindings=[], asset_package={})
    else:
        model_mode = shot["mode"]
        engine = _production_engine(cfg, model_mode)
        benchmark_shot = shot
    if spatial_guide and model_mode != "ref2va":
        raise ValueError("Blender 时空视频引导当前要求 H3 Ref2VA；FL2VA 镜头不能静默跳过白模")
    generation = dict(cfg["generation"])
    if generation_override:
        generation.update(generation_override)
    width, height = generation["width"], generation["height"]
    if width % 32 or height % 32:
        raise ValueError("生成尺寸须为 32 的倍数")
    delivery = cfg.get("delivery", {})
    native_delivery = (width, height) == (delivery.get("width"), delivery.get("height"))
    if width * 9 != height * 16 and not generation.get("crop_to_delivery") and not native_delivery:
        raise ValueError("生成尺寸须为 16:9，或与交付画布完全一致")
    prefix = (f"benchmarks/fasth3/{engine.get('label', 'engine')}/{shot['id']}/{take_id}"
              if benchmark else f"novel_h3/{episode['id']}/{shot['id']}/{take_id}")
    nodes = {}

    def add(nid, kind, **inputs):
        nodes[str(nid)] = {"class_type": kind, "inputs": inputs}
        return [str(nid), 0]

    model_name = engine.get("model_filename", cfg["models"][model_mode])
    model = add(1, "UNETLoader", unet_name=model_name, weight_dtype="default")
    vdn_enabled = bool(engine.get("vdn_enabled", False))
    if vdn_enabled:
        if generation["steps"] != 8 or cfg["vdn"]["inputs"].get("apply_turbo_adapter") is not True:
            raise ValueError("当前 VDN-H3 使用 8 步蒸馏权重，必须启用 Turbo 并设置 8 步")
        vdn_inputs = cfg["vdn"]["inputs"] if not benchmark else engine.get("vdn_inputs", cfg["vdn"]["inputs"])
        model = add(21, "ApplyVDNH3", model=model, **vdn_inputs)
    clip = add(2, "CLIPLoader", clip_name=cfg["models"]["clip"], type="minimax", device="default")
    vae = add(3, "VAELoader", vae_name=cfg["models"]["video_vae"])
    audio_vae = add(4, "VAELoader", vae_name=cfg["models"]["audio_vae"])
    model = add(5, "MiniMaxH3SigmaShift", model=model,
                shift_video=float(engine.get("shift_video", 12.0)),
                shift_audio=float(engine.get("shift_audio", 3.0)))
    if benchmark:
        model_prompt = h3_prompt(benchmark_shot, cfg["style"])
        prompt_shot, visual_assets = benchmark_shot, []
        execution_sheet = {
            "schema": "h3_asset_bound_execution_v4_benchmark",
            "benchmark_engine": engine,
            "episode_id": episode["id"], "shot_id": shot["id"],
            "source_mode": shot["mode"], "model_mode": model_mode,
            "asset_binding_note": "生产镜头资产不发送至 FastH3 T2AV 基准；仅比较同一镜头文本/时长/种子下的生成速度。",
            "model_input": {"engine": engine.get("label", "FastH3"), "mode": model_mode,
                            "prompt": model_prompt, "prompt_sha256": digest(model_prompt),
                            "scheduler_shift_video": float(engine.get("shift_video", 12.0)),
                            "scheduler_shift_audio": float(engine.get("shift_audio", 3.0)),
                            "steps": generation["steps"]},
        }
    else:
        prompt_shot, visual_assets, execution_sheet, model_prompt = compile_execution_sheet(
            root, episode, shot, observed_handoff=observed_handoff, persist=True,
            spatial_guide=spatial_guide)
        execution_sheet["video_engine"] = {k: engine[k] for k in ("id", "name", "model_filename", "vdn_enabled")}
        execution_sheet["model_input"].update({"engine": engine["name"], "model_filename": model_name,
            "scheduler_shift_video": engine["shift_video"], "scheduler_shift_audio": engine["shift_audio"],
            "steps": generation["steps"]})
        write(Path(root) / "execution_sheets" / episode["id"] / f"{shot['id']}.json", execution_sheet)
    speech_bindings = prompt_shot["speech_bindings"]
    inputs = {"clip": clip, "vae": vae, "prompt": model_prompt,
              "width": width, "height": height, "length": shot["frames"]}

    def image_input(asset_id, resolved=None):
        if resolved:
            p = inside(root, resolved["generation_path"])
            sha = resolved["generation_sha256"]
        else:
            p, sha = asset_for(root, asset_id)
        name = f"novel_h3/{asset_id}_{sha[:12]}{p.suffix}"
        if stage_assets:
            dest = Path(cfg["input_dir"]) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(p, dest)
        return add(100 + len(nodes), "LoadImage", image=name)

    if model_mode == "ref2va" and not benchmark:
        from .ref2va import validate_legacy
        validate_legacy(prompt_shot, model_prompt, require_population=True)
        inputs.update(audio_vae=audio_vae, ref_image_size="match")
        for i, (ref, resolved) in enumerate(zip(prompt_shot["references"], visual_assets)):
            inputs[f"ref_images.ref_image_{i}"] = image_input(ref["asset_id"], resolved)
        for i, binding in enumerate(speech_bindings):
            source = Path(root) / binding["path"]
            name = f"novel_h3/voices/{binding['sha256']}{source.suffix}"
            if stage_assets:
                dest = Path(cfg["input_dir"]) / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            inputs[f"ref_audios.ref_audio_{i}"] = add(100 + len(nodes), "LoadAudio", audio=name)
        if spatial_guide:
            guide_path = inside(root, spatial_guide["path"])
            if file_hash(guide_path) != spatial_guide["sha256"]:
                raise ValueError("Blender 白模引导视频哈希不匹配，拒绝送入 H3")
            guide_name = f"novel_h3/previs/{spatial_guide['sha256'][:16]}.mp4"
            if stage_assets:
                staged = Path(cfg["input_dir"]) / guide_name
                staged.parent.mkdir(parents=True, exist_ok=True)
                if not staged.is_file() or file_hash(staged) != spatial_guide["sha256"]:
                    shutil.copy2(guide_path, staged)
            loaded_video = add(100 + len(nodes), "LoadVideo", file=guide_name)
            frame_sequence = add(100 + len(nodes), "GetVideoComponents", video=loaded_video)
            inputs["ref_videos.ref_video_0"] = frame_sequence
        cond = add(6, "MiniMaxH3ReferenceToVideo", **inputs)
    else:
        for k in ("first_frame", "last_frame"):
            if benchmark_shot.get(k):
                inputs[k] = image_input(benchmark_shot[k])
        cond = add(6, "MiniMaxH3ImageToVideo", **inputs)
    latent = ["6", 1]
    continuing = shot["continuity"] == "continue"
    if continuing and not previous:
        raise ValueError("连续镜头必须指定已验收的前一镜头 latent")
    old = add(7, "MiniMaxH3MotionContextLoadLatent", latent_path=previous or "novel_h3", clip_index=1 if continuing else 0)
    motion = add(8, "MiniMaxH3MotionContext", conditioning=cond, vae=vae, latent=latent,
                 context_length="22", audio_context_length=24, context_latent=old, audio_vae=audio_vae)
    noise = add(9, "RandomNoise", noise_seed=shot["seed"])
    guider = add(10, "BasicGuider", model=model, conditioning=motion)
    sampler = add(11, "KSamplerSelect", sampler_name=generation.get("sampler", "res_multistep"))
    sigmas = add(12, "BasicScheduler", model=model, scheduler=generation.get("scheduler", "simple"), steps=generation["steps"], denoise=1.0)
    sampled = add(13, "SamplerCustomAdvanced", noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=latent)
    add(14, "MiniMaxH3MotionContextSaveLatent", latent=sampled, filename_prefix=prefix + "/clip", clip_index=1)
    images = add(15, "VAEDecode", samples=sampled, vae=vae)
    audio = add(16, "VAEDecodeAudio", samples=sampled, vae=audio_vae)
    # Save untrimmed audio so the seam probe can measure the pinned overlap.
    add(17, "SaveAudio", audio=audio, filename_prefix=prefix + "/untrimmed")
    trimmed = add(18, "MiniMaxH3MotionContextTrim", images=images, audio=audio,
                  trim_frames=["8", 1], fps=24.0, match_tail=True)
    video = add(19, "CreateVideo", images=trimmed, audio=["18", 1], fps=24.0)
    add(20, "SaveVideo", video=video, filename_prefix=prefix + "/video", format="mp4", **{"format.codec": "h264"})
    return (nodes, prefix, execution_sheet) if return_package else (nodes, prefix)


def schema_check(nodes, info):
    errors = []
    for nid, node in nodes.items():
        kind, inputs = node["class_type"], node["inputs"]
        if kind not in info:
            errors.append(f"缺少节点 {kind}")
            continue
        for name, spec in info[kind]["input"].get("required", {}).items():
            if name not in inputs:
                errors.append(f"{kind}.{name}: 缺少必填输入")
        for name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                src = nodes.get(value[0])
                if not src or src["class_type"] not in info or value[1] >= len(info[src["class_type"]]["output"]):
                    errors.append(f"{nid}.{name}: 无效节点连接")
    return errors


def current_takes(root, episode):
    state = load_state(root)
    result, previous = [], None

    def is_current_execution_sheet(take):
        """Reject rendered takes made with an older binding contract.

        Retained speech failures are deliberately reusable across prompt-only
        edits (the retry-limit tests and the product policy depend on this).
        A take is different when its persisted execution sheet predates the
        global identity-binding revision, so only those historical renders
        are excluded here.  Small unit-test fixtures do not have a sheet and
        therefore keep the existing retention semantics.
        """
        sheet = root / "renders" / str(take.get("id", "")) / "h3_execution_sheet.json"
        if not sheet.is_file():
            return True
        try:
            return read(sheet).get("schema") == "h3_asset_bound_execution_v5"
        except (OSError, ValueError, TypeError):
            return False

    def is_migrated_bound_take(take, shot):
        """Accept a rendered take whose persisted fingerprint predates a
        prompt-contract migration, provided its reviewable execution sheet
        and media are already on the current binding schema.

        Fingerprints include the compiled prompt and asset package.  A global
        prompt migration therefore changes the calculated value even when the
        existing video was already rebuilt and its execution sheet was
        migrated.  Treating such a take as missing causes the serial worker to
        restart at the first old shot after every migration.
        """
        if take.get("status") not in ("rendered", "approved") or not take.get("video"):
            return False
        try:
            if file_hash(inside(root, take["video"])) != take.get("video_sha256"):
                return False
            sheet = read(root / "renders" / str(take.get("id", "")) / "h3_execution_sheet.json")
        except (OSError, ValueError, TypeError, KeyError):
            return False
        if (sheet.get("schema") != "h3_asset_bound_execution_v5"
                or sheet.get("episode_id") != episode["id"]
                or sheet.get("shot_id") != shot["id"]):
            return False
        expected_dialogue = [{**{k: line.get(k) for k in ("kind", "speaker", "text")},
                              "offscreen": bool(line.get("offscreen"))}
                             for line in shot.get("dialogue", [])]
        assigned = [{**{k: line.get(k) for k in ("kind", "speaker", "text")},
                     "offscreen": bool(line.get("offscreen"))}
                    for line in take.get("assigned_dialogue", [])]
        if assigned != expected_dialogue:
            return False
        quality = sheet.get("quality_gate", {})
        if quality.get("speaker_event_binding_version") != 1:
            return False
        if shot.get("dialogue"):
            prompt_path = root / "renders" / str(take.get("id", "")) / "prompt.json"
            try:
                prompt = read(prompt_path)
                prompt_text = json.dumps(prompt, ensure_ascii=False)
            except (OSError, ValueError, TypeError):
                return False
            if "DIALOGUE_EVENT_BINDING_LOCK" not in prompt_text:
                return False
        return True

    for shot in episode["shots"]:
        prev_hash = digest({"take": previous["id"], "video": previous.get("video_sha256"), "observed_handoff": previous.get("observed_handoff_out")}) if shot["continuity"] == "continue" and previous else None
        base_fp = fingerprint(root, episode, shot, prev_hash)
        fp = base_fp
        accepted_fingerprints = {base_fp}
        config_path = Path(root) / "config.json"
        cfg = config(root) if config_path.is_file() else {}
        if cfg.get("blender_previs", {}).get("enabled") is True:
            from .blender_previs import planned_guide
            try:
                signature = planned_guide(root, episode, shot, cfg)["signature"]
            except ValueError:
                # Progress and delivery readers must remain available while a
                # later chapter is still missing its scene card. Submission
                # itself remains fail-closed at the chapter readiness gate.
                signature = None
            if signature:
                fp = spatial_fingerprint(base_fp, signature)
                # Completed pre-integration takes remain usable. A missing/new
                # or explicitly requested retake shot gets the new guide.
                accepted_fingerprints.add(fp)
        candidates = [t for t in state["takes"].values() if not t.get("retired") and t["episode"] == episode["id"] and t["shot"] == shot["id"] and t["fingerprint"] in accepted_fingerprints]
        # A user-requested retake has a distinct fingerprint because its
        # review note is part of the prompt. Once rendered, it is nevertheless
        # the current production take and must not be submitted again by the
        # ordinary queue after the priority item is drained. Do not compare its
        # retake fingerprint with the ordinary fingerprint: the deliberate
        # prompt/seed change is exactly what makes it different.
        retakes = [t for t in state["takes"].values()
                   if (not t.get("retired") and t.get("rework")
                       and t.get("episode") == episode["id"] and t.get("shot") == shot["id"]
                       and t.get("status") in ("rendered", "approved") and t.get("video"))]
        valid_retakes = []
        for retake in retakes:
            try:
                if file_hash(inside(root, retake["video"])) == retake.get("video_sha256"):
                    valid_retakes.append(retake)
            except (OSError, ValueError):
                pass
        if valid_retakes:
            valid_retakes.sort(key=lambda x: x.get("created_at", 0))
            candidates = valid_retakes[-1:]
        # A retained speech exception is intentionally reusable after a
        # prompt-only change (for example a pronunciation hint). Match the
        # locked source dialogue and verify the media hash before allowing the
        # queue to pass it; never reuse an unrelated stale render.
        if not candidates:
            expected_dialogue = [{**{k: line.get(k) for k in ("kind", "speaker", "text")},
                                  "offscreen": bool(line.get("offscreen"))}
                                 for line in shot.get("dialogue", [])]
            retained = []
            for take in state["takes"].values():
                if (take.get("retired") or take.get("episode") != episode["id"]
                        or take.get("shot") != shot["id"]
                        or (take.get("speech_retry_exhausted") is not True
                            and take.get("speech_qc_failed_retained") is not True)):
                    continue
                if not is_current_execution_sheet(take):
                    continue
                assigned = [{**{k: line.get(k) for k in ("kind", "speaker", "text")},
                             "offscreen": bool(line.get("offscreen"))}
                            for line in take.get("assigned_dialogue", [])]
                if assigned != expected_dialogue or not take.get("video"):
                    continue
                try:
                    if file_hash(inside(root, take["video"])) != take.get("video_sha256"):
                        continue
                except (OSError, ValueError):
                    continue
                retained.append(take)
            retained.sort(key=lambda x: x.get("created_at", 0))
            candidates = retained[-1:]
        if not candidates:
            # A migrated execution sheet is authoritative for an already
            # rendered take even when its old state fingerprint was calculated
            # before the current prompt contract.  This preserves book order
            # and prevents duplicate renders after a global migration.
            migrated = [t for t in state["takes"].values()
                        if not t.get("retired") and t.get("episode") == episode["id"]
                        and t.get("shot") == shot["id"]
                        and is_migrated_bound_take(t, shot)]
            migrated.sort(key=lambda x: x.get("created_at", 0))
            candidates = migrated[-1:]
        candidates.sort(key=lambda x: x["created_at"])
        take = candidates[-1] if candidates else None
        result.append((shot, fp, take))
        previous = take
    return result


def submit_next(root, episode_id, preview=False, independent_cuts=False, check_preparation=True,
                rework_item=None, single_pass=False):
    from .safety import check_paused, check_shot_budget
    check_paused()
    root = Path(root)
    with locked(root, "submit"):
        from .listening import active_audio
        if active_audio(root, gpu_only=True):
            raise ValueError("本地音频分析正在运行，请等待完成后再生成视频")
        episode = read(episode_path(root, episode_id))
        # The video queue may run while later chapters are still being prepared,
        # but every chapter submission keeps its own strict material gate.
        if check_preparation and episode_id.startswith('chapter_'):
            from .video_control import require_ready
            require_ready(root, episode_id)
        if independent_cuts and (preview or any(s["continuity"] != "cut" for s in episode["shots"])):
            raise ValueError("待审镜头批量生成仅适用于全部独立切镜的章节；连续镜头仍需逐镜验收")
        errors = validate_episode(root, episode)
        if errors:
            raise ValueError("\n".join(errors))
        cfg, state = config(root), load_state(root)
        if state["approvals"].get(episode_id, {}).get("sha256") != digest(episode):
            raise ValueError("分镜没有通过验收，或分镜修改后验收已失效")
        queue = api(cfg["comfy_url"], "/queue")
        if queue["queue_running"] or queue["queue_pending"]:
            raise ValueError("专用 ComfyUI 正忙；先同步正在运行的任务")
        previous = None
        target_shot = rework_item.get("shot") if rework_item else None
        target_found = False
        rows = current_takes(root, episode)
        if rework_item and not any(shot["id"] == target_shot for shot, _, _ in rows):
            raise ValueError(f"重拍目标镜头不存在：{episode_id}/{target_shot}")
        for shot, fp, take in rows:
            if rework_item and shot["id"] != target_shot and not target_found:
                # Establish the prior approved take for a possible continuation
                # before reaching the requested shot. A retake never changes
                # the ordinary queue's current take until its new render exists.
                # The ordinary index intentionally ignores retake fingerprints;
                # for a retake prerequisite, resolve the newest usable take for
                # this shot so a completed prior retake is not mistaken for the
                # old rejected sample.
                if not take or take.get("status") not in ("rendered", "approved"):
                    prior = [candidate for candidate in state["takes"].values()
                             if candidate.get("episode") == episode["id"]
                             and candidate.get("shot") == shot["id"]
                             and not candidate.get("retired")
                             and candidate.get("status") in ("rendered", "approved")
                             and candidate.get("video")]
                    if prior:
                        take = max(prior, key=lambda candidate: candidate.get("created_at", 0))
                if not take or take.get("status") not in ("rendered", "approved"):
                    raise ValueError(f"重拍前置镜头尚未完成：{shot['id']}")
                previous = take
                continue
            if single_pass and take and take.get("status") in ("failed", "cancelled"):
                previous = take
                continue
            if single_pass and take and take.get("status") == "rendered":
                try:
                    intact = (take.get("video") and file_hash(inside(root, take["video"]))
                              == take.get("video_sha256"))
                except (OSError, ValueError):
                    intact = False
                if not intact:
                    raise ValueError(f"{shot['id']} 的已生成候选缺少或未通过完整性绑定；单轮模式不会重拍")
                previous = take
                continue
            if rework_item and shot["id"] == target_shot:
                target_found = True
                retake_shot = _retake_shot_contract(shot, rework_item, root)
                fp = fingerprint(root, episode, retake_shot, None if shot["continuity"] == "cut" else
                                 (digest({"take": previous["id"], "video": previous.get("video_sha256"),
                                         "observed_handoff": previous.get("observed_handoff_out")}) if previous else None),
                                 review_note=rework_item.get("note"))
                if cfg.get("blender_previs", {}).get("enabled") is True:
                    from .blender_previs import planned_guide
                    fp = spatial_fingerprint(fp, planned_guide(root, episode, retake_shot, cfg)["signature"])
                # A retake deliberately bypasses the old rejected/rendered
                # take, while preserving it for audit and review history.
                take = None
            if take and ((take.get("speech_retry_exhausted") is True
                          or take.get("speech_qc_failed_retained") is True)
                         or take["status"] == "approved" or (preview and take["status"] == "rendered" and take.get("visual_review"))
                         or (independent_cuts and take["status"] == "rendered" and take.get("qc", {}).get("passed")
                             and (not cfg.get("speech_policy", {}).get("require_audio_transcription")
                                  or take.get("speech_check", {}).get("passed")))):
                if file_hash(inside(root, take["video"])) != take["video_sha256"]:
                    raise ValueError("已验收的视频被修改，不能继续")
                previous = take
                continue
            if take and take["status"] in ("submitted", "submitting", "rendered"):
                raise ValueError(f"{shot['id']} 的状态是 {take['status']}；请同步或审片，不重复提交")
            if shot["continuity"] == "continue" and (not previous or not (previous["status"] == "approved" or (preview and previous.get("visual_review")))):
                raise ValueError("上一连续镜头未验收，不能自动传播角色或动作错误")
            old = previous["latent"] if shot["continuity"] == "continue" else None
            if old and (not Path(old).is_file() or file_hash(old) != previous["latent_sha256"]):
                raise ValueError("前一镜头 latent 缺失或变化，请恢复原始文件或从自然剪辑点重拍")
            take_id = "t_" + uuid.uuid4().hex[:12]
            check_shot_budget(cfg, shot)
            native_profile, memory_fallback = native_generation(cfg, shot)
            observed = previous.get("observed_handoff_out") if old else None
            retries = sum(t.get('speech_retry') is True and t['episode'] == episode_id
                          and t['shot'] == shot['id'] and t['fingerprint'] == fp
                          for t in state['takes'].values())
            generation_shot = copy.deepcopy(shot)
            generation_shot["seed"] = (shot["seed"] + retries) % (2**64)
            if rework_item:
                generation_shot = _retake_shot_contract(generation_shot, rework_item, root)
                # A user-requested retake must not silently repeat the
                # rejected sample. Review identity fixes also receive a
                # structural speaker-focused composition above.
                attempt = max(1, int(rework_item.get("attempt", 1)))
                seed_material = "|".join((str(shot.get("seed", 0)), str(rework_item.get("id", "")),
                                            str(rework_item.get("note", "")), str(attempt)))
                generation_shot["seed"] = int.from_bytes(
                    hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
                generation_shot.update(review_note=rework_item.get("note"),
                                       rework_source_take_id=rework_item.get("source_take_id"),
                                       rework_request_id=rework_item.get("id"))
            spatial_guide = None
            if cfg.get("blender_previs", {}).get("enabled") is True:
                from .blender_previs import build_guide, planned_guide
                spatial_guide = build_guide(root, episode, generation_shot, cfg)
                expected_signature = planned_guide(root, episode, generation_shot, cfg)["signature"]
                if spatial_guide.get("signature") != expected_signature:
                    raise ValueError("Blender 白模预演在渲染期间发生变化，请重新检查镜头资料")
            nodes, prefix, execution_sheet = graph(
                root, episode, generation_shot, take_id, old, stage_assets=True,
                observed_handoff=observed, return_package=True, generation_override=native_profile,
                spatial_guide=spatial_guide)
            info = api(cfg["comfy_url"], "/object_info")
            errors = schema_check(nodes, info)
            if errors:
                raise ValueError("\n".join(errors))
            take = {"id": take_id, "episode": episode_id, "shot": shot["id"], "fingerprint": fp,
                    "status": "submitting", "created_at": time.time(), "prefix": prefix,
                    "frames": delivered_frames(shot), "expected_width": cfg["generation"]["width"],
                    "expected_height": cfg["generation"]["height"], "native_width": native_profile["width"],
                    "native_height": native_profile["height"], "previous_take": previous["id"] if old else None,
                    "preview_only": preview, "observed_handoff_used": observed}
            if rework_item:
                take.update(rework=True, rework_source_take_id=rework_item.get("source_take_id"),
                            rework_request_id=rework_item.get("id"),
                            review_note=rework_item.get("note"),
                            review_reviewer=rework_item.get("reviewer"))
            selected_engine = _production_engine(cfg, shot["mode"])
            take["generation_profile"] = {"engine": selected_engine["id"],
                                           "engine_name": selected_engine["name"],
                                           "base": selected_engine["model_filename"],
                                           "generation": native_profile,
                                           "requested_generation": cfg["generation"],
                                           "vdn": cfg.get("vdn") if selected_engine["vdn_enabled"] else {"enabled": False}}
            if spatial_guide:
                take["spatial_guide"] = spatial_guide
            if memory_fallback:
                take["memory_fallback"] = {**memory_fallback, "scaled_to": {
                    "width": cfg["generation"]["width"], "height": cfg["generation"]["height"]}}
            take['actual_seed'] = generation_shot['seed']
            take['speech_retry_attempt'] = retries
            take['speaker_event_binding_version'] = 1
            from .voices import bindings
            take["speech_bindings"] = bindings(root, generation_shot)
            # The generation path may place the scene plate first in the H3
            # reference list.  Keep the persisted manifest's Picture ordinal
            # aligned with the exact execution sheet sent to ComfyUI.
            picture_by_asset = {
                item["asset_id"]: int(item["picture_label"].split()[-1])
                for item in execution_sheet.get("visual_assets", [])
            }
            for binding in take["speech_bindings"]:
                if binding.get("asset_id") in picture_by_asset:
                    binding["picture"] = picture_by_asset[binding["asset_id"]]
            take["assigned_dialogue"] = generation_shot.get("dialogue", [])
            write(root / "renders" / take_id / "speech_manifest.json",
                  {"shot": shot["id"], "dialogue": shot.get("dialogue", []),
                   "bindings": take["speech_bindings"]})
            write(root / "renders" / take_id / "h3_execution_sheet.json", execution_sheet)
            write(root / "renders" / take_id / "prompt.json", nodes)
            update_state(root, lambda s: s["takes"].__setitem__(take_id, take))
            # Persist a unique client tag before POST. A network timeout never triggers a blind retry.
            try:
                response = api(cfg["comfy_url"], "/prompt", {"prompt": nodes, "client_id": take_id,
                                                            "extra_data": {"novel_h3_take": take_id}})
            except ValueError as exc:
                update_state(root, lambda s: s["takes"][take_id].update(status="failed", error=str(exc)))
                raise
            update_state(root, lambda s: s["takes"][take_id].update(status="submitted", prompt_id=response["prompt_id"]))
            return load_state(root)["takes"][take_id]
        if single_pass:
            final_rows = current_takes(root, episode)
            statuses = [take.get("status") for _, _, take in final_rows if take]
            complete = all(take and take.get("status") in ("rendered", "approved", "failed", "cancelled")
                           for _, _, take in final_rows)
            if complete:
                return {"status": "single_pass_complete_pending_review", "episode": episode_id,
                        "rendered": sum(status in ("rendered", "approved") for status in statuses),
                        "failed": sum(status in ("failed", "cancelled") for status in statuses)}
        return {"status": "episode_rendered_pending_review" if independent_cuts else "episode_ready", "episode": episode_id}


def sync(root):
    from .media import technical_qc
    root = Path(root)
    cfg, state = config(root), load_state(root)
    history = api(cfg["comfy_url"], "/history")
    queue = api(cfg["comfy_url"], "/queue")
    updates = {}
    for take_id, take in state["takes"].items():
        if take["status"] not in ("submitting", "submitted"):
            continue
        pid = take.get("prompt_id")
        if not pid:
            for item in list(history.values()):
                prompt = item.get("prompt", [])
                if len(prompt) > 3 and prompt[3].get("novel_h3_take") == take_id:
                    pid = prompt[1]
            for item in queue["queue_running"] + queue["queue_pending"]:
                if item[3].get("novel_h3_take") == take_id:
                    pid = item[1]
            if pid:
                updates[take_id] = {"prompt_id": pid, "status": "submitted"}
        record = history.get(pid)
        if not record:
            continue
        result = record.get("status", {})
        write(root / "renders" / take_id / "comfy_history.json", record)
        if result.get("status_str") == "error":
            updates[take_id] = {"status": "failed", "error": result.get("messages", [])}
            continue
        if not result.get("completed"):
            continue
        folder = inside(cfg["output_dir"], take["prefix"])
        videos = sorted(folder.glob("video*.mp4"))
        latent = folder / "clip_00001.safetensors"
        if len(videos) != 1 or not latent.is_file():
            updates[take_id] = {"status": "failed", "error": "完成记录缺少唯一视频或 AV latent"}
            continue
        dest = root / "renders" / take_id / "video.mp4"
        native_width = int(take.get("native_width", take["expected_width"]))
        native_height = int(take.get("native_height", take["expected_height"]))
        if (native_width, native_height) == (take["expected_width"], take["expected_height"]):
            shutil.copy2(videos[0], dest)
        else:
            pending = dest.with_name("video.scaled.pending.mp4")
            try:
                subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(videos[0]),
                                "-map", "0:v:0", "-map", "0:a:0?", "-vf",
                                f"scale={take['expected_width']}:{take['expected_height']}:flags=lanczos,setsar=1",
                                "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
                                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(pending)],
                               check=True, timeout=180, capture_output=True)
                pending.replace(dest)
            except (OSError, subprocess.SubprocessError) as exc:
                pending.unlink(missing_ok=True)
                updates[take_id] = {"status": "failed", "error": f"显存回退视频缩放失败: {exc}"}
                continue
        for p in folder.glob("untrimmed*.flac"):
            shutil.copy2(p, dest.parent / "untrimmed.flac")
        episode = read(episode_path(root, take["episode"]))
        shot = next(row for row in episode["shots"] if row["id"] == take["shot"])
        audio_policy = None
        if not shot.get("dialogue"):
            audio_policy = {"status": "preserved", "policy": "diegetic_only",
                            "reason": "本镜无人物对白；保留模型生成的环境声和动作音效，禁止旁白、配乐和可识别台词。",
                            "video_sha256": file_hash(dest)}
            write(dest.parent / "audio_policy.json", audio_policy)
        report = technical_qc(dest, take["frames"], take["expected_width"], take["expected_height"])
        write(dest.parent / "technical_qc.json", report)
        updates[take_id] = {"status": "rendered" if report["passed"] else "failed",
                            "video": str(dest.relative_to(root)), "video_sha256": file_hash(dest),
                            "latent": str(latent), "latent_sha256": file_hash(latent), "qc": report}
        if audio_policy:
            updates[take_id]["audio_policy"] = audio_policy
    if updates:
        def apply(s):
            for tid, fields in updates.items():
                s["takes"][tid].update(fields)
        update_state(root, apply)
    return updates


REVIEW_ITEMS = ("story", "identity", "performance", "camera", "continuity", "dialogue", "sound", "no_artifacts", "av_sync")


def review_visual(root, take_id, note, closing_state, evidence_path):
    """Permit an explicitly requested rough cut without claiming final audio approval."""
    take = load_state(root)["takes"][take_id]
    if take["status"] != "rendered" or not take.get("qc", {}).get("passed"):
        raise ValueError("视觉粗剪检查只适用于已完成技术检查的待审视频")
    if not note or not closing_state or not inside(root, evidence_path).is_file():
        raise ValueError("请保存实际视觉检查说明、结束状态及检查图片")
    if file_hash(inside(root, take["video"])) != take["video_sha256"]:
        raise ValueError("视频已修改，视觉检查失效")
    update_state(root, lambda s: s["takes"][take_id].update(
        visual_review={"reviewer": "Codex visual sampling", "note": note, "evidence": str(evidence_path),
                       "audio_listening": "pending", "release_approved": False}, observed_handoff_out=closing_state))


def _human_approval(root, take, review):
    from .delivery_policy import require_final_reviews
    checks, reviewer, note = review['checks'], review['reviewer'], review['note']
    if not str(note).strip() or not str(reviewer).strip():
        raise ValueError("请记录审阅意见及实际审阅人")
    if checks.get("av_sync") is not True and checks.get("av_sync") != "not_applicable":
        raise ValueError("请实际观看并听音后勾选音画同步检查（av_sync）；无可见说话时须明确选不适用并说明，旧八项检查或 ASR 不能代替口型审核")
    if re.match(r"^(codex|assistant|agent|automatic|auto)(?:\b|[_ -])", str(reviewer).strip(), re.I):
        raise ValueError("最终批准需要实际人工审核人；Codex 或自动检查不能冒充人工观看和听音")
    if not all(checks.get(k) is True for k in REVIEW_ITEMS if k != 'av_sync'):
        raise ValueError("通过审片需完成九项实际观看/听音检查，不能只凭文件存在")
    if take.get("retired"):
        raise ValueError("该候选已列入重拍并失效，请审核当前候选视频")
    if not take.get("video") or not inside(root, take['video']).is_file() or file_hash(inside(root, take["video"])) != take.get("video_sha256"):
        raise ValueError("视频已变化或缺失，原检查结果失效")
    av_sync = {"status": "not_applicable" if checks['av_sync'] == 'not_applicable' else "passed",
               "method": "human", "reviewer": reviewer, "note": note, "video_examined": True,
               "measurement": "human_viewing_and_listening", "video_sha256": take["video_sha256"],
               "reviewed_at": review["reviewed_at"]}
    gates = require_final_reviews(dict(take, review=review, av_sync_review=av_sync))
    return dict(status="approved", review=review, av_sync_review=av_sync, review_gates=gates,
                approval_method="human_viewing_and_listening", pending_reviews=[],
                review_required=None, retake_review_required=False, release_approved=False)


def review_take(root, take_id, approved, note, reviewer, checks):
    if not str(note).strip() or not str(reviewer).strip():
        raise ValueError("请记录审阅意见及实际审阅人")

    def apply(s):
        take = s["takes"][take_id]
        if take["status"] not in ("rendered", "approved", "rejected"):
            raise ValueError("只有已经完成技术检查的视频可以审片")
        review = {"reviewer": reviewer, "note": note, "checks": dict(checks), "reviewed_at": time.time()}
        if approved:
            take.update(_human_approval(root, take, review))
        else:
            take.update(status="rejected", review=review)
        # Descendants of a rejected latent must not retain acceptance.
        if not approved:
            stale = {take_id}
            changed = True
            while changed:
                changed = False
                for tid, other in s["takes"].items():
                    if tid not in stale and other.get("previous_take") in stale:
                        stale.add(tid)
                        other["status"] = "stale"
                        changed = True
    state = update_state(root, apply)
    take = state["takes"][take_id]
    from .rework_queue import enqueue as enqueue_rework, resolve_shot
    if approved:
        resolve_shot(root, take["episode"], take["shot"])
        from .delivery_policy import maybe_assemble
        maybe_assemble(root, take["episode"])
    else:
        # A user review is the source of truth for a retake. Keep the rejected
        # take and persist the exact note so the serial worker can inject it
        # into the next execution sheet/prompt with higher priority.
        enqueue_rework(root, take, note, reviewer)
    return {"take": take_id, "status": "approved" if approved else "rework_queued"}


def review_chapter(root, episode_id, approved, note, reviewer, checks):
    """Approve every current rendered take in one chapter after one review pass.

    The chapter action is deliberately stricter than a convenience bulk update:
    it resolves the newest take for every shot, requires a complete set of
    rendered videos, re-checks QC and media hashes, and records the same nine
    real viewing/listening checks used by :func:`review_take`.
    """
    if not approved:
        raise ValueError("章节一键验收只支持通过；需重拍请逐条标记")
    if not str(note).strip() or not str(reviewer).strip():
        raise ValueError("请记录章节审阅意见及实际审阅人")
    episode_id = safe_id(episode_id)
    episode = read(episode_path(root, episode_id))
    shot_ids = [shot["id"] for shot in episode.get("shots", [])]
    if not shot_ids:
        raise ValueError("章节没有可验收的镜头")

    review = {"reviewer": reviewer, "note": note, "checks": dict(checks),
              "scope": "chapter", "episode": episode_id, "shot_count": len(shot_ids),
              "reviewed_at": time.time()}

    def apply(s):
        latest = {}
        for take in s["takes"].values():
            if (take.get("retired") or take.get("episode") != episode_id
                    or take.get("shot") not in shot_ids):
                continue
            current = latest.get(take["shot"])
            if current is None or (take.get("created_at", 0), take.get("id", "")) > (current.get("created_at", 0), current.get("id", "")):
                latest[take["shot"]] = take
        missing = [shot_id for shot_id in shot_ids
                   if latest.get(shot_id, {}).get("status") not in ("rendered", "approved")]
        if missing:
            raise ValueError("本章仍有镜头未完成技术检查或待重拍：" + ", ".join(missing))
        updates = {}
        for shot_id in shot_ids:
            take = latest[shot_id]
            updates[take['id']] = _human_approval(root, take, review)
        # Every candidate is validated before any approval is applied.
        for take_id, fields in updates.items():
            s['takes'][take_id].update(fields)
        s.setdefault("approvals", {})[f"chapter:{episode_id}"] = review

    update_state(root, apply)
    from .rework_queue import resolve_shot
    for shot_id in shot_ids:
        resolve_shot(root, episode_id, shot_id)
    from .delivery_policy import maybe_assemble
    maybe_assemble(root, episode_id)
    return {"episode": episode_id, "approved_shots": len(shot_ids), "status": "approved"}


def cancel(root):
    cfg, state = config(root), load_state(root)
    queue = api(cfg["comfy_url"], "/queue")
    active = {tid: t for tid, t in state["takes"].items() if t["status"] in ("submitted", "submitting")}
    owned = {t.get("prompt_id") for t in active.values()} - {None}
    recovered = {}
    for item in queue["queue_running"] + queue["queue_pending"]:
        tid = item[3].get("novel_h3_take") if len(item) > 3 else None
        if tid in active:
            owned.add(item[1])
            recovered[tid] = item[1]
    pending = [x[1] for x in queue["queue_pending"] if x[1] in owned]
    if pending:
        api(cfg["comfy_url"], "/queue", {"delete": pending})
    running = [x[1] for x in queue["queue_running"] if x[1] in owned]
    if running:
        api(cfg["comfy_url"], "/interrupt", {})
    canceled = set(pending + running)
    def apply(s):
        for tid, take in s["takes"].items():
            if tid in recovered:
                take["prompt_id"] = recovered[tid]
            if take.get("prompt_id") in canceled:
                take["status"] = "canceled"
    update_state(root, apply)
    return {"canceled_prompt_ids": list(canceled), "retained_outputs": True}
