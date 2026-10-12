import unittest
from pathlib import Path

from novel_h3.server import media_content_type


class WorkbenchMediaEncodingTests(unittest.TestCase):
    def test_markdown_media_declares_utf8_charset(self):
        self.assertEqual(
            media_content_type(Path("cinematic_screenplay.md")),
            "text/markdown; charset=utf-8",
        )


if __name__ == "__main__":
    unittest.main()
