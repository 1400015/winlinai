"""Tests for Windows screenshot capture (src/windows_screenshot.py)."""
import unittest
from unittest.mock import patch

from src.windows_screenshot import (
    is_windows,
    ScreenshotError,
    ScreenshotCancelled,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    MAX_IMAGE_PIXELS,
)


class TestIsWindows(unittest.TestCase):
    def test_returns_bool(self):
        self.assertIsInstance(is_windows(), bool)


class TestConstants(unittest.TestCase):
    def test_max_image_bytes(self):
        self.assertEqual(MAX_IMAGE_BYTES, 64 * 1024 * 1024)

    def test_max_image_edge(self):
        self.assertEqual(MAX_IMAGE_EDGE, 16384)

    def test_max_image_pixels(self):
        self.assertEqual(MAX_IMAGE_PIXELS, 32 * 1000 * 1000)


class TestCaptureScreen(unittest.TestCase):
    def test_not_windows_raises_cancelled(self):
        with patch('src.windows_screenshot.is_windows', return_value=False):
            from src.windows_screenshot import capture_screen
            with self.assertRaises(ScreenshotCancelled):
                capture_screen()

    def test_pillow_missing_raises_error(self):
        with patch('src.windows_screenshot.is_windows', return_value=True):
            with patch.dict('sys.modules', {'PIL': None, 'PIL.ImageGrab': None}):
                from src.windows_screenshot import capture_screen
                with self.assertRaises(ScreenshotError) as ctx:
                    capture_screen()
                self.assertIn("Pillow", str(ctx.exception))


class TestScreenshotError(unittest.TestCase):
    def test_is_runtime_error(self):
        self.assertTrue(issubclass(ScreenshotError, RuntimeError))

    def test_cancelled_is_screenshot_error(self):
        self.assertTrue(issubclass(ScreenshotCancelled, ScreenshotError))


if __name__ == "__main__":
    unittest.main()
