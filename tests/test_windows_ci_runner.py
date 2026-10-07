"""The native CI gate must reject missing dependencies and platform skips."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.run_windows_tests import EXPECTED_SKIPS, discover_windows_suite, unexpected_skips


class TestWindowsCi(unittest.TestCase):
    @staticmethod
    def result(identifier, reason):
        return SimpleNamespace(skipped=[(SimpleNamespace(id=lambda: identifier), reason)])

    def test_native_platform_and_dependency_skips_are_rejected(self):
        for identifier, reason in (
            ('test_windows_foundation_storage.TestNativeStorage', 'Windows only'),
            ('test_qt_phase4b.TestQtChatBehaviour', 'PySide6 unavailable in this environment'),
        ):
            self.assertEqual(unexpected_skips(self.result(identifier, reason)), [(identifier, reason)])

    def test_only_exact_inverse_contract_skips_are_allowed(self):
        for identifier, reason in EXPECTED_SKIPS.items():
            self.assertEqual(unexpected_skips(self.result(identifier, reason)), [])
            self.assertEqual(len(unexpected_skips(self.result(identifier, 'PySide6 unavailable'))), 1)

    def test_discovery_includes_native_windows_and_qt_tests(self):
        loaded = []
        loader = SimpleNamespace(discover=lambda directory, pattern: loaded.append(pattern) or [])
        with tempfile.TemporaryDirectory() as directory:
            for name in ('test_windows_foundation_storage.py', 'test_windows_foundation_bootstrap.py',
                         'test_windows_file_actions.py', 'test_windows_screenshot.py',
                         'test_windows_system_actions.py', 'test_windows_phase1.py',
                         'test_pwsh_output.py', 'test_qt_phase4a.py',
                         'test_device_dialogs.py'):
                (Path(directory) / name).touch()
            suite = discover_windows_suite(directory, loader)
        self.assertEqual(loaded, ['test_pwsh_output.py', 'test_qt_phase4a.py',
                                  'test_windows_file_actions.py',
                                  'test_windows_foundation_bootstrap.py',
                                  'test_windows_foundation_storage.py',
                                  'test_windows_screenshot.py',
                                  'test_windows_system_actions.py'])
        self.assertEqual(suite.countTestCases(), 0)


if __name__ == '__main__':
    unittest.main()
