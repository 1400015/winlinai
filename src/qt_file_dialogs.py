"""Qt dialog for file write confirmation on Windows.

Shows a diff/preview of the proposed file changes and asks for confirmation.
"""
from __future__ import annotations

import logging
from xml.sax.saxutils import escape

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


def confirm_file_write_qt(parent, path: str, content: str, is_new: bool = False) -> bool:
    """Show a Qt dialog to confirm a file write.

    Args:
        parent: Parent widget
        path: Target file path
        content: Content to write (or diff if file exists)
        is_new: Whether this is a new file

    Returns:
        True if the user confirmed, False otherwise
    """
    if not QT_AVAILABLE:
        logger.error("PySide6 is required for file write confirmation")
        return False

    from ..i18n import _

    title = _("New file") if is_new else _("Proposed changes")
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setMinimumSize(600, 400)
    dialog.setModal(True)

    layout = QtWidgets.QVBoxLayout(dialog)

    # Path header
    header = QtWidgets.QLabel(f"<b>{escape(path)}</b>")
    header.setTextFormat(QtCore.Qt.RichText)
    header.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    layout.addWidget(header)

    # Content preview (scrollable)
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    text_edit = QtWidgets.QPlainTextEdit()
    text_edit.setReadOnly(True)
    text_edit.setPlainText(content)
    text_edit.setMaximumBlockCount(10000)
    # Monospace font for diffs
    font = text_edit.font()
    font.setFamily("Consolas" if hasattr(QtCore.Qt, "ită") else "Monospace")
    text_edit.setFont(font)
    scroll.setWidget(text_edit)
    layout.addWidget(scroll, 1)

    # Buttons
    button_box = QtWidgets.QDialogButtonBox()
    button_box.addButton(_("Cancel"), QtWidgets.QDialogButtonBox.RejectRole)
    write_btn = button_box.addButton(_("Write file"), QtWidgets.QDialogButtonBox.AcceptRole)
    write_btn.setDefault(True)
    layout.addWidget(button_box)

    # Show dialog
    result = dialog.exec()
    return result == QtWidgets.QDialog.Accepted


def confirm_file_delete_qt(parent, path: str) -> bool:
    """Show a Qt dialog to confirm file deletion.

    Args:
        parent: Parent widget
        path: File path to delete

    Returns:
        True if the user confirmed, False otherwise
    """
    if not QT_AVAILABLE:
        logger.error("PySide6 is required for file delete confirmation")
        return False

    from ..i18n import _

    reply = QtWidgets.QMessageBox.question(
        parent,
        _("Delete file"),
        _("Delete this file?\n\n{path}\n\nA backup will be created.").format(path=path),
        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        QtWidgets.QMessageBox.No,
    )
    return reply == QtWidgets.QMessageBox.Yes


def show_file_info_qt(parent, info: dict):
    """Show file information in a Qt dialog.

    Args:
        parent: Parent widget
        info: File info dict from get_file_info()
    """
    if not QT_AVAILABLE or info is None:
        return

    from ..i18n import _

    text = (
        f"{_('Path')}: {info.get('path', '')}\n"
        f"{_('Type')}: {'Directory' if info.get('is_dir') else 'File'}\n"
        f"{_('Size')}: {info.get('size', 0):,} bytes\n"
        f"{_('Modified')}: {info.get('modified', '')}\n"
    )
    if info.get('digest'):
        text += f"SHA-256: {info['digest'][:16]}...\n"

    QtWidgets.QMessageBox.information(parent, _("File information"), text)
