import functools
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import shutil
import tempfile
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

from .project import (status, read, inside, safe_id, analysis_packet, approve_asset, approve_voice,
                       accept_analysis, precheck_scene_prop_assets, approve_prechecked_scene_prop_assets)
from .arcreel import approve_content, approve_rhythm, visual_packet, save_content, compile_visual, save_inventory, create_asset_jobs
from .director import approve_episode, coverage
from .comfy import doctor, submit_next, sync, cancel, review_take, review_chapter, REVIEW_ITEMS
from .media import assemble_episode, assemble_book
from .listening import start_audio, audio_reports


def _create_project(server, data):
    """Create an isolated project from an uploaded novel without touching others."""
    title = str(data.get("title") or "").strip()
    author = str(data.get("author") or "未填写作者").strip() or "未填写作者"
    filename = Path(str(data.get("filename") or "novel.txt").strip() or "novel.txt").name
    encoded = data.get("source_base64")
    if not title:
        raise ValueError("请填写小说名称")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("请先选择小说原文文件")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("原文文件编码无效，请重新选择文件") from exc
    if not raw or len(raw) > 40 * 1024 * 1024:
        raise ValueError("原文文件不能为空且不能超过 40 MB")
    requested = str(data.get("id") or "").strip()
    project_id = requested or f"novel_{hashlib.sha1((title + filename + str(time.time_ns())).encode()).hexdigest()[:12]}"
    safe_id(project_id)
    base = Path(server.projects_root).resolve()
    target = (base / project_id).resolve()
    if target.parent != base or target.exists():
        raise ValueError("项目标识已存在，请换一个项目标识")
    upload_dir = Path(server.project).resolve().parent / ".uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temp_path = upload_dir / f"{project_id}_{safe_id(re.sub(r'[^a-zA-Z0-9_-]', '_', Path(filename).stem) or 'novel')}.txt"
    try:
        temp_path.write_bytes(raw)
        from .project import ingest, write
        book = ingest(temp_path, target)
        from .cli import configure
        configure(target)
        book["title"], book["author"], book["source_filename"] = title, author, filename
        book["source_path"] = "source/original.txt"
        write(target / "book.json", book)
        return {"project": _project_context(target), "next": "guide", "chapters": len(book["chapters"]),
                "analysis_packets": 0, "message": "项目已创建，原文已保存；请在项目向导中生成逐章分析工作单。"}
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def _project_path(server, project_id):
    project_id = safe_id(str(project_id or ""))
    base = Path(server.projects_root).resolve()
    target = (base / project_id).resolve()
    if target.parent != base or not (target / "book.json").is_file():
        raise ValueError("项目不存在或尚未初始化：" + project_id)
    return target

def _project_context(root):
    root = Path(root).resolve()
    book = read(root / "book.json")
    return {
        "id": root.name,
        "title": book.get("title") or root.name,
        "author": book.get("author") or "未填写作者",
        "chapter_count": len(book.get("chapters", [])),
        "project_path": str(root),
    }

def project_catalog(server):
    base = Path(server.projects_root).resolve()
    active = Path(server.project).resolve()
    items = []
    for child in sorted(base.iterdir() if base.exists() else [], key=lambda item: item.name.lower()):
        if not child.is_dir() or not (child / "book.json").is_file():
            continue
        try:
            context = _project_context(child)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        context.pop("project_path", None)
        context["active"] = child.resolve() == active
        items.append(context)
    return {"active": active.name, "projects": items}


def _rename_project(server, data):
    target = _project_path(server, data.get("project"))
    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("项目名称不能为空")
    book = read(target / "book.json")
    previous = book.get("title") or target.name
    previous_author = book.get("author") or "未填写作者"
    book["title"] = title
    if "author" in data:
        book["author"] = str(data.get("author") or "").strip() or "未填写作者"
    from .project import write
    write(target / "book.json", book)
    return {"project": _project_context(target), "previous_title": previous,
            "previous_author": previous_author}


