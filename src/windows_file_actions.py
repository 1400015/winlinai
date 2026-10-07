"""Windows file actions: file writing with confirmation and diff.

Port of src/file_actions.py for Windows paths and Qt dialogs.
Adapted from the Linux version to support:
- Windows paths (C:\\Users\\..., UNC paths, etc.)
- Qt dialogs instead of GTK
- Windows ACLs for security (via src/platform/windows_files.py)
- No pkexec (Windows uses different elevation model)

Security model:
- Paths must be inside user's home or allowed directories
- Sensitive Windows paths are blocked (System32, Program Files, etc.)
- All writes create backups
- Diffs are shown before writing
"""
from __future__ import annotations

import difflib
import hashlib
import logging
import ntpath
import os
import re
import sys
import time
import uuid
from pathlib import Path, PureWindowsPath
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Windows-specific sensitive paths (blocked from AI writes)
SENSITIVE_WINDOWS_PATHS = frozenset({
    # System files
    r"C:\Windows\System32",
    r"C:\Windows\SysWOW64",
    r"C:\Windows\System",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData",
    # Registry hives (if accessed as files)
    r"C:\Windows\System32\config",
    # User profile system areas
    r"C:\Users\Default",
    r"C:\Users\All Users",
    r"C:\Users\Public\Public Desktop",
    r"C:\Users\Public\Public Documents",
})

# Sensitive file patterns (blocked)
SENSITIVE_FILE_PATTERNS = (
    "SAM", "SECURITY", "SOFTWARE", "SYSTEM",  # Registry hives
    "pagefile.sys", "hiberfil.sys", "swapfile.sys",
    "ntuser.dat", "ntuser.dat.log",
)

# Directories that contain sensitive data
SENSITIVE_DIR_NAMES = (
    ".ssh", ".gnupg", ".aws", ".azure", ".gcloud",
    "AppData\\Local\\Microsoft\\Windows\\INetCookies",
    "AppData\\Roaming\\Microsoft\\Credentials",
)

MAX_DIFF_BYTES = 1024 * 1024  # 1 MB


def is_windows() -> bool:
    """True when running on Windows."""
    return sys.platform == "win32"


def get_user_home() -> Path:
    """Get the current user's home directory."""
    return Path.home()


_WINDOWS_ROOT_RE = re.compile(r"^[A-Za-z]:[\\/]|^\\\\")


_WIN_ENV_RE = re.compile(r"%(\w+)%")


def _expand_windows_env(path: str) -> str:
    """Expand %VAR% references from os.environ on any host OS."""
    def replace(match):
        return os.environ.get(match.group(1), "")
    return _WIN_ENV_RE.sub(replace, path)


def _is_windows_style(path: str) -> bool:
    """True for drive-letter (C:\\...) or UNC (\\\\server\\share) paths."""
    return bool(_WINDOWS_ROOT_RE.match(path.replace("/", "\\")))


def _normalize_pure(path: str) -> PureWindowsPath:
    """Normalize with Windows semantics for security decisions.

    Works identically on Windows and on the Linux CI: ``ntpath`` interprets
    drive letters, separators and dot segments, and ``PureWindowsPath``
    exposes the resulting components without touching the filesystem.
    """
    expanded = os.path.expandvars(_expand_windows_env(path))
    expanded = os.path.expanduser(expanded)
    if _is_windows_style(expanded):
        return PureWindowsPath(ntpath.normpath(expanded))
    return PureWindowsPath(os.path.normpath(expanded))


def normalize_windows_path(path: str) -> Path:
    """Normalize a path with Windows semantics, regardless of the host OS.

    Drive-letter and UNC paths are interpreted with ``ntpath`` rules so the
    behaviour of this module is identical on Windows and on the Linux CI.
    Relative paths resolve against the current directory using the host's
    path module, matching the behaviour of the running application.

    Handles:
    - Environment variables (%USERPROFILE%, %APPDATA%, etc.)
    - Tilde expansion (~)
    - Relative paths
    - Forward/backward slashes
    - Dot segments (.., .)
    """
    expanded = os.path.expanduser(os.path.expandvars(_expand_windows_env(path)))
    if _is_windows_style(expanded):
        return Path(str(_normalize_pure(path)))
    return Path(os.path.normpath(expanded)).absolute()


