"""End-to-end integration tests for the Qt track on Windows.

These tests exercise the full flow: shell creation → chat → offline response
→ history persistence → theme application → conversation actions.

They require PySide6 and run with QT_QPA_PLATFORM=offscreen on CI.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import i18n

# Skip all tests if PySide6 is not available
try:
    from PySide6 import QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for E2E tests")
class TestQtE2EBase(unittest.TestCase):
    """Base class with common setup for E2E tests."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config = self._make_config()

    def _make_config(self):
        """Create a fake config manager with persistent get/set state."""
        config = Mock()
        values = {
            "app.expert_mode": False,
            "app.tray_toggle_on_click": True,
            "ui.theme": "dark",
            "features.expert_mode": True,
        }
        config.get = Mock(side_effect=lambda key, default=None: values.get(key, default))
        config.set = Mock(side_effect=lambda key, value: values.__setitem__(key, value))
        config.get_api_key = Mock(return_value=None)
        config.api_key_env_var = Mock(return_value="TEST_KEY")
        config.get_api_key_env_override = Mock(return_value=None)
        return config


class TestQtShellE2E(TestQtE2EBase):
    """End-to-end tests for the Qt shell."""

    def test_shell_creates_with_all_components(self):
        """Shell should create with chat, history, and tray."""
        from src.qt_app import QtShell
        history_path = Path(self.temp_dir.name) / "history.json"
        shell = QtShell(self.config, "windows", history_path=str(history_path))
        self.addCleanup(shell.close)

        # Verify components
        self.assertIsNotNone(shell.chat)
        self.assertIsNotNone(shell.history_store)
        self.assertEqual(shell.platform_name, "windows")

    def test_offline_chat_flow(self):
        """Full offline chat flow: send message → get response → save history."""
        from src.qt_app import QtShell

        history_path = Path(self.temp_dir.name) / "history.json"
        shell = QtShell(self.config, "windows", history_path=str(history_path))
        self.addCleanup(shell.close)

        # Send a message through the chat widget
        chat = shell.chat
        chat.input.setText("hello")
        chat._on_send()

        # Verify message was added to log
        log_text = chat.log.toPlainText()
        self.assertIn(i18n._("User"), log_text)
        self.assertIn("hello", log_text)
        # Should have an AI response (offline assistant)
        self.assertIn(i18n._("AI"), log_text)

    def test_history_persistence(self):
        """Messages should persist to history file."""
        from src.qt_app import QtShell

        history_path = Path(self.temp_dir.name) / "history.json"
        shell = QtShell(self.config, "windows", history_path=str(history_path))
        self.addCleanup(shell.close)

        # Send a message
        chat = shell.chat
        chat.input.setText("test message for history")
        chat._on_send()

        # Close history to flush
        shell._close_history()

        # Verify history file exists and contains the message
        self.assertTrue(history_path.exists())
        content = history_path.read_text(encoding="utf-8")
        self.assertIn("test message for history", content)

    def test_theme_application(self):
        """Theme should be applied to the application."""
        from src.qt_theme import apply_theme, load_theme

        theme = load_theme("dark")
        apply_theme(self.app, theme)

        # Verify stylesheet was set
        stylesheet = self.app.styleSheet()
        self.assertTrue(len(stylesheet) > 0)
        self.assertIn("QWidget", stylesheet)

    def test_conversation_actions(self):
        """Conversation actions should work (export, summary, etc.)."""
        from src.qt_conversation_actions import (
            export_to_markdown,
            summarize_messages,
            count_messages,
        )

        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # Test export
        md = export_to_markdown(messages, "Test")
        self.assertIn("# Test", md)
        self.assertIn("Hello", md)

        # Test summary
        summary = summarize_messages(messages)
        self.assertIn("2 messages", summary)

        # Test count
        counts = count_messages(messages)
        self.assertEqual(counts["total"], 2)

    def test_expert_mode_toggle(self):
        """Expert mode should toggle and persist."""
        from src.qt_app import QtShell

        history_path = Path(self.temp_dir.name) / "history.json"
        shell = QtShell(self.config, "windows", history_path=str(history_path))
        self.addCleanup(shell.close)

        # Toggle expert mode
        shell.on_expert_mode_toggled(None)
        self.config.set.assert_called_with("app.expert_mode", True)

        # Toggle back
        shell.on_expert_mode_toggled(None)
        self.config.set.assert_called_with("app.expert_mode", False)


