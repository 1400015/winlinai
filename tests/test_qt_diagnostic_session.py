"""A conversation's guide must stay in the conversation that started it.

The Qt widget never touched the diagnostic continuation: load_session
only re-read messages and _send_to_offline stored only the answer text.
A guide started in session A kept advancing in whatever session was
opened next - the assistant's in-memory continuation leaked across
conversations - and nothing was persisted, so reopening A lost the
saved position. The widget now rebinds the assistant on every session
change (restore_diagnostic for a valid stored state, reset_conversation
otherwise) and stores diagnostic_state() in the session that received
each offline answer.
"""
import os
import tempfile
import unittest
from pathlib import Path

from src.qt_chat import QT_AVAILABLE, QtChatWidget, should_use_provider
from src.history_store import HistoryStore
from src.offline_assistant import OfflineAssistant
from src.system_utils import SystemUtils
from src.config_manager import ConfigManager

if QT_AVAILABLE:
    from PySide6 import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for diagnostic session tests")
class TestQtDiagnosticSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.config = ConfigManager(str(self.dir / "config.json"))
        self.config.set("assistance.mode", "offline")
        self.store = HistoryStore(str(self.dir / "history.json"))
        self.addCleanup(self.store.close)
        self.assistant = OfflineAssistant(SystemUtils(self.config), self.config)
        self.chat = QtChatWidget(self.config, self.assistant,
                                 history_store=self.store, ai_client=None)
        self.addCleanup(self.chat.close)

    def _send(self, text):
        self.assertFalse(should_use_provider(self.chat.ai_client, self.config))
        self.chat.input.setText(text)
        self.chat._on_send()
        self.app.processEvents()

    def test_guide_does_not_leak_into_another_session(self):
        """The guide of A must not answer in B opened through Open's path."""
        session_a = self.store.active_session_id
        self._send("guia network-interface")
        self.assertEqual(self.assistant.diagnostic_state(),
                         {"id": "network-interface", "step": 0})
        # Open's real path: the store selects, then the chat loads.
        created = self.store.create_session(select=True)
        session_b = created["id"]
        self.store.select_session(session_b)
        self.chat.load_session(session_b)
        self.assertEqual(self.chat.log.toPlainText(), "")
        # B has no guide: its answer must not advance network-interface.
        self._send("e depois?")
        self.assertIsNone(self.assistant.diagnostic_state())
        log = self.chat.log.toPlainText()
        self.assertNotIn("ip-address", log)
        self.assertNotIn("Next step", log)
        # The stored state of A is untouched by B's answer.
        self.assertEqual(self.store.get_diagnostic_state(session_a),
                         {"id": "network-interface", "step": 0})
        self.assertIsNone(self.store.get_diagnostic_state(session_b))

    def test_reopened_session_continues_its_saved_step(self):
        """Reopening A (also through a fresh store) restores its position."""
        session_a = self.store.active_session_id
        self._send("guia network-interface")
        created = self.store.create_session(select=True)
        session_b = created["id"]
        self.store.select_session(session_b)
        self.chat.load_session(session_b)
        self.assertIsNone(self.assistant.diagnostic_state())
        # Back to A through Open's path.
        self.store.select_session(session_a)
        self.chat.load_session(session_a)
        self.assertEqual(self.assistant.diagnostic_state(),
                         {"id": "network-interface", "step": 0})
        self._send("next")
        self.assertEqual(self.assistant.diagnostic_state(),
                         {"id": "network-interface", "step": 1})
        self.assertEqual(self.store.get_diagnostic_state(session_a),
                         {"id": "network-interface", "step": 1})
        self.assertIsNone(self.store.get_diagnostic_state(session_b))
        # A brand-new store over the same file still sees A's position.
        reopened = HistoryStore(self.store.path)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.get_diagnostic_state(session_a),
                         {"id": "network-interface", "step": 1})

    def test_new_conversation_does_not_continue_the_previous_guide(self):
        """clear_conversation leaves the previous guide behind."""
        self._send("guia network-interface")
        self.assertEqual(self.assistant.diagnostic_state(),
                         {"id": "network-interface", "step": 0})
        self.chat.clear_conversation()
        self.assertIsNone(self.assistant.diagnostic_state())
        self._send("e depois?")
        self.assertIsNone(self.assistant.diagnostic_state())
        log = self.chat.log.toPlainText()
        self.assertNotIn("ip-address", log)
        self.assertNotIn("Next step", log)

    def test_late_offline_answer_cannot_advance_another_session_guide(self):
        """A stale answer's session receives its own guide position only.

        A request started in A settles after the user already switched
        to B: the step belongs to A's stored state, never to B's.
        """
        session_a = self.store.active_session_id
        self._send("guia network-interface")
        created = self.store.create_session(select=True)
        session_b = created["id"]
        # Simulate the switch happening while A's answer is still the
        # captured request: the diagnostic write goes to the captured
        # session, the same one _store_response writes to.
        self.store.select_session(session_b)
        self.chat._request_session_id = session_a
        self.chat._send_to_offline("next")
        self.assertEqual(self.store.get_diagnostic_state(session_a)["step"], 1)
        self.assertIsNone(self.store.get_diagnostic_state(session_b))

    def test_session_without_diagnostic_answers_without_advancing(self):
        """A session with no guide answers 'e depois?' plainly."""
        self._send("e depois?")
        self.assertIsNone(self.assistant.diagnostic_state())


if __name__ == "__main__":
    unittest.main()
