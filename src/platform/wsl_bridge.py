"""WSL bridge: enumerate distributions and build validated probe commands.

Phase 3 of the Windows support plan. The bridge never executes anything by
itself: it parses ``wsl.exe`` output (with an injectable runner for tests)
and builds argv lists from an exact catalogue of read-only probes. This
bridge is for a Windows host inspecting an explicitly selected distro;
processes already running inside WSL use their native POSIX commands.
"""
import re
from typing import Callable, Dict, Iterable, Optional, Tuple

_LIST_ARGV = ("wsl.exe", "--list", "--verbose")
_DISTRIBUTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

# No operands, arbitrary paths, executables or flags are admitted through
# the host/distro boundary. Add a complete argv here only when a diagnostic
# needs it; the general POSIX argument policy is not a command allowlist.
READ_ONLY_PROBES = frozenset({
    ("ip", "link"), ("ip", "link", "show"),
    ("ip", "-brief", "link"), ("ip", "-brief", "link", "show"),
    ("ip", "-br", "link"), ("ip", "-br", "link", "show"),
    ("ip", "addr"), ("ip", "addr", "show"),
    ("ip", "address"), ("ip", "address", "show"),
    ("ip", "-brief", "addr"), ("ip", "-brief", "addr", "show"),
    ("ip", "-br", "addr"), ("ip", "-br", "addr", "show"),
    ("ip", "route"), ("ip", "route", "show"),
    ("df", "-h"), ("df", "-i"), ("free", "-h"),
})


def _reject_path(path):
    """An optional extra validator never receives blanket path access."""
    return False


def parse_wsl_list(output: str) -> Tuple[Dict[str, str], ...]:
    """Parse ``wsl -l -v`` output into bounded distribution records.

    Accepts both the UTF-16 output produced by wsl.exe on Windows and plain
    UTF-8 text; malformed lines are skipped rather than trusted.
    """
    text = output
    if isinstance(text, bytes):
        encoding = "utf-16" if text.startswith((b"\xff\xfe", b"\xfe\xff")) else (
            "utf-16-le" if b"\x00" in text else "utf-8")
        text = text.decode(encoding, errors="replace")
    records = []
    for line in text.splitlines():
        line = line.lstrip("\ufeff").strip()
        if line.startswith("*"):
            line = line[1:].strip()
        if not line or line.startswith("Windows") or ("NAME" in line and "STATE" in line):
            continue
        columns = line.split()
        if not columns or not _DISTRIBUTION.fullmatch(columns[0]):
            continue
        name = columns[0]
        state = columns[1] if len(columns) > 1 else "unknown"
        version = columns[2] if len(columns) > 2 else ""
        records.append({"name": name, "state": state[:32], "version": version[:16]})
    return tuple(records)


def detect_wsl_distros(run: Optional[Callable[..., "object"]] = None) -> Tuple[Dict[str, str], ...]:
    """Enumerate installed WSL distributions.

    ``run`` defaults to :func:`subprocess.run`; tests inject a fake. Any
    failure (missing wsl.exe, non-zero exit, unparseable output) yields an
    empty tuple: the bridge degrades, it never blocks startup.
    """
    if run is None:
        import subprocess
        run = subprocess.run
    try:
        completed = run(list(_LIST_ARGV), capture_output=True, timeout=10)
    except Exception:
        return ()
    if completed.returncode != 0:
        return ()
    output = getattr(completed, "stdout", b"")
    return parse_wsl_list(output)


def probe_argv(distro: str, inner_argv: Iterable[str], validate_arguments=None) -> Optional[Tuple[str, ...]]:
    """Build the argv for a read-only probe inside a WSL distribution.

    Only an exact argv in ``READ_ONLY_PROBES`` is accepted. An optional
    validator may narrow that catalogue, never expand it. Distro names are
    matched against a strict identifier pattern so they cannot become
    options to wsl.exe.
    """
    try:
        inner = tuple(inner_argv)
    except TypeError:
        return None
    if not inner or not isinstance(distro, str) or not _DISTRIBUTION.fullmatch(distro):
        return None
    if not all(isinstance(argument, str) for argument in inner) or inner not in READ_ONLY_PROBES:
        return None
    if validate_arguments is not None:
        try:
            if not validate_arguments(inner, _reject_path):
                return None
        except Exception:
            return None
    return ("wsl.exe", "--distribution", distro, "--exec", *inner)
