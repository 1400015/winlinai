"""Run the Linux/GTK suite; unavailable GTK classes must not make CI green."""

from pathlib import Path
import sys
import unittest


# These tests intentionally exercise installations without GTK, so the GTK job
# cannot execute them. All other environment/import skips are errors here.
EXPECTED_SKIPS = {
    'test_regressions.TestGracefulGtkFailure.test_app_reports_missing_gtk_clearly',
    'test_regressions.TestGracefulGtkFailure.test_main_window_is_not_imported_without_gtk',
}


def unexpected_skips(result):
    return [(test.id(), reason) for test, reason in result.skipped
            if test.id() not in EXPECTED_SKIPS or reason != 'GTK is available in this environment']


def discover_gtk_suite(test_directory, loader=None):
    """Keep Qt and the native Windows foundation in their dedicated jobs.

    The headless Linux job still discovers every module, including optional
    dependency contracts. Avoid importing native Windows test modules in the
    GTK gate: their platform skips are deliberate, not missing GTK coverage.
    """
    loader = loader or unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for path in sorted(Path(test_directory).glob('test_*.py')):
        if path.name.startswith(('test_qt_', 'test_windows_foundation')):
            continue
        suite.addTests(loader.discover(str(test_directory), pattern=path.name))
    return suite


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk
        if not Gtk.init_check()[0]:
            raise RuntimeError('GTK cannot open the test display')
        # Import failures must fail preflight instead of becoming class skips.
        from src import main_window, trial_dialog, device_dialogs, dock  # noqa: F401
    except (ImportError, ValueError, RuntimeError) as error:
        print('GTK preflight failed: ' + str(error), file=sys.stderr)
        return 1
    suite = discover_gtk_suite(root / 'tests')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    skipped = unexpected_skips(result)
    for identifier, reason in skipped:
        print('Unexpected test skip: {}: {}'.format(identifier, reason), file=sys.stderr)
    return 0 if result.wasSuccessful() and not skipped else 1


if __name__ == '__main__':
    sys.exit(main())
