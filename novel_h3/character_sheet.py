"""Two-view character asset-sheet prompts for lead reference generation.

The contract follows the reference workflow used by the 猫斯卡 article:
one image contains exactly two views of the same person — a head-to-collarbone
portrait on the left and a front full-body standing view on the right — on a
neutral gray studio background, with a neutral expression and no acting pose.

This sheet is a casting/design asset, not a film still and not an H3 reference.
For H3 Ref2VA, crop one view into a single-body reference before generation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

STYLE_TAGS = {
    "realpeople_cinematic": (
        "电影摄影机拍摄，shot on ARRI Alexa，85mm portrait lens，35mm film grain，"
        "胶片颗粒，高光柔滚降，电影级肤色分级"
    ),
    "realpeople_sweet_romance": (
        "romantic drama cinematography，idol drama look，beauty lighting，85mm portrait lens"
    ),
    "realpeople_ancient_chinese": (
        "真人写实摄影，古风写实纪实，强对比度，极致细节，85mm portrait lens"
    ),
}

REQUIRED_INVARIANTS = (
    "character design sheet",
    "two-view character sheet",
    "同一画面左右并排：人像特写+正面全身立像",
    "画面中只有这两个视图、是同一个人",
    "无侧视图、无后视图、无 3/4 转身",
    "不出现第三个视图或第二个人",
    "only two views",
    "no side view",
    "no back view",
    "no turnaround",
    "single character",
    "人像特写从头顶到锁骨完整展示，不裁切头顶",
    "全身立像从头顶到脚底完整展示，不裁切头顶和脚部",
    "中性微表情，平视镜头，自然直立，双臂自然下垂",
    "neutral expression",
    "looking straight at camera",
    "standing straight",
    "arms relaxed at sides",
    "no acting pose",
    "no hands on hips",
    "纯净中性灰背景",
    "large softbox key light from front or 45° front-side",
    "2:1 lighting ratio",
    "85mm portrait lens",
    "图中不要有任何文字",
    "画面铺满，无黑边，无遮幅",
)


@dataclass(frozen=True)
class CharacterSheetSpec:
    """Authored inputs for one lead character sheet.

    ``face``, ``skin``, ``body``, ``hair``, ``costume`` and ``world`` are
    project-specific. The invariant blocks are injected by the builder so no
    story can silently drop the two-view / single-character / no-text contract.
    """

    name: str
    gender: str
    age: str
    world: str
    style: str
    face: str
    skin: str
    body: str
    hair: str
    costume: str
    accessories: str = ""
    palette: str = "奶油白、焦糖棕、低饱和中国传统色"
    height_cm: int | None = None
    extra: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterSheetSpec":
        allowed = {field.name for field in fields(cls)}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown character sheet fields: {sorted(unknown)}")
        payload = dict(data)
        if isinstance(payload.get("extra"), list):
            payload["extra"] = tuple(payload["extra"])
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["extra"] = list(self.extra)
        return data


def _clean(value: str) -> str:
    return " ".join(str(value).split()).strip().strip("，,。.;；")


def _style_tags(style: str) -> str:
    return STYLE_TAGS.get(style, style)


def validate_spec(spec: CharacterSheetSpec) -> None:
    if spec.gender not in ("male", "female"):
        raise ValueError("gender must be 'male' or 'female'")
    for name in ("name", "age", "world", "style", "face", "skin", "body", "hair", "costume"):
        if not _clean(getattr(spec, name)):
            raise ValueError(f"character sheet field {name!r} must be non-empty")
    if spec.height_cm is not None and spec.height_cm <= 0:
        raise ValueError("height_cm must be positive when supplied")
    if any(not _clean(item) for item in spec.extra):
        raise ValueError("extra descriptors must be non-empty strings")


def build_character_sheet_prompt(spec: CharacterSheetSpec) -> str:
    """Return the complete two-view character-sheet image prompt.

    The prompt is intentionally Chinese-first with English production tags,
    matching the referenced workflow. The image itself must contain no text.
    """
    validate_spec(spec)
    gender_cn = "女" if spec.gender == "female" else "男"
    parts = [
        f"{gender_cn}角色设定图",
        _style_tags(spec.style),
        "character design sheet",
        "two-view character sheet",
        _clean(spec.world),
        _clean(spec.face),
        _clean(spec.skin),
    ]
    if spec.height_cm:
        parts.append(f"{spec.height_cm}cm tall")
    parts.extend([
        _clean(spec.body),
        _clean(spec.hair),
        _clean(spec.costume),
    ])
    if _clean(spec.accessories):
        parts.append(_clean(spec.accessories))
    if _clean(spec.palette):
        parts.append(_clean(spec.palette))
    parts.extend(_clean(item) for item in spec.extra if _clean(item))

    body = "，".join(parts)
    prompt = f"""请根据以下参数生成角色标准两视图设定图（左：人像特写，右：正面全身立像）：
**基础参数：**
- 画风风格: {spec.style}
**角色设定：**
- 性别: {gender_cn},
- 提示词: {body}，
同一画面左右并排：人像特写+正面全身立像，
画面中只有这两个视图、是同一个人，无侧视图、无后视图、无 3/4 转身、不出现第三个视图或第二个人，only two views，no side view，no back view，no turnaround，single character，
人像特写从头顶到锁骨完整展示，不裁切头顶，
全身立像从头顶到脚底完整展示，不裁切头顶和脚部，
中性微表情，平视镜头，自然直立，双臂自然下垂，
无表情表演、无肢体动作、不叉腰、不抱胸、不歪头、不低头、不侧身，neutral expression，looking straight at camera，standing straight，arms relaxed at sides，no acting pose，no hands on hips，no head tilt，no emotional expression，
纯净中性灰背景，large softbox key light from front or 45° front-side，fill light，soft-edged shadows with modeling retained，2:1 lighting ratio，主光来自正面或侧前45°，禁止纯逆光当主光，slightly high key，bright airy，lifted shadows while retaining facial modeling，low contrast，soft modeling shadows on nose bridge and cheekbones，facial structure clearly readable，defined jawline，
面部阴影边缘柔但保留塑形暗面，鼻梁与颧骨有柔过渡暗面把脸撑起来，
暗部提亮通透但不过曝，面部严禁被高光冲平，
白色取奶油白不用纯白，画面最深只到焦糖棕不用纯黑，
各视图一致性，面容细腻，发丝细腻，肌肤通透
图中不要有任何文字，画面铺满，无黑边，无遮幅。
请严格按照系统规范生成人物角色设定图；只出人像特写与正面全身两个视图，不出侧视图、后视图或转身图；性别以「性别」字段为准，提示词须体现该性别。
本图为角色素材卡而非剧照：表情中性平静、双眼平视镜头、自然直立、双臂自然垂放身体两侧，不摆任何姿势与表情（neutral expression，looking straight at camera，arms relaxed at sides，no acting pose，no hands on hips）。
"""
    validate_prompt(prompt)
    return prompt


def validate_prompt(prompt: str) -> None:
    missing = [item for item in REQUIRED_INVARIANTS if item not in prompt]
    if missing:
        raise ValueError(f"character sheet prompt is missing invariants: {missing}")
    if "请根据以下参数生成角色标准两视图设定图" not in prompt:
        raise ValueError("character sheet prompt is missing the two-view opening instruction")
