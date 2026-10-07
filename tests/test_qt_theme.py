"""Tests for Qt theme support (src/qt_theme.py)."""
import unittest
from unittest.mock import Mock

from src.qt_theme import (
    available_themes,
    load_theme,
    theme_to_stylesheet,
    _lighten,
    _darken,
    _hex_to_rgb,
    _rgb_to_hex,
    get_current_theme_name,
    set_current_theme,
    DEFAULT_THEME,
)


class TestAvailableThemes(unittest.TestCase):
    def test_returns_list(self):
        themes = available_themes()
        self.assertIsInstance(themes, list)

    def test_includes_default(self):
        themes = available_themes()
        # Should at least have the default or themes from the themes/ dir
        self.assertTrue(len(themes) > 0)


class TestLoadTheme(unittest.TestCase):
    def test_load_default_theme(self):
        theme = load_theme()
        self.assertIn("name", theme)
        self.assertIn("colors", theme)
        self.assertIn("ui", theme)

    def test_load_named_theme(self):
        theme = load_theme("dark")
        self.assertIsInstance(theme, dict)

    def test_load_nonexistent_falls_back(self):
        theme = load_theme("nonexistent-theme-xyz")
        # Should fall back to default or minimal
        self.assertIsInstance(theme, dict)
        self.assertIn("colors", theme)

    def test_theme_has_required_keys(self):
        theme = load_theme()
        self.assertIn("background", theme["colors"])
        self.assertIn("text", theme["colors"])
        self.assertIn("accent", theme["colors"])


class TestColorHelpers(unittest.TestCase):
    def test_hex_to_rgb(self):
        self.assertEqual(_hex_to_rgb("#ff0000"), (255, 0, 0))
        self.assertEqual(_hex_to_rgb("#00ff00"), (0, 255, 0))
        self.assertEqual(_hex_to_rgb("#0000ff"), (0, 0, 255))
        self.assertEqual(_hex_to_rgb("#fff"), (255, 255, 255))

    def test_rgb_to_hex(self):
        self.assertEqual(_rgb_to_hex(255, 0, 0), "#ff0000")
        self.assertEqual(_rgb_to_hex(0, 255, 0), "#00ff00")
        self.assertEqual(_rgb_to_hex(0, 0, 255), "#0000ff")

    def test_lighten(self):
        result = _lighten("#808080", 0.5)
        # Should be lighter than #808080
        r, g, b = _hex_to_rgb(result)
        self.assertGreater(r, 128)
        self.assertGreater(g, 128)
        self.assertGreater(b, 128)

    def test_darken(self):
        result = _darken("#808080", 0.5)
        # Should be darker than #808080
        r, g, b = _hex_to_rgb(result)
        self.assertLess(r, 128)
        self.assertLess(g, 128)
        self.assertLess(b, 128)

    def test_lighten_invalid_returns_original(self):
        self.assertEqual(_lighten("invalid", 0.5), "invalid")

    def test_darken_invalid_returns_original(self):
        self.assertEqual(_darken("invalid", 0.5), "invalid")


class TestThemeToStylesheet(unittest.TestCase):
    def test_generates_qss(self):
        theme = load_theme()
        qss = theme_to_stylesheet(theme)
        self.assertIsInstance(qss, str)
        self.assertIn("QWidget", qss)
        self.assertIn("QPushButton", qss)
        self.assertIn("QLineEdit", qss)

    def test_includes_colors(self):
        theme = {
            "name": "Test",
            "colors": {
                "background": "#112233",
                "text": "#aabbcc",
                "accent": "#ff0000",
                "secondary": "#445566",
                "tertiary": "#778899",
                "border": "#aabbcc",
            },
            "ui": {
                "font_family": "Test Font",
                "font_size": 12,
                "border_radius": 8,
            },
        }
        qss = theme_to_stylesheet(theme)
        self.assertIn("#112233", qss)  # background
        self.assertIn("#aabbcc", qss)  # text
        self.assertIn("#ff0000", qss)  # accent

    def test_handles_minimal_theme(self):
        theme = {"name": "Minimal", "colors": {}, "ui": {}}
        qss = theme_to_stylesheet(theme)
        self.assertIsInstance(qss, str)
        # Should use default colors
        self.assertIn("#1e1e1e", qss)  # default background


class TestThemeConfig(unittest.TestCase):
    def test_get_current_theme_name_default(self):
        config = Mock()
        config.get = Mock(return_value="dark")
        self.assertEqual(get_current_theme_name(config), "dark")

    def test_get_current_theme_name_fallback(self):
        config = Mock()
        config.get = Mock(side_effect=Exception("broken"))
        self.assertEqual(get_current_theme_name(config), DEFAULT_THEME)

    def test_set_current_theme(self):
        config = Mock()
        self.assertTrue(set_current_theme(config, "light"))
        config.set.assert_called_once_with("ui.theme", "light")

    def test_set_current_theme_failure(self):
        config = Mock()
        config.set = Mock(side_effect=Exception("readonly"))
        self.assertFalse(set_current_theme(config, "light"))


class TestMinimalDarkTheme(unittest.TestCase):
    def test_minimal_theme_structure(self):
        from src.qt_theme import _minimal_dark_theme
        theme = _minimal_dark_theme()
        self.assertIn("name", theme)
        self.assertIn("colors", theme)
        self.assertIn("ui", theme)
        self.assertIn("background", theme["colors"])


if __name__ == "__main__":
    unittest.main()
