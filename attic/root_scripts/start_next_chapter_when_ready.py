"""Start a chapter after that chapter's asset gate is green.

The complete inventory continues in the preparation queue, but a ready
chapter must not wait for unrelated later-book assets. Pending or unapproved
assets for the selected chapter never reach ComfyUI.
"""
from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from novel_h3.arcreel import compile_visual
from novel_h3.comfy import api, config
from novel_h3.director import approve_episode, validate_episode
from novel_h3.project import digest, file_hash, inside, locked, read, write


REPO = Path(__file__).resolve().parent
DEFAULT_ROOT = REPO / "projects/rendao-wuji"
POLL_SECONDS = 30


def _chapter_requirements(root: Path, episode_id: str):
    plan = read(root / "content_plans" / f"{episode_id}.json")
    visual = read(root / "analysis" / f"{episode_id}_speaker_visual.json")
    assets = read(root / "bible/assets.json")
    state = read(root / "state.json")
    voices = read(root / "bible/voices.json")
    blockers = []
    revision = config(root).get("creative_revision")
    if revision and plan.get("creative_revision") != revision:
        blockers.append({"reason": "script_missing", "details": "剧本已失效，必须重写当前剧本"})
    required_assets = set()
    required_speakers = set()
    required_names = {"characters": set(), "scenes": set(), "props": set()}
    for scene in plan["script"]["scenes"]:
        required_speakers.update(line["speaker"] for line in scene.get("utterances", []) if line.get("speaker"))
        for bucket, field in (("characters", "characters_in_scene"), ("scenes", "scenes"), ("props", "props")):
            for name in scene.get(field, []):
                required_names[bucket].add(name)
                item = assets.get(bucket, {}).get(name)
                if not item:
                    blockers.append({"shot": scene["scene_id"], "asset": name, "reason": "asset_not_registered"})
                else:
                    required_assets.add(item["id"])
    for bucket in ("characters", "scenes", "props"):
        for name in sorted(required_names[bucket]):
            definition = assets[bucket].get(name)
            if not definition:
                continue
            aid = definition["id"]
            item = state.get("assets", {}).get(aid, {})
            path = inside(root, item.get("path", "")) if item.get("path") else None
            if not item:
                blockers.append({"asset": aid, "name": name, "reason": "image_not_registered"})
            elif not item.get("approved"):
                blockers.append({"asset": aid, "name": name, "reason": "image_review_pending"})
            elif not path or not path.is_file():
                blockers.append({"asset": aid, "name": name, "reason": "image_file_missing"})
            elif file_hash(path) != item.get("sha256"):
                blockers.append({"asset": aid, "name": name, "reason": "image_hash_changed"})
            else:
                from novel_h3.comfy import asset_for
                try:
                    asset_for(root, aid)
                except (ValueError, OSError, KeyError) as exc:
                    blockers.append({"asset": aid, "name": name, "reason": "image_source_invalid", "details": str(exc)})
            if bucket == "characters":
                from novel_h3.character_views import readiness_blockers
                blockers.extend(readiness_blockers(root, aid, name))
    for speaker in sorted(required_speakers):
        item = voices.get(speaker, {})
        path = inside(root, item.get("path", "")) if item.get("path") else None
        if not item:
            blockers.append({"speaker": speaker, "reason": "voice_not_registered"})
        elif not item.get("approved"):
            blockers.append({"speaker": speaker, "reason": "voice_review_pending"})
        elif not path or not path.is_file():
            blockers.append({"speaker": speaker, "reason": "voice_file_missing"})
        elif file_hash(path) != item.get("sha256"):
            blockers.append({"speaker": speaker, "reason": "voice_hash_changed"})
    if plan.get("rhythm_review", {}).get("version") != 2 or not plan.get("rhythm_review", {}).get("reviewed"):
        blockers.append({"reason": "rhythm_review_pending"})
    if not plan.get("rhythm_review", {}).get("source_sequence_verified"):
        blockers.append({"reason": "source_sequence_unverified"})
    if plan.get("speaker_audit", {}).get("status") != "reviewed":
        blockers.append({"reason": "speaker_audit_pending"})
    expected_ids = {scene["scene_id"] for scene in plan["script"]["scenes"]}
    rows = {row["scene_id"]: row for row in visual.get("scenes", [])}
    if visual.get("content_sha256") != digest(plan):
        blockers.append({"reason": "visual_content_digest_stale"})
    if set(rows) != expected_ids:
        blockers.append({"reason": "visual_workorder_incomplete", "expected": len(expected_ids), "actual": len(rows)})
    return plan, visual, blockers, required_assets, required_speakers


