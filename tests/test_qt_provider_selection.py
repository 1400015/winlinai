"""The next request must use the provider and mode currently selected.

should_use_provider only looked for API keys and ignored
assistance.mode: with a key configured, selecting offline mode kept
dispatching the next request to the provider worker (which then failed
inside the worker instead of using the offline assistant), and the
visible indicator kept saying "AI Provider mode". In local mode with
no API keys, the next request fell to the offline assistant although
the user had selected the local LLM. The router now resolves the
selection through the same client the request uses.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.qt_chat import QT_AVAILABLE, QtChatWidget, should_use_provider

if QT_AVAILABLE:
    from PySide6 import QtWidgets


def _config(path):
    from src.config_manager import ConfigManager
    return ConfigManager(str(path / "config.json"))


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for provider selection tests")
class TestProviderSelectionFollowsConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from src.ai_client import AIClient
        from src.history_store import HistoryStore
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.dir = Path(directory.name)
        self.config = _config(self.dir)
        self.config.set("api.default_provider", "mistral")
        self.config.set_api_key("mistral", "sk-live")
        self.store = HistoryStore(str(self.dir / "history.json"))
        self.addCleanup(self.store.close)
        self.client = AIClient(self.config)
        self.chat = QtChatWidget(self.config,
                                 Mock(distro=None, system_context=None),
                                 history_store=self.store,
                                 ai_client=self.client)
        self.addCleanup(self.chat.close)

    def test_offline_selection_routes_the_next_request_offline(self):
        """Selecting offline mode must reach the next request, not just the client.

        The old router returned True with a key present, so the worker
        was dispatched to the provider while the visible mode said
        offline; the request then failed inside the worker.
        """
        self.assertTrue(should_use_provider(self.chat.ai_client, self.config))
        self.config.set("assistance.mode", "offline")
        # What the user sees:
        self.chat._update_provider_indicator()
        self.assertEqual(self.chat.windowTitle(), "Offline mode")
        # What the next request uses: the same selection.
        self.assertFalse(should_use_provider(self.chat.ai_client, self.config))

    def test_local_selection_routes_the_next_request_to_the_local_llm(self):
        """In local mode with no API keys, the next request uses the local LLM."""
        self.config.set("assistance.mode", "local")
        self.config.set("api.providers.local_llm.base_url", "http://127.0.0.1:11434")
        self.config.set("api.providers.local_llm.model", "llama3")
        self.assertEqual(self.client.active_provider(), "local_llm")
        self.assertTrue(should_use_provider(self.chat.ai_client, self.config))

    def test_next_request_matches_the_visible_offline_selection(self):
        """End to end: the send itself goes offline after the switch.

        The send itself updates the indicator: the title must reflect the
        selection without any manual indicator call before checking it.
        """
        self.config.set("assistance.mode", "offline")
        with patch("src.qt_chat.offline_reply_text",
                   return_value="offline answer") as offline:
            self.chat.input.setText("hello")
            self.chat._on_send()
        self.assertTrue(offline.called)
        thread = self.chat._worker_thread
        self.addCleanup(self._join, thread)
        self.assertIsNone(thread, "the request was dispatched to the provider worker")
        self.assertEqual(self.chat.windowTitle(), "Offline mode")

    def test_remote_mode_with_local_selection_is_refused(self):
        """Remote mode with local_llm selected is a refusal, not offline.

        active_provider() raises ProviderNotConfigured; the old router
        swallowed it into False and the request fell to the offline
        assistant. The refusal must be visible: no offline call, no
        provider worker, and a system line in the log.
        """
        from src.ai_client import ProviderNotConfigured
        self.config.set("assistance.mode", "remote")
        self.config.set("api.default_provider", "local_llm")
        with self.assertRaises(ProviderNotConfigured):
            should_use_provider(self.chat.ai_client, self.config)
        with patch("src.qt_chat.offline_reply_text",
                   return_value="offline answer") as offline:
            self.chat.input.setText("hello")
            self.chat._on_send()
        thread = self.chat._worker_thread
        self.addCleanup(self._join, thread)
        self.assertFalse(offline.called, "a refusal must not reach the offline assistant")
        self.assertIsNone(thread, "a refusal must not dispatch the provider worker")
        log = self.chat.log.toPlainText()
        self.assertIn("Choose a remote provider", log)
        self.assertNotIn("offline answer", log)
        # The send itself refreshes the indicator: the title no longer
        # claims "AI Provider mode" after the switch.
        self.assertNotEqual(self.chat.windowTitle(), "AI Provider mode")

    def _join(self, thread):
        if thread is not None:
            self.chat._cancel_event.set()
            thread.join(timeout=5)
        self.app.processEvents()


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for expert mode tests")
class TestExpertModeFollowsConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_file_write_not_offered_with_expert_mode_off(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        config = _config(base)
        config.set("app.expert_mode", True)
        config.set("permissions.allowed_edit_dirs", [str(base)])
        from src.history_store import HistoryStore
        store = HistoryStore(str(base / "history.json"))
        self.addCleanup(store.close)
        chat = QtChatWidget(config, Mock(distro=None, system_context=None),
                           history_store=store, ai_client=None)
        self.addCleanup(chat.close)
        target = base / "out.py"
        reply = "```{}\nprint('x')\n```".format(target)
        config.set("app.expert_mode", False)
        with patch("src.qt_file_dialogs.confirm_file_write_qt",
                   return_value=True) as confirmed:
            chat._offer_file_blocks(reply)
        self.assertFalse(confirmed.called)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
