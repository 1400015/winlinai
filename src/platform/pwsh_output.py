"""PowerShell output normalization for the Windows track.

PowerShell cmdlets emit objects, not plain text. When piped through
``powershell -Command``, objects are formatted as a table by default,
which loses structure. This module wraps cmdlets to emit JSON
(``ConvertTo-Json``) and parses the result into Python dicts/lists,
providing a consistent interface for the offline assistant's probes.

The module never executes anything by itself: it builds argv lists and
parses output strings. Execution goes through ``windows_process.run_bounded``
or ``process_output.run_bounded``.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Markers that PowerShell may emit before/after the JSON payload.
_JSON_START = re.compile(r"^\s*(\[|\{)")
_PWSH_ERROR_PREFIX = "powershell : "


def wrap_cmdlet_json(cmdlet_argv):
    """Wrap a validated cmdlet argv so its output is JSON.

    Returns an argv list for ``powershell -EncodedCommand`` that pipes the
    cmdlet output through ``ConvertTo-Json``. Get-Service projects only the
    four fields consumed by normalize_service before serialization, avoiding
    traversal of related services; other cmdlets retain depth 10. The cmdlet
    argv must already be validated by
    :func:`shell_pwsh.validate_pwsh_arguments`.

    Example:
        wrap_cmdlet_json(["Get-Service", "-Name", "wuauserv"])
        → powershell -EncodedCommand <base64 of
          "Get-Service -Name 'wuauserv' | Select-Object ... | ConvertTo-Json ...">
    """
    import re as _re
    from .shell_pwsh import launch_script

    if not cmdlet_argv:
        raise ValueError("empty cmdlet argv")
    # argv[0] is the cmdlet name: it must stay bare, because 'Get-Service'
    # would be a string literal in the pipeline, not a cmdlet invocation.
    # The same conservative name pattern shell_pwsh uses keeps injection
    # tokens out; anything else raises instead of emitting a script.
    cmdlet_name = cmdlet_argv[0]
    if not _re.match(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$", cmdlet_name):
        raise ValueError("invalid cmdlet name: {!r}".format(cmdlet_name))
    # Parameter names stay bare; values are single-quoted to survive the
    # PowerShell parser, with interior quotes doubled (it's -> 'it''s').
    parts = [cmdlet_name]
    for arg in cmdlet_argv[1:]:
        if arg.startswith("-"):
            parts.append(arg)
        else:
            # Escape single quotes by doubling them (PowerShell convention).
            escaped = arg.replace("'", "''")
            parts.append("'{}'".format(escaped))
    cmdlet = " ".join(parts)
    if cmdlet_name.lower() == "get-service":
        # ServiceController exposes getters for dependency graphs and other
        # SCM queries. Only read the fields that the assistant actually uses.
        script = (cmdlet + " | Select-Object Name,DisplayName,"
                  "@{Name='Status';Expression={[string]$_.Status}},"
                  "@{Name='StartType';Expression={[string]$_.StartType}}"
                  " | ConvertTo-Json -Compress -Depth 2")
    else:
        script = "{} | ConvertTo-Json -Compress -Depth 10".format(cmdlet)
    return launch_script(script)


def parse_json_output(stdout, stderr="", returncode=0):
    """Parse PowerShell JSON output into Python objects.

    Returns a tuple ``(data, error)`` where:
    - ``data`` is the parsed JSON (dict, list, str, int, etc.) or None on failure
    - ``error`` is an error message string, or None on success

    Handles:
    - Clean JSON output
    - JSON with PowerShell error records mixed in
    - Non-JSON output (returns the raw string)
    - Empty output
    """
    if not stdout or not stdout.strip():
        if returncode != 0:
            return None, stderr.strip() or "command failed with no output"
        return None, None

    text = stdout.strip()

    # Strip PowerShell error prefix lines that may appear before JSON.
    lines = text.splitlines()
    json_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_PWSH_ERROR_PREFIX):
            continue
        if stripped.startswith("CategoryInfo") or stripped.startswith("FullyQualifiedErrorId"):
            continue
        json_lines.append(line)
    text = "\n".join(json_lines).strip()

    if not text:
        return None, stderr.strip() or None

    # Try to parse as JSON.
    try:
        data = json.loads(text)
        return data, None
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from a larger blob (e.g. mixed output).
    match = _JSON_START.search(text)
    if match:
        try:
            # Find the matching closing bracket.
            start = match.start()
            candidate = text[start:]
            data = json.loads(candidate)
            return data, None
        except json.JSONDecodeError:
            pass

    # Not JSON: return the raw text as a string.
    if returncode != 0:
        return None, stderr.strip() or text
    return text, None


def normalize_service(service_obj):
    """Normalize a Get-Service JSON object into a flat dict."""
    if not isinstance(service_obj, dict):
        return {}
    return {
        "name": service_obj.get("Name", ""),
        "display_name": service_obj.get("DisplayName", ""),
        "status": str(service_obj.get("Status", "")),
        "start_type": str(service_obj.get("StartType", "")),
    }


def normalize_process(process_obj):
    """Normalize a Get-Process JSON object into a flat dict."""
    if not isinstance(process_obj, dict):
        return {}
    return {
        "name": process_obj.get("ProcessName", ""),
        "id": process_obj.get("Id", 0),
        "cpu": process_obj.get("CPU", 0),
        "memory_mb": round(process_obj.get("WorkingSet", 0) / (1024 * 1024), 2),
    }


def normalize_volume(volume_obj):
    """Normalize a Get-Volume JSON object into a flat dict."""
    if not isinstance(volume_obj, dict):
        return {}
    size = volume_obj.get("Size", 0) or 0
    remaining = volume_obj.get("SizeRemaining", 0) or 0
    return {
        "drive_letter": volume_obj.get("DriveLetter", ""),
        "label": volume_obj.get("FileSystemLabel", ""),
        "size_gb": round(size / (1024 ** 3), 2),
        "free_gb": round(remaining / (1024 ** 3), 2),
        "used_gb": round((size - remaining) / (1024 ** 3), 2),
        "file_system": volume_obj.get("FileSystem", ""),
    }


def normalize_network_adapter(adapter_obj):
    """Normalize a Get-NetAdapter JSON object into a flat dict."""
    if not isinstance(adapter_obj, dict):
        return {}
    return {
        "name": adapter_obj.get("Name", ""),
        "interface": adapter_obj.get("InterfaceAlias", ""),
        "status": str(adapter_obj.get("Status", "")),
        "mac": adapter_obj.get("MacAddress", ""),
        "speed": adapter_obj.get("LinkSpeed", ""),
    }


def normalize_ip_config(config_obj):
    """Normalize a Get-NetIPConfiguration JSON object into a flat dict."""
    if not isinstance(config_obj, dict):
        return {}
    ipv4 = config_obj.get("IPv4Address", [])
    ipv6 = config_obj.get("IPv6Address", [])
    dns = config_obj.get("DNSServer", [])
    return {
        "interface": config_obj.get("InterfaceAlias", ""),
        "ipv4": [a.get("IPAddress", "") for a in (ipv4 if isinstance(ipv4, list) else [ipv4]) if isinstance(a, dict)],
        "ipv6": [a.get("IPAddress", "") for a in (ipv6 if isinstance(ipv6, list) else [ipv6]) if isinstance(a, dict)],
        "dns": [d.get("ServerAddresses", "") for d in (dns if isinstance(dns, list) else [dns]) if isinstance(d, dict)],
    }


def normalize_output(data, probe_key=None):
    """Normalize parsed JSON output based on the probe key.

    ``probe_key`` is one of: "links", "addresses", "routes", "disk", "memory",
    "services", "processes". When provided, the corresponding normalizer is
    applied to each item (if data is a list) or the single object.
    """
    if data is None:
        return None

    normalizers = {
        "services": normalize_service,
        "processes": normalize_process,
        "disk": normalize_volume,
        "links": normalize_network_adapter,
        "addresses": normalize_ip_config,
    }

    if probe_key and probe_key in normalizers:
        normalizer = normalizers[probe_key]
        if isinstance(data, list):
            return [normalizer(item) for item in data]
        return normalizer(data)

    return data


def run_probe(cmdlet_argv, runner=None, timeout=30, limit=1024 * 1024, probe_key=None):
    """Build argv, execute via runner, and return normalized output.

    ``runner`` is a callable ``(argv, timeout, limit) -> (returncode, stdout, stderr)``.
    Defaults to ``process_output.run_bounded`` on Windows or POSIX.

    ``probe_key`` is passed to :func:`normalize_output` to normalize the
    parsed data (e.g. ``"services"``, ``"processes"``, ``"disk"``).

    Returns a dict: {"ok": bool, "data": Any, "error": str|None, "raw": str}
    """
    from .shell_pwsh import validate_pwsh_arguments

    if not validate_pwsh_arguments(cmdlet_argv):
        return {"ok": False, "data": None,
                "error": "cmdlet argv failed validation", "raw": ""}

    argv = wrap_cmdlet_json(cmdlet_argv)

    if runner is None:
        try:
            from ..process_output import run_bounded
        except ImportError:
            return {"ok": False, "data": None,
                    "error": "no runner available", "raw": ""}
        runner = run_bounded

    try:
        returncode, stdout, stderr = runner(list(argv), timeout=timeout, limit=limit)
    except Exception as error:
        return {"ok": False, "data": None,
                "error": "execution failed: {}".format(type(error).__name__),
                "raw": ""}

    data, parse_error = parse_json_output(stdout, stderr, returncode)
    data = normalize_output(data, probe_key)

    return {
        "ok": returncode == 0 and data is not None,
        "data": data,
        "error": parse_error,
        "raw": stdout,
        "returncode": returncode,
    }
