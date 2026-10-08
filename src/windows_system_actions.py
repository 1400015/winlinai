"""Windows system actions: services, processes, packages via PowerShell.

Read-only system queries for the Qt track on Windows. Uses the validated
PowerShell allowlist (src/platform/shell_pwsh.py) and output normalization
(src/platform/pwsh_output.py).

Actions:
- list_services: Get-Service
- list_processes: Get-Process
- get_system_info: Get-ComputerInfo (basic)
- list_packages: winget list (if available)
"""
from __future__ import annotations

import logging
import shutil
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def is_windows() -> bool:
    """True when running on Windows."""
    import sys
    return sys.platform == "win32"


def _run_powershell(cmdlet_argv: List[str], timeout: int = 30) -> Dict:
    """Run a PowerShell cmdlet and return normalized output.

    Returns a dict: {"ok": bool, "data": Any, "error": str|None}
    """
    from .platform.pwsh_output import run_probe
    return run_probe(cmdlet_argv, timeout=timeout)


def list_services(limit: int = 50) -> Tuple[bool, List[Dict], Optional[str]]:
    """List Windows services.

    Returns (success, services_list, error_message).
    Each service: {"name": str, "display_name": str, "status": str, "start_type": str}
    """
    if not is_windows():
        return False, [], "Not on Windows"

    result = _run_powershell(["Get-Service"])
    if not result["ok"]:
        return False, [], result.get("error", "Unknown error")

    data = result.get("data")
    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []

    from .platform.pwsh_output import normalize_service
    services = [normalize_service(s) for s in data[:limit]]
    return True, services, None


def get_service_status(name: str) -> Tuple[bool, Optional[Dict], Optional[str]]:
    """Get status of a specific service.

    Returns (success, service_dict, error_message).
    """
    if not is_windows():
        return False, None, "Not on Windows"

    from .platform.shell_pwsh import validate_pwsh_arguments
    if not validate_pwsh_arguments(["Get-Service", "-Name", name]):
        return False, None, "Invalid service name"

    result = _run_powershell(["Get-Service", "-Name", name])
    if not result["ok"]:
        return False, None, result.get("error", "Unknown error")

    data = result.get("data")
    if isinstance(data, dict):
        from .platform.pwsh_output import normalize_service
        return True, normalize_service(data), None
    return False, None, "Service not found"


def list_processes(limit: int = 30, sort_by: str = "memory") -> Tuple[bool, List[Dict], Optional[str]]:
    """List running processes.

    Returns (success, processes_list, error_message).
    Each process: {"name": str, "id": int, "cpu": float, "memory_mb": float}
    """
    if not is_windows():
        return False, [], "Not on Windows"

    result = _run_powershell(["Get-Process"])
    if not result["ok"]:
        return False, [], result.get("error", "Unknown error")

    data = result.get("data")
    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []

    from .platform.pwsh_output import normalize_process
    processes = [normalize_process(p) for p in data]

    # Sort
    if sort_by == "memory":
        processes.sort(key=lambda p: p.get("memory_mb", 0), reverse=True)
    elif sort_by == "cpu":
        processes.sort(key=lambda p: p.get("cpu", 0), reverse=True)
    elif sort_by == "name":
        processes.sort(key=lambda p: p.get("name", ""))

    return True, processes[:limit], None


def get_system_info() -> Tuple[bool, Dict, Optional[str]]:
    """Get basic system information.

    Returns (success, info_dict, error_message).
    """
    if not is_windows():
        return False, {}, "Not on Windows"

    info = {}

    # Computer info
    result = _run_powershell(["Get-ComputerInfo", "-Property",
                              "WindowsProductName,WindowsVersion,TotalPhysicalMemory,CsProcessors"])
    if result["ok"] and isinstance(result.get("data"), dict):
        data = result["data"]
        info["os_name"] = data.get("WindowsProductName", "")
        info["os_version"] = data.get("WindowsVersion", "")
        mem = data.get("TotalPhysicalMemory", 0)
        if isinstance(mem, (int, float)):
            info["total_memory_gb"] = round(mem / (1024 ** 3), 2)

    # CPU
    result = _run_powershell(["Get-CimInstance", "-ClassName", "Win32_Processor"])
    # Note: Get-CimInstance may not be in allowlist; skip if fails

    # Disks
    result = _run_powershell(["Get-Volume"])
    if result["ok"]:
        data = result.get("data")
        if isinstance(data, list):
            from .platform.pwsh_output import normalize_volume
            info["disks"] = [normalize_volume(v) for v in data]
        elif isinstance(data, dict):
            from .platform.pwsh_output import normalize_volume
            info["disks"] = [normalize_volume(data)]

    # Network adapters
    result = _run_powershell(["Get-NetAdapter"])
    if result["ok"]:
        data = result.get("data")
        if isinstance(data, list):
            from .platform.pwsh_output import normalize_network_adapter
            info["network_adapters"] = [normalize_network_adapter(a) for a in data]
        elif isinstance(data, dict):
            from .platform.pwsh_output import normalize_network_adapter
            info["network_adapters"] = [normalize_network_adapter(data)]

    return True, info, None


