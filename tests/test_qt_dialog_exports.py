"""The history dialog must write what the user asked it to export."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from src.history_store import HistoryStore


class TestHistoryExportWritesFiles(unittest.TestCase):
    """The export path writes real files through a real HistoryStore.

    These drive the pure export_session_to_file helper (what the dialog
    calls), so they run without a window on every core job in 3.8, 3.10
    and 3.12, and on the native Windows job.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = HistoryStore(str(Path(self.directory.name) / "history.json"))
        self.addCleanup(self.store.close)
        self.store.append("user", "tell me about DNS")
        self.store.append("assistant", "the DNS knowledge article")
        self.store.flush()

    def _export(self, target):
        from src.qt_dialogs import export_session_to_file
        export_session_to_file(self.store, self.store.active_session_id, target)

    def test_markdown_export_writes_the_file(self):
        target = str(Path(self.directory.name) / "conversation.md")
        self._export(target)
        self.assertTrue(os.path.exists(target), "the .md file was not written")
        text = Path(target).read_text(encoding="utf-8")
        self.assertIn("tell me about DNS", text)
        self.assertIn("the DNS knowledge article", text)

    def test_json_export_writes_the_file(self):
        target = str(Path(self.directory.name) / "conversation.json")
        self._export(target)
        self.assertTrue(os.path.exists(target), "the .json file was not written")
        document = json.loads(Path(target).read_text(encoding="utf-8"))
        content = json.dumps(document, ensure_ascii=False)
        self.assertIn("tell me about DNS", content)
        self.assertIn("the DNS knowledge article", content)

    def test_text_export_uses_export_to_text(self):
        target = str(Path(self.directory.name) / "conversation.txt")
        self._export(target)
        self.assertTrue(os.path.exists(target), "the .txt file was not written")
        text = Path(target).read_text(encoding="utf-8")
        self.assertIn("[USER] tell me about DNS", text)
        self.assertIn("[ASSISTANT] the DNS knowledge article", text)

    def test_a_path_is_never_passed_as_the_format(self):
        original = HistoryStore.export_session

        def spy(store_self, session_id=None, fmt="markdown"):
            assert fmt in ("markdown", "json"), "a path leaked into the format"
            return original(store_self, session_id, fmt)

        HistoryStore.export_session = spy
        self.addCleanup(setattr, HistoryStore, "export_session", original)
        target = str(Path(self.directory.name) / "conversation.md")
        self._export(target)
        self.assertTrue(os.path.exists(target))


class TestCheckboxDecision(unittest.TestCase):
    """checkbox_is_checked accepts both binding generations."""

    def test_integers(self):
        from src.qt_dialogs import checkbox_is_checked
        self.assertTrue(checkbox_is_checked(2))
        self.assertFalse(checkbox_is_checked(0))

    def test_qt_states_when_available(self):
        try:
            from PySide6 import QtCore
        except ImportError:
            self.skipTest("PySide6 not installed")
        from src.qt_dialogs import checkbox_is_checked
        self.assertTrue(checkbox_is_checked(QtCore.Qt.Checked))
        self.assertFalse(checkbox_is_checked(QtCore.Qt.Unchecked))


class TestProviderRowsUseRealIds(unittest.TestCase):
    def test_google_ai_studio_is_the_row_id(self):
        from src.qt_dialogs import provider_rows
        config = Mock()
        config.get_api_key = Mock(return_value="")
        config.api_key_env_var = Mock(return_value="PROVIDER_API_KEY")
        config.get_api_key_env_override = Mock(return_value=None)
        rows = provider_rows(config)
        ids = [row["provider"] for row in rows]
        self.assertEqual(len(rows), 2)
        self.assertNotIn("google", ids)
        self.assertIn("google_ai_studio", ids)


if __name__ == "__main__":
    unittest.main()
