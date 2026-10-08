"""PyInstaller entry point for the Windows Qt package.

This file lives outside the src package on purpose: as the analyzed script
it has no relative imports and never pulls the GTK path, so the frozen
executable starts straight into the Qt track.
"""
import sys


def main() -> int:
    from src.qt_app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
