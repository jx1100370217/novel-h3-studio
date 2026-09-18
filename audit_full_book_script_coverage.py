"""Write an honest full-book screenplay coverage report.

Only chapters with a source-reviewed content plan are marked ready. Unreviewed
chapters are left as work items so they cannot accidentally enter the render
queue as narrator-only placeholders.
"""
import json
from pathlib import Path
from novel_h3.project import read, write

ROOT = Path(__file__).parent / "projects/rendao-wuji"


def run():
    book = read(ROOT / "book.json")
    chapter_ids = {c["id"] for c in book["chapters"]}
    plans = {p.stem.removeprefix("chapter_"): read(p) for p in (ROOT / "content_plans").glob("*.json")
             if p.stem.removeprefix("chapter_") in chapter_ids}
    ready = {}
    for cid, plan in plans.items():
        scenes = plan.get("script", {}).get("scenes", [])
        audit = plan.get("speaker_audit", {})
        ready[cid] = {"shots": len(scenes), "utterances": sum(len(s.get("utterances", [])) for s in scenes),
                      "speaker_audit": audit.get("status") == "reviewed",
                      "status": "ready_for_voice_asset_gate" if audit.get("status") == "reviewed" else "needs_source_review"}
    pending = [c["id"] for c in book["chapters"] if c["id"] not in ready]
    report = {"source": book["source_path"], "chapters_total": len(book["chapters"]),
              "story_chapters_total": sum(c.get("kind") == "story" for c in book["chapters"]),
              "content_plans_ready": len(ready), "chapters_pending_screenplay": len(pending),
              "ready": ready, "pending": pending,
              "policy": "未完成原文逐句说话人核对的章节不进入视频提交队列；不把整部小说冒充已完成。"}
    write(ROOT / "analysis/full_book_script_coverage.json", report)
    print(json.dumps({k: report[k] for k in ("chapters_total", "story_chapters_total", "content_plans_ready", "chapters_pending_screenplay")}, ensure_ascii=False))


if __name__ == "__main__":
    run()
