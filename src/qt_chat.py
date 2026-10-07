"""Qt chat widget on the shared backends (phase 4b + AI providers).

Hosts the conversation inside the Qt shell using the same OfflineAssistant,
AIClient and i18n used by the GTK track. When an AI provider is configured
(api key present), messages go to the provider; otherwise the offline
assistant answers locally. Provider streaming, sessions and dialogs arrive
in later sub-phases; the offline replies already flow through the exact
same Reply contract as the GTK window.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False

MAX_LOG_CHARS = 131072


def offline_reply_text(offline_assistant, message, lang="en"):
    """Pure send path: run the offline assistant and return its answer.

    Kept Qt-free so the routing contract (including failure handling) is
    testable without PySide6, exactly like the GTK track's decision points.
    """
    message = (message or "").strip()
    if not message:
        return None
    try:
        reply = offline_assistant.handle(message, lang)
        return reply.text if reply is not None else None
    except Exception as error:
        logger.error("Offline assistant failed: %s", type(error).__name__)
        return None


def append_is_bounded(log_chars, chunk):
    """Pure bound decision for the message log."""
    return log_chars + len(chunk) <= MAX_LOG_CHARS


def provider_reply_text(ai_client, messages, lang="en", image_paths=None, cancel_event=None,
                        expert=False, distro=None, query="", context=None):
    """Pure send path: call the AI provider and return its answer.

    Args:
        ai_client: AIClient instance
        messages: List of message dicts
        lang: Language code for system prompt
        image_paths: Optional list of image file paths to attach
        cancel_event: Optional threading.Event; when set, the request is
            aborted via AIClient's AIRequestCancelled (no offline fallback).
        expert: Expert mode flag for the system message
        distro: DistroInfo for the system message (None on Windows)
        query: User query for knowledge context in the system message
        context: System context snapshot for the system message

    Returns (text, error) where error is None on success.
    Error "cancelled" means the user aborted (AIRequestCancelled).
    """
    if ai_client is None:
        return None, "no-client"
    try:
        from .assistant_context import build_system_message
        system_message = build_system_message(
            expert=expert, distro=distro, query=query, lang=lang, context=context)
        full_messages = [system_message] + list(messages)

        # Prepare images if provided
        images: Optional[list] = None
        if image_paths:
            try:
                from .image_attachments import validate_attachment
                images = []
                for path in image_paths:
                    attachment = validate_attachment(path)
                    if attachment:
                        images.append(attachment)
                if not images:
                    images = None
            except Exception as error:
                logger.warning("Image validation failed: %s", type(error).__name__)
                images = None

        response = ai_client.chat(full_messages, images=images, cancel_event=cancel_event)
        if response:
            return response, None
        return None, "empty-response"
    except Exception as error:
        from .ai_client import AIRequestCancelled
        if isinstance(error, AIRequestCancelled):
            logger.info("Provider request cancelled by user")
            return None, "cancelled"
        logger.error("AI provider failed: %s", type(error).__name__)
        return None, type(error).__name__


def should_use_provider(ai_client, config_manager):
    """Decide whether to use the AI provider or the offline assistant.

    Returns True when an AI provider is configured and ready.
    """
    if ai_client is None:
        return False
    try:
        # Check if any provider has an API key configured
        for provider in ("openrouter", "google_ai_studio", "anthropic",
                         "mistral", "groq", "cohere"):
            try:
                key = config_manager.get_api_key(provider)
                if key:
                    return True
            except Exception:
                pass
        # Check local LLM
        try:
            base_url = config_manager.get("api.providers.local_llm.base_url")
            if base_url:
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False


if QT_AVAILABLE:
    _BaseWidget = QtWidgets.QWidget
    _Slot = QtCore.Slot

    class _ProviderWorker(QtCore.QObject):
        """Runs a provider request off the GUI thread and reports via signals.

        Replaces QMetaObject.invokeMethod with string-based slot lookup:
        signals are type-safe and survive method renames.
        """
        finished = QtCore.Signal(str)      # (text)
        failed = QtCore.Signal(str)        # (last_user_message) -> offline fallback
        cancelled = QtCore.Signal(str)     # (last_user_message)

        def run(self, ai_client, messages, lang, image_paths, cancel_event,
                expert=False, distro=None, query="", context=None):
            text, error = provider_reply_text(
                ai_client, messages, lang,
                image_paths=image_paths, cancel_event=cancel_event,
                expert=expert, distro=distro, query=query, context=context)
            if error == "cancelled":
                self.cancelled.emit(messages[-1]["content"] if messages else "")
            elif error:
                self.failed.emit(messages[-1]["content"] if messages else "")
            else:
                self.finished.emit(text or "")
else:
    _BaseWidget = object

    def _Slot(*args, **kwargs):
        """No-op decorator when Qt is unavailable."""
        def decorator(func):
            return func
        return decorator

    class _ProviderWorker:  # type: ignore[no-redef]
        """Stub so module import works without PySide6 (tests skip the class)."""
        pass


class QtChatWidget(_BaseWidget):  # type: ignore[misc, valid-type]
    """Message log plus input line, driven by AI provider or offline assistant."""

    send_requested = QtCore.Signal(str) if QT_AVAILABLE else None
    response_received = QtCore.Signal(str) if QT_AVAILABLE else None

    def __init__(self, config_manager, offline_assistant, parent=None,
                 history_store=None, ai_client=None):
        if not QT_AVAILABLE:
            raise RuntimeError("PySide6 is required for QtChatWidget")
        super().__init__(parent)
        self.config = config_manager
        self.offline = offline_assistant
        self.ai_client = ai_client
        self.history_store = history_store
        self._log_chars = 0
        self._pending_messages = []  # Messages to send to provider (main thread only)
        self._cancel_event = threading.Event()
        self._worker = None
        self._worker_thread = None
        # In-flight request isolation: the session that originated the request
        # and a request id. Responses are always stored in the originating
        # session, even if the user switches, archives or deletes meanwhile.
        self._request_session_id = None
        self._request_serial = 0
        self._build()
        if self.send_requested is not None:
            self.send_requested.connect(self._on_send)
        if self.response_received is not None:
            self.response_received.connect(self._on_response_received)
        self.load_session()

    def _build(self):
        from . import i18n
        layout = QtWidgets.QVBoxLayout(self)

        # Status indicator (shows when AI is thinking)
        self.status_label = QtWidgets.QLabel(self)
        self.status_label.setVisible(False)
        self.status_label.setStyleSheet("color: #888; font-style: italic; padding: 4px;")
        layout.addWidget(self.status_label)

        self.log = QtWidgets.QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4096)
        # Enable drag & drop for images
        self.log.setAcceptDrops(True)
        self.log.dragEnterEvent = self._on_drag_enter
        self.log.dropEvent = self._on_drop
        layout.addWidget(self.log, 1)

        # Attachment preview area (hidden by default)
        self.attachment_area = QtWidgets.QWidget(self)
        self.attachment_layout = QtWidgets.QHBoxLayout(self.attachment_area)
        self.attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachment_area.setVisible(False)
        self._attachments = []  # List of attachment dicts
        layout.addWidget(self.attachment_area)

        # Input row
        row = QtWidgets.QHBoxLayout()

        # Attach button
        self.attach_button = QtWidgets.QPushButton("📎", self)
        self.attach_button.setMaximumWidth(40)
        self.attach_button.setToolTip(i18n._("Attach image"))
        self.attach_button.clicked.connect(self._on_attach_clicked)
        row.addWidget(self.attach_button)

        # Screenshot button (Windows)
        self.screenshot_button = QtWidgets.QPushButton("📷", self)
        self.screenshot_button.setMaximumWidth(40)
        self.screenshot_button.setToolTip(i18n._("Take screenshot"))
        self.screenshot_button.clicked.connect(self._on_screenshot_clicked)
        row.addWidget(self.screenshot_button)

        self.input = QtWidgets.QLineEdit(self)
        self.input.setPlaceholderText(i18n._("Type a message..."))
        self.input.returnPressed.connect(self._on_return)
        self.send_button = QtWidgets.QPushButton(i18n._("Send"), self)
        self.send_button.clicked.connect(self._on_send_clicked)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_button)
        layout.addLayout(row)

        # Provider indicator
        self._update_provider_indicator()

        # Add context menu with conversation actions
        try:
            from .qt_conversation_actions import add_context_menu_to_chat
            add_context_menu_to_chat(self)
        except Exception as error:
            logger.warning("Could not add context menu: %s", type(error).__name__)

    def _on_attach_clicked(self):
        """Open file dialog to attach an image."""
        from . import i18n
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, i18n._("Attach image"), "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All files (*)")
        if filepath:
            self._add_attachment(filepath)

    def _on_screenshot_clicked(self):
        """Take a screenshot and attach it."""
        from .windows_screenshot import capture_and_attach
        result = capture_and_attach(self)
        if result:
            filepath, _data = result
            self._add_attachment(filepath)

    def _on_drag_enter(self, event):
        """Handle drag enter event for images."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def _on_drop(self, event):
        """Handle drop event for images."""
        for url in event.mimeData().urls():
            filepath = url.toLocalFile()
            if self._is_image_file(filepath):
                self._add_attachment(filepath)
        event.acceptProposedAction()

    def _is_image_file(self, filepath):
        """Check if a file is an image."""
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
        return Path(filepath).suffix.lower() in image_extensions

    def _add_attachment(self, filepath):
        """Add an image attachment with preview."""
        from . import i18n
        from pathlib import Path

        path = Path(filepath)
        if not path.is_file():
            return

        # Check if image input is supported
        if not should_use_provider(self.ai_client, self.config):
            QtWidgets.QMessageBox.information(
                self, i18n._("Image attachments"),
                i18n._("Image attachments require an AI provider with vision support."))
            return

        # Create preview widget
        preview = QtWidgets.QWidget(self.attachment_area)
        preview_layout = QtWidgets.QVBoxLayout(preview)
        preview_layout.setContentsMargins(4, 4, 4, 4)

        # Thumbnail
        label = QtWidgets.QLabel(preview)
        pixmap = QtGui.QPixmap(str(path))
        if not pixmap.isNull():
            pixmap = pixmap.scaled(64, 64, QtCore.Qt.KeepAspectRatio,
                                   QtCore.Qt.SmoothTransformation)
            label.setPixmap(pixmap)
        else:
            label.setText("🖼️")
        preview_layout.addWidget(label)

        # Filename
        name_label = QtWidgets.QLabel(path.name[:15], preview)
        name_label.setAlignment(QtCore.Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 9px;")
        preview_layout.addWidget(name_label)

        # Remove button
        remove_btn = QtWidgets.QPushButton("×", preview)
        remove_btn.setMaximumWidth(20)
        remove_btn.setMaximumHeight(20)
        remove_btn.clicked.connect(lambda: self._remove_attachment(preview, filepath))
        preview_layout.addWidget(remove_btn, alignment=QtCore.Qt.AlignRight)

        self.attachment_layout.addWidget(preview)
        self._attachments.append({"path": filepath, "widget": preview})
        self.attachment_area.setVisible(True)

    def _remove_attachment(self, widget, filepath):
        """Remove an attachment."""
        self._attachments = [a for a in self._attachments if a["path"] != filepath]
        widget.deleteLater()
        if not self._attachments:
            self.attachment_area.setVisible(False)

    def _clear_attachments(self):
        """Clear all attachments."""
        for attachment in self._attachments:
            attachment["widget"].deleteLater()
        self._attachments = []
        self.attachment_area.setVisible(False)

    def _update_provider_indicator(self):
        """Show which backend is active (AI provider or offline)."""
        from . import i18n
        if should_use_provider(self.ai_client, self.config):
            self.setWindowTitle(i18n._("AI Provider mode"))
        else:
            self.setWindowTitle(i18n._("Offline mode"))

    def _on_return(self):
        self._on_send()

    def _on_send_clicked(self):
        self._on_send()

    def _on_send(self):
        text = self.input.text().strip()
        if not text and not self._attachments:
            return
        if self._worker_thread is not None and self._worker_thread.is_alive():
            return  # Don't send while waiting for a response
        self.input.clear()
        from . import i18n

        # Build display text with attachment indicators
        display_text = text
        if self._attachments:
            attachment_names = ", ".join(Path(a["path"]).name for a in self._attachments)
            display_text = f"{text}\n[📎 {attachment_names}]" if text else f"[📎 {attachment_names}]"

        self.append_message(i18n._("User"), display_text)

        # Save to history
        if self.history_store is not None:
            try:
                self.history_store.append("user", display_text)
            except Exception as error:
                logger.warning("History write failed: %s", type(error).__name__)

        # Track message for provider context
        self._pending_messages.append({"role": "user", "content": text or "[image]"})
        # Capture the originating session and a request id before dispatching.
        # Every path that stores the answer must honour this pair.
        self._request_serial += 1
        self._request_session_id = self._current_session_id()

        # Show thinking indicator
        self._show_thinking()

        # Decide: AI provider or offline
        if should_use_provider(self.ai_client, self.config):
            self._send_to_provider()
        else:
            self._send_to_offline(text)

        # Clear attachments after sending
        self._clear_attachments()

    def _show_thinking(self):
        from . import i18n
        self.status_label.setText(i18n._("Thinking..."))
        self.status_label.setVisible(True)
        # The send button becomes a Stop button while a request is in flight.
        self.send_button.setText(i18n._("Stop"))
        self.send_button.clicked.disconnect()
        self.send_button.clicked.connect(self._on_stop_clicked)
        self.input.setEnabled(False)

    def _hide_thinking(self):
        from . import i18n
        self.status_label.setVisible(False)
        self.send_button.setText(i18n._("Send"))
        try:
            self.send_button.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.send_button.clicked.connect(self._on_send_clicked)
        self.input.setEnabled(True)
        self.input.setFocus()

    def _on_stop_clicked(self):
        """User pressed Stop: cancel the in-flight provider request."""
        self._cancel_event.set()
        self.status_label.setText("Cancelling...")

    def _send_to_offline(self, text):
        """Send to the offline assistant (synchronous, fast)."""
        from . import i18n
        lang = i18n.get_language() if hasattr(i18n, "get_language") else "en"
        answer = offline_reply_text(self.offline, text, lang) or ""
        self._hide_thinking()
        self._store_response(answer)
        self._pending_messages.append({"role": "assistant", "content": answer})
        self._finish_request()
        self.append_message(i18n._("AI"), answer)
        if self.response_received is not None:
            self.response_received.emit(answer)

    def _send_to_provider(self):
        """Send to the AI provider via a signal-based worker (no invokeMethod).

        The message list is snapshotted (immutable copy) before the worker
        starts, so later sends on the main thread cannot race the worker.
        """
        if not QT_AVAILABLE:
            return
        from . import i18n
        lang = i18n.get_language() if hasattr(i18n, "get_language") else "en"
        # Immutable snapshot: the worker reads this, the main thread keeps
        # appending to self._pending_messages for the next turn.
        messages = list(self._pending_messages)
        # Capture attachment paths (they are cleared after send)
        attachment_paths = [a["path"] for a in self._attachments]

        self._cancel_event.clear()
        self._worker = _ProviderWorker()
        self._worker.finished.connect(self._on_provider_response)
        self._worker.failed.connect(self._on_provider_failed)
        self._worker.cancelled.connect(self._on_provider_cancelled)
        # Capture context for the system message (parity with GTK track)
        try:
            expert = bool(self.config.get("app.expert_mode", False))
        except Exception:
            expert = False
        distro = getattr(self.offline, "distro", None)
        context = getattr(self.offline, "system_context", None)
        query = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                query = message.get("content", "")
                break
        self._worker_thread = threading.Thread(
            target=self._worker.run,
            args=(self.ai_client, messages, lang,
                  attachment_paths if attachment_paths else None,
                  self._cancel_event),
            kwargs={"expert": expert, "distro": distro,
                    "query": query, "context": context},
            daemon=True,
            name="provider-request",
        )
        self._worker_thread.start()

    @_Slot(str)
    def _on_provider_response(self, text):
        """Handle provider response (delivered by the worker's finished signal)."""
        from . import i18n
        self._hide_thinking()
        # The answer is stored in the session that originated the request;
        # the visible log only advances when that session is still shown.
        self._store_response(text)
        if self._request_session_is_selected():
            self._pending_messages.append({"role": "assistant", "content": text})
            self.append_message(i18n._("AI"), text)
            if self.response_received is not None:
                self.response_received.emit(text)
            # Offer to write any ``` file blocks in the reply (expert mode only)
            self._offer_file_blocks(text)
        self._finish_request()

    @_Slot(str)
    def _on_provider_failed(self, last_user_message):
        """Provider failed: fall back to the offline assistant (signal-based)."""
        from . import i18n
        lang = i18n.get_language() if hasattr(i18n, "get_language") else "en"
        answer = offline_reply_text(self.offline, last_user_message, lang) or ""
        self._hide_thinking()
        self._store_response(answer)
        if self._request_session_is_selected():
            self._pending_messages.append({"role": "assistant", "content": answer})
            self.append_message(i18n._("AI"), answer + "\n\n(Provider unavailable, answered offline)")
        self._finish_request()

    @_Slot(str)
    def _on_provider_cancelled(self, last_user_message):
        """User cancelled the in-flight provider request."""
        from . import i18n
        self._hide_thinking()
        # A cancelled request stores no answer in any session.
        if self._request_session_is_selected():
            self.append_message(i18n._("System"), i18n._("Request cancelled."))
            self._pending_messages.append(
                {"role": "system", "content": "Request cancelled by user."})
        self._finish_request()

    def _current_session_id(self):
        """The history session that a send right now belongs to."""
        if self.history_store is None:
            return None
        try:
            # HistoryStore.active_session_id is a property.
            return self.history_store.active_session_id
        except Exception:
            return None

    def _store_response(self, answer):
        """Store an assistant answer in the session that originated the request.

        The captured session id is used explicitly: even if the user switched,
        archived or deleted the conversation meanwhile, the answer lands in
        the conversation that asked the question, or nowhere when that
        conversation no longer exists.
        """
        session_id = self._request_session_id
        if self.history_store is None or session_id is None:
            return
        try:
            sessions = self.history_store.list_sessions(include_archived=True)
        except Exception as error:
            logger.warning("History read failed: %s", type(error).__name__)
            return
        if not any(session["id"] == session_id for session in sessions):
            # The originating session disappeared; drop the pending state and
            # let the visible line below explain where the answer went.
            self._request_session_id = None
            return
        try:
            self.history_store.append("assistant", answer, session_id=session_id)
        except Exception as error:
            logger.warning("History write failed: %s", type(error).__name__)

    def _request_session_is_selected(self):
        """True when the originating session is still the one being shown."""
        return (self._request_session_id is not None
                and self._request_session_id == self._current_session_id())

    def _finish_request(self):
        """Clear the in-flight request state after a response settles."""
        self._request_session_id = None

    def request_in_flight(self):
        """True while a provider request is pending (Stop button active)."""
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _session_action_allowed(self):
        """New/Open/Archive/Delete are refused while a request is in flight.

        Chosen contract: the actions are refused instead of queued, and the
        refusal is visible, so the answer always lands in the conversation
        that originated it and no background write can race a session
        switch. The guard is advisory for callers (menus/dialogs); the
        store itself still routes by captured session id.
        """
        return not self.request_in_flight()

    def _expert_mode_enabled(self):
        try:
            return bool(self.config.get("app.expert_mode", False))
        except Exception:
            return False

    def _allowed_edit_dirs(self):
        try:
            dirs = self.config.get("permissions.allowed_edit_dirs", [])
            return list(dirs) if isinstance(dirs, list) else []
        except Exception:
            return []

    def _offer_file_blocks(self, reply_text):
        """Detect ``` file blocks in an AI reply and offer to write them (Qt).

        Mirrors the GTK track (file_actions.offer_file_blocks_async): only in
        expert mode, at most 3 blocks, each confirmed via a Qt dialog and
        written through WindowsFileActions (path validation + backup + atomic).
        """
        from . import i18n
        from .render_core import FileBlock
        from .windows_file_actions import WindowsFileActions, preview_diff
        from .qt_file_dialogs import confirm_file_write_qt

        if not self._expert_mode_enabled():
            return
        blocks = FileBlock.parse_all(reply_text)
        if not blocks or len(blocks) > 3:
            return
        actions = WindowsFileActions(allowed_dirs=self._allowed_edit_dirs())
        for block in blocks:
            if not actions.is_allowed(block.path):
                self.append_message(
                    i18n._("System"),
                    i18n._("Path not allowed: {path}").format(path=block.path))
                continue
            diff = preview_diff(block.path, block.content)
            content = diff if diff is not None else block.content
            confirmed = confirm_file_write_qt(self, block.path, content, is_new=diff is None)
            if not confirmed:
                self.append_message(
                    i18n._("System"),
                    i18n._("File write cancelled: {path}").format(path=block.path))
                continue
            status, msg = actions.write_file(block.path, block.content)
            if status == "written":
                self.append_message(
                    i18n._("System"),
                    i18n._("File written: {path}").format(path=block.path))
            else:
                self.append_message(
                    i18n._("System"),
                    i18n._("Error writing file: {detail}").format(detail=msg))

    def _on_response_received(self, text):
        """Slot for response_received signal."""
        pass

    def load_session(self, session_id=None):
        """Render the active (or given) session's stored messages."""
        if self.history_store is None:
            return
        if not self._session_action_allowed():
            from . import i18n
            self.append_message(
                i18n._("System"),
                i18n._("Wait for the pending answer before switching conversations."))
            return
        try:
            entries = self.history_store.load_messages(session_id)
        except Exception as error:
            logger.warning("History read failed: %s", type(error).__name__)
            return
        self.log.clear()
        self._log_chars = 0
        self._pending_messages = []
        from . import i18n
        labels = {"user": i18n._("User"), "assistant": i18n._("AI"),
                  "system": i18n._("System")}
        for entry in entries:
            role = entry.get("role", "")
            content = entry.get("content", "")
            label = labels.get(role, role or "?")
            self.append_message(label, content)
            # Rebuild pending messages for provider context
            if role in ("user", "assistant"):
                self._pending_messages.append({"role": role, "content": content})

    def append_message(self, label, text):
        chunk = "{}: {}\n".format(label, text)
        if not append_is_bounded(self._log_chars, chunk):
            return
        self._log_chars += len(chunk)
        self.log.appendPlainText(chunk.rstrip("\n"))
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    @_Slot(str)
    def append_system_message(self, text):
        """Append a system message (thread-safe: usable via invokeMethod)."""
        from . import i18n
        self.append_message(i18n._("System"), text)

    def clear_conversation(self):
        """Clear the current conversation (new session)."""
        if not self._session_action_allowed():
            from . import i18n
            self.append_message(
                i18n._("System"),
                i18n._("Wait for the pending answer before starting a new conversation."))
            return
        if self.history_store is not None:
            try:
                self.history_store.create_session(select=True)
            except Exception as error:
                logger.warning("Could not create new session: %s", type(error).__name__)
        self.log.clear()
        self._log_chars = 0
        self._pending_messages = []
