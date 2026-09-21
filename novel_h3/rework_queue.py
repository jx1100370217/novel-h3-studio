"""Durable, high-priority queue for user-requested video retakes."""
from pathlib import Path
import json
import time

from .project import inside, load_state, update_state, locked, read


ACTIVE = {"queued", "running"}


def _entry_id(take_id):
    return "take:" + str(take_id)


def _remove_file(path):
    """Remove a generated media file without ever following a symlink."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError(f"拒绝删除符号链接视频：{path}")
    path.unlink(missing_ok=True)


def _invalidate_deliverables(root, take_id):
    """Remove assembled outputs whose receipt still contains the rejected take."""
    root = Path(root)
    invalidated_chapter = False
    for folder in (root / "chapter_videos", root / "final", root / "previews"):
        for receipt in folder.glob("*.json"):
            try:
                manifest = read(receipt)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if take_id not in manifest.get("take_ids", []):
                continue
            _remove_file(receipt)
            _remove_file(receipt.with_suffix(".mp4"))
            _remove_file(receipt.with_suffix(".srt"))
            invalidated_chapter |= folder.name == "chapter_videos"
    # The cumulative file records chapter names rather than individual take IDs.
    # Once a chapter receipt is invalidated, the cumulative delivery is stale too.
    if invalidated_chapter:
        for receipt in (root / "final").glob("*.json"):
            try:
                manifest = read(receipt)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if manifest.get("kind") == "latest_cumulative_video":
                _remove_file(receipt)
                _remove_file(receipt.with_suffix(".mp4"))
                _remove_file(receipt.with_suffix(".srt"))


def _retire_source_media(root, take, note, now):
    """Delete the rejected shot from delivery and keep an auditable tombstone."""
    root = Path(root)
    video = take.get("video")
    if video:
        _remove_file(inside(root, video))
    _invalidate_deliverables(root, take.get("id", ""))

    def apply(state):
        source = state.setdefault("takes", {}).get(take.get("id"))
        if source is not None:
            source.update(
                retired=True,
                video_deleted=True,
                video_deleted_at=now,
                deletion_reason="用户标记重拍，旧问题视频已删除；保留审片记录和诊断文件",
                review_required="retake_queued",
                retention_note=str(note).strip(),
            )

    update_state(root, apply)


def enqueue(root, take, note, reviewer):
    """Add or refresh one retake request, preserving the latest review note."""
    if not str(note).strip():
        raise ValueError("重拍必须包含审核意见")
    now = time.time()
    key = _entry_id(take["id"])

    # Retakes must never leave the rejected media visible as if it were the
    # current shot. Keep the state entry as an audit tombstone, then queue the
    # replacement using its immutable source_take_id.
    _retire_source_media(root, take, note, now)

    def apply(state):
        queue = state.setdefault("rework_queue", {})
        old = queue.get(key, {})
        queue[key] = {
            "id": key,
            "source_take_id": take["id"],
            "episode": take.get("episode", ""),
            "shot": take.get("shot", ""),
            "note": str(note).strip(),
            "reviewer": reviewer,
            "status": "queued" if old.get("status") not in ACTIVE else old["status"],
            "requested_at": old.get("requested_at", now),
            "updated_at": now,
            "attempt": int(old.get("attempt", 0)),
        }

    update_state(root, apply)
    return snapshot(root)["items"]


def claim(root):
    """Claim the oldest request. Only one serial video worker may own it."""
    claimed = None
    now = time.time()
    with locked(root, "rework_queue"):
        state = load_state(root)
        queue = state.setdefault("rework_queue", {})
        rows = sorted((item for item in queue.values() if item.get("status") == "queued"),
                      key=lambda item: (item.get("requested_at", 0), item.get("id", "")))
        if rows:
            item = dict(rows[0])
            item.update(status="running", started_at=now, updated_at=now,
                        attempt=int(item.get("attempt", 0)) + 1,
                        message="正在根据审核意见重拍")
            queue[item["id"]] = item
            from .project import write
            write(Path(root) / "state.json", state)
            claimed = item
    return claimed


def complete(root, queue_id, generated_take_id):
    _update(root, queue_id, status="completed", generated_take_id=generated_take_id,
            completed_at=time.time(), updated_at=time.time())


def release(root, queue_id, message):
    _update(root, queue_id, status="queued", message=str(message), updated_at=time.time())


def fail(root, queue_id, message):
    _update(root, queue_id, status="failed", message=str(message), updated_at=time.time())


def resolve_shot(root, episode, shot):
    """Resolve active requests when a reviewed shot is accepted."""
    now = time.time()

    def apply(state):
        for item in state.setdefault("rework_queue", {}).values():
            if (item.get("episode") == episode and item.get("shot") == shot
                    and item.get("status") in ACTIVE):
                item.update(status="resolved", resolved_at=now, updated_at=now)

    update_state(root, apply)


def _update(root, queue_id, **fields):
    def apply(state):
        item = state.setdefault("rework_queue", {}).get(queue_id)
        if item:
            item.update(fields)

    update_state(root, apply)


def snapshot(root):
    state = load_state(root)
    rows = sorted((dict(item) for item in state.get("rework_queue", {}).values()
                   if item.get("status") in ACTIVE),
                  key=lambda item: (item.get("status") != "running",
                                    item.get("requested_at", 0), item.get("id", "")))
    return {
        "total": len(rows),
        "queued": sum(item.get("status") == "queued" for item in rows),
        "running": sum(item.get("status") == "running" for item in rows),
        "items": rows,
    }
