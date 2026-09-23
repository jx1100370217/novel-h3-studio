"""ArcReel content contracts adapted to the local H3 executor.

This is an independent adapter, not an ArcReel provider plugin. Keep the vendor
checkout unchanged; export its DramaEpisodeScript shape plus an H3 sidecar.
"""
import copy
from pathlib import Path
import time

from .project import read, write, digest, safe_id, load_state, update_state
from .director import frames_for, validate_episode, image_job, h3_prompt
from .storyboard_design import AUTHORING_RULES, SHOT_FIELDS, fit_action_beats, validate_scene_content, validate_shot, VERSION

BUCKETS = {"characters": "character", "scenes": "scene", "props": "prop"}
CONTENT_FIELDS = {"scene_id", "duration_seconds", "segment_break", "characters_in_scene",
                  "scenes", "props", "scene_description", "utterances", "source_text", "needs_replan",
                  "voice_groups", "visual_narration", "editorial_purpose", "dramatic_function",
                  "scene_goal", "turning_point", "story_beat_id", "source_fact_ids",
                  "source_ids", "cinematic_storyboard_version"}
H3_FIELDS = {"location_id", "mode", "continuity", "seed", "hold_frames", "first_frame", "last_frame",
             "references", "dramatic_function", "action", "camera", "handoff_in", "handoff_out",
             "timeline", "soundscape", *SHOT_FIELDS}


def inventory(root):
    path = Path(root) / "bible/assets.json"
    return read(path) if path.exists() else {key: {} for key in BUCKETS}


def evidence_check(paragraphs, source_ids, quote):
    if not source_ids or not set(source_ids) <= set(paragraphs):
        raise ValueError("资产或内容规划缺少有效原文段落")
    if not quote or not any(quote in paragraphs[pid]["text"] for pid in source_ids):
        raise ValueError("source_text / evidence 必须是对应原文中的逐字摘录")


def save_inventory(root, value):
    paragraphs = {p["id"]: p for p in read(Path(root) / "paragraphs.json")}
    names, ids = set(), set()
    for bucket in BUCKETS:
        for name, item in value.get(bucket, {}).items():
            aid = safe_id(item["id"])
            if not name or name in names or aid in ids or "/" in name:
                raise ValueError("角色、场景、道具名称及资产 ID 必须唯一，主名称不能含 /")
            names.add(name); ids.add(aid)
            evidence_check(paragraphs, item["source_ids"], item["evidence"])
            if not item.get("source_facts") or not item.get("design_description"):
                raise ValueError("资产必须分开填写原文事实与美术设计，未知外貌不得写成事实")
            if bucket == "characters" and item.get("gender") not in {"男", "女", "非人形", "群体", "未知"}:
                raise ValueError("角色资产必须登记性别：男、女、非人形、群体或未知")
            if item.get("derivatives") and bucket != "characters":
                raise ValueError("当前仅角色支持衍生形象")
            for derivative, change in item.get("derivatives", {}).items():
                did = safe_id(change["id"])
                if did in ids or "/" in derivative or not change.get("description"):
                    raise ValueError("衍生角色需要独立 ID 和相对基础角色的修改说明")
                ids.add(did)
    write(Path(root) / "bible/assets.json", value)
    return {key: len(value.get(key, {})) for key in BUCKETS}


