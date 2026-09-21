import math
import re
from pathlib import Path
from .project import read, write, digest, safe_id, load_state, update_state

FPS = 24
CONTEXT = 22

GENDER_PROMPTS = {
    "男": "male character identity; preserve masculine anatomy and presentation; no feminine facial styling, earrings or feminine silhouette",
    "女": "female character identity; preserve feminine anatomy and presentation; do not masculinize",
    "非人形": "non-human creature identity; keep the species or creature anatomy; do not turn it into a human woman or man",
    "群体": "group asset; preserve the storyboard's group composition and do not invent an individual identity",
    "未知": "gender unspecified; do not infer, feminize or masculinize beyond the approved reference",
}

# H3 does not expose a separate "mute human voice" input on its reference-to-
# video node.  Keep the no-dialogue contract deliberately short and
# machine-readable: long negative lists have repeatedly been interpreted as
# language material by the audio head (and then repeated by Whisper).  The
# positive sound cues remain in ``overall_soundscape`` below.
NO_DIALOGUE_AUDIO_SCHEMA = (
    "H3_AUDIO_SCHEMA_V3\n"
    "AUDIO_MODE=DIEGETIC_EFFECTS_ONLY\n"
    "HUMAN_VOICE_ALLOWLIST=[]\n"
    "DIALOGUE_SOURCE=[]\n"
    "NARRATION=DISABLED\n"
    "REFERENCE_AUDIO_INPUT=NONE\n"
    "MOUTH_AUDIO_LINK=OFF\n"
    "NON_DIEGETIC_MUSIC=OFF\n"
    "AUDIO_ACTION=RENDER_ONLY_POSITIVE_SOUNDSCAPE; OTHERWISE_SILENCE"
)


def gender_prompt(value):
    """Return a visual-only gender lock for an asset-bound model prompt."""
    return GENDER_PROMPTS.get(value, GENDER_PROMPTS["未知"])


def soundscape_for(shot):
    """Build a diegetic sound brief without turning narration into speech."""
    text = " ".join(str(shot.get(key, "")) for key in ("action", "visual_narration", "soundscape"))
    cues = []
    patterns = (
        (r"雷|闪电|雷鸣", "sharp lightning cracks followed by layered distant thunder"),
        (r"震动|震荡|山崩|地裂|坍塌|碎石", "clear low ground rumble, stone fracture and layered distant collapse at a natural film-mix level"),
        (r"海水|海浪|水面|倾覆|潮", "clearly audible heavy surf, wave impact and wind pushed by the moving water"),
        (r"金光|光芒|飞落|飞去|飞射|腾云|金云|云", "high-altitude wind rush and a focused, non-musical energy whoosh"),
        (r"走|脚踏|进入|点头|躬身|跪|站", "motivated footsteps, cloth movement and light contact sounds"),
        (r"天兵|神将|铠甲|玉笏|宫|殿|门", "audible armor or prop contact with a natural palace-space reverb"),
        (r"黑暗|虚空|天外天|寂静", "subtle but clearly audible cosmic air and natural spatial bed, never a musical drone"),
    )
    for pattern, cue in patterns:
        if re.search(pattern, text):
            cues.append(cue)
    if not cues:
        cues.append("quiet location ambience and small movement sounds only when visibly motivated")
    if shot.get("dialogue"):
        lead = ("SOUNDSCAPE_OUTPUT=DIALOGUE_PLUS_DIEGETIC_EFFECTS; use the exact dialogue allowlist only for human voice. "
                "Keep the bound line intelligible and place these positive, non-verbal diegetic effects underneath or between "
                "the line without masking it: ")
    else:
        lead = ("SOUNDSCAPE_OUTPUT=EFFECTS_ONLY; render only the following positive, non-verbal diegetic effects, "
                "synchronized to visible action, with natural dynamic range and no masking noise: ")
    return lead + "; ".join(dict.fromkeys(cues)) + ". MUSIC_MODE=OFF."


