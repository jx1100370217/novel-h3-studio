from fractions import Fraction
import json
import os
from pathlib import Path
import subprocess
import time

from .project import read, write, file_hash, inside, digest
from .director import coverage, episode_path, delivered_frames


def assembly_progress(root):
    """Return the latest chapter-assembly state for the progress dashboard."""
    root = Path(root)
    path = root / "runtime" / "chapter_assembly.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    # Keep already-produced chapters visible after upgrading an installation
    # that did not yet persist live assembly state.
    receipts = sorted((root / "chapter_videos").glob("chapter_*.json"),
                      key=lambda item: item.stat().st_mtime)
    if receipts:
        receipt = receipts[-1]
        try:
            data = json.loads(receipt.read_text(encoding="utf-8"))
            section = data.get("section") or receipt.stem.removeprefix("chapter_")
            title = section
            for chapter in json.loads((root / "book.json").read_text(encoding="utf-8")).get("chapters", []):
                if chapter.get("id") == section:
                    title = chapter.get("title", section)
                    break
            count = len(data.get("take_ids", []))
            return {"status": "completed", "episode": "chapter_" + section,
                    "title": title, "phase": "章节成片已完成，等待人工验收",
                    "message": "章节视频已生成", "completed_shots": count,
                    "total_shots": count, "output": str(receipt.with_suffix(".mp4").relative_to(root)),
                    "started_at": receipt.stat().st_mtime, "updated_at": receipt.stat().st_mtime,
                    "qc": data.get("qc")}
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return {"status": "idle", "episode": None, "title": None,
            "phase": "尚未开始章节合成", "message": "等待镜头全部通过后自动合成",
            "completed_shots": 0, "total_shots": 0, "output": None,
            "started_at": None, "updated_at": time.time()}


def _write_assembly_progress(root, **updates):
    root = Path(root)
    path = root / "runtime" / "chapter_assembly.json"
    current = assembly_progress(root)
    current.update(updates, updated_at=time.time())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def technical_qc(path, frames, width, height):
    meta = probe(path)
    video = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    errors = []
    if not video or not audio:
        return {"passed": False, "errors": ["缺少视频或音频轨"], "metadata": meta}
    if (video["width"], video["height"]) != (width, height):
        errors.append("画面尺寸与任务不符")
    if Fraction(video.get("avg_frame_rate", "0/1")) != 24:
        errors.append("帧率不是 24 fps")
    # Count actual decoded frames when the container does not state them.
    count = video.get("nb_frames")
    if not count or count == "N/A":
        out = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True)
        count = out.stdout.strip()
    if int(count) != frames:
        errors.append(f"实际 {count} 帧，期望 {frames} 帧")
    vtime = frames / 24
    atime = float(audio.get("duration", meta["format"]["duration"]))
    if abs(atime - vtime) > 0.08:
        errors.append(f"音画长度差 {abs(atime - vtime):.4f} 秒")
    decode = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    if decode.returncode:
        errors.append("媒体解码失败: " + decode.stderr[-500:])
    return {"passed": not errors, "errors": errors, "frames": int(count), "seconds": vtime,
            "width": width, "height": height, "audio_sample_rate": int(audio["sample_rate"]),
            "semantic_review": "尚需真实观看、听音；技术通过不代表电影品质"}


def enforce_silent_audio(path):
    """Keep an audio track for assembly while guaranteeing a no-dialogue shot is silent."""
    path = Path(path)
    pending = path.with_name(path.stem + ".silent.pending.mp4")
    before = file_hash(path)
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path),
                        "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                        "-af", "volume=0", "-c:a", "aac", "-b:a", "192k", str(pending)],
                       check=True, timeout=90, capture_output=True)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)
    return {"status": "applied", "policy": "absolute_silence",
            "reason": "本镜无人物对白；模型原始音频已强制静音，防止旁白或误绑定声音泄漏。",
            "original_video_sha256": before, "video_sha256": file_hash(path)}


