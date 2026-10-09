"""Run native Windows foundation and Qt tests, rejecting unexpected skips."""

import os
from pathlib import Path
import sys
import unittest


if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.qt_test_support import EXPECTED_SKIPS, qt_preflight, unexpected_skips  # noqa: F401


def discover_windows_suite(test_directory, loader=None):
    """Do not import tests for Linux-only facilities into the native job."""
    loader = loader or unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in sorted(Path(test_directory).glob('test_*.py')):
        if path.name == 'test_updater.py' or path.name.startswith((
                'test_windows_foundation', 'test_windows_file_actions',
                'test_windows_screenshot', 'test_windows_system_actions',
                'test_pwsh_output', 'test_qt_', 'test_readme_')):
            suite.addTests(loader.discover(str(test_directory), pattern=path.name))
    return suite


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if os.name != 'nt':
        print('Windows preflight failed: this job requires native Windows, not WSL.', file=sys.stderr)
        return 1
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        application = qt_preflight()
    except (ImportError, RuntimeError) as error:
        print('Windows/Qt preflight failed: ' + str(error), file=sys.stderr)
        return 1
    test_directory = root / 'tests'
    if not any(test_directory.glob('test_windows_foundation*.py')):
        print('Windows foundation tests are missing.', file=sys.stderr)
        return 1
    suite = discover_windows_suite(test_directory)
    count = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    application.processEvents()
    skipped = unexpected_skips(result)
    for identifier, reason in skipped:
        print('Unexpected test skip: {}: {}'.format(identifier, reason), file=sys.stderr)
    return 0 if result.wasSuccessful() and count and not skipped else 1


if __name__ == '__main__':
    sys.exit(main())
