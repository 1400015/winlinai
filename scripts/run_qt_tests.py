"""Run Qt/Linux with real bindings, rejecting unavailable GUI tests."""

import os
from pathlib import Path
import sys
import unittest

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.qt_test_support import qt_preflight, unexpected_skips


def discover_qt_suite(test_directory, loader=None):
    """Exercise the portable Qt track without importing GTK/native Windows."""
    loader = loader or unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in sorted(Path(test_directory).glob('test_qt_*.py')):
        suite.addTests(loader.discover(str(test_directory), pattern=path.name))
    return suite


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    if not sys.platform.startswith('linux'):
        print('Qt/Linux preflight failed: this job requires Linux.', file=sys.stderr)
        return 1
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        application = qt_preflight()
    except (ImportError, RuntimeError) as error:
        print('Qt/Linux preflight failed: ' + str(error), file=sys.stderr)
        return 1
    suite = discover_qt_suite(root / 'tests')
    count = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    # Explicitly dispatch queued events while the same QApplication remains alive.
    application.processEvents()
    skipped = unexpected_skips(result)
    for identifier, reason in skipped:
        print('Unexpected test skip: {}: {}'.format(identifier, reason), file=sys.stderr)
    return 0 if count and result.wasSuccessful() and not skipped else 1


if __name__ == '__main__':
    sys.exit(main())