def concatenate(paths, output, width, height, progress=None):
    """Normalize each clip's own audio rate before concatenation, never assume H3 is 48 kHz."""
    output = Path(output)
    work = output.parent / (output.stem + "_work")
    work.mkdir(parents=True, exist_ok=True)
    normalized = []
    frames = 0
    for i, path in enumerate(paths):
        if progress:
            progress(i, len(paths), "正在规范化镜头音视频")
        meta = probe(path)
        video = next(s for s in meta["streams"] if s["codec_type"] == "video")
        if not any(s["codec_type"] == "audio" for s in meta["streams"]):
            raise ValueError(f"视频没有声音，不能以静音替代交付: {path}")
        nframes = int(video["nb_frames"])
        frames += nframes
        seconds = nframes / 24
        dest = work / f"part_{i:05d}.mov"
        args = ["ffmpeg", "-nostdin", "-y", "-v", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0",
                "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}:(iw-{width})/2:(ih-{height})/2,setsar=1,fps=24",
                "-af", f"aresample=48000,apad,atrim=duration={seconds:.9f},asetpts=PTS-STARTPTS",
                "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "pcm_s16le", "-ac", "2", "-t", f"{seconds:.9f}", str(dest)]
        subprocess.run(args, check=True, capture_output=True)
        normalized.append(dest.name)
        if progress:
            progress(i + 1, len(paths), "正在合并镜头")
    manifest = work / "concat.txt"
    manifest.write_text("".join(f"file '{p}'\n" for p in normalized), encoding="utf-8")
    tmp = output.with_suffix(".pending.mp4")
    if progress:
        progress(len(paths), len(paths), "正在封装章节视频")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-v", "error", "-f", "concat", "-safe", "1", "-i", str(manifest),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", str(tmp)],
                   check=True, capture_output=True)
    report = technical_qc(tmp, frames, width, height)
    if not report["passed"]:
        raise ValueError("合成检查失败: " + str(report["errors"]))
    tmp.replace(output)
    return report


def assemble_episode(root, episode_id):
    from .comfy import current_takes, config
    root = Path(root)
    episode = read(episode_path(root, episode_id))
    takes = current_takes(root, episode)
    if any(not t or t["status"] != "approved" for _, _, t in takes):
        raise ValueError("所有当前镜头均需通过技术检查和实际审片，才可合成")
    paths = []
    for _, _, take in takes:
        path = inside(root, take["video"])
        if file_hash(path) != take["video_sha256"]:
            raise ValueError("素材已更改，审片结果失效")
        paths.append(path)
    cfg = config(root)
    token = digest([t["video_sha256"] for _, _, t in takes])[:12]
    output = root / "final" / f"{episode_id}_{token}.mp4"
    report = concatenate(paths, output, cfg["delivery"]["width"], cfg["delivery"]["height"])
    write(output.with_suffix(".json"), {"episode": episode_id, "episode_sha256": digest(episode),
                                      "take_ids": [t["id"] for _, _, t in takes], "sha256": file_hash(output), "qc": report})
    write_subtitles(root, episode, output.with_suffix(".srt"))
    return str(output)


def write_subtitles(root, episode, target):
    def tc(frame):
        ms = round(frame / 24 * 1000)
        return f"{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}"
    rows, offset = [], 0
    for shot in episode["shots"]:
        for line in shot.get("dialogue", []):
            rows.append(f"{len(rows)+1}\n{tc(offset+line['start_frame'])} --> {tc(offset+line['end_frame'])}\n{line['text']}\n")
        offset += delivered_frames(shot)
    target.write_text("\n".join(rows), encoding="utf-8")


def assemble_preview(root, episode_id):
    from .comfy import current_takes, config
    root = Path(root)
    episode = read(episode_path(root, episode_id))
    takes = current_takes(root, episode)
    paths = []
    for _, _, take in takes:
        if not take or not take.get("qc", {}).get("passed") or not (take["status"] == "approved" or (take["status"] == "rendered" and take.get("visual_review"))):
            raise ValueError("粗剪需每镜技术通过且完成实际视觉抽查")
        path = inside(root, take["video"])
        if file_hash(path) != take["video_sha256"]:
            raise ValueError("镜头视频已改变")
        paths.append(path)
    cfg = config(root)
    token = digest([t["video_sha256"] for _, _, t in takes])[:12]
    output = root / "previews" / f"{episode_id}_{token}_rough_cut.mp4"
    output.parent.mkdir(exist_ok=True)
    qc = concatenate(paths, output, cfg["delivery"]["width"], cfg["delivery"]["height"])
    write(output.with_suffix(".json"), {"episode": episode_id, "take_ids": [t["id"] for _, _, t in takes],
        "release_approved": False, "audio_listening": "pending", "sha256": file_hash(output), "qc": qc})
    write_subtitles(root, episode, output.with_suffix(".srt"))
    return str(output)