def generation_audio_contract(shot):
    """Return a compact fail-closed audio contract for the H3 audio head.

    The previous contract repeated a long negative list and included example
    words. H3 could treat those words as language material. Keep the model
    input machine-readable and positive: the only human voice source is the
    exact ``<d>`` allowlist; all other human speech is silence.
    """
    if shot.get("dialogue"):
        return (
            "H3_AUDIO_SCHEMA_V4\n"
            "AUDIO_MODE=DIALOGUE_ALLOWLIST_PLUS_DIEGETIC_EFFECTS\n"
            "HUMAN_VOICE_SOURCE=EXACT_D_BLOCKS_ONLY\n"
            "DIALOGUE_CARDINALITY=EACH_D_BLOCK_ONCE\n"
            "REFERENCE_AUDIO=BOUND_TIMBRE_ONLY\n"
            "NARRATION=DISABLED\n"
            "OUTSIDE_D_WINDOWS=NO_HUMAN_VOICE\n"
            "UNMATCHED_HUMAN_VOICE=SILENCE\n"
            "METADATA_AND_SOURCE_TEXT=NON_SPEECH"
        )
    return NO_DIALOGUE_AUDIO_SCHEMA


def frames_for(seconds, continuation=False):
    # H3's conditioning node accepts the 17k+5 grid from 5 frames upward.
    # Do not impose the old ~5-second (124-frame) floor: short dialogue shots
    # should end when their locked performance ends, with only the grid round-up.
    need = max(5, math.ceil(seconds * FPS) + (CONTEXT if continuation else 0))
    frames = 5 + math.ceil((need - 5) / 17) * 17
    if frames > 362:
        raise ValueError("镜头超过 H3 训练时长，请拆镜头")
    return frames


def delivered_frames(shot):
    return shot["frames"] - (CONTEXT if shot["continuity"] == "continue" else 0)


def episode_path(root, episode_id):
    return Path(root) / "episodes" / f"{safe_id(episode_id)}.json"


def validate_episode(root, episode):
    errors = []
    ids, previous, chain_size = set(), None, 0
    paragraphs = {p["id"]: p for p in read(Path(root) / "paragraphs.json")}
    safe_id(episode["id"])
    if not episode.get("shots"):
        return ["缺少镜头"]
    if not episode.get("dramatic_question") or not episode.get("turning_point"):
        errors.append("分集必须有戏剧问题与转折")
    for shot in episode["shots"]:
        sid = safe_id(shot["id"])
        if sid in ids:
            errors.append(f"{sid}: 镜头编号重复")
        ids.add(sid)
        if shot.get("mode") not in ("fl2va", "ref2va"):
            errors.append(f"{sid}: 模式必须为 fl2va 或 ref2va")
        if shot.get("continuity") not in ("cut", "continue"):
            errors.append(f"{sid}: 缺少剪辑/续接决策")
        frames = shot["frames"]
        if type(frames) is not int or not 5 <= frames <= 362 or (frames - 5) % 17:
            errors.append(f"{sid}: 帧数须在 5–362 且满足 17k+5")
        refs = shot.get("source_ids", [])
        if not refs or not set(refs) <= set(paragraphs):
            errors.append(f"{sid}: 缺少有效原文段落引用")
        for key in ("dramatic_function", "action", "soundscape", "handoff_in", "handoff_out"):
            if not shot.get(key):
                errors.append(f"{sid}: 缺少 {key}")
        camera = shot.get("camera", {})
        if not all(camera.get(k) for k in ("size", "lens_mm", "movement", "motivation")):
            errors.append(f"{sid}: 镜头必须有景别、焦距、运动及叙事动机")
        if shot["continuity"] == "continue":
            chain_size += 1
            if previous is None or shot["scene_id"] != previous["scene_id"]:
                errors.append(f"{sid}: 不得跨场景续接")
            elif shot["handoff_in"] != previous["handoff_out"]:
                errors.append(f"{sid}: 续接入口必须与上镜出口完全一致")
            if shot.get("first_frame"):
                errors.append(f"{sid}: 续接帧已由 latent 固定，不能再绑首帧")
            if shot.get("hold_frames", 0) < 48:
                errors.append(f"{sid}: 续接开头需至少 2 秒活动衔接，不能冻结表演")
            if chain_size > 3:
                errors.append(f"{sid}: 连续链超过 3 段，请在合理剪辑点重建场景")
        else:
            chain_size = 1
        timeline = shot.get("timeline", [])
        cursor = 0
        for beat in timeline:
            if beat["start_frame"] != cursor or beat["end_frame"] <= cursor or not beat.get("description"):
                errors.append(f"{sid}: 动作时间线有空缺、重叠或无动作说明")
            if beat["end_frame"] - beat["start_frame"] > FPS:
                errors.append(f"{sid}: 动作指令应逐秒填写，每段不超过 24 帧")
            cursor = beat["end_frame"]
        if cursor != delivered_frames(shot):
            errors.append(f"{sid}: 时间线应完整覆盖交付的 {delivered_frames(shot)} 帧")
        speech_end = 0
        for line in shot.get("dialogue", []):
            if type(line["start_frame"]) is not int or type(line["end_frame"]) is not int or line["start_frame"] < speech_end:
                errors.append(f"{sid}: 台词时段必须为整数帧且不得重叠")
            speech_end = line["end_frame"]
            if not line.get("speaker") or not line.get("text") or not (0 <= line["start_frame"] < line["end_frame"] <= cursor):
                errors.append(f"{sid}: 台词缺说话人、文字或有效时段")
            if shot["continuity"] == "continue" and line["start_frame"] < shot.get("hold_frames", 48):
                errors.append(f"{sid}: 续接入口不能抢入新台词")
            if len(line["text"]) / max((line["end_frame"] - line["start_frame"]) / FPS, .01) > 6:
                errors.append(f"{sid}: 台词语速超过每秒 6 字，请重排时间")
        if shot["mode"] == "ref2va" and not shot.get("references"):
            errors.append(f"{sid}: Ref2VA 缺少已定义参考")
        if len(shot.get("references", [])) > 9:
            errors.append(f"{sid}: 图片参考不得超过 9 张")
        # A Ref2VA shot has no separate background input.  When the project
        # inventory is available, require exactly one declared scene asset and
        # make its ID agree with scene_id before an episode can be compiled.
        asset_inventory = Path(root) / "bible" / "assets.json"
        if shot.get("mode") == "ref2va" and asset_inventory.exists():
            asset_data = read(asset_inventory)
            scene_ids = {item.get("id") for item in asset_data.get("scenes", {}).values()}
            scene_refs = [ref.get("asset_id") for ref in shot.get("references", [])
                          if ref.get("asset_id") in scene_ids]
            if shot.get("scene_id") not in scene_ids:
                errors.append(f"{sid}: scene_id={shot.get('scene_id') or '<missing>'} 不存在于场景资产名册")
            elif scene_refs != [shot["scene_id"]]:
                errors.append(f"{sid}: 场景参考必须且只能绑定 scene_id={shot['scene_id']}")
        if (Path(root) / "bible/voices.json").exists():
            from .voices import bindings
            try:
                bindings(root, shot)
            except (ValueError, KeyError, OSError) as exc:
                errors.append(f"{sid}: {exc}")
        previous = shot
    return errors


