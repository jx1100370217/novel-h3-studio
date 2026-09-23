"""Compile a storyboard shot into an explicit, inspectable H3 asset binding package."""
from pathlib import Path
import re

from .project import read
from .director import character_visibility_policy, gender_prompt, bound_character_action_contract


CAMERA_SOURCES = [
    "https://dev.epicgames.com/documentation/en-us/fortnite/making-cinematics-3-camera-movement-and-framing-in-unreal-editor-for-fortnite",
    "https://dev.epicgames.com/documentation/unreal-engine/camera-jibs-and-dollies-in-unreal-engine",
    "https://docs.unity3d.com/Packages/com.unity.cinemachine@2.6/manual/CinemachineBodyFramingTransposer.html",
]


def _inventory(root):
    path = Path(root) / "bible/assets.json"
    if not path.exists():
        return {}
    result = {}
    for bucket, kind in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        for name, item in read(path).get(bucket, {}).items():
            result[item["id"]] = {"kind": kind, "name": name,
                                   "source_facts": item.get("source_facts", ""),
                                   "design_description": item.get("design_description", ""),
                                   "gender": item.get("gender", "未知") if kind == "character" else None}
            for variant, derivative in item.get("derivatives", {}).items():
                result[derivative["id"]] = {"kind": kind, "name": f"{name}/{variant}"}
    return result


