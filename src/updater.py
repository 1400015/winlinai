"""Windows update check for WinLinAI.

The application reports a newer GitHub release and opens that release page.
It does not download or run an installer.

Security:
- The release page must be HTTPS on this repository
- A failed check is never reported as up to date
- Nothing is installed automatically
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Dict, Tuple
from urllib.parse import unquote, urlparse

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
    """Check if a URL is HTTPS on an allowed host."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and host in ALLOWED_HOSTS
    except Exception:
        return False


def official_release_url(url: str) -> str:
    """Keep an HTTPS page of this repository. Anything else uses the releases page."""
    try:
        parsed = urlparse(url or "")
        path = unquote(parsed.path or "").replace("\\", "/")
        prefix = "/" + GITHUB_REPO
        host = (parsed.hostname or "").lower()
        segments = path.split("/")
        on_repo = path == prefix or path.startswith(prefix + "/")
        if (parsed.scheme == "https"
                and host == "github.com"
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and on_repo
                and "." not in segments
                and ".." not in segments):
            return url
    except Exception:
        pass
    return GITHUB_RELEASES_URL


def _is_windows_installer_asset(name: str) -> bool:
    """True if the asset name looks like a Windows installer for WinLinAI.

    Pure function so the matching policy is fully testable.
    Accepts .exe files whose name mentions windows, winlinai or setup.
    Rejects everything else (deb, rpm, dmg, random exes).
    """
    if not isinstance(name, str):
        return False
    lowered = name.lower()
    if not lowered.endswith(".exe"):
        return False
    return any(keyword in lowered for keyword in ("windows", "winlinai", "setup"))


def check_for_updates(timeout: int = CHECK_TIMEOUT) -> Dict:
    """Check GitHub for a newer release.

    Always returns a dict with a "status" key, so a check failure can never
    be confused with being current:
    - "unsupported": not running on Windows (no check happened at all)
    - "current": a release tag exists and it is not newer
    - "available": a newer release exists; keeps version, name, body, url,
      published_at and assets as before
    - "failed": urlopen failed, the body was not JSON, or the tag was empty.
      Only the exception type is logged; the URL and body are never logged.
    """
    if not is_windows():
        return {"status": "unsupported"}

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
            return {"status": "failed"}

        if not is_newer_version(current, latest_version):
            logger.info(f"Already up to date (current: {current}, latest: {latest_version})")
            return {"status": "current", "version": latest_version}

        # Find Windows installer asset
        assets = []
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            url = asset.get("browser_download_url", "")
            size = asset.get("size", 0)
            if _is_windows_installer_asset(name) and _safe_url(url):
                assets.append({
                    "name": name,
                    "url": url,
                    "size": size,
                })

        return {
            "status": "available",
            "version": latest_version,
            "name": data.get("name", f"v{latest_version}"),
            "body": data.get("body", ""),
            "url": official_release_url(data.get("html_url") or ""),
            "published_at": data.get("published_at", ""),
            "assets": assets,
        }

    except Exception as error:
        logger.warning(f"Update check failed: {type(error).__name__}")
        return {"status": "failed"}


def check_and_notify(config_manager=None) -> Dict:
    """Record a completed update check. Nothing is downloaded.

    ``available`` stores the new version and announces it. ``current`` clears
    a stale available flag. ``failed`` and ``unsupported`` leave a previously
    stored update untouched and do not announce an update.
    """
    update = check_for_updates()
    status = update.get("status") if isinstance(update, dict) else None
    if status == "available":
        logger.info("Update available: %s", update.get("version"))
        if config_manager is not None:
            try:
                config_manager.set("update.available", True)
                config_manager.set("update.version", update.get("version"))
                config_manager.set("update.url", update.get("url"))
            except Exception:
                pass
    elif status == "current" and config_manager is not None:
        try:
            config_manager.set("update.available", False)
        except Exception:
            pass
    return update if isinstance(update, dict) else {"status": "failed"}
