"""A dependency/import skip must fail the GTK job, including class skips."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.run_gtk_tests import EXPECTED_SKIPS, discover_gtk_suite, unexpected_skips


class TestGtkCiSkips(unittest.TestCase):
    @staticmethod
    def result(identifier, reason):
        test = SimpleNamespace(id=lambda: identifier)
        return SimpleNamespace(skipped=[(test, reason)])

    def test_gui_class_dependency_skip_is_rejected(self):
        result = self.result('test_trial_dialog.TestTrialDialog',
                             "GTK unavailable: No module named 'yaml'")
        self.assertEqual(len(unexpected_skips(result)), 1)

    def test_only_the_expected_inverse_tests_are_allowed(self):
        for identifier in EXPECTED_SKIPS:
            self.assertEqual(unexpected_skips(self.result(
                identifier, 'GTK is available in this environment')), [])
            self.assertEqual(len(unexpected_skips(self.result(
                identifier, "No module named 'gi'"))), 1)

    def test_gtk_discovery_keeps_native_and_qt_tests_in_their_jobs(self):
        loaded = []
        loader = SimpleNamespace(discover=lambda directory, pattern: loaded.append(pattern) or [])
        with tempfile.TemporaryDirectory() as directory:
            for name in ('test_trial_dialog.py', 'test_qt_phase4a.py',
                         'test_windows_foundation_storage.py', 'test_windows_phase1.py'):
                (Path(directory) / name).touch()
            discover_gtk_suite(directory, loader)
        self.assertEqual(loaded, ['test_trial_dialog.py', 'test_windows_phase1.py'])


if __name__ == '__main__':
    unittest.main()