def create_asset_jobs(root):
    assets = inventory(root)
    style = read(Path(root) / "config.json")["style"]
    from .director import gender_prompt
    jobs = []
    for bucket, role in BUCKETS.items():
        for name, item in assets[bucket].items():
            layout = {"character": "One full-body three-quarter portrait and a clearly separated face close-up of the SAME identity, neutral pose, plain background. No labels.",
                      "scene": "One wide establishing view, coherent geography and human scale. No people or collage.",
                      "prop": "One clearly isolated hero prop, three-quarter view, neutral studio lighting and plain background. No letters or labels."}[role]
            prompt = (f"{style}\nAsset: {name}.\nSource facts: {item['source_facts']}\n"
                      f"Art direction (adaptation choices, not textual facts): {item['design_description']}\n{layout}")
            if role == "character":
                prompt += (f"\nVisual-only gender lock: {gender_prompt(item.get('gender', '未知'))}. "
                           "Never speak or subtitle this metadata.")
            identity_ref = item.get("identity_reference_asset_id")
            if identity_ref:
                prompt += "\nPreserve the exact face and identity of the supplied reference; change only the role costume."
            job = image_job(root, item["id"], prompt,
                            references=[identity_ref] if identity_ref else [], role=role)
            jobs.append(job["id"])
            for name2, derivative in item.get("derivatives", {}).items():
                job = image_job(root, derivative["id"],
                                f"Edit the reference character {name} into the {name2} appearance. "
                                f"Preserve the exact face, age, proportions and identity. Change only: {derivative['description']}. {layout}",
                                references=[item["id"]], role="character_derivative")
                jobs.append(job["id"])
    return {"image_jobs": jobs, "provider": "ChatGPT 5x / Images 2.5 via current Codex image_gen only"}


def resolve_reference(assets, bucket, name):
    base, _, derivative = name.partition("/")
    item = assets[bucket].get(base)
    if not item:
        raise ValueError(f"未登记的 {bucket} 资产：{name}")
    if derivative:
        if bucket != "characters" or derivative not in item.get("derivatives", {}):
            raise ValueError(f"未登记的角色衍生形象：{name}")
        return item["derivatives"][derivative]["id"]
    return item["id"]


def plan_path(root, episode_id):
    return Path(root) / "content_plans" / f"{safe_id(episode_id)}.json"


def check_speaker_audit(root, plan):
    if not read(Path(root) / "config.json").get("speech_policy", {}).get("require_source_attribution"):
        return
    audit = plan.get("speaker_audit", {})
    if audit.get("status") != "reviewed" or not audit.get("reviewer"):
        raise ValueError("剧本必须逐句核对原文说话人后才能生成")
    for scene in plan["script"]["scenes"]:
        records = audit.get("scenes", {}).get(scene["scene_id"], [])
        if len(records) != len(scene["utterances"]):
            raise ValueError("对白说话人审阅记录不完整")
        for line, record in zip(scene["utterances"], records):
            if any(line[k] != record.get(k) for k in ("kind", "speaker", "text")) or not record.get("reason"):
                raise ValueError("对白或说话人已变化，必须重新对照原文审阅")