class TestQtDialogsE2E(TestQtE2EBase):
    """End-to-end tests for Qt dialogs."""

    def test_settings_dialog_creates(self):
        """Settings dialog should create without errors."""
        from src.qt_dialogs import QtSettingsDialog

        dialog = QtSettingsDialog(self.config)
        self.addCleanup(dialog.close)

        self.assertIsNotNone(dialog.provider_combo)
        self.assertIsNotNone(dialog.key_edit)
        # Theme selector should be present
        self.assertIsNotNone(dialog.theme_combo)

    def test_history_dialog_creates(self):
        """History dialog should create with a store."""
        from src.qt_dialogs import QtHistoryDialog
        from src.history_store import HistoryStore

        history_path = Path(self.temp_dir.name) / "history.json"
        store = HistoryStore(str(history_path))
        self.addCleanup(store.close)

        dialog = QtHistoryDialog(store)
        self.addCleanup(dialog.close)

        self.assertIsNotNone(dialog.list_widget)

    def test_statistics_dialog_creates(self):
        """Statistics dialog should create with or without AI client."""
        from src.qt_dialogs import QtStatisticsDialog

        # Without client
        dialog = QtStatisticsDialog(None)
        self.addCleanup(dialog.close)
        self.assertIsNotNone(dialog)

        # With mock client
        ai_client = Mock()
        ai_client.get_token_usage.return_value = {
            "openrouter": {"input": 100, "output": 50, "total": 150}
        }
        dialog2 = QtStatisticsDialog(ai_client)
        self.addCleanup(dialog2.close)
        self.assertIsNotNone(dialog2)


class TestWindowsFoundationE2E(TestQtE2EBase):
    """End-to-end tests for Windows foundation components."""

    def test_pwsh_output_normalization(self):
        """PowerShell output normalization should work end-to-end."""
        import base64

        from src.platform.pwsh_output import (
            wrap_cmdlet_json,
            parse_json_output,
            normalize_output,
        )

        # Wrap a cmdlet
        argv = wrap_cmdlet_json(["Get-Service", "-Name", "wuauserv"])
        self.assertEqual(argv[0], "powershell")
        script = base64.b64decode(argv[5]).decode("utf-16-le")
        self.assertIn("Get-Service", script)

        # Parse JSON output
        json_output = '{"Name":"wuauserv","Status":4,"DisplayName":"Windows Update","StartType":3}'
        data, error = parse_json_output(json_output)
        self.assertIsNone(error)
        self.assertEqual(data["Name"], "wuauserv")

        # Normalize
        normalized = normalize_output(data, probe_key="services")
        self.assertEqual(normalized["name"], "wuauserv")
        self.assertEqual(normalized["display_name"], "Windows Update")

    def test_autostart_logic(self):
        """Autostart logic should work with mocked backends."""
        from src.windows_autostart import (
            apply_autostart,
            autostart_command,
            autostart_should_update,
        )

        # Test command building
        cmd = autostart_command("powershell.exe", "C:\\app\\run.ps1")
        self.assertIn("powershell.exe", cmd)
        self.assertIn("run.ps1", cmd)

        # Test idempotency
        self.assertFalse(autostart_should_update("cmd", "cmd"))
        self.assertTrue(autostart_should_update("cmd", "other"))

        # Test apply with mocked backends
        state = {"value": None}
        read = Mock(side_effect=lambda k, n: state["value"])
        write = Mock(side_effect=lambda k, n, v: state.update(value=v))
        delete = Mock(side_effect=lambda k, n: state.update(value=None))

        result = apply_autostart(True, "test-cmd", read, write, delete)
        self.assertEqual(result, "enabled")
        write.assert_called_once()

    def test_theme_stylesheet_generation(self):
        """Theme should generate valid QSS stylesheet."""
        from src.qt_theme import load_theme, theme_to_stylesheet

        for theme_name in ["dark", "light"]:
            with self.subTest(theme=theme_name):
                theme = load_theme(theme_name)
                qss = theme_to_stylesheet(theme)
                self.assertIn("QWidget", qss)
                self.assertIn("QPushButton", qss)
                self.assertIn(theme["colors"].get("background", "#1e1e1e"), qss)