def series_packet(root):
    root = Path(root)
    book = read(root / "book.json")
    missing = [c["id"] for c in book["chapters"] if not (root / "analysis" / f"{c['id']}.json").exists()]
    return {"kind": "series_design", "status": "waiting_analysis" if missing else "ready",
            "source_scope": book["scope"], "missing_analysis": missing,
            "inputs": {"chapter_analysis": "analysis/*.json", "characters": "bible/characters.json", "world": "bible/world.json"},
            "instruction": "所有正文逐章分析后，按因果与人物选择重组分集。缺失章号允许形成断裂，不补写原文没有的连接剧情。首集不要长篇神谱讲解，先建立人物处境；创世背景按观众当前需要分配。每集 12–20 分钟是初始编辑目标而非强制机械长度。分集必须有主动目标、阻力、关键选择、后果、结尾推进，保留全书人物与伏笔账本。禁止只选开头几章冒充全书。",
            "output": {"series.json": {"episode_ids": ["ep001"], "arcs": [], "episode_summaries": []},
                       "episodes/ep001.json": "与 examples/proof_tongtian.json 相同的镜头结构；release_role 改为 episode。每镜填写 source_ids、角色/场景参考、对白时段、动作时间线与交接状态。"}}


def approve_episode(root, episode_id, reviewer, note):
    episode = read(episode_path(root, episode_id))
    from .arcreel import content_current
    content_current(root, episode)
    errors = validate_episode(root, episode)
    if errors:
        raise ValueError("\n".join(errors))
    if not reviewer or not note:
        raise ValueError("需记录分镜审阅人和审阅意见")
    approval = {"sha256": digest(episode), "reviewer": reviewer, "note": note}
    update_state(root, lambda s: s["approvals"].__setitem__(episode_id, approval))


def timestamp(frame):
    ms = round(frame * 1000 / FPS)
    return f"{ms // 60000:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def _speech_safe_visual_text(value):
    """Keep dialogue-shot visual direction from becoming a spoken source.

    Chinese is retained in the exact ``<d>`` line below, but free-form Chinese
    in action, timeline or handoff metadata is replaced before it reaches H3's
    audio head. The full text remains in the execution sheet for review.
    """
    return re.sub(r"[\u3400-\u9fff]+", "visual metadata", str(value or ""))