def save_content(root, plan):
    """Accept ArcReel DramaNormalizedScript with a separate source binding map."""
    if read(Path(root) / "config.json").get("speech_policy", {}).get("dialogue_only"):
        from .dialogue_only import content
        plan = content(plan)
    # Entrance/reaction inserts have a short editorial target, not a global
    # minimum or a cap on substantive action scenes. Dialogue remains content timed.
    for scene in plan["script"]["scenes"]:
        if not scene.get("utterances") and scene.get("editorial_purpose") in ("entrance", "reaction", "transition"):
            scene["duration_seconds"] = min(scene["duration_seconds"], 4)
    # Normalize every saved dialogue workorder at authoring time. This keeps
    # future plans on the content-based rule instead of requiring a later
    # migration pass; silent scenes retain their visual action duration.
    from .timing import retime_content_plan
    plan, _, blocked_timing = retime_content_plan(plan)
    if blocked_timing:
        details = '；'.join(f"{item.get('scene_id')}: {item.get('reason')}" for item in blocked_timing)
        raise ValueError('对白镜头超过约15秒，必须先按语义拆镜：' + details)
    revision = read(Path(root) / "config.json").get("creative_revision")
    if revision and plan.get("creative_revision") != revision:
        raise ValueError("当前剧本已失效，请重新编写剧本")
    safe_id(plan["id"])
    check_speaker_audit(root, plan)
    if not plan.get("dramatic_question") or not plan.get("turning_point"):
        raise ValueError("内容规划必须有戏剧问题和转折")
    script = plan["script"]
    if not script.get("title") or not script.get("scenes"):
        raise ValueError("ArcReel 内容规划缺少标题或分镜")
    paras = {p["id"]: p for p in read(Path(root) / "paragraphs.json")}
    assets, ids = inventory(root), set()
    strict_assets = read(Path(root) / "config.json").get("asset_policy", {}).get("require_every_scene", False)
    for scene in script["scenes"]:
        sid = safe_id(scene["scene_id"])
        if sid in ids or set(scene) - CONTENT_FIELDS:
            raise ValueError("内容层分镜 ID 重复或混入视觉提示词 / 未知字段")
        ids.add(sid)
        if type(scene["duration_seconds"]) is not int or not 1 <= scene["duration_seconds"] <= 15:
            raise ValueError("H3 内容单元采用 1–15 秒的编辑目标；较长 ArcReel 单元需先拆分")
        if not scene.get("scene_description") or scene.get("needs_replan"):
            raise ValueError("画面描述缺失或该分镜仍需重新规划")
        if (plan.get("release_role", "episode") == "episode"
                and scene.get("cinematic_storyboard_version") != VERSION):
            raise ValueError(f"{sid}: 正式剧本必须使用 {VERSION} 并补齐叙事节拍与连续性字段")
        content_errors = validate_scene_content(scene, paras, assets)
        if content_errors:
            raise ValueError("\n".join(content_errors))
        if strict_assets and not any(scene.get(field) for field in ("characters_in_scene", "scenes", "props")):
            raise ValueError("资产门禁开启：正式分集每个镜头至少绑定一个已登记人物、场景或道具")
        evidence_check(paras, plan["source_map"].get(sid, []), scene.get("source_text"))
        for bucket, field in (("characters", "characters_in_scene"), ("scenes", "scenes"), ("props", "props")):
            for name in scene.get(field, []):
                resolve_reference(assets, bucket, name)
        speakers = {n.split("/")[0] for n in scene["characters_in_scene"]}
        speakers.update(scene.get("voice_groups", []))
        for utterance in scene["utterances"]:
            if set(utterance) != {"kind", "speaker", "text"} or not utterance["text"]:
                raise ValueError("发声内容必须包含 kind、speaker、text")
            if utterance["kind"] == "dialogue":
                if utterance["speaker"] not in speakers:
                    raise ValueError("角色台词必须绑定出场基础角色，衍生形象沿用基础角色发声身份")
            elif utterance["kind"] != "voiceover" or utterance["speaker"] not in (None, "旁白", "作者旁白"):
                raise ValueError("画外旁白必须明确为旁白或作者旁白，不能替代角色对白")
    if set(plan["source_map"]) != ids:
        raise ValueError("原文映射必须与内容分镜一一对应")
    write(plan_path(root, plan["id"]), plan)
    return {"id": plan["id"], "content_sha256": digest(plan), "scenes": len(ids)}


def approve_content(root, episode_id, reviewer, note):
    plan = read(plan_path(root, episode_id))
    save_content(root, plan)
    # save_content normalizes the plan (including semantic dialogue splitting)
    # before writing it.  Read that canonical object back so the approval
    # fingerprint pins exactly what compile_visual will consume; hashing the
    # pre-normalized object leaves a false "content not reviewed" gate.
    plan = read(plan_path(root, episode_id))
    if not reviewer or not note:
        raise ValueError("请记录内容审阅人和审阅结论")
    update_state(root, lambda s: s["approvals"].__setitem__(f"content:{episode_id}",
                 {"sha256": digest(plan), "reviewer": reviewer, "note": note}))
    return {"id": episode_id, "content_sha256": digest(plan)}


