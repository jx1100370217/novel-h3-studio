"""Continue whole-book preparation without touching the active render queue.

The output is deliberately a preparation queue: source-speaker attribution and
asset approval remain explicit gates, so a candidate work order cannot silently
become a renderable episode.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from novel_h3.project import read, write, file_hash
from novel_h3.timing import semantic_chunks, speech_seconds
from novel_h3.storyboard_design import AUTHORING_RULES, VERSION


ROOT = Path(__file__).resolve().parent / "projects/rendao-wuji"
OUT = ROOT / "analysis" / "full_book_workorders"


def _voice_bindings(assets: dict, voices: dict) -> int:
    """Attach an auditable reference_audio record to every character card."""
    changed = 0
    for name, card in assets.get("characters", {}).items():
        voice = voices.get(name)
        if not voice:
            continue
        record = {
            "voice_id": name,
            "path": voice.get("path"),
            "sha256": voice.get("sha256"),
            "approved": bool(voice.get("approved")),
            "status": "approved" if voice.get("approved") else "bound_pending_review",
            "source": "bible/voices.json",
        }
        if card.get("reference_audio") != record:
            card["reference_audio"] = record
            changed += 1
    return changed


def _asset_ids(text: str, assets: dict) -> list[str]:
    result = []
    for bucket in ("characters", "scenes", "props"):
        for name, item in assets.get(bucket, {}).items():
            if name in text or any(alias in text for alias in item.get("aliases", [])):
                result.append(item["id"])
    return list(dict.fromkeys(result))


def _visual_order(utterance: dict, paragraph_text: str, assets: dict) -> dict:
    scene_ids = []
    prop_ids = []
    for name, item in assets.get("scenes", {}).items():
        if name in paragraph_text or any(alias in paragraph_text for alias in item.get("aliases", [])):
            scene_ids.append(item["id"])
    for name, item in assets.get("props", {}).items():
        if name in paragraph_text or any(alias in paragraph_text for alias in item.get("aliases", [])):
            prop_ids.append(item["id"])
    dialogue = utterance["kind"] == "dialogue"
    speaker_card = assets.get("characters", {}).get(utterance["speaker"], {}) if dialogue else {}
    character_ids = [speaker_card["id"]] if speaker_card.get("id") else []
    return {
        "h3_mode": "ref2va",
        "scene_asset_ids": list(dict.fromkeys(scene_ids)),
        "character_asset_ids": character_ids,
        "prop_asset_ids": list(dict.fromkeys(prop_ids)),
        "camera": {
            "size": "medium close-up" if dialogue else "wide establishing shot",
            "lens_mm": 65 if dialogue else 35,
            "movement": "slow motivated dolly or lateral track",
            "motivation": "follow the assigned speaker" if dialogue else "reveal the narrated action",
        },
        "speech_visibility": (f"仅 {utterance['speaker']} 可见口型并发声；其他人物闭口。"
                              if dialogue else "旁白画外发声；画面内人物不得出现与旁白同步的口型。"),
        "continuity": "cut",
        "asset_status": "pending_visual_asset_review",
    }


def _candidate_timing(text: str) -> dict:
    try:
        parts = semantic_chunks(text)
    except ValueError:
        # Keep a long uninterrupted clause intact for a human editor; never
        # invent a punctuation boundary in the source text.
        parts = [text]
    durations = [min(15.0, max(0.6, speech_seconds(part) + 0.6)) for part in parts]
    return {
        "parts": len(parts),
        "durations_seconds": [round(x, 3) for x in durations],
        "max_duration_seconds": round(max(durations, default=0), 3),
        "max_frames": 362,
        "status": "candidate_pending_semantic_review",
    }


def _speaker_candidate(text: str, known_names: list[str]) -> tuple[list[dict], int]:
    """Extract quote spans and conservative local speaker candidates.

    A quote is only assigned when the same paragraph contains one unique named
    character in an attribution clause. Otherwise it stays explicitly pending;
    this is safer than guessing from a pronoun or a distant paragraph.
    """
    rows: list[dict] = []
    unresolved = 0
    pieces = re.findall(r"“[^”]*”|[^“]+", text)
    attribution_text = "".join(piece for piece in pieces if not piece.startswith("“"))
    for piece in pieces:
        quoted = piece.startswith("“")
        spoken = piece.strip("“”")
        if not spoken:
            continue
        if not quoted:
            rows.append({"kind": "voiceover", "speaker": "旁白", "text": spoken,
                         "speaker_status": "source_reviewed_narration"})
            continue
        # Names inside the spoken words (for example, “我叫振明”) are not
        # attribution evidence. Only text outside quotation marks may name the
        # speaker, and multiple names remain unresolved for source review.
        hits = [name for name in known_names if name in attribution_text]
        # Names appearing only once and in the attribution tail are usable; a
        # paragraph containing multiple characters needs source review.
        unique = list(dict.fromkeys(hits))
        if len(unique) == 1:
            speaker, status = unique[0], "local_attribution_candidate"
        else:
            speaker, status = "说话人待原文核对", "unresolved_quote_speaker"
            unresolved += 1
        rows.append({"kind": "dialogue", "speaker": speaker, "text": spoken,
                     "speaker_status": status})
    if not rows:
        rows.append({"kind": "voiceover", "speaker": "旁白", "text": text,
                     "speaker_status": "source_reviewed_narration"})
    return rows, unresolved


def _write_candidate(chapter: dict, paragraphs: list[dict], assets: dict, voices: dict, output_dir=None) -> dict:
    cid = chapter["id"]
    reviewed_path = (output_dir or OUT).parent / f"chapter_{cid}_reviewed_workorder.json"
    if reviewed_path.exists():
        reviewed = read(reviewed_path)
        reconstructed = ''.join(x.get('text', '') for x in reviewed.get('source_reconstruction', []))
        source = ''.join(p['text'].replace('“', '').replace('”', '') for p in paragraphs)
        if reviewed.get('source_coverage_verified') and reconstructed == source:
            value = dict(reviewed, candidate_shots=len(reviewed['scenes']),
                         status='source_reviewed_pending_visual_and_voice',
                         speaker_unresolved_quotes=0)
            write((output_dir or OUT) / f"{cid}.json", value)
            return {'chapter':cid, 'title':chapter.get('title'), 'source_paragraphs':len(paragraphs),
                    'candidate_shots':len(reviewed['scenes']), 'speaker_unresolved_quotes':0,
                    'status':value['status']}
    known = sorted(assets.get("characters", {}), key=len, reverse=True)
    scenes = []
    unresolved = 0
    total_parts = 0
    for index, paragraph in enumerate(paragraphs, 1):
        utterances, count = _speaker_candidate(paragraph["text"], known)
        unresolved += count
        timing = _candidate_timing(paragraph["text"])
        total_parts += timing["parts"]
        for utterance in utterances:
            try:
                parts = semantic_chunks(utterance['text'])
                timing_status = 'candidate_pending_semantic_review'
            except ValueError:
                parts = [utterance['text']]
                timing_status = 'blocked_long_clause_needs_editor'
            for part in parts:
                seconds = round(max(1.0, speech_seconds(part) + .6), 3)
                scene_id = f"{cid.upper()}_P{index:04d}_{len(scenes)+1:04d}"
                scenes.append({
                    'scene_id': scene_id, 'source_ids': [paragraph['id']],
                    'source_text': part, 'utterances': [dict(utterance, text=part)],
                    'duration_seconds': seconds,
                    'asset_ids': _asset_ids(paragraph['text'], assets),
                    'visual_order': _visual_order(utterance, paragraph['text'], assets),
                    'timing': {'status': timing_status, 'max_seconds': 15,
                               'requires_split': seconds > 15},
                    'status': 'candidate_pending_speaker_and_visual_review',
                })
    speakers = sorted({u["speaker"] for s in scenes for u in s["utterances"]
                       if u["kind"] == "dialogue" and u["speaker"] != "说话人待原文核对"})
    voice_rows = []
    for name in speakers:
        voice = voices.get(name)
        voice_rows.append({"speaker": name, "path": voice.get("path") if voice else None,
                           "sha256": voice.get("sha256") if voice else None,
                           "approved": bool(voice and voice.get("approved")),
                           "status": "ready_for_voice_gate" if voice and voice.get("approved") else "pending_voice_review"})
    value = {
        "chapter": cid,
        "title": chapter.get("title"),
        "source_paragraphs": len(paragraphs),
        "source_chars": sum(len(p["text"]) for p in paragraphs),
        "candidate_shots": len(scenes),
        "candidate_timing_units": total_parts,
        "speaker_unresolved_quotes": unresolved,
        "all_source_paragraphs_included": True,
        "status": "candidate_pending_source_speaker_visual_review",
        "storyboard_design_version": VERSION,
        "authoring_rules": AUTHORING_RULES,
        "adaptation_gate": {
            "source_reconstruction_required": True,
            "dramatic_question_required": True,
            "causal_scene_beats_required": True,
            "each_shot_claims_source_facts": True,
            "no_paragraph_equals_shot_assumption": True,
            "no_visual_event_without_source_or_explicit_adaptation_note": True,
            "exact_dialogue_and_speaker_review_required": True,
            "status": "candidate_pending_editorial_authoring",
        },
        "policy": "保留原文逐字证据；未核对的对白不进入正式生成队列。先完成因果场景节拍，再按可演动作/对白时长拆镜；不再默认一段原文等于一个镜头。单镜头不超过362帧（约15秒）。",
        "voice_bindings": voice_rows,
        "scenes": scenes,
    }
    write((output_dir or OUT) / f"{cid}.json", value)
    return {"chapter": cid, "title": chapter.get("title"), "source_paragraphs": len(paragraphs),
            "candidate_shots": len(scenes), "speaker_unresolved_quotes": unresolved,
            "status": value["status"]}


def _write_reblocked_visual_sidecar(cid: str, assets: dict, voices: dict) -> None:
    """Persist visual-sidecar work orders for the next candidate chapters."""
    source = ROOT / "analysis" / "rhythm_candidates" / f"chapter_{cid}_reblocked_candidate.json"
    if not source.exists():
        return
    candidate = read(source)
    shots = []
    speakers = set()
    for scene in candidate.get("script", {}).get("scenes", []):
        utterance = (scene.get("utterances") or [{"kind": "voiceover", "speaker": "旁白", "text": scene.get("source_text", "")}])[0]
        if utterance.get("kind") == "dialogue":
            speakers.add(utterance.get("speaker"))
        visual = _visual_order(utterance, scene.get("source_text", ""), assets)
        shots.append({
            "shot": scene["scene_id"],
            "source_ids": candidate.get("source_map", {}).get(scene["scene_id"], []),
            "speaker": utterance.get("speaker"),
            "kind": utterance.get("kind"),
            "source_text": scene.get("source_text"),
            "duration_seconds": scene.get("duration_seconds"),
            "visual_order": visual,
            "status": "candidate_pending_visual_asset_review",
        })
    voice_audit = []
    for name in sorted(speakers):
        voice = voices.get(name, {})
        voice_audit.append({"character": name, "path": voice.get("path"),
                            "sha256": voice.get("sha256"), "approved": bool(voice.get("approved")),
                            "status": "ready_for_voice_gate" if voice.get("approved") else "pending_voice_review"})
    write(ROOT / "analysis" / "rhythm_candidates" / f"chapter_{cid}_visual_workorder.json", {
        "chapter": cid,
        "status": "candidate_pending_rhythm_source_visual_review",
        "timing_policy": {"max_frames": 362, "max_seconds": 15, "content_based": True},
        "source_and_speakers_unchanged": candidate.get("rhythm_review", {}).get("source_and_speakers_unchanged", True),
        "voice_audit": voice_audit,
        "shots": shots,
        "asset_gate_note": "候选工作单保留原文与说话人绑定；图像和参考音频未批准前不会进入正式提交队列。",
    })


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    book = read(ROOT / "book.json")
    paragraphs = read(ROOT / "paragraphs.json")
    assets = read(ROOT / "bible/assets.json")
    voices = read(ROOT / "bible/voices.json")
    state = read(ROOT / "state.json")
    changed_cards = _voice_bindings(assets, voices)
    write(ROOT / "bible/assets.json", assets)

    asset_completion = {}
    for bucket in ("characters", "scenes", "props"):
        registered = []
        unregistered = []
        approved = []
        for name, item in assets.get(bucket, {}).items():
            aid = item["id"]
            if aid in state.get("assets", {}):
                registered.append(aid)
                if state["assets"][aid].get("approved"):
                    approved.append(aid)
            else:
                unregistered.append(aid)
        asset_completion[bucket] = {"inventory": len(assets.get(bucket, {})),
                                    "registered": len(registered), "approved": len(approved),
                                    "unregistered": unregistered}

    by_section: dict[str, list[dict]] = {}
    for paragraph in paragraphs:
        by_section.setdefault(paragraph["section"], []).append(paragraph)
    existing = {p.stem.removeprefix("chapter_") for p in (ROOT / "content_plans").glob("chapter_*.json")}
    rows = []
    for chapter in book["chapters"]:
        if chapter.get("kind") != "story":
            continue
        cid = chapter["id"]
        if cid in existing:
            continue
        rows.append(_write_candidate(chapter, by_section.get(cid, []), assets, voices))
    for cid in ("s0005", "s0007"):
        _write_reblocked_visual_sidecar(cid, assets, voices)
    report = {
        "source_sha256": book["source_sha256"],
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "character_cards_with_reference_audio": len([c for c in assets.get("characters", {}).values() if c.get("reference_audio")]),
        "reference_audio_cards_updated": changed_cards,
        "candidate_chapters_written": len(rows),
        "candidate_shots_written": sum(r["candidate_shots"] for r in rows),
        "unresolved_quote_speakers": sum(r["speaker_unresolved_quotes"] for r in rows),
        "asset_completion": asset_completion,
        "existing_formal_content_plans": sorted(existing),
        "chapters": rows,
        "gates": [
            "角色声音必须逐角色实听并批准后才可提交 VDN-H3",
            "引号内对白若未能在同段落确定说话人，必须人工对照原文",
            "视觉资产必须登记并通过审阅；候选工作单不改变生成队列",
            "时长按语义和对白估算，单镜头最多362帧，超限必须按语义拆分",
        ],
    }
    write(ROOT / "analysis/full_book_preparation_queue.json", report)
    print(json.dumps({k: report[k] for k in (
        "character_cards_with_reference_audio", "reference_audio_cards_updated",
        "candidate_chapters_written", "candidate_shots_written", "unresolved_quote_speakers")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