def character_visibility_policy(cast_count, has_dialogue):
    """Return the hard character-visibility rule for both the sheet and H3."""
    if has_dialogue:
        if cast_count:
            return ("Dialogue shot character lock: only the registered character assets explicitly bound in this shot may appear. "
                    "Do not generate or show any unbound or unregistered person, face, silhouette, reflection, clone, crowd, passerby, "
                    "background human, guard, child, deity or other human-like figure. Character reference pictures are the sole identity source. "
                    "Every visible speaking or listening person must be one of the bound character subjects. "
                    "The total number of human bodies must equal the bound cast count; never add a body, face, silhouette or duplicate.")
        return ("Dialogue shot character lock: no bound character asset is present, so no person, face, silhouette, reflection, clone, crowd, "
                "passerby or human-like figure may appear. Do not invent a speaker or listener.")
    if cast_count:
        return ("Silent visual cast policy: the bound character assets are the only named or foreground identities. "
                "Keep every registered mouth at rest; unregistered background extras, if visually motivated, stay distant and non-identifiable.")
    return ("Silent visual cast policy: no bound character is required. Any motivated background atmosphere stays distant and non-identifiable; "
            "do not create a foreground human identity or a vocal performance.")


def h3_prompt(shot, style):
    offset = CONTEXT if shot["continuity"] == "continue" else 0
    camera = shot["camera"]
    package = shot.get("asset_package", {})
    package_visuals = package.get("visual_assets", [])
    has_dialogue = bool(shot.get("dialogue"))
    visual_action = _speech_safe_visual_text(shot["action"]) if has_dialogue else shot["action"]
    visual_size = _speech_safe_visual_text(camera["size"]) if has_dialogue else camera["size"]
    visual_movement = _speech_safe_visual_text(camera["movement"]) if has_dialogue else camera["movement"]
    intro = (f"{style}\n{generation_audio_contract(shot)}\n[Shot 1] {visual_size}, {camera['lens_mm']}mm lens. "
             f"{visual_movement}. {visual_action}\n")
    camera_execution = package.get("camera_execution", {})
    if camera_execution.get("model_instruction"):
        camera_instruction = camera_execution["model_instruction"]
        if has_dialogue:
            # Keep speaker names in the human-facing execution sheet, but do
            # not feed them as extra language to H3. The bound picture/audio
            # labels and the exact <d> line are the only spoken identity data.
            for binding in package.get("audio_bindings", []):
                speaker = str(binding.get("speaker", "")).strip()
                if speaker:
                    camera_instruction = camera_instruction.replace(speaker, "the assigned speaker subject")
            camera_instruction = _speech_safe_visual_text(camera_instruction)
        intro += "Professional camera execution: " + camera_instruction + "\n"
    identity_bindings = package.get("identity_bindings", [])
    # In an effects-only shot, Chinese identity names and long appearance
    # metadata are visual production records, not model language.  Sending
    # them repeatedly in subject definitions, identity locks and listener
    # locks can make H3 read the metadata as an unsolicited voice line.
    # Use neutral subject slots for every H3 prompt and let the bound pictures
    # carry appearance identity. Human-readable names remain in the execution
    # sheet and the exact dialogue text remains the sole spoken text source.
    if identity_bindings:
        intro += (
            "IDENTITY_BINDING_LOCK (visual production metadata only; never speak, subtitle or turn this table into narration):\n"
        )
        for item in identity_bindings:
            role = "the only assigned speaker" if item.get("role") == "speaker" else "the only silent listener"
            view = item.get("selected_character_view_label") or item.get("selected_character_view") or "approved independent view"
            view = {"正面": "front view", "背面": "rear view", "侧面": "side view", "特写": "close-up view"}.get(view, "bound view")
            # Names and Chinese appearance notes belong to the auditable sheet,
            # not the multimodal generation prompt. Reference pictures are the
            # authoritative identity source and the neutral subject slot keeps
            # the audio head from reading asset metadata as dialogue.
            name = item.get("subject_label", "visual subject")
            anchor = "use only the bound reference picture for appearance"
            intro += (
                f"- {item['subject_label']} = registered visual subject {name} "
                f"(asset_id={item['asset_id']}), {item['picture_label']}, {role}, "
                f"one body only, reference view={view}. "
                f"Approved appearance anchor: {anchor}. "
                "This identity is visually distinct from every other bound identity; never swap, merge or duplicate it.\n"
            )
        speaker_rows = package.get("interaction_contract", {}).get("speaker_visual_bindings", [])
        for row in speaker_rows:
            if row.get("asset_id") and row.get("picture_label"):
                intro += (
                    f"- SPEAKER_LOCK: {row.get('picture_label')} -> {row['asset_id']} -> "
                    f"{row['picture_label']} -> {row['audio_label']}; "
                    "the voice reference cannot authorize a different face or body, and no other subject may speak.\n"
                )
        for item in (item for item in identity_bindings if item.get("role") == "listener"):
            view = item.get("selected_character_view_label") or item.get("selected_character_view") or "approved independent view"
            view = {"正面": "front view", "背面": "rear view", "侧面": "side view", "特写": "close-up view"}.get(view, "bound view")
            listener_name = item.get("subject_label", "visual subject")
            intro += (
                f"- LISTENER_LOCK: {listener_name} -> {item['asset_id']} -> {item['picture_label']} -> {view}; "
                "this is the one silent listener body in the blocking, shown only in the requested rear/occluded framing; "
                "never reveal a second listener, a frontal face, a mirror, a reflection or a replacement identity.\n"
            )
        if package.get("character_identity_lock", {}).get("present_time_only"):
            intro += (
                "PRESENT_TIME INTERACTION LOCK: this is one continuous present-time scene. "
                "Do not visualize the content being recounted. No flashback, memory, apparition, ghost, vision, "
                "insert portrait, symbolic duplicate, mirrored copy or third human body. "
                "The declared cast is the complete cast for the entire shot.\n"
            )
    if shot.get("review_note"):
        # Keep the user's exact note in the human-facing execution sheet and
        # fingerprint, but never send its original language to H3.  A model
        # can still treat text surrounded by "never speak" as a script cue;
        # the model prompt therefore receives only a neutral English control
        # instruction and the actual dialogue remains the sole vocal source.
        intro += ("HUMAN_REVIEW_CORRECTION_FOR_RETAKE (silent production direction only): "
                  "apply the requested correction to picture, blocking, identity, camera, continuity and sound as applicable. "
                  "The private review note is not a script, subtitle, narration, voice, lyric or sound cue; never read, quote, "
                  "paraphrase, translate or vocalize any review text, metadata or instruction, and do not add new dialogue.\n")
    if shot.get("speaker_focus_mode") == "speaker_dominant":
        intro += (
            "SPEAKER_DOMINANT_RETAKE (visual production instruction only; never speak or subtitle this metadata): "
            "the assigned speaker subject is the only fully visible face and the only visible moving mouth. "
            "Keep the listener in the same physical space only as one partial rear shoulder or back-of-head at the edge of frame; "
            "hide the listener's face completely, do not show listener lips, and do not create a second frontal face. "
            "Do not change the bound speaker, voice reference, costume, scene or dialogue.\n"
        )
    dialogue_events = package.get("dialogue_event_bindings", [])
    if dialogue_events:
        intro += (
            "DIALOGUE_EVENT_BINDING_LOCK (silent production metadata only; never speak, subtitle, quote, paraphrase "
            "or vocalize this table): each event below has one immutable visual mouth owner and one matching voice reference.\n"
        )
        for event in dialogue_events:
            if event.get("kind") == "voiceover":
                intro += (
                    f"- {event['event_id']} at {timestamp(event.get('start_frame', 0) + offset)}-"
                    f"{timestamp(event.get('end_frame', 0) + offset)}: offscreen narrator, "
                    f"{event.get('audio_label') or 'no visual subject'}, mouth_owner=none; no visible character may lip-sync.\n"
                )
                continue
            intro += (
                f"- {event['event_id']} at {timestamp(event.get('start_frame', 0) + offset)}-"
                f"{timestamp(event.get('end_frame', 0) + offset)}: "
                f"visual_subject={event['subject_label']}; visual_picture={event['picture_label']}; "
                f"voice_reference={event['audio_label']}; mouth_owner={event['subject_label']}; "
                "the voice reference cannot authorize another face or body.\n"
            )
        if len(dialogue_events) and len(package.get("visual_assets", [])) > 1:
            intro += (
                "For every speaking event, the assigned visual picture is the only fully visible moving mouth. "
                "Keep all listener faces rear-facing, occluded or outside the focal plane with closed lips; never show two "
                "full frontal faces competing for the same dialogue. Do not infer the speaker from audio, position or costume.\n"
            )
    if shot.get("visual_narration"):
        intro += "Source prose is used only by the human storyboard and is intentionally omitted from the model prompt.\n"
    cast = [item for item in package_visuals if item["kind"] == "character"]
    if package_visuals:
        if cast:
            labels = ", ".join(f"<Subject {item['subject_label'].split()[-1]}>" for item in cast)
            intro += f"Visible cast count: exactly {len(cast)} distinct character(s): {labels}. "
            intro += "Show each bound character exactly once.\n"
            locks = "; ".join(
                f"<Subject {item['subject_label'].split()[-1]}> {gender_prompt(item.get('gender', '未知'))}"
                for item in cast if item.get('gender'))
            if locks:
                intro += "Visual-only gender locks (never speak or subtitle this metadata): " + locks + ".\n"
            if len(cast) > 1:
                intro += (
                    "Distinct-identity check before rendering: assign each body to exactly one subject slot by its "
                    "bound picture, costume, face and silhouette. Subject slots cannot be reused. "
                    "If a framing change is needed, reframe the same bodies; never add a replacement body or "
                    "leave a stale copy in the background.\n"
                )
            if len(cast) > 1:
                intro += ("Keep every bound character visible in the same continuous physical space as a real interaction shot. "
                          "Use shared blocking, coherent scale, eyelines and screen direction; never replace the interaction with "
                          "separate solo portraits or a split screen. "
                          + ("Only the assigned speaker moves their mouth; every listener reacts naturally with closed lips.\n"
                             if has_dialogue else
                             "All bound mouths remain at rest for the entire shot.\n"))
                if "over-the-shoulder" in str(camera.get("size", "")).lower() or "过肩" in str(camera.get("size", "")):
                    intro += ("Hard over-the-shoulder blocking: exactly two human bodies total in this frame. "
                              "The foreground shoulder/back belongs to the single bound listener only; it is one partial body, "
                              "never a face, a second body or a new person. Show the bound speaker as the only other human. "
                              "Do not reveal the listener's face, do not repeat either identity in the background, and do not add "
                              "any extra human, silhouette, reflection, passerby or crowd.\n")
        else:
            intro += "Visible cast count: zero bound character assets.\n"
        scenes = [item for item in package_visuals if item["kind"] == "scene"]
        for scene in scenes:
            subject_label = scene.get("subject_label", "Subject 1")
            picture_label = scene.get("picture_label", "Picture 1")
            label = f"<Subject {subject_label.split()[-1]}>"
            intro += (f"Environment anchor (highest visual priority): {label} is the exclusive background plate and the only location. "
                      f"Use the exact environment from <Picture {picture_label.split()[-1]}> across the entire shot; preserve its geography, depth, lighting and distinctive structures. "
                      "Composite bound characters and props into this plate. Never substitute a different interior, exterior, architecture, room, palace, furniture layout or unrelated location, and never import a background from a character or prop reference.\n")
            design = scene.get("design_description", "").strip()
            if design:
                # Keep the full design note in the human-facing execution
                # sheet, but do not place Chinese metadata in H3's shared
                # audio/visual prompt: H3 may read it as dialogue despite
                # surrounding "visual only" instructions.
                intro += (f"Environment appearance is fixed by <Picture {picture_label.split()[-1]}>. "
                          "Visual asset metadata is non-speech; never vocalize, paraphrase or subtitle it.\n")
        props = [item for item in package_visuals if item["kind"] == "prop"]
        if props:
            labels = ", ".join(f"<Subject {item['subject_label'].split()[-1]}>" for item in props)
            intro += (f"Bound props: exactly {len(props)} distinct prop(s): {labels}. Keep each prop's owner, hand, position, "
                      "orientation and state continuous with the action; do not drop, duplicate or teleport it.\n")
        intro += ("Reference pictures provide identity, environment or prop appearance only. Never reproduce a reference-sheet layout, "
                  "split screen, inset portrait, reflection, twin, clone, mirrored duplicate or second copy of a bound subject.\n")
    intro += character_visibility_policy(len(cast), bool(shot.get("dialogue"))) + "\n"
    if not shot.get("dialogue"):
        intro += (
            "NO_DIALOGUE_BOUNDARY: H3_AUDIO_SCHEMA_V3 is authoritative for this shot. "
            "All registered bodies are silent visual subjects; keep every mouth at rest and attach no vocal performance. "
            "Render only the positive effects listed in SOUNDSCAPE_OUTPUT.\n"
        )
    if shot.get("dialogue"):
        intro += (
            "VOCAL_CONTENT_LOCK: The human-voice track contains only the exact <d> dialogue lines below, each once, "
            "through its bound picture and bound timbre reference. No human voice exists outside those time windows or "
            "between lines. All metadata, source prose, labels and reference-audio words are non-speech. Keep diegetic "
            "thunder, water, wind, impact and room ambience non-verbal.\n"
        )
        intro += ("Only the target words enclosed in <d> may be spoken, exactly once. Never pronounce character names, reference labels, "
                  "reference descriptions or commentary. The listed start and finish times are strict picture-time locks.\n")
        intro += (
            "SINGLE_PASS_DIALOGUE_LOCK: Treat each <d> block as one atomic performance. Read the exact Chinese text left-to-right "
            "once, then stop the human voice. Do not restart, extend, paraphrase or source words from the reference sample.\n"
        )
        if shot.get("id") == "C3P01_03":
            intro += ("This is one complete, single-sentence offscreen voiceover. Treat the clause as finished at the end of this shot; "
                      "speak it once, then output silence for the rest of the shot. Do not continue, repeat, paraphrase or add any words.\n")
        if package.get("character_identity_lock", {}).get("present_time_only"):
            intro += (
                "No visualized exposition: the dialogue may describe past events, but those events must not appear "
                "as a flashback, apparition, ghost, memory insert or second version of any bound character.\n"
            )
    if offset:
        intro += (f"The first {offset / FPS:.6f} seconds repeat the pinned tail of the previous shot. "
                  f"Preserve this exact starting state: {shot['handoff_in']}. Continue physical motion; no freeze, no new people, no new speech.\n")
    for beat in shot["timeline"]:
        description = beat["description"]
        if has_dialogue:
            description = _speech_safe_visual_text(description)
        if not shot.get("dialogue") and re.search(r"speaks?|listeners?|dialogue|voice", description, re.I):
            description = "Continue the established visual action and camera move; keep all mouths at rest and preserve AUDIO_MODE=DIEGETIC_EFFECTS_ONLY."
        intro += (f"From {timestamp(beat['start_frame'] + offset)} to {timestamp(beat['end_frame'] + offset)}: "
                  f"{description}\n")
    speakers = []
    bindings = {b["speaker"]: b for b in shot.get("speech_bindings", [])}
    for line in shot.get("dialogue", []):
        if line["speaker"] not in speakers:
            speakers.append(line["speaker"])
        spoken_text = line["text"]
        if shot.get("id") == "C3P01_03":
            spoken_text = spoken_text.rstrip("，,、;；:：") + "。"
        voice = "offscreen narrator" if line.get("kind") == "voiceover" else line["speaker"]
        binding = bindings.get(line["speaker"])
        if binding:
            voice = (f"<Subject {binding['picture']}>" if binding["picture"]
                     else (f"the collective voice reference <Audio {binding['audio']}>"
                           if binding.get('collective') else "offscreen narrator"))
        instruction = "No visible character mouths this narration." if line.get("kind") == "voiceover" else "Only this person speaks."
        delivery = "says in an off-screen voiceover" if line.get("kind") == "voiceover" else "says"
        intro += (f"At {timestamp(line['start_frame'] + offset)}, {voice} "
                  f"(S{speakers.index(line['speaker']) + 1}) {delivery} <d>[Chinese] {spoken_text}</d>. "
                  f"{instruction} Finish by {timestamp(line['end_frame'] + offset)}.\n")
    handoff_out = _speech_safe_visual_text(shot["handoff_out"]) if has_dialogue else shot["handoff_out"]
    intro += f"End state: {handoff_out}.\n"
    soundscape = soundscape_for(shot)
    # Keep one audio contract at the prompt head. Repeating a long contract at
    # the tail increased the amount of text available to H3's audio head and
    # made metadata more likely to be interpreted as a vocal continuation.
    tail = (f"\noverall_soundscape:\n{soundscape}\n\nnon_diegetic_music:\nN/A")
    if shot["mode"] == "fl2va":
        alignment = ""
        if shot.get("first_frame") and shot.get("last_frame"):
            alignment = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                         f"Picture 2 (from Shot 1) aligns with the {shot['frames'] / FPS:.2f}-second mark of the target video.\n\n")
        elif shot.get("first_frame"):
            alignment = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        elif shot.get("last_frame"):
            alignment = f"How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the {shot['frames'] / FPS:.2f}-second mark of the target video.\n\n"
        return alignment + "integrated_multimodal_description:\n" + intro + tail
    definitions, retention = [], []
    for i, ref in enumerate(shot["references"], 1):
        package_ref = package_visuals[i - 1] if i <= len(package_visuals) else None
        if package_ref and package_ref["kind"] == "character":
            view = package_ref.get("selected_character_view") or package_ref.get("reference_variant")
            gender = gender_prompt(package_ref.get("gender", "未知"))
            identity = next((item for item in package.get("identity_bindings", [])
                             if item.get("asset_id") == package_ref.get("asset_id")), None)
            identity_label = (
                f" registered visual subject {package_ref.get('subject_label', 'subject')} "
                f"(asset_id {package_ref.get('asset_id', '')})" if identity else ""
            )
            if package_ref.get("view_selection_reason") == "over_shoulder_listener_rear_identity_anchor":
                description = (f"exactly one{identity_label} {gender} whose identity is anchored by the bound independent rear view; "
                               "this is the single silent listener and must appear only as that same character's partial rear shoulder and back of head, "
                               "never a frontal face, second body, duplicate or new person")
            else:
                description = f"exactly one{identity_label} {gender} using only the bound independent {view} view"
            lock = ref["lock"] + "; render one instance only, with no duplicate, inset, reflection or clone"
        elif package_ref and package_ref["kind"] == "scene":
            description = "the environment"
            lock = ref["lock"] + "; use it only as the location and never as a person or voice source"
        elif package_ref and package_ref["kind"] == "prop":
            description = "exactly one prop"
            lock = ref["lock"] + "; render one instance only unless the storyboard explicitly requests more"
        else:
            description = ref['description']
            if re.search(r'[\u4e00-\u9fff]', description):
                # Chinese asset labels can leak into generated speech. Keep them in
                # the human-facing manifest, not in the model's visual definitions.
                description = "the same character" if any(b['picture'] == i for b in bindings.values()) else "the same visual subject"
            lock = ref["lock"]
        definitions.append(f"<Subject {i}> is {description} from <Picture {i}>.")
        retention.append(f"<Subject {i}> (appears in [Shot 1]): fully_preserved - {lock}.")
    for binding in bindings.values():
        target = f"<Subject {binding['picture']}>" if binding["picture"] else "the offscreen narrator"
        definitions.append(f"<Audio {binding['audio']}> is the voice-timbre reference for {target} ({binding['speaker_label']}).")
        retention.append(f"<Audio {binding['audio']}>: reference - transfer only this speaker's vocal identity and timbre. Speak only the target Chinese dialogue, never copy the reference transcript. No other character uses this voice.")
    task_type = "[reference generation + audio reference] " if bindings else "[reference generation] "
    summary = _speech_safe_visual_text(shot["action"]) if has_dialogue else shot["action"]
    return ("subject_definitions:\n" + "\n".join(definitions) + "\n\nsummary:\n" + task_type + summary +
            "\n\nretention_analysis:\n" + "\n".join(retention) + "\n\ndetailed_description:\n" + intro + tail)


