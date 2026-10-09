"""Qt dialogs for the Windows track (phase 4d): settings and history.

The presentation logic lives in pure functions (testable without PySide6,
following the repository's decision-point pattern); the dialog classes stay
thin wrappers over the shared ConfigManager and HistoryStore backends.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

if TYPE_CHECKING or QT_AVAILABLE:
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

def export_session_to_file(store, session_id, filename):
    """Write a session export to filename, choosing the format by extension.

    Pure logic, no Qt: the history dialog calls this so the behaviour is
    testable without a window on every core job. export_session's second
    argument is the format (markdown/json) and it returns the text; a path
    is never passed as the format. Plain .txt uses export_to_text.
    """
    lower = filename.lower()
    if hasattr(store, "export_session") and lower.endswith((".md", ".json")):
        fmt = "json" if lower.endswith(".json") else "markdown"
        text = store.export_session(session_id, fmt)
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(text)
        return
    from .qt_conversation_actions import export_to_text
    messages = store.load_messages(session_id)
    with open(filename, "w", encoding="utf-8") as handle:
        handle.write(export_to_text(messages))


def update_status_phrase(update, current_version=""):
    """Choose the settings status phrase for a check result.

    Pure function (the dialog renders whatever it returns): a failure is
    never worded as being up to date, and 'current' carries the running
    version. 'available' carries the new version.
    """
    from . import i18n
    status = (update or {}).get("status")
    if status == "available":
        return i18n._("New version available: {version}").format(
            version=update["version"])
    if status == "current":
        return i18n._("You are up to date (version {version}).").format(
            version=update.get("version") or current_version)
    if status == "failed":
        return i18n._("Could not check for updates.")
    if status == "unsupported":
        return i18n._("Update checks are supported on Windows.")
    return i18n._("Updates have not been checked.")


def checkbox_is_checked(state) -> bool:
    """Interpret a checkbox state from any Qt binding generation.

    stateChanged may deliver the integer 2/0 (PySide2, older PySide6 and
    the untyped fallback) or a Qt.CheckState value (recent PySide6, where
    comparing the enum with the int 2 is always False). Both mark the same
    preference; a single decision is shared by every slot.
    """
    checked_states = (2,)
    unchecked_states = (0,)
    state_value = getattr(state, "value", state)
    if state_value in checked_states:
        return True
    if state_value in unchecked_states:
        return False
    try:
        from PySide6 import QtCore
    except ImportError:
        return bool(state)
    checked = getattr(QtCore.Qt, "Checked", None)
    if checked is not None and (state is checked or state == checked):
        return True
    unchecked = getattr(QtCore.Qt, "Unchecked", None)
    if unchecked is not None and (state is unchecked or state == unchecked):
        return False
    return bool(state)


def provider_rows(config, providers=("openrouter", "google_ai_studio")):
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

if TYPE_CHECKING or QT_AVAILABLE:
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
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
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
            QtWidgets.QDialogButtonBox.StandardButton.Close)
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
        from .updater import get_current_version
        try:
            available = bool(self.config.get("update.available", False))
            version = self.config.get("update.version", "")
            checked = self.config.get("update.checked", False)
            checked_ok = self.config.get("update.last_result") == "current"
        except Exception:
            available, version, checked, checked_ok = False, "", False, False
        if available and version:
            self.updates_status.setText(
                i18n._("New version available: {version}").format(version=version))
            self.updates_status.setStyleSheet("color: #4CAF50;")
        elif checked_ok and checked:
            # Only a completed 'current' check may say up to date.
            self.updates_status.setText(
                i18n._("You are up to date (version {version}).").format(
                    version=version or get_current_version()))
            self.updates_status.setStyleSheet("color: gray;")
        else:
            # No completed check: neutral, never 'up to date'.
            self.updates_status.setText(i18n._("Updates have not been checked."))
            self.updates_status.setStyleSheet("color: gray;")

    def _on_updates_toggled(self, state):
        try:
            self.config.set("app.check_updates", checkbox_is_checked(state))
        except Exception:
            logger.warning("Could not persist update-check preference")

    def _check_updates_now(self):
        """Run an update check via a signal-based worker (no invokeMethod)."""
        from . import i18n
        from .qt_worker import Worker, start_worker
        from .updater import check_for_updates

        self.updates_status.setText(i18n._("Checking for updates..."))
        self.updates_status.setStyleSheet("color: gray;")

        worker = Worker()
        worker.finished.connect(self._on_update_check_done)
        start_worker(worker, check_for_updates)

    @_Slot(object)
    def _on_update_check_done(self, update):
        from . import i18n
        from .updater import get_current_version
        result = update or {}
        status = result.get("status")
        try:
            self.config.set("update.checked", True)
            self.config.set("update.last_result", status)
        except Exception:
            pass
        if status == "available":
            try:
                self.config.set("update.available", True)
                self.config.set("update.version", result["version"])
                self.config.set("update.url", result["url"])
            except Exception:
                pass
            self.updates_status.setText(
                update_status_phrase(result, get_current_version()))
            self.updates_status.setStyleSheet("color: #4CAF50;")
            # Offer to open the releases page (no auto-download: honest + safe)
            reply = QtWidgets.QMessageBox.question(
                self, i18n._("Update available"),
                i18n._("WinLinAI {version} is available. Open the releases page?").format(
                    version=result["version"]),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                import webbrowser
                webbrowser.open(result["url"])
        elif status == "current":
            try:
                self.config.set("update.available", False)
            except Exception:
                pass
            self.updates_status.setText(
                update_status_phrase(result, get_current_version()))
            self.updates_status.setStyleSheet("color: gray;")
        else:
            # 'failed' or 'unsupported': never say up to date, and never
            # erase a previously stored available update.
            self.updates_status.setText(
                update_status_phrase(result, get_current_version()))
            self.updates_status.setStyleSheet("color: gray;")
            return

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
        from .windows_autostart import set_autostart, is_autostart_enabled
        enabled = checkbox_is_checked(state)
        result = set_autostart(enabled)
        status = is_autostart_enabled()
        self.autostart_status.setText(
            i18n._("Status: {}").format(i18n._(autostart_status_label(status))))
        if result is None:
            logger.warning("Autostart change failed")
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(bool(status))
            self.autostart_check.blockSignals(False)

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
        self.list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
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
        self.archive_button = QtWidgets.QPushButton(i18n._("Archive / restore"), self)
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
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.reload()

    def reload(self):
        self.list_widget.clear()
        from . import i18n
        for entry in history_rows(self.store, include_archived=True):
            label = entry["title"]
            if entry["active"]:
                label = "• " + label
            if entry["archived"]:
                label += " — " + i18n._("archived")
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, entry["id"])
            item.setData(QtCore.Qt.ItemDataRole.UserRole + 1, entry["archived"])
            self.list_widget.addItem(item)

    def selected_session_id(self):
        item = self.list_widget.currentItem()
        return item.data(QtCore.Qt.ItemDataRole.UserRole) if item is not None else None

    def _selected_item(self):
        return self.list_widget.currentItem()

    def _new(self):
        # The guard runs before create_session: with a request in flight the
        # store must not gain an active session the chat cannot show.
        if self._session_change_refused():
            return
        session = self.store.create_session(select=True)
        session_id = session.get("id") if isinstance(session, dict) else session
        if callable(self.on_new):
            self.on_new(session_id)
        self.reload()

    def _session_change_refused(self):
        """Refuse session changes while the chat has a request in flight.

        The chat widget (when reachable through the parent chain) owns the
        pending-request state; this dialog only surfaces the refusal.
        """
        widget = self.parent()
        while widget is not None:
            guard = getattr(widget, "chat", None)
            if guard is not None and hasattr(guard, "request_in_flight"):
                if guard.request_in_flight():
                    from . import i18n
                    QtWidgets.QMessageBox.information(
                        self, i18n._("Conversation History"),
                        i18n._("Wait for the pending answer before changing conversations."))
                    return True
                return False
            widget = widget.parent()
        return False

    def _visible_session_id(self):
        """Return the session the chat currently shows, if reachable."""
        widget = self.parent()
        while widget is not None:
            chat = getattr(widget, "chat", None)
            if chat is not None and getattr(chat, "history_store", None) is not None:
                return chat.history_store.active_session_id
            widget = widget.parent()
        return None

    def _sync_visible_session(self, visible):
        """Reload the chat when the store's active session moved.

        Archiving or deleting the visible session makes the store adopt
        another active session; the chat must follow through the same
        path Open uses, so the log and pending provider context match.
        """
        active = getattr(self.store, "active_session_id", None)
        if visible is None or active == visible:
            return
        if callable(self.on_open):
            self.on_open(active)

    def _open(self):
        session_id = self.selected_session_id()
        if session_id is None:
            return
        if self._session_change_refused():
            return
        try:
            self.store.select_session(session_id)
        except ValueError as error:
            from . import i18n
            QtWidgets.QMessageBox.information(
                self, i18n._("Conversation History"), str(error))
            return
        if callable(self.on_open):
            self.on_open(session_id)
        self.accept()

    def _archive(self):
        """Toggle archive status of the selected session."""
        item = self._selected_item()
        if item is None:
            return
        if self._session_change_refused():
            return
        session_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        is_archived = bool(item.data(QtCore.Qt.ItemDataRole.UserRole + 1))
        visible = self._visible_session_id()
        try:
            if hasattr(self.store, "archive_session"):
                self.store.archive_session(session_id, not is_archived)
            elif hasattr(self.store, "set_archived"):
                self.store.set_archived(session_id, not is_archived)
            else:
                logger.warning("Archive not supported by this history store")
                return
        except Exception as error:
            logger.error("Archive failed: %s", type(error).__name__)
            return
        self._sync_visible_session(visible)
        self.reload()

    def _delete(self):
        """Delete the selected session after confirmation."""
        from . import i18n
        item = self._selected_item()
        if item is None:
            return
        if self._session_change_refused():
            return
        session_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        visible = self._visible_session_id()
        reply = QtWidgets.QMessageBox.question(
            self, i18n._("Delete conversation"),
            i18n._("Delete this conversation? This cannot be undone."),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No)
        if reply != QtWidgets.QMessageBox.StandardButton.Yes:
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
        self._sync_visible_session(visible)
        self.reload()

    def _export(self):
        """Export the selected session to a file."""
        from . import i18n
        item = self._selected_item()
        if item is None:
            return
        session_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, i18n._("Export conversation"),
            "conversation.md", "Markdown (*.md);;JSON (*.json);;Text (*.txt)")
        if not filename:
            return
        try:
            export_session_to_file(self.store, session_id, filename)
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

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok)
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