class TestQtChatE2E(TestQtE2EBase):
    """End-to-end tests for the Qt chat widget."""

    def test_chat_widget_creation(self):
        """Chat widget should create with offline assistant."""
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        system_utils = SystemUtils(self.config)
        offline = OfflineAssistant(system_utils, self.config)

        chat = QtChatWidget(self.config, offline, ai_client=None)
        self.addCleanup(chat.close)

        self.assertIsNotNone(chat.log)
        self.assertIsNotNone(chat.input)
        self.assertIsNotNone(chat.send_button)
        # Attachment buttons should be present
        self.assertIsNotNone(chat.attach_button)
        self.assertIsNotNone(chat.screenshot_button)

    def test_chat_offline_response(self):
        """Chat should respond via offline assistant."""
        from src.qt_chat import QtChatWidget, should_use_provider
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        system_utils = SystemUtils(self.config)
        offline = OfflineAssistant(system_utils, self.config)

        # Verify provider detection returns False (no API keys)
        self.assertFalse(should_use_provider(None, self.config))

        chat = QtChatWidget(self.config, offline, ai_client=None)
        self.addCleanup(chat.close)

        # Send a message
        chat.input.setText("hello")
        chat._on_send()

        # Should have user and AI messages
        log_text = chat.log.toPlainText()
        self.assertIn(i18n._("User"), log_text)
        self.assertIn(i18n._("AI"), log_text)


class TestQtFileBlocksE2E(TestQtE2EBase):
    """E2E: AI reply with a ``` file block triggers write flow (expert mode)."""

    def _make_expert_config(self, allowed_dir):
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.expert_mode": True,
            "app.tray_toggle_on_click": True,
            "permissions.allowed_edit_dirs": [str(allowed_dir)],
        }.get(key, default))
        config.set = Mock()
        config.get_api_key = Mock(return_value=None)
        return config

    def test_file_block_written_when_confirmed(self):
        """A ``` block in the AI reply is written after Qt confirmation."""
        from unittest.mock import patch
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        target = Path(self.temp_dir.name) / "hello.py"
        config = self._make_expert_config(self.temp_dir.name)
        system_utils = SystemUtils(config)
        offline = OfflineAssistant(system_utils, config)
        chat = QtChatWidget(config, offline, ai_client=None)
        self.addCleanup(chat.close)

        reply = f"Here is the file:\n```\n{target}\nprint('hi')\n```\nDone."
        with patch("src.qt_file_dialogs.confirm_file_write_qt", return_value=True):
            chat._on_provider_response(reply)

        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(encoding="utf-8"), "print('hi')\n")
        log_text = chat.log.toPlainText()
        self.assertIn(i18n._("File written: {path}").format(path=str(target)), log_text)

    def test_file_block_skipped_when_cancelled(self):
        """Cancelling the confirmation dialog leaves no file behind."""
        from unittest.mock import patch
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        target = Path(self.temp_dir.name) / "nope.py"
        config = self._make_expert_config(self.temp_dir.name)
        system_utils = SystemUtils(config)
        offline = OfflineAssistant(system_utils, config)
        chat = QtChatWidget(config, offline, ai_client=None)
        self.addCleanup(chat.close)

        reply = f"```\n{target}\nprint('nope')\n```"
        with patch("src.qt_file_dialogs.confirm_file_write_qt", return_value=False):
            chat._on_provider_response(reply)

        self.assertFalse(target.exists())
        self.assertIn(i18n._("File write cancelled: {path}").format(path=str(target)),
                      chat.log.toPlainText())

    def test_file_blocks_ignored_without_expert_mode(self):
        """Without expert mode, file blocks in replies are not offered."""
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        target = Path(self.temp_dir.name) / "ignored.py"
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.expert_mode": False,
            "permissions.allowed_edit_dirs": [str(self.temp_dir.name)],
        }.get(key, default))
        config.set = Mock()
        config.get_api_key = Mock(return_value=None)
        system_utils = SystemUtils(config)
        offline = OfflineAssistant(system_utils, config)
        chat = QtChatWidget(config, offline, ai_client=None)
        self.addCleanup(chat.close)

        reply = f"```\n{target}\nprint('ignored')\n```"
        chat._on_provider_response(reply)
        self.assertFalse(target.exists())

    def test_disallowed_path_is_rejected(self):
        """A path outside allowed dirs is rejected without a dialog."""
        from unittest.mock import patch
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils

        config = self._make_expert_config(self.temp_dir.name)
        system_utils = SystemUtils(config)
        offline = OfflineAssistant(system_utils, config)
        chat = QtChatWidget(config, offline, ai_client=None)
        self.addCleanup(chat.close)

        outside = Path(self.temp_dir.name).parent / "outside_target.py"
        reply = f"```\n{outside}\nprint('x')\n```"
        with patch("src.qt_file_dialogs.confirm_file_write_qt", return_value=True) as dialog:
            chat._on_provider_response(reply)
        dialog.assert_not_called()
        self.assertIn("not allowed", chat.log.toPlainText())


