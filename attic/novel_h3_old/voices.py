"""Resolve speech to explicit picture and immutable voice references."""
from pathlib import Path
from .project import read, inside, file_hash


def bindings(root, shot):
    lines = shot.get("dialogue", [])
    if not lines:
        return []
    cfg_path = Path(root) / "config.json"
    cfg = read(cfg_path) if cfg_path.exists() else {}
    local_postdub = (cfg.get("speech_policy", {}).get("dialogue_audio_source")
                     == "qwen3_tts_local_postdub")
    if shot.get("mode") != "ref2va" and not (shot.get("mode") == "fl2va" and local_postdub):
        raise ValueError("有对白的镜头必须使用支持声音参考的 Ref2VA")
    if cfg.get("speech_policy", {}).get("dialogue_only") and any(
            line.get("kind") == "voiceover" for line in lines):
        raise ValueError("当前项目旁白仅作画面参考，禁止绑定旁白声音")
    bank = read(Path(root) / "bible/voices.json")
    inventory_path = Path(root) / "bible/assets.json"
    characters = read(inventory_path).get("characters", {}) if inventory_path.exists() else None
    result = []
    speaker_modes = {}
    for line in lines:
        name = line["speaker"]
        if name not in bank:
            raise ValueError(f"说话人 {name} 未登记声音，禁止猜测或回退到旁白")
        entry = bank[name]
        narrator = line.get("kind") == "voiceover"
        offscreen = line.get("offscreen") is True
        if narrator and offscreen:
            raise ValueError(f"{name}: 旁白与画外角色对白不能混用")
        collective = entry.get("collective") is True
        if narrator != (entry.get("asset_id") is None) and not collective:
            raise ValueError(f"{name}: 角色对白与旁白身份不一致")
        if not narrator and not collective and characters is not None and characters.get(name, {}).get("id") != entry["asset_id"]:
            raise ValueError(f"{name}: 音频绑定的角色 ID 与资产名册不一致")
        if any(b["speaker"] == name for b in result):
            continue
        path = inside(root, entry["path"])
        if not entry.get("approved") or file_hash(path) != entry["sha256"]:
            raise ValueError(f"{name}: 声音参考未审阅或文件已变化")
        mode = "voiceover" if narrator else "offscreen" if offscreen else "visible"
        if name in speaker_modes and speaker_modes[name] != mode:
            raise ValueError(f"{name}: 同一镜头不能混用画外与画内说话绑定")
        speaker_modes[name] = mode
        picture = None
        if not narrator and not offscreen and not collective:
            matches = [i for i, ref in enumerate(shot.get("references", []), 1)
                       if ref["asset_id"] == entry["asset_id"]]
            if len(matches) != 1:
                raise ValueError(f"{name}: 必须有且仅有一张对应角色参考图")
            picture = matches[0]
        result.append(dict(entry, speaker=name, picture=picture, offscreen=offscreen,
                           audio=len(result) + 1, speaker_label=f"S{len(result) + 1}"))
    if len(result) > 3:
        raise ValueError("H3 最多支持三个声音参考，请拆分对白镜头")
    return result
