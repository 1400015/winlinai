"""Run native Windows foundation and Qt tests, rejecting unexpected skips."""

import os
from pathlib import Path
import sys
import unittest


# These inverse tests deliberately exercise absent Qt bindings. Qt is required
# by this job, so only these exact test/reason pairs may be skipped.
EXPECTED_SKIPS = {
    'test_qt_phase4a.TestQtRunWithoutDependency.test_run_reports_missing_dependency_and_returns_nonzero':
        'PySide6 installed in this environment',
    'test_qt_phase4b.TestQtChatModuleContract.test_widget_raises_without_pyside6':
        'PySide6 installed in this environment',
    'test_qt_phase4d.TestQtDialogsContract.test_dialogs_raise_without_pyside6':
        'PySide6 installed in this environment',
}


def unexpected_skips(result):
    return [(test.id(), reason) for test, reason in result.skipped
            if EXPECTED_SKIPS.get(test.id()) != reason]


def discover_windows_suite(test_directory, loader=None):
    """Do not import tests for Linux-only facilities into the native job."""
    loader = loader or unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in sorted(Path(test_directory).glob('test_*.py')):
        if path.name.startswith((
                'test_windows_foundation', 'test_windows_file_actions',
                'test_windows_screenshot', 'test_windows_system_actions',
                'test_windows_phase', 'test_pwsh_output', 'test_qt_')):
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
        from PySide6 import QtWidgets
        # Keep the application alive for all widget tests in the same process.
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from src import qt_app, qt_chat, qt_dialogs, qt_tray
        if not all((qt_app.available(), qt_chat.QT_AVAILABLE,
                    qt_dialogs.QT_AVAILABLE, qt_tray.QT_AVAILABLE)):
            raise RuntimeError('A Qt frontend module failed to load its bindings')
        application.processEvents()
    except (ImportError, RuntimeError) as error:
        print('Windows/Qt preflight failed: ' + str(error), file=sys.stderr)
        return 1
    test_directory = root / 'tests'
    if not any(test_directory.glob('test_windows_foundation*.py')):
        print('Windows foundation tests are missing.', file=sys.stderr)
        return 1
    suite = discover_windows_suite(test_directory)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    skipped = unexpected_skips(result)
    for identifier, reason in skipped:
        print('Unexpected test skip: {}: {}'.format(identifier, reason), file=sys.stderr)
    return 0 if result.wasSuccessful() and suite.countTestCases() and not skipped else 1


if __name__ == '__main__':
    sys.exit(main())
