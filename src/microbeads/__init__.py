"""Microbeads - A simplified git-backed issue tracker for AI agents."""

import shutil
import sys
from pathlib import Path

__version__ = "0.1.0"


def get_command_name() -> str:
    """Get the command name for invoking microbeads.

    Returns 'mb' if available in PATH or we were invoked as 'mb',
    otherwise returns 'uvx microbeads' for portability.
    """
    # Check argv[0] to see how we were called
    if sys.argv and sys.argv[0]:
        prog = Path(sys.argv[0]).name
        if prog == "mb":
            return "mb"

    # Check if mb is available in PATH
    if shutil.which("mb"):
        return "mb"

    # Default to uvx microbeads for portability
    return "uvx microbeads"
