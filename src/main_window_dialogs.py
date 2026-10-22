"""GTK report and confirmation dialogs extracted from MainWindow.

The dialogs still read window state through the window passed in; keeping
them here stops MainWindow from growing with presentation-only code.
"""

import threading

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import GLib, Gtk

from .i18n import _

__all__ = [
    "confirm_display_change",
    "show_action_audit",
    "show_stats_dialog",
]


def show_stats_dialog(window):
    """Show statistics dialog"""
    dialog = Gtk.Dialog(
        title=_("Statistics - Linux AI Assistant"),
        parent=window,
        flags=0,
        buttons=(Gtk.STOCK_OK, Gtk.ResponseType.OK)
    )
    dialog.set_default_size(400, 300)

    content = dialog.get_content_area()

    # Get statistics
    token_usage = window.ai_client.get_token_usage()

    # Create box vertical
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_border_width(10)
    content.add(box)

    # Title
    title = Gtk.Label(label="<b>" + _("Usage Statistics") + "</b>")
    title.set_use_markup(True)
    box.pack_start(title, False, False, 0)

    # Tokens by provider. The labels are kept so the reset button can
    # refresh them in place instead of leaving stale numbers on screen.
    token_labels = []
    for provider, usage in token_usage.items():
        provider_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)

        provider_label = Gtk.Label(label=f"{provider}:")
        provider_label.set_halign(Gtk.Align.START)
        provider_box.pack_start(provider_label, False, False, 0)

        tokens_label = Gtk.Label(label=f"Input: {usage.get('input', 0)}, Output: {usage.get('output', 0)}, Total: {usage.get('total', 0)}")
        tokens_label.set_halign(Gtk.Align.END)
        provider_box.pack_end(tokens_label, True, True, 0)

        box.pack_start(provider_box, False, False, 0)
        token_labels.append((provider, tokens_label))

    # Button to reset statistics
    def _reset_stats(btn):
        window.ai_client.reset_token_usage()
        for provider, tokens_label in token_labels:
            tokens_label.set_text("Input: 0, Output: 0, Total: 0")
    reset_btn = Gtk.Button(label=_("Reset Statistics"))
    reset_btn.connect("clicked", _reset_stats)
    reset_btn.set_halign(Gtk.Align.CENTER)
    box.pack_start(reset_btn, False, False, 0)

    dialog.show_all()
    dialog.run()
    dialog.destroy()


def show_action_audit(window):
    session_id = window.history_store.active_session_id

    def show(events, error):
        if getattr(window, '_audit_closed', False):
            return False
        dialog = Gtk.Dialog(title=_("Actions"), transient_for=window, modal=True)
        dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)
        dialog.set_default_size(720, 400)
        tree = Gtk.TreeStore(str, str, str, str)
        parents = {}
        for event in events:
            identifier = event['operation_id']
            if identifier not in parents:
                parents[identifier] = tree.append(None, [event['action_id'], event['resource'], event['phase'], identifier])
            tree.set_value(parents[identifier], 2, event['phase'])
            tree.append(parents[identifier], [event['phase'], event['detail'], '', ''])
        view = Gtk.TreeView(model=tree)
        for column, title in enumerate((_("Actions"), _("Details"), _("Status"), 'ID')):
            view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=column))
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.add(view)
        dialog.get_content_area().pack_start(scrolled, True, True, 0)
        if error or not events:
            dialog.get_content_area().pack_start(Gtk.Label(label=error or _("No actions recorded.")), False, False, 8)
        dialog.show_all()
        dialog.run()
        dialog.destroy()
        return False

    def load():
        try:
            events, error = window.actions.audit.events(session_id), ''
        except (OSError, ValueError):
            events, error = [], _("Cannot read the operation audit.")
        GLib.idle_add(show, events, error)
    threading.Thread(target=load, daemon=True).start()


def confirm_display_change(window, change, request_id, cancel_event, session_id):
    dialog = Gtk.Dialog(title=_("Keep display configuration?"), transient_for=window, modal=True)
    dialog.add_button(_("Revert"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Keep"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.CANCEL)
    label = Gtk.Label()
    label.set_margin_top(16)
    label.set_margin_bottom(16)
    label.set_margin_start(16)
    label.set_margin_end(16)
    dialog.get_content_area().add(label)
    timer_active = [True]

    def tick():
        if (change.status != 'pending' or request_id != window._active_request
                or cancel_event.is_set() or change.remaining_seconds <= 0):
            timer_active[0] = False
            dialog.response(Gtk.ResponseType.CANCEL)
            return False
        label.set_text(_("Reverting in {seconds} seconds unless you keep this configuration.").format(
            seconds=max(1, int(change.remaining_seconds + 0.999)),
        ))
        return True

    if tick():
        timer = GLib.timeout_add(200, tick)
        dialog.show_all()
        response = dialog.run()
        if timer_active[0]:
            GLib.source_remove(timer)
    else:
        response = Gtk.ResponseType.CANCEL
    dialog.destroy()
    keep = (response == Gtk.ResponseType.OK and request_id == window._active_request
            and not cancel_event.is_set())
    window._finish_display_change(change, keep, request_id, session_id)

