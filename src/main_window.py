import gi
import threading
from typing import Optional, Dict

try:
    import notify2
except ImportError:
    notify2 = None

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')

from gi.repository import Gtk, GLib
import logging

from . import device_dialogs, dock, offline_assistant
from .ai_client import AIClient, AIProviderError, AIImageRequestError
from .history_store import MAX_HISTORY_MESSAGES
from .i18n import _, get_language
from .assistant_context import build_system_message
from .conversation_dialog import show_conversations
from .provider_settings import MODE_LABELS, STATUS_LABELS
from .main_window_theme_dialogs import (
    add_theme_dialog,
    populate_themes,
    remove_theme_dialog,
    show_theme_settings,
)
from .main_window_dialogs import (
    confirm_display_change,
    show_action_audit,
    show_stats_dialog,
)
from .main_window_capture import (
    capture_screen,
    on_capture_complete,
    review_captured_image,
)
from .main_window_ui import build_style, build_ui, setup_keybindings, show_menu
from .main_window_offline import (
    finish_offline_commands,
    offer_offline_commands,
    record_offline_result,
    run_offline_commands,
)
from .main_window_chat_flow import finalize_response, process_message, send_message
from .main_window_settings import show_settings_dialog
from .document_store import DocumentStore
from .image_dialog import pick_image, review_image

# Set up logger
logger = logging.getLogger(__name__)

from .chat_core import limit_context, request_budget
from .main_window_bootstrap import initialize_window


