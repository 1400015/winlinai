"""Sending, streaming and finalising chat turns extracted from MainWindow.

The window still owns state and widgets; the worker and idle callbacks keep
every mutation behind the request id and cancel event captured at send time.
"""

import logging
import threading
import time

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import GLib, Gtk

from . import file_actions
from .ai_client import (
    AIClient,
    AIProviderError,
    AIRequestCancelled,
    AIResponseLimitError,
    AIImageRequestError,
)
from .device_actions import split_offer
from .document_context import (
    MAX_DOCUMENT_CONTEXT_CHARS,
    display_document_context,
    with_document_context,
)
from .document_review import review_document_context
from .history_store import MAX_MESSAGE_CHARS
from .i18n import _, get_language
from .image_dialog import review_image

logger = logging.getLogger(__name__)

# Minimum interval between streamed chunk flushes to the UI (seconds).
STREAM_FLUSH_INTERVAL = 0.08

__all__ = [
    "finalize_response",
    "process_message",
    "send_message",
]


def send_message(window):
    """Handler for send button click"""
    if (getattr(window, '_history_recovering', False)
            or getattr(getattr(window, 'history_store', None), 'last_error', None) is not None):
        window._show_history_warning()
        return
    if window.is_loading:
        logger.warning("A message is already being processed")
        return

    image = getattr(window, '_pending_image', None)
    text = window.input_entry.get_text().strip()
    if not text and image is not None:
        text = _("Describe this image.")
    if not text:
        return

    if len(text) > MAX_MESSAGE_CHARS:
        window._add_system_message(_("Message exceeds the local history limit. Shorten it before sending."))
        return

    try:
        provider = window.ai_client.active_provider()
        route = {'provider': provider, 'ready': window.ai_client.provider_ready(provider)}
    except AIProviderError:
        route = {'provider': None, 'ready': False}
    images: tuple = ()
    document_context = ''
    try:
        if image is not None:
            provider, model = window.ai_client.validate_image_request((image,))
            if not route['ready']:
                raise AIImageRequestError(_("Configure a usable OpenRouter provider before sending an image."))
            if ((provider, model) != getattr(window, '_pending_image_destination', None)
                    and not review_image(window, image, provider, model)):
                return
            route.update(provider=provider, model=model)
            images = (image,)
        documents_check = getattr(window, 'documents_check', None)
        if documents_check is not None and documents_check.get_active():
            document_context = window._get_document_store().context(text, max_chars=MAX_DOCUMENT_CONTEXT_CHARS)
            if not document_context:
                window._add_system_message(_("No matching passages in the selected documents. Add documents or refine your question."))
                return
            if route['ready'] and not review_document_context(window, document_context, route['provider']):
                return
    except (OSError, ValueError, AIProviderError) as error:
        window._add_system_message(str(error))
        return

    try:
        history_text = text
        if image is not None:
            history_text += '\n\n' + _("[Image attached for this request; pixels are not stored.]")
        window._remember("user", history_text)
    except (OSError, ValueError, RuntimeError) as error:
        window._add_system_message(_("Could not save the message: {error}").format(error=error))
        return

    window.input_entry.set_text("")
    window._clear_pending_image()

    # Add the user message to the chat...
    window._add_user_message(history_text)

    # ...and to the context + history.json (ponto único de persistência)

    # Snapshot do pedido construído NA main thread: a worker deixou de
    # ler conversation_history/expert_mode/config sem sincronização.
    context = window._get_context_message()
    messages = window._build_request_messages()
    full_history = ([context] + messages) if context else messages
    if document_context:
        full_history = with_document_context(full_history, document_context)

    # Per-request state: fresh id + cancel event. A worker that is
    # still draining after a cancel can no longer touch this request.
    window._request_seq += 1
    request_id = window._request_seq
    cancel_event = threading.Event()
    window._cancel_event = cancel_event
    window._active_request = request_id
    window.chat_view.abort_stream()

    # Update state
    window.is_loading = True
    window.streaming = True
    window.cancel_btn.set_sensitive(True)
    window.status_icon.set_from_icon_name("process-working-symbolic", Gtk.IconSize.MENU)
    window.status_icon.set_tooltip_text(_("Processing..."))

    # Process in a separate thread so the UI is not blocked
    threading.Thread(
        target=window._process_message,
        args=(text, full_history, request_id, cancel_event, window.offline, route,
              window.history_store.active_session_id, images, document_context),
        daemon=True,
    ).start()


