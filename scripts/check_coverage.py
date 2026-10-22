"""Enforce a coverage floor over the platform-independent core.

The Linux CI job measures the core and the GTK track. The Qt shell and the
native Windows modules need their own runners (real Qt bindings, native
Windows APIs), so they are reported but excluded from the floor: a job that
cannot execute a module must not be allowed to fail it.

Usage::

    python -m coverage run scripts/run_gtk_tests.py
    python scripts/check_coverage.py
    python scripts/check_coverage.py --floor 65        # temporary override
    python scripts/check_coverage.py --report-only     # never fails
"""

import argparse
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
DATA = ROOT / "coverage.json"

GTK_MARKER = re.compile(r"^\s*(import gi|from gi\.repository)", re.MULTILINE)
QT_MARKER = re.compile(r"^\s*(from PySide6|import PySide6)", re.MULTILINE)
WINDOWS_MARKER = re.compile(r"^\s*(import winreg|from winreg)", re.MULTILINE)


def read_floor():
    """Read the configured floor from pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"\[tool\.coverage\.core_floor\]\s*percent\s*=\s*([0-9.]+)", text)
    if not match:
        raise SystemExit("pyproject.toml has no [tool.coverage.core_floor] percent value")
    return float(match.group(1))


def platform_specific(relative_path):
    """Report whether the module needs GTK, Qt or native Windows."""
    if relative_path.startswith("qt_") or "/qt_" in relative_path:
        return "qt"
    if relative_path.startswith("windows_") or "windows_" in relative_path:
        return "windows"
    text = (ROOT / relative_path).read_text(encoding="utf-8")
    if QT_MARKER.search(text):
        return "qt"
    if GTK_MARKER.search(text):
        return "gtk"
    if WINDOWS_MARKER.search(text):
        return "windows"
    return None


def load_report():
    if not DATA.is_file():
        raise SystemExit("coverage.json is missing; run the suite under coverage first")
    with DATA.open(encoding="utf-8") as stream:
        return json.load(stream)


def summarize(report, names):
    """Return (covered, total, percentage) for the given file names."""
    covered = 0
    total = 0
    for name in names:
        entry = report.get("files", {}).get(name)
        if entry is None:
            continue
        summary = entry["summary"]
        covered += summary["covered_lines"] + summary.get("covered_branches", 0)
        total += summary["num_statements"] + summary.get("num_branches", 0)
    if not total:
        return 0, 0, 0.0
    return covered, total, round(covered * 100.0 / total, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--floor", type=float, default=None,
                        help="override the configured floor")
    parser.add_argument("--report-only", action="store_true",
                        help="report the numbers without failing")
    parser.add_argument("--top", type=int, default=15,
                        help="how many weak modules to list")
    arguments = parser.parse_args()

    floor = read_floor() if arguments.floor is None else arguments.floor
    report = load_report()
    files = report.get("files", {})

    core = []
    other = {}
    for name in sorted(files):
        relative = name.replace("\\", "/")
        if not relative.startswith("src/"):
            continue
        kind = platform_specific(relative)
        if kind is None:
            core.append(name)
        else:
            other[name] = kind

    core_covered, core_total, core_percent = summarize(report, core)
    all_covered, all_total, all_percent = summarize(report, sorted(files))

    print("Coverage report (branch mode)")
    print("  core (platform independent) : {} / {} statements = {}%".format(
        core_covered, core_total, core_percent))
    print("  every measured module        : {} / {} statements = {}%".format(
        all_covered, all_total, all_percent))
    for kind in sorted(set(other.values())):
        names = [name for name, value in other.items() if value == kind]
        covered, total, percent = summarize(report, names)
        print("  {:<27} : {} / {} statements = {}%".format(
            kind + " modules (reported only)", covered, total, percent))

    weak = []
    for name in core:
        entry = files[name]
        summary = entry["summary"]
        total = summary["num_statements"] + summary.get("num_branches", 0)
        covered = summary["covered_lines"] + summary.get("covered_branches", 0)
        percent = round(covered * 100.0 / total, 1) if total else 100.0
        weak.append((percent, name, entry.get("missing_lines", [])))
    weak.sort()

    if weak:
        print("\nWeakest core modules:")
        for percent, name, missing in weak[:arguments.top]:
            first = ", ".join(str(line) for line in missing[:8])
            print("  {:>5}%  {}".format(percent, name))
            if first:
                print("         missing lines: {}".format(first))

    print("\nCoverage floor for the core: {}%".format(floor))
    if arguments.report_only:
        print("Report only: the floor was not enforced.")
        return 0
    if core_percent < floor:
        print("FAILED: the core covers {}% and the floor is {}%.".format(core_percent, floor),
              file=sys.stderr)
        return 1
    print("OK: the core covers {}% (floor {}%).".format(core_percent, floor))
    return 0


if __name__ == "__main__":
    sys.exit(main())
