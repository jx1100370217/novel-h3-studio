"""Source-grounded screenplay and shot-continuity contracts for H3 chapters."""
from __future__ import annotations

VERSION = "cinematic_storyboard_v2"
MAX_H3_FRAMES = 362  # H3 accepts the 17k+5 grid; its top grid point is 15.08 s at 24 fps.
CONTENT_SHOT_FIELDS = {
    "cinematic_storyboard_version", "editorial_purpose", "dramatic_function",
    "scene_goal", "turning_point", "story_beat_id", "source_fact_ids",
}
SHOT_FIELDS = {
    "sequence_id", "beat_function", "state_in", "state_out", "screen_direction",
    "axis_id", "transition", "blocking_plan", "composition", "action_beats",
}


AUTHORING_RULES = """\
分层创作：原文事实与人物对白 → 有因果的场景节拍 → 可拍摄的镜头执行单 → 资产绑定和模型提示词。
正式剧本的每个镜头须写 cinematic_storyboard_version=cinematic_storyboard_v2、story_beat_id、source_fact_ids、editorial_purpose、dramatic_function、scene_goal 和 turning_point。剧本层须有场景目标、阻力/新信息、转折或后果；每一镜认领具体原文段落和一个连续可演的动作节拍。不得把原文事实改写成未发生的视觉事件；对白逐字保留，旁白只作画面依据。
镜头层必须声明场景/地点、在场角色及精确数量、道具状态、画面开始/结束状态、演员走位与朝向、屏幕运动方向、剪辑/续接理由、景别/焦距/机位/单一有动机的运镜。对白镜头保持说话者可见、听者闭口、同一说话者跨镜保持同一场景/轴线/视线方向；长对白按语义分段，不能为填时长重复动作或对白。动作时间段按可见状态转变划分，不按固定帧数机械切段；连续动作只写一次并覆盖其真实持续时间，静止等待可用较长的单一时段。
入场、到达、落座、起身、交接等必须使用明确的起点→路径→终点；不得用“到达/走入/登场”代替路径。群戏按同一空间调度，进入/离开画面必须可追踪。静默转场按信息量定时，通常 2–4 秒；动作剧情按动作完成时间；任何镜头不超过 15 秒。
环境动作也必须可视化建模：雷光、瓦片坠落、水浪推进、山体裂开、碎石滑落、尘土扩散、光轨下降等，要在动作节拍中写清对象、起点、方向、终点和物理后果；只写在文字里、白模仍保持静止的动作不得进入正式镜头。环境动作的尺度必须在所选景别中可辨，并用连续而明确的运动路径表达，不把一次事件拆成反复发生。
H3 提示词仅使用执行单绑定的图片/音频/白模标签；说话人、角色图片、参考声音一一绑定。源文、美术注释和执行单元数据不能作为语音输入。Blender 白模须展示精确角色数、标记点、路线、屏幕方向、镜头路径、首尾状态和所有关键环境动作的时间/轨迹；H3 必须跟随这些动作的方向和时序。
"""


QUALITY_STANDARD = {
    "story": ["source_faithful", "cause_effect", "visible_turn_or_consequence", "no_filler_repetition"],
    "coverage": ["one_source_beat_per_shot", "exact_dialogue", "speaker_and_voice_match", "all_required_assets_bound"],
    "continuity": ["stable_location", "axis_and_eyelines", "screen_direction", "actor_count", "prop_state", "action_handoff", "environment_motion_path"],
    "camera": ["motivated_shot_size", "motivated_lens", "single_physical_move", "subject_visible_and_readable"],
    "render": ["no_unbound_duplicate_or_missing_cast", "no_empty_set_during_bound_cast", "no_reverse_motion", "no_unlisted_human_voice", "dialogue_intelligible", "chapter_cut_coherent"],
}


def fit_action_beats(beats: list[dict], total_frames: int) -> list[dict]:
    if not beats or total_frames <= 0:
        return []
    # Collapse adjacent duplicate instructions before retiming. Splitting one
    # continuous action into short intervals with the same imperative made H3
    # restart or replay the action at each boundary.
    authored = []
    for row in beats:
        action = str(row.get("action") or row.get("description") or "").strip()
        weight = max(1, int(row.get("end_frame", 0)) - int(row.get("start_frame", 0)))
        if authored and action == authored[-1]["action"]:
            authored[-1]["weight"] += weight
        else:
            authored.append({"row": row, "action": action, "weight": weight})
    weights = [item["weight"] for item in authored]
    total_weight = sum(weights)
    result, cursor = [], 0
    for index, item in enumerate(authored):
        beat, weight = item["row"], item["weight"]
        end = total_frames if index == len(authored) - 1 else round(sum(weights[:index + 1]) * total_frames / total_weight)
        end = max(cursor + 1, min(total_frames, end))
        action = item["action"] or "Continue the authored physical action."
        result.append({**beat, "start_frame": cursor, "end_frame": end, "action": action})
        cursor = end
    return result