def _run_winget(args, timeout=60, output_limit=1024 * 1024):
    """Run winget through the project's bounded process runner.

    winget is not in the POSIX command_policy allowlist (it is a Windows
    tool), so this applies its own narrow policy: only `list` and `search`
    subcommands, with a validated query for search. Everything goes through
    process_output.run_bounded (timeout + output limit + Windows Job Object
    cleanup), never a raw subprocess.run.
    """
    import re
    from .process_output import run_bounded

    if not args or args[0] not in ("list", "search"):
        raise ValueError("winget subcommand not allowed")
    argv = ["winget", args[0]]
    if args[0] == "list":
        argv.append("--accept-source-agreements")
    else:  # search
        if len(args) < 2:
            raise ValueError("winget search requires a query")
        query = " ".join(args[1:])
        # Conservative query: alphanumerics, spaces and ._- only; no shell
        # metacharacters, no paths, bounded length.
        if (not query or len(query) > 128
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._+-]{0,127}", query)):
            raise ValueError("invalid winget search query")
        argv.extend([query, "--accept-source-agreements"])
    return run_bounded(argv, timeout=timeout, limit=output_limit)


def _parse_winget_table(stdout, limit, with_source):
    """Parse `winget list/search` table output into package dicts."""
    packages = []
    for line in stdout.splitlines():
        if not line.strip() or line.startswith("Name") or line.startswith("---"):
            continue
        parts = line.split(None, 3 if with_source else 2)
        if len(parts) >= 2:
            entry = {
                "name": parts[0],
                "id": parts[1],
                "version": parts[2] if len(parts) > 2 else "",
            }
            if with_source:
                entry["source"] = parts[3] if len(parts) > 3 else ""
            packages.append(entry)
        if len(packages) >= limit:
            break
    return packages


def list_packages(limit: int = 50) -> Tuple[bool, List[Dict], Optional[str]]:
    """List installed packages using winget (if available).

    Returns (success, packages_list, error_message).
    Each package: {"name": str, "id": str, "version": str, "source": str}
    """
    if not is_windows():
        return False, [], "Not on Windows"

    # Check if winget is available
    if shutil.which("winget") is None:
        return False, [], "winget not available"

    try:
        code, stdout, stderr = _run_winget(["list"], timeout=60)
    except ValueError as error:
        return False, [], str(error)
    except Exception as error:
        return False, [], f"winget failed: {type(error).__name__}"
    if code != 0:
        return False, [], stderr or "winget failed"
    return True, _parse_winget_table(stdout, limit, with_source=True), None


def search_packages(query: str, limit: int = 20) -> Tuple[bool, List[Dict], Optional[str]]:
    """Search for packages using winget.

    Returns (success, packages_list, error_message).
    """
    if not is_windows():
        return False, [], "Not on Windows"

    if shutil.which("winget") is None:
        return False, [], "winget not available"

    try:
        code, stdout, stderr = _run_winget(["search", query], timeout=30)
    except ValueError as error:
        return False, [], str(error)
    except Exception as error:
        return False, [], f"winget search failed: {type(error).__name__}"
    if code != 0:
        return False, [], stderr or "winget search failed"
    return True, _parse_winget_table(stdout, limit, with_source=False), None


def list_volumes(limit: int = 32) -> Tuple[bool, List[Dict], Optional[str]]:
    """List storage volumes (read-only Get-Volume probe).

    Returns (success, volumes_list, error_message). Each volume carries
    drive_letter, label, size_gb and free_gb via normalize_volume.
    """
    if not is_windows():
        return False, [], "Not on Windows"
    result = _run_powershell(["Get-Volume"])
    if not result["ok"]:
        return False, [], result.get("error", "Unknown error")
    data = result.get("data")
    if not isinstance(data, list):
        data = [data] if isinstance(data, dict) else []
    from .platform.pwsh_output import normalize_volume
    volumes = [normalize_volume(v) for v in data if isinstance(v, dict)]
    return True, volumes[:limit], None


def format_volumes_table(volumes: List[Dict]) -> str:
    """Format volumes as a text table."""
    if not volumes:
        return "No volumes found"
    lines = ["Drive  Label                    Size(GB)   Free(GB)   FS"]
    lines.append("-" * 60)
    for v in volumes:
        letter = str(v.get("drive_letter", "") or "-")[:4]
        label = str(v.get("label", ""))[:24]
        size = "{:.1f}".format(v.get("size_gb", 0))[:9]
        free = "{:.1f}".format(v.get("free_gb", 0))[:9]
        fs = str(v.get("file_system", ""))[:10]
        lines.append("{:<6} {:<24} {:<10} {:<10} {}".format(letter, label, size, free, fs))
    return "\n".join(lines)


def format_services_table(services: List[Dict]) -> str:
    """Format services as a text table."""
    if not services:
        return "No services found"
    lines = ["Name                 Status      StartType    DisplayName"]
    lines.append("-" * 70)
    for s in services:
        name = s.get("name", "")[:20]
        status = s.get("status", "")[:10]
        start = s.get("start_type", "")[:12]
        display = s.get("display_name", "")[:28]
        lines.append(f"{name:<20} {status:<11} {start:<12} {display}")
    return "\n".join(lines)


def format_processes_table(processes: List[Dict]) -> str:
    """Format processes as a text table."""
    if not processes:
        return "No processes found"
    lines = ["Name                 PID      CPU(s)   Memory(MB)"]
    lines.append("-" * 50)
    for p in processes:
        name = p.get("name", "")[:20]
        pid = str(p.get("id", ""))[:8]
        cpu = f"{p.get('cpu', 0):.1f}"[:7]
        mem = f"{p.get('memory_mb', 0):.1f}"[:10]
        lines.append(f"{name:<20} {pid:<8} {cpu:<8} {mem}")
    return "\n".join(lines)