def _write_waiting_report(root: Path, episode_id: str, blockers: list[dict], assets: set[str], speakers: set[str]):
    path = root / "analysis" / f"{episode_id}_readiness.json"
    previous = read(path) if path.exists() else {}
    report = {
        **previous,
        "chapter": episode_id.removeprefix("chapter_"),
        "ready": False,
        "gate_status": "waiting_for_asset_and_voice_approval",
        "generation_started": False,
        "required_assets": len(assets),
        "required_speakers": sorted(speakers),
        "asset_scope": "chapter_required_assets",
        "blockers": blockers,
        "updated_at": time.time(),
    }
    write(path, report)


def _queue_idle(root: Path) -> bool:
    queue = api(config(root)["comfy_url"], "/queue")
    return not queue.get("queue_running") and not queue.get("queue_pending")


def run(root: Path, episode_id: str, poll_seconds: int = POLL_SECONDS):
    root = root.resolve()
    episode_id = episode_id if episode_id.startswith("chapter_") else f"chapter_{episode_id}"
    runtime = REPO / "runtime" / "asset_gate"
    runtime.mkdir(parents=True, exist_ok=True)
    status_path = runtime / f"{episode_id}.json"
    with locked(root, "asset_gate"):
        while True:
            from novel_h3.project import approve_prechecked_scene_prop_assets
            approve_prechecked_scene_prop_assets(root, 'user_authorized_auto_scene_prop', '用户要求场景道具预检通过后自动确认')
            try:
                plan, visual, blockers, required_assets, required_speakers = _chapter_requirements(root, episode_id)
            except (FileNotFoundError, KeyError, ValueError) as exc:
                from novel_h3.preparation import readiness
                blockers = readiness(root, episode_id)["blockers"]
                required_assets, required_speakers = set(), {"旁白"}
                _write_waiting_report(root, episode_id, blockers, required_assets, required_speakers)
                write(status_path, {"status": "waiting", "episode": episode_id, "blockers": blockers, "time": time.time()})
                time.sleep(poll_seconds)
                continue
            if blockers:
                _write_waiting_report(root, episode_id, blockers, required_assets, required_speakers)
                write(status_path, {"status": "waiting", "episode": episode_id, "blockers": blockers, "time": time.time()})
                time.sleep(poll_seconds)
                continue
            if not _queue_idle(root):
                blocker = [{"reason": "comfy_queue_busy"}]
                _write_waiting_report(root, episode_id, blocker, required_assets, required_speakers)
                write(status_path, {"status": "waiting_for_queue", "episode": episode_id, "blockers": blocker, "time": time.time()})
                time.sleep(poll_seconds)
                continue
            break

        episode = compile_visual(root, episode_id, visual)
        errors = validate_episode(root, read(root / "episodes" / f"{episode_id}.json"))
        if errors:
            raise RuntimeError("编译后的章节仍未通过验证：" + "; ".join(errors[:8]))
        approve_episode(root, episode_id, "Codex 资产门禁", "章节所需角色、场景、道具图片和说话人参考音频均已登记并通过审阅；内容节奏、原文顺序和说话人锁定保持不变。")
        write(status_path, {"status": "starting_render", "episode": episode_id, "time": time.time(), "shots": episode["shots"]})
        report = read(root / "analysis" / f"{episode_id}_readiness.json") if (root / "analysis" / f"{episode_id}_readiness.json").exists() else {}
        write(root / "analysis" / f"{episode_id}_readiness.json", {**report, "ready": True, "gate_status": "passed", "generation_started": True, "updated_at": time.time()})
    # Keep the project lock released while the serial renderer owns the submit
    # lock and resource guard.
    subprocess.run(["/home/jx/miniconda3/bin/python3", str(REPO / "render_chapter.py"), episode_id, "--project", str(root)], cwd=REPO, check=True)
    write(status_path, {"status": "chapter_rendered_pending_review", "episode": episode_id, "time": time.time()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("episode", nargs="?", default="chapter_s0004")
    parser.add_argument("--project", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    args = parser.parse_args()
    run(args.project, args.episode, max(5, args.poll_seconds))
