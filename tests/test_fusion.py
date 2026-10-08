import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from src.render_core import FileBlock, render_text_markup
from src.file_actions import is_privileged_path, preview_diff


class TestFileBlock(unittest.TestCase):
    def test_parse_all_extracts_path(self):
        text = "Aqui está:\n```/etc/fstab\nbody\n```\nfim"
        blocks = FileBlock.parse_all(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, "/etc/fstab")
        self.assertEqual(blocks[0].content, "body\n")

    def test_parse_all_expands_home(self):
        text = "```~/x.conf\na=1\n```"
        blocks = FileBlock.parse_all(text)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, os.path.expanduser("~/x.conf"))


class TestRenderTextMarkup(unittest.TestCase):
    def test_escapes_and_code(self):
        result = render_text_markup("a <b> & c `code` d")
        self.assertNotIn("<b>", result)
        self.assertIn("&lt;b&gt;", result)
        self.assertIn("&amp;", result)
        self.assertIn("font_family='monospace'", result)
        self.assertIn(">code</span>", result)


class TestIsPrivilegedPath(unittest.TestCase):
    def test_privileged(self):
        self.assertTrue(is_privileged_path("/etc/fstab"))

    def test_not_privileged(self):
        self.assertFalse(is_privileged_path("~/x.conf"))


class TestPreviewDiff(unittest.TestCase):
    def test_new_file_returns_none(self):
        self.assertIsNone(preview_diff("/nonexistent_path_xyz/f.txt", "a\n"))

    def test_existing_file_diff(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write("a=1\n")
            path = f.name
        try:
            diff = preview_diff(path, "a=2\n")
            self.assertIsNotNone(diff)
            self.assertIn("+a=2", diff)
            self.assertIn("-a=1", diff)
        finally:
            os.unlink(path)


class TestI18n(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, ROOT)

    def test_english_default(self):
        from src import i18n
        i18n.set_language("en")
        self.assertEqual(i18n._("Settings"), "Settings")

    def test_portuguese(self):
        from src import i18n
        i18n.set_language("pt")
        self.assertEqual(i18n._("Settings"), "Configurações")
        self.assertEqual(i18n._("Expert Mode"), "Modo Especialista")

    def test_fallback_to_english(self):
        from src import i18n
        i18n.set_language("pt")
        self.assertEqual(i18n._("No translation for this"), "No translation for this")

    def test_unknown_language_falls_back(self):
        from src import i18n
        i18n.set_language("xyz")
        self.assertEqual(i18n._("Settings"), "Settings")


if __name__ == "__main__":
    unittest.main()


class TestFileBlockWindowsPaths(unittest.TestCase):
    """The file-block parser accepts POSIX and Windows absolute paths."""

    def test_posix_header_still_works(self):
        blocks = FileBlock.parse_all("```/tmp/x.py\ncontent\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, '/tmp/x.py')
        self.assertEqual(blocks[0].content, 'content\n')

    def test_home_header_still_works(self):
        import os as _os
        blocks = FileBlock.parse_all("```~/x.py\ncontent\n```")
        self.assertEqual(blocks[0].path, _os.path.expanduser('~/x.py'))

    def test_windows_header(self):
        blocks = FileBlock.parse_all("```C:\\tmp\\x.py\ncontent\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, 'C:\\tmp\\x.py')

    def test_windows_drive_with_forward_slash_header(self):
        blocks = FileBlock.parse_all("```C:/tmp/x.py\ncontent\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, 'C:/tmp/x.py')

    def test_unc_header(self):
        blocks = FileBlock.parse_all("```\\\\server\\share\\x.py\ncontent\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, '\\\\server\\share\\x.py')

    def test_empty_info_string_windows_first_line(self):
        blocks = FileBlock.parse_all("```\nC:\\tmp\\hello.py\nprint('hi')\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].path, 'C:\\tmp\\hello.py')
        self.assertEqual(blocks[0].content, "print('hi')\n")

    def test_empty_info_string_unc_first_line(self):
        blocks = FileBlock.parse_all("```\n\\\\server\\share\\x.py\ncontent\n```")
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].content, 'content\n')

    def test_language_label_is_not_a_path(self):
        self.assertEqual(FileBlock.parse_all("```python\nprint('x')\n```"), [])
        self.assertEqual(FileBlock.parse_all("```json\n{}\n```"), [])

    def test_relative_name_is_not_a_path(self):
        self.assertEqual(FileBlock.parse_all("```\nfoo.py\nprint('x')\n```"), [])
        self.assertEqual(
            FileBlock.parse_all("```\n..\\..\\Windows\\System32\\x.py\nx\n```"), [])