def _chapter_material(root, section_id):
    """Return current reviewed shots whose source evidence belongs to one chapter."""
    from .comfy import current_takes
    root = Path(root)
    book = read(root / "book.json")
    chapter = next(c for c in book["chapters"] if c["id"] == section_id)
    source_ids = set(chapter["paragraph_ids"])
    rows, covered = [], set()
    for episode_path_value in sorted((root / "episodes").glob("*.json")):
        episode = read(episode_path_value)
        if episode.get("release_role") == "proof":
            continue
        for shot, _, take in current_takes(root, episode):
            if not source_ids.intersection(shot.get("source_ids", [])):
                continue
            if not take or not take.get("qc", {}).get("passed") or take["status"] != "approved":
                raise ValueError(f"章节 {section_id} 尚有镜头未完成或重拍未人工验收")
            if source_ids.intersection(shot.get("source_ids", [])):
                path = inside(root, take["video"])
                if file_hash(path) != take["video_sha256"]:
                    raise ValueError(f"章节 {section_id} 的镜头素材已变化: {take['id']}")
                rows.append((shot, take, path))
                covered.update(source_ids.intersection(shot.get("source_ids", [])))
    return chapter, rows, covered


def assemble_chapter(root, section_id):
    """Write one deterministic per-chapter video, replacing its prior version atomically."""
    from .comfy import config
    root = Path(root)
    _write_assembly_progress(root, status="preparing", episode="chapter_" + section_id,
                             title=section_id, phase="正在检查章节镜头", message="正在检查镜头和原文覆盖",
                             completed_shots=0, total_shots=0, output=None, qc=None,
                             started_at=time.time())
    try:
        chapter, rows, covered = _chapter_material(root, section_id)
        total_shots = len(rows)
        _write_assembly_progress(root, title=chapter["title"], total_shots=total_shots,
                                 phase="正在准备合成", message=f"已找到 {total_shots} 个通过镜头")
        if not rows:
            raise ValueError(f"章节 {section_id} 尚无完成并通过视觉抽查的镜头")
        missing = sorted(set(chapter["paragraph_ids"]) - covered)
        if missing:
            raise ValueError(f"章节 {section_id} 仍有 {len(missing)} 个原文段落未进入镜头，禁止生成章节成片；请先完成全文改编")
        cfg = config(root)
        out = root / "chapter_videos" / f"chapter_{section_id}.mp4"
        qc = concatenate([p for _, _, p in rows], out, cfg["delivery"]["width"], cfg["delivery"]["height"],
                          progress=lambda done, total, phase: _write_assembly_progress(
                              root, status="running", phase=phase, message=f"已处理 {done} / {total} 个镜头",
                              completed_shots=done, total_shots=total))
        _write_assembly_progress(root, status="finalizing", phase="正在写入章节字幕和校验", message="视频已封装，正在写入交付记录",
                                 completed_shots=total_shots, total_shots=total_shots)
        write_subtitles(root, {"shots": [shot for shot, _, _ in rows]}, out.with_suffix(".srt"))
        write(out.with_suffix(".json"), {"kind": "chapter_video", "section": section_id,
            "source_number": chapter["source_number"], "title": chapter["title"],
            "take_ids": [t["id"] for _, t, _ in rows], "release_approved": False, "chapter_review": {"approved": False},
            "audio_listening": "pending", "sha256": file_hash(out), "qc": qc,
            "note": "章节固定文件名；同章再次生成会原子覆盖旧结果。"})
        from .project import update_state
        update_state(root, lambda state: state.setdefault("invalidated_chapters", {}).pop(section_id, None))
        _write_assembly_progress(root, status="completed", phase="章节成片已完成，等待人工验收",
                                 message="章节视频已生成，等待看片与验收", output=str(out.relative_to(root)),
                                 completed_shots=total_shots, total_shots=total_shots, qc=qc)
        return str(out)
    except Exception as exc:
        _write_assembly_progress(root, status="failed", phase="章节合成失败", message=str(exc))
        raise


