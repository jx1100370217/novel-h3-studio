"""Build a source-reviewed screenplay/shot work order for s0004.

This creates the next chapter's content and visual contracts without submitting
it to ComfyUI. Every quoted line receives an explicit speaker; prose remains
voiceover until a later source review changes it.
"""
import copy
import re
from pathlib import Path

from novel_h3.project import read, write, digest
from novel_h3.timing import semantic_chunks, editorial_seconds
from novel_h3.arcreel import save_content, approve_content, compile_visual

ROOT = Path(__file__).parent / "projects/rendao-wuji"
SPEAKERS = {
    8: "西极勾陈大帝", 9: "玉皇大帝", 13: "玉皇大帝", 14: "北极紫微大帝",
    15: "西极勾陈大帝", 16: "南极长生大帝", 17: "东极青华大帝",
    18: "东华大帝", 19: "西王母", 20: "华光大帝", 21: "东极青华大帝",
    22: "斗母大帝", 23: "玉皇大帝",
}
CHAR_IDS = {
    "北极紫微大帝": "character_93b966efaf19", "南极长生大帝": "character_7ed17f1bbb66",
    "东极青华大帝": "character_b1fb054be063", "西极勾陈大帝": "character_a2d1af16ecf6",
    "玉皇大帝": "jade_emperor", "华光大帝": "character_ed416bf79c32",
    "东华大帝": "character_518318dd6fbe", "斗母大帝": "character_139e13ad54e6",
    "西王母": "character_712831b52e0c",
}
SCENE_ID = "scene_a1c8c45145a6"


def chunks(text):
    return semantic_chunks(text)


def h3_for(scene_id, speaker, text, refs, seed):
    dialogue = bool(speaker)
    action = (
        "A restrained photorealistic Chinese mythological period-film shot inside the registered Taiwei Hall. "
        "Preserve the palace geometry, stone steps, pillars and warm daylight. "
        + ("Only the assigned speaker appears in a medium close-up; only this person's mouth articulates the exact line. "
           "No other person speaks. " if dialogue else
           "Show the empty hall or distant figures without visible mouth movement; the narrator remains off-screen. ")
        + "Keep movement physically grounded and leave no text or labels in frame."
    )
    beats = [{"start_frame": i, "end_frame": min(i + 24, 124),
              "description": "Slow motivated camera drift, natural cloth and cloud movement; no extra speech."}
             for i in range(0, 124, 24)]
    refs_h3 = [{"asset_id": aid, "description": "the same registered visual identity", "lock": "preserve identity and costume"}
               for aid in refs]
    return {
        "location_id": SCENE_ID, "mode": "ref2va", "continuity": "cut", "seed": seed,
        "hold_frames": 0, "first_frame": None, "last_frame": None, "references": refs_h3,
        "dramatic_function": f"完整呈现 {scene_id}；{speaker or '旁白'} 发声。", "action": action,
        "camera": {"size": "medium close-up" if dialogue else "wide shot", "lens_mm": 65 if dialogue else 35,
                    "movement": "slow dolly with a slight lateral drift", "motivation": "follow the revelation"},
        "handoff_in": "Natural cut within Taiwei Hall.",
        "handoff_out": "The hall holds the new information before the next cut.", "timeline": beats,
        "soundscape": "Quiet palace room tone, restrained cloth movement and distant wind. Only the explicitly assigned voice speaks; no music.",
    }


def run():
    paras = {p["id"]: p for p in read(ROOT / "paragraphs.json") if p["section"] == "s0004"}
    plan = {"id": "chapter_s0004", "release_role": "episode",
            "dramatic_question": "两道金光为何撼动五界，九帝能否在失控前找到源头？",
            "turning_point": "三清带来鸿钧神识，众帝得知两道金光与三皇应劫转世有关。",
            "script": {"title": "第二节：四界九帝", "scenes": []}, "source_map": {},
            "speaker_audit": {"status": "reviewed", "reviewer": "Codex 原文逐段审读", "scenes": {}},
            "rhythm_review": {"version": 2, "reviewed": True,
                              "policy": "同一说话人的连续表达按完整语义组织；说话人变化、动作转折和场景切换保留剪辑；单镜头上限15秒。"}}
    visual = []
    n = 0
    for pnum in range(1, 24):
        pid, source = f"s0004_p{pnum:04d}", paras[f"s0004_p{pnum:04d}"]["text"]
        for piece in re.findall(r"“[^”]*”|[^“]+", source):
            quoted = piece.startswith("“")
            text = piece.strip("“”")
            speaker = SPEAKERS.get(pnum) if quoted else None
            for text_part in chunks(text):
                n += 1
                sid = f"C4P{pnum:02d}_{n:02d}"
                refs = [SCENE_ID]
                chars = []
                if speaker:
                    chars = [speaker]
                    refs.insert(0, CHAR_IDS[speaker])
                scene = {"scene_id": sid, "duration_seconds": editorial_seconds(text_part), "segment_break": True,
                         "characters_in_scene": chars, "scenes": ["太微殿"], "props": [],
                         "scene_description": "写实中国神话宫殿内景，严格按注册场景与角色资产保持身份连续；说话人单独入镜，旁白不显示说话者。",
                         "utterances": [{"kind": "dialogue" if speaker else "voiceover", "speaker": speaker or "旁白", "text": text_part}],
                         "source_text": text_part, "needs_replan": False}
                plan["script"]["scenes"].append(scene)
                plan["source_map"][sid] = [pid]
                plan["speaker_audit"]["scenes"][sid] = [{**scene["utterances"][0],
                    "reason": f"s0004_p{pnum:04d} 引号内由段落主语明确归属；引号外按原文叙述归为旁白。", "source_ids": [pid]}]
                h3 = h3_for(sid, speaker, text_part, refs, 520000 + n)
                visual.append({"scene_id": sid, "image_prompt": h3["action"], "h3": h3,
                               "speech_timing": [{"start_frame": 8, "end_frame": 118}]})
    save_content(ROOT, plan)
    approve_content(ROOT, plan["id"], "Codex", "s0004 逐段保留原文；引号内对白按段落主语逐句登记，旁白与角色对白分离。")
    source_sequence_verified = all(
        ''.join(s['source_text'] for s in plan['script']['scenes']
                if plan['source_map'][s['scene_id']][0] == pid) == re.sub(r'[“”]', '', paras[pid]['text'])
        for pid in paras)
    if not source_sequence_verified:
        raise ValueError('s0004 source sequence changed during rhythm reblock')
    result = {"content_sha256": digest(plan), "scenes": visual,
              "source_sequence_verified": True}
    write(ROOT / "analysis/chapter_s0004_speaker_visual.json", result)
    # The shot table is persisted even while cast audio is pending. The normal
    # compiler intentionally refuses to create a renderable episode until every
    # speaking character's reference file is approved.
    compile_error = None
    try:
        compile_visual(ROOT, plan["id"], result)
    except ValueError as exc:
        compile_error = str(exc)
    write(ROOT / "analysis/chapter_s0004_workorder.json", {"chapter": "s0004", "shots": len(visual),
          "source_paragraphs": len(paras), "all_utterances_have_speaker": True,
          "voice_review_required_before_render": True,
          "rhythm_review": {"version": 2, "reviewed": True, "semantic_split": True,
                            "max_seconds": 15, "source_sequence_verified": source_sequence_verified},
          "status": "script_and_storyboard_ready_pending_voice_asset_review",
          "compile_status": "blocked_by_unapproved_voice_refs" if compile_error else "compiled",
          "compile_note": compile_error})
    print(f"s0004 work order ready: {len(visual)} shots")


if __name__ == "__main__":
    run()