def fit_timeline_beats(beats: list[dict], total_frames: int) -> list[dict]:
    """Retime meaningful visual stages without repeating an instruction."""
    if not beats or total_frames <= 0:
        return []
    authored = []
    for row in beats:
        description = str(row.get("description", "")).strip()
        weight = max(1, int(row.get("end_frame", 0)) - int(row.get("start_frame", 0)))
        if authored and description == authored[-1]["description"]:
            authored[-1]["weight"] += weight
        else:
            authored.append({"row": row, "description": description, "weight": weight})
    weights = [item["weight"] for item in authored]
    total_weight = sum(weights)
    result, cursor = [], 0
    for index, item in enumerate(authored):
        end = total_frames if index == len(authored) - 1 else round(sum(weights[:index + 1]) * total_frames / total_weight)
        end = max(cursor + 1, min(total_frames, end))
        result.append({**item["row"], "start_frame": cursor, "end_frame": end,
                       "description": item["description"] or "Continue the authored visual action without restarting."})
        cursor = end
    return result


def validate_scene_content(scene: dict, source_paragraphs: dict, assets: dict) -> list[str]:
    """Fail closed on source linkage, exact speaker binding and authored beat shape."""
    sid = scene.get("scene_id", "<unknown>")
    errors = []
    source_ids = scene.get("source_ids", [])
    source_text = scene.get("source_text", "")
    if not source_ids or any(pid not in source_paragraphs for pid in source_ids):
        errors.append(f"{sid}: 缺少有效原文段落引用")
    elif not any(source_text and source_text in source_paragraphs[pid].get("text", "") for pid in source_ids):
        errors.append(f"{sid}: 原文证据不是引用段落中的逐字内容")
    if not scene.get("scene_description"):
        errors.append(f"{sid}: 缺少可拍摄场景描述")
    if scene.get("cinematic_storyboard_version") == VERSION:
        for field in CONTENT_SHOT_FIELDS - {"cinematic_storyboard_version", "source_fact_ids"}:
            if not scene.get(field):
                errors.append(f"{sid}: 缺少叙事节拍字段 {field}")
        if not scene.get("source_fact_ids"):
            errors.append(f"{sid}: 缺少可追溯的原文事实编号")
        elif not set(scene.get("source_fact_ids", [])) <= set(source_ids):
            errors.append(f"{sid}: 原文事实编号必须来自本镜头绑定的原文段落")
    cast = scene.get("characters_in_scene", [])
    if len(cast) != len(set(cast)):
        errors.append(f"{sid}: 角色资产重复绑定")
    for name in cast:
        if name not in assets.get("characters", {}):
            errors.append(f"{sid}: 未登记角色 {name}")
    for name in scene.get("scenes", []):
        if name not in assets.get("scenes", {}):
            errors.append(f"{sid}: 未登记场景 {name}")
    for name in scene.get("props", []):
        if name not in assets.get("props", {}):
            errors.append(f"{sid}: 未登记道具 {name}")
    speaker_names = {line.get("speaker") for line in scene.get("utterances", []) if line.get("kind") == "dialogue"}
    if not speaker_names <= set(cast):
        errors.append(f"{sid}: 每位对白说话人必须绑定为在场角色")
    if not scene.get("dramatic_function"):
        errors.append(f"{sid}: 缺少此镜的叙事作用")
    return errors


