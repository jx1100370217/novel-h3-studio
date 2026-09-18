import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from novel_h3 import safety
from novel_h3.comfy import submit_next
from novel_h3.listening import start_audio
from novel_h3.project import digest, file_hash


class SafetyTests(unittest.TestCase):
    def test_independent_batch_keeps_review_pending(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "test.mp4"
            video.write_bytes(b"fixture")
            episode = {"id": "e", "shots": [{"id": "s", "continuity": "cut"}]}
            take = {"status": "rendered", "qc": {"passed": True}, "video": "test.mp4",
                    "video_sha256": file_hash(video)}
            with patch('novel_h3.safety.check_paused'), \
                    patch('novel_h3.comfy.read', return_value=episode), \
                    patch('novel_h3.comfy.validate_episode', return_value=[]), \
                    patch('novel_h3.comfy.config', return_value={"comfy_url": "unused"}), \
                    patch('novel_h3.comfy.load_state', return_value={"approvals": {"e": {"sha256": digest(episode)}}}), \
                    patch('novel_h3.comfy.api', return_value={"queue_running": [], "queue_pending": []}) as api, \
                    patch('novel_h3.comfy.current_takes', return_value=[(episode['shots'][0], 'fp', take)]):
                self.assertEqual(submit_next(root, 'e', independent_cuts=True)['status'],
                                 'episode_rendered_pending_review')
                self.assertEqual(take['status'], 'rendered')
                with self.assertRaisesRegex(ValueError, 'rendered'):
                    submit_next(root, 'e')
                episode['shots'][0]['continuity'] = 'continue'
                with self.assertRaisesRegex(ValueError, '连续镜头'):
                    submit_next(root, 'e', independent_cuts=True)
                self.assertTrue(all(len(c.args) == 2 for c in api.call_args_list))

    def test_power_limit_must_be_applied(self):
        with patch.object(safety.subprocess, "run") as run:
            run.return_value.stdout = "450.00\n"
            safety.check_power_cap(450)
            run.return_value.stdout = "600.00\n"
            with self.assertRaisesRegex(ValueError, "功耗上限"):
                safety.check_power_cap(450)

    def test_pause_blocks_all_entry_points_before_work(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "paused"
            marker.write_text("incident")
            with patch.object(safety, "PAUSE", marker):
                for call in (safety.bounded_worker,
                             lambda: submit_next(Path(folder), "missing"),
                             lambda: start_audio(Path(folder), "missing.mp4")):
                    with self.assertRaisesRegex(ValueError, "已暂停"):
                        call()

    def test_native_long_shot_rejected(self):
        cfg = {"generation": {"width": 1920, "height": 1088}}
        safety.check_shot_budget(cfg, {"frames": 124})
        with self.assertRaisesRegex(ValueError, "124"):
            safety.check_shot_budget(cfg, {"frames": 243})

    def test_missing_budget_fails_closed(self):
        with patch.object(safety, "check_paused"), \
                patch.object(Path, "read_text", return_value="0::/unbounded.scope"), \
                patch.object(safety.subprocess, "run") as run, \
                patch.object(safety.os, "execvp") as execute:
            run.return_value.stdout = "infinity"
            with self.assertRaisesRegex(ValueError, "拒绝无保护"):
                safety.bounded_worker()
            execute.assert_not_called()