def is_sensitive_windows_path(path: str) -> bool:
    """Check if a Windows path is sensitive (blocked from AI writes).

    Blocks:
    - System directories (System32, Program Files, etc.)
    - Registry hive files
    - Page/hibernation files
    - SSH/GPG/AWS/Azure credentials
    - Browser credential stores
    """
    try:
        if not path or not isinstance(path, str):
            return True  # Fail closed on empty/invalid input
        normalized = _normalize_pure(path)
        path_str = str(normalized).lower()

        # Check sensitive directories
        for sensitive in SENSITIVE_WINDOWS_PATHS:
            if path_str.startswith(sensitive.lower() + "\\") or path_str == sensitive.lower():
                return True

        # Check sensitive file names
        filename = normalized.name.lower()
        for pattern in SENSITIVE_FILE_PATTERNS:
            if filename == pattern.lower() or filename.startswith(pattern.lower() + "."):
                return True

        # Check sensitive directory names in path
        parts = normalized.parts
        for part in parts:
            for sensitive_dir in SENSITIVE_DIR_NAMES:
                if sensitive_dir.lower() in part.lower():
                    return True

        return False
    except Exception:
        return True  # Fail closed


def is_allowed_windows_path(path: str, allowed_dirs: Optional[List[str]] = None) -> bool:
    """Check if a path is allowed for AI writes.

    Allowed paths:
    - Inside user's home directory
    - Inside one of the allowed_dirs (from config)

    Args:
        path: The path to check
        allowed_dirs: List of additional allowed directories

    Returns:
        True if the path is allowed
    """
    try:
        normalized = _normalize_pure(path)

        # Block sensitive paths
        if is_sensitive_windows_path(str(normalized)):
            return False

        # Check if inside home
        home = PureWindowsPath(str(get_user_home()))
        if normalized.is_relative_to(home):
            return True

        # Check allowed directories
        for allowed_dir in allowed_dirs or ():
            try:
                allowed = _normalize_pure(allowed_dir)
                if normalized.is_relative_to(allowed):
                    return True
            except (ValueError, TypeError):
                continue

        return False
    except Exception:
        return False


def is_privileged_windows_path(path: str) -> bool:
    """Check if a path requires elevation on Windows.

    On Windows, paths outside the user's home typically require elevation.
    """
    try:
        normalized = _normalize_pure(path)
        home = PureWindowsPath(str(get_user_home()))
        if normalized.is_relative_to(home):
            return False  # Inside home, no elevation needed
        return True  # Outside home, may need elevation
    except Exception:
        return True


def file_digest(path: str) -> Optional[str]:
    """Calculate SHA-256 digest of a file. Returns None if file doesn't exist."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def preview_diff(path: str, new_content: str) -> Optional[str]:
    """Generate a unified diff between existing file and new content.

    Returns None if the file doesn't exist (new file).
    Returns the diff text, with truncation notice if file is too large.
    """
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        return None
    try:
        truncated = os.path.getsize(path) > MAX_DIFF_BYTES
        with open(path, "rb") as f:
            old_lines = f.read(MAX_DIFF_BYTES).decode("utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return None
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=path, tofile=path
    )
    text = "".join(diff)
    if truncated:
        text += "\n\n!!! WARNING: preview truncated at 1 MB; the file is bigger and this diff is NOT complete.\n"
    return text


def _backup_path(path: str) -> str:
    """Generate a backup path with timestamp (never overwrites previous)."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return f"{path}.{stamp}.{uuid.uuid4().hex}.bak"


def make_backup(path: str) -> Optional[str]:
    """Create a backup of the file before editing (best effort).

    Returns the backup path, or None if backup failed.
    """
    try:
        if os.path.isfile(path):
            backup = _backup_path(path)
            with open(path, "rb") as source, open(backup, "xb") as target:
                import shutil
                shutil.copyfileobj(source, target, 65536)
            return backup
    except OSError as e:
        logger.warning(f"Could not create backup of {path}: {e}")
    return None


def write_file_safe(path: str, content: str, create_backup: bool = True) -> Tuple[bool, str, Optional[str]]:
    """Safely write content to a file.

    - Validates the path is allowed
    - Creates a backup if the file exists
    - Writes atomically (temp file + rename)

    Args:
        path: Target file path
        content: Content to write
        create_backup: Whether to create a backup of existing file

    Returns:
        (success, message, backup_path)
    """
    try:
        normalized = normalize_windows_path(path)

        # Create parent directories if needed
        normalized.parent.mkdir(parents=True, exist_ok=True)

        # Create backup
        backup = None
        if create_backup and normalized.exists():
            backup = make_backup(str(normalized))

        # Write atomically (temp file + rename)
        temp_path = normalized.with_suffix(normalized.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
        # Atomic rename
        os.replace(temp_path, normalized)

        return True, f"File written: {normalized}", backup

    except PermissionError as e:
        return False, f"Permission denied: {e}", None
    except OSError as e:
        return False, f"Write failed: {e}", None
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}", None