def approve_rhythm(root, episode_id, reviewer, note):
    """Record explicit approval of the chapter's semantic timing rewrite."""
    if not reviewer or not note:
        raise ValueError("请记录节奏复核意见")
    plan = read(plan_path(root, episode_id))
    rhythm = plan.get("rhythm_review", {})
    if rhythm.get("version") != 2:
        raise ValueError("本章节奏配置不匹配，不能确认")
    if not rhythm.get("source_sequence_verified"):
        raise ValueError("本章原文顺序尚未核对，不能确认")
    check_speaker_audit(root, plan)
    rhythm = {**rhythm, "reviewed": True, "status": "reviewed",
              "reviewer": reviewer, "note": note, "reviewed_at": time.time()}
    plan["rhythm_review"] = rhythm
    write(plan_path(root, episode_id), plan)
    content_sha256 = digest(plan)
    visual_path = Path(root) / "analysis" / f"{episode_id}_speaker_visual.json"
    if visual_path.exists():
        visual = read(visual_path)
        visual["content_sha256"] = content_sha256
        write(visual_path, visual)
    episode_file = Path(root) / "episodes" / f"{episode_id}.json"
    if episode_file.exists():
        episode = read(episode_file)
        episode["content_sha256"] = content_sha256
        episode["rhythm_review"] = copy.deepcopy(rhythm)
        write(episode_file, episode)
    def record_approval(state):
        # The script and dialogue are unchanged; carry the existing content
        # approval forward to the new digest after reviewing timing metadata.
        content_approval = state["approvals"].get(f"content:{episode_id}")
        if content_approval:
            state["approvals"][f"content:{episode_id}"] = {
                **content_approval, "sha256": content_sha256,
                "rhythm_reviewed_at": rhythm["reviewed_at"],
            }
        state["approvals"][f"rhythm:{episode_id}"] = {
            "sha256": content_sha256, "reviewer": reviewer, "note": note,
            "reviewed_at": rhythm["reviewed_at"],
        }
    update_state(root, record_approval)
    return {"id": episode_id, "content_sha256": content_sha256, "reviewed": True}


def visual_packet(root, episode_id):
    plan = read(plan_path(root, episode_id))
    return {"kind": "arcreel_visual_authoring_for_h3", "content_sha256": digest(plan),
            "instruction": AUTHORING_RULES + "\n仅编写视觉层，禁止重写 title、source_text、utterances、角色归属或源文事实。必须按 scene_id 一一覆盖。speech_timing 每条严格对应锁定对白。为每个镜头输出 sequence_id、beat_function、state_in/state_out、screen_direction、axis_id、transition、blocking_plan、composition、action_beats；blocking_plan.actors 与绑定角色资产一一对应，声明首尾走位点/姿态/可见性；action_beats 要覆盖交付帧且每段不超过24帧。H3时长按对白/动作决定，17k+5 帧，续接扣除22帧，绝不为凑时长重复动作。场景和道具资产必须逐镜绑定。换场才切，场内续接需首尾状态一致。生成前使用 storyboard_design.validate_shot 和完整资产/对白门禁。",
            "content": plan, "assets": inventory(root),
            "design_version": VERSION,
            "output_fields": ["content_sha256", "scenes: [{scene_id, image_prompt, h3, speech_timing}]",
                              "h3 必须含 " + ", ".join(sorted(SHOT_FIELDS))],
            "h3_fields": sorted(H3_FIELDS)}


