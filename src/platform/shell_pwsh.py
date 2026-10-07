"""Operand-aware allowlist for read-only PowerShell diagnostics.

Phase 3 of the Windows support plan. This mirrors the philosophy of
``src/command_policy.py``: a positive allowlist of command names plus
per-command flag/parameter validation, with an explicit denylist of
engine- and mutation-shaped cmdlets. The policy only *validates*; it never
executes anything.
"""
import base64
import re
from typing import Iterable, Optional, Tuple

# Cmdlets that run arbitrary code, mutate state or reach the network.
UNSAFE_PWSH = {
    'invoke-expression', 'iex', 'invoke-command', 'start-process', 'stop-process',
    'remove-item', 'ri', 'rm', 'del', 'erase', 'rd', 'remove-*',
    'set-item', 'set-content', 'sc', 'set-*', 'new-item', 'ni', 'new-*',
    'clear-content', 'clear-item', 'copy-item', 'cpi', 'cp', 'move-item', 'mi',
    'mv', 'move-*', 'rename-item', 'rni', 'rn', 'invoke-webrequest', 'iwr',
    'invoke-restmethod', 'irm', 'start-service', 'stop-service', 'set-service',
    'restart-service', 'suspend-service', 'resume-service', 'stop-computer',
    'restart-computer', 'disable-netadapter', 'enable-netadapter', 'out-file',
    'export-csv', 'export-clixml', 'add-content', 'ac', 'tee-object', 'write-output',
    'powershell', 'pwsh', 'cmd', 'wsl', 'wsl.exe', 'winget', 'choco', 'scoop',
    'install-module', 'uninstall-module', 'update-module', 'save-module',
    'find-module', 'publish-module', 'register-psrepository',
}

# Read-only cmdlets: network state, system info, logs, processes, volumes.
ALLOWED_PWSH = {
    'get-netadapter': {'name'},
    'get-netipconfiguration': {'interfacealias', 'detailed'},
    'get-dnsclientserveraddress': {'interfacealias', 'addressfamily'},
    'get-service': {'name', 'displayname'},
    'get-process': {'name', 'id'},
    'get-volume': {},
    'get-psdrive': {'name'},
    'get-computerinfo': {'property'},
    'get-winevent': {'logname', 'maxevents'},
    'get-hotfix': {'id', 'description'},
    'get-date': {},
    'get-culture': {},
    'get-uiculture': {},
    'get-alias': {'name', 'definition'},
    'get-command': {'name', 'module', 'commandtype'},
    'get-module': {'name', 'listavailable'},
    'get-executionpolicy': {'list', 'scope'},
    'get-nettcpipaddress': {'interfacealias', 'addressfamily'},
    'get-netroute': {'destinationprefix', 'interfacealias'},
    'get-netfirewallprofile': {'name'},
    'get-psprovider': {},
    'get-help': {'name'},
    'get-variable': {'name'},
    'get-history': {},
    'get-eventlog': {'logname', 'newest'},
    'get-counter': {},
}

# Parameters that carry a value (as opposed to boolean switches) per cmdlet.
VALUE_PARAMS = {
    'get-netadapter': {'name'},
    'get-netipconfiguration': {'interfacealias'},
    'get-dnsclientserveraddress': {'interfacealias', 'addressfamily'},
    'get-service': {'name', 'displayname'},
    'get-process': {'name', 'id'},
    'get-psdrive': {'name'},
    'get-computerinfo': {'property'},
    'get-winevent': {'logname', 'maxevents'},
    'get-hotfix': {'id', 'description'},
    'get-alias': {'name', 'definition'},
    'get-command': {'name', 'module'},
    'get-module': {'name'},
    'get-executionpolicy': {'scope'},
    'get-nettcpipaddress': {'interfacealias'},
    'get-netroute': {'destinationprefix', 'interfacealias'},
    'get-netfirewallprofile': {'name'},
    'get-help': {'name'},
    'get-variable': {'name'},
    'get-eventlog': {'logname', 'newest'},
}

# Boolean switches (never take a value). Presence alone is safe.
SWITCH_PARAMS = {
    'get-netipconfiguration': {'detailed'},
    'get-executionpolicy': {'list'},
    'get-module': {'listavailable'},
}

# A cmdlet invocation must never contain these tokens anywhere: they enable
# pipelines into mutation, redirection or shell escapes.
FORBIDDEN_TOKENS = ('|', ';', '&', '>', '<', '`', '$(', '${', ')', '(', "'")
NAME_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$')
VALUE_PATTERN = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.,:\-*\\/()\[\]]{0,255}$')
MAX_ARGV = 32


def validate_pwsh_arguments(argv: Iterable[str]) -> bool:
    """Validate a PowerShell probe argv: allowlisted cmdlet, safe operands.

    ``argv[0]`` is the cmdlet name (case-insensitive). Parameters must be
    allowlisted per cmdlet, either as ``-Name value`` or ``-Switch``. Values
    matching a conservative pattern keep injection tokens out; any forbidden
    token anywhere rejects the whole invocation.
    """
    arguments = tuple(argv)
    if not arguments or len(arguments) > MAX_ARGV or not all(isinstance(argument, str) for argument in arguments):
        return False
    command = arguments[0].lower()
    if not NAME_PATTERN.fullmatch(arguments[0]):
        return False
    if command in UNSAFE_PWSH or command not in ALLOWED_PWSH:
        return False
    for argument in arguments:
        if any(token in argument for token in FORBIDDEN_TOKENS):
            return False
    values = VALUE_PARAMS.get(command, set())
    switches = SWITCH_PARAMS.get(command, set())
    index = 1
    while index < len(arguments):
        argument = arguments[index]
        index += 1
        if not argument.startswith('-') or not NAME_PATTERN.fullmatch(argument[1:]):
            return False
        name = argument[1:].lower()
        if name in switches:
            continue
        if name not in values:
            return False
        if index == len(arguments):
            return False
        value = arguments[index]
        index += 1
        if not VALUE_PATTERN.fullmatch(value):
            return False
    return True


def launch_argv(argv: Iterable[str]) -> Optional[Tuple[str, ...]]:
    """Build a non-interactive PowerShell process for a validated cmdlet.

    The caller supplies a cmdlet argv, never a script. Only this fixed
    wrapper controls encoding and execution; quotes around operand values
    keep wildcards, commas and backslashes as data in the generated script.
    ``run_bounded`` decodes UTF-8, including Windows PowerShell 5.1 output.
    """
    arguments = tuple(argv)
    if not validate_pwsh_arguments(arguments):
        return None
    invocation = " ".join(
        argument if index == 0 or argument.startswith('-') else "'" + argument + "'"
        for index, argument in enumerate(arguments))
    script = ("$ErrorActionPreference = 'Stop'; "
              "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
              "$OutputEncoding = [Console]::OutputEncoding; " + invocation)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ("powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded)
