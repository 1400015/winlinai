"""Theme utilities for the GTK track: color validation and CSS generation.

Extracted from main_window.py to reduce its size and improve testability.
These functions are pure (no GTK imports) and can be tested without a display.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Values coming from theme files are interpolated into GTK's CSS; validating
# the format prevents a malicious JSON from injecting arbitrary style rules.
# GTK3 supports RGB hex colors; CSS4's RGBA hex forms fail its CSS parser.
_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_FONT_FAMILY_RE = re.compile(r"^[A-Za-z0-9 _.,'-]{1,64}$")


def safe_color(value, fallback="#1e1e1e"):
    """Return a hex color supported by GTK3 CSS or `fallback`."""
    if isinstance(value, str) and _COLOR_RE.match(value.strip()):
        return value.strip()
    if value is not None:
        logger.warning(f"Invalid theme color ignored: {value!r}")
    return fallback


def safe_font_family(value, fallback="Monospace"):
    """Return a safe font-family name for CSS."""
    if isinstance(value, str) and _FONT_FAMILY_RE.match(value.strip()):
        return value.strip()
    if value is not None:
        logger.warning(f"Invalid theme font family ignored: {value!r}")
    return fallback


def contrasting_text_color(background):
    """Choose readable text for a validated theme accent, including light ones."""
    value = safe_color(background, '#4CAF50')[1:]
    if len(value) == 3:
        value = ''.join(character * 2 for character in value)
    channels = [int(value[offset:offset + 2], 16) / 255 for offset in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    luminance = sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return '#000000' if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else '#ffffff'


def safe_number(value, fallback, cast, minimum=None, maximum=None):
    """Convert `value` to a number with bounds, or return `fallback`."""
    try:
        number = cast(value)
    except (TypeError, ValueError):
        return fallback
    if minimum is not None and number < minimum:
        return fallback
    if maximum is not None and number > maximum:
        return fallback
    return number


def build_css(colors: Dict, theme_info: Optional[Dict], chat_colors: Optional[Dict] = None) -> str:
    """Build the GTK CSS string from theme colors and settings.

    Args:
        colors: Dict with background, text, accent, secondary, tertiary, border
        theme_info: Optional theme info dict with ui and syntax_highlighting
        chat_colors: Optional pre-computed chat colors (user, ai, system, code)

    Returns:
        CSS string for GTK CssProvider
    """
    theme_ui: Dict = {}
    if theme_info:
        theme_ui = theme_info.get('ui', {}) or {}

    # Usar valores validados do theme
    bg_color = safe_color(colors.get('background'), '#1e1e1e')
    text_color = safe_color(colors.get('text'), '#e0e0e0')
    accent_color = safe_color(colors.get('accent'), '#4CAF50')
    secondary_color = safe_color(colors.get('secondary'), '#2d2d2d')
    tertiary_color = safe_color(colors.get('tertiary'), '#252525')
    border_color = safe_color(colors.get('border'), '#3d3d3d')
    accent_text = contrasting_text_color(accent_color)
    expert_text = contrasting_text_color('#2196F3')
    danger_text = contrasting_text_color('#f44336')

    font_family = safe_font_family(theme_ui.get('font_family'), 'Monospace')
    font_size = safe_number(theme_ui.get('font_size'), 12, int, minimum=4, maximum=72)
    border_radius = safe_number(theme_ui.get('border_radius'), 10, int, minimum=0, maximum=64)

    css = f"""
    .linux-ai-main #main-box {{
        background-color: {bg_color};
        color: {text_color};
        border-radius: {border_radius}px;
        padding: 10px;
        margin: 5px;
    }}

    .linux-ai-main #header {{
        background-color: {secondary_color};
        border-radius: {border_radius}px {border_radius}px 0 0;
        padding: 8px;
        margin-bottom: 10px;
    }}

    .linux-ai-main #chat-area {{
        background-color: {bg_color};
        color: {text_color};
        border: 1px solid {border_color};
        border-radius: {border_radius}px;
    }}

    .linux-ai-main #input-box {{
        background-color: {secondary_color};
        border-radius: {border_radius}px;
        padding: 5px;
        margin-top: 10px;
    }}

    .linux-ai-main #send-button {{
        background-color: {accent_color};
        color: {accent_text};
        border-radius: {border_radius}px;
        padding: 8px 16px;
        font-weight: bold;
    }}

    .linux-ai-main #send-button:hover {{
        opacity: 0.9;
    }}

    .linux-ai-main #expert-button {{
        background-color: #2196F3;
        color: {expert_text};
        border-radius: {border_radius}px;
        padding: 8px 12px;
    }}

    .linux-ai-main #expert-button.expert {{
        background-color: #1976D2;
    }}

    .linux-ai-main #menu-button {{
        background-color: {tertiary_color};
        color: {text_color};
        border-radius: {border_radius}px;
        padding: 8px;
    }}

    .linux-ai-main #attach-button {{
        background-color: {tertiary_color};
        color: {text_color};
        border-radius: {border_radius}px;
        padding: 8px;
    }}

    .linux-ai-main #capture-button {{
        background-color: {tertiary_color};
        color: {text_color};
        border-radius: {border_radius}px;
        padding: 8px;
    }}

    .linux-ai-main .danger {{
        background-color: #f44336;
        color: {danger_text};
    }}

    .linux-ai-main textview text {{
        background-color: {bg_color};
        color: {text_color};
        font-family: "{font_family}";
        font-size: {font_size}pt;
    }}

    .linux-ai-main entry {{
        background-color: {secondary_color};
        color: {text_color};
        border: 1px solid {border_color};
        border-radius: {border_radius}px;
        padding: 8px;
        font-family: "{font_family}";
        font-size: {font_size}pt;
    }}

    .linux-ai-main entry:focus {{
        border-color: {accent_color};
    }}

    .linux-ai-main scrolledwindow {{
        border: none;
    }}

    .linux-ai-main scrollbar {{
        background-color: {tertiary_color};
    }}

    .linux-ai-main scrollbar slider {{
        background-color: {border_color};
        border-radius: {border_radius}px;
    }}

    .linux-ai-main scrollbar slider:hover {{
        background-color: {accent_color};
    }}
    """
    return css


def get_chat_style_colors(colors: Dict, theme_info: Optional[Dict]) -> Dict[str, str]:
    """Get validated chat message colors from theme.

    Returns a dict with keys: user, ai, system, code, code_background
    """
    syntax_colors: Dict = {}
    if theme_info:
        syntax_colors = theme_info.get('syntax_highlighting', {}) or {}

    text_color = safe_color(colors.get('text'), '#e0e0e0')
    secondary_color = safe_color(colors.get('secondary'), '#2d2d2d')

    return {
        'user': safe_color(syntax_colors.get('user_message'), text_color),
        'ai': safe_color(syntax_colors.get('ai_message'), text_color),
        'system': safe_color(syntax_colors.get('system_message'), text_color),
        'code': safe_color(syntax_colors.get('code'), text_color),
        'code_background': secondary_color,
    }


def build_gtk_css(colors: Dict, theme_info: Optional[Dict],
                  font_family: str, font_size: int, border_radius: int) -> str:
    """Build the exact GTK CSS string used by MainWindow._setup_style.

    Extracted verbatim from main_window.py so the GTK track and the
    extracted module share a single source of truth. The golden test
    (tests/test_theme_golden.py) pins this output.

    Args:
        colors: Theme colors dict (background, text, accent, secondary, tertiary)
        theme_info: Optional theme info (unused for now, kept for parity)
        font_family: Resolved font family (already validated)
        font_size: Resolved font size in pt (already validated)
        border_radius: Resolved border radius in px (already validated)

    Returns:
        CSS string for Gtk.CssProvider.load_from_data
    """
    # Usar valores validados do theme (ver safe_color/safe_font_family)
    bg_color = safe_color(colors.get('background'), '#1e1e1e')
    text_color = safe_color(colors.get('text'), '#e0e0e0')
    accent_color = safe_color(colors.get('accent'), '#4CAF50')
    secondary_color = safe_color(colors.get('secondary'), '#2d2d2d')
    tertiary_color = safe_color(colors.get('tertiary'), '#252525')
    accent_text = contrasting_text_color(accent_color)
    expert_text = contrasting_text_color('#2196F3')
    danger_text = contrasting_text_color('#f44336')

    css = f"""
        .linux-ai-main #main-box {{
            background-color: {bg_color};
            color: {text_color};
            border-radius: {border_radius}px;
            padding: 10px;
            margin: 5px;
        }}

        .linux-ai-main #header {{
            background-color: {secondary_color};
            border-radius: {border_radius}px {border_radius}px 0 0;
            padding: 8px;
            margin-bottom: 10px;
        }}

        .linux-ai-main #chat-area {{
            background-color: {tertiary_color};
            border-radius: 5px;
            padding: 10px;
            margin-bottom: 10px;
            min-height: 300px;
        }}

        .linux-ai-main #input-area {{
            background-color: {secondary_color};
            border-radius: 5px;
            padding: 10px;
        }}

        .linux-ai-main #main-box textview,
        .linux-ai-main #main-box textview text {{
            font-family: {font_family};
            font-size: {font_size}pt;
            background-color: {tertiary_color};
            color: {text_color};
            border: none;
            padding: 5px;
        }}

        .linux-ai-main #main-box button {{
            background-color: {accent_color};
            background-image: none;
            color: {accent_text};
            text-shadow: none;
            -gtk-icon-shadow: none;
            box-shadow: none;
            border-radius: 5px;
            padding: 5px 10px;
            font-family: {font_family};
            font-size: 10pt;
            border: none;
            min-width: 32px;
        }}

        .linux-ai-main #main-box button:hover {{
            opacity: 0.9;
        }}

        .linux-ai-main #main-box button:active {{
            opacity: 0.7;
        }}

        .linux-ai-main #main-box button.expert {{
            background-color: #2196F3;
            color: {expert_text};
        }}

        .linux-ai-main #main-box button.expert:hover {{
            background-color: #0b7dda;
        }}

        .linux-ai-main #main-box button.danger {{
            background-color: #f44336;
            color: {danger_text};
        }}

        .linux-ai-main #main-box button.danger:hover {{
            background-color: #da190b;
        }}

        .linux-ai-main #main-box button:disabled {{
            background-color: {secondary_color};
            color: {text_color};
            opacity: 0.6;
        }}

        .linux-ai-main #main-box entry {{
            background-color: {secondary_color};
            background-image: none;
            color: {text_color};
            border-radius: 5px;
            padding: 5px;
            font-family: {font_family};
            font-size: {font_size}pt;
            border: 1px solid transparent;
            box-shadow: none;
            caret-color: {text_color};
        }}

        .linux-ai-main #main-box entry:focus {{
            border: 1px solid {accent_color};
        }}

        .linux-ai-main #main-box entry selection,
        .linux-ai-main #main-box textview text selection {{
            background-color: {accent_color};
            color: {accent_text};
        }}

        .linux-ai-main #main-box scrolledwindow {{
            background-color: {tertiary_color};
            border-radius: 5px;
            border: none;
        }}

        .linux-ai-main #main-box .loading {{
            opacity: 0.7;
            font-style: italic;
        }}

        .linux-ai-main #main-box .expert-mode {{
            border-left: 3px solid #2196F3;
            padding-left: 10px;
        }}
        """
    return css
