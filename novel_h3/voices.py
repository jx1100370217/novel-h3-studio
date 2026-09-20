"""Resolve speech to explicit picture and immutable voice references."""
from pathlib import Path
from .project import read, inside, file_hash


def bindings(root, shot):
    lines = shot.get("dialogue", [])
    if not lines:
        return []
    if shot.get("mode") != "ref2va":
        raise ValueError("有对白的镜头必须使用支持声音参考的 Ref2VA")
    cfg_path = Path(root) / "config.json"
    cfg = read(cfg_path) if cfg_path.exists() else {}
    if cfg.get("speech_policy", {}).get("dialogue_only") and any(
            line.get("kind") == "voiceover" for line in lines):
        raise ValueError("当前项目旁白仅作画面参考，禁止绑定旁白声音")
    bank = read(Path(root) / "bible/voices.json")
    inventory_path = Path(root) / "bible/assets.json"
    characters = read(inventory_path).get("characters", {}) if inventory_path.exists() else None
    result = []
    for line in lines:
        name = line["speaker"]
        if name not in bank:
            raise ValueError(f"说话人 {name} 未登记声音，禁止猜测或回退到旁白")
        entry = bank[name]
        narrator = line.get("kind") == "voiceover"
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
        picture = None
        if not narrator and not collective:
            matches = [i for i, ref in enumerate(shot.get("references", []), 1)
                       if ref["asset_id"] == entry["asset_id"]]
            if len(matches) != 1:
                raise ValueError(f"{name}: 必须有且仅有一张对应角色参考图")
            picture = matches[0]
        result.append(dict(entry, speaker=name, picture=picture,
                           audio=len(result) + 1, speaker_label=f"S{len(result) + 1}"))
    if len(result) > 3:
        raise ValueError("H3 最多支持三个声音参考，请拆分对白镜头")
    return result