def validate_shot(scene: dict, shot: dict) -> list[str]:
    sid = shot.get("id", "<unknown>")
    errors = []
    missing = SHOT_FIELDS - set(shot)
    if missing:
        errors.append(f"{sid}: 缺少影视连续性字段 {', '.join(sorted(missing))}")
        return errors
    if not shot["sequence_id"] or not shot["beat_function"] or not shot["state_in"] or not shot["state_out"]:
        errors.append(f"{sid}: 叙事节拍/首尾状态不能为空")
    if not shot["axis_id"] or not shot["screen_direction"]:
        errors.append(f"{sid}: 必须声明场景轴线和屏幕运动方向")
    delivered_frames = shot.get("frames", 0) - (22 if shot.get("continuity") == "continue" else 0)
    if delivered_frames <= 0 or shot.get("frames", 0) > MAX_H3_FRAMES:
        errors.append(f"{sid}: 交付时长必须大于 0，且 H3 输入不得超过 {MAX_H3_FRAMES} 帧")
    dialogue_speakers = {line.get("speaker") for line in shot.get("dialogue", []) if line.get("kind") == "dialogue"}
    cast_ids = {ref.get("asset_id") for ref in shot.get("references", [])
                if str(ref.get("asset_id", "")).startswith("character_") or ref.get("asset_id") == "jade_emperor"}
    if dialogue_speakers and not cast_ids:
        errors.append(f"{sid}: 有对白的镜头没有可见绑定角色")
    blocking = shot.get("blocking_plan", {})
    expected = blocking.get("expected_actor_count")
    actors = blocking.get("actors", [])
    actor_ids = [actor.get("asset_id") for actor in actors]
    if len(actor_ids) != len(set(actor_ids)):
        errors.append(f"{sid}: 白模角色清单存在重复资产")
    if set(actor_ids) != cast_ids:
        errors.append(f"{sid}: 白模角色清单必须与角色图片绑定逐个对应")
    if expected != len(actors):
        errors.append(f"{sid}: 白模演员数量与走位清单不一致")
    expected_bodies = sum(int(actor.get("instances", 1)) for actor in actors)
    if blocking.get("expected_body_count", expected_bodies) != expected_bodies:
        errors.append(f"{sid}: 白模可见人物总数与群体资产实例数不一致")
    if expected != len(scene.get("characters_in_scene", [])):
        errors.append(f"{sid}: 执行单演员数与剧本角色数不一致")
    for actor in actors:
        instances = actor.get("instances", 1)
        if type(instances) is not int or instances < 1:
            errors.append(f"{sid}: 群体资产实例数必须是正整数")
        path = actor.get("path", [])
        frames = [point.get("frame") for point in path]
        if any(type(frame) is not int for frame in frames) or frames != sorted(set(frames)):
            errors.append(f"{sid}: 演员走位关键帧必须递增且不能重复")
        for point in path:
            position = point.get("position", {})
            if not all(type(position.get(axis)) in (int, float) for axis in ("x", "y", "z")):
                errors.append(f"{sid}: 演员走位点必须含 x/y/z 坐标")
                break
    if not blocking.get("environment_only_allowed") and expected and any(not actor.get("visible_throughout", True) for actor in actors):
        errors.append(f"{sid}: 绑定角色必须持续可见，除非剧本明确写明出画")
    if not shot.get("action_beats") or not isinstance(shot["action_beats"], list):
        errors.append(f"{sid}: 缺少按时间展开的动作节拍")
    else:
        cursor = 0
        previous_action = None
        for beat in shot["action_beats"]:
            if beat.get("start_frame") != cursor or beat.get("end_frame", 0) <= cursor or not beat.get("action"):
                errors.append(f"{sid}: 动作节拍有空缺、重叠或空动作")
                break
            action = str(beat.get("action", "")).strip()
            if action == previous_action:
                errors.append(f"{sid}: 相邻动作节拍重复；同一连续动作只能描述一次，不能在时间边界重新下达")
                break
            previous_action = action
            cursor = beat["end_frame"]
        expected_frames = shot.get("frames", 0) - (22 if shot.get("continuity") == "continue" else 0)
        if cursor != expected_frames:
            errors.append(f"{sid}: 动作节拍必须完整覆盖交付帧")
    return errors


def h3_instruction(shot: dict) -> str:
    """Compact, positive visual control text from the authored shot contract."""
    plan = shot.get("blocking_plan", {})
    rows = []
    for actor in plan.get("actors", []):
        path = actor.get("path", [])
        route = " -> ".join(str(point.get("mark") or point.get("position")) for point in path)
        count = int(actor.get("instances", 1))
        cardinality = f"exactly {count} members of this registered group" if count > 1 else "exactly one registered body"
        visibility = "visible from first to last frame" if actor.get("visible_throughout", True) else "may leave frame only on the authored route"
        rows.append(f"{actor.get('subject_label', actor.get('asset_id'))}: {cardinality}; {visibility}; "
                    f"{route or actor.get('mark', 'hold assigned mark')}")
    visible_bodies = sum(int(actor.get("instances", 1)) for actor in plan.get("actors", []))
    state = f"Entry state: {shot.get('state_in')}. Exit state: {shot.get('state_out')}."
    framing = shot.get("composition", {})
    frame_text = "; ".join(f"{k}={v}" for k, v in framing.items() if v not in (None, "", [], {}))
    beat_rows = []
    for beat in shot.get("action_beats", []):
        beat_rows.append(
            f"{beat.get('start_frame', 0)}-{beat.get('end_frame', 0)}f: {beat.get('action', '')}"
        )
    return (
        f"CINEMATIC_SHOT_CONTRACT {VERSION}. Sequence={shot.get('sequence_id')}; beat={shot.get('beat_function')}; "
        f"axis={shot.get('axis_id')}; screen_direction={shot.get('screen_direction')}; transition={shot.get('transition')}. "
        f"{state} Blocking: {' | '.join(rows) if rows else 'no foreground actors are bound'}; "
        f"exact visible registered body count={visible_bodies}. "
        f"Composition: {frame_text or 'protect the declared primary subject and location anchors'}. "
        f"Action progression: {' | '.join(beat_rows) if beat_rows else 'one authored action, no filler beats'}. "
        "The authored action and bound references are the only visual authority. Execute one readable action progression with a clear start, change and settled end; "
        "preserve actor identity/count, relative scale, eyelines, geography and prop ownership through every frame. "
        "A registered group may appear only at its explicitly stated cardinality; do not create a second group or duplicate a member. "
        "Camera movement must follow the stated motivation and stay on the declared axis."
    )