def process_message(window, message, full_history, request_id, cancel_event,
                    offline=None, route=None, session_id=None, images=(), document_context=''):
    """Process the message and get the AI response.

    All UI/history mutations are queued to the main loop with
    `request_id`, so output from a superseded or cancelled request is
    dropped instead of corrupting the next turn.
    """
    if cancel_event.is_set() or request_id != window._active_request:
        return
    offline = offline if offline is not None else window.offline
    GLib.idle_add(window._add_loading_message, request_id, cancel_event)
    response_text = ""
    # Coalescing de chunks: acumula no worker e faz flush à UI no
    # máximo ~12x/segundo (STREAM_FLUSH_INTERVAL), em vez de um idle
    # por chunk (milhares por resposta rápida).
    pending_chunks = []
    last_flush = 0.0

    try:
        actions = getattr(window, 'actions', None)
        if actions is not None and session_id is not None and not images and not document_context:
            reply = actions.handle(
                message, session_id, get_language(),
                is_current=lambda: request_id == window._active_request and not cancel_event.is_set(),
            )
            if reply is not None:
                GLib.idle_add(window._complete_action_reply, request_id, cancel_event, reply, session_id)
                return
        offline_reply = None

        ready = route['ready'] if route is not None else window.ai_client.provider_ready()
        if not ready and images:
            raise AIImageRequestError(_("The image request cannot be answered offline."))
        if not ready and document_context:
            GLib.idle_add(window._finish_local_document_reply, request_id, cancel_event,
                          _("Local document matches (no model request):") + '\n\n' + display_document_context(document_context))
            return
        if not ready:
            # No key for the selected provider: answer from local knowledge
            # instead of failing with "API key not configured".
            logger.info("No usable provider; using the offline assistant")
            # Keep the diagnostic on this request's selected provider.
            # An empty override may come from the process environment;
            # only assignments this manager loaded can be removed here.
            try:
                shadow_provider = route['provider'] if route is not None else window.ai_client.active_provider()
                if shadow_provider and window.config.stored_key_shadowed_by_empty_env(shadow_provider):
                    shadow_var = window.config.api_key_env_var(shadow_provider)
                    warning = _(
                        "The stored key for {provider} is disabled by the empty "
                        "{var} environment variable."
                    ).format(provider=shadow_provider, var=shadow_var)
                    if window.config.can_remove_empty_api_key_override(shadow_provider):
                        warning += ' ' + _(
                            "Open Settings → API and choose '{button}' to remove "
                            "the empty assignment from .env."
                        ).format(button=_("Use stored key (remove empty override from .env)"))
                    else:
                        warning += ' ' + _(
                            "Remove or fill this variable at its source, then restart the application."
                        )
                    GLib.idle_add(
                        window._add_system_message_if_active, request_id, cancel_event, warning)
            except Exception:
                pass
            offline_reply = offline.handle(message, get_language())
        else:
            try:
                if cancel_event.is_set():
                    return
                options = {'provider': route['provider']} if route is not None else {}
                if images:
                    options['images'] = images
                    if route is not None:
                        options['model'] = route['model']
                # Keep old third-party clients/test shims callable, while
                # the built-in client propagates this request's event.
                if isinstance(window.ai_client, AIClient):
                    options['cancel_event'] = cancel_event
                stream = window.ai_client.stream_chat(full_history, **options)
                try:
                    for chunk in stream:
                        if cancel_event.is_set():
                            break
                        if len(response_text) + len(chunk) > MAX_MESSAGE_CHARS:
                            raise AIResponseLimitError(
                                _("AI response exceeds the local history limit. The incomplete response was not saved; ask for a shorter response.")
                            )
                        response_text += chunk
                        pending_chunks.append(chunk)
                        now = time.monotonic()
                        if now - last_flush >= STREAM_FLUSH_INTERVAL:
                            GLib.idle_add(window._update_ai_message, request_id,
                                          "".join(pending_chunks), True)
                            pending_chunks = []
                            last_flush = now
                finally:
                    close = getattr(stream, 'close', None)
                    if callable(close):
                        close()
            except AIRequestCancelled:
                GLib.idle_add(window._finalize_response, request_id, "", True)
                return
            except (AIResponseLimitError, AIImageRequestError):
                # A local limit is an incomplete answer, not a reason to
                # silently replace it with an unrelated offline answer.
                raise
            except AIProviderError as e:
                if images:
                    raise
                if document_context and not cancel_event.is_set():
                    GLib.idle_add(window._finish_local_document_reply, request_id, cancel_event,
                                  _("The model is unavailable. Local document matches:") + '\n\n' + display_document_context(document_context),
                                  )
                    return
                # Falha ESTRUTURADA do provider (rede/HTTP/config) — não
                # é conteúdo do modelo. O fallback offline dispara tanto
                # para falha antes do primeiro chunk como a meio do
                # stream (o antigo _is_api_failure por prefixo perdia
                # os erros a meio e disparava o fallback para respostas
                # legítimas que começassem por "Error:").
                logger.info(
                    "Provider unavailable (%s); using the offline assistant", e
                )
                if not cancel_event.is_set():
                    pending_chunks.clear()
                    response_text = ""
                    offline_reply = offline.handle(message, get_language())

            if offline_reply is None and not response_text and not cancel_event.is_set():
                if images:
                    raise AIImageRequestError(_("The model returned no answer for the image."))
                if document_context:
                    GLib.idle_add(window._finish_local_document_reply, request_id, cancel_event,
                                  _("The model is unavailable. Local document matches:") + '\n\n' + display_document_context(document_context))
                    return
                offline_reply = offline.handle(message, get_language())
            if pending_chunks and offline_reply is None and not cancel_event.is_set():
                GLib.idle_add(window._update_ai_message, request_id,
                              "".join(pending_chunks), True)
                pending_chunks = []

        action = None
        if offline_reply is not None:
            pending_chunks.clear()
            response_text = offline_reply.text
            GLib.idle_add(window._replace_ai_reply, request_id, cancel_event, response_text)
            action = offline_reply
        elif response_text and not cancel_event.is_set() and not images and not document_context:
            # The model may explain the step. The command, if any, comes
            # from the user's sentence and the local catalog.
            propose = getattr(offline, "propose", None)
            if callable(propose):
                try:
                    action = propose(message, get_language())
                except Exception as exc:
                    logger.error("Could not prepare a confirmed action: %s", exc, exc_info=True)

        cancelled = cancel_event.is_set()
        if images or document_context:
            GLib.idle_add(window._finalize_response, request_id, response_text, cancelled, False)
        else:
            GLib.idle_add(window._finalize_response, request_id, response_text, cancelled)
        interaction, commands = split_offer(action)
        if (interaction or commands) and not cancelled:
            GLib.idle_add(window._offer_confirmed_action, interaction, commands,
                          request_id, cancel_event)

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        GLib.idle_add(window._abort_ai_stream_if_active, request_id)
        GLib.idle_add(window._add_system_message_if_active, request_id,
                      cancel_event, _("Error: {error}").format(error=e))
        GLib.idle_add(window._finalize_response, request_id, "", cancel_event.is_set())


