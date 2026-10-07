"""Golden test for the GTK CSS extraction (improvement plan task B.1).

Pins the exact CSS that MainWindow._setup_style produced before the
extraction, so the refactoring to theme_utils.build_gtk_css cannot
silently change a single byte of the generated stylesheet.

The "expected" template below is a verbatim copy of the inline CSS from
main_window.py at the time of extraction. If the CSS is intentionally
changed in the future, update build_gtk_css AND this template together.
"""
import json
import unittest
from pathlib import Path

from src.theme_utils import (
    build_gtk_css,
    safe_color,
    safe_font_family,
    safe_number,
    contrasting_text_color,
    get_chat_style_colors,
)

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
BUILTIN_THEMES = ["dark", "light", "dracula", "solarized-dark"]


def _expected_css(colors, font_family, font_size, border_radius):
    """Verbatim copy of the inline CSS from main_window.py (pre-extraction).

    This is the characterization test's source of truth. Do not "fix" it
    to match build_gtk_css — if they differ, the extraction was unfaithful.
    """
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


def _load_theme(name):
    """Load a theme JSON and return (colors, theme_info, font_family, font_size, border_radius)."""
    path = THEMES_DIR / f"{name}.json"
    theme_info = json.loads(path.read_text(encoding="utf-8"))
    colors = theme_info.get("colors", {})
    theme_ui = theme_info.get("ui", {}) or {}
    # Mirror the fallback chain from MainWindow._setup_style
    font_family = safe_font_family(theme_ui.get("font_family"), "Monospace")
    font_size = safe_number(theme_ui.get("font_size"), 12, int, minimum=4, maximum=72)
    border_radius = safe_number(theme_ui.get("border_radius"), 10, int, minimum=0, maximum=64)
    return colors, theme_info, font_family, font_size, border_radius


class TestGtkCssGolden(unittest.TestCase):
    """build_gtk_css must produce byte-identical CSS to the pre-extraction inline template."""

    def test_all_builtin_themes_match_golden(self):
        for theme_name in BUILTIN_THEMES:
            with self.subTest(theme=theme_name):
                colors, theme_info, font_family, font_size, border_radius = _load_theme(theme_name)
                expected = _expected_css(colors, font_family, font_size, border_radius)
                actual = build_gtk_css(colors, theme_info, font_family, font_size, border_radius)
                self.assertEqual(expected, actual,
                                 f"CSS mismatch for theme '{theme_name}'. "
                                 f"The extraction changed the generated stylesheet.")

    def test_css_contains_core_selectors(self):
        colors, theme_info, _, _, _ = _load_theme("dark")
        css = build_gtk_css(colors, theme_info, "Monospace", 12, 10)
        for selector in ("#main-box", "#header", "#chat-area", "#input-area",
                         "button.expert", "button.danger", ".loading", ".expert-mode"):
            self.assertIn(selector, css)

    def test_chat_style_colors_match_inline_logic(self):
        """get_chat_style_colors must match what _setup_style computed inline."""
        for theme_name in BUILTIN_THEMES:
            with self.subTest(theme=theme_name):
                colors, theme_info, _, _, _ = _load_theme(theme_name)
                syntax_colors = (theme_info or {}).get("syntax_highlighting", {}) or {}
                text_color = safe_color(colors.get("text"), "#e0e0e0")
                secondary_color = safe_color(colors.get("secondary"), "#2d2d2d")
                expected = {
                    "user": safe_color(syntax_colors.get("user_message"), text_color),
                    "ai": safe_color(syntax_colors.get("ai_message"), text_color),
                    "system": safe_color(syntax_colors.get("system_message"), text_color),
                    "code": safe_color(syntax_colors.get("code"), text_color),
                    "code_background": secondary_color,
                }
                actual = get_chat_style_colors(colors, theme_info)
                self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