class TestQtFileDialogButtons(TestQtE2EBase):
    """The confirmation dialog's buttons conclude the dialog (no patching)."""

    def _make_dialog(self):
        from src.qt_file_dialogs import confirm_file_write_qt, QT_AVAILABLE
        if not QT_AVAILABLE:
            self.skipTest('PySide6 required for dialog tests')
        return confirm_file_write_qt

    def test_write_button_accepts_and_cancel_button_rejects(self):
        """A click on Write accepts; a click on Cancel rejects.

        Runs against the real dialog: the function is not patched, only
        exec() is replaced so the modal loop does not block the test.
        """
        from unittest.mock import patch
        from PySide6 import QtWidgets
        confirm = self._make_dialog()

        captured = {}

        def fake_exec(self_dialog):
            captured['dialog'] = self_dialog
            # Find the button box and click each button in turn.
            box = self_dialog.findChild(QtWidgets.QDialogButtonBox)
            self.assertIsNotNone(box)
            buttons = box.buttons()
            self.assertEqual(len(buttons), 2)
            # Click Write (AcceptRole) -> the dialog must accept.
            write_button = next(b for b in buttons
                                if box.buttonRole(b) == QtWidgets.QDialogButtonBox.AcceptRole)
            write_button.click()
            return self_dialog.result()

        with patch('PySide6.QtWidgets.QDialog.exec', side_effect=fake_exec, autospec=True):
            self.assertTrue(confirm(None, '/tmp/x.py', 'content', is_new=True))
            dialog = captured['dialog']
            self.assertEqual(dialog.result(), QtWidgets.QDialog.Accepted)

        def fake_exec_reject(self_dialog):
            box = self_dialog.findChild(QtWidgets.QDialogButtonBox)
            buttons = box.buttons()
            cancel_button = next(b for b in buttons
                                 if box.buttonRole(b) == QtWidgets.QDialogButtonBox.RejectRole)
            cancel_button.click()
            return self_dialog.result()

        with patch('PySide6.QtWidgets.QDialog.exec', side_effect=fake_exec_reject, autospec=True):
            self.assertFalse(confirm(None, '/tmp/y.py', 'content', is_new=True))