class MainWindow(Gtk.Window):
    """Application main window"""

    dock_method: Optional[str]
    expert_mode: bool
    _document_store: Optional[DocumentStore]
    _cancel_event: threading.Event

    def __init__(self, app, config_manager, ai_client, system_utils, history_store=None):
        super().__init__(title="Linux AI Assistant")
        initialize_window(self, app, config_manager, ai_client, system_utils, history_store)


    def _setup_notifications(self):
        """Configure system notifications"""
        self.notifications_enabled = False
        try:
            if notify2 is not None:
                notify2.init("Linux AI Assistant")
                self.notifications_enabled = True
                logger.info("System notifications enabled")
        except Exception as e:
            logger.warning(f"Could not enable notifications: {e}")

    def _on_realize_dock(self, widget):
        """Apply dock struts once the GdkWindow exists (X11 needs it)."""
        if self.dock_method == "layer-shell":
            return  # already applied pre-realize on Wayland
        self.dock_method = dock.apply_dock(self, self._dock_edge, self._dock_width)
        logger.info(f"Dock applied via {self.dock_method}")

    def _reapply_dock(self):
        """Re-apply dock/float settings after they change in the dialog."""
        mode = self.config.get("app.dock_mode", "float")
        self._dock_edge = self.config.get("app.dock_edge", "right")
        self._dock_width = self.config.get("app.width", 400)
        if mode == "dock":
            self.set_decorated(False)
            if self.get_realized():
                self.dock_method = dock.apply_dock(self, self._dock_edge, self._dock_width)
                logger.info(f"Dock re-applied via {self.dock_method}")
            # otherwise _on_realize_dock will handle it
        else:
            self.set_decorated(True)
            dock.apply_float(self, self.config.get("app.always_on_top", True))
            self.dock_method = None
            logger.info("Dock removed (floating mode)")

    def _apply_feature_toggles(self):
        """Show/hide the feature buttons according to features.* settings."""
        if hasattr(self, "capture_btn"):
            self.capture_btn.set_no_show_all(True)
            self.capture_btn.set_visible(self.config.get("features.screen_capture", True))
        if hasattr(self, "expert_btn"):
            self.expert_btn.set_no_show_all(True)
            self.expert_btn.set_visible(self.config.get("features.expert_mode", True))

    def close_history_writer(self, timeout=None):
        """Flush pending history writes and stop the writer thread."""
        event = getattr(self, '_cancel_event', None)
        self._audit_closed = True
        if getattr(self, '_history_watch_source', None) is not None:
            self._stop_history_watch()
        for controller in getattr(self, '_file_action_controllers', ()):
            controller.cancel()
        if event is not None:
            event.set()
        actions = getattr(self, 'actions', None)
        if actions is not None:
            actions.close()
        document_store = getattr(self, '_document_store', None)
        if document_store is not None:
            document_store.close()
        if not self.history_store.close(timeout):
            logger.error("History writer did not finish successfully: %s", self.history_store.last_error)

    def show_notification(self, title: str, message: str, icon: str = "dialog-information"):
        """Show system notification"""
        if self.notifications_enabled and notify2 is not None:
            try:
                n = notify2.Notification(title, message, icon)
                n.show()
                logger.debug(f"Notification shown: {title}")
            except Exception as e:
                logger.error(f"Error showing notification: {e}")

    def _setup_keybindings(self):
        """Set up keyboard shortcuts"""
        setup_keybindings(self)


    def on_clear_input(self, *args):
        """Clear input when Escape is pressed"""
        self.input_entry.set_text("")
        logger.debug("Input cleared")

    def _setup_style(self):
        """Set up window CSS styling"""
        build_style(self)


    def _create_ui(self):
        """Create the window interface"""
        build_ui(self)


    def on_menu_clicked(self, button):
        """Show options menu"""
        show_menu(self, button)


    def on_config_clicked(self, item):
        """Open settings window"""
        self._show_config_dialog()

    def _get_document_store(self):
        if self._document_store is None:
            self._document_store = DocumentStore()
        return self._document_store

    def on_documents_clicked(self, button=None):
        from .document_dialog import DocumentDialog
        try:
            dialog = DocumentDialog(self, self._get_document_store())
            try:
                dialog.show_all()
                dialog.run()
            finally:
                dialog.destroy()
        except (OSError, ValueError) as error:
            self._add_system_message(_("Could not open documents: {error}").format(error=error))

    def _clear_pending_image(self):
        self._pending_image = None
        self._pending_image_destination = None
        label = getattr(self, 'attachment_label', None)
        if label is not None:
            label.set_text('')
        button = getattr(self, 'remove_image_button', None)
        if button is not None:
            button.hide()

    def _review_and_attach_image(self, image):
        try:
            if not isinstance(self.ai_client, AIClient):
                raise AIImageRequestError(_("This client does not support reviewed images."))
            provider, model = self.ai_client.validate_image_request((image,))
            if review_image(self, image, provider, model):
                self._pending_image = image
                self._pending_image_destination = (provider, model)
                self.attachment_label.set_text(_("Image ready for the next question: {name} ({width} × {height})")
                                               .format(name=image.filename, width=image.width, height=image.height))
                self.remove_image_button.show()
        except (OSError, ValueError, AIProviderError) as error:
            self._add_system_message(_("Could not attach image: {error}").format(error=error))
        return False

    def on_attach_image_clicked(self, button=None):
        if self.is_loading:
            self._add_system_message(_("Wait for the current message to be processed"))
            return
        try:
            image = pick_image(self)
            if image is not None:
                self._review_and_attach_image(image)
        except (OSError, ValueError) as error:
            self._add_system_message(_("Could not attach image: {error}").format(error=error))

    def on_themes_clicked(self, button):
        """Open the settings dialog on the Themes tab."""
        show_theme_settings(self, button)

    def on_add_theme_clicked(self, button):
        """Add a new theme"""
        add_theme_dialog(self, button)

    def on_remove_theme_clicked(self, button):
        """Remove the selected theme"""
        remove_theme_dialog(self, button)

    def _populate_themes_list(self):
        """Populate the themes list (delegates to main_window_themes)."""
        populate_themes(self)


    def on_history_clicked(self, item):
        """Show conversation history"""
        self._show_history_dialog()

    def on_stats_clicked(self, item):
        """Show usage statistics"""
        self._show_stats_dialog()

    def _show_stats_dialog(self):
        """Show statistics dialog"""
        show_stats_dialog(self)


    def _show_history_dialog(self):
        show_conversations(self)

    def _show_config_dialog(self):
        """Show settings dialog"""
        show_settings_dialog(self)

    def toggle_visibility(self):
        """Alterna a visibilidade da janela e sincroniza o estado visível.

        Ponto ÚNICO do toggle (tray, botão flutuante): sem isto, o label da
        tray dessincronizava (update_toggle_label nunca era chamado pelos
        outros caminhos).
        """
        if self.get_visible():
            self.hide()
        else:
            self.show_all()
            self.present()
        self.sync_visibility()
        logger.debug("Window visibility toggled: visible=%s", self.get_visible())

    def sync_visibility(self):
        """Repõe o label do menu da tray em coerência com a janela."""
        tray = getattr(self.app, "tray_icon", None)
        if tray is not None:
            tray.update_toggle_label(self.get_visible())

    # ---- Delegações ao ChatView (buffer/tags/offsets/placeholder) ----
    # A mecânica de inserção vive em src/chat_view.py; aqui ficam apenas as
    # DECISÕES (o que mostrar, quando persistir).

    def _add_user_message(self, message: str):
        """Add a user message to the chat (apenas UI; persistência via _remember)"""
        if not message:
            return

        self.chat_view.append_message(_('User'), message, "user-message")
        self.chat_view.scroll_to_bottom()
        logger.debug(f"User message added: {message[:50]}...")

    def _add_ai_message(self, message: str, streaming: bool = False):
        """Add an AI message to the chat"""
        if self._cancel_event.is_set():
            return

        if streaming and self.streaming:
            self.chat_view.insert_stream_chunk(message)
            self.chat_view.scroll_to_bottom()
        else:
            self.chat_view.body_start = None
            self.chat_view.append_message(_('AI'), message, "ai-message")
            self.chat_view.scroll_to_bottom()

        logger.debug(f"AI message added: {message[:50]}...")

    def _add_system_message(self, message: str):
        """Add a system message to the chat"""
        self.chat_view.append_message(_('System'), message, "system-message")
        self.chat_view.scroll_to_bottom()
        logger.debug(f"System message: {message}")

    def _add_loading_message(self, request_id=None, cancel_event=None):
        """Add a loading message (delegado ao ChatView, com guarda de pedido:
        um idle de um worker cancelado não pode inserir um "Thinking..."
        que ninguém remove — placeholder fantasma)."""
        self.chat_view.show_loading(
            request_id=request_id,
            is_active=lambda rid: rid == self._active_request,
            cancelled=(cancel_event.is_set if cancel_event is not None else None),
        )

    def _remove_loading_message(self):
        """Remove ONLY the loading placeholder."""
        self.chat_view.clear_loading()

    def _scroll_to_bottom(self):
        self.chat_view.scroll_to_bottom()

    def _load_conversation_history(self):
        self.offline.restore_diagnostic(self.history_store.get_diagnostic_state())
        self.conversation_history = self.history_store.load_messages()
        self.chat_view.abort_stream()
        self.chat_view.buffer.set_text('')
        if len(self.conversation_history) > 100:
            self._add_system_message(_("Showing the latest 100 messages. Export to view the full conversation."))
        for message in self.conversation_history[-100:]:
            if message['role'] == 'user':
                self._add_user_message(message['content'])
            else:
                self._add_ai_message(message['content'])

    def _refresh_session_controls(self):
        self._refreshing_sessions = True
        try:
            self.session_combo.remove_all()
            for session in self.history_store.list_sessions():
                self.session_combo.append(session['id'], session['title'])
            self.session_combo.set_active_id(self.history_store.active_session_id)
        except (OSError, ValueError) as error:
            self._show_history_warning(error)
        finally:
            self._refreshing_sessions = False

    def _show_history_warning(self, error=None):
        if error is not None:
            logger.error("Conversation history needs attention: %s", error)
        warning = getattr(self, 'history_warning', None)
        if warning is not None:
            warning.show()

    def _check_history_writer(self):
        if getattr(self, '_audit_closed', False):
            return False
        if self.history_store.last_error is not None:
            self._show_history_warning()
        return True

    def _stop_history_watch(self, *args):
        source = getattr(self, '_history_watch_source', None)
        if source is not None:
            GLib.source_remove(source)
            self._history_watch_source = None

    def _recover_history(self, *args):
        if getattr(self, '_history_recovering', False):
            return
        if (any(controller.active for controller in getattr(self, '_file_action_controllers', ()))
                or getattr(self, '_file_recovery_active', False)):
            self._add_system_message(_("Wait for the approved file operation to finish before recovering history."))
            return
        from .history_recovery import recover_history
        self._history_recovering = True
        try:
            # A reply already in flight must not append after the replacement
            # history has become a new conversation.
            self._cancel_for_session_change()
            result = recover_history(self, self.history_store, self.history_store.last_error)
            if getattr(getattr(self, 'app', None), '_shutdown_pending', False):
                return
            if result.status == 'recovered':
                self._renew_offline_assistant()
                self._load_conversation_history()
                self._refresh_session_controls()
                self.history_warning.hide()
                self._add_system_message(_("History recovered. Original backup: {path}").format(path=result.backup))
            elif result.status == 'failed':
                self._show_history_warning(result.error)
        except (OSError, ValueError, RuntimeError) as error:
            self._show_history_warning(error)
            self._add_system_message(_("Could not recover history: {error}").format(error=error))
        finally:
            self._history_recovering = False

    def _refresh_mode_status(self):
        status = self.ai_client.provider_status()
        label = _(MODE_LABELS.get(status.mode, status.mode))
        detail = _(STATUS_LABELS.get(status.state, status.state))
        self.mode_label.set_text('{} — {}'.format(label, detail))
        self.status_icon.set_tooltip_text(detail)

    def _cancel_for_session_change(self):
        self._cancel_event.set()
        self._request_seq += 1
        self._active_request = self._request_seq
        # Workers retain the cancelled event they were given. A fresh event
        # lets the selected/recovered conversation render its stored replies.
        self._cancel_event = threading.Event()
        self.is_loading = self.streaming = False
        self.cancel_btn.set_sensitive(False)
        self.chat_view.abort_stream()
        self.chat_view.clear_loading()
        self._clear_pending_image()
        documents_check = getattr(self, 'documents_check', None)
        if documents_check is not None:
            documents_check.set_active(False)
        self.status_icon.set_from_icon_name('object-select-symbolic', Gtk.IconSize.MENU)
        self._renew_offline_assistant()
        self._refresh_mode_status()

    def _renew_offline_assistant(self):
        self.offline = offline_assistant.OfflineAssistant(self.system_utils, self.config)
        try:
            self.offline.restore_diagnostic(self.history_store.get_diagnostic_state())
        except (OSError, ValueError) as error:
            self._show_history_warning(error)

    def _switch_session(self, identifier):
        self._cancel_for_session_change()
        self.history_store.select_session(identifier)
        # A cancelled worker keeps its own assistant; it cannot alter the next session's diagnostic.
        self._renew_offline_assistant()
        self._load_conversation_history()
        self._refresh_session_controls()
        self._refresh_mode_status()

    def _on_session_selected(self, combo):
        identifier = combo.get_active_id()
        if (not self._refreshing_sessions and identifier
                and identifier != self.history_store.active_session_id):
            try:
                self._switch_session(identifier)
            except (OSError, ValueError, KeyError) as error:
                self._add_system_message(str(error))
                self._refresh_session_controls()

    def _new_conversation(self, button=None):
        try:
            session = self.history_store.create_session(_("New conversation"), select=False)
            self._switch_session(session['id'])
        except (OSError, ValueError) as error:
            self._add_system_message(str(error))

    def _build_request_messages(self):
        """Build the message list for the API.

        It removes `timestamp` (which only exists in the on-disk history) and
        limits the context to the configured budget, so a long conversation
        does not send 1000 messages on every turn.
        """
        messages = [{"role": m["role"], "content": m["content"]}
                    for m in self.conversation_history
                    if m.get("role") and m.get("content")]

        max_messages, max_chars = request_budget(self.config)
        bounded = limit_context(messages, max_messages, max_chars)
        if len(bounded) != len(messages):
            logger.debug(
                "Context truncated from %s to %s messages", len(messages), len(bounded)
            )
        return bounded

    def _save_message_to_history(self, role: str, content: str):
        """Enfileira a mensagem no HistoryStore (writer background)."""
        self.history_store.append(role, content)

    def _remember(self, role: str, content: str):
        """Registar uma mensagem no contexto em memória E no history.json.

        Ponto ÚNICO de persistência de mensagens (o duplo save offline
        vinha de dois caminhos a gravar o mesmo turno). O contexto em
        memória tem o mesmo teto de 1000 mensagens do writer, para sessões
        longas não reterem memória ilimitada.
        """
        # Validate/enqueue first. A rejected history entry must not leave an
        # apparently saved message in the context of the next request.
        self._save_message_to_history(role, content)
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > MAX_HISTORY_MESSAGES:
            del self.conversation_history[:-MAX_HISTORY_MESSAGES]

    def _get_context_message(self) -> Optional[Dict[str, str]]:
        query = next((item['content'] for item in reversed(self.conversation_history)
                      if item['role'] == 'user'), '')
        return build_system_message(self.expert_mode, self.offline.distro, query, get_language(), getattr(self, 'system_context', None))

    def _get_system_info_for_context(self) -> str:
        """Get system information for context."""
        try:
            info = self.system_utils.get_system_info()
            lines = [
                f"System: {info.get('distro', 'Unknown')}",
                f"Kernel: {info.get('release', 'Unknown')}",
                f"Architecture: {info.get('machine', 'Unknown')}",
                f"Memory: {info.get('memory_used', 'N/A')} used of {info.get('memory_total', 'N/A')}",
                f"CPU: {info.get('cpu_cores', 'N/A')} cores",
            ]
            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.warning(f"Error getting system info for context: {e}")
            return ""

    def on_input_activate(self, entry):
        """Handler for Enter no input"""
        self.on_send_clicked()

    def on_send_clicked(self):
        """Handler for send button click"""
        send_message(self)


    def _process_message(self, message: str, full_history: list,
                         request_id: int, cancel_event: threading.Event, offline=None, route=None,
                         session_id=None, images=(), document_context=''):
        """Process the message and get the AI response.

        All UI/history mutations are queued to the main loop with
        `request_id`, so output from a superseded or cancelled request is
        dropped instead of corrupting the next turn.
        """
        process_message(self, message, full_history, request_id, cancel_event,
                        offline, route, session_id, images, document_context)


    def _complete_action_reply(self, request_id, cancel_event, reply, session_id):
        """Record a local task without interpreting its output as model code."""
        if request_id != self._active_request or cancel_event.is_set():
            if reply.executed:
                self._record_offline_result(request_id, reply.text, session_id)
            if reply.change is not None:
                self._finish_display_change(reply.change, False, request_id, session_id)
            return False
        self.streaming = False
        self.chat_view.abort_stream()
        try:
            self._add_ai_message(reply.text, False)
            self._remember('assistant', reply.text)
        except (OSError, ValueError, RuntimeError) as error:
            self._add_system_message(_("Could not save the response: {error}").format(error=error))
        finally:
            self._on_message_processed(request_id)
        if reply.change is not None:
            self._confirm_display_change(reply.change, request_id, cancel_event, session_id)
        return False

    def _show_action_audit(self, button=None):
        show_action_audit(self)


    def _finish_display_change(self, change, keep, request_id, session_id):
        def finish():
            ok, detail = change.confirm() if keep else change.revert()
            GLib.idle_add(self._record_offline_result, request_id, detail, session_id)
        threading.Thread(target=finish, daemon=False).start()

    def _confirm_display_change(self, change, request_id, cancel_event, session_id):
        confirm_display_change(self, change, request_id, cancel_event, session_id)


    def _abort_ai_stream_if_active(self, request_id):
        if request_id == self._active_request:
            self.chat_view.abort_stream()
        return False

    def _replace_ai_reply(self, request_id, cancel_event, response_text):
        if request_id != self._active_request or cancel_event.is_set():
            return False
        self.chat_view.abort_stream()
        self._add_system_message(_("Offline mode: answering from local knowledge."))
        self._add_ai_message(response_text, False)
        return False

    def _add_system_message_if_active(self, request_id, cancel_event, text):
        """_add_system_message com guarda de pedido (para callbacks idle).

        Sem a guarda, o aviso/erro de um pedido antigo podia aparecer a meio
        de uma conversa nova; os restantes outputs do pipeline já tinham
        guarda, estes não.
        """
        if request_id != self._active_request or cancel_event.is_set():
            return False
        self._add_system_message(text)
        return False

    def _offer_confirmed_action(self, interaction, commands, request_id, cancel_event):
        """Confirm a catalog action after the reply is on screen.

        A device chooser owns its own command list: the generic dialog must
        not also open, or a scanner install would be offered before the scan.
        """
        if request_id != self._active_request or cancel_event.is_set():
            return False
        if interaction:
            self._start_device_choice(interaction, commands, request_id, cancel_event)
            return False
        if commands:
            return self._offer_offline_commands(commands, request_id, cancel_event)
        return False

    def _start_device_choice(self, kind, commands, request_id, cancel_event):
        """Look up devices on a worker, then let the user pick on this thread."""
        store = getattr(self, "history_store", None)
        session_id = store.active_session_id if store is not None else None
        looking = {
            "wifi": _("Looking up Wi-Fi networks…"),
            "printer": _("Looking up printers…"),
            "scanner": _("Looking up scanners…"),
        }.get(kind)
        if looking:
            self._add_system_message(looking)

        def still_current():
            return request_id == self._active_request and not cancel_event.is_set()

        def report(text):
            # `text` is already redacted. The password never reaches history.
            GLib.idle_add(self._record_offline_result, request_id, text, session_id)

        device_dialogs.start(self, kind, commands, report, still_current)

    def _offer_offline_commands(self, commands, request_id, cancel_event):
        """Ask for confirmation before running privileged offline commands."""
        return offer_offline_commands(self, commands, request_id, cancel_event)


    def _run_offline_commands(self, commands, request_id, cancel_event, session_id=None):
        """Run the confirmed commands via pkexec (worker thread)."""
        return run_offline_commands(self, commands, request_id, cancel_event, session_id)


    def _finish_offline_commands(self, request_id, cancel_event):
        return finish_offline_commands(self, request_id, cancel_event)


    def _record_offline_result(self, request_id, result, session_id=None):
        """Show a command result and keep it in the conversation context."""
        return record_offline_result(self, request_id, result, session_id)


    def _record_file_action_result(self, session_id, status, message):
        """Retain the outcome of an approved operation in its own conversation."""
        if status == 'writing':
            if not getattr(self, '_audit_closed', False) and session_id == self.history_store.active_session_id:
                self._add_system_message(message)
            return False
        if status not in ('written', 'restored', 'error'):
            return False
        store = self.history_store
        current = session_id == store.active_session_id
        if not getattr(self, '_audit_closed', False):
            if current:
                self._add_system_message(message)
            else:
                self._add_system_message(_("File operation completed in another conversation: {message}").format(message=message))
        try:
            if current and not getattr(self, '_audit_closed', False):
                self._remember('assistant', message)
            else:
                store.append('assistant', message, session_id=session_id)
        except (OSError, ValueError, RuntimeError) as error:
            logger.error("Could not save the file operation result: %s", error)
            if not getattr(self, '_audit_closed', False):
                self._show_history_warning(error)
        return False

    def _finalize_response(self, request_id: int, response_text: str,
                           cancelled: bool, allow_file_actions=True, history_text=None):
        """Persist the response and settle the UI (main loop only)."""
        return finalize_response(self, request_id, response_text, cancelled,
                                 allow_file_actions, history_text)


    def _finish_local_document_reply(self, request_id, cancel_event, text):
        if request_id != self._active_request or cancel_event.is_set():
            self._on_message_processed(request_id, True)
            return False
        # Replace any partial provider output with the actual local excerpts.
        # Unapproved local source text must not travel later via chat history.
        visible = text + '\n\n' + _("These local excerpts are not saved in conversation history.")
        self.chat_view.abort_stream()
        self._add_ai_message(visible, False)
        summary = _("Local document matches were shown. Excerpts remain only in the local document index.")
        return self._finalize_response(request_id, visible, False, False, summary)

    def _update_ai_message(self, request_id: int, chunk: str, streaming: bool):
        """Update the AI message, ignoring output from stale requests."""
        if request_id != self._active_request or self._cancel_event.is_set():
            # Pedido antigo ou cancelado: chunks em fila de idle não podem
            # ser despejados no chat como uma mensagem nova avulsa.
            logger.debug("Dropping chunk from stale/cancelled request %s", request_id)
            return False
        self._add_ai_message(chunk, streaming)
        return False

    def _on_message_processed(self, request_id=None, cancelled=False):
        """Callback when the message is processed."""
        if request_id is not None and request_id != self._active_request:
            return False

        self.is_loading = False
        self.cancel_btn.set_sensitive(False)

        # Remove the loading message (no-op if already replaced by the response)
        self._remove_loading_message()

        if cancelled:
            # on_cancel_streaming already painted the cancelled state.
            return False

        self.status_icon.set_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
        self.status_icon.set_tooltip_text(_("Ready"))

        # Show a notification if the window is not active. `is-active` is a
        # Gtk.Window property (GdkWindow does not have it).
        if not self.get_property("is-active"):
            self.show_notification("Linux AI Assistant", _("New response received"))
        return False

    def on_cancel_streaming(self, button):
        """Cancel the current streaming."""
        self._cancel_event.set()
        local_running = getattr(self, '_local_running_request', None) == self._active_request
        self.is_loading = local_running
        self.streaming = False
        self.cancel_btn.set_sensitive(False)
        self.status_icon.set_from_icon_name("dialog-error-symbolic", Gtk.IconSize.MENU)
        self.status_icon.set_tooltip_text(_("Cancelled"))

        self.chat_view.abort_stream()
        if getattr(self, 'history_store', None) is not None:
            self._renew_offline_assistant()
        if local_running:
            self._add_system_message(_("Cancellation requested. An operation already started may still finish; its result will be shown here."))
        else:
            self._add_system_message(_("Streaming cancelled"))
        logger.info("Streaming cancelled by the user")

    def on_capture_screen_clicked(self, button, for_ai=False):
        """Handler for screen capture"""
        capture_screen(self, button, for_ai)


    def _review_captured_image(self, image, request_id, session_id, cancel_event=None):
        review_captured_image(self, image, request_id, session_id, cancel_event)


    def _on_capture_complete(self, request_id=None, session_id=None, cancel_event=None):
        """Callback when the capture is completed."""
        on_capture_complete(self, request_id, session_id, cancel_event)


    def on_expert_mode_toggled(self, button):
        """Toggle expert mode."""
        self.expert_mode = not self.expert_mode
        # Persist: the mode used to reset to normal on every restart.
        self.config.set("app.expert_mode", self.expert_mode)

        if self.expert_mode:
            self.expert_btn.get_style_context().add_class("expert")
            self._add_system_message(_("Expert Mode ENABLED - Helping with system configuration"))
            self.show_notification("Linux AI Assistant", _("Expert Mode enabled"))
        else:
            self.expert_btn.get_style_context().remove_class("expert")
            self._add_system_message(_("Expert Mode DISABLED"))
            self.show_notification("Linux AI Assistant", _("Expert Mode disabled"))

        # Expertise changes the prompt; conversation boundaries are explicit sessions.
        # Keep the tray menu checkbox in sync (it may have been the source,
        # or the window button may have been)
        tray = getattr(self.app, "tray_icon", None)
        if tray is not None:
            tray.update_expert_mode(self.expert_mode)
        logger.info(f"Expert mode {'enabled' if self.expert_mode else 'disabled'}")

    def on_close_clicked(self):
        """Handler for closing the window."""
        return self.on_delete_event(None, None)

    def on_delete_event(self, widget, event):
        """Handler for closing the window."""
        # Save the window geometry. `GdkWindow.get_geometry()` returns the
        # client-side rect but its position is relative to the parent, and
        # `get_position()` on the GdkWindow is not reliable before the window
        # is mapped; Gtk.Window's accessors return absolute coordinates.
        try:
            x, y = self.get_position()
            width, height = self.get_size()
            self.config.set_window_geometry(width, height, x, y)
        except Exception as e:
            logger.warning(f"Could not save window geometry: {e}")
        # Persistir qualquer alteracao pendente antes de sair
        self.config.flush()
        # Drain the history writer so the last messages reach history.json
        self.close_history_writer()

        # Close application (quit() destroys windows and stops the main loop,
        # so it also covers quitting from the tray menu).
        logger.info("Janela fechada")
        self.app.quit()
        return True

    def on_configure_event(self, widget, event):
        """Handler for redimensionar/mover janela

        `set()` ignora valores repetidos e e debounced, por isso mover a
        janela nao provoca uma escrita de config.json por pixel.
        """
        self.config.set("app.x_position", event.x)
        self.config.set("app.y_position", event.y)
        self.config.set("app.width", event.width)
        self.config.set("app.height", event.height)

        return True
