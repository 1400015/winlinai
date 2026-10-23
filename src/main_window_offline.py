"""Offline command confirmation and execution extracted from MainWindow.

The dialogs and worker still update the window they receive; the module
keeps the privileged-command path together with its guarded results.
"""

import logging
import threading

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import GLib, Gtk

from . import offline_assistant
from .i18n import _

logger = logging.getLogger(__name__)

__all__ = [
    "finish_offline_commands",
    "offer_offline_commands",
    "record_offline_result",
    "run_offline_commands",
]


def offer_offline_commands(window, commands, request_id, cancel_event):
    """Ask for confirmation before running privileged offline commands."""
    if not commands:
        return False
    # A newer request may already be active by the time this idle
    # callback runs: confirming a superseded turn would run commands
    # the user no longer expects.
    if request_id != window._active_request or cancel_event.is_set():
        return False

    dialog = Gtk.Dialog(
        title=_("Run suggested commands?"),
        transient_for=window,
        modal=True,
    )
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Run"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)

    content = dialog.get_content_area()
    header = Gtk.Label(
        label=_("These changes need administrator rights (pkexec):")
    )
    header.set_halign(Gtk.Align.START)
    header.set_line_wrap(True)
    content.pack_start(header, False, False, 6)
    for command in commands:
        row = Gtk.Label(label=f"$ {command.display()}")
        row.set_halign(Gtk.Align.START)
        row.set_selectable(True)
        row.set_monospace(True)
        content.pack_start(row, False, False, 2)

    dialog.show_all()
    response = dialog.run()
    dialog.destroy()
    if response != Gtk.ResponseType.OK:
        return False
    if request_id != window._active_request or cancel_event.is_set():
        return False

    window._local_running_request = request_id
    window.is_loading = True
    window.cancel_btn.set_sensitive(True)
    window.status_icon.set_from_icon_name('process-working-symbolic', Gtk.IconSize.MENU)
    window.status_icon.set_tooltip_text(_("Running confirmed commands…"))
    window._add_system_message(_("Running confirmed commands. Cancellation stops later commands; an operation already started may still finish."))
    threading.Thread(
        target=window._run_offline_commands,
        args=(commands, request_id, cancel_event, window.history_store.active_session_id),
        daemon=True,
    ).start()
    return False


def run_offline_commands(window, commands, request_id, cancel_event, session_id=None):
    """Run the confirmed commands via pkexec (worker thread)."""
    store = getattr(window, 'history_store', None)
    session_id = session_id or (store.active_session_id if store is not None else None)
    try:
        for command in commands:
            # Cancellation does not roll back an operation already begun.
            if cancel_event.is_set() or request_id != window._active_request:
                logger.info("Skipping offline command: request was cancelled")
                return False
            try:
                ok, output = offline_assistant.OfflineAssistant.run_privileged(command)
            except Exception:
                # An exception after dispatch does not prove that no
                # mutation happened. Avoid exposing command secrets.
                ok = False
                output = _("The operation result could not be determined. Check the target before trying again.")
            detail = output or (_("Done.") if ok else _("Failed."))
            result = f"$ {command.display()}\n{detail}"
            GLib.idle_add(window._record_offline_result, request_id, result, session_id)
            if not ok:
                logger.info("Stopping confirmed command sequence after failure")
                break
    finally:
        GLib.idle_add(finish_offline_commands, window, request_id, cancel_event)
    return False


def finish_offline_commands(window, request_id, cancel_event):
    if getattr(window, '_local_running_request', None) == request_id:
        window._local_running_request = None
    if request_id == window._active_request:
        window._on_message_processed(request_id, cancel_event.is_set())
    return False


def record_offline_result(window, request_id, result, session_id=None):
    """Show a command result and keep it in the conversation context.

    Without the history append, follow-up questions had no idea what
    was executed (the text only reached the chat buffer).
    """
    if request_id != window._active_request:
        # A completed action belongs to its original conversation even after a switch.
        if session_id is not None:
            available = window.history_store.list_sessions(include_archived=True)
            if any(session['id'] == session_id for session in available):
                try:
                    window.history_store.append('assistant', result, session_id=session_id)
                except (OSError, ValueError, RuntimeError) as error:
                    logger.error("Could not save the completed operation in its original session: %s", error)
        return False
    # A cancelled operation's actual outcome remains visible in the same
    # conversation. It must never be presented as if cancellation undid it.
    if window._cancel_event.is_set():
        window._add_system_message(_("Operation completed after cancellation. Check its result below; cancellation did not undo it."))
    window._add_system_message(result)
    try:
        window._remember("assistant", result)
    except (OSError, ValueError, RuntimeError) as error:
        window._add_system_message(_("Could not save the operation result: {error}").format(error=error))
    return False

