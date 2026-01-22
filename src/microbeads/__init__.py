"""Microbeads - A simplified git-backed issue tracker for AI agents."""

import shutil
import sys
from pathlib import Path

__version__ = "0.1.0"


def _is_dogfooding() -> bool:
    """Check if we're running within the microbeads repo itself (dogfooding)."""
    try:
        cwd = Path.cwd()
        # Walk up to find pyproject.toml
        for parent in [cwd, *cwd.parents]:
            pyproject = parent / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text()
                # Check if this is the microbeads project
                if 'name = "microbeads"' in content:
                    return True
                break  # Found a pyproject.toml but it's not microbeads
    except (OSError, PermissionError):
        pass
    return False


def get_command_name() -> str:
    """Get the command name for invoking microbeads.

    Returns 'uv run mb' if dogfooding (developing within microbeads repo),
    'mb' if available in PATH or we were invoked as 'mb',
    otherwise returns 'uvx microbeads' for portability.
    """
    # Check if we're dogfooding (developing microbeads itself)
    if _is_dogfooding():
        return "uv run mb"

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
