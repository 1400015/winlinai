"""Run the type check for one target platform.

The gate is not a single list: some modules only exist on POSIX and others
only on native Windows. Checking the wrong list reports missing platform
symbols instead of real defects, so the list is assembled per platform.

The shared settings live in ``pyproject.toml`` (``[tool.mypy]``). The lists
are read from there as well: ``[tool.mypy].files`` holds the modules that
type check on every platform, ``[tool.mypy.posix_only].files`` the ones that
need POSIX and ``[tool.mypy.windows_only].files`` the ones that need Windows.

Usage::

    python scripts/typecheck.py --platform linux
    python scripts/typecheck.py --platform win32
"""

import argparse
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "pyproject.toml"


def _table(text, name):
    """Read a list of modules from the [tool.typecheck] table."""
    pattern = r"\[tool\.typecheck\](.*?)(?=\n\[|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        raise SystemExit("pyproject.toml has no [tool.typecheck] table")
    body = match.group(1)
    entries = re.search(re.escape(name) + r"\s*=\s*\[(.*?)\]", body, re.DOTALL)
    if not entries:
        return []
    return re.findall(r'"([^"]+)"', entries.group(1))


def _shared(text):
    match = re.search(r"\[tool\.mypy\]\s*(.*?)(?=\n\[tool\.|\Z)", text, re.DOTALL)
    if not match:
        raise SystemExit("pyproject.toml has no [tool.mypy] table")
    return re.findall(r'"([^"]+\.py)"', match.group(1))


def modules_for(platform):
    """Return the modules that must be checked for the given platform."""
    text = CONFIG.read_text(encoding="utf-8")
    shared = _shared(text)
    posix = _table(text, "posix_files")
    windows = _table(text, "windows_files")
    if platform == "linux":
        selected = shared + posix
    elif platform == "win32":
        selected = shared + windows
    else:
        raise SystemExit("unknown platform: " + platform)
    ordered = []
    for name in selected:
        if name not in ordered:
            ordered.append(name)
    missing = [name for name in ordered if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("these modules do not exist: " + ", ".join(missing))
    return ordered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("linux", "win32"), required=True)
    parser.add_argument("--config", default=str(CONFIG))
    arguments = parser.parse_args()

    modules = modules_for(arguments.platform)
    command = [sys.executable, "-m", "mypy", "--config-file", arguments.config,
               "--platform", arguments.platform] + modules
    print("Type checking {} modules for platform {}".format(len(modules), arguments.platform))
    return subprocess.call(command, cwd=str(ROOT))


if __name__ == "__main__":
    sys.exit(main())