def assemble_latest(root):
    """Replace the single cumulative video with available chapter videos in source order."""
    from .comfy import config
    root = Path(root)
    book = read(root / "book.json")
    from .project import load_state
    if load_state(root).get("invalidated_chapters"):
        raise ValueError("有章节等待重拍验收及重新合成，不能生成合集")
    paths, sections = [], []
    for chapter in book["chapters"]:
        path = root / "chapter_videos" / f"chapter_{chapter['id']}.mp4"
        receipt_path = path.with_suffix(".json")
        if not path.exists() or not receipt_path.exists():
            continue
        receipt = read(receipt_path)
        if receipt.get("sha256") != file_hash(path):
            raise ValueError(f"章节视频校验失败: {path}")
        review = receipt.get("chapter_review", {})
        if not review.get("approved") or review.get("sha256") != receipt.get("sha256"):
            raise ValueError(f"章节 {chapter['id']} 的当前成片尚未人工验收，不能合成合集")
        paths.append(path)
        sections.append({"id": chapter["id"], "source_number": chapter["source_number"], "title": chapter["title"]})
    if not paths:
        raise ValueError("尚无章节视频，不能生成最新全量视频")
    cfg = config(root)
    out = root / "final" / "latest_full_video.mp4"
    qc = concatenate(paths, out, cfg["delivery"]["width"], cfg["delivery"]["height"])
    write(out.with_suffix(".json"), {"kind": "latest_cumulative_video", "chapters": sections,
        "chapter_count": len(sections), "release_approved": False, "audio_listening": "pending",
        "sha256": file_hash(out), "qc": qc,
        "note": "固定文件名；新增章节后覆盖更新，表示当前已生成章节的顺序合并。"})
    return str(out)


def assemble_book(root):
    from .comfy import current_takes, config
    root = Path(root)
    story_sections = [c["id"] for c in read(Path(root)/"book.json")["chapters"] if c.get("kind") == "story"]
    if any(not (Path(root)/"chapter_videos"/f"chapter_{sid}.json").exists() for sid in story_sections):
        raise ValueError("全书合集需要全部章节成片及人工验收")
    for receipt_path in (Path(root)/"chapter_videos").glob("*.json"):
        receipt = read(receipt_path)
        if not receipt.get("chapter_review", {}).get("approved") or receipt.get("chapter_review", {}).get("sha256") != receipt.get("sha256"):
            raise ValueError("请先人工验收所有章节视频")
    report = coverage(root)
    if not report["all_supplied_text_accounted_for"]:
        raise ValueError("仍有原文未分析或未改编，禁止将部分视频标为全书")
    plan = read(root / "series.json")
    episodes = plan["episode_ids"]
    if not episodes or len(episodes) != len(set(episodes)):
        raise ValueError("分集总表不能为空或重复")
    all_ids = {read(p)["id"] for p in (root / "episodes").glob("*.json") if read(p).get("release_role", "episode") == "episode"}
    if set(episodes) != all_ids:
        raise ValueError("分集总表与全部正式分集不一致")
    paths = []
    for eid in episodes:
        ep = read(episode_path(root, eid))
        current = current_takes(root, ep)
        if any(not t or t["status"] != "approved" for _, _, t in current):
            raise ValueError(f"{eid} 尚有未验收镜头")
        token = digest([t["video_sha256"] for _, _, t in current])[:12]
        path = root / "final" / f"{eid}_{token}.mp4"
        if not path.exists():
            raise ValueError(f"请先合成 {eid}")
        receipt = read(path.with_suffix(".json"))
        if receipt["sha256"] != file_hash(path) or receipt["episode_sha256"] != digest(ep):
            raise ValueError(f"{eid} 成片已变化或记录已失效")
        paths.append(path)
    cfg = config(root)
    out = root / "final" / ("rendao_wuji_supplied_text_" + digest([file_hash(p) for p in paths])[:12] + ".mp4")
    qc = concatenate(paths, out, cfg["delivery"]["width"], cfg["delivery"]["height"])
    write_subtitles(root, {"shots": [shot for eid in episodes for shot in read(episode_path(root, eid))["shots"]]}, out.with_suffix(".srt"))
    write(out.with_suffix(".json"), {"scope": read(root / "book.json")["scope"], "coverage": report,
                                   "episodes": episodes, "qc": qc, "sha256": file_hash(out)})
    return str(out)