def _camera_execution(shot, cast, audio):
    """Translate storyboard shorthand into an executable live-action camera plan."""
    camera = shot.get("camera", {})
    movement = str(camera.get("movement", "locked camera"))
    lower = movement.lower()
    if any(word in lower for word in ("locked", "static", "tripod")):
        rig, axis, path, extent = "locked tripod", "none", "fixed camera position and orientation", "0 m"
    elif any(word in lower for word in ("crane", "jib", "boom")):
        rig, axis, path, extent = "crane or jib", "vertical Z with restrained arc", "smooth rising or descending arc", "0.8–1.5 m"
    elif any(word in lower for word in ("lateral", "truck", "sideways")):
        rig, axis, path, extent = "dolly rail", "lateral X", "straight lateral track parallel to the staging line", "0.4–0.9 m"
    elif any(word in lower for word in ("arc", "orbit")):
        rig, axis, path, extent = "curved dolly rail", "horizontal X/Y arc", "single shallow arc around the dramatic focus", "15–30 degrees"
    elif any(word in lower for word in ("push", "dolly in", "inward")):
        rig, axis, path, extent = "dolly rail", "forward Y", "straight optical-axis move toward the dramatic focus", "0.3–0.8 m"
    elif any(word in lower for word in ("pull", "dolly out", "backward")):
        rig, axis, path, extent = "dolly rail", "backward Y", "straight optical-axis move away from the dramatic focus", "0.4–1.0 m"
    elif "pan" in lower:
        rig, axis, path, extent = "fluid-head tripod", "yaw", "camera body remains fixed while panning", "10–30 degrees"
    elif "tilt" in lower:
        rig, axis, path, extent = "fluid-head tripod", "pitch", "camera body remains fixed while tilting", "10–25 degrees"
    elif any(word in lower for word in ("follow", "track")):
        rig, axis, path, extent = "stabilized tracking rig", "subject path", "parallel follow maintaining subject distance", "match subject travel"
    elif any(word in lower for word in ("handheld", "shoulder")):
        rig, axis, path, extent = "controlled shoulder rig", "human micro-drift", "operator follows blocking without reframing jumps", "under 5 cm micro-drift"
    else:
        rig, axis, path, extent = "stabilized dolly", "story-motivated path", movement, "under 0.8 m"

    size = str(camera.get("size", "medium shot"))
    close = "close" in size.lower()
    multi = len(cast) > 1
    has_dialogue = bool(shot.get("dialogue"))
    action_text = str(shot.get("action", ""))
    action_lower = action_text.lower()
    start_composition = (
        "keep every bound character in one shared frame, coherent scale and matching eyelines"
        if multi else
        "place the primary subject on a rule-of-thirds point with natural look room"
        if cast else
        "establish depth with foreground, midground and background anchors"
    )
    if "speaker-dominant" in size.lower():
        start_composition = ("the assigned speaker is the only fully visible face and mouth, centered in the focal plane; "
                             "the bound listener contributes one partial rear shoulder or back-of-head at the edge of frame, "
                             "with the listener's face completely hidden")
    elif "over-the-shoulder" in size.lower():
        start_composition = ("foreground listener occupies no more than 20% of frame; speaking character remains unobstructed, "
                             "both characters share one physical space and the camera stays on one side of the 180-degree axis")
    end_composition = ("settle on the reaction or revealed information and hold the final composition for the edit"
                       if movement.lower() not in ("locked camera", "static") else
                       "preserve the established composition and allow performance, not reframing, to carry the beat")
    if cast:
        # H3 otherwise treats a background plate as permission to cut away from
        # the bound bodies.  Character presence is a shot-level invariant: the
        # scene can breathe behind the performers, but it cannot replace them.
        if multi:
            start_composition = (
                "keep every bound character in one shared physical space, at a stable human scale, "
                "with both bodies visible from the first frame"
            )
        elif not has_dialogue:
            start_composition = (
                "keep the single bound character visibly present from the first frame, full or three-quarter body, "
                "feet grounded and at a stable human scale"
            )
        end_composition = (
            "hold the same bound character bodies and the same physical location through the final frame; "
            "the background may remain visible but may never take over the frame"
        )
        # “Emerges/follows” is a common source of reverse walking and scale
        # drift. Keep the authored movement, but make the physical direction
        # deterministic and disallow model-invented locomotion.
        if not has_dialogue:
            travel = bool(re.search(r"\b(?:walk|step|enter|emerge|approach|move)\b", action_lower)) or any(
                word in action_text for word in ("走", "进入", "走入", "走来", "飞", "腾云"))
            if travel:
                staging_lock = (
                    "The bound character(s) move only forward along the established screen direction, "
                    "never backward or in reverse playback; preserve constant body scale, feet-to-floor contact "
                    "and one continuous path, then stop in the final composition."
                )
            else:
                staging_lock = (
                    "The bound character(s) remain planted in the declared blocking unless the action explicitly "
                    "requires a step; no walking, reverse movement, floating, teleportation or scale change."
                )
        else:
            staging_lock = (
                "The bound speaking/listening character(s) stay in the declared blocking for the entire take; "
                "do not replace them with a background plate or a new body."
            )
    else:
        staging_lock = "No bound character is present; do not invent a foreground human identity."
    speakers = [item["speaker"] for item in audio]
    focus = (f"focus on the assigned speaker ({', '.join(speakers)}); rack focus only when the speaking turn changes"
             if speakers else "hold focus on the dramatic visual subject; do not hunt or pulse")
    if close:
        focus += "; keep the near eye sharp and preserve natural facial depth"
    fps = 24
    delivered = shot.get("frames", 5) - (22 if shot.get("continuity") == "continue" else 0)
    moving = rig != "locked tripod"
    prompt = (
        f"Use a {rig} with a {camera.get('lens_mm', 50)}mm lens at eye level relative to the primary subject. "
        f"Start: {start_composition}. Execute one {path} on {axis}, extent {extent}; "
        f"{'ease in over 12 frames, maintain an even physical speed, then ease out over the final 12 frames' if moving else 'no translation, rotation, zoom, roll or stabilization drift'}. "
        f"Focus: {focus}. End: {end_composition}. "
        f"{staging_lock} "
        "No unmotivated zoom, whip pan, orbit, drone rise, floating camera, axis crossing or mid-shot lens change."
    )
    return {
        "shot_size": size,
        "lens_mm": camera.get("lens_mm"),
        "camera_height": camera.get("height", "eye level relative to primary subject"),
        "rig": rig,
        "movement_name": movement,
        "movement_axis": axis,
        "physical_path": path,
        "movement_extent": extent,
        "frame_range": {"start": 0, "end": max(0, delivered), "fps": fps},
        "speed_curve": "locked" if not moving else "12-frame ease-in, constant middle, 12-frame ease-out",
        "start_composition": start_composition,
        "end_composition": end_composition,
        "focus_plan": focus,
        "screen_direction_and_axis": ("preserve the 180-degree line and matching eyelines" if multi else
                                      "preserve established screen direction"),
        "stabilization": "zero drift" if not moving else "cinematic inertia with no gimbal bob or floating correction",
        "motivation": camera.get("motivation"),
        "handoff_in": shot.get("handoff_in"),
        "handoff_out": shot.get("handoff_out"),
        "model_instruction": prompt,
        "reference_sources": CAMERA_SOURCES,
    }