def content_current(root, episode):
    if not episode.get("content_sha256"):
        if episode.get("release_role") == "proof":
            return
        raise ValueError("正式分集必须通过 ArcReel 内容锁定和视觉合并流程")
    plan = read(plan_path(root, episode["id"]))
    check_speaker_audit(root, plan)
    state = load_state(root)
    content_digest = digest(plan)
    approval = state["approvals"].get(f"content:{episode['id']}", {})
    # Chapters authored before the content/rhythm approvals were split may
    # have only the explicit rhythm approval.  That approval still pins the
    # same content digest after the complete speaker and source-order review.
    # Accept it as the handoff lock so a finished chapter can advance; any
    # digest mismatch remains a hard failure.
    rhythm_approval = state["approvals"].get(f"rhythm:{episode['id']}", {})
    content_locked = approval.get("sha256") == content_digest or (
        plan.get("rhythm_review", {}).get("reviewed") is True
        and rhythm_approval.get("sha256") == content_digest
    )
    if episode["content_sha256"] != content_digest or not content_locked:
        raise ValueError("内容规划已变化或尚未审阅，需重新合并视觉分镜")
    if "shots" in episode:
        policy = read(Path(root) / "config.json").get("timing_policy", {})
        if policy.get("require_rhythm_review") and (episode.get("rhythm_review", {}).get("version") != policy.get("rhythm_version") or not episode.get("rhythm_review", {}).get("reviewed")):
            raise ValueError("该章节尚未完成按完整语义及动作节奏重新编排，不可沿用旧短句分镜生成")
        scenes = plan["script"]["scenes"]
        if [s["scene_id"] for s in scenes] != [s["id"] for s in episode["shots"]]:
            raise ValueError("分镜边界与锁定内容不一致")
        for scene, shot in zip(scenes, episode["shots"]):
            lines = [{"kind": line.get("kind", "dialogue"), "speaker": line["speaker"], "text": line["text"]} for line in shot["dialogue"]]
            expected = [dict(line, speaker=line["speaker"] or "旁白") for line in scene["utterances"]]
            if lines != expected or shot["source_ids"] != plan["source_map"][scene["scene_id"]]:
                raise ValueError("编译后的台词或原文引用被修改，必须返回内容层重新审阅")


