"""An archived conversation stays reachable, exportable and restorable.

The history dialog listed only unarchived sessions, so archiving removed
the row. The restore branch then called HistoryStore.unarchive_session,
which does not exist; the store restores with archive_session(id, False).
select_session refuses an archived conversation until that restore.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.history_store import HistoryStore
from src.qt_chat import QT_AVAILABLE, QtChatWidget
from src.qt_dialogs import history_rows

if QT_AVAILABLE:
    from PySide6 import QtCore, QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for archive restore tests")
class TestQtArchiveRestore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.store = HistoryStore(str(self.directory / "history.json"))
        self.addCleanup(self.store.close)
        self.session_a = self.store.active_session_id
        self.store.append("user", "question A", session_id=self.session_a)
        self.store.append("assistant", "answer A", session_id=self.session_a)
        created = self.store.create_session(select=True)
        self.session_b = created["id"]
        self.store.append("user", "question B", session_id=self.session_b)
        self.assertTrue(self.store.flush(timeout=5))
        config = Mock()
        config.get.side_effect = lambda key, default=None: default
        self.chat = QtChatWidget(
            config, Mock(distro=None, system_context=None),
            history_store=self.store, ai_client=Mock())
        self.addCleanup(self.chat.close)
        self.shell = _ShellStub(self.store, self.chat)
        from src.qt_dialogs import QtHistoryDialog
        self.opened = []
        self.dialog = QtHistoryDialog(
            self.store, self.shell,
            on_open=lambda session_id: self.opened.append(session_id))
        self.addCleanup(self.dialog.deleteLater)

    def _item(self, session_id):
        role = QtCore.Qt.ItemDataRole.UserRole
        for row in range(self.dialog.list_widget.count()):
            item = self.dialog.list_widget.item(row)
            if item.data(role) == session_id:
                return item
        raise AssertionError("session not listed")

    def _select(self, session_id):
        item = self._item(session_id)
        self.dialog.list_widget.setCurrentItem(item)
        return item

    def _archived(self, session_id):
        return bool(self._item(session_id).data(
            QtCore.Qt.ItemDataRole.UserRole + 1))

    def test_archived_session_stays_listed_and_exports(self):
        self.chat.load_session(self.session_b)
        log_before = self.chat.log.toPlainText()
        self._select(self.session_a)
        self.dialog._archive()
        self.assertEqual(self.opened, [])
        self.assertEqual(self.store.active_session_id, self.session_b)
        self.assertEqual(self.chat.log.toPlainText(), log_before)
        self.assertTrue(self._archived(self.session_a))
        self.assertEqual(
            [row["id"] for row in history_rows(self.store)],
            [self.session_b])
        target = str(self.directory / "archived.md")
        self._select(self.session_a)
        with patch("src.qt_dialogs.QtWidgets.QFileDialog.getSaveFileName",
                   return_value=(target, "Markdown (*.md)")):
            self.dialog._export()
        exported = Path(target).read_text(encoding="utf-8")
        self.assertIn("question A", exported)
        self.assertNotIn("question B", exported)

    def test_open_refuses_an_archived_session_until_it_is_restored(self):
        self._select(self.session_a)
        self.dialog._archive()
        self.opened.clear()
        self._select(self.session_a)
        with patch("PySide6.QtWidgets.QMessageBox.information") as info:
            self.dialog._open()
        self.assertTrue(info.called)
        self.assertEqual(self.opened, [])
        self.assertEqual(self.store.active_session_id, self.session_b)
        with self.assertRaises(ValueError):
            self.store.select_session(self.session_a)
        self._select(self.session_a)
        self.dialog._archive()
        self.assertFalse(self._archived(self.session_a))
        self.assertEqual(self.opened, [])
        self.assertEqual(self.store.active_session_id, self.session_b)
        restored = self.store.select_session(self.session_a)
        self.assertEqual(restored["id"], self.session_a)
        self.assertFalse(restored["archived"])
        messages = [entry["content"] for entry in
                    self.store.load_messages(self.session_a)]
        self.assertEqual(messages, ["question A", "answer A"])


class _ShellStub(QtWidgets.QWidget if QT_AVAILABLE else object):
    def __init__(self, store, chat):
        if QT_AVAILABLE:
            super().__init__()
        self.history_store = store
        self.chat = chat


if __name__ == "__main__":
    unittest.main()
