import tempfile
import unittest
from pathlib import Path

from novel_h3.project import write, load_state, file_hash, sync_speech_reports
from novel_h3.rework_queue import enqueue, claim, complete, snapshot


class ReworkQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root / "state.json", {"assets": {}, "takes": {}, "approvals": {}})
        self.take = {"id": "t_old", "episode": "chapter_s0003", "shot": "C3D001"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_review_request_is_claimed_in_priority_order_and_completed(self):
        enqueue(self.root, self.take, "无极必须保持男性；删除未登记人物", "user")
        queued = snapshot(self.root)
        self.assertEqual(queued["total"], 1)
        self.assertEqual(queued["items"][0]["note"], "无极必须保持男性；删除未登记人物")
        item = claim(self.root)
        self.assertEqual(item["status"], "running")
        self.assertEqual(snapshot(self.root)["running"], 1)
        complete(self.root, item["id"], "t_new")
        self.assertEqual(snapshot(self.root)["total"], 0)
        self.assertEqual(load_state(self.root)["rework_queue"][item["id"]]["generated_take_id"], "t_new")

    def test_enqueue_removes_rejected_video_and_invalidates_delivery(self):
        video = self.root / "renders" / "t_old" / "video.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"old problematic video")
        chapter = self.root / "chapter_videos" / "chapter_s0003.mp4"
        chapter.parent.mkdir(parents=True)
        chapter.write_bytes(b"chapter containing old video")
        write(chapter.with_suffix(".json"), {
            "kind": "chapter_video", "take_ids": ["t_old"],
        })
        write(self.root / "final" / "latest_full_video.json", {
            "kind": "latest_cumulative_video", "chapters": [{"id": "s0003"}],
        })
        cumulative = self.root / "final" / "latest_full_video.mp4"
        cumulative.parent.mkdir(parents=True, exist_ok=True)
        cumulative.write_bytes(b"stale cumulative")
        take = {**self.take, "video": str(video.relative_to(self.root)),
                "video_sha256": file_hash(video), "status": "rejected"}
        write(self.root / "state.json", {"assets": {}, "takes": {"t_old": take}, "approvals": {}})

        enqueue(self.root, take, "人物错位，需要重拍", "user")

        state = load_state(self.root)
        self.assertTrue(state["takes"]["t_old"]["retired"])
        self.assertTrue(state["takes"]["t_old"]["video_deleted"])
        self.assertFalse(video.exists())
        self.assertFalse(chapter.exists())
        self.assertFalse((chapter.with_suffix(".json")).exists())
        self.assertFalse(cumulative.exists())
        self.assertFalse((self.root / "final" / "latest_full_video.json").exists())

    def test_speech_report_replaces_stale_state_transcript(self):
        take = {**self.take, "speech_check": {
            "passed": False, "transcript": "旧的 ASR 幻觉",
        }, "speech_qc_failed_retained": True,
            "review_required": "speech_qc_failed_retained"}
        write(self.root / "state.json", {"assets": {}, "takes": {"t_old": take}, "approvals": {}})
        report_path = self.root / "renders" / "t_old" / "speech_check.json"
        write(report_path, {
            "passed": True, "expected": "", "transcript": "",
            "speech_gate": {"available": True, "speech_detected": False},
            "video_sha256": "new-hash",
        })

        state = sync_speech_reports(self.root)

        self.assertEqual(state["takes"]["t_old"]["speech_check"]["transcript"], "")
        self.assertEqual(state["takes"]["t_old"]["video_sha256"], "new-hash")
        self.assertNotIn("speech_qc_failed_retained", state["takes"]["t_old"])
        self.assertNotIn("review_required", state["takes"]["t_old"])


if __name__ == "__main__":
    unittest.main()
