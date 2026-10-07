"""Tests for main window theme management (src/main_window_themes.py)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.main_window_themes import (
    PREDEFINED_THEMES,
    THEME_NAME_RE,
    get_user_themes_dir,
    create_theme,
    remove_theme,
    populate_themes_list,
)


class TestThemeNamePattern(unittest.TestCase):
    def test_valid_names(self):
        self.assertTrue(THEME_NAME_RE.fullmatch("dark"))
        self.assertTrue(THEME_NAME_RE.fullmatch("my-theme"))
        self.assertTrue(THEME_NAME_RE.fullmatch("my_theme"))
        self.assertTrue(THEME_NAME_RE.fullmatch("Theme123"))
        self.assertTrue(THEME_NAME_RE.fullmatch("a"))

    def test_invalid_names(self):
        self.assertFalse(THEME_NAME_RE.fullmatch(""))
        self.assertFalse(THEME_NAME_RE.fullmatch("my theme"))  # space
        self.assertFalse(THEME_NAME_RE.fullmatch("../etc/passwd"))  # path traversal
        self.assertFalse(THEME_NAME_RE.fullmatch("theme.json"))  # dot
        self.assertFalse(THEME_NAME_RE.fullmatch("a" * 65))  # too long


class TestPredefinedThemes(unittest.TestCase):
    def test_contains_builtin_themes(self):
        self.assertIn("dark", PREDEFINED_THEMES)
        self.assertIn("light", PREDEFINED_THEMES)
        self.assertIn("dracula", PREDEFINED_THEMES)
        self.assertIn("solarized-dark", PREDEFINED_THEMES)


class TestGetUserThemesDir(unittest.TestCase):
    def test_returns_path(self):
        path = get_user_themes_dir()
        self.assertIsInstance(path, Path)
        self.assertIn("linux_ai_assistant", str(path))
        self.assertIn("themes", str(path))


class TestCreateTheme(unittest.TestCase):
    def setUp(self):
        self.window = Mock()
        self.window.show_notification = Mock()

    def test_invalid_name(self):
        result = create_theme(self.window, "../evil", "desc", {}, {})
        self.assertFalse(result)
        self.window.show_notification.assert_called()

    def test_valid_theme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('src.main_window_themes.get_user_themes_dir',
                       return_value=Path(tmpdir)):
                result = create_theme(
                    self.window,
                    "my-theme",
                    "My custom theme",
                    {"background": "#000000", "text": "#ffffff",
                     "accent": "#ff0000", "secondary": "#333333",
                     "tertiary": "#222222"},
                    {"font_family": "Monospace", "font_size": 12,
                     "border_radius": 10}
                )
                self.assertTrue(result)
                theme_file = Path(tmpdir) / "my-theme.json"
                self.assertTrue(theme_file.exists())
                data = json.loads(theme_file.read_text())
                self.assertEqual(data["name"], "my-theme")
                self.assertEqual(data["colors"]["background"], "#000000")

    def test_save_failure(self):
        with patch('src.main_window_themes.get_user_themes_dir',
                   side_effect=OSError("permission denied")):
            result = create_theme(self.window, "test", "desc", {}, {})
            self.assertFalse(result)
            self.window.show_notification.assert_called()


class TestRemoveTheme(unittest.TestCase):
    def setUp(self):
        self.window = Mock()
        self.window.show_notification = Mock()

    def test_predefined_theme_rejected(self):
        result = remove_theme(self.window, "dark")
        self.assertFalse(result)
        self.window.show_notification.assert_called()

    def test_remove_existing_theme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            themes_dir = Path(tmpdir)
            theme_file = themes_dir / "custom.json"
            theme_file.write_text('{"name": "custom"}')

            with patch('src.main_window_themes.get_user_themes_dir',
                       return_value=themes_dir):
                result = remove_theme(self.window, "custom")
                self.assertTrue(result)
                self.assertFalse(theme_file.exists())

    def test_remove_nonexistent_theme(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('src.main_window_themes.get_user_themes_dir',
                       return_value=Path(tmpdir)):
                result = remove_theme(self.window, "nonexistent")
                self.assertFalse(result)

    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            themes_dir = Path(tmpdir)
            # Create a file outside themes_dir
            outside_file = themes_dir.parent / "evil.json"
            outside_file.write_text('{"name": "evil"}')

            with patch('src.main_window_themes.get_user_themes_dir',
                       return_value=themes_dir):
                # Try to remove with path traversal
                result = remove_theme(self.window, "../evil")
                self.assertFalse(result)
                self.assertTrue(outside_file.exists())  # not deleted


class TestPopulateThemesList(unittest.TestCase):
    def test_populate(self):
        window = Mock()
        window.config.get_available_themes.return_value = ["dark", "light", "custom"]
        window.config.get_theme_info.side_effect = lambda name: {
            "name": name.title(),
            "description": f"Description for {name}",
        } if name != "custom" else None

        # Mock the listbox
        listbox = Mock()
        listbox.get_children.return_value = []
        window.themes_listbox = listbox

        # This requires GTK, so we just test that it doesn't crash
        # when GTK is not available, it should raise ImportError
        try:
            populate_themes_list(window)
        except ImportError:
            # GTK not available in test environment
            pass


if __name__ == "__main__":
    unittest.main()
