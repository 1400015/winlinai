"""Qt dialogs for the Windows track (phase 4d): settings and history.

The presentation logic lives in pure functions (testable without PySide6,
following the repository's decision-point pattern); the dialog classes stay
thin wrappers over the shared ConfigManager and HistoryStore backends.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

if QT_AVAILABLE:
    _Slot = QtCore.Slot
else:
    def _Slot(*args, **kwargs):
        """No-op decorator when PySide6 is unavailable."""
        def decorator(func):
            return func
        return decorator


# ---------------------------------------------------------------------------
# Pure presentation logic (no Qt import needed to test these)
# ---------------------------------------------------------------------------

def provider_rows(config, providers=("openrouter", "google")):
    """Rows for the API settings table, without exposing stored keys."""
    rows = []
    for provider in providers:
        try:
            key = config.get_api_key(provider) or ""
            stored = bool(key)
            env_var = config.api_key_env_var(provider)
            overridden = config.get_api_key_env_override(provider) is not None
        except Exception:
            stored, env_var, overridden = False, "", False
        rows.append({
            "provider": provider,
            "status": "configured" if stored else "missing",
            "env_var": env_var,
            "overridden": overridden,
        })
    return rows


def history_rows(store, include_archived=False):
    """Session summaries for the history dialog."""
    sessions = store.list_sessions(include_archived=include_archived)
    rows = []
    for session in sessions:
        rows.append({
            "id": session.get("id"),
            "title": session.get("title") or "Untitled",
            "updated_at": session.get("updated_at"),
            "archived": bool(session.get("archived")),
            "active": session.get("id") == store.active_session_id,
        })
    return rows


def save_api_key(config, provider, key_text):
    """Validate and persist an API key. Returns (ok, message)."""
    if not provider or not isinstance(provider, str):
        return False, "invalid-provider"
    key_text = (key_text or "").strip()
    if not key_text:
        return False, "empty-key"
    try:
        config.set_api_key(provider, key_text)
    except Exception:
        logger.error("Failed to store the API key for %s", provider)
        return False, "store-failed"
    return True, "stored"


def autostart_status_label(enabled):
    """Human-readable label for the autostart checkbox state.

    ``enabled`` is True/False/None (None = unknown / not on Windows).
    """
    if enabled is None:
        return "unavailable"
    return "enabled" if enabled else "disabled"


def statistics_rows(ai_client):
    """Token usage rows for the statistics dialog.

    Returns a list of dicts: {"provider": str, "input": int, "output": int, "total": int}.
    Returns an empty list when no client or no stats are available.
    """
    if ai_client is None:
        return []
    try:
        usage = ai_client.get_token_usage()
    except Exception:
        return []
    rows = []
    for provider, stats in usage.items():
        rows.append({
            "provider": provider,
            "input": stats.get("input", 0),
            "output": stats.get("output", 0),
            "total": stats.get("total", 0),
        })
    return rows


# ---------------------------------------------------------------------------
# Dialogs (thin Qt wrappers)
# ---------------------------------------------------------------------------

if QT_AVAILABLE:
    _BaseDialog = QtWidgets.QDialog
else:
    _BaseDialog = object


class QtSettingsDialog(_BaseDialog):
    """API settings: provider selector, key entry, save, plus autostart."""

    def __init__(self, config, parent=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtSettingsDialog")
        super().__init__(parent)
        from . import i18n
        self.config = config
        self.setWindowTitle(i18n._("Settings"))
        self.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(self)

        # --- API Keys section ---
        api_group = QtWidgets.QGroupBox(i18n._("API Keys"), self)
        api_layout = QtWidgets.QVBoxLayout(api_group)
        form = QtWidgets.QFormLayout()
        self.provider_combo = QtWidgets.QComboBox(api_group)
        for row in provider_rows(config):
            label = row["provider"]
            if row["overridden"]:
                label += " ({})".format(i18n._("overridden by environment"))
            self.provider_combo.addItem(label, row["provider"])
        form.addRow(i18n._("Provider"), self.provider_combo)
        self.key_edit = QtWidgets.QLineEdit(api_group)
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.setPlaceholderText(i18n._("API Key"))
        form.addRow(i18n._("API Key"), self.key_edit)
        api_layout.addLayout(form)
        save_key_btn = QtWidgets.QPushButton(i18n._("Save API Key"), api_group)
        save_key_btn.clicked.connect(self._save_key)
        api_layout.addWidget(save_key_btn)
        layout.addWidget(api_group)

        # --- Appearance section (theme selector) ---
        self._build_appearance_section(layout, i18n)

        # --- Updates section ---
        self._build_updates_section(layout, i18n)

        # --- Autostart section (Windows only) ---
        self._build_autostart_section(layout, i18n)

        # --- Buttons ---
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_appearance_section(self, layout, i18n):
        """Add the theme selector."""
        from .qt_theme import available_themes, get_current_theme_name
        group = QtWidgets.QGroupBox(i18n._("Appearance"), self)
        group_layout = QtWidgets.QVBoxLayout(group)

        form = QtWidgets.QFormLayout()
        self.theme_combo = QtWidgets.QComboBox(group)
        current = get_current_theme_name(self.config)
        for theme_name in available_themes():
            self.theme_combo.addItem(theme_name, theme_name)
            if theme_name == current:
                self.theme_combo.setCurrentIndex(self.theme_combo.count() - 1)
        form.addRow(i18n._("Theme"), self.theme_combo)
        group_layout.addLayout(form)

        apply_btn = QtWidgets.QPushButton(i18n._("Apply Theme"), group)
        apply_btn.clicked.connect(self._apply_theme)
        group_layout.addWidget(apply_btn)

        layout.addWidget(group)

    def _apply_theme(self):
        """Apply the selected theme immediately."""
        from .qt_theme import apply_theme, set_current_theme
        theme_name = self.theme_combo.currentData()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            apply_theme(app, theme_name=theme_name)
        set_current_theme(self.config, theme_name)

    def _build_updates_section(self, layout, i18n):
        """Add the updates section: autostart check + manual check + status."""
        from .updater import get_current_version
        group = QtWidgets.QGroupBox(i18n._("Updates"), self)
        group_layout = QtWidgets.QVBoxLayout(group)

        # Checkbox: check for updates on startup
        self.updates_check = QtWidgets.QCheckBox(
            i18n._("Check for updates on startup"), group)
        try:
            enabled = bool(self.config.get("app.check_updates", True))
        except Exception:
            enabled = True
        self.updates_check.setChecked(enabled)
        self.updates_check.stateChanged.connect(self._on_updates_toggled)
        group_layout.addWidget(self.updates_check)

        # Status label
        self.updates_status = QtWidgets.QLabel(group)
        self._refresh_updates_status()
        group_layout.addWidget(self.updates_status)

        # Check now button
        check_btn = QtWidgets.QPushButton(i18n._("Check now"), group)
        check_btn.clicked.connect(self._check_updates_now)
        group_layout.addWidget(check_btn)

        # Current version footer
        version_label = QtWidgets.QLabel(
            i18n._("Current version: {version}").format(version=get_current_version()),
            group)
        version_label.setStyleSheet("color: gray;")
        group_layout.addWidget(version_label)

        layout.addWidget(group)

    def _refresh_updates_status(self):
        from . import i18n
        try:
            available = bool(self.config.get("update.available", False))
            version = self.config.get("update.version", "")
        except Exception:
            available, version = False, ""
        if available and version:
            self.updates_status.setText(
                i18n._("New version available: {version}").format(version=version))
            self.updates_status.setStyleSheet("color: #4CAF50;")
        else:
            self.updates_status.setText(i18n._("You are up to date."))
            self.updates_status.setStyleSheet("color: gray;")

    def _on_updates_toggled(self, state):
        try:
            self.config.set("app.check_updates", state == QtCore.Qt.Checked)
        except Exception:
            logger.warning("Could not persist update-check preference")

    def _check_updates_now(self):
        """Run an update check in a worker thread and refresh the status."""
        import threading
        from . import i18n
        from .updater import check_for_updates

        self.updates_status.setText(i18n._("Checking for updates..."))
        self.updates_status.setStyleSheet("color: gray;")

        def worker():
            update = check_for_updates()
            QtCore.QMetaObject.invokeMethod(
                self, "_on_update_check_done",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(object, update))

        threading.Thread(target=worker, daemon=True).start()

    @_Slot(object)
    def _on_update_check_done(self, update):
        from . import i18n
        from .updater import get_current_version
        if update is None:
            try:
                self.config.set("update.available", False)
            except Exception:
                pass
            self.updates_status.setText(
                i18n._("You are up to date (version {version}).").format(
                    version=get_current_version()))
            self.updates_status.setStyleSheet("color: gray;")
        else:
            try:
                self.config.set("update.available", True)
                self.config.set("update.version", update["version"])
                self.config.set("update.url", update["url"])
            except Exception:
                pass
            self.updates_status.setText(
                i18n._("New version available: {version}").format(
                    version=update["version"]))
            self.updates_status.setStyleSheet("color: #4CAF50;")
            # Offer to open the releases page (no auto-download: honest + safe)
            reply = QtWidgets.QMessageBox.question(
                self, i18n._("Update available"),
                i18n._("WinLinAI {version} is available. Open the releases page?").format(
                    version=update["version"]),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if reply == QtWidgets.QMessageBox.Yes:
                import webbrowser
                webbrowser.open(update["url"])

    def _build_autostart_section(self, layout, i18n):
        """Add the autostart checkbox (Windows only, hidden elsewhere)."""
        from .windows_autostart import is_autostart_enabled, is_windows
        if not is_windows():
            return
        group = QtWidgets.QGroupBox(i18n._("Startup"), self)
        group_layout = QtWidgets.QVBoxLayout(group)
        self.autostart_check = QtWidgets.QCheckBox(
            i18n._("Start with Windows"), group)
        status = is_autostart_enabled()
        self.autostart_check.setChecked(bool(status))
        self.autostart_check.stateChanged.connect(self._on_autostart_changed)
        group_layout.addWidget(self.autostart_check)
        self.autostart_status = QtWidgets.QLabel(
            i18n._("Status: {}").format(
                i18n._(autostart_status_label(status))), group)
        group_layout.addWidget(self.autostart_status)
        layout.addWidget(group)

    def _on_autostart_changed(self, state):
        from . import i18n
        from .windows_autostart import set_autostart, is_autostart_enabled, autostart_status_label
        enabled = state == 2  # Qt.Checked
        result = set_autostart(enabled)
        status = is_autostart_enabled()
        self.autostart_status.setText(
            i18n._("Status: {}").format(i18n._(autostart_status_label(status))))
        if result is None:
            logger.warning("Autostart change failed")

    def selected_provider(self):
        return self.provider_combo.currentData()

    def _save_key(self):
        ok, _message = save_api_key(self.config, self.selected_provider(),
                                    self.key_edit.text())
        if ok:
            self.key_edit.clear()

    def _save(self):
        ok, _message = save_api_key(self.config, self.selected_provider(),
                                    self.key_edit.text())
        if ok:
            self.accept()


class QtHistoryDialog(_BaseDialog):
    """Conversation history: session list, open, new, archive, delete, export."""

    def __init__(self, store, parent=None, on_open=None, on_new=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtHistoryDialog")
        super().__init__(parent)
        from . import i18n
        self.store = store
        self.on_open = on_open
        self.on_new = on_new
        self.setWindowTitle(i18n._("Conversation History"))
        self.setMinimumSize(520, 360)
        layout = QtWidgets.QVBoxLayout(self)
        self.list_widget = QtWidgets.QListWidget(self)
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        layout.addWidget(self.list_widget, 1)

        # Button row 1: New, Open
        row1 = QtWidgets.QHBoxLayout()
        new_button = QtWidgets.QPushButton(i18n._("New conversation"), self)
        new_button.clicked.connect(self._new)
        open_button = QtWidgets.QPushButton(i18n._("Open"), self)
        open_button.clicked.connect(self._open)
        row1.addWidget(new_button)
        row1.addWidget(open_button)
        layout.addLayout(row1)

        # Button row 2: Archive, Delete, Export
        row2 = QtWidgets.QHBoxLayout()
        self.archive_button = QtWidgets.QPushButton(i18n._("Archive"), self)
        self.archive_button.clicked.connect(self._archive)
        self.delete_button = QtWidgets.QPushButton(i18n._("Delete"), self)
        self.delete_button.clicked.connect(self._delete)
        self.export_button = QtWidgets.QPushButton(i18n._("Export..."), self)
        self.export_button.clicked.connect(self._export)
        row2.addWidget(self.archive_button)
        row2.addWidget(self.delete_button)
        row2.addWidget(self.export_button)
        layout.addLayout(row2)

        # Close button
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.reload()

    def reload(self):
        self.list_widget.clear()
        from . import i18n
        for entry in history_rows(self.store):
            label = entry["title"]
            if entry["active"]:
                label = "• " + label
            if entry["archived"]:
                label += " — " + i18n._("archived")
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, entry["id"])
            item.setData(QtCore.Qt.UserRole + 1, entry["archived"])
            self.list_widget.addItem(item)

    def selected_session_id(self):
        item = self.list_widget.currentItem()
        return item.data(QtCore.Qt.UserRole) if item is not None else None

    def _selected_item(self):
        return self.list_widget.currentItem()

    def _new(self):
        session = self.store.create_session(select=True)
        session_id = session.get("id") if isinstance(session, dict) else session
        if callable(self.on_new):
            self.on_new(session_id)
        self.reload()

    def _open(self):
        session_id = self.selected_session_id()
        if session_id is None:
            return
        self.store.select_session(session_id)
        if callable(self.on_open):
            self.on_open(session_id)
        self.accept()

    def _archive(self):
        """Toggle archive status of the selected session."""
        item = self._selected_item()
        if item is None:
            return
        session_id = item.data(QtCore.Qt.UserRole)
        is_archived = bool(item.data(QtCore.Qt.UserRole + 1))
        try:
            if hasattr(self.store, "set_archived"):
                self.store.set_archived(session_id, not is_archived)
            elif hasattr(self.store, "archive_session"):
                if is_archived:
                    self.store.unarchive_session(session_id)
                else:
                    self.store.archive_session(session_id)
            else:
                logger.warning("Archive not supported by this history store")
                return
        except Exception as error:
            logger.error("Archive failed: %s", type(error).__name__)
            return
        self.reload()

    def _delete(self):
        """Delete the selected session after confirmation."""
        from . import i18n
        item = self._selected_item()
        if item is None:
            return
        session_id = item.data(QtCore.Qt.UserRole)
        reply = QtWidgets.QMessageBox.question(
            self, i18n._("Delete conversation"),
            i18n._("Delete this conversation? This cannot be undone."),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            if hasattr(self.store, "delete_session"):
                self.store.delete_session(session_id)
            else:
                logger.warning("Delete not supported by this history store")
                return
        except Exception as error:
            logger.error("Delete failed: %s", type(error).__name__)
            return
        self.reload()

    def _export(self):
        """Export the selected session to a file."""
        from . import i18n
        item = self._selected_item()
        if item is None:
            return
        session_id = item.data(QtCore.Qt.UserRole)
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, i18n._("Export conversation"),
            "conversation.md", "Markdown (*.md);;JSON (*.json);;Text (*.txt)")
        if not filename:
            return
        try:
            if hasattr(self.store, "export_session"):
                self.store.export_session(session_id, filename)
            else:
                # Fallback: export messages manually
                messages = self.store.load_messages(session_id)
                with open(filename, "w", encoding="utf-8") as f:
                    for msg in messages:
                        role = msg.get("role", "unknown")
                        content = msg.get("content", "")
                        f.write(f"**{role}**: {content}\n\n")
        except Exception as error:
            logger.error("Export failed: %s", type(error).__name__)
            QtWidgets.QMessageBox.warning(
                self, i18n._("Export failed"), str(error))


class QtStatisticsDialog(_BaseDialog):
    """Usage statistics: token counts by provider, with reset."""

    def __init__(self, ai_client, parent=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtStatisticsDialog")
        super().__init__(parent)
        from . import i18n
        self.ai_client = ai_client
        self.setWindowTitle(i18n._("Statistics - Linux AI Assistant"))
        self.setMinimumSize(400, 300)
        layout = QtWidgets.QVBoxLayout(self)

        title = QtWidgets.QLabel("<b>{}</b>".format(i18n._("Usage Statistics")), self)
        layout.addWidget(title)

        self.rows_layout = QtWidgets.QVBoxLayout()
        layout.addLayout(self.rows_layout)

        self.token_labels = []
        self._populate()

        reset_btn = QtWidgets.QPushButton(i18n._("Reset Statistics"), self)
        reset_btn.clicked.connect(self._reset)
        reset_btn.setStyleSheet("margin-top: 10px;")
        layout.addWidget(reset_btn)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _populate(self):
        for row in statistics_rows(self.ai_client):
            provider_box = QtWidgets.QHBoxLayout()
            provider_label = QtWidgets.QLabel("{}:".format(row["provider"]), self)
            provider_box.addWidget(provider_label)
            tokens_label = QtWidgets.QLabel(
                "Input: {}, Output: {}, Total: {}".format(
                    row["input"], row["output"], row["total"]), self)
            provider_box.addWidget(tokens_label, 1)
            self.rows_layout.addLayout(provider_box)
            self.token_labels.append((row["provider"], tokens_label))

    def _reset(self):
        if self.ai_client is None:
            return
        try:
            self.ai_client.reset_token_usage()
        except Exception:
            logger.warning("Could not reset token usage")
        for _provider, tokens_label in self.token_labels:
            tokens_label.setText("Input: 0, Output: 0, Total: 0")