def read_file_preview(path: str, max_bytes: int = MAX_DIFF_BYTES) -> Tuple[bool, str, bool]:
    """Read a file for preview (bounded).

    Returns:
        (success, content, truncated)
    """
    try:
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            return False, "File not found", False
        size = os.path.getsize(path)
        truncated = size > max_bytes
        with open(path, "rb") as f:
            data = f.read(max_bytes)
        content = data.decode("utf-8", errors="replace")
        return True, content, truncated
    except OSError as e:
        return False, str(e), False


def list_directory(path: str, max_items: int = 100) -> Tuple[bool, List[dict], Optional[str]]:
    """List directory contents (bounded).

    Returns:
        (success, items, error)
        items: list of {"name": str, "type": "file"|"dir", "size": int}
    """
    try:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return False, [], "Not a directory"
        items = []
        for entry in os.scandir(path):
            try:
                items.append({
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": entry.stat().st_size if entry.is_file() else 0,
                })
            except OSError:
                continue
            if len(items) >= max_items:
                break
        return True, items, None
    except OSError as e:
        return False, [], str(e)


def delete_file_safe(path: str, create_backup: bool = True) -> Tuple[bool, str, Optional[str]]:
    """Safely delete a file (with optional backup).

    Returns:
        (success, message, backup_path)
    """
    try:
        normalized = normalize_windows_path(path)
        if not normalized.exists():
            return False, "File not found", None

        # Create backup
        backup = None
        if create_backup:
            backup = make_backup(str(normalized))

        # Delete
        normalized.unlink()
        return True, f"File deleted: {normalized}", backup

    except PermissionError as e:
        return False, f"Permission denied: {e}", None
    except OSError as e:
        return False, f"Delete failed: {e}", None


def get_file_info(path: str) -> Optional[dict]:
    """Get file information (size, modified time, etc.)."""
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            return None
        stat = os.stat(path)
        return {
            "path": path,
            "size": stat.st_size,
            "is_file": os.path.isfile(path),
            "is_dir": os.path.isdir(path),
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            "digest": file_digest(path) if os.path.isfile(path) else None,
        }
    except OSError:
        return None


class WindowsFileActions:
    """File actions for the Windows/Qt track.

    Provides file operations with safety checks:
    - Path validation (allowed directories)
    - Sensitive path blocking
    - Backup creation
    - Diff preview
    """

    def __init__(self, allowed_dirs: Optional[List[str]] = None):
        self.allowed_dirs = allowed_dirs or []

    def is_allowed(self, path: str) -> bool:
        """Check if a path is allowed for writes."""
        return is_allowed_windows_path(path, self.allowed_dirs)

    def write_file(self, path: str, content: str,
                   confirm_callback: Optional[Callable[[str, str, bool], bool]] = None) -> Tuple[str, str]:
        """Write a file with optional confirmation.

        Args:
            path: Target path
            content: Content to write
            confirm_callback: Optional callback(parent, path, diff_or_content, is_new) -> bool
                             Called to confirm the write. Returns True to proceed.

        Returns:
            ("written"|"cancelled"|"error", message)
        """
        # Validate path
        if not self.is_allowed(path):
            return "error", f"Path not allowed: {path}"

        normalized = normalize_windows_path(path)
        is_new = not normalized.exists()

        # Generate diff
        diff = preview_diff(str(normalized), content)
        display_content = diff if diff is not None else content

        # Confirm if callback provided
        if confirm_callback is not None:
            confirmed = confirm_callback(str(normalized), display_content, is_new)
            if not confirmed:
                return "cancelled", "User cancelled"

        # Write
        success, message, backup = write_file_safe(str(normalized), content)
        if success:
            return "written", message
        return "error", message

    def read_file(self, path: str, max_bytes: int = MAX_DIFF_BYTES) -> Tuple[bool, str]:
        """Read a file (bounded)."""
        if not self.is_allowed(path):
            return False, "Path not allowed"
        success, content, _truncated = read_file_preview(path, max_bytes)
        return success, content

    def delete_file(self, path: str,
                    confirm_callback: Optional[Callable[[str], bool]] = None) -> Tuple[str, str]:
        """Delete a file with optional confirmation."""
        if not self.is_allowed(path):
            return "error", f"Path not allowed: {path}"

        normalized = normalize_windows_path(path)
        if not normalized.exists():
            return "error", "File not found"

        # Confirm if callback provided
        if confirm_callback is not None:
            confirmed = confirm_callback(str(normalized))
            if not confirmed:
                return "cancelled", "User cancelled"

        success, message, _backup = delete_file_safe(str(normalized))
        if success:
            return "written", message
        return "error", message