class TestQtUpdatesE2E(TestQtE2EBase):
    """E2E: Settings has an Updates section; startup check respects config."""

    def test_settings_dialog_has_updates_section(self):
        from src.qt_dialogs import QtSettingsDialog
        dialog = QtSettingsDialog(self.config)
        self.addCleanup(dialog.close)
        self.assertTrue(hasattr(dialog, "updates_check"))
        self.assertTrue(hasattr(dialog, "updates_status"))
        self.assertIsNotNone(dialog.updates_check)
        self.assertIsNotNone(dialog.updates_status)

    def test_maybe_check_updates_respects_config_disabled(self):
        from src.qt_app import _maybe_check_updates
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": False,
        }.get(key, default))
        config.set = Mock()
        with patch("src.qt_worker.Worker") as worker_cls:
            _maybe_check_updates(config, shell=None)
        worker_cls.assert_not_called()
        config.set.assert_not_called()

    @staticmethod
    def _sync_worker_patches(update_result):
        """Patches that make _maybe_check_updates run synchronously."""
        class FakeSignal:
            def __init__(self):
                self._slots = []
            def connect(self, slot):
                self._slots.append(slot)
            def emit(self, value):
                for slot in self._slots:
                    slot(value)

        class SyncWorker:
            def __init__(self):
                self.finished = FakeSignal()
                self.failed = FakeSignal()

        def sync_start_worker(worker, func, *args, **kwargs):
            worker.finished.emit(func(*args, **kwargs))

        def run_now(ms, func):
            func()

        return (
            patch("src.qt_worker.Worker", SyncWorker),
            patch("src.qt_worker.start_worker", sync_start_worker),
            patch("src.qt_app.QtCore.QTimer.singleShot", run_now),
            patch("src.updater.check_for_updates", return_value=update_result),
        )

    def test_maybe_check_updates_stores_available_update(self):
        from src.qt_app import _maybe_check_updates
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": True,
        }.get(key, default))
        config.set = Mock()
        fake_update = {"version": "9.9.9", "url": "https://github.com/1400015/winlinai/releases"}
        p_worker, p_start, p_timer, p_check = self._sync_worker_patches(fake_update)
        with p_worker, p_start, p_timer, p_check:
            _maybe_check_updates(config, shell=None)
        config.set.assert_any_call("update.available", True)
        config.set.assert_any_call("update.version", "9.9.9")

    def test_maybe_check_updates_quiet_when_none(self):
        from src.qt_app import _maybe_check_updates
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": True,
        }.get(key, default))
        config.set = Mock()
        p_worker, p_start, p_timer, p_check = self._sync_worker_patches(None)
        with p_worker, p_start, p_timer, p_check:
            _maybe_check_updates(config, shell=None)
        config.set.assert_not_called()

    def test_maybe_check_updates_notifies_shell(self):
        from src.qt_app import _maybe_check_updates
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": True,
        }.get(key, default))
        config.set = Mock()
        shell = Mock()
        fake_update = {"version": "9.9.9", "url": "https://example.com"}
        p_worker, p_start, p_timer, p_check = self._sync_worker_patches(fake_update)
        with p_worker, p_start, p_timer, p_check:
            _maybe_check_updates(config, shell=shell)
        shell.notify_update_available.assert_called_once_with(fake_update)


class TestQtProviderWorkerE2E(TestQtE2EBase):
    """E2E: provider worker signals - success, failure fallback, cancellation."""

    def _make_chat(self, ai_client):
        from src.qt_chat import QtChatWidget
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils
        system_utils = SystemUtils(self.config)
        offline = OfflineAssistant(system_utils, self.config)
        chat = QtChatWidget(self.config, offline, ai_client=ai_client)
        self.addCleanup(chat.close)
        return chat

    def test_provider_success_via_signal(self):
        ai_client = Mock()
        ai_client.chat.return_value = "Hello from AI"
        chat = self._make_chat(ai_client)
        with patch("src.qt_chat.should_use_provider", return_value=True):
            chat.input.setText("hi")
            chat._on_send()
            chat._worker_thread.join(timeout=5)
        # Deliver the worker's queued signals to the UI before asserting.
        self.app.processEvents()
        self.assertIn("Hello from AI", chat.log.toPlainText())

    def test_provider_failure_falls_back_to_offline(self):
        ai_client = Mock()
        ai_client.chat.side_effect = RuntimeError("boom")
        chat = self._make_chat(ai_client)
        with patch("src.qt_chat.should_use_provider", return_value=True):
            chat.input.setText("hello offline")
            chat._on_send()
            chat._worker_thread.join(timeout=5)
        # Deliver the worker's queued signals to the UI before asserting.
        self.app.processEvents()
        log_text = chat.log.toPlainText()
        self.assertIn(i18n._("(Provider unavailable, answered offline)"), log_text)

    def test_cancel_event_aborts_request(self):
        from src.ai_client import AIRequestCancelled

        def slow_chat(messages, images=None, cancel_event=None):
            if cancel_event is not None:
                cancel_event.wait(timeout=5)
            raise AIRequestCancelled("user stop")

        ai_client = Mock()
        ai_client.chat.side_effect = slow_chat
        chat = self._make_chat(ai_client)
        with patch("src.qt_chat.should_use_provider", return_value=True):
            chat.input.setText("long question")
            chat._on_send()
            chat._on_stop_clicked()
            chat._worker_thread.join(timeout=5)
        # Deliver the worker's queued signals to the UI before asserting.
        self.app.processEvents()
        self.assertIn(i18n._("Request cancelled."), chat.log.toPlainText())


