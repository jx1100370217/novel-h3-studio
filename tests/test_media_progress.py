import tempfile
import unittest
from pathlib import Path

from novel_h3.media import assembly_progress, _write_assembly_progress
from novel_h3.project import write


class MediaProgressTests(unittest.TestCase):
    def test_live_assembly_progress_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_assembly_progress(root, status="running", episode="chapter_s0004",
                                     title="四界九帝", phase="正在合成",
                                     message="已处理 2 / 34 个镜头", completed_shots=2,
                                     total_shots=34)
            state = assembly_progress(root)
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["completed_shots"], 2)
            self.assertEqual(state["total_shots"], 34)
            self.assertEqual(state["title"], "四界九帝")

    def test_existing_receipt_is_visible_after_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write(root / "book.json", {"chapters": [{"id": "s0004", "title": "四界九帝"}]})
            video = root / "chapter_videos" / "chapter_s0004.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"video")
            write(root / "chapter_videos" / "chapter_s0004.json",
                  {"section": "s0004", "take_ids": ["C4D001"], "qc": {"passed": True}})
            state = assembly_progress(root)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["title"], "四界九帝")
            self.assertEqual(state["completed_shots"], 1)


if __name__ == "__main__":
    unittest.main()
