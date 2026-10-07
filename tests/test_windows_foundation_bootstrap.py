"""Exercise the real entry point and required Qt backend startup."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class TestPlatformBootstrap(unittest.TestCase):
    def _main_without_gtk(self, ui, platform="windows"):
        script = textwrap.dedent("""
            import importlib.abc
            import sys
            from unittest.mock import patch

            class NoGtk(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'gi' or fullname.startswith('gi.'):
                        raise ImportError('GTK deliberately unavailable')
                    if fullname in ('src.main_window', 'src.tray_icon'):
                        raise AssertionError('GTK window imported by the Qt entry point')

            sys.meta_path.insert(0, NoGtk())
            import src.app as app
            assert not app.GTK_AVAILABLE
            with patch('src.setup_file_logging'), \
                    patch('src.platform.detect_platform', return_value=PLATFORM), \
                    patch('src.qt_app.run', return_value=7) as run_qt:
                assert app.main(['--ui', UI]) == 7
                run_qt.assert_called_once_with()
            assert 'src.main_window' not in sys.modules
            assert 'src.tray_icon' not in sys.modules
        """).replace("PLATFORM", repr(platform)).replace("UI", repr(ui))
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_qt_reaches_runner_without_gtk(self):
        self._main_without_gtk("qt", platform="linux")

    def test_windows_auto_reaches_qt_runner_without_gtk(self):
        self._main_without_gtk("auto")

    def test_explicit_gtk_reports_the_missing_selected_dependency(self):
        script = textwrap.dedent("""
            import importlib.abc
            import sys
            from unittest.mock import patch
            class NoGtk(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    if fullname == 'gi' or fullname.startswith('gi.'):
                        raise ImportError('GTK deliberately unavailable')
            sys.meta_path.insert(0, NoGtk())
            from src.app import main
            with patch('src.setup_file_logging'), patch('src.qt_app.run') as run_qt:
                assert main(['--ui', 'gtk']) == 1
                run_qt.assert_not_called()
        """)
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("GTK 3 is not available", result.stderr)

    def test_qt_configuration_failure_returns_a_clear_error(self):
        from src import qt_app
        output = io.StringIO()
        with patch.object(qt_app, "QT_AVAILABLE", True), \
                patch("src.config_manager.ConfigManager", side_effect=PermissionError("private detail")), \
                redirect_stderr(output):
            self.assertEqual(qt_app.run(), 1)
        self.assertIn("Configuration could not be loaded", output.getvalue())
        self.assertNotIn("private detail", output.getvalue())

    def test_qt_missing_binding_does_not_initialize_configuration(self):
        from src import qt_app
        output = io.StringIO()
        with patch.object(qt_app, "QT_AVAILABLE", False), \
                patch("src.config_manager.ConfigManager") as config, redirect_stderr(output):
            self.assertEqual(qt_app.run(), 1)
        config.assert_not_called()
        self.assertIn("PySide6", output.getvalue())


class TestQtRequiredBackends(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src import qt_app
        if not qt_app.available():
            raise unittest.SkipTest("PySide6 unavailable")
        cls.qt_app = qt_app
        cls.application = qt_app.QtWidgets.QApplication.instance() or qt_app.QtWidgets.QApplication([])

    def setUp(self):
        self.config = SimpleNamespace(get=lambda key, default=None: default, flush=Mock())

    def test_system_utils_failure_aborts_shell_construction(self):
        with patch("src.system_utils.SystemUtils", side_effect=AttributeError("missing API")):
            with self.assertRaisesRegex(self.qt_app.QtStartupError, "System utilities"):
                self.qt_app.QtShell(self.config, "windows")

    def test_history_constructor_failure_aborts_shell_construction(self):
        with patch("src.history_store.HistoryStore", side_effect=PermissionError("unreadable")):
            with self.assertRaisesRegex(self.qt_app.QtStartupError, "Conversation history"):
                self.qt_app.QtShell(self.config, "windows")

    def test_history_validation_failure_closes_the_started_writer(self):
        store = Mock()
        store.list_sessions.side_effect = ValueError("unsupported format")
        with patch("src.history_store.HistoryStore", return_value=store):
            with self.assertRaisesRegex(self.qt_app.QtStartupError, "Conversation history"):
                self.qt_app.QtShell(self.config, "windows")
        store.close.assert_called_once_with()

    def test_shell_can_use_an_explicit_history_path(self):
        from src.history_store import HistoryStore
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            with patch("src.history_store.HistoryStore", wraps=HistoryStore) as create_store:
                shell = self.qt_app.QtShell(self.config, "windows", history_path=path)
            try:
                create_store.assert_called_once_with(path)
                self.assertEqual(shell.history_store.path, path)
                self.assertTrue(path.is_file())
            finally:
                shell.close()

    def test_run_sets_language_before_creating_the_shell_and_releases_resources(self):
        from src import i18n
        previous_language = i18n._current_lang
        self.addCleanup(setattr, i18n, "_current_lang", previous_language)
        self.config.get = lambda key, default=None: "pt" if key == "app.language" else default
        shell = Mock()
        observed_languages = []

        def create_shell(*args):
            observed_languages.append(i18n._current_lang)
            return shell

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(self.qt_app, "lock_file_path", return_value=str(Path(directory) / "instance.lock")), \
                patch.object(self.qt_app, "QtShell", side_effect=create_shell), \
                patch.object(self.qt_app.QtWidgets.QApplication, "exec", return_value=0):
            self.assertEqual(self.qt_app.run(self.config, argv=["test"]), 0)
            self.assertFalse((Path(directory) / "instance.lock").exists())
        self.assertEqual(observed_languages, ["pt"])
        shell.show.assert_called_once_with()
        shell._close_history.assert_called_once_with()
        self.config.flush.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
