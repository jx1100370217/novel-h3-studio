"""Host-memory watchdog for long H3 renders.

A 260-frame take plus the FastVideo service can push a 61 GB host into
global OOM during VAE decode. The kernel then kills the model service (which
is recoverable) but systemd-oomd can kill the desktop session first. This
watchdog watches PSI and MemAvailable and pulls the plug on the model service
before the machine reaches that point.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

MEMINFO = Path('/proc/meminfo')
PRESSURE = Path('/proc/pressure/memory')


def read_available_gb(path: Path = MEMINFO) -> float:
    """MemAvailable in GiB; ``inf`` when the file cannot be read."""
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    return float('inf')


def read_pressure_avg10(path: Path = PRESSURE) -> float:
    """Memory PSI ``some avg10`` percentage; 0 when PSI is unavailable."""
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if line.startswith('some'):
                for field in line.split():
                    if field.startswith('avg10='):
                        return float(field.split('=', 1)[1])
    except OSError:
        pass
    return 0.0


class MemoryGuard:
    """Background watchdog that aborts a render on sustained memory pressure.

    ``on_abort`` should free memory immediately (stop the model service); the
    render call then fails and the batch's retry path takes over.
    """

    def __init__(self, *, min_available_gb: float = 0.8, max_pressure_avg10: float = 50.0,
                 hold_seconds: float = 10.0, interval: float = 2.0,
                 on_abort: Callable[[], None] | None = None,
                 available_reader: Callable[[], float] = read_available_gb,
                 pressure_reader: Callable[[], float] = read_pressure_avg10) -> None:
        self.min_available_gb = min_available_gb
        self.max_pressure_avg10 = max_pressure_avg10
        self.hold_seconds = hold_seconds
        self.interval = interval
        self.on_abort = on_abort
        self._available = available_reader
        self._pressure = pressure_reader
        self.aborted = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        streak = 0.0
        while not self._stop.is_set():
            low_memory = self._available() < self.min_available_gb
            high_pressure = self._pressure() > self.max_pressure_avg10
            streak = streak + self.interval if (low_memory or high_pressure) else 0.0
            if streak >= self.hold_seconds:
                self.aborted.set()
                if self.on_abort is not None:
                    try:
                        self.on_abort()
                    except Exception:  # noqa: BLE001 - watchdog must keep running
                        pass
                return
            self._stop.wait(self.interval)

    def start(self) -> 'MemoryGuard':
        self._thread = threading.Thread(target=self._run, name='memory-guard', daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval * 2)

    def __enter__(self) -> 'MemoryGuard':
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def wait_for_headroom(self, need_gb: float, timeout_seconds: float = 600.0,
                          poll_seconds: float = 10.0) -> bool:
        """Block until ``need_gb`` is available; False when the wait times out."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if self._available() >= need_gb:
                return True
            time.sleep(poll_seconds)
        return self._available() >= need_gb
