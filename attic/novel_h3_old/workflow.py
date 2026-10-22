"""Project onboarding and production workflow summaries for the workbench."""
from __future__ import annotations

from pathlib import Path

from .project import load_state, read
from .arcreel import inventory


def _stage(current: int, total: int) -> str:
    if total and current >= total:
        return "done"
    if current:
        return "in_progress"
    return "pending"


def summary(root):
    root = Path(root)
    book = read(root / "book.json")
    chapters = book.get("chapters", [])
    story_total = sum(chapter.get("kind") == "story" for chapter in chapters)
    analysis_done = sum((root / "analysis" / f"{chapter['id']}.json").is_file() for chapter in chapters)
    content_plans = list((root / "content_plans").glob("chapter_*.json"))
    episodes = [read(path) for path in sorted((root / "episodes").glob("chapter_*.json"))]
    state = load_state(root)
    assets = inventory(root)
    prep = None
    try:
        from .preparation_progress import summary as preparation_summary
        prep = preparation_summary(root)
    except (OSError, KeyError, ValueError, FileNotFoundError):
        prep = {"chapters": {"total": story_total, "written": len(content_plans), "reviewed": 0},
                "assets": {}}

    execution_total = sum(len(episode.get("shots", [])) for episode in episodes)
    execution_done = sum(1 for episode in episodes for shot in episode.get("shots", [])
                         if (root / "execution_sheets" / episode["id"] / f"{shot['id']}.json").is_file())
    latest = {}
    for take in state.get("takes", {}).values():
        if take.get("retired"):
            continue
        key = (take.get("episode"), take.get("shot"))
        old = latest.get(key)
        if old is None or take.get("created_at", 0) > old.get("created_at", 0):
            latest[key] = take
    generated = sum(take.get("status") in {"rendered", "approved"} and bool(take.get("video"))
                    for take in latest.values())
    reviewed = sum(take.get("status") == "approved" for take in latest.values())
    chapter_videos = list((root / "chapter_videos").glob("*.mp4"))
    full_video = (root / "final" / "latest_full_video.mp4").is_file()
    asset_total = sum(value.get("total", 0) for value in prep.get("assets", {}).values())
    asset_approved = sum(value.get("approved", 0) for value in prep.get("assets", {}).values())

    def step(step_id, title, current, total, detail, view, action=None):
        return {"id": step_id, "title": title, "current": current, "total": total,
                "status": _stage(current, total), "detail": detail, "view": view,
                "action": action}

    steps = [
        step("source", "创建项目并上传原文", 1, 1,
             f"已载入《{book.get('title', root.name)}》 · {len(chapters)} 个章节段落",
             "source"),
        step("analysis", "原文完整性与逐章分析", analysis_done, len(chapters),
             "逐章生成分析工作单，保留缺章、重复章号和连载状态",
             "source", "prepare_book"),
        step("script", "分镜剧本与说话人", prep.get("chapters", {}).get("written", 0), story_total,
             "对白明确说话人；旁白只作画面参考；时长按内容决定",
             "content", "start_preparation"),
        step("assets", "角色、参考音频、场景与道具", asset_approved, asset_total,
             "角色需参考音频和四视图；场景、道具完成登记与审批" if asset_total else "等待导入或生成资产清单",
             "assets", "open_assets"),
        step("execution", "资产绑定镜头执行单", execution_done, execution_total,
             "每镜绑定角色视角、参考音频、场景、道具和运镜提示",
             "execution", "open_execution"),
        step("video", "章节视频生成", generated, execution_total,
             "只在当前章节资料齐全后启动；按原文顺序逐章生成",
             "video_progress", "start_video"),
        step("review", "看片与验收", reviewed, generated,
             "逐镜观看、听音、核对对白口型和连续性",
             "review", "open_review"),
        step("delivery", "章节视频与全书合集", len(chapter_videos) + int(full_video), len(episodes) + 1,
             "先合成章节视频，再更新最新全量合集",
             "delivery", "open_delivery"),
    ]
    return {"project": {"id": root.name, "title": book.get("title", root.name),
                         "author": book.get("author", "未填写作者"), "chapters": len(chapters)},
            "steps": steps,
            "counts": {"chapters": len(chapters), "story_chapters": story_total,
                       "analysis": analysis_done, "scripts": len(content_plans),
                       "episodes": len(episodes), "execution_sheets": execution_done,
                       "generated_shots": generated, "reviewed_shots": reviewed,
                       "chapter_videos": len(chapter_videos), "full_video": full_video},
            "preparation": prep}
