import tempfile
import unittest
from pathlib import Path

from novel_h3.project import write, load_state
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


if __name__ == "__main__":
    unittest.main()
