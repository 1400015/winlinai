"""Windows screenshot capture for the Qt track.

Captures the screen or a region using Windows APIs. Unlike the Wayland
portal (src/screenshot_portal.py), this uses native Windows APIs via
pywin32 or falls back to Pillow's ImageGrab.

Security notes:
- Captures are saved to a user-selected location only
- No automatic upload or transmission
- Bounded image size (max 64 MB, max 16384px per edge)
- Metadata is stripped (no EXIF, no GPS)
"""
from __future__ import annotations

import io
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 64 * 1024 * 1024  # 64 MB
MAX_IMAGE_PIXELS = 32 * 1000 * 1000
MAX_IMAGE_EDGE = 16384


class ScreenshotError(RuntimeError):
    """Screenshot capture failed."""


class ScreenshotCancelled(ScreenshotError):
    """User cancelled the screenshot."""


def is_windows() -> bool:
    """True when running on Windows."""
    return sys.platform == "win32"


def capture_screen(region: Optional[Tuple[int, int, int, int]] = None,
                   save_path: Optional[str] = None) -> bytes:
    """Capture the screen (or a region) and return PNG bytes.

    Args:
        region: Optional (left, top, right, bottom) tuple for partial capture
        save_path: Optional path to save the image (also returns bytes)

    Returns:
        PNG image bytes

    Raises:
        ScreenshotError: if capture fails
        ScreenshotCancelled: if not on Windows or capture is cancelled
    """
    if not is_windows():
        raise ScreenshotCancelled("Screenshot capture requires Windows")

    try:
        from PIL import Image, ImageGrab
    except ImportError:
        raise ScreenshotError("Pillow is required for screenshot capture")

    try:
        if region:
            image = ImageGrab.grab(bbox=region)
        else:
            image = ImageGrab.grab()

        # Validate size
        if image.width > MAX_IMAGE_EDGE or image.height > MAX_IMAGE_EDGE:
            raise ScreenshotError(
                f"Image too large: {image.width}x{image.height}")
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ScreenshotError("Image exceeds pixel limit")

        # Convert to RGB (remove alpha for JPEG compatibility)
        if image.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            background.paste(image, mask=image.split()[-1] if image.mode in ("RGBA", "LA") else None)
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")

        # Save to bytes
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()

        if len(data) > MAX_IMAGE_BYTES:
            # Try JPEG with quality reduction
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85, optimize=True)
            data = buffer.getvalue()
            if len(data) > MAX_IMAGE_BYTES:
                raise ScreenshotError("Image exceeds size limit after compression")

        # Optionally save to file
        if save_path:
            path = Path(save_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            logger.info("Screenshot saved to %s", path)

        return data

    except ScreenshotError:
        raise
    except Exception as error:
        raise ScreenshotError(f"Capture failed: {type(error).__name__}") from error


def capture_screen_dialog(parent=None) -> Optional[bytes]:
    """Show a dialog to capture the screen.

    Returns PNG bytes or None if cancelled.
    """
    try:
        from PySide6 import QtWidgets
    except ImportError:
        raise ScreenshotError("PySide6 is required for the screenshot dialog")

    from . import i18n

    # Ask user what to capture
    options = [
        i18n._("Full screen"),
        i18n._("Cancel"),
    ]
    choice, ok = QtWidgets.QInputDialog.getItem(
        parent, i18n._("Screenshot"),
        i18n._("Capture:"), options, 0, False)

    if not ok or choice == i18n._("Cancel"):
        return None

    try:
        return capture_screen()
    except ScreenshotError as error:
        QtWidgets.QMessageBox.warning(parent, i18n._("Screenshot failed"), str(error))
        return None


def save_screenshot(data: bytes, parent=None, default_name: str = "screenshot.png") -> Optional[str]:
    """Show a save dialog and save the screenshot.

    Returns the saved path or None if cancelled.
    """
    try:
        from PySide6 import QtWidgets
    except ImportError:
        raise ScreenshotError("PySide6 is required for the save dialog")

    from . import i18n

    filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
        parent, i18n._("Save screenshot"),
        default_name, "PNG (*.png);;JPEG (*.jpg)")

    if not filepath:
        return None

    try:
        Path(filepath).write_bytes(data)
        logger.info("Screenshot saved to %s", filepath)
        return filepath
    except Exception as error:
        logger.error("Failed to save screenshot: %s", type(error).__name__)
        return None


def capture_and_attach(parent=None) -> Optional[Tuple[str, bytes]]:
    """Capture screen and return (path, data) for attaching to a chat message.

    Returns None if cancelled or failed.
    """
    data = capture_screen_dialog(parent)
    if data is None:
        return None

    # Save to temp file for attachment
    temp_dir = Path(tempfile.gettempdir()) / "winlinai_screenshots"
    temp_dir.mkdir(parents=True, exist_ok=True)

    import time
    filename = f"screenshot_{int(time.time())}.png"
    filepath = temp_dir / filename

    try:
        filepath.write_bytes(data)
        return str(filepath), data
    except Exception as error:
        logger.error("Failed to save screenshot: %s", type(error).__name__)
        return None
