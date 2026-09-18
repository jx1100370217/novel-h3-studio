"""Fail closed while paused; contain model workers in a shared memory budget."""
from pathlib import Path
import os
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
PAUSE = REPO / "runtime/GENERATION_PAUSED"
SLICE = "novel-h3-workloads.slice"
MAX_MEMORY = 44 * 1024 ** 3


def user_service_env():
    """Connect to the current user's existing service manager in GUI launches."""
    env = os.environ.copy()
    runtime = Path('/run/user') / str(os.getuid())
    if not env.get('XDG_RUNTIME_DIR') and (runtime / 'bus').exists():
        env['XDG_RUNTIME_DIR'] = str(runtime)
    if not env.get('DBUS_SESSION_BUS_ADDRESS') and env.get('XDG_RUNTIME_DIR'):
        env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + env['XDG_RUNTIME_DIR'] + '/bus'
    return env


def check_paused():
    if PAUSE.exists():
        raise ValueError(f"生成与音频分析已暂停：{PAUSE.read_text().strip()}")


def check_shot_budget(cfg, shot):
    generation = cfg["generation"]
    if generation["width"] * generation["height"] >= 1920 * 1088 and shot["frames"] > 124:
        raise ValueError("1920×1088 暂限每镜头 124 帧；更长镜头需拆分，以避免已复现的显存不足")


def native_generation(cfg, shot):
    """Choose a memory-safe native size without shortening the authored shot.

    VDN-H3's activation memory grows with both spatial tokens and temporal
    length.  Long, dialogue-heavy shots can therefore exhaust a 32 GiB card
    even when they are below H3's 362-frame contract.  Keep the requested
    duration and scale the completed clip back to the configured output size
    after rendering.  Short shots retain the normal native profile.
    """
    generation = dict(cfg["generation"])
    policy = cfg.get("resource_policy", {}).get("long_clip_fallback", {})
    fallback = {
        "enabled": bool(policy.get("enabled", False)),
        "threshold_frames": int(policy.get("threshold_frames", 328)),
        "width": int(policy.get("width", 1280)),
        "height": int(policy.get("height", 704)),
    }
    use_fallback = (
        bool(cfg.get("vdn", {}).get("enabled"))
        and fallback["enabled"]
        and int(shot.get("frames", 0)) >= fallback["threshold_frames"]
        and fallback["width"] * fallback["height"] < generation["width"] * generation["height"]
    )
    if use_fallback:
        generation.update(width=fallback["width"], height=fallback["height"])
    return generation, (fallback if use_fallback else None)


def check_power_cap(max_watts):
    result = subprocess.run(
        ["nvidia-smi", "-i", "0", "--query-gpu=power.limit", "--format=csv,noheader,nounits"],
        text=True, capture_output=True, timeout=10, check=True)
    if float(result.stdout.strip()) > max_watts:
        raise ValueError(f"显卡功耗上限超过 {max_watts} W，拒绝启动；重启后需重新设置功耗限制")


def bounded_worker(*, ignore_pause=False):
    """Re-exec in a systemd scope before importing/loading any model."""
    if not ignore_pause:
        check_paused()
    if f"/{SLICE}/" in Path("/proc/self/cgroup").read_text():
        return
    result = subprocess.run(
        ["systemctl", "--user", "show", SLICE, "--property=MemoryMax", "--value"],
        text=True, capture_output=True, timeout=10, check=True, env=user_service_env())
    if result.stdout.strip() != str(MAX_MEMORY):
        raise ValueError("模型资源隔离未就绪，拒绝无保护启动；检查 novel-h3-workloads.slice")
    args = ["systemd-run", "--user", "--scope", "--slice=" + SLICE,
            "--property=OOMPolicy=kill", "--", sys.executable,
            str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    os.execvpe(args[0], args, user_service_env())
