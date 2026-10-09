"""Qt system tray for the Windows track (phase 4c).

The drawer toggle lives here in full: ``QSystemTrayIcon`` delivers a real
left-click (Trigger) event on Windows, which the AppIndicator3 backend on
Linux cannot provide. The enable/disable decision reuses the shared
``app.tray_toggle_on_click`` config key and the same single toggle point
(the shell window), keeping both tracks coherent.

Parity with the GTK tray (src/tray_icon.py):
- Expert Mode checkbox (checkable QAction)
- Statistics menu item
- Bundled window icon: Windows .ico, then the shared SVG resolver
- Platform-aware tooltip
"""
from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtGui, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


TOGGLE_REASONS = frozenset(("Trigger", "MiddleClick"))

ICON_NAME = "io.github.linux_ai_assistant"


def qt_icon_candidates(platform, checkout_root, prefix, svg_path, icon_name=ICON_NAME):
    """Icon files for the Qt window and tray, first match wins.

    Windows prefers the existing .ico (checkout, then the installed wheel)
    because the taskbar loads that format without an SVG plugin. Every
    platform then uses the SVG ``desktop_icons.icon_path`` already resolved:
    checkout, installed prefix, or Flatpak. GTK keeps its own resolver.
    """
    candidates = []
    if platform == "win32":
        candidates.append(Path(checkout_root) / "assets" / (icon_name + ".ico"))
        candidates.append(
            Path(prefix) / "share" / "linux-ai-assistant" / (icon_name + ".ico"))
    if svg_path is not None:
        candidates.append(Path(svg_path))
    return candidates


def _bundled_icon_path():
    """Locate the Qt icon in a checkout or an installed wheel."""
    from .desktop_icons import icon_path
    checkout = Path(__file__).resolve().parents[1]
    return next(
        (path for path in qt_icon_candidates(
            sys.platform, checkout, sys.prefix, icon_path())
         if path.is_file()),
        None)


