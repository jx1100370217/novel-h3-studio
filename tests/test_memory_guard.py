import threading
import time
import unittest

from novel_h3.memory_guard import MemoryGuard, read_available_gb, read_pressure_avg10


class MemoryReaderTests(unittest.TestCase):
    def test_reads_mem_available(self, ):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'meminfo'
            path.write_text('MemTotal: 64000000 kB\nMemAvailable: 8388608 kB\n', encoding='utf-8')
            self.assertAlmostEqual(read_available_gb(path), 8.0, places=3)

    def test_missing_meminfo_is_infinite(self):
        self.assertEqual(read_available_gb('/nonexistent/meminfo'), float('inf'))

    def test_reads_pressure_avg10(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pressure'
            path.write_text('some avg10=63.42 avg60=20.00 avg300=5.00 total=123\n'
                            'full avg10=1.00 avg60=0.50 avg300=0.10 total=2\n', encoding='utf-8')
            self.assertAlmostEqual(read_pressure_avg10(path), 63.42, places=2)


class MemoryGuardTests(unittest.TestCase):
    def test_aborts_on_sustained_pressure(self):
        aborted = threading.Event()
        guard = MemoryGuard(min_available_gb=1.0, max_pressure_avg10=50.0, hold_seconds=0.2,
                            interval=0.05, on_abort=aborted.set,
                            available_reader=lambda: 0.5, pressure_reader=lambda: 90.0)
        with guard:
            deadline = time.time() + 2
            while not aborted.is_set() and time.time() < deadline:
                time.sleep(0.02)
        self.assertTrue(guard.aborted.is_set())
        self.assertTrue(aborted.is_set())

    def test_stays_quiet_when_memory_is_healthy(self):
        guard = MemoryGuard(min_available_gb=1.0, max_pressure_avg10=50.0, hold_seconds=0.2,
                            interval=0.05, available_reader=lambda: 20.0, pressure_reader=lambda: 2.0)
        with guard:
            time.sleep(0.4)
        self.assertFalse(guard.aborted.is_set())

    def test_headroom_wait_gives_up(self):
        guard = MemoryGuard(available_reader=lambda: 1.0)
        self.assertFalse(guard.wait_for_headroom(6.0, timeout_seconds=0.3, poll_seconds=0.05))
        self.assertTrue(guard.wait_for_headroom(0.5, timeout_seconds=0.3))


if __name__ == '__main__':
    unittest.main()