def compile_visual(root, episode_id, visual):
    plan = read(plan_path(root, episode_id))
    content_current(root, {"id": episode_id, "content_sha256": visual["content_sha256"]})
    rows = visual["scenes"]
    formal_release = plan.get("release_role", "episode") != "proof"
    allowed = {"scene_id", "image_prompt", "h3", "speech_timing"}
    if any(set(row) != allowed for row in rows):
        raise ValueError("视觉输出只能包含 scene_id、image_prompt、h3、speech_timing，不能改写台词或原文")
    by_id = {row["scene_id"]: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != {s["scene_id"] for s in plan["script"]["scenes"]}:
        raise ValueError("视觉分镜必须按 ID 完整覆盖内容规划，不能重复、漏镜或增镜")
    assets = inventory(root)
    ep = {key: plan[key] for key in ("id", "dramatic_question", "turning_point")}
    ep.update(title=plan["script"]["title"], release_role=plan.get("release_role", "episode"),
              content_sha256=digest(plan), shots=[])
    export_scenes, pending_jobs = [], []
    for scene in plan["script"]["scenes"]:
        sid = scene["scene_id"]
        row = by_id[sid]
        h3 = copy.deepcopy(row["h3"])
        if set(h3) - H3_FIELDS:
            raise ValueError(f"{sid} 的 H3 视觉字段含内容字段或未知字段")
        if not isinstance(row["image_prompt"], str) or not row["image_prompt"].strip():
            raise ValueError("分镜图必须有非空提示词")
        if len(row["speech_timing"]) != len(scene["utterances"]):
            raise ValueError("发声时段必须逐条对应已锁定台词")
        h3.update(id=sid, scene_id=h3.pop("location_id"), source_ids=plan["source_map"][sid],
                  frames=frames_for(scene["duration_seconds"], h3["continuity"] == "continue"), dialogue=[])
        for line, timing in zip(scene["utterances"], row["speech_timing"]):
            if set(timing) != {"start_frame", "end_frame"}:
                raise ValueError("发声时间层只能调整时间，不能重写台词")
            h3["dialogue"].append(dict(timing, text=line["text"], speaker=line["speaker"] or "旁白", kind=line["kind"]))
        if read(Path(root) / "config.json").get("timing_policy", {}).get("content_based"):
            from .timing import retime
            h3 = retime(h3)
        if not h3["dialogue"]:
            total = h3["frames"] - (22 if h3["continuity"] == "continue" else 0)
            old_total = h3["timeline"][-1]["end_frame"]
            timeline, cursor = [], 0
            for index, beat in enumerate(h3["timeline"]):
                end = total if index == len(h3["timeline"]) - 1 else round(beat["end_frame"] * total / old_total)
                end = max(cursor + 1, min(total, end))
                while cursor < end:
                    stop = min(cursor + 24, end)
                    timeline.append(dict(beat, start_frame=cursor, end_frame=stop))
                    cursor = stop
            h3["timeline"] = timeline
        delivered = h3["frames"] - (22 if h3["continuity"] == "continue" else 0)
        h3["action_beats"] = fit_action_beats(h3["action_beats"], delivered)
        required = [resolve_reference(assets, bucket, name)
                    for bucket, field in (("characters", "characters_in_scene"), ("scenes", "scenes"), ("props", "props"))
                    for name in scene.get(field, [])]
        required = list(dict.fromkeys(required))
        references = {ref["asset_id"] for ref in h3.get("references", [])}
        if h3.get("first_frame"):
            reuse_scene_frame = required == [h3["first_frame"]] and h3["first_frame"] in load_state(root)["assets"]
            existing_job = Path(root) / "jobs" / f"image_{h3['first_frame']}.json"
            reuse_generated_frame = (h3["first_frame"] in load_state(root)["assets"] and existing_job.is_file()
                                     and read(existing_job).get("prompt") == row["image_prompt"]
                                     and read(existing_job).get("reference_asset_ids") == required)
            if not reuse_scene_frame and not reuse_generated_frame:
                pending_jobs.append((h3["first_frame"], row["image_prompt"], required))
        elif h3["continuity"] == "cut" and not set(required) <= references:
            raise ValueError(f"{sid} 必须通过首帧或 Ref2VA 引用全部出场资产")
        if h3["continuity"] == "continue":
            if not ep["shots"] or required != ep["shots"][-1].get("required_assets", []):
                raise ValueError("续接不能引入不同出场资产；请使用剪辑重建身份")
        if scene.get("visual_narration"):
            h3["visual_narration"] = scene["visual_narration"]
        h3["required_assets"] = required
        if formal_release:
            h3["storyboard_schema"] = VERSION
            shot_errors = validate_shot(scene, h3)
            if shot_errors:
                raise ValueError("\n".join(shot_errors))
        ep["shots"].append(h3)
        # ArcReel's interchange schema represents narration with speaker=null.
        # The studio content plan and H3 sidecar retain the explicit voice owner.
        export_scenes.append({**{k: v for k, v in scene.items() if k != "scene_description"},
                              "utterances": [dict(line, speaker=None if line['kind']=='voiceover' else line['speaker']) for line in scene['utterances']],
                              "duration_seconds": round((h3["frames"] - (22 if h3["continuity"] == "continue" else 0))/24),
                              "image_prompt": row["image_prompt"],
                              "video_prompt": h3_prompt(dict(h3, dialogue=[]), read(Path(root) / "config.json")["style"])})
    errors = validate_episode(root, ep)
    if errors:
        raise ValueError("\n".join(errors))
    # Carry the reviewed content timing contract into the compiled episode so
    # the submission-time gate can verify that semantic reblocking was kept.
    ep["rhythm_review"] = copy.deepcopy(plan.get("rhythm_review", {}))
    if formal_release:
        ep["storyboard_schema"] = VERSION
    if len({aid for aid, _, _ in pending_jobs}) != len(pending_jobs):
        raise ValueError("每个首帧工作单必须使用独立 ID")
    for aid, prompt, refs in pending_jobs:
        image_job(root, aid, prompt, refs, role="storyboard_keyframe")
    write(Path(root) / "episodes" / f"{episode_id}.json", ep)
    export_dir = Path(root) / "arcreel_export" / episode_id
    write(export_dir / "script.json", {"title": ep["title"], "content_mode": "drama", "scenes": export_scenes})
    write(export_dir / "h3.json", ep)
    return {"episode": episode_id, "shots": len(ep["shots"]), "export": str(export_dir),
            "note": "ArcReel 剧本保留整数秒编辑目标；h3.json 保存准确交付帧数和续接状态"}
