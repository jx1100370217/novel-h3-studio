"""Launch isolated local audio analysis from the workbench or CLI."""
from pathlib import Path
import subprocess
import threading
import time
from urllib.error import URLError

from .project import read, write, locked, file_hash

REPO = Path(__file__).resolve().parents[1]


def active_audio(root, gpu_only=False):
    marker = Path(root) / "audio_reviews/active.json"
    if not marker.exists():
        return False
    job = read(marker)
    if gpu_only and job.get("device") != "cuda":
        return False
    try:
        command = Path(f"/proc/{job['pid']}/cmdline").read_bytes()
        return str(REPO / "audio_review.py").encode() in command
    except FileNotFoundError:
        return False


def audio_reports(root):
    result = []
    for path in sorted((Path(root) / "audio_reviews").glob("*/progress.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        item = {"id": path.parent.name, "progress": read(path)}
        report = path.with_name("report.json")
        if report.is_file() and item["progress"]["stage"] == "已完成":
            item.update(report=read(report), audio=str(path.with_name("audio_16k.wav").relative_to(root)),
                        report_path=str(report.relative_to(root)), subtitles=str(path.with_name("transcript_candidate.srt").relative_to(root)))
        result.append(item)
    return result


def start_audio(root, source, device="cuda", language="zh"):
    from .safety import check_paused
    check_paused()
    from .comfy import api, config
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
        raise ValueError("请选择本地音频或视频文件")
    if device not in ("cuda", "cpu") or language not in ("zh", "auto", "en"):
        raise ValueError("设备或语言选项无效")
    runtime = REPO / ".venv-audio/bin/python"
    if not runtime.is_file():
        raise ValueError("本地音频环境尚未安装，请查看 docs/本地音频理解.md")
    with locked(root, "submit"):
        if active_audio(root):
            raise ValueError("已有音频分析在运行，请等待当前分析完成")
        if device == "cuda":
            try:
                url = config(root)["comfy_url"]
                queue = api(url, "/queue")
                if queue["queue_running"] or queue["queue_pending"]:
                    raise ValueError("视频正在生成，请等待完成后再使用显卡分析音频；也可选择 CPU")
                api(url, "/free", {"unload_models": True, "free_memory": True})
                # ComfyUI applies /free in its worker on the next loop, not in the HTTP handler.
                time.sleep(2)
            except (URLError, ConnectionError):
                pass  # ComfyUI is optional; the audio worker still checks real free VRAM.
        job_id = f"audio_{int(time.time() * 1000)}_{file_hash(source)[:8]}"
        out = Path(root) / "audio_reviews" / job_id
        out.mkdir(parents=True)
        write(out / "progress.json", {"stage": "正在启动", "source": str(source), "updated_at": time.time()})
        with (out / "run.log").open("w") as log:
            process = subprocess.Popen([str(runtime), str(REPO / "audio_review.py"), str(source), "--out", str(out),
                                        "--device", device, "--language", language], cwd=REPO, stdout=log, stderr=log, start_new_session=True)
        write(Path(root) / "audio_reviews/active.json", {"pid": process.pid, "id": job_id, "device": device})

        def reap():
            code = process.wait()
            progress = read(out / "progress.json")
            if code and progress.get("stage") != "失败":
                write(out / "progress.json", {"stage": "失败", "error": f"分析进程退出 ({code})，详见 {out / 'run.log'}"})
        threading.Thread(target=reap, daemon=True).start()
        return {"id": job_id, "pid": process.pid, "status": "running", "output": str(out)}
