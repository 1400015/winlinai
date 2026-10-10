"""Settings must be reachable from the main window, tray or no tray.

The tray menu was the only route to the Settings dialog (and its API
keys): when the system tray is unavailable there was no way to reach
the provider configuration at all. The main window now carries a
Settings button that opens the same dialog.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.qt_chat import QT_AVAILABLE

if QT_AVAILABLE:
    from PySide6 import QtWidgets


@unittest.skipUnless(QT_AVAILABLE, "PySide6 required for settings button tests")
class TestQtSettingsButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def _shell(self):
        from src.qt_app import QtShell
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Mock()
        config.get = Mock(side_effect=lambda key, default=None: default)
        config.get_api_key = Mock(return_value=None)
        shell = QtShell(config, "windows",
                        history_path=str(Path(directory.name) / "history.json"))
        self.addCleanup(self._destroy, shell)
        return shell

    def _destroy(self, shell):
        shell.close()
        shell.deleteLater()
        self.app.processEvents()

    def test_main_window_has_a_settings_button(self):
        shell = self._shell()
        self.assertTrue(hasattr(shell, "settings_button"))
        self.assertEqual(shell.settings_button.text(), "Settings")

    def test_settings_button_opens_the_settings_dialog(self):
        shell = self._shell()
        with patch("src.qt_dialogs.QtSettingsDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            shell.settings_button.click()
            self.app.processEvents()
        dialog.assert_called_once()
        self.assertIn(shell.config, dialog.call_args.args)


if __name__ == "__main__":
    unittest.main()
