"""Qt shell for the Windows track, using the shared offline backends.

PySide6 is an optional dependency: when absent, ``available()`` is False and
``run()`` reports the same missing-binding message style used for GTK.
"""
import logging
import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .qt_chat import QtChatWidget
    from .qt_tray import QtTrayIcon
    from .history_store import HistoryStore

logger = logging.getLogger(__name__)

QT_IMPORT_ERROR = None

try:
    from PySide6 import QtCore, QtWidgets
    QT_AVAILABLE = True
except ImportError as error:
    QT_AVAILABLE = False
    QT_IMPORT_ERROR = str(error)


MIN_WINDOW_SIZE = (420, 260)


class QtStartupError(RuntimeError):
    """A required backend failed before the Qt shell was ready."""


def available() -> bool:
    return QT_AVAILABLE


def missing_dependency_message() -> str:
    return (
        "PySide6 is not installed. Install it with:\n"
        "  pip install PySide6\n"
        "or add the `qt` extra: pip install -e .[qt]"
    )


if TYPE_CHECKING or QT_AVAILABLE:
    _BaseShell = QtWidgets.QMainWindow
else:
    _BaseShell = object


class QtShell(_BaseShell):
    """Qt main window: status line plus the chat widget (phase 4b)."""

    def __init__(self, config_manager, platform_name, history_path=None):
        if not QT_AVAILABLE:
            raise RuntimeError(missing_dependency_message())
        super().__init__()
        self.config = config_manager
        self.platform_name = platform_name
        self.history_path = history_path
        self.chat: Optional[QtChatWidget] = None
        self.history_store: Optional[HistoryStore] = None
        self.tray_icon: Optional[QtTrayIcon] = None
        self.setWindowTitle("Linux AI Assistant")
        self.resize(*MIN_WINDOW_SIZE)
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        status = QtWidgets.QLabel(self._status_text(), central)
        status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(status)
        self._build_chat(layout)
        self.setCentralWidget(central)
        self._build_tray()

    def open_settings_dialog(self):
        from .qt_dialogs import QT_AVAILABLE as DIALOGS_QT_AVAILABLE, QtSettingsDialog
        if not DIALOGS_QT_AVAILABLE:
            return
        QtSettingsDialog(self.config, self).exec()

    def open_history_dialog(self):
        from .qt_dialogs import QT_AVAILABLE as DIALOGS_QT_AVAILABLE, QtHistoryDialog
        if not DIALOGS_QT_AVAILABLE or getattr(self, "history_store", None) is None:
            return
        def reopen(session_id):
            if self.chat is not None and hasattr(self.chat, "load_session"):
                self.chat.load_session(session_id)
        QtHistoryDialog(self.history_store, self, on_open=reopen, on_new=reopen).exec()

    def on_expert_mode_toggled(self, _button):
        """Toggle expert mode (called from the tray menu or a future button)."""
        try:
            current = bool(self.config.get("app.expert_mode", False))
        except Exception:
            current = False
        new_value = not current
        try:
            self.config.set("app.expert_mode", new_value)
        except Exception as error:
            logger.warning("Could not persist expert mode: %s", type(error).__name__)
            return
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.update_expert_mode(new_value)
        logger.info("Expert mode %s (Qt)", "enabled" if new_value else "disabled")

    def show_statistics(self):
        """Show usage statistics dialog (parity with GTK tray)."""
        from .qt_dialogs import QT_AVAILABLE as DIALOGS_QT_AVAILABLE
        if not DIALOGS_QT_AVAILABLE:
            return
        from .qt_dialogs import QtStatisticsDialog
        chat = getattr(self, "chat", None)
        ai_client = getattr(chat, "ai_client", None) if chat is not None else None
        QtStatisticsDialog(ai_client, self).exec()

    def toggle_visibility(self):
        """Single toggle point for the Qt track (tray, future shortcut)."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            tray.update_toggle_label(self.isVisible())

    def notify_update_available(self, update):
        """Show an update-available system message in the chat."""
        from . import i18n
        message = i18n._(
            "New version available: {version} (open Settings → Updates for details)."
        ).format(version=update["version"])
        logger.info("Update available: %s", update["version"])
        chat = getattr(self, "chat", None)
        if chat is not None:
            chat.append_system_message(message)

    def _build_tray(self):
        from .qt_tray import QT_AVAILABLE as TRAY_QT_AVAILABLE, QtTrayIcon
        if not TRAY_QT_AVAILABLE or not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        try:
            self.tray_icon = QtTrayIcon(self.config, self, self)
        except Exception as error:
            logger.warning("Qt tray icon unavailable: %s", type(error).__name__)
            self.tray_icon = None

    def _build_chat(self, layout):
        from .qt_chat import QT_AVAILABLE as CHAT_QT_AVAILABLE, QtChatWidget
        if not CHAT_QT_AVAILABLE:
            raise QtStartupError("The Qt chat requires PySide6.")
        from .offline_assistant import OfflineAssistant
        from .system_utils import SystemUtils
        try:
            system_utils = SystemUtils(self.config)
        except Exception as error:
            raise QtStartupError("System utilities could not be initialized ({})".format(
                type(error).__name__)) from error
        try:
            offline = OfflineAssistant(system_utils, self.config)
        except Exception as error:
            raise QtStartupError("The offline assistant could not be initialized ({})".format(
                type(error).__name__)) from error
        # AI provider client (optional; chat falls back to offline without it)
        ai_client = None
        try:
            from .ai_client import AIClient
            ai_client = AIClient(self.config)
        except Exception as error:
            logger.warning("AI client unavailable: %s", type(error).__name__)
        try:
            from .history_store import HistoryStore
            self.history_store = HistoryStore() if self.history_path is None else HistoryStore(self.history_path)
            # Validate existing history and initialize a writable conversation
            # before displaying the chat. Loading messages alone can mask a
            # malformed or unreadable store as an empty conversation.
            self.history_store.list_sessions()
        except Exception as error:
            self._close_history()
            raise QtStartupError(
                "Conversation history could not be opened ({}). "
                "Check access to the history file; for damaged history, use "
                "`python -m src.cli history recover --help`.".format(type(error).__name__)) from error
        try:
            self.chat = QtChatWidget(self.config, offline, self,
                                      history_store=self.history_store,
                                      ai_client=ai_client)
            layout.addWidget(self.chat, 1)
        except Exception:
            self._close_history()
            raise

    def _close_history(self):
        if self.history_store is not None:
            self.history_store.close()

    def _status_text(self):
        from . import i18n
        name = {"windows": "Windows", "wsl": "WSL", "linux": "Linux"}.get(
            self.platform_name, self.platform_name)
        title = i18n._("Welcome to Linux AI Assistant!")
        return "{}\nQt shell — platform: {}".format(title, name)

    def closeEvent(self, event):
        logger.info("Qt shell closed by the user")
        self._close_history()
        super().closeEvent(event)


def lock_file_path(base_dir=None):
    """Single-instance lock location for the Qt track."""
    import os
    directory = base_dir or os.path.join(
        os.path.expanduser("~"), ".config", "linux_ai_assistant")
    return os.path.join(directory, "qt-instance.lock")


def _maybe_check_updates(config_manager, shell):
    """Silent background update check on startup (opt-in via app.check_updates).

    Never blocks startup: runs in a daemon thread via a signal-based
    Worker, stores the result in config and reports it as a system
    message in the chat. No auto-download.
    """
    if not QT_AVAILABLE:
        return
    try:
        enabled = bool(config_manager.get("app.check_updates", True))
    except Exception:
        enabled = True
    if not enabled:
        return

    from .qt_worker import Worker, start_worker

    def check():
        from .updater import check_for_updates
        return check_for_updates()

    def on_finished(update):
        # Only a confirmed 'available' result may notify or mark the config;
        # 'failed', 'current' and 'unsupported' show nothing and store
        # nothing (a failure is not an update, and it is not 'up to date').
        if not isinstance(update, dict) or update.get("status") != "available":
            return
        try:
            config_manager.set("update.available", True)
            config_manager.set("update.version", update["version"])
            config_manager.set("update.url", update["url"])
        except Exception:
            pass
        if shell is not None:
            shell.notify_update_available(update)

    worker = Worker()
    worker.finished.connect(on_finished)

    def start():
        start_worker(worker, check)

    # Defer until the event loop is running so signals are delivered.
    QtCore.QTimer.singleShot(0, start)


def run(config_manager=None, argv=None):
    """Start Qt with all required backends, returning a process exit code."""
    if not QT_AVAILABLE:
        print("\nError: {}\n\n{}".format(QT_IMPORT_ERROR, missing_dependency_message()),
              file=sys.stderr)
        return 1
    shell = None
    lock = None
    try:
        if config_manager is None:
            from .config_manager import ConfigManager
            try:
                config_manager = ConfigManager()
            except Exception as error:
                raise QtStartupError("Configuration could not be loaded ({})".format(
                    type(error).__name__)) from error
        from . import i18n
        i18n.set_language_from_config(config_manager)
        from .platform import detect_platform
        platform_name = detect_platform()
        argv = list(sys.argv[:1]) if argv is None else list(argv)
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
        app.setApplicationName("linux-ai-assistant")

        # Apply visual theme from themes/*.json
        try:
            from .qt_theme import apply_theme, get_current_theme_name
            theme_name = get_current_theme_name(config_manager)
            apply_theme(app, theme_name=theme_name)
        except Exception as error:
            logger.warning("Could not apply theme: %s", type(error).__name__)

        # Single-instance guard (the GTK track uses DesktopActivation):
        # QLockFile also removes a stale lock left by a crashed process.
        lock = QtCore.QLockFile(lock_file_path())
        if not lock.tryLock(0):
            print("Another Linux AI Assistant (Qt) instance is already running.",
                  file=sys.stderr)
            return 1
        shell = QtShell(config_manager, platform_name)
        shell.show()
        _maybe_check_updates(config_manager, shell)
        logger.info("Starting Qt event loop (platform: %s)", platform_name)
        return app.exec()
    except Exception as error:
        # Report the failed component without echoing configuration or
        # untrusted history content from the original exception.
        detail = str(error) if isinstance(error, QtStartupError) else type(error).__name__
        logger.error("Qt startup failed: %s", detail)
        print("Error: Qt startup failed: {}".format(detail), file=sys.stderr)
        return 1
    finally:
        if shell is not None:
            shell._close_history()
        if config_manager is not None:
            try:
                config_manager.flush()
            except Exception as error:
                logger.warning("Could not flush Qt configuration: %s", type(error).__name__)
        if lock is not None:
            lock.unlock()


if __name__ == "__main__":
    sys.exit(run(None))