def _icon_from_svg(path):
    """Rasterize an SVG after the application already exists.

    ``QIcon(path)`` leaves an SVG empty when the icon engine was not loaded
    before ``QApplication``. ``QSvgRenderer`` uses the imported module directly.
    """
    try:
        from PySide6 import QtCore, QtSvg
    except ImportError:
        return None
    renderer = QtSvg.QSvgRenderer(str(path))
    if not renderer.isValid():
        return None
    size = renderer.defaultSize()
    if not size.isValid() or size.isEmpty():
        size = QtCore.QSize(128, 128)
    image = QtGui.QImage(size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QtGui.QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    if image.isNull():
        return None
    return QtGui.QIcon(QtGui.QPixmap.fromImage(image))


def load_window_icon():
    """QIcon for the Qt window and tray, or None when Qt is unavailable."""
    if not QT_AVAILABLE:
        return None
    path = _bundled_icon_path()
    if path is None:
        return QtGui.QIcon()
    if path.suffix.lower() == ".svg":
        rendered = _icon_from_svg(path)
        if rendered is not None:
            return rendered
    return QtGui.QIcon(str(path))


def _platform_label(platform_name):
    """Human-readable platform name for the tooltip."""
    return {
        "windows": "Windows",
        "wsl": "WSL",
        "linux": "Linux",
    }.get(platform_name, platform_name or "Unknown")


def normalize_reason(activation_reason):
    """Normalize a Qt activation reason (enum, name or int) to a name."""
    if activation_reason is None:
        return ""
    text = str(activation_reason)
    if not text.isdigit():
        for separator in (".", "::"):
            if separator in text:
                return text.rsplit(separator, 1)[-1]
        return text
    return {"2": "DoubleClick", "3": "Trigger", "4": "MiddleClick"}.get(text, "")


def tray_click_toggles(config_manager, activation_reason, default=True):
    """Pure decision: does this activation reason toggle the drawer?

    ``Trigger`` is a real left click (and ``MiddleClick`` the middle button,
    matching the AppIndicator3 backend). Unknown reasons never toggle; the
    config key can still disable the behaviour entirely.
    """
    from .platform.tray_config import toggle_on_click_enabled
    if not toggle_on_click_enabled(config_manager, default):
        return False
    return normalize_reason(activation_reason) in TOGGLE_REASONS


def quit_only_after_confirmation(config_manager):
    """Placeholder decision point: quit stays explicit in the context menu."""
    return True


def expert_mode_enabled(config_manager, default=False):
    """Read app.expert_mode from config, tolerating a broken backend."""
    try:
        return bool(config_manager.get("app.expert_mode", default))
    except Exception:
        return default


if TYPE_CHECKING or QT_AVAILABLE:
    _BaseTray = QtWidgets.QSystemTrayIcon
else:
    _BaseTray = object


class QtTrayIcon(_BaseTray):
    """System tray icon with drawer toggle on left click.

    Menu parity with the GTK tray: Show/Hide, Expert Mode (checkbox),
    Settings, Conversation History, Statistics, Quit.
    """

    def __init__(self, config_manager, shell_window, parent=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtTrayIcon")
        super().__init__(parent)
        self.config = config_manager
        self.shell = shell_window
        self._syncing_expert = False
        self._tray_icon = self._load_icon()
        self.setIcon(self._tray_icon)
        self.setToolTip(self._tooltip_text())
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _load_icon(self):
        """Load the bundled icon, falling back to the theme or window icon."""
        icon = load_window_icon()
        if icon is None or icon.isNull():
            icon = QtGui.QIcon.fromTheme("linux-ai-assistant")
        if icon.isNull():
            icon = self.shell.windowIcon()
        return icon

    def _tooltip_text(self):
        """Tooltip with the platform name."""
        from . import i18n
        platform = getattr(self.shell, "platform_name", "")
        label = _platform_label(platform)
        return "{} — {}".format(i18n._("Linux AI Assistant"), label)

    def _build_menu(self):
        from . import i18n
        self.menu = QtWidgets.QMenu()

        # Show/Hide window toggle
        self.toggle_action = self.menu.addAction(i18n._("Hide Window"))
        self.toggle_action.triggered.connect(self.toggle_window)

        self.menu.addSeparator()

        # Expert Mode checkbox (parity with GTK tray)
        self.expert_action = self.menu.addAction(i18n._("Expert Mode"))
        self.expert_action.setCheckable(True)
        self.expert_action.setChecked(expert_mode_enabled(self.config))
        self.expert_action.triggered.connect(self._on_expert_toggled)

        self.menu.addSeparator()

        # Settings
        self.settings_action = self.menu.addAction(i18n._("Settings"))
        self.settings_action.triggered.connect(self.show_settings)

        # Conversation History
        self.history_action = self.menu.addAction(i18n._("Conversation History"))
        self.history_action.triggered.connect(self.show_history)

        # Statistics (parity with GTK tray)
        self.stats_action = self.menu.addAction(i18n._("Statistics"))
        self.stats_action.triggered.connect(self.show_statistics)

        self.menu.addSeparator()

        # Quit
        self.quit_action = self.menu.addAction(i18n._("Quit"))
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)

    def _on_expert_toggled(self, checked):
        """Handle Expert Mode toggle from the tray menu."""
        if self._syncing_expert:
            return
        handler = getattr(self.shell, "on_expert_mode_toggled", None)
        if callable(handler):
            handler(None)
        else:
            # Fallback: persist directly if the shell has no handler
            try:
                self.config.set("app.expert_mode", bool(checked))
            except Exception:
                logger.warning("Could not persist expert mode from tray")

    def show_settings(self):
        dialog = getattr(self.shell, "open_settings_dialog", None)
        if callable(dialog):
            dialog()

    def show_history(self):
        dialog = getattr(self.shell, "open_history_dialog", None)
        if callable(dialog):
            dialog()

    def show_statistics(self):
        """Open the statistics dialog (parity with GTK tray)."""
        dialog = getattr(self.shell, "_show_stats_dialog", None)
        if callable(dialog):
            dialog()
        else:
            handler = getattr(self.shell, "show_statistics", None)
            if callable(handler):
                handler()

    def _on_activated(self, reason):
        if tray_click_toggles(self.config, reason):
            self.toggle_window()

    def toggle_window(self):
        # Single toggle point: the shell keeps the state and the menu label
        # coherent wherever the toggle came from (click, menu, shortcut).
        self.shell.toggle_visibility()

    def quit(self):
        logger.info("Quit through the Qt tray menu")
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.quit()

    def update_toggle_label(self, visible):
        from . import i18n
        if hasattr(self, "toggle_action"):
            self.toggle_action.setText(
                i18n._("Hide Window") if visible else i18n._("Show Window"))

    def update_expert_mode(self, enabled):
        """Sync the Expert Mode checkbox without re-triggering the handler."""
        if not hasattr(self, "expert_action"):
            return
        if self.expert_action.isChecked() == bool(enabled):
            return
        self._syncing_expert = True
        try:
            self.expert_action.setChecked(bool(enabled))
        finally:
            self._syncing_expert = False
        logger.debug("Expert mode menu updated: %s", enabled)

    def update_tooltip(self):
        """Refresh the tooltip (e.g. after a platform change)."""
        self.setToolTip(self._tooltip_text())
