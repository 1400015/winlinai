"""Archive/delete of the visible session must reload the chat.

QtHistoryDialog._archive and _delete only reloaded the list. When the
affected session was the visible one, HistoryStore adopts another active
session while the log and _pending_messages kept the old conversation.
"""
import os
import threading
import unittest
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch

from src.history_store import HistoryStore
from src.qt_chat import QT_AVAILABLE, QtChatWidget

if QT_AVAILABLE:
    from PySide6 import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for history sync tests")
class TestQtHistorySync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.json"
        self.store = HistoryStore(self.path)
        self.addCleanup(self.store.close)
        self.session_a = self.store.active_session_id
        for role, content in (("user", "question A"),
                              ("assistant", "answer A")):
            self.store.append(role, content, session_id=self.session_a)
        created = self.store.create_session(select=True)
        self.session_b = created["id"]
        for role, content in (("user", "question B"),
                              ("assistant", "answer B")):
            self.store.append(role, content, session_id=self.session_b)
        self.assertTrue(self.store.flush(timeout=5))
        config = Mock()
        config.get.side_effect = lambda key, default=None: default
        offline = Mock(distro=None, system_context=None)
        self.chat = QtChatWidget(config, offline, history_store=self.store,
                                 ai_client=Mock())
        self.addCleanup(self.chat.close)
        self.addCleanup(self._settle_worker)
        self.shell = _ShellStub(self.store, self.chat)
        from src.qt_dialogs import QtHistoryDialog
        self.dialog = QtHistoryDialog(
            self.store, self.shell,
            on_open=lambda session_id: self.chat.load_session(session_id),
            on_new=lambda session_id: self.chat.load_session(session_id))
        self.addCleanup(self.dialog.deleteLater)

    def _settle_worker(self):
        thread = self.chat._worker_thread
        if thread is not None:
            self.chat._cancel_event.set()
            thread.join(timeout=5)
        self.app.processEvents()

    def _select(self, session_id):
        for row in range(self.dialog.list_widget.count()):
            item = self.dialog.list_widget.item(row)
            if item.data(0x0100) == session_id:
                self.dialog.list_widget.setCurrentItem(item)
                return item
        raise AssertionError("session not listed")

    def _log_and_pending(self):
        return (self.chat.log.toPlainText(),
                [dict(message) for message in self.chat._pending_messages])

    def test_archiving_visible_session_reloads_chat_to_new_active(self):
        self.chat.load_session(self.session_b)
        self.assertIn("question B", self.chat.log.toPlainText())
        self._select(self.session_b)
        self.dialog._archive()
        self.assertNotEqual(self.store.active_session_id, self.session_b)
        self.assertEqual(self.store.active_session_id, self.session_a)
        self.assertIn("question A", self.chat.log.toPlainText())
        self.assertNotIn("question B", self.chat.log.toPlainText())
        self.assertEqual(
            [message["content"] for message in self.chat._pending_messages],
            ["question A", "answer A"])

    def test_deleting_visible_session_reloads_chat_to_new_active(self):
        self.chat.load_session(self.session_b)
        self.assertIn("question B", self.chat.log.toPlainText())
        self._select(self.session_b)
        with patch("PySide6.QtWidgets.QMessageBox.question",
                   return_value=QtWidgets.QMessageBox.StandardButton.Yes):
            self.dialog._delete()
        self.assertNotIn(self.session_b,
                         [s["id"] for s in self.store.list_sessions()])
        self.assertEqual(self.store.active_session_id, self.session_a)
        self.assertIn("question A", self.chat.log.toPlainText())
        self.assertNotIn("question B", self.chat.log.toPlainText())
        self.assertEqual(
            [message["content"] for message in self.chat._pending_messages],
            ["question A", "answer A"])

    def test_non_visible_session_actions_keep_chat_untouched(self):
        self.chat.load_session(self.session_b)
        log_before, pending_before = self._log_and_pending()
        self._select(self.session_a)
        self.dialog._archive()
        log_after, pending_after = self._log_and_pending()
        self.assertEqual(log_after, log_before)
        self.assertEqual(pending_after, pending_before)
        self.assertEqual(self.store.active_session_id, self.session_b)

    def test_delete_refused_while_request_in_flight(self):
        self.chat.load_session(self.session_b)
        release = threading.Event()
        self.addCleanup(release.set)

        def slow_chat(messages, images=None, cancel_event=None):
            release.wait(timeout=5)
            return "late answer"
        client = Mock()
        client.chat.side_effect = slow_chat
        self.chat.ai_client = client
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat.input.setText("pending question")
            self.chat._on_send()
            self.addCleanup(self.chat._worker_thread.join)
            self.assertTrue(self.chat.request_in_flight())
            log_before, pending_before = self._log_and_pending()
            self._select(self.session_b)
            with patch("PySide6.QtWidgets.QMessageBox.information"):
                self.dialog._delete()
            self.assertEqual(self.store.active_session_id, self.session_b)
            self.assertIn(self.session_b,
                          [s["id"] for s in self.store.list_sessions()])
            log_after, pending_after = self._log_and_pending()
            self.assertEqual(log_after, log_before)
            self.assertEqual(pending_after, pending_before)


class _ShellStub(QtWidgets.QWidget if QT_AVAILABLE else object):
    def __init__(self, store, chat):
        if QT_AVAILABLE:
            super().__init__()
        self.history_store = store
        self.chat = chat


if __name__ == "__main__":
    unittest.main()
