"""Platform-aware read probes for the offline assistant diagnostics.

Phase 3 integration: the offline assistant's probe registry is POSIX-only.
On Windows the equivalent evidence comes from read-only PowerShell cmdlets;
inside a WSL distribution the POSIX probes run natively. Only a Windows
host inspecting an explicitly selected distro uses the WSL bridge. This
module maps probe keys to platform commands
and never executes anything: the caller (SystemUtils or the assistant)
remains the single execution authority.
"""
from typing import Callable, Optional, Tuple

from . import WINDOWS, WSL, effective_platform

# POSIX probe registry (mirrors offline_assistant._probe commands).
POSIX_PROBES = {
    "links": ("ip", "link", "show"),
    "addresses": ("ip", "addr", "show"),
    "routes": ("ip", "route"),
    "disk": ("df", "-h"),
    "inodes": ("df", "-i"),
    "memory": ("free", "-h"),
}

# Windows equivalents: read-only, allowlisted PowerShell cmdlets wrapped
# for ``powershell -Command`` so system_utils can validate the cmdlet tail.
WINDOWS_PROBES = {
    "links": ("powershell", "-Command", "Get-NetAdapter"),
    "addresses": ("powershell", "-Command", "Get-NetIPConfiguration"),
    "routes": ("powershell", "-Command", "Get-NetRoute"),
    "disk": ("powershell", "-Command", "Get-Volume"),
    "memory": ("powershell", "-Command", "Get-Process"),
}

PROBE_KEYS = tuple(POSIX_PROBES)


def probe_argv_for(key: str, platform: Optional[str] = None,
                   wsl_distro: Optional[str] = None,
                   validate_pwsh: Optional[Callable] = None,
                   validate_posix: Optional[Callable] = None) -> Optional[Tuple[str, ...]]:
    """Return the argv for a read probe on the given (or detected) platform.

    - Windows: the PowerShell equivalent, or a catalogue probe in an
      explicitly selected ``wsl_distro``. Optional validators only narrow
      the built-in policies.
    - WSL: the native POSIX probe, without launching another distribution.
    - Linux (or an unknown key): ``None``; the caller keeps its native path.
    """
    if key not in PROBE_KEYS:
        return None
    current = effective_platform(platform)
    if current == WINDOWS:
        if wsl_distro is not None:
            from .wsl_bridge import probe_argv as wsl_probe
            return wsl_probe(wsl_distro, POSIX_PROBES[key], validate_arguments=validate_posix)
        argv = WINDOWS_PROBES.get(key)
        if argv is None:
            return None
        from .shell_pwsh import validate_pwsh_arguments
        if not validate_pwsh_arguments(argv[2:]):
            return None
        return argv if validate_pwsh is None or validate_pwsh(argv[2:]) else None
    if current == WSL:
        return POSIX_PROBES[key]
    return None
