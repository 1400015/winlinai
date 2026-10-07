"""Dialog methods extracted from MainWindow.

These methods handle the settings, statistics and history dialogs.
Extracted from main_window.py to reduce its size.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)


def show_stats_dialog(window: "MainWindow"):
    """Show usage statistics dialog.

    Args:
        window: The MainWindow instance
    """
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk
    from .i18n import _

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


def show_config_dialog(window: "MainWindow"):
    """Show settings dialog.

    This is a large dialog with multiple tabs (API, Appearance, Themes, Features).
    For now, this delegates to the original implementation in main_window.py.

    Args:
        window: The MainWindow instance
    """
    # The original _show_config_dialog is very large (~300 lines).
    # For this refactoring phase, we keep it in main_window.py and
    # only extract the smaller dialogs.
    # TODO: Extract the full config dialog in a future refactoring.
    return window._show_config_dialog_original()