def compile_package(root, shot, visual_assets, speech_bindings):
    """Bind each model input to one visual/audio role before prompt writing."""
    inventory = _inventory(root)
    speakers = {binding["asset_id"]: binding["speaker"] for binding in speech_bindings
                if binding.get("asset_id")}
    blocking_instances = {
        actor.get("asset_id"): int(actor.get("instances", 1))
        for actor in shot.get("blocking_plan", {}).get("actors", [])
    }
    visuals = []
    for index, resolved in enumerate(visual_assets, 1):
        meta = inventory.get(resolved["asset_id"], {"kind": "visual", "name": resolved["asset_id"]})
        role = meta["kind"]
        if role == "character":
            role = "visible_speaker" if resolved["asset_id"] in speakers else "visible_character"
        visuals.append({
            "asset_id": resolved["asset_id"],
            "name": meta["name"],
            "kind": meta["kind"],
            "source_facts": meta.get("source_facts", ""),
            "design_description": meta.get("design_description", ""),
            "gender": meta.get("gender") if meta["kind"] == "character" else None,
            "gender_prompt": gender_prompt(meta.get("gender", "未知")) if meta["kind"] == "character" else None,
            "role": role,
            "picture_label": f"Picture {index}",
            "subject_label": f"Subject {index}",
            "expected_instances": (blocking_instances.get(resolved["asset_id"], 1)
                                   if meta["kind"] == "character" else 1 if meta["kind"] == "prop" else None),
            "source_sha256": resolved["source_sha256"],
            "generation_reference": resolved["generation_path"],
            "generation_sha256": resolved["generation_sha256"],
            "reference_variant": resolved["variant"],
            "selected_character_view": resolved.get("selected_view"),
            "selected_character_view_label": resolved.get("selected_view_label"),
            "view_selection_reason": resolved.get("selected_view_reason"),
            "turnaround_master_asset_id": resolved.get("master_asset_id"),
        })
    audio = [{
        "speaker": binding["speaker"],
        "asset_id": binding.get("asset_id"),
        "collective": bool(binding.get("collective")),
        "audio_label": f"Audio {binding['audio']}",
        "speaker_label": binding["speaker_label"],
        "path": binding["path"],
        "sha256": binding["sha256"],
        "allowed_dialogue": [line["text"] for line in shot.get("dialogue", [])
                             if line["speaker"] == binding["speaker"]],
    } for binding in speech_bindings]
    cast = [item for item in visuals if item["kind"] == "character"]
    visible_body_count = sum(int(item.get("expected_instances") or 1) for item in cast)
    scenes = [item for item in visuals if item["kind"] == "scene"]
    speaking_names = {binding["speaker"] for binding in audio}
    listeners = [item["name"] for item in cast if item["name"] not in speaking_names]
    props = [item for item in visuals if item["kind"] == "prop"]
    picture_by_asset = {item["asset_id"]: item["picture_label"] for item in visuals}
    subject_by_asset = {item["asset_id"]: item["subject_label"] for item in visuals}
    audio_by_speaker = {item["speaker"]: item for item in audio}
    dialogue_events = []
    for index, line in enumerate(shot.get("dialogue", []), 1):
        speaker = str(line.get("speaker", ""))
        binding = audio_by_speaker.get(speaker)
        if line.get("kind") == "voiceover":
            dialogue_events.append({
                "event_id": f"D{index}", "kind": "voiceover", "speaker": speaker,
                "text": line.get("text", ""), "start_frame": line.get("start_frame"),
                "end_frame": line.get("end_frame"), "audio_label": binding.get("audio_label") if binding else None,
                "visual_subject": "offscreen narrator", "visual_picture": None,
                "mouth_owner": "none",
            })
            continue
        if not binding or not binding.get("asset_id"):
            # Collective auditions intentionally have no single character
            # asset or picture.  They are still a valid, explicitly bound
            # voice source; represent the event as the already-bound cast so
            # prompt compilation never indexes a missing subject_label.
            if binding and binding.get("collective"):
                dialogue_events.append({
                    "event_id": f"D{index}", "kind": line.get("kind", "dialogue"),
                    "speaker": speaker, "collective": True,
                    "audio_label": binding.get("audio_label"),
                    "speaker_label": binding.get("speaker_label"),
                    "subject_label": "bound collective cast",
                    "picture_label": "bound cast",
                    "text": line.get("text", ""),
                    "start_frame": line.get("start_frame"),
                    "end_frame": line.get("end_frame"),
                    "mouth_owner": "bound collective cast",
                    "listener_lips": "closed_and_occluded",
                })
                continue
            dialogue_events.append({
                "event_id": f"D{index}", "kind": line.get("kind", "dialogue"), "speaker": speaker,
                "text": line.get("text", ""), "start_frame": line.get("start_frame"),
                "end_frame": line.get("end_frame"), "binding_status": "unresolved",
                "mouth_owner": "unresolved",
            })
            continue
        asset_id = binding["asset_id"]
        picture = picture_by_asset.get(asset_id)
        subject = subject_by_asset.get(asset_id)
        if not picture or not subject:
            dialogue_events.append({
                "event_id": f"D{index}", "kind": line.get("kind", "dialogue"), "speaker": speaker,
                "text": line.get("text", ""), "start_frame": line.get("start_frame"),
                "end_frame": line.get("end_frame"), "binding_status": "unresolved",
                "mouth_owner": "unresolved",
            })
            continue
        dialogue_events.append({
            "event_id": f"D{index}", "kind": line.get("kind", "dialogue"), "speaker": speaker,
            "asset_id": asset_id, "subject_label": subject, "picture_label": picture,
            "audio_label": binding["audio_label"], "speaker_label": binding["speaker_label"],
            "text": line.get("text", ""), "start_frame": line.get("start_frame"),
            "end_frame": line.get("end_frame"), "mouth_owner": subject,
            "listener_lips": "closed_and_occluded" if len(cast) > 1 else "closed",
        })
    # Keep visual identity, speaking role, picture ordinal and voice ordinal in
    # one immutable table.  H3 receives multiple reference images and can
    # otherwise satisfy the prose instruction with the wrong face or by
    # inventing a second copy of the listener.
    identity_bindings = []
    for item in cast:
        voice = next((entry for entry in audio if entry.get("asset_id") == item["asset_id"]), None)
        identity_bindings.append({
            "asset_id": item["asset_id"],
            "name": item["name"],
            "picture_label": item["picture_label"],
            "subject_label": item["subject_label"],
            "role": "speaker" if voice else "listener",
            "speaks": bool(voice),
            "audio_label": voice["audio_label"] if voice else None,
            "speaker_label": voice["speaker_label"] if voice else None,
            "selected_character_view": item.get("selected_character_view"),
            "selected_character_view_label": item.get("selected_character_view_label"),
            "gender": item.get("gender", "未知"),
            "gender_prompt": item.get("gender_prompt"),
            "design_description": item.get("design_description", ""),
        })
    camera_execution = _camera_execution(shot, cast, audio)
    character_policy = character_visibility_policy(len(cast), bool(shot.get("dialogue")))
    visible_dialogue = any(
        line.get("kind") != "voiceover" and str(line.get("text", "")).strip()
        for line in shot.get("dialogue", [])
    )
    over_shoulder = len(cast) > 1 and ("over-the-shoulder" in str(shot.get("camera", {}).get("size", "")).lower()
                                       or "过肩" in str(shot.get("camera", {}).get("size", "")))
    package = {
        "schema": "h3_asset_bound_shot_v2",
        "shot_id": shot["id"],
        "source_ids": shot.get("source_ids", []),
        "storyboard": {
            "dramatic_action": str(shot.get("action", "")) + bound_character_action_contract(shot, len(cast)),
            "camera": shot.get("camera"),
            "timeline": shot.get("timeline", []),
            "screenplay_beat": {
                key: shot.get(key) for key in (
                    "storyboard_schema", "sequence_id", "beat_function", "state_in", "state_out",
                    "screen_direction", "axis_id", "transition", "blocking_plan", "composition",
                    "action_beats",
                ) if shot.get(key) is not None
            },
            "scene_id": shot.get("scene_id"),
            "continuity": shot.get("continuity"),
            "handoff_in": shot.get("handoff_in"),
            "handoff_out": shot.get("handoff_out"),
            "frames": shot.get("frames"),
            "fps": 24,
        },
        "camera_execution": camera_execution,
        "scene_continuity_contract": shot.get("scene_continuity_contract", {}),
        "scene_anchor": ({
            "asset_id": scenes[0]["asset_id"],
            "name": scenes[0]["name"],
            "picture_label": scenes[0]["picture_label"],
            "subject_label": scenes[0]["subject_label"],
            "generation_reference": scenes[0]["generation_reference"],
            "environment_design": next((item.get("design_description", "") for item in visuals
                                         if item["asset_id"] == scenes[0]["asset_id"]), ""),
            "role": "exclusive_background_plate",
            "priority": "highest_visual_priority",
            "background_only": True,
            "may_fill_frame_during_dialogue": False if cast else True,
            "may_replace_bound_characters": False if cast else True,
            "presence_rule": (
                "At least one bound character must remain visible in every frame; the scene plate is background only."
                if cast else "Environment-only framing is allowed because no character is bound."
            ),
        } if len(scenes) == 1 else None),
        "visual_assets": visuals,
        "audio_bindings": audio,
        "identity_bindings": identity_bindings,
        "character_identity_lock": {
            "present_time_only": bool(shot.get("dialogue")),
            "no_flashback_or_apparition": bool(shot.get("dialogue")),
            "no_duplicate_or_third_body": bool(shot.get("dialogue")),
            "instruction": (
                "Dialogue is performed in the declared present-time blocking. "
                "Recounted events remain visual reference only: never create a flashback, memory, apparition, "
                "vision, insert portrait, symbolic duplicate or additional human body unless that asset is explicitly bound."
                if shot.get("dialogue") else ""
            ),
        },
        "visible_character_count": len(cast),
        "visible_body_count": visible_body_count,
        "visible_characters": [item["name"] for item in cast],
        "character_visibility_policy": character_policy,
        "character_gender_contract": [
            {"asset_id": item["asset_id"], "name": item["name"],
             "gender": item.get("gender", "未知"),
             "instruction": item.get("gender_prompt") or gender_prompt("未知")}
            for item in cast
        ],
        "interaction_contract": {
            "mode": "multi_character" if len(cast) > 1 else "single_character" if cast else "environment_only",
            "all_bound_characters_visible_in_same_physical_space": len(cast) > 1,
            "speakers": sorted(speaking_names),
            "visible_listeners": listeners,
            "speaker_visual_bindings": [
                {"speaker": entry["speaker"], "asset_id": entry.get("asset_id"),
                 "picture_label": next((item["picture_label"] for item in identity_bindings
                                         if item["asset_id"] == entry.get("asset_id")), None),
                 "audio_label": entry["audio_label"]}
                for entry in audio
            ],
            "speaker_only_moves_mouth_during_dialogue": True,
            "listener_reacts_with_closed_lips": bool(listeners),
            "allowed_character_asset_ids": [item["asset_id"] for item in cast],
            "max_visible_human_bodies": visible_body_count,
            "unregistered_humans_allowed": False if cast else True,
            "over_shoulder_foreground_listener_only": over_shoulder,
            "blocking_source": shot.get("action"),
            "dialogue_event_bindings": dialogue_events,
            "speaker_face_ownership": "one_event_one_bound_picture",
            "listener_face_policy": ("rear_or_occluded; no full frontal listener face during a speaking event"
                                      if shot.get("dialogue") and len(cast) > 1 else "closed_lips"),
            "silent_bound_characters": not bool(shot.get("dialogue")),
            "no_dialogue_mouth_movement": not bool(shot.get("dialogue")),
            "human_voice_allowlist": sorted(speaking_names),
            "dialogue_framing": {
                "enabled": visible_dialogue,
                "policy": "single_uninterrupted_take" if visible_dialogue else "not_applicable",
                "speaker_visible_throughout_dialogue_windows": visible_dialogue,
                "no_environment_only_cutaway_during_dialogue": visible_dialogue,
            },
            "character_presence_required": bool(cast),
            "bound_character_presence_every_frame": bool(cast),
            "no_background_takeover": bool(cast),
            "no_reverse_or_scale_drift": bool(cast),
        },
        "prop_contract": {
            "count": len(props),
            "assets": [item["name"] for item in props],
            "preserve_ownership_position_and_state": bool(props),
        },
        "dialogue": [{key: line.get(key) for key in ("kind", "speaker", "text", "start_frame", "end_frame")}
                     for line in shot.get("dialogue", [])],
        "dialogue_event_bindings": dialogue_events,
        "audio_policy": "dialogue_and_diegetic_sfx" if shot.get("dialogue") else "diegetic_only",
        "audio_contract": {
            "schema": "H3_AUDIO_SCHEMA_V4" if shot.get("dialogue") else "H3_AUDIO_SCHEMA_V3",
            "mode": "dialogue_and_diegetic_effects" if shot.get("dialogue") else "diegetic_effects_only",
            "human_voice_allowlist": sorted(speaking_names),
            "dialogue_source": "explicit_d_blocks" if shot.get("dialogue") else [],
            "narration": "explicit_voiceover_only" if shot.get("dialogue") else "disabled",
            "reference_audio_input": "bound_speaker_only" if shot.get("dialogue") else "none",
            "mouth_audio_link": "speaker_event_only" if shot.get("dialogue") else "off",
            "fallback": "silence_human_voice_channel" if not shot.get("dialogue") else "silence_unmatched_line",
        },
        "visual_narration_policy": {
            "used_for_storyboard_only": bool(shot.get("visual_narration")),
            "included_in_h3_prompt": False,
        },
        "constraints": [
            "Each bound character or prop appears at most once unless the storyboard explicitly lists multiple assets.",
            "Reference-sheet panels, inset portraits, mirrors, twins and cloned duplicates are never reproduced.",
            "For each character, use only the bound independent view image recorded above; never send or recreate the four-panel master sheet.",
            "Character gender is a locked visual attribute recorded in character_gender_contract; never change it, infer another gender, or vocalize this metadata.",
            "Only bound dialogue and its bound reference audio may produce speech.",
            "When this shot has no dialogue, the human-voice allowlist is empty: all bound characters are silent visual bodies with closed or neutral mouths, and no reference audio may be emitted.",
            "Preserve screen direction, eyeline, pose, prop state and environment anchors across the declared handoff.",
            "Do not add an unbound character, prop, readable text, line of dialogue or sound source.",
            "A multi-character interaction stays in one physical composition; do not replace it with isolated solo portraits.",
            "The total visible human-body count equals the bound cast count; a foreground shoulder is part of its bound listener, never a new subject.",
            "Every dialogue event has exactly one visual mouth owner and one matching reference audio; never infer a mouth owner from the voice alone.",
            "During a speaking event, the assigned picture is the only fully visible moving mouth; listener faces are rear-facing, occluded or closed-lipped.",
            "The scene anchor is the exclusive background plate and has highest visual priority; never import a character-reference background.",
            character_policy,
        ],
    }
    if shot.get("storyboard_schema"):
        package["storyboard"]["design_version"] = shot["storyboard_schema"]
        package["quality_standard"] = {
            "source_grounding": "exact source paragraph and verbatim dialogue only",
            "blocking": shot.get("blocking_plan", {}),
            "continuity": {
                "sequence_id": shot.get("sequence_id"),
                "axis_id": shot.get("axis_id"),
                "screen_direction": shot.get("screen_direction"),
                "transition": shot.get("transition"),
                "state_in": shot.get("state_in"),
                "state_out": shot.get("state_out"),
            },
            "camera_composition": shot.get("composition", {}),
            "visual_review_required": [
                "actor count and identity throughout the full shot",
                "speaker mouth/voice ownership",
                "environment anchor and empty-frame check",
                "screen direction, eyeline and action handoff",
                "prop state, size continuity and motivated camera movement",
            ],
        }
    if visible_dialogue:
        package["constraints"].extend([
            "Dialogue coverage is a single uninterrupted take with no internal editorial cuts.",
            "Keep the assigned speaker's bound face and upper torso visibly in frame during every dialogue window and during the pauses between windows.",
            "The environment reference is a background layer only; never show it alone during dialogue. No empty hall, empty room, throne-only, prop-only, ceiling, floor, corridor, listener-only or wide establishing cutaway.",
        ])
    if cast:
        package["constraints"].extend([
            "Bound-character presence is a hard frame-level invariant: at least one bound character remains visible in every frame; the environment plate may never replace the cast.",
            "Keep every bound body at a stable human scale with grounded feet and continuous physical blocking; never shrink, grow, float, teleport, reverse-walk or play motion backward.",
            "No environment-only, architecture-only or empty-hall frame is permitted in a shot that binds a character, including silent visual shots.",
            "No unregistered human, duplicate, replacement identity, reflection or background silhouette may enter a bound-character shot.",
        ])
    # Do not change ordinary-shot fingerprints when the retake-only contract
    # is absent. These fields are emitted only for a structural speaker fix.
    if shot.get("speaker_focus_mode") == "speaker_dominant":
        package["interaction_contract"].update(
            speaker_focus_mode="speaker_dominant",
            speaker_focus_name=shot.get("speaker_focus_name"),
            listener_face="hidden",
        )
        package["constraints"].append(
            "For a speaker-dominant retake, the assigned speaker is the only fully visible face and moving mouth; "
            "the bound listener's face remains hidden behind one partial rear shoulder or back-of-head."
        )
    # Do not alter the fingerprint of existing ordinary takes. A review note
    # is added only for an actual retake request.
    if shot.get("review_note"):
        package["storyboard"]["retake_review_note"] = shot["review_note"]
        package["retake_review_note"] = shot["review_note"]
    return package
