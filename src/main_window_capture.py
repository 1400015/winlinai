"""Screen-capture workflow extracted from MainWindow.

The GTK window still owns the widgets and request state; these functions
run the guarded capture, OCR and image-review paths over that window.
"""

import logging
import os
import threading

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import GLib, Gtk

from .ai_client import AIClient, AIProviderError, AIImageRequestError
from .i18n import _
from .image_attachments import prepare_image
from .image_dialog import review_image

logger = logging.getLogger(__name__)

__all__ = [
    "capture_screen",
    "on_capture_complete",
    "review_captured_image",
]


def capture_screen(window, button=None, for_ai=False):
    """Handler for screen capture"""
    # The button/shortcut stays available even if the feature was
    # disabled after startup, so enforce the setting here too.
    if not window.config.get("features.screen_capture", True):
        window._add_system_message(_("Screen capture is disabled in settings."))
        return
    if window.is_loading:
        window.show_notification("Linux AI Assistant", _("Wait for the current message to be processed"))
        return

    # A capture is its own request. Reusing a cancelled chat's event would
    # discard a new capture, and reusing its ID lets old callbacks alter it.
    previous_event = getattr(window, '_cancel_event', None)
    if previous_event is not None:
        previous_event.set()
    capture_request = max(getattr(window, '_request_seq', 0) or 0,
                          getattr(window, '_active_request', 0) or 0) + 1
    window._request_seq = window._active_request = capture_request
    capture_event = threading.Event()
    window._cancel_event = capture_event
    capture_session = getattr(getattr(window, 'history_store', None), 'active_session_id', None)
    ocr_enabled = window.config.get("features.ocr_enabled", True)

    def current():
        return (not capture_event.is_set() and not getattr(window, '_audit_closed', False)
                and capture_request == getattr(window, '_active_request', None)
                and capture_session == getattr(getattr(window, 'history_store', None), 'active_session_id', None))

    def dispatch(callback, *args):
        if current():
            callback(*args)
        return False

    def queue(callback, *args):
        GLib.idle_add(dispatch, callback, *args)

    def remember_ocr(text):
        # Keep one guarded main-loop callback for persistence and display;
        # a rejected entry must not appear to have been saved successfully.
        try:
            window._remember('user', text)
            window._add_user_message(text)
        except (OSError, ValueError, RuntimeError) as error:
            window._add_system_message(_("Could not save the message: {error}").format(error=error))

    window._add_system_message(_("Capturing screen..."))
    window.is_loading = True
    window.streaming = False
    cancel_button = getattr(window, 'cancel_btn', None)
    if cancel_button is not None:
        cancel_button.set_sensitive(True)
    window.status_icon.set_from_icon_name("process-working-symbolic", Gtk.IconSize.MENU)
    window.status_icon.set_tooltip_text(_("Capturing screen..."))

    def capture_and_process():
        temporary_image = None
        try:
            # Capture screen
            success, image_path = window.system_utils.capture_screen(cancel_event=capture_event)

            if success:
                temporary_image = image_path
                if not current():
                    return
                if for_ai:
                    image = prepare_image(image_path)
                    queue(window._review_captured_image, image, capture_request, capture_session, capture_event)
                    return
                queue(window._add_system_message, _("Screen captured: {path}").format(path=image_path))

                # Extract text
                if ocr_enabled:
                    queue(window._add_system_message, _("Extracting text from the image..."))
                    success, text = window.system_utils.extract_text_from_image(image_path)

                    if success and text:
                        # Limit the text so it does not overload the UI
                        max_length = 2000
                        if len(text) > max_length:
                            text = text[:max_length] + "\n\n... " + _("(text truncated)")

                        queue(remember_ocr, f"[{_('Screen capture')}]\n{text}")
                    else:
                        queue(window._add_system_message, _("Could not extract text from the image."))
                else:
                    queue(window._add_system_message, _("OCR disabled in settings."))

            else:
                queue(window._add_system_message, _("Error capturing screen: {detail}").format(detail=image_path))

        except Exception as e:
            logger.error(f"Error in screen capture: {e}", exc_info=True)
            queue(window._add_system_message, _("Error: {error}").format(error=e))
        finally:
            if temporary_image is not None:
                try:
                    os.unlink(temporary_image)
                except OSError:
                    pass
            queue(window._on_capture_complete, capture_request, capture_session, capture_event)

    threading.Thread(target=capture_and_process, daemon=True).start()

def review_captured_image(window, image, request_id, session_id, cancel_event=None):
    event = cancel_event if cancel_event is not None else getattr(window, '_cancel_event', None)

    def current():
        return (not getattr(window, '_audit_closed', False)
                and (event is None or not event.is_set())
                and request_id == getattr(window, '_active_request', None)
                and session_id == getattr(getattr(window, 'history_store', None), 'active_session_id', None))

    if not current():
        return False
    try:
        if not isinstance(window.ai_client, AIClient):
            raise AIImageRequestError(_("This client does not support reviewed images."))
        provider, model = window.ai_client.validate_image_request((image,))
        # A modal dialog runs a nested main loop: cancellation or a session
        # change can happen while the reviewed image is on screen.
        if review_image(window, image, provider, model) and current():
            window._pending_image = image
            window._pending_image_destination = (provider, model)
            window.attachment_label.set_text(_("Image ready for the next question: {name} ({width} × {height})")
                                           .format(name=image.filename, width=image.width, height=image.height))
            window.remove_image_button.show()
    except (OSError, ValueError, AIProviderError) as error:
        if current():
            window._add_system_message(_("Could not attach image: {error}").format(error=error))
    return False

def on_capture_complete(window, request_id=None, session_id=None, cancel_event=None):
    """Callback when the capture is completed."""
    if (getattr(window, '_audit_closed', False)
            or (cancel_event is not None and cancel_event.is_set())
            or (request_id is not None and request_id != getattr(window, '_active_request', None))
            or (session_id is not None and session_id != getattr(getattr(window, 'history_store', None), 'active_session_id', None))):
        return False
    window.is_loading = False
    window.streaming = False
    cancel_button = getattr(window, 'cancel_btn', None)
    if cancel_button is not None:
        cancel_button.set_sensitive(False)
    window.status_icon.set_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
    window.status_icon.set_tooltip_text(_("Ready"))
    return False

