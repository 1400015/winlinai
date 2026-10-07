"""End-to-end integration tests for the Qt track on Windows.

These tests exercise the full flow: shell creation → chat → offline response
→ history persistence → theme application → conversation actions.

They require PySide6 and run with QT_QPA_PLATFORM=offscreen on CI.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
        """Create a mock config manager."""
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.expert_mode": False,
            "app.tray_toggle_on_click": True,
            "ui.theme": "dark",
            "features.expert_mode": True,
        }.get(key, default))
        config.set = Mock()
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
        self.assertIn("User", log_text)
        self.assertIn("hello", log_text)
        # Should have an AI response (offline assistant)
        self.assertIn("AI", log_text)

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
        from src.platform.pwsh_output import (
            wrap_cmdlet_json,
            parse_json_output,
            normalize_output,
        )

        # Wrap a cmdlet
        argv = wrap_cmdlet_json(["Get-Service", "-Name", "wuauserv"])
        self.assertEqual(argv[0], "powershell")
        self.assertIn("Get-Service", argv[5])

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
        self.assertIn("User", log_text)
        self.assertIn("AI", log_text)


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
        self.assertIn("File written", log_text)

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
        self.assertIn("cancelled", chat.log.toPlainText())

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
        with patch("src.qt_app.threading.Thread") as thread_cls:
            _maybe_check_updates(config, shell=None)
        thread_cls.assert_not_called()
        config.set.assert_not_called()

    def test_maybe_check_updates_stores_available_update(self):
        from src.qt_app import _maybe_check_updates

        class SyncThread:
            """Runs the target synchronously so the test is deterministic."""
            def __init__(self, target=None, daemon=None, name=None):
                self._target = target
            def start(self):
                if self._target:
                    self._target()

        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": True,
        }.get(key, default))
        config.set = Mock()
        fake_update = {"version": "9.9.9", "url": "https://github.com/1400015/winlinai/releases"}
        with patch("src.qt_app.threading.Thread", SyncThread):
            with patch("src.updater.check_for_updates", return_value=fake_update):
                _maybe_check_updates(config, shell=None)
        config.set.assert_any_call("update.available", True)
        config.set.assert_any_call("update.version", "9.9.9")

    def test_maybe_check_updates_quiet_when_none(self):
        from src.qt_app import _maybe_check_updates

        class SyncThread:
            def __init__(self, target=None, daemon=None, name=None):
                self._target = target
            def start(self):
                if self._target:
                    self._target()

        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: {
            "app.check_updates": True,
        }.get(key, default))
        config.set = Mock()
        with patch("src.qt_app.threading.Thread", SyncThread):
            with patch("src.updater.check_for_updates", return_value=None):
                _maybe_check_updates(config, shell=None)
        config.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
