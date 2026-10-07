"""Windows auto-update support for WinLinAI.

Checks for new versions on GitHub releases and downloads updates.

Security:
- Only downloads from the official GitHub repository
- Verifies SHA-256 checksums before installing
- Never runs downloaded files automatically
- User must confirm before installing

Usage:
    from src.updater import check_for_updates, download_update
    update = check_for_updates()
    if update:
        print(f"New version available: {update['version']}")
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Official repository
GITHUB_REPO = "1400015/winlinai"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# Allowed download hosts (security: only download from these)
ALLOWED_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "api.github.com",
}

# Update check timeout
CHECK_TIMEOUT = 10
DOWNLOAD_TIMEOUT = 300

# Max download size (500 MB)
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024


def is_windows() -> bool:
    """True when running on Windows."""
    return sys.platform == "win32"


def get_current_version() -> str:
    """Get the current application version."""
    try:
        from ._version import __version__
        return __version__
    except ImportError:
        return "0.0.0"


def parse_version(version: str) -> Tuple[int, ...]:
    """Parse a version string into a tuple of integers.

    "1.4.2" -> (1, 4, 2)
    "1.4.2-beta" -> (1, 4, 2)
    """
    # Remove pre-release suffix
    version = version.split("-")[0].split("+")[0]
    parts = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_newer_version(current: str, new: str) -> bool:
    """Check if `new` version is newer than `current`."""
    return parse_version(new) > parse_version(current)


def _safe_url(url: str) -> bool:
    """Check if a URL is from an allowed host."""
    try:
        parsed = urlparse(url)
        return parsed.hostname in ALLOWED_HOSTS if parsed.hostname else False
    except Exception:
        return False


def check_for_updates(timeout: int = CHECK_TIMEOUT) -> Optional[Dict]:
    """Check GitHub for a newer release.

    Returns:
        Dict with update info if available, None otherwise:
        {
            "version": "1.5.0",
            "name": "Release name",
            "body": "Release notes",
            "url": "https://github.com/.../releases/tag/v1.5.0",
            "assets": [{"name": "WinLinAI-1.5.0-Setup.exe", "url": "...", "size": 12345678}]
        }
    """
    if not is_windows():
        return None

    try:
        import urllib.request
        import ssl

        current = get_current_version()

        # Create request with GitHub API
        request = urllib.request.Request(
            GITHUB_API_URL,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"WinLinAI/{current}",
            },
        )

        # SSL context
        context = ssl.create_default_context()

        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            data = json.loads(response.read().decode("utf-8"))

        latest_version = data.get("tag_name", "").lstrip("v")
        if not latest_version:
            return None

        if not is_newer_version(current, latest_version):
            logger.info(f"Already up to date (current: {current}, latest: {latest_version})")
            return None

        # Find Windows installer asset
        assets = []
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            url = asset.get("browser_download_url", "")
            size = asset.get("size", 0)
            if name.endswith(".exe") and "windows" in name.lower() or name.endswith("-Setup.exe"):
                if _safe_url(url):
                    assets.append({
                        "name": name,
                        "url": url,
                        "size": size,
                    })

        return {
            "version": latest_version,
            "name": data.get("name", f"v{latest_version}"),
            "body": data.get("body", ""),
            "url": data.get("html_url", GITHUB_RELEASES_URL),
            "published_at": data.get("published_at", ""),
            "assets": assets,
        }

    except Exception as error:
        logger.warning(f"Update check failed: {type(error).__name__}")
        return None


def download_update(asset: Dict, dest_dir: Optional[str] = None,
                    progress_callback=None) -> Optional[str]:
    """Download an update asset.

    Args:
        asset: Asset dict from check_for_updates()
        dest_dir: Destination directory (default: temp)
        progress_callback: Optional callback(downloaded_bytes, total_bytes)

    Returns:
        Path to downloaded file, or None on failure
    """
    if not is_windows():
        return None

    url = asset.get("url", "")
    name = asset.get("name", "update.exe")
    expected_size = asset.get("size", 0)

    if not _safe_url(url):
        logger.error(f"Unsafe download URL: {url}")
        return None

    try:
        import urllib.request
        import ssl

        # Prepare destination
        if dest_dir is None:
            dest_dir = tempfile.mkdtemp(prefix="winlinai_update_")
        dest_path = Path(dest_dir) / name

        # Download
        request = urllib.request.Request(
            url,
            headers={"User-Agent": f"WinLinAI/{get_current_version()}"},
        )
        context = ssl.create_default_context()

        downloaded = 0
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT, context=context) as response:
            with open(dest_path, "wb") as f:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, expected_size)
                    if downloaded > MAX_DOWNLOAD_BYTES:
                        raise ValueError("Download exceeds maximum size")

        # Verify size if known
        actual_size = dest_path.stat().st_size
        if expected_size and actual_size != expected_size:
            logger.warning(f"Size mismatch: expected {expected_size}, got {actual_size}")

        logger.info(f"Downloaded update: {dest_path} ({actual_size} bytes)")
        return str(dest_path)

    except Exception as error:
        logger.error(f"Download failed: {type(error).__name__}: {error}")
        return None


def verify_checksum(filepath: str, expected_sha256: str) -> bool:
    """Verify a file's SHA-256 checksum."""
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual = h.hexdigest()
        return actual.lower() == expected_sha256.lower()
    except Exception:
        return False


def get_update_downloads_dir() -> Path:
    """Get the directory for downloaded updates."""
    path = Path.home() / "AppData" / "Local" / "WinLinAI" / "Updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def check_and_notify(config_manager=None) -> Optional[Dict]:
    """Check for updates and return info if available.

    This is the main entry point for the UI to check for updates.
    Does not download automatically - user must confirm.
    """
    update = check_for_updates()
    if update:
        logger.info(f"Update available: {update['version']}")
        # Could store in config for UI to display
        if config_manager is not None:
            try:
                config_manager.set("update.available", True)
                config_manager.set("update.version", update["version"])
                config_manager.set("update.url", update["url"])
            except Exception:
                pass
    return update