def finalize_response(window, request_id, response_text, cancelled, allow_file_actions=True, history_text=None):
    """Persist the response and settle the UI (main loop only)."""
    if request_id != window._active_request:
        # A newer request replaced this one; its output is stale.
        logger.debug("Dropping result from stale request %s", request_id)
        return False

    window.streaming = False

    # Cancellation can arrive after the worker queued this final callback.
    cancelled = cancelled or window._cancel_event.is_set()
    if cancelled:
        window.chat_view.abort_stream()

    try:
        if response_text and len(response_text) > MAX_MESSAGE_CHARS:
            window.chat_view.abort_stream()
            window._add_system_message(_("AI response exceeds the local history limit. The incomplete response was not saved; ask for a shorter response."))
            return False
        if response_text and not cancelled:
            # The streamed body was inserted chunk by chunk; now that it is
            # complete, tag its code spans and close with the "\n\n"
            # separator (tudo dentro do ChatView, dono dos offsets).
            window.chat_view.close_streamed_message(response_text)

            # Ponto único de persistência do turno (memória + history.json)
            window._remember("assistant", response_text if history_text is None else history_text)
            store = getattr(window, 'history_store', None)
            if store is not None:
                try:
                    store.set_diagnostic_state(window.offline.diagnostic_state())
                except (OSError, ValueError) as error:
                    logger.error("Could not persist diagnostic progress: %s", error)
                    window._add_system_message(str(error))

            # GTK owns the consent dialog; digest/preview and the approved
            # transaction run in workers, including any polkit wait.
            if window.expert_mode and allow_file_actions:
                session_id = window.history_store.active_session_id
                cancel_event = window._cancel_event
                controller = file_actions.offer_file_blocks_async(
                    window, response_text,
                    lambda status, msg: window._record_file_action_result(session_id, status, msg),
                    lambda: window.config.get("permissions.allowed_edit_dirs", []),
                    window.change_journal, session_id,
                    is_current=lambda: (not getattr(window, '_audit_closed', False)
                                        and not getattr(window, '_history_recovering', False)
                                        and request_id == window._active_request
                                        and not cancel_event.is_set()
                                        and session_id == window.history_store.active_session_id),
                )
                controllers = getattr(window, '_file_action_controllers', None)
                if controllers is not None and controller is not None:
                    controllers[:] = [item for item in controllers if not item.finished]
                    controllers.append(controller)

    except (OSError, ValueError, RuntimeError) as error:
        logger.error("Could not finish or persist the response: %s", error)
        window._add_system_message(_("Could not save the response: {error}").format(error=error))
        if getattr(getattr(window, 'history_store', None), 'last_error', None) is not None:
            window._show_history_warning(error)
    finally:
        window._on_message_processed(request_id, cancelled)
    return False

