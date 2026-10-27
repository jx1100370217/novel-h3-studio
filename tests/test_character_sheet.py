import pytest

from novel_h3.character_sheet import (
    CharacterSheetSpec,
    build_character_sheet_prompt,
    validate_prompt,
)


def spec(gender="female"):
    return CharacterSheetSpec(
        name="Test Lead",
        gender=gender,
        age="twenty-five",
        world="period Chinese fantasy",
        style="realpeople_cinematic",
        face="oval face, clear jawline, dark eyes",
        skin="natural warm-cool skin, visible texture",
        body="eight heads tall, slender, upright",
        hair="black hair in a low bun with a silver pin",
        costume="cream robe with pale blue trim",
        accessories="small pearl earrings",
        palette="cream, pale blue, caramel brown",
        height_cm=168,
    )


@pytest.mark.parametrize("gender,marker", [("female", "女角色设定图"), ("male", "男角色设定图")])
def test_prompt_has_two_view_contract(gender, marker):
    prompt = build_character_sheet_prompt(spec(gender))
    assert marker in prompt
    assert "only two views" in prompt
    assert "no side view" in prompt
    assert "no back view" in prompt
    assert "no turnaround" in prompt
    assert "single character" in prompt
    assert "neutral expression" in prompt
    assert "looking straight at camera" in prompt
    assert "standing straight" in prompt
    assert "arms relaxed at sides" in prompt
    assert "no acting pose" in prompt
    assert "85mm portrait lens" in prompt
    assert "纯净中性灰背景" in prompt
    assert "图中不要有任何文字" in prompt
    assert "人像特写从头顶到锁骨完整展示" in prompt
    assert "全身立像从头顶到脚底完整展示" in prompt


def test_prompt_uses_authored_identity_and_costume():
    prompt = build_character_sheet_prompt(spec())
    assert "oval face, clear jawline, dark eyes" in prompt
    assert "cream robe with pale blue trim" in prompt
    assert "small pearl earrings" in prompt
    assert "168cm tall" in prompt


def test_invalid_gender_rejected():
    with pytest.raises(ValueError, match="gender"):
        build_character_sheet_prompt(spec("other"))


def test_missing_invariant_rejected():
    prompt = build_character_sheet_prompt(spec()).replace("only two views", "")
    with pytest.raises(ValueError, match="missing invariants"):
        validate_prompt(prompt)


def test_unknown_spec_field_rejected():
    with pytest.raises(ValueError, match="Unknown character sheet fields"):
        CharacterSheetSpec.from_dict({"name": "x", "gender": "female", "unknown": 1})
