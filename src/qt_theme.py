"""Qt theme support: load themes/*.json as Qt stylesheets.

Themes are defined in JSON (same format as the GTK track) with colors and
UI settings. This module converts them to Qt stylesheets (QSS) so the
Qt track can use the same theme files.

Usage:
    from src.qt_theme import load_theme, apply_theme, available_themes
    theme = load_theme("dark")  # or load_theme() for default
    apply_theme(app, theme)     # apply to QApplication
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).resolve().parents[1] / "themes"

DEFAULT_THEME = "dark"


def available_themes() -> List[str]:
    """List available theme names (without .json extension)."""
    if not THEMES_DIR.is_dir():
        return [DEFAULT_THEME]
    return sorted(
        path.stem for path in THEMES_DIR.glob("*.json")
        if path.is_file()
    )


def load_theme(name: Optional[str] = None) -> Dict:
    """Load a theme by name, falling back to the default theme.

    Returns the parsed theme dict with "name", "colors", "ui" keys.
    """
    if not name:
        name = DEFAULT_THEME
    path = THEMES_DIR / f"{name}.json"
    if not path.is_file():
        # Try default
        path = THEMES_DIR / f"{DEFAULT_THEME}.json"
    if not path.is_file():
        # Return a minimal dark theme
        return _minimal_dark_theme()
    try:
        with open(path, "r", encoding="utf-8") as f:
            theme = json.load(f)
        theme.setdefault("name", name)
        theme.setdefault("colors", {})
        theme.setdefault("ui", {})
        return theme
    except (json.JSONDecodeError, OSError) as error:
        logger.warning("Failed to load theme %s: %s", name, error)
        return _minimal_dark_theme()


def _minimal_dark_theme() -> Dict:
    """Fallback theme when no theme files are available."""
    return {
        "name": "Minimal Dark",
        "colors": {
            "background": "#1e1e1e",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        },
        "ui": {
            "font_family": "Sans Serif",
            "font_size": 10,
            "border_radius": 8,
        },
    }


def theme_to_stylesheet(theme: Dict) -> str:
    """Convert a theme dict to a Qt stylesheet (QSS) string.

    Maps theme colors to Qt widget selectors:
    - background → QWidget, QMainWindow background
    - text → color for labels, text edits
    - accent → buttons, highlights
    - secondary → secondary surfaces (menus, toolbars)
    - tertiary → tertiary surfaces (status bars, frames)
    - border → borders
    """
    colors = theme.get("colors", {})
    ui = theme.get("ui", {})

    bg = colors.get("background", "#1e1e1e")
    text = colors.get("text", "#e0e0e0")
    accent = colors.get("accent", "#4CAF50")
    secondary = colors.get("secondary", "#2d2d2d")
    tertiary = colors.get("tertiary", "#252525")
    border = colors.get("border", "#3d3d3d")

    font_family = ui.get("font_family", "Sans Serif")
    font_size = ui.get("font_size", 10)
    border_radius = ui.get("border_radius", 8)

    # Derived colors
    accent_hover = _lighten(accent, 0.1)
    accent_pressed = _darken(accent, 0.1)
    text_disabled = _darken(text, 0.3)

    return f"""
/* Base */
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: "{font_family}";
    font-size: {font_size}pt;
    border: none;
}}

QMainWindow {{
    background-color: {bg};
}}

/* Labels */
QLabel {{
    background-color: transparent;
    color: {text};
}}

/* Text inputs */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    border-radius: {border_radius}px;
    padding: 6px;
    selection-background-color: {accent};
    selection-color: {bg};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {accent};
}}

QLineEdit:disabled, QPlainTextEdit:disabled {{
    color: {text_disabled};
    background-color: {tertiary};
}}

/* Buttons */
QPushButton {{
    background-color: {accent};
    color: {bg};
    border: none;
    border-radius: {border_radius}px;
    padding: 6px 16px;
    font-weight: bold;
}}

QPushButton:hover {{
    background-color: {accent_hover};
}}

QPushButton:pressed {{
    background-color: {accent_pressed};
}}

QPushButton:disabled {{
    background-color: {tertiary};
    color: {text_disabled};
}}

/* Secondary buttons (flat) */
QPushButton[flat="true"] {{
    background-color: transparent;
    color: {text};
    border: 1px solid {border};
}}

