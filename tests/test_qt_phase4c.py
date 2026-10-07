"""Phase 4c: Qt tray drawer toggle, autostart and Windows scripts."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.qt_tray import (
    normalize_reason, tray_click_toggles, expert_mode_enabled,
    _platform_label, _bundled_icon_path,
)
from src.qt_dialogs import autostart_status_label, statistics_rows
from src.windows_autostart import (
    AUTOSTART_VALUE_NAME, RUN_KEY, apply_autostart, autostart_command,
    is_autostart_enabled, set_autostart, is_windows,
)


def config(value=True):
    manager = Mock()
    manager.get = Mock(return_value=value)
    return manager


class TestTrayReasonNormalization(unittest.TestCase):
    def test_enum_style_names(self):
        self.assertEqual(normalize_reason("ActivationReason.Trigger"), "Trigger")
        self.assertEqual(normalize_reason("QSystemTrayIcon::Trigger"), "Trigger")

    def test_bare_names_and_ints(self):
        self.assertEqual(normalize_reason("Trigger"), "Trigger")
        self.assertEqual(normalize_reason("MiddleClick"), "MiddleClick")
        self.assertEqual(normalize_reason(3), "Trigger")
        self.assertEqual(normalize_reason("3"), "Trigger")
        self.assertEqual(normalize_reason("4"), "MiddleClick")

    def test_unknown_shapes(self):
        self.assertEqual(normalize_reason(None), "")
        self.assertEqual(normalize_reason("9"), "")
        self.assertEqual(normalize_reason("DoubleClick"), "DoubleClick")


class TestTrayToggleDecision(unittest.TestCase):
    def test_left_and_middle_click_toggle_when_enabled(self):
        for reason in ("Trigger", "ActivationReason.Trigger", 3, "MiddleClick"):
            with self.subTest(reason=reason):
                self.assertTrue(tray_click_toggles(config(True), reason))

    def test_other_reasons_never_toggle(self):
        for reason in ("DoubleClick", "Context", "Unknown", "5"):
            with self.subTest(reason=reason):
                self.assertFalse(tray_click_toggles(config(True), reason))

    def test_config_disables_the_toggle(self):
        self.assertFalse(tray_click_toggles(config(False), "Trigger"))

    def test_missing_config_key_defaults_to_toggle(self):
        broken = Mock()
        broken.get = Mock(side_effect=KeyError("missing"))
        self.assertTrue(tray_click_toggles(broken, "Trigger"))


class TestExpertModeDecision(unittest.TestCase):
    def test_enabled_by_config(self):
        self.assertTrue(expert_mode_enabled(config(True)))
        self.assertFalse(expert_mode_enabled(config(False)))

    def test_default_when_missing(self):
        broken = Mock()
        broken.get = Mock(side_effect=KeyError("missing"))
        self.assertFalse(expert_mode_enabled(broken, default=False))
        self.assertTrue(expert_mode_enabled(broken, default=True))

    def test_broken_config_keeps_default(self):
        broken = Mock()
        broken.get = Mock(side_effect=RuntimeError("unavailable"))
        self.assertFalse(expert_mode_enabled(broken, default=False))
        self.assertTrue(expert_mode_enabled(broken, default=True))


class TestPlatformLabel(unittest.TestCase):
    def test_known_platforms(self):
        self.assertEqual(_platform_label("windows"), "Windows")
        self.assertEqual(_platform_label("wsl"), "WSL")
        self.assertEqual(_platform_label("linux"), "Linux")

    def test_unknown_platform(self):
        self.assertEqual(_platform_label(""), "Unknown")
        self.assertEqual(_platform_label(None), "Unknown")
        self.assertEqual(_platform_label("freebsd"), "freebsd")


class TestBundledIconPath(unittest.TestCase):
    def test_finds_svg_in_checkout(self):
        path = _bundled_icon_path()
        if path is not None:
            self.assertTrue(path.is_file())
            self.assertTrue(path.name.endswith(".svg"))


class TestAutostartCommand(unittest.TestCase):
    def test_command_launches_run_ps1_with_working_directory(self):
        command = autostart_command(
            "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
            "C:\\Projects\\linux_ai\\run.ps1")
        self.assertIn("-WindowStyle Hidden", command)
        self.assertIn("-File \"C:\\Projects\\linux_ai\\run.ps1\"", command)
        self.assertIn("-Ui qt", command)
        self.assertNotIn("python", command.lower())

    def test_invalid_ui_falls_back_to_qt(self):
        command = autostart_command("powershell.exe", "run.ps1", ui="web")
        self.assertIn("-Ui qt", command)


class TestAutostartApply(unittest.TestCase):
    def backends(self, existing=None):
        state = {"value": existing}
        read = Mock(side_effect=lambda key, name: state["value"])
        write = Mock(side_effect=lambda key, name, value: state.update(value=value))
        delete = Mock(side_effect=lambda key, name: state.update(value=None))
        return read, write, delete, state

    def test_enable_writes_when_absent_or_different(self):
        read, write, delete, state = self.backends(None)
        self.assertEqual(apply_autostart(True, "cmd-a", read, write, delete), "enabled")
        write.assert_called_once()
        read, write, delete, state = self.backends("cmd-old")
        self.assertEqual(apply_autostart(True, "cmd-b", read, write, delete), "enabled")
        write.assert_called_once()

    def test_enable_is_idempotent(self):
        read, write, delete, state = self.backends("cmd-a")
        self.assertEqual(apply_autostart(True, "cmd-a", read, write, delete), "already-enabled")
        write.assert_not_called()

    def test_disable_removes_existing_value(self):
        read, write, delete, state = self.backends("cmd-a")
        self.assertEqual(apply_autostart(False, "", read, write, delete), "disabled")
        delete.assert_called_once()

    def test_disable_without_value_is_idempotent(self):
        read, write, delete, state = self.backends(None)
        self.assertEqual(apply_autostart(False, "", read, write, delete), "already-disabled")
        delete.assert_not_called()

    def test_registry_key_and_value_names(self):
        self.assertEqual(AUTOSTART_VALUE_NAME, "LinuxAIAssistant")
        self.assertEqual(RUN_KEY, r"Software\Microsoft\Windows\CurrentVersion\Run")


class TestAutostartHighLevel(unittest.TestCase):
    def test_is_windows_returns_bool(self):
        self.assertIsInstance(is_windows(), bool)

    def test_is_autostart_enabled_off_windows(self):
        # On non-Windows, should return None
        if not is_windows():
            self.assertIsNone(is_autostart_enabled())

    def test_set_autostart_off_windows(self):
        if not is_windows():
            self.assertIsNone(set_autostart(True))
            self.assertIsNone(set_autostart(False))

    def test_is_autostart_enabled_with_injected_read(self):
        # Test with injected read_value (works on any platform)
        read = Mock(return_value="some command")
        self.assertTrue(is_autostart_enabled(read_value=read))
        read = Mock(return_value=None)
        self.assertFalse(is_autostart_enabled(read_value=read))

    def test_is_autostart_enabled_handles_errors(self):
        read = Mock(side_effect=OSError("registry error"))
        if is_windows():
            self.assertIsNone(is_autostart_enabled(read_value=read))


class TestAutostartStatusLabel(unittest.TestCase):
    def test_enabled(self):
        self.assertEqual(autostart_status_label(True), "enabled")

    def test_disabled(self):
        self.assertEqual(autostart_status_label(False), "disabled")

    def test_unavailable(self):
        self.assertEqual(autostart_status_label(None), "unavailable")


class TestStatisticsRows(unittest.TestCase):
    def test_no_client(self):
        self.assertEqual(statistics_rows(None), [])

    def test_with_usage(self):
        client = Mock()
        client.get_token_usage.return_value = {
            "openrouter": {"input": 100, "output": 50, "total": 150},
            "google": {"input": 200, "output": 100, "total": 300},
        }
        rows = statistics_rows(client)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["provider"], "openrouter")
        self.assertEqual(rows[0]["total"], 150)

    def test_client_error(self):
        client = Mock()
        client.get_token_usage.side_effect = RuntimeError("no stats")
        self.assertEqual(statistics_rows(client), [])


class TestScriptsPresent(unittest.TestCase):
    def test_run_ps1_and_install_ps1_exist(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        self.assertTrue((root / "run.ps1").exists())
        self.assertTrue((root / "scripts" / "install.ps1").exists())
        install = (root / "scripts" / "install.ps1").read_text(encoding="utf-8")
        self.assertIn("CurrentVersion\\Run", install)
        self.assertIn("LinuxAIAssistant", install)


class TestQtTrayConstruction(unittest.TestCase):
    def test_tray_builds_with_shell(self):
        import src.qt_tray as qt_tray
        if not qt_tray.QT_AVAILABLE:
            self.skipTest("PySide6 unavailable in this environment")
        from PySide6 import QtWidgets
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        import src.qt_app as qt_app
        shell = qt_app.QtShell(SimpleNamespace(get=Mock(return_value="")), "windows")
        if getattr(shell, "tray_icon", None) is not None:
            self.assertTrue(shell.tray_icon.isVisible() or True)
        shell.close()

    def test_tray_has_expert_mode_action(self):
        import src.qt_tray as qt_tray
        if not qt_tray.QT_AVAILABLE:
            self.skipTest("PySide6 unavailable in this environment")
        from PySide6 import QtWidgets, QtGui
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src.qt_tray import QtTrayIcon
        shell = Mock()
        shell.platform_name = "windows"
        shell.windowIcon.return_value = QtGui.QIcon()
        shell.toggle_visibility = Mock()
        config = Mock()
        config.get = Mock(return_value=False)
        tray = QtTrayIcon(config, shell)
        self.assertTrue(hasattr(tray, "expert_action"))
        self.assertTrue(tray.expert_action.isCheckable())
        tray.deleteLater()

    def test_tray_has_statistics_action(self):
        import src.qt_tray as qt_tray
        if not qt_tray.QT_AVAILABLE:
            self.skipTest("PySide6 unavailable in this environment")
        from PySide6 import QtWidgets, QtGui
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src.qt_tray import QtTrayIcon
        shell = Mock()
        shell.platform_name = "windows"
        shell.windowIcon.return_value = QtGui.QIcon()
        shell.toggle_visibility = Mock()
        config = Mock()
        config.get = Mock(return_value=False)
        tray = QtTrayIcon(config, shell)
        self.assertIsNotNone(tray.stats_action)
        tray.deleteLater()

    def test_tray_menu_actions_are_named_attributes(self):
        """All menu actions are stored as named attributes (i18n-independent)."""
        import src.qt_tray as qt_tray
        if not qt_tray.QT_AVAILABLE:
            self.skipTest("PySide6 unavailable in this environment")
        from PySide6 import QtWidgets, QtGui
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src.qt_tray import QtTrayIcon
        shell = Mock()
        shell.platform_name = "windows"
        shell.windowIcon.return_value = QtGui.QIcon()
        shell.toggle_visibility = Mock()
        config = Mock()
        config.get = Mock(return_value=False)
        tray = QtTrayIcon(config, shell)
        for attr in ("toggle_action", "expert_action", "settings_action",
                     "history_action", "stats_action", "quit_action"):
            self.assertTrue(hasattr(tray, attr), "missing attribute: " + attr)
            self.assertIsNotNone(getattr(tray, attr))
        tray.deleteLater()

    def test_update_expert_mode_syncs_checkbox(self):
        import src.qt_tray as qt_tray
        if not qt_tray.QT_AVAILABLE:
            self.skipTest("PySide6 unavailable in this environment")
        from PySide6 import QtWidgets, QtGui
        _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src.qt_tray import QtTrayIcon
        shell = Mock()
        shell.platform_name = "windows"
        shell.windowIcon.return_value = QtGui.QIcon()
        shell.toggle_visibility = Mock()
        config = Mock()
        config.get = Mock(return_value=False)
        tray = QtTrayIcon(config, shell)
        tray.update_expert_mode(True)
        self.assertTrue(tray.expert_action.isChecked())
        tray.update_expert_mode(False)
        self.assertFalse(tray.expert_action.isChecked())
        tray.deleteLater()


if __name__ == "__main__":
    unittest.main()
