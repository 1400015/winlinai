"""New-conversation failures must preserve the visible and provider context."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.history_store import HistoryStore
from src.qt_chat import QT_AVAILABLE, QtChatWidget

if QT_AVAILABLE:
    from PySide6 import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for conversation tests")
class TestQtClearConversation(unittest.TestCase):
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
        self.origin = self.store.active_session_id
        self.messages = [
            {"role": "user", "content": "Keep this question"},
            {"role": "assistant", "content": "Keep this answer"},
        ]
        for message in self.messages:
            self.store.append(message["role"], message["content"])
        self.assertTrue(self.store.flush(timeout=5))
        self.assertEqual(len(self.store.list_sessions()), 1)
        config = Mock()
        config.get.side_effect = lambda key, default=None: default
        offline = Mock(distro=None, system_context=None)
        self.client = Mock()
        self.client.chat.return_value = "Continued answer"
        self.chat = QtChatWidget(config, offline, history_store=self.store,
                                 ai_client=self.client)
        self.addCleanup(self.chat.close)
        self.addCleanup(self._settle_worker)
        # Include context that has not reached the saved history: reloading
        # the session after a failure would also lose this context.
        self.chat.append_message("AI", "Answer still in memory")
        self.chat._pending_messages.append(
            {"role": "assistant", "content": "Answer still in memory"})
        self.chat.input.setText("Unsent draft")

    def _settle_worker(self):
        thread = self.chat._worker_thread
        if thread is not None:
            self.chat._cancel_event.set()
            thread.join(timeout=5)
        self.app.processEvents()

    def _assert_failed_clear_preserves_conversation(self):
        visible = self.chat.log.toPlainText()
        characters = self.chat._log_chars
        pending = self.chat._pending_messages
        context = [dict(message) for message in pending]
        original_file = self.path.read_bytes()
        with self.assertLogs("src.qt_chat", level="WARNING"):
            self.chat.clear_conversation()
        self.assertEqual(self.chat.log.toPlainText(), visible)
        self.assertEqual(self.chat._log_chars, characters)
        self.assertIs(self.chat._pending_messages, pending)
        self.assertEqual(self.chat._pending_messages, context)
        self.assertEqual(self.chat.input.text(), "Unsent draft")
        self.assertEqual(self.store.active_session_id, self.origin)
        self.assertEqual(self.path.read_bytes(), original_file)
        self.assertEqual(self.store.load_messages(), self.messages)
        self.assertEqual(len(self.store.list_sessions()), 1)

    def test_publication_failure_preserves_conversation(self):
        # Run the real transaction and temporary-file write, then refuse rename.
        with patch("src.storage._publish_temporary",
                   side_effect=OSError("Publication refused")) as publish:
            self._assert_failed_clear_preserves_conversation()
        publish.assert_called_once()
        self.assertEqual(list(self.path.parent.glob("history.json.*.tmp")), [])

    def test_session_limit_preserves_conversation(self):
        with patch("src.history_store.MAX_SESSIONS", 1):
            self._assert_failed_clear_preserves_conversation()

    def test_next_provider_request_keeps_context_and_origin_after_failure(self):
        context = [dict(message) for message in self.chat._pending_messages]
        with patch("src.storage._publish_temporary",
                   side_effect=OSError("Publication refused")), \
                self.assertLogs("src.qt_chat", level="WARNING"):
            self.chat.clear_conversation()
        follow_up = {"role": "user", "content": "Continue this conversation"}
        self.chat.input.setText(follow_up["content"])
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat._on_send()
            self.chat._worker_thread.join(timeout=5)
        self.assertFalse(self.chat._worker_thread.is_alive())
        self.app.processEvents()
        self.client.chat.assert_called_once()
        sent = self.client.chat.call_args[0][0]
        self.assertEqual(sent[1:], context + [follow_up])
        self.assertTrue(self.store.flush(timeout=5))
        self.assertEqual(self.store.active_session_id, self.origin)
        self.assertEqual(self.store.load_messages(self.origin), self.messages + [
            follow_up, {"role": "assistant", "content": "Continued answer"}])
        self.assertIn("Keep this answer", self.chat.log.toPlainText())
        self.assertIn("Continued answer", self.chat.log.toPlainText())

    def test_success_selects_empty_session_and_keeps_previous_history(self):
        self.chat.clear_conversation()
        self.assertNotEqual(self.store.active_session_id, self.origin)
        self.assertEqual(len(self.store.list_sessions()), 2)
        self.assertEqual(self.store.load_messages(), [])
        self.assertEqual(self.store.load_messages(self.origin), self.messages)
        self.assertEqual(self.chat.log.toPlainText(), "")
        self.assertEqual(self.chat._log_chars, 0)
        self.assertEqual(self.chat._pending_messages, [])

    def test_without_history_clears_local_conversation(self):
        self.chat.history_store = None
        original_file = self.path.read_bytes()
        self.chat.clear_conversation()
        self.assertEqual(self.chat.log.toPlainText(), "")
        self.assertEqual(self.chat._log_chars, 0)
        self.assertEqual(self.chat._pending_messages, [])
        self.assertEqual(self.path.read_bytes(), original_file)
