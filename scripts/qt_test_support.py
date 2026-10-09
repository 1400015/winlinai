"""Shared preflight and exact skip contract for the real Qt CI jobs."""

import importlib
import platform


# The Qt jobs install bindings; only the inverse missing-binding contracts
# cannot execute there. An import failure or a GUI class skip is a failure.
EXPECTED_SKIPS = {
    'test_qt_phase4a.TestQtRunWithoutDependency.test_run_reports_missing_dependency_and_returns_nonzero':
        'PySide6 installed in this environment',
    'test_qt_phase4b.TestQtChatModuleContract.test_widget_raises_without_pyside6':
        'PySide6 installed in this environment',
    'test_qt_phase4d.TestQtDialogsContract.test_dialogs_raise_without_pyside6':
        'PySide6 installed in this environment',
}

QT_MODULES = (
    'qt_app', 'qt_chat', 'qt_dialogs', 'qt_tray', 'qt_worker',
    'qt_conversation_actions', 'qt_file_dialogs',
)


def unexpected_skips(result):
    return [(test.id(), reason) for test, reason in result.skipped
            if EXPECTED_SKIPS.get(test.id()) != reason]


def qt_preflight():
    """Require installed bindings and working frontend imports/event dispatch.

    Return the application so the caller retains it for all widget tests.
    Importing the optional modules alone could silently select their fallbacks.
    """
    from PySide6 import QtCore, QtWidgets, __version__
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for module_name in QT_MODULES:
        module = importlib.import_module('src.' + module_name)
        if not module.QT_AVAILABLE:
            raise RuntimeError('Qt frontend bindings failed to load: ' + module_name)
    application.processEvents()
    print('Qt preflight: Python {}; PySide6 {}; Qt {}; platform {}'.format(
        platform.python_version(), __version__, QtCore.qVersion(), platform.system()))
    return application
