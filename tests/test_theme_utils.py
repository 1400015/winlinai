"""Tests for theme utilities (src/theme_utils.py)."""
import unittest

from src.theme_utils import (
    safe_color,
    safe_font_family,
    contrasting_text_color,
    safe_number,
    build_css,
    get_chat_style_colors,
)


class TestSafeColor(unittest.TestCase):
    def test_valid_hex_6(self):
        self.assertEqual(safe_color("#ff0000"), "#ff0000")
        self.assertEqual(safe_color("#FF0000"), "#FF0000")

    def test_valid_hex_3(self):
        self.assertEqual(safe_color("#f00"), "#f00")

    def test_invalid_returns_fallback(self):
        self.assertEqual(safe_color("red"), "#1e1e1e")
        self.assertEqual(safe_color("#ff0000ff"), "#1e1e1e")  # RGBA not supported
        self.assertEqual(safe_color(""), "#1e1e1e")

    def test_none_returns_fallback(self):
        self.assertEqual(safe_color(None), "#1e1e1e")

    def test_custom_fallback(self):
        self.assertEqual(safe_color("invalid", "#ffffff"), "#ffffff")

    def test_strips_whitespace(self):
        self.assertEqual(safe_color("  #ff0000  "), "#ff0000")


class TestSafeFontFamily(unittest.TestCase):
    def test_valid_font(self):
        self.assertEqual(safe_font_family("Monospace"), "Monospace")
        self.assertEqual(safe_font_family("Sans Serif"), "Sans Serif")
        self.assertEqual(safe_font_family("Arial, sans-serif"), "Arial, sans-serif")

    def test_invalid_returns_fallback(self):
        self.assertEqual(safe_font_family(""), "Monospace")
        self.assertEqual(safe_font_family("font; malicious"), "Monospace")
        self.assertEqual(safe_font_family("<script>"), "Monospace")

    def test_none_returns_fallback(self):
        self.assertEqual(safe_font_family(None), "Monospace")


class TestContrastingTextColor(unittest.TestCase):
    def test_dark_background_returns_white(self):
        self.assertEqual(contrasting_text_color("#000000"), "#ffffff")
        self.assertEqual(contrasting_text_color("#1e1e1e"), "#ffffff")

    def test_light_background_returns_black(self):
        self.assertEqual(contrasting_text_color("#ffffff"), "#000000")
        self.assertEqual(contrasting_text_color("#f0f0f0"), "#000000")

    def test_accent_green(self):
        # #4CAF50 is medium green, should return white or black
        result = contrasting_text_color("#4CAF50")
        self.assertIn(result, ("#000000", "#ffffff"))


class TestSafeNumber(unittest.TestCase):
    def test_valid_int(self):
        self.assertEqual(safe_number("12", 10, int), 12)
        self.assertEqual(safe_number(12, 10, int), 12)

    def test_valid_float(self):
        self.assertEqual(safe_number("1.5", 1.0, float), 1.5)

    def test_invalid_returns_fallback(self):
        self.assertEqual(safe_number("abc", 10, int), 10)
        self.assertEqual(safe_number(None, 10, int), 10)

    def test_minimum_bound(self):
        self.assertEqual(safe_number("3", 10, int, minimum=5), 10)
        self.assertEqual(safe_number("7", 10, int, minimum=5), 7)

    def test_maximum_bound(self):
        self.assertEqual(safe_number("100", 10, int, maximum=50), 10)
        self.assertEqual(safe_number("30", 10, int, maximum=50), 30)


class TestBuildCSS(unittest.TestCase):
    def test_basic_css(self):
        colors = {
            "background": "#1e1e1e",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        }
        css = build_css(colors, None)
        self.assertIn(".linux-ai-main", css)
        self.assertIn("#1e1e1e", css)
        self.assertIn("#4CAF50", css)

    def test_css_with_theme_info(self):
        colors = {
            "background": "#1e1e1e",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        }
        theme_info = {
            "ui": {"font_family": "Monospace", "font_size": 14, "border_radius": 8},
            "syntax_highlighting": {"user_message": "#ff0000"},
        }
        css = build_css(colors, theme_info)
        self.assertIn("Monospace", css)
        self.assertIn("14pt", css)
        self.assertIn("8px", css)

    def test_css_injection_prevented(self):
        """Invalid colors should not be injected into CSS."""
        colors = {
            "background": "red; malicious: code",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        }
        css = build_css(colors, None)
        self.assertNotIn("malicious", css)
        self.assertIn("#1e1e1e", css)  # fallback


class TestGetChatStyleColors(unittest.TestCase):
    def test_basic_colors(self):
        colors = {
            "background": "#1e1e1e",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        }
        result = get_chat_style_colors(colors, None)
        self.assertIn("user", result)
        self.assertIn("ai", result)
        self.assertIn("system", result)
        self.assertIn("code", result)
        self.assertIn("code_background", result)

    def test_with_syntax_colors(self):
        colors = {
            "background": "#1e1e1e",
            "text": "#e0e0e0",
            "accent": "#4CAF50",
            "secondary": "#2d2d2d",
            "tertiary": "#252525",
            "border": "#3d3d3d",
        }
        theme_info = {
            "syntax_highlighting": {
                "user_message": "#ff0000",
                "ai_message": "#00ff00",
            }
        }
        result = get_chat_style_colors(colors, theme_info)
        self.assertEqual(result["user"], "#ff0000")
        self.assertEqual(result["ai"], "#00ff00")


if __name__ == "__main__":
    unittest.main()
