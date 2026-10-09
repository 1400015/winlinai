"""The Qt/Linux gate must prove capabilities rather than silently skip them."""

from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from scripts.qt_test_support import EXPECTED_SKIPS, qt_preflight, unexpected_skips
from scripts.run_qt_tests import discover_qt_suite, main


class TestQtCiRunner(unittest.TestCase):
    def test_discovery_includes_every_qt_module_only(self):
        loaded = []
        loader = SimpleNamespace(discover=lambda directory, pattern: loaded.append(pattern) or [])
        with tempfile.TemporaryDirectory() as directory:
            for name in ('test_qt_phase4a.py', 'test_qt_e2e.py', 'test_qt_ci_runner.py',
                         'test_windows_foundation_storage.py', 'test_trial_dialog.py'):
                (Path(directory) / name).touch()
            discover_qt_suite(directory, loader)
        self.assertEqual(loaded, ['test_qt_ci_runner.py', 'test_qt_e2e.py', 'test_qt_phase4a.py'])

    def test_only_exact_inverse_dependency_skips_are_accepted(self):
        for identifier, reason in EXPECTED_SKIPS.items():
            result = SimpleNamespace(skipped=[(SimpleNamespace(id=lambda: identifier), reason)])
            self.assertEqual(unexpected_skips(result), [])
            result.skipped[0] = (result.skipped[0][0], 'PySide6 unavailable')
            self.assertTrue(unexpected_skips(result))

    def test_real_runner_fails_without_bindings(self):
        # -S deliberately removes site-packages from this separate interpreter;
        # the runner must fail preflight before optional module fallbacks can skip.
        runner = Path(__file__).resolve().parents[1] / 'scripts' / 'run_qt_tests.py'
        result = subprocess.run([sys.executable, '-S', str(runner)],
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        if sys.platform.startswith('linux'):
            self.assertIn('Qt/Linux preflight failed', result.stderr)
            self.assertIn('PySide6', result.stderr)

    def test_preflight_rejects_frontend_that_silently_selected_fallback(self):
        application = Mock()
        bindings = SimpleNamespace(QtCore=SimpleNamespace(qVersion=lambda: 'test'),
                                   QtWidgets=SimpleNamespace(QApplication=SimpleNamespace(
                                       instance=lambda: application)), __version__='test')
        with patch.dict(sys.modules, {'PySide6': bindings}):
            with patch('scripts.qt_test_support.importlib.import_module',
                       return_value=SimpleNamespace(QT_AVAILABLE=False)):
                with self.assertRaisesRegex(RuntimeError, 'bindings failed to load'):
                    qt_preflight()
        application.processEvents.assert_not_called()

    def test_optional_frontends_still_import_with_bindings_unavailable(self):
        # Type-checking uses actual Qt bases; runtime core installations retain
        # the dependency-free fallback rather than failing during class creation.
        root = Path(__file__).resolve().parents[1]
        code = (
            "import importlib, sys; sys.modules['PySide6'] = None; "
            "names = ('qt_app', 'qt_chat', 'qt_dialogs', 'qt_tray', 'qt_conversation_actions'); "
            "modules = [importlib.import_module('src.' + name) for name in names]; "
            "assert all(not module.QT_AVAILABLE for module in modules)"
        )
        result = subprocess.run([sys.executable, '-c', code], cwd=str(root),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_failed_frontend_import_fails_job(self):
        with patch('scripts.run_qt_tests.sys.platform', 'linux'):
            with patch('scripts.run_qt_tests.qt_preflight', side_effect=ImportError('broken frontend')):
                with redirect_stderr(io.StringIO()) as output:
                    self.assertEqual(main(), 1)
        self.assertIn('broken frontend', output.getvalue())

    def test_non_linux_job_is_refused_before_bindings_or_discovery(self):
        with patch('scripts.run_qt_tests.sys.platform', 'win32'):
            with patch('scripts.run_qt_tests.qt_preflight') as preflight:
                with patch('scripts.run_qt_tests.discover_qt_suite') as discovery:
                    with redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(main(), 1)
        self.assertIn('requires Linux', output.getvalue())
        preflight.assert_not_called()
        discovery.assert_not_called()

    def test_successful_run_accepts_exact_inverse_skip_and_dispatches_events(self):
        identifier, reason = next(iter(EXPECTED_SKIPS.items()))

        class InverseBindingContract(unittest.TestCase):
            def id(self):
                return identifier

            def runTest(self):
                self.skipTest(reason)

        application = Mock()
        suite = unittest.TestSuite([InverseBindingContract()])
        with patch('scripts.run_qt_tests.sys.platform', 'linux'):
            with patch('scripts.run_qt_tests.qt_preflight', return_value=application):
                with patch('scripts.run_qt_tests.discover_qt_suite', return_value=suite):
                    with redirect_stderr(io.StringIO()):
                        self.assertEqual(main(), 0)
        application.processEvents.assert_called_once_with()

    def test_empty_discovery_cannot_pass(self):
        with patch('scripts.run_qt_tests.sys.platform', 'linux'):
            with patch('scripts.run_qt_tests.qt_preflight', return_value=Mock()):
                with patch('scripts.run_qt_tests.discover_qt_suite', return_value=unittest.TestSuite()):
                    with redirect_stderr(io.StringIO()):
                        self.assertEqual(main(), 1)

    def test_class_dependency_skip_fails_job_even_if_unittest_succeeds(self):
        @unittest.skip('PySide6 GUI class unavailable')
        class MissingGui(unittest.TestCase):
            def test_widget(self):
                raise AssertionError('the skipped test must not execute')

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(MissingGui)
        with patch('scripts.run_qt_tests.sys.platform', 'linux'):
            with patch('scripts.run_qt_tests.qt_preflight', return_value=Mock()):
                with patch('scripts.run_qt_tests.discover_qt_suite', return_value=suite):
                    with redirect_stderr(io.StringIO()) as output:
                        self.assertEqual(main(), 1)
        self.assertIn('Unexpected test skip', output.getvalue())


if __name__ == '__main__':
    unittest.main()
