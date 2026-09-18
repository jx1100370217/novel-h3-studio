"""Build the next source-reviewed screenplay/shot work order (s0005)."""
from novel_h3.timing import editorial_seconds
import re
import hashlib
from pathlib import Path

from novel_h3.project import read, write, digest
from novel_h3.arcreel import save_content, approve_content, compile_visual
from build_chapter_s0004_workorder import chunks, h3_for, SCENE_ID, CHAR_IDS

ROOT = Path(__file__).parent / "projects/rendao-wuji"
SPEAKERS = {
    1: "道德天尊", 3: "三清与九帝（齐声）", 5: "元始天尊", 8: "三清与九帝（齐声）",
    9: "鸿钧老祖", 10: "鸿钧老祖", 11: "鸿钧老祖", 12: "鸿钧老祖",
    13: "玉皇大帝", 14: "鸿钧老祖", 15: "鸿钧老祖",
}
CHAR_IDS.update({"元始天尊": "yuanshi_tianzun", "灵宝天尊": "lingbao_tianzun",
                 "道德天尊": "daode_tianzun", "鸿钧老祖": "hongjun"})


def run():
    voices = read(ROOT / "bible/voices.json")
    if "三清与九帝（齐声）" not in voices:
        path = ROOT / "voices/pangu.wav"
        voices["三清与九帝（齐声）"] = {
            "asset_id": None, "identity": "三清与九帝（齐声）", "collective": True,
            "path": "voices/pangu.wav", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": str(path), "transcript": "仅作为集体发声的音色基准，不复制参考台词。",
            "approved": False, "selection_status": "pending_collective_voice_design",
            "selection_note": "原文明确写‘齐声’，保留为集体发声；需要后续合成或审听后才能生成。"
        }
        write(ROOT / "bible/voices.json", voices)
    paras = {p["id"]: p for p in read(ROOT / "paragraphs.json") if p["section"] == "s0005"}
    plan = {"id": "chapter_s0005", "release_role": "episode",
            "dramatic_question": "三皇转世与六界失衡的真相是什么，仙道能否守住浩劫边界？",
            "turning_point": "鸿钧神识揭示无界、轮回与两道金光的关系，并警告无极与女娲不可入魔。",
            "script": {"title": "第三节：三清一祖", "scenes": []}, "source_map": {},
            "speaker_audit": {"status": "reviewed", "reviewer": "Codex 原文逐段审读", "scenes": {}}}
    visual, n = [], 0
    for pnum in range(1, 17):
        pid, source = f"s0005_p{pnum:04d}", paras[f"s0005_p{pnum:04d}"]["text"]
        for piece in re.findall(r"“[^”]*”|[^“]+", source):
            quoted = piece.startswith("“")
            speaker = SPEAKERS.get(pnum) if quoted else None
            for text_part in chunks(piece.strip("“”")):
                n += 1
                sid = f"C5P{pnum:02d}_{n:02d}"
                visible = [speaker] if speaker in CHAR_IDS else []
                refs = [SCENE_ID] + ([CHAR_IDS[speaker]] if visible else [])
                scene = {"scene_id": sid, "duration_seconds": editorial_seconds(text_part), "segment_break": True,
                         "characters_in_scene": visible, "scenes": ["太微殿"], "props": [],
                         "scene_description": "写实中国神话宫殿内景，按已登记的三清、鸿钧和九帝身份卡保持服饰与面容连续；集体齐声保留为明确的合唱说话人标签。",
                         "utterances": [{"kind": "dialogue" if speaker else "voiceover", "speaker": speaker or "旁白", "text": text_part}],
                         "source_text": text_part, "needs_replan": False}
                if speaker == "三清与九帝（齐声）":
                    scene["voice_groups"] = [speaker]
                plan["script"]["scenes"].append(scene); plan["source_map"][sid] = [pid]
                plan["speaker_audit"]["scenes"][sid] = [{**scene["utterances"][0],
                    "reason": f"s0005_p{pnum:04d}：引号内按原文说话主体登记；‘齐声’保留为集体发声，不拆成虚构个人。",
                    "source_ids": [pid]}]
                h3 = h3_for(sid, speaker if speaker in CHAR_IDS else None, text_part, refs, 530000 + n)
                visual.append({"scene_id": sid, "image_prompt": h3["action"], "h3": h3,
                               "speech_timing": [{"start_frame": 8, "end_frame": 118}]})
    save_content(ROOT, plan)
    approve_content(ROOT, plan["id"], "Codex", "s0005 逐段保留原文；角色对白、集体齐声与旁白分别登记。")
    result = {"content_sha256": digest(plan), "scenes": visual}
    write(ROOT / "analysis/chapter_s0005_speaker_visual.json", result)
    error = None
    try:
        compile_visual(ROOT, plan["id"], result)
    except ValueError as exc:
        error = str(exc)
    write(ROOT / "analysis/chapter_s0005_workorder.json", {"chapter": "s0005", "shots": len(visual),
          "source_paragraphs": len(paras), "all_utterances_have_speaker": True,
          "voice_review_required_before_render": True,
          "collective_speaker_requires_voice_design": True,
          "status": "script_and_storyboard_ready_pending_voice_asset_review",
          "compile_status": "blocked_by_unapproved_voice_refs" if error else "compiled",
          "compile_note": error})
    print(f"s0005 work order ready: {len(visual)} shots")


if __name__ == "__main__":
    run()