def _delete_project(server, data):
    target = _project_path(server, data.get("project"))
    active = Path(server.project).resolve()
    if target == active:
        from .preparation_control import status as preparation_status
        from .video_control import status as video_status
        if preparation_status(target).get("worker_alive") or video_status(target).get("worker_alive"):
            raise ValueError("项目仍有任务运行，请先暂停准备和视频任务后再删除")
        candidates = [
            child for child in sorted(Path(server.projects_root).iterdir(), key=lambda item: item.name.lower())
            if child.is_dir() and child != target and (child / "book.json").is_file()
        ]
        if not candidates:
            raise ValueError("至少保留一个项目，无法删除当前唯一项目")
        next_project = candidates[0]
    else:
        next_project = active
    shutil.rmtree(target)
    if target == active:
        server.project = next_project.resolve()
    return {"deleted": target.name, "project": _project_context(server.project),
            "switched": target == active}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    @property
    def root(self):
        return self.server.project

    def valid_host(self):
        return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

    def do_GET(self):
        if not self.valid_host():
            self.send_error(403); return
        try:
            url = urlsplit(self.path)
            if url.path == "/api/regeneration":
                from .regeneration import tasks
                return self.send_json(tasks(self.root))
            if url.path == "/api/chapter-readiness":
                from .preparation import readiness
                return self.send_json(readiness(self.root, parse_qs(url.query)["episode"][0]))
            if url.path == "/api/shot-execution":
                from .comfy import compile_execution_sheet
                query = parse_qs(url.query)
                episode_id, shot_id = query["episode"][0], query["shot"][0]
                episode = read(Path(self.root) / "episodes" / f"{episode_id}.json")
                shot = next(item for item in episode["shots"] if item["id"] == shot_id)
                return self.send_json(compile_execution_sheet(self.root, episode, shot, persist=True)[2])
            if url.path == "/api/projects":
                return self.send_json(project_catalog(self.server))
            if url.path == "/api/progress":
                from .progress import snapshot
                payload = snapshot(self.root)
                payload["project_context"] = _project_context(self.root)
                return self.send_json(payload)
            if url.path == "/api/workflow":
                from .workflow import summary
                return self.send_json(summary(self.root))
            if url.path == "/api/status":
                payload = status(self.root)
                payload["project_context"] = _project_context(self.root)
                return self.send_json(payload)
            if url.path == "/api/audio-reports":
                return self.send_json(audio_reports(self.root))
            if url.path == "/api/doctor":
                return self.send_json(doctor(self.root))
            if url.path == "/api/coverage":
                return self.send_json(coverage(self.root))
            if url.path == "/api/packet":
                return self.send_json(analysis_packet(self.root, parse_qs(url.query)["section"][0]))
            if url.path == "/api/visual-packet":
                return self.send_json(visual_packet(self.root, parse_qs(url.query)["episode"][0]))
            if url.path == "/":
                return self.file(Path(__file__).with_name("web.html"))
            if url.path == "/media":
                path = inside(self.root, parse_qs(url.query)["path"][0])
                if path.suffix.lower() not in (".mp4", ".png", ".jpg", ".jpeg", ".webp", ".srt", ".json", ".jsonl", ".flac", ".wav", ".txt"):
                    raise ValueError("不支持的文件类型")
                return self.file(path)
            self.send_error(404)
        except (ValueError, KeyError, OSError, StopIteration) as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_HEAD(self):
        """Return media/file metadata without sending the body.

        Browser video elements commonly issue HEAD before their first range
        request.  Keeping this path aligned with do_GET avoids a false
        "cannot play" result when the public gateway is used.
        """
        if not self.valid_host():
            self.send_error(403); return
        try:
            url = urlsplit(self.path)
            if url.path == "/":
                return self.file(Path(__file__).with_name("web.html"), head=True)
            if url.path == "/media":
                path = inside(self.root, parse_qs(url.query)["path"][0])
                if path.suffix.lower() not in (".mp4", ".png", ".jpg", ".jpeg", ".webp", ".srt", ".json", ".jsonl", ".flac", ".wav", ".txt"):
                    raise ValueError("不支持的文件类型")
                return self.file(path, head=True)
            self.send_error(404)
        except (ValueError, KeyError, OSError, StopIteration) as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_POST(self):
        expected = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
        if not self.valid_host() or self.headers.get("Origin") not in expected or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send_error(403); return
        try:
            size = int(self.headers.get("Content-Length", 0))
            limit = 60 * 1024 * 1024 if self.path == "/api/create-project" else 1024 * 1024
            if not 0 < size <= limit:
                raise ValueError("请求大小无效")
            data = json.loads(self.rfile.read(size))
            if self.path == "/api/create-project":
                result = _create_project(self.server, data)
                self.server.project = Path(result["project"]["project_path"]).resolve()
            elif self.path == "/api/rename-project":
                result = _rename_project(self.server, data)
                if Path(self.server.project).name == data.get("project"):
                    self.server.project = Path(result["project"]["project_path"]).resolve()
            elif self.path == "/api/delete-project":
                result = _delete_project(self.server, data)
            elif self.path == "/api/prepare-book":
                from .cli import prepare_packets
                result = prepare_packets(self.root)
            elif self.path == "/api/switch-project":
                target = _project_path(self.server, data.get("project"))
                previous = Path(self.server.project).resolve()
                self.server.project = target
                result = {"project": _project_context(target), "previous": previous.name}
            elif self.path == "/api/video-control":
                from .video_control import control
                result = control(self.root, data["action"])
            elif self.path == "/api/preparation-control":
                from .preparation_control import control
                result = control(self.root, data["action"], data.get("episode"))
            elif self.path == "/api/regenerate":
                from .regeneration import enqueue
                result = enqueue(self.root, data["kind"], data["target"], data.get("episode"))
                if data["kind"] == "video":
                    from .video_control import start_retake_if_idle
                    start_retake_if_idle(self.root)
            elif self.path == "/api/prepare-missing":
                from .preparation import prepare
                result = prepare(self.root, data["episode"], data["kind"], data.get("asset"))
            elif self.path == "/api/sync": result = sync(self.root)
            elif self.path == "/api/audio-review": result = start_audio(self.root, data["file"], data.get("device", "cuda"), data.get("language", "zh"))
            elif self.path == "/api/import-analysis": result = accept_analysis(self.root, data)
            elif self.path == "/api/import-content": result = save_content(self.root, data)
            elif self.path == "/api/import-assets": result = save_inventory(self.root, data)
            elif self.path == "/api/asset-jobs": result = create_asset_jobs(self.root)
            elif self.path == "/api/compile-visual": result = compile_visual(self.root, data["episode"], data["visual"])
            elif self.path == "/api/submit":
                from .preparation import readiness
                if data['episode'].startswith('chapter_'):
                    report = readiness(self.root, data['episode'])
                    if report['blockers']:
                        raise ValueError('本章资料未齐全，请打开“章节资料与补充”处理缺失项')
                result = submit_next(self.root, data['episode'])
            elif self.path == "/api/cancel": result = cancel(self.root)
            elif self.path == "/api/approve-plan":
                result = approve_episode(self.root, data["episode"], "user", data["note"])
            elif self.path == "/api/approve-content":
                result = approve_content(self.root, data["episode"], "user", data["note"])
            elif self.path == "/api/approve-rhythm":
                result = approve_rhythm(self.root, data["episode"], "user", data.get("note", ""))
            elif self.path == "/api/approve-image":
                aid = data["asset"]
                if not data.get("note"):
                    raise ValueError("请写下形象或首帧审阅意见")
                result = approve_asset(self.root, aid, "user", data["note"])
            elif self.path == "/api/precheck-assets":
                result = precheck_scene_prop_assets(self.root)
            elif self.path == "/api/approve-prechecked-assets":
                result = approve_prechecked_scene_prop_assets(self.root, "user", data.get("note", ""))
            elif self.path == "/api/approve-voice":
                result = approve_voice(self.root, data["speaker"], "user", data.get("note", ""))
            elif self.path == "/api/review":
                result = review_take(self.root, data["take"], data["approved"], data["note"], "user", data["checks"])
                if not data["approved"]:
                    from .video_control import start_retake_if_idle
                    start_retake_if_idle(self.root)
            elif self.path == "/api/review-chapter":
                result = review_chapter(self.root, data["episode"], True, data["note"], "user", data["checks"])
            elif self.path == "/api/approve-chapter-video":
                from .delivery_policy import approve_chapter_video
                result = approve_chapter_video(self.root, data["section"], data["sha256"])
            elif self.path == "/api/assemble": result = assemble_episode(self.root, data["episode"])
            elif self.path == "/api/assemble-book": result = assemble_book(self.root)
            else:
                self.send_error(404); return
            self.send_json({"result": result})
        except Exception as exc:
            payload = {"error": str(exc)}
            if getattr(exc, 'gate', None):
                payload['gate'] = exc.gate
            self.send_json(payload, 400)

    def file(self, path, head=False):
        total = path.stat().st_size
        start, end = 0, total - 1
        value = self.headers.get("Range")
        if value:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", value)
            if not match:
                self.send_error(416); return
            start = int(match[1]); end = min(int(match[2]) if match[2] else total - 1, total - 1)
            if start > end or start >= total:
                self.send_error(416); return
        self.send_response(206 if value else 200)
        self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("X-Content-Type-Options", "nosniff")
        if path.suffix.lower() in (".html", ".htm"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        if value:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.end_headers()
        if head:
            return
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = f.read(min(65536, remaining))
                self.wfile.write(chunk)
                remaining -= len(chunk)


def serve(root, port, open_browser=True):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.project = Path(root).resolve()
    server.projects_root = server.project.parent
    from .live_progress import listener
    listener(root)
    print(f"影视制片工作台：http://127.0.0.1:{port}", flush=True)
    if open_browser:
        webbrowser.open(f"http://127.0.0.1:{port}")
    from .regeneration import recover
    recover(root)
    server.serve_forever()
