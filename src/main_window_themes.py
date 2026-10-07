"""Theme management methods extracted from MainWindow.

These methods handle adding, removing and listing custom themes.
Extracted from main_window.py to reduce its size.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from .main_window import MainWindow

logger = logging.getLogger(__name__)

# Themes that ship with the app and cannot be removed
PREDEFINED_THEMES = ["dark", "light", "dracula", "solarized-dark"]

# Valid theme name pattern (becomes a filename)
THEME_NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def get_user_themes_dir() -> Path:
    """Get the user's custom themes directory."""
    return Path.home() / ".config" / "linux_ai_assistant" / "themes"


def create_theme(window: "MainWindow", theme_name: str, description: str,
                 colors: dict, ui: dict) -> bool:
    """Create a new custom theme.

    Args:
        window: The MainWindow instance (for notifications)
        theme_name: Theme name (becomes filename)
        description: Theme description
        colors: Dict with background, text, accent, secondary, tertiary
        ui: Dict with font_family, font_size, border_radius

    Returns:
        True if theme was created successfully
    """
    from .i18n import _

    # Validate theme name (becomes a filename)
    if not THEME_NAME_RE.fullmatch(theme_name):
        window.show_notification(
            "Linux AI Assistant",
            _("A theme name is required (letters, digits, '-' or '_', max 64)")
        )
        return False

    theme = {
        "name": theme_name,
        "description": description,
        "colors": colors,
        "ui": ui,
    }

    # Save theme
    try:
        themes_dir = get_user_themes_dir()
        themes_dir.mkdir(parents=True, exist_ok=True)
        theme_file = themes_dir / f"{theme_name}.json"

        with open(theme_file, 'w', encoding='utf-8') as f:
            json.dump(theme, f, indent=2, ensure_ascii=False)
        window.show_notification("Linux AI Assistant", f"Theme '{theme_name}' created")
        return True
    except Exception as e:
        logger.error(f"Error saving theme: {e}")
        window.show_notification("Linux AI Assistant", f"Error saving theme: {e}")
        return False


def remove_theme(window: "MainWindow", theme_name: str) -> bool:
    """Remove a custom theme.

    Args:
        window: The MainWindow instance (for notifications)
        theme_name: Theme name to remove

    Returns:
        True if theme was removed successfully
    """
    from .i18n import _

    # Do not allow removing built-in themes
    if theme_name in PREDEFINED_THEMES:
        window.show_notification("Linux AI Assistant", _("Cannot remove built-in themes"))
        return False

    themes_dir = get_user_themes_dir()
    theme_file = themes_dir / f"{theme_name}.json"

    try:
        # Resolve and confirm the target really is inside the user's themes dir
        resolved = theme_file.resolve()
        if resolved.parent != themes_dir.resolve():
            raise ValueError(f"Refusing to delete outside themes dir: {resolved}")
        if resolved.exists():
            resolved.unlink()
            window.show_notification("Linux AI Assistant", f"Theme '{theme_name}' removed")
            return True
        return False
    except Exception as e:
        logger.error(f"Error removing theme: {e}")
        window.show_notification("Linux AI Assistant", f"Error removing theme: {e}")
        return False


def populate_themes_list(window: "MainWindow"):
    """Populate the themes listbox in the settings dialog.

    Args:
        window: The MainWindow instance
    """
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk

    listbox = window.themes_listbox

    # Clear list
    for child in listbox.get_children():
        listbox.remove(child)

    # Get available themes
    available_themes: List[str] = window.config.get_available_themes()

    for theme_name in available_themes:
        theme_info = window.config.get_theme_info(theme_name)
        display_name = theme_info.get("name", theme_name) if theme_info else theme_name
        description = theme_info.get("description", "") if theme_info else ""

        row = Gtk.ListBoxRow()
        # Keep the file stem on the row: the visible label is the
        # display name, which may differ from the file name.
        row._theme_id = theme_name
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        name_label = Gtk.Label(label=display_name)
        name_label.set_halign(Gtk.Align.START)
        box.pack_start(name_label, False, False, 0)

        desc_label = Gtk.Label(label=description)
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_xalign(0)
        desc_label.get_style_context().add_class(Gtk.STYLE_CLASS_DIM_LABEL)
        box.pack_start(desc_label, False, False, 0)

        row.add(box)
        listbox.add(row)
        row.show_all()
