"""A queued worker signal must stay bound to the request that emitted it.

request_in_flight() used to be only _worker_thread.is_alive(): the thread
died, the Qt signal stayed queued, and the guards already stopped refusing.
A second send replaced the single _request_session_id, so the late slot
could store or show the answer on the new request, and _finish_request()
cleared the id of the request that was still running. The slots now carry
the (serial, session) token captured at dispatch time.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.history_store import HistoryStore
from src.qt_chat import QT_AVAILABLE, QtChatWidget

if QT_AVAILABLE:
    from PySide6 import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for late signal tests")
class TestQtLateSignalBinding(unittest.TestCase):
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
        self.config = Mock()
        self.config.get.side_effect = lambda key, default=None: default
        self.client = Mock()
        self.client.chat.return_value = "unused"
        self.offline = Mock(distro=None, system_context=None)
        self.chat = QtChatWidget(self.config, self.offline,
                                 history_store=self.store,
                                 ai_client=self.client)
        self.addCleanup(self.chat.close)
        self.addCleanup(self._join_worker)

    def _join_worker(self):
        thread = self.chat._worker_thread
        if thread is not None:
            self.chat._cancel_event.set()
            thread.join(timeout=5)
        self.app.processEvents()

    def _blocking_client(self, gate, answer):
        def slow_chat(messages, images=None, cancel_event=None):
            gate.wait(timeout=5)
            return answer
        client = Mock()
        client.chat.side_effect = slow_chat
        return client

    def _send(self, text):
        with patch("src.qt_chat.should_use_provider", return_value=True):
            self.chat.input.setText(text)
            self.chat._on_send()

    def test_late_signal_cannot_clear_the_running_request_state(self):
        """Second send after thread death: the late slot stays bound.

        The first worker dies with its finished signal queued, a second
        send starts (the alive-thread guard passes on a dead thread), and
        only then is the queued signal delivered.
        """
        first_gate = threading.Event()
        self.chat.ai_client = self._blocking_client(first_gate, "first answer")
        self._send("first question")
        first_thread = self.chat._worker_thread
        self.assertTrue(self.chat.request_in_flight())
        first_gate.set()
        first_thread.join(timeout=5)
        self.assertFalse(first_thread.is_alive())
        # The thread is dead but its slot has not run: still in flight.
        self.assertTrue(self.chat.request_in_flight())
        # The second send replaces the widget-level request state.
        second_gate = threading.Event()
        self.addCleanup(second_gate.set)
        self.chat.ai_client = self._blocking_client(second_gate, "second answer")
        self._send("second question")
        second_thread = self.chat._worker_thread
        self.assertIsNot(second_thread, first_thread)
        self.assertTrue(self.chat.request_in_flight())
        # Deliver the first worker's queued signal after the second send.
        self.app.processEvents()
        # The late answer was stored in the session that originated it.
        stored = [message for message in self.store.load_messages()
                  if message["role"] == "assistant"]
        self.assertTrue(any(message["content"] == "first answer"
                             for message in stored))
        # The running second request kept its pending state.
        self.assertIsNotNone(self.chat._request_session_id)
        self.assertTrue(self.chat.request_in_flight())
        # The late signal did not undo the Thinking/Stop state either: the
        # second worker is alive, the input stays disabled, the button stays
        # Stop and the thinking indicator stays visible.
        self.assertTrue(second_thread.is_alive())
        self.assertFalse(self.chat.input.isEnabled())
        from src import i18n
        self.assertEqual(self.chat.send_button.text(), i18n._("Stop"))
        self.assertTrue(self.chat.status_label.isVisibleTo(self.chat))
        # The late slot did not finish the second request: its answer is
        # still pending and the log holds only the first answer.
        self.assertIn("first answer", self.chat.log.toPlainText())
        self.assertNotIn("second answer", self.chat.log.toPlainText())

    def test_late_signal_after_session_change_stores_only_in_origin(self):
        """Session change after thread death: the late slot stays bound.

        The first worker dies with its finished signal queued; the store's
        active session moves to another conversation before the queued
        signal is delivered.
        """
        session_a = self.store.active_session_id
        created = self.store.create_session(select=True)
        session_b = created["id"]
        self.chat.load_session(session_b)
        gate = threading.Event()
        self.chat.ai_client = self._blocking_client(gate, "late answer")
        self._send("question for B")
        worker_thread = self.chat._worker_thread
        gate.set()
        worker_thread.join(timeout=5)
        self.assertFalse(worker_thread.is_alive())
        self.assertTrue(self.chat.request_in_flight())
        # The session change starts while the answer is still queued.
        self.store.select_session(session_a)
        self.assertEqual(self.chat._current_session_id(), session_a)
        self.app.processEvents()
        # The late answer landed in B, the session that asked; A stayed clean.
        stored_b = [message for message in self.store.load_messages(session_b)
                    if message["role"] == "assistant"]
        self.assertEqual([message["content"] for message in stored_b],
                         ["late answer"])
        stored_a = [message for message in self.store.load_messages(session_a)
                    if message["role"] == "assistant"]
        self.assertEqual(stored_a, [])
        # It is not shown and does not join the provider context of A.
        self.assertNotIn("late answer", self.chat.log.toPlainText())
        self.assertNotIn("late answer",
                         [message["content"]
                          for message in self.chat._pending_messages])
        # With no other request running, the slot finished this one.
        self.assertIsNone(self.chat._request_session_id)
        self.assertFalse(self.chat.request_in_flight())


if __name__ == "__main__":
    unittest.main()
