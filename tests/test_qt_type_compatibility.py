"""Preserve real Qt APIs and optional imports while tightening the type gate."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class TestOptionalQtImports(unittest.TestCase):
    def test_frontends_import_and_refuse_construction_without_bindings(self):
        # Blocking only PySide6 exercises the runtime fallback even when
        # the parent test process has real bindings installed.
        script = """
import importlib
import sys
sys.modules['PySide6'] = None
names = ('qt_app', 'qt_chat', 'qt_dialogs', 'qt_tray', 'qt_conversation_actions')
modules = {name: importlib.import_module('src.' + name) for name in names}
assert all(not module.QT_AVAILABLE for module in modules.values())
constructors = (
    lambda: modules['qt_app'].QtShell(None, 'linux'),
    lambda: modules['qt_chat'].QtChatWidget(None, None),
    lambda: modules['qt_dialogs'].QtSettingsDialog(None),
    lambda: modules['qt_dialogs'].QtHistoryDialog(None),
    lambda: modules['qt_dialogs'].QtStatisticsDialog(None),
    lambda: modules['qt_tray'].QtTrayIcon(None, None),
)
for construct in constructors:
    try:
        construct()
    except RuntimeError as error:
        assert 'PySide6' in str(error)
    else:
        raise AssertionError('A frontend constructor accepted absent Qt bindings')
"""
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-c', script], cwd=str(root),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(QT_AVAILABLE, 'PySide6 unavailable in this environment')
class TestQtApiCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_tray_preserves_callable_qt_icon_method(self):
        from src.qt_tray import QtTrayIcon

        shell = Mock()
        shell.platform_name = 'windows'
        shell.windowIcon.return_value = QtGui.QIcon()
        config = Mock()
        config.get.return_value = False
        tray = QtTrayIcon(config, shell)
        self.addCleanup(tray.deleteLater)
        self.assertIsInstance(tray.icon(), QtGui.QIcon)
        replacement = QtGui.QIcon(QtGui.QPixmap(2, 2))
        tray.setIcon(replacement)
        self.assertEqual(tray.icon().cacheKey(), replacement.cacheKey())

    def test_drag_and_drop_events_still_attach_only_images(self):
        from src.qt_chat import QtChatWidget

        config = Mock()
        config.get.return_value = False
        chat = QtChatWidget(config, Mock())
        self.addCleanup(chat.close)
        with tempfile.TemporaryDirectory() as directory:
            image_path = str(Path(directory) / 'accepted.PNG')
            text_path = str(Path(directory) / 'rejected.txt')
            image = QtGui.QImage(2, 2, QtGui.QImage.Format.Format_ARGB32)
            image.fill(QtGui.QColor('red'))
            self.assertTrue(image.save(image_path))
            mime = QtCore.QMimeData()
            mime.setUrls([QtCore.QUrl.fromLocalFile(image_path), QtCore.QUrl.fromLocalFile(text_path)])
            enter = QtGui.QDragEnterEvent(QtCore.QPoint(1, 1), QtCore.Qt.DropAction.CopyAction,
                                         mime, QtCore.Qt.MouseButton.LeftButton,
                                         QtCore.Qt.KeyboardModifier.NoModifier)
            drop = QtGui.QDropEvent(QtCore.QPointF(1, 1), QtCore.Qt.DropAction.CopyAction,
                                   mime, QtCore.Qt.MouseButton.LeftButton,
                                   QtCore.Qt.KeyboardModifier.NoModifier)
            with patch('src.qt_chat.should_use_provider', return_value=True):
                self.application.sendEvent(chat.log.viewport(), enter)
                self.assertTrue(enter.isAccepted())
                self.application.sendEvent(chat.log.viewport(), drop)
                self.assertTrue(drop.isAccepted())
            self.assertEqual([item['path'] for item in chat._attachments], [image_path])
            preview = chat._attachments[0]['widget']
            pixmaps = (label.pixmap() for label in preview.findChildren(QtWidgets.QLabel))
            self.assertTrue(any(pixmap is not None and not pixmap.isNull() for pixmap in pixmaps))


if __name__ == '__main__':
    unittest.main()
