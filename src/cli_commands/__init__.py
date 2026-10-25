"""CLI command handlers split by functional area.

Each module owns the argparse subparser registration and the handler for one
command group. The main CLIApp class delegates to these modules, keeping
cli.py focused on application lifecycle and shared plumbing.
"""