def image_job(root, asset_id, prompt, references=None, role="keyframe"):
    job = {"id": safe_id(asset_id), "kind": "image", "provider": "codex_image_gen",
           "subscription": "ChatGPT 5x", "status": "pending_verified_2_5_generation",
           "requested_model": "ChatGPT Images 2.5", "model_selection": "managed_by_current_codex_tool",
           "role": role, "prompt": prompt, "reference_asset_ids": references or [],
           "instruction": "由当前 Codex 对话调用 image_gen；先查看所有本地参考图，再传 referenced_image_paths。禁止切换到其他文生图模型或伪造接口。复制工具实际生成文件回项目，记录工具返回的模型信息；没有信息就标为不可核实。"}
    write(Path(root) / "jobs" / f"image_{asset_id}.json", job)
    return job


def coverage(root):
    root = Path(root)
    paragraphs = read(root / "paragraphs.json")
    analyses = [read(p) for p in (root / "analysis").glob("*.json")]
    episodes = [read(p) for p in sorted((root / "episodes").glob("*.json"))]
    treatments = {d["paragraph_id"]: d for a in analyses for d in a["dispositions"]}
    represented = {pid for ep in episodes if ep.get("release_role", "episode") == "episode"
                   for sh in ep["shots"] for pid in sh["source_ids"]}
    pending = [p["id"] for p in paragraphs if p["id"] not in treatments]
    not_adapted = [pid for pid, d in treatments.items() if d["treatment"] == "dramatize" and pid not in represented]
    return {"total_paragraphs": len(paragraphs), "analyzed_paragraphs": len(treatments),
            "pending_analysis": pending, "drama_without_shots": not_adapted,
            "all_supplied_text_accounted_for": not pending and not not_adapted}
