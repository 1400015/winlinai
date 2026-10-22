"""GTK theme management dialogs extracted from MainWindow.

Each function receives the window and updates the same state the methods
used to touch; MainWindow keeps a thin delegate with the public name.
"""

import gi

gi.require_version('Gtk', '3.0')

from gi.repository import Gtk

from .i18n import _
from .main_window_themes import PREDEFINED_THEMES, create_theme, populate_themes_list, remove_theme

__all__ = [
    "add_theme_dialog",
    "populate_themes",
    "remove_theme_dialog",
    "show_theme_settings",
]


def show_theme_settings(window, button):
    """Open the settings dialog on the Themes tab.

    The "Manage Themes" button lives inside the dialog itself, so
    reopening it would stack a second modal dialog on top of the first.
    """
    if window._settings_notebook is None:
        window._show_config_dialog()
        return
    # Themes is the third page (API, Appearance, Themes, Features)
    window._settings_notebook.set_current_page(2)


def add_theme_dialog(window, button):
    """Add a new theme"""
    dialog = Gtk.Dialog(
        title="Add Theme",
        parent=window,
        flags=0,
        buttons=(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
    )

    content = dialog.get_content_area()

    # Theme name
    name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    name_label = Gtk.Label(label=_("Name:"))
    name_entry = Gtk.Entry()
    name_box.pack_start(name_label, False, False, 0)
    name_box.pack_start(name_entry, True, True, 0)
    content.pack_start(name_box, False, False, 0)

    # Description
    desc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
    desc_label = Gtk.Label(label=_("Description:"))
    desc_entry = Gtk.Entry()
    desc_box.pack_start(desc_label, False, False, 0)
    desc_box.pack_start(desc_entry, True, True, 0)
    content.pack_start(desc_box, False, False, 0)

    # Colors
    colors_frame = Gtk.Frame(label=_("Colors"))
    colors_grid = Gtk.Grid()
    colors_grid.set_column_spacing(10)
    colors_grid.set_row_spacing(5)
    colors_frame.add(colors_grid)
    content.pack_start(colors_frame, False, False, 0)

    # Background
    bg_label = Gtk.Label(label=_("Background:"))
    bg_entry = Gtk.Entry()
    bg_entry.set_placeholder_text("#1e1e1e")
    bg_entry.set_text("#1e1e1e")
    colors_grid.attach(bg_label, 0, 0, 1, 1)
    colors_grid.attach(bg_entry, 1, 0, 1, 1)

    # Text
    text_label = Gtk.Label(label=_("Text:"))
    text_entry = Gtk.Entry()
    text_entry.set_placeholder_text("#e0e0e0")
    text_entry.set_text("#e0e0e0")
    colors_grid.attach(text_label, 0, 1, 1, 1)
    colors_grid.attach(text_entry, 1, 1, 1, 1)

    # Accent
    accent_label = Gtk.Label(label=_("Accent:"))
    accent_entry = Gtk.Entry()
    accent_entry.set_placeholder_text("#4CAF50")
    accent_entry.set_text("#4CAF50")
    colors_grid.attach(accent_label, 0, 2, 1, 1)
    colors_grid.attach(accent_entry, 1, 2, 1, 1)

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        theme_name = name_entry.get_text().strip()
        description = desc_entry.get_text().strip()
        colors = {
            "background": bg_entry.get_text().strip(),
            "text": text_entry.get_text().strip(),
            "accent": accent_entry.get_text().strip(),
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
        }
        ui = {
            "font_family": "Monospace",
            "font_size": 12,
            "border_radius": 10,
        }
        # create_theme validates the name (it becomes a file name) and
        # handles persistence + notifications.
        if create_theme(window, theme_name, description, colors, ui):
            window._populate_themes_list()

    dialog.destroy()


def remove_theme_dialog(window, button):
    """Remove the selected theme"""
    selected_row = window.themes_listbox.get_selected_row()
    if not selected_row:
        window.show_notification("Linux AI Assistant", _("No theme selected"))
        return

    theme_name = getattr(selected_row, "_theme_id", None)
    if not theme_name:
        window.show_notification("Linux AI Assistant", _("No theme selected"))
        return

    # Do not allow removing built-in themes (they ship with the app,
    # under the package's themes dir, not the user's)
    if theme_name in PREDEFINED_THEMES:
        window.show_notification("Linux AI Assistant", _("Cannot remove built-in themes"))
        return

    # Confirm removal
    dialog = Gtk.MessageDialog(
        parent=window,
        flags=0,
        message_type=Gtk.MessageType.QUESTION,
        buttons=Gtk.ButtonsType.YES_NO,
        text=f"Remove theme '{theme_name}'?"
    )

    response = dialog.run()
    dialog.destroy()

    if response == Gtk.ResponseType.YES:
        # remove_theme resolves the target inside the user themes dir,
        # refuses path traversal, deletes and notifies.
        if remove_theme(window, theme_name):
            window._populate_themes_list()


def populate_themes(window):
    """Populate the themes list (delegates to main_window_themes)."""
    populate_themes_list(window)