class TestQtSessionIsolation(TestQtE2EBase):
    """A pending response must land in the conversation that originated it."""

    def _make_chat_with_history(self, ai_client):
        from src.qt_chat import QtChatWidget
        from src.history_store import HistoryStore
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils
        history_path = Path(self.temp_dir.name) / "history.json"
        store = HistoryStore(str(history_path))
        self.addCleanup(store.close)
        system_utils = SystemUtils(self.config)
        offline = OfflineAssistant(system_utils, self.config)
        chat = QtChatWidget(self.config, offline, ai_client=ai_client, history_store=store)
        self.addCleanup(chat.close)
        return chat, store

    def _messages(self, store, session_id):
        return store.load_messages(session_id)

    def test_answer_lands_in_originating_session_after_switch(self):
        ai_client = Mock()
        release = threading.Event()

        def slow_chat(messages, images=None, cancel_event=None):
            release.wait(timeout=5)
            return "answer to session A"

        ai_client.chat.side_effect = slow_chat
        chat, store = self._make_chat_with_history(ai_client)
        session_a = store.active_session_id
        store.create_session(select=True)
        session_b = store.active_session_id
        chat.load_session(session_b)
        with patch("src.qt_chat.should_use_provider", return_value=True):
            chat._request_session_id = session_a  # simulate the send that started in A
            chat._pending_messages.append({"role": "user", "content": "question for A"})
            release.set()
            chat._on_provider_response("answer to session A")
        self.app.processEvents()
        # The answer is stored in A, the session that originated the request.
        stored_a = [m for m in self._messages(store, session_a) if m["role"] == "assistant"]
        self.assertEqual(len(stored_a), 1)
        self.assertEqual(stored_a[0]["content"], "answer to session A")
        # Session B, the currently shown one, received nothing.
        stored_b = [m for m in self._messages(store, session_b) if m["role"] == "assistant"]
        self.assertEqual(stored_b, [])
        # The visible log is session B's; the answer is not shown there.
        self.assertNotIn("answer to session A", chat.log.toPlainText())

    def test_session_switch_refused_while_request_in_flight(self):
        ai_client = Mock()
        chat, store = self._make_chat_with_history(ai_client)
        # Simulate a request in flight with a thread that stays alive.
        release = threading.Event()

        def busy():
            release.wait(timeout=5)

        chat._worker_thread = threading.Thread(target=busy)
        chat._worker_thread.start()
        self.addCleanup(release.set)
        self.addCleanup(chat._worker_thread.join)
        active = store.active_session_id
        created = store.create_session(select=False)
        other = created["id"]
        self.assertNotEqual(other, active)
        chat.load_session(other)
        self.assertEqual(store.active_session_id, active)
        self.assertIn(i18n._("Wait for the pending answer before switching conversations."),
                      chat.log.toPlainText())
        chat.clear_conversation()
        self.assertEqual(store.active_session_id, active)

    def test_archive_or_delete_of_origin_session_does_not_write_to_survivor(self):
        ai_client = Mock()
        chat, store = self._make_chat_with_history(ai_client)
        session_a = store.active_session_id
        store.create_session(select=True)
        session_b = store.active_session_id
        # The request originated in A; A was deleted while it was pending.
        store.delete_session(session_a)
        chat._request_session_id = session_a
        chat._on_provider_response("late answer")
        self.app.processEvents()
        # Nothing was written to B, the session that stayed active.
        stored_b = [m for m in self._messages(store, session_b) if m["role"] == "assistant"]
        self.assertEqual(stored_b, [])
        # The pending state was cleared.
        self.assertIsNone(chat._request_session_id)

    def test_cancelled_request_stores_no_answer(self):
        ai_client = Mock()
        chat, store = self._make_chat_with_history(ai_client)
        session_a = store.active_session_id
        chat._request_session_id = session_a
        chat._on_provider_cancelled("long question")
        self.app.processEvents()
        stored = [m for m in self._messages(store, session_a) if m["role"] == "assistant"]
        self.assertEqual(stored, [])

    def test_history_dialog_new_refused_while_request_in_flight(self):
        """New must not create a session while a request is pending.

        The dialog is wired exactly like QtShell.open_history_dialog: the
        shell (parent) owns the chat, and the worker thread is alive. The
        pending state comes from a real send, not from an injected
        _request_session_id.
        """
        from src.qt_app import QtShell
        from src.qt_dialogs import QtHistoryDialog

        history_path = Path(self.temp_dir.name) / "history.json"
        shell = QtShell(self.config, "windows", history_path=str(history_path))
        self.addCleanup(shell.close)
        chat = shell.chat
        store = shell.history_store
        self.assertIsNotNone(chat)
        self.assertIsNotNone(store)
        # A real pending request: patch the provider path so the worker
        # stays alive until this test releases it.
        release = threading.Event()

        def slow_chat(messages, images=None, cancel_event=None):
            release.wait(timeout=5)
            return "late answer"

        ai_client = Mock()
        ai_client.chat.side_effect = slow_chat
        chat.ai_client = ai_client
        with patch("src.qt_chat.should_use_provider", return_value=True):
            chat.input.setText("pending question")
            chat._on_send()
            self.addCleanup(release.set)
            self.addCleanup(chat._worker_thread.join)
            self.assertTrue(chat.request_in_flight())
            active_before = store.active_session_id
            sessions_before = len(store.list_sessions())
            dialog = QtHistoryDialog(store, shell,
                                     on_open=lambda _id: None,
                                     on_new=lambda _id: None)
            self.addCleanup(dialog.deleteLater)
            # The refusal shows a modal box; keep the test non-interactive.
            with patch("PySide6.QtWidgets.QMessageBox.information"):
                dialog._new()
            self.assertEqual(store.active_session_id, active_before)
            self.assertEqual(len(store.list_sessions()), sessions_before)

    def test_offline_answer_follows_the_same_contract(self):
        from src.qt_chat import QtChatWidget
        from src.history_store import HistoryStore
        from src.offline_assistant import OfflineAssistant
        from src.system_utils import SystemUtils
        history_path = Path(self.temp_dir.name) / "history.json"
        store = HistoryStore(str(history_path))
        self.addCleanup(store.close)
        system_utils = SystemUtils(self.config)
        offline = OfflineAssistant(system_utils, self.config)
        chat = QtChatWidget(self.config, offline, ai_client=Mock(), history_store=store)
        self.addCleanup(chat.close)
        session_a = store.active_session_id
        store.create_session(select=True)
        session_b = store.active_session_id
        chat.load_session(session_b)
        with patch("src.qt_chat.should_use_provider", return_value=False), \
                patch("src.qt_chat.offline_reply_text", return_value="offline answer"):
            chat._request_session_id = session_a
            chat._send_to_offline("question for A")
        self.app.processEvents()
        stored_a = [m for m in self._messages(store, session_a) if m["role"] == "assistant"]
        self.assertEqual(len(stored_a), 1)
        self.assertEqual(stored_a[0]["content"], "offline answer")
        stored_b = [m for m in self._messages(store, session_b) if m["role"] == "assistant"]
        self.assertEqual(stored_b, [])


if __name__ == "__main__":
    unittest.main()
