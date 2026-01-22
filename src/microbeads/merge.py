"""JSON merge driver for git."""

import json
import sys
from pathlib import Path
from typing import Any


def merge_json_files(base_path: str, ours_path: str, theirs_path: str) -> int:
    """Merge two JSON files with a common base.

    Implements a 3-way merge with these strategies:
    - For metadata.json: prefer theirs (remote) version
    - Scalars: Last-Write-Wins based on updated_at
    - Arrays (labels, dependencies): Union merge
    - Timestamps: Take the later one

    Args:
        base_path: Path to the common ancestor version (%O)
        ours_path: Path to our version (%A) - this file is modified in place
        theirs_path: Path to their version (%B)

    Returns:
        0 on success, 1 on conflict that couldn't be resolved
    """

    def read_json(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            return {}
        content = p.read_text().strip()
        if not content:
            return {}
        return json.loads(content)

    try:
        base = read_json(base_path)
        ours = read_json(ours_path)
        theirs = read_json(theirs_path)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading files: {e}", file=sys.stderr)
        return 1

    # For metadata.json (identified by having 'version' but no 'id'), prefer theirs
    is_metadata = "version" in (ours or theirs) and "id" not in (ours or theirs)
    if is_metadata:
        # Always prefer remote (theirs) for metadata to avoid conflicts
        merged = theirs if theirs else ours
    else:
        merged = merge_issues(base, ours, theirs)

    # Write result back to ours_path (git expects this)
    Path(ours_path).write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n")
    return 0


def merge_issues(base: dict, ours: dict, theirs: dict) -> dict[str, Any]:
    """Merge two issue versions with a common base."""
    # Determine which version is newer based on updated_at
    ours_updated = ours.get("updated_at", "")
    theirs_updated = theirs.get("updated_at", "")

    # Newer version wins for scalar fields
    newer = ours if ours_updated >= theirs_updated else theirs

    result = {}

    # Start with base, then apply changes
    all_keys = set(base.keys()) | set(ours.keys()) | set(theirs.keys())

    for key in all_keys:
        base_val = base.get(key)
        ours_val = ours.get(key)
        theirs_val = theirs.get(key)

        # Array fields: union merge
        if key in ("labels", "dependencies"):
            base_set = set(base_val or [])
            ours_set = set(ours_val or [])
            theirs_set = set(theirs_val or [])

            # Union of additions, intersection of removals
            # If both added something, include it
            # If one removed something that was in base, remove it
            added = (ours_set - base_set) | (theirs_set - base_set)
            kept = ours_set & theirs_set & base_set
            result[key] = sorted(added | kept)

        # Timestamp fields: take the later one
        elif key in ("updated_at", "closed_at", "created_at"):
            # For closed_at, take non-None if one exists
            if key == "closed_at":
                if ours_val and theirs_val:
                    result[key] = max(ours_val, theirs_val)
                else:
                    result[key] = ours_val or theirs_val
            else:
                result[key] = max(ours_val or "", theirs_val or "") or None

        # ID should never change
        elif key == "id":
            result[key] = ours_val or theirs_val or base_val

        # Scalar fields: last-write-wins
        else:
            # If both changed from base, take the newer one
            if ours_val != base_val and theirs_val != base_val:
                result[key] = newer.get(key)
            elif ours_val != base_val:
                result[key] = ours_val
            elif theirs_val != base_val:
                result[key] = theirs_val
            else:
                result[key] = base_val

    return result


def main() -> int:
    """Entry point for git merge driver."""
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <base> <ours> <theirs>", file=sys.stderr)
        return 1

    return merge_json_files(sys.argv[1], sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    sys.exit(main())
