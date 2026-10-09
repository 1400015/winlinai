"""Windows autostart for the Qt track (phase 4c).

The Registry ``Run`` key is the Windows equivalent of scripts/autostart.sh:
a single value under HKCU pointing at the launcher. Registry access is
injected (``read_value``/``write_value``/``delete_value``) so the decision
logic — value construction, idempotency, comparison — is fully testable
without Windows, exactly like the polkit-free decision points elsewhere.

High-level helpers (``is_autostart_enabled``, ``set_autostart``) wrap the
pure logic with the real winreg backends and degrade gracefully off Windows.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, cast

logger = logging.getLogger(__name__)

AUTOSTART_VALUE_NAME = "LinuxAIAssistant"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command(powershell_exe, script_path, ui="qt"):
    """Build the checkout launcher stored in the Registry Run key.

    The Registry Run key starts a process without the project working
    directory, so a checkout launches ``run.ps1`` (which sets it) through
    PowerShell instead of calling ``python -m src.app`` directly.
    """
    if ui not in ("qt", "gtk"):
        ui = "qt"
    return '"{}" -WindowStyle Hidden -ExecutionPolicy Bypass -File "{}" -Ui {}'.format(
        powershell_exe, script_path, ui)


def interpreter_autostart_command(python_exe, ui="qt"):
    """Launch an installed copy with the interpreter that is already running.

    An installed wheel has no ``run.ps1``. ``python -m src.app`` does not
    need the project directory because the package is on that interpreter's
    module path.
    """
    if ui not in ("qt", "gtk"):
        ui = "qt"
    return '"{}" -m src.app --ui {}'.format(python_exe, ui)


def resolve_autostart_command(powershell_exe, script_path, python_exe, ui="qt"):
    """Checkout keeps ``run.ps1``. An install uses the running interpreter."""
    if script_path:
        return autostart_command(powershell_exe, script_path, ui)
    if python_exe:
        return interpreter_autostart_command(python_exe, ui)
    return None


def autostart_should_update(current_value, desired_command):
    """Idempotency: only rewrite when the stored value differs."""
    return current_value != desired_command


def apply_autostart(enabled, desired_command, read_value, write_value, delete_value):
    """Pure orchestration over injected Registry primitives.

    Returns a short status string for the UI/log; never raises on its own
    primitives (callers wrap winreg errors).
    """
    if enabled:
        current = read_value(RUN_KEY, AUTOSTART_VALUE_NAME)
        if autostart_should_update(current, desired_command):
            write_value(RUN_KEY, AUTOSTART_VALUE_NAME, desired_command)
            logger.info("Autostart enabled via Registry Run key")
            return "enabled"
        return "already-enabled"
    if read_value(RUN_KEY, AUTOSTART_VALUE_NAME) is not None:
        delete_value(RUN_KEY, AUTOSTART_VALUE_NAME)
        logger.info("Autostart disabled (Registry value removed)")
        return "disabled"
    return "already-disabled"


def windows_backends():
    """Real winreg-backed primitives, or None off Windows."""
    try:
        import winreg
    except ImportError:
        return None

    # Use Any to avoid attr-defined errors on winreg (Windows-only module)
    winreg_any = cast(Any, winreg)

    def read_value(key, name):
        try:
            with winreg_any.OpenKey(winreg_any.HKEY_CURRENT_USER, key, 0,
                                   winreg_any.KEY_READ) as handle:
                value, _ = winreg_any.QueryValueEx(handle, name)
                return value
        except OSError:
            return None

    def write_value(key, name, value):
        with winreg_any.CreateKey(winreg_any.HKEY_CURRENT_USER, key) as handle:
            winreg_any.SetValueEx(handle, name, 0, winreg_any.REG_SZ, value)

    def delete_value(key, name):
        with winreg_any.OpenKey(winreg_any.HKEY_CURRENT_USER, key, 0,
                                winreg_any.KEY_SET_VALUE) as handle:
            winreg_any.DeleteValue(handle, name)

    return read_value, write_value, delete_value


def is_windows():
    """True when running on a native Windows host."""
    return sys.platform == "win32"


def default_powershell_exe():
    """Locate powershell.exe (Windows PowerShell 5.1, always present)."""
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    return os.path.join(
        system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def default_script_path():
    """Locate run.ps1 relative to the project root."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    script = root / "run.ps1"
    return str(script) if script.is_file() else None


def is_autostart_enabled(read_value=None):
    """Check whether autostart is currently enabled.

    Returns True/False on Windows; None when the status cannot be determined
    (off Windows, missing winreg, or registry error). An injected read_value
    is honoured on any platform so the status contract is testable everywhere;
    production code never injects it.
    """
    if read_value is None:
        if not is_windows():
            return None
        backends = windows_backends()
        if backends is None:
            return None
        read_value = backends[0]
    try:
        return read_value(RUN_KEY, AUTOSTART_VALUE_NAME) is not None
    except Exception:
        logger.warning("Could not read autostart status from Registry")
        return None


def set_autostart(enabled, script_path=None, ui="qt", read_value=None,
                  write_value=None, delete_value=None):
    """Enable or disable autostart on Windows.

    Returns a status string ("enabled", "disabled", "already-enabled",
    "already-disabled") or None when not on Windows / backends unavailable.
    """
    if not is_windows():
        return None
    backends = windows_backends()
    if backends is None:
        return None
    if read_value is None:
        read_value, write_value, delete_value = backends
    if script_path is None:
        script_path = default_script_path()
    command = resolve_autostart_command(
        default_powershell_exe(), script_path, sys.executable, ui)
    if command is None:
        logger.error("Cannot configure autostart without a launcher")
        return None
    try:
        return apply_autostart(enabled, command, read_value, write_value, delete_value)
    except Exception as error:
        logger.error("Failed to apply autostart: %s", type(error).__name__)
        return None