QPushButton[flat="true"]:hover {{
    background-color: {secondary};
    border-color: {accent};
}}

/* Combo boxes */
QComboBox {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    border-radius: {border_radius}px;
    padding: 4px 8px;
}}

QComboBox:hover {{
    border-color: {accent};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    selection-background-color: {accent};
    selection-color: {bg};
}}

/* Check boxes */
QCheckBox {{
    color: {text};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {border};
    border-radius: 3px;
    background-color: {secondary};
}}

QCheckBox::indicator:checked {{
    background-color: {accent};
    border-color: {accent};
}}

/* List widgets */
QListWidget {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    border-radius: {border_radius}px;
    outline: none;
}}

QListWidget::item {{
    padding: 8px;
    border-radius: 4px;
}}

QListWidget::item:selected {{
    background-color: {accent};
    color: {bg};
}}

QListWidget::item:hover {{
    background-color: {tertiary};
}}

/* Group boxes */
QGroupBox {{
    color: {text};
    border: 1px solid {border};
    border-radius: {border_radius}px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {accent};
}}

/* Dialogs */
QDialog {{
    background-color: {bg};
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {tertiary};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background-color: {border};
    border-radius: 5px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {accent};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {tertiary};
    height: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal {{
    background-color: {border};
    border-radius: 5px;
    min-width: 20px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {accent};
}}

/* Menu */
QMenu {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    border-radius: {border_radius}px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {accent};
    color: {bg};
}}

QMenu::item:disabled {{
    color: {text_disabled};
}}

QMenu::separator {{
    height: 1px;
    background-color: {border};
    margin: 4px 8px;
}}

/* Tray icon tooltip */
QToolTip {{
    background-color: {secondary};
    color: {text};
    border: 1px solid {border};
    border-radius: 4px;
    padding: 4px;
}}

/* Status bar */
QStatusBar {{
    background-color: {tertiary};
    color: {text};
    border-top: 1px solid {border};
}}

/* Splitter */
QSplitter::handle {{
    background-color: {border};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}

/* Tab widget */
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: {border_radius}px;
}}

QTabBar::tab {{
    background-color: {tertiary};
    color: {text};
    padding: 8px 16px;
    border: none;
    border-top-left-radius: {border_radius}px;
    border-top-right-radius: {border_radius}px;
}}

QTabBar::tab:selected {{
    background-color: {accent};
    color: {bg};
}}

QTabBar::tab:hover {{
    background-color: {secondary};
}}
"""


def _lighten(hex_color: str, factor: float) -> str:
    """Lighten a hex color by a factor (0.0-1.0)."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
        r = min(255, int(r + (255 - r) * factor))
        g = min(255, int(g + (255 - g) * factor))
        b = min(255, int(b + (255 - b) * factor))
        return _rgb_to_hex(r, g, b)
    except Exception:
        return hex_color


def _darken(hex_color: str, factor: float) -> str:
    """Darken a hex color by a factor (0.0-1.0)."""
    try:
        r, g, b = _hex_to_rgb(hex_color)
        r = max(0, int(r * (1 - factor)))
        g = max(0, int(g * (1 - factor)))
        b = max(0, int(b * (1 - factor)))
        return _rgb_to_hex(r, g, b)
    except Exception:
        return hex_color


def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert #RRGGBB to (r, g, b)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert (r, g, b) to #RRGGBB."""
    return f"#{r:02x}{g:02x}{b:02x}"


def apply_theme(app, theme: Optional[Dict] = None, theme_name: Optional[str] = None):
    """Apply a theme to a QApplication.

    Args:
        app: QApplication instance
        theme: Pre-loaded theme dict (optional)
        theme_name: Theme name to load (optional)
    """
    if theme is None:
        theme = load_theme(theme_name)
    stylesheet = theme_to_stylesheet(theme)
    app.setStyleSheet(stylesheet)
    logger.info("Applied theme: %s", theme.get("name", "unknown"))
    return theme


def get_current_theme_name(config_manager) -> str:
    """Get the current theme name from config."""
    try:
        return config_manager.get("ui.theme", DEFAULT_THEME)
    except Exception:
        return DEFAULT_THEME


def set_current_theme(config_manager, theme_name: str) -> bool:
    """Set the current theme name in config."""
    try:
        config_manager.set("ui.theme", theme_name)
        return True
    except Exception:
        logger.warning("Could not save theme preference")
        return False
