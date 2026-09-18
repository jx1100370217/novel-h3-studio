"""Seed a source-grounded asset inventory and a two-shot ArcReel/H3 example."""
import copy
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from novel_h3.project import read, write, digest
from novel_h3.arcreel import save_inventory, create_asset_jobs, save_content


def seed(root):
    book = read(root / "book.json")
    if book["source_sha256"] != "043025dbb6e3b6756ac4fe6e0155e838378f52dc8d804a0f0f5e3880c3e6447b":
        raise ValueError("这份初始资产只对应已核对的人道无极原文")
    paragraphs = {p["id"]: p for p in read(root / "paragraphs.json")}
    assets = {"status": "seed_inventory_needs_full_book_reconciliation",
              "scope": "从作者资料和通天峰段落建立的初始资产；并非全书角色总表。外貌和衣着均为待审阅的影视设计。作者资料含后续剧情，只用于一致性管理，不能提前写进角色台词。",
              "characters": {}, "scenes": {}, "props": {}}
    characters = [
        ("振明", "zhenming", "s0001_p0002", [], "二十年前水患夜出生，被道士救起交予养母。",
         "成年男性，约二十岁视觉年龄；瘦而结实，黑发束起，黛青色粗布交领短袍，朴素束带，风霜与生活痕迹；自然肤质。脸型与服饰属于改编设计，须与后续正文复核。"),
        ("冰雨", "bingyu", "s0001_p0003", ["笑笑", "小龙女"], "冰雨、笑笑、小龙女为同一角色的不同称呼；具有元丹。",
         "成年女性形象，长黑发，清澈而坚定的神情，浅月白色交领长衣，低调灰蓝滚边，发簪简洁。角色真实年龄和此衣着未从本段确定。"),
        ("冷月", "lengyue", "s0001_p0004", [], "波成王康仁合之女，寒星之妹；善良而任性。",
         "成年女性形象，深绛色贵族常服，少量金饰，明亮敏锐的目光，带不服输的神态；服装和外貌是暂定设计。"),
        ("寒星", "hanxing", "s0001_p0005", [], "波成王之子，冷月之兄；雄才大略、一表人才、善良。",
         "成年男性形象，藏青色贵族长袍，束冠整洁，肩背挺直，沉稳而温和的神态；具体年龄、面容、配色为设计。"),
        ("素灵儿", "sulinger", "s0001_p0007", [], "素国皇帝素林鹏第五女；文武出众，作者资料中尚未登场。",
         "成年女性形象，墨绿贵族骑行服装，精细但克制的缎纹，目光专注，姿态利落；只做角色储备，不提前安排登场。"),
        ("万年火龟", "fire_turtle", "s0001_p0008", ["龟仙人"], "瑶池火龟，因偷吃蟠桃受罚看守射日神弓，龟壳有神箭秘图。",
         "龟形基础资产：厚重深褐色龟壳，真实鳞片，古老刻痕，极轻微暖色内蕴，不画文字。体型比例、纹路和材质为设计；人形暂不生成。")]
    for name, aid, pid, aliases, facts, design in characters:
        assets["characters"][name] = {"id": aid, "aliases": aliases, "source_ids": [pid],
            "evidence": paragraphs[pid]["text"][:24], "source_facts": facts,
            "design_description": design, "voice_style": "待实听选定；同一角色与衍生形象共享发声身份。", "derivatives": {}}
    assets["characters"]["振明"]["derivatives"]["雨中"] = {
        "id": "zhenming_rain", "description": "衣料被雨打湿，发梢结成湿束，保留原衣款、脸型和年龄。这是光线天气变体，不新增剧情或伤势。"}
    for name, aid, pid, facts, design in [
        ("通天峰", "tongtian_peak", "s0007_p0007", "位于灵山山脉与墨河相交处；墨河自山底穿过。", "写实陡峭巨峰，山脚河道与洞口可辨；设定峰顶有两处不等高岩牙作为空间识别点，此轮廓属影视美术设计。"),
        ("天波府", "tianbo_palace", "s0001_p0004", "寿国桐城波成王康仁合的府邸。", "宽阔但有生活痕迹的古代王府庭院，木构回廊、灰瓦、石阶、朱漆旧门，日间自然侧光；建筑布局属于改编设计。")]:
        assets["scenes"][name] = {"id": aid, "source_ids": [pid], "evidence": paragraphs[pid]["text"][:24], "source_facts": facts, "design_description": design}
    assets["props"]["射日神弓"] = {"id": "sun_bow", "source_ids": ["s0001_p0009"],
        "evidence": "射日神弓是上古时期箭神后羿的武器", "source_facts": "后羿旧弓，混沌所生；具有神识和受封印的力量。",
        "design_description": "古朴有重量感的深铜色大弓，弓臂如沉积岩与古铜结合，弧线克制，接合部有暗金细纹。弓形、尺寸和材质是暂定设计；不附赠未确认数量的神箭。"}
    save_inventory(root, assets)
    create_asset_jobs(root)
    ep = read(REPO / "examples/proof_tongtian.json")
    plan = {k: ep[k] for k in ("id", "release_role", "dramatic_question", "turning_point")}
    plan["script"] = {"title": ep["title"], "scenes": []}
    plan["source_map"] = {}
    visual = {"scenes": []}
    for shot in ep["shots"]:
        sid = "E1" + shot["id"]
        plan["script"]["scenes"].append({"scene_id": sid, "duration_seconds": 5,
            "segment_break": shot["continuity"] == "cut", "characters_in_scene": [], "scenes": ["通天峰"], "props": [],
            "scene_description": shot["action"], "utterances": [], "source_text": "第三天夜里通天峰顶上金光闪闪"})
        plan["source_map"][sid] = shot["source_ids"]
        h3 = {k: copy.deepcopy(v) for k, v in shot.items() if k not in {"id", "source_ids", "frames", "dialogue", "scene_id"}}
        h3["location_id"] = shot["scene_id"]
        if h3.get("first_frame"):
            h3["first_frame"] = "keyframe_tongtian_001"
        visual["scenes"].append({"scene_id": sid, "h3": h3, "speech_timing": [],
            "image_prompt": "Photorealistic 16:9 Chinese mythological cinema. Use the reference mountain's exact profile and geography. Flooded river below Tongtian Peak at night. Distant summit to the right, old fence post left, empty wooden boat lower left. Cool moonlight, rain, thin mist, barely visible warm gold behind summit clouds. Natural camera at human eye level, 35mm lens, restrained color. No people, text, split panels or collage. Boat and fence are adaptation set dressing."})
    visual["content_sha256"] = digest(plan)
    save_content(root, plan)
    write(REPO / "examples/arcreel_content.json", plan)
    write(REPO / "examples/arcreel_visual.json", visual)
    return {"characters": len(assets["characters"]), "scenes": len(assets["scenes"]), "props": len(assets["props"]), "example": plan["id"]}


if __name__ == "__main__":
    print(seed(REPO / "projects/rendao-wuji"))
