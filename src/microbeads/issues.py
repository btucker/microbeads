"""Issue storage and management."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from . import repo

# In-memory caches for loaded issues, keyed by directory path
_active_cache: dict[str, dict[str, dict[str, Any]]] = {}
_closed_cache: dict[str, dict[str, dict[str, Any]]] = {}


def _get_active_cache_key(worktree: Path) -> str:
    """Get the cache key for active issues."""
    return str(repo.get_active_issues_path(worktree))


def _get_closed_cache_key(worktree: Path) -> str:
    """Get the cache key for closed issues."""
    return str(repo.get_closed_issues_path(worktree))


def _get_active_cache(worktree: Path) -> dict[str, dict[str, Any]] | None:
    """Get cached active issues for a worktree, or None if not cached."""
    return _active_cache.get(_get_active_cache_key(worktree))


def _get_closed_cache(worktree: Path) -> dict[str, dict[str, Any]] | None:
    """Get cached closed issues for a worktree, or None if not cached."""
    return _closed_cache.get(_get_closed_cache_key(worktree))


def _update_active_cache(worktree: Path, issue: dict[str, Any]) -> None:
    """Update a single issue in the active cache."""
    cache = _get_active_cache(worktree)
    if cache is not None:
        cache[issue["id"]] = issue


def _update_closed_cache(worktree: Path, issue: dict[str, Any]) -> None:
    """Update a single issue in the closed cache."""
    cache = _get_closed_cache(worktree)
    if cache is not None:
        cache[issue["id"]] = issue


def _remove_from_active_cache(worktree: Path, issue_id: str) -> None:
    """Remove an issue from the active cache."""
    cache = _get_active_cache(worktree)
    if cache is not None:
        cache.pop(issue_id, None)


def _remove_from_closed_cache(worktree: Path, issue_id: str) -> None:
    """Remove an issue from the closed cache."""
    cache = _get_closed_cache(worktree)
    if cache is not None:
        cache.pop(issue_id, None)


def clear_cache(worktree: Path | None = None) -> None:
    """Clear the issues cache.

    Args:
        worktree: If provided, clear cache only for this worktree.
                  If None, clear all caches.
    """
    global _active_cache, _closed_cache
    if worktree is None:
        _active_cache = {}
        _closed_cache = {}
    else:
        _active_cache.pop(_get_active_cache_key(worktree), None)
        _closed_cache.pop(_get_closed_cache_key(worktree), None)


class IssueType(str, Enum):
    BUG = "bug"
    FEATURE = "feature"
    TASK = "task"
    EPIC = "epic"
    CHORE = "chore"


class Status(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    CLOSED = "closed"


def generate_id(title: str, prefix: str = "bd", timestamp: datetime | None = None) -> str:
    """Generate a short issue ID based on title and timestamp."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    # Create a hash from title + timestamp
    # Use 8 hex chars (4 billion possibilities) to avoid collisions at scale
    data = f"{title}{timestamp.isoformat()}".encode()
    hash_hex = hashlib.sha256(data).hexdigest()[:8]

    return f"{prefix}-{hash_hex}"


def now_iso() -> str:
    """Get current UTC time in ISO format."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def create_issue(
    title: str,
    worktree: Path,
    description: str = "",
    issue_type: IssueType = IssueType.TASK,
    priority: int = 2,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new issue dictionary."""
    now = now_iso()
    prefix = repo.get_prefix(worktree)
    issue_id = generate_id(title, prefix)

    return {
        "closed_at": None,
        "closed_reason": None,
        "created_at": now,
        "dependencies": [],
        "description": description,
        "id": issue_id,
        "labels": labels or [],
        "priority": priority,
        "status": Status.OPEN.value,
        "title": title,
        "type": issue_type.value,
        "updated_at": now,
    }


def issue_to_json(issue: dict[str, Any]) -> str:
    """Serialize issue to JSON with sorted keys."""
    return json.dumps(issue, indent=2, sort_keys=True) + "\n"


def load_issue(path: Path) -> dict[str, Any]:
    """Load an issue from a JSON file."""
    return json.loads(path.read_text())


def save_issue(worktree: Path, issue: dict[str, Any]) -> Path:
    """Save an issue to a JSON file in the appropriate directory and update cache."""
    is_closed = issue.get("status") == Status.CLOSED.value

    if is_closed:
        issues_dir = repo.get_closed_issues_path(worktree)
    else:
        issues_dir = repo.get_active_issues_path(worktree)

    issues_dir.mkdir(parents=True, exist_ok=True)

    path = issues_dir / f"{issue['id']}.json"
    path.write_text(issue_to_json(issue))

    # Update appropriate cache
    if is_closed:
        _update_closed_cache(worktree, issue)
    else:
        _update_active_cache(worktree, issue)

    return path


def get_issue(worktree: Path, issue_id: str) -> dict[str, Any] | None:
    """Get an issue by ID, checking active first then closed."""
    active_dir = repo.get_active_issues_path(worktree)
    closed_dir = repo.get_closed_issues_path(worktree)

    # Check active first (most common case)
    path = active_dir / f"{issue_id}.json"
    if path.exists():
        return load_issue(path)

    # Check closed
    path = closed_dir / f"{issue_id}.json"
    if path.exists():
        return load_issue(path)

    # Try partial match in active
    if active_dir.exists():
        for p in active_dir.glob("*.json"):
            if p.stem.startswith(issue_id) or issue_id in p.stem:
                return load_issue(p)

    # Try partial match in closed
    if closed_dir.exists():
        for p in closed_dir.glob("*.json"):
            if p.stem.startswith(issue_id) or issue_id in p.stem:
                return load_issue(p)

    return None


def resolve_issue_id(worktree: Path, issue_id: str) -> str | None:
    """Resolve a partial issue ID to a full ID, checking both active and closed."""
    active_dir = repo.get_active_issues_path(worktree)
    closed_dir = repo.get_closed_issues_path(worktree)

    # Check exact match in active
    if (active_dir / f"{issue_id}.json").exists():
        return issue_id

    # Check exact match in closed
    if (closed_dir / f"{issue_id}.json").exists():
        return issue_id

    # Try partial match in both directories
    matches = []
    for issues_dir in [active_dir, closed_dir]:
        if issues_dir.exists():
            for p in issues_dir.glob("*.json"):
                if p.stem.startswith(issue_id) or issue_id in p.stem:
                    if p.stem not in matches:  # Avoid duplicates
                        matches.append(p.stem)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(f"Ambiguous issue ID '{issue_id}'. Matches: {', '.join(matches)}")

    return None


def load_active_issues(worktree: Path) -> dict[str, dict[str, Any]]:
    """Load active issues (open, in_progress, blocked) into a dict keyed by ID."""
    issues_dir = repo.get_active_issues_path(worktree)

    if not issues_dir.exists():
        return {}

    cache_key = _get_active_cache_key(worktree)
    if cache_key in _active_cache:
        return _active_cache[cache_key]

    issues = {path.stem: load_issue(path) for path in issues_dir.glob("*.json")}
    _active_cache[cache_key] = issues
    return issues


def load_closed_issues(worktree: Path) -> dict[str, dict[str, Any]]:
    """Load closed issues into a dict keyed by ID."""
    issues_dir = repo.get_closed_issues_path(worktree)

    if not issues_dir.exists():
        return {}

    cache_key = _get_closed_cache_key(worktree)
    if cache_key in _closed_cache:
        return _closed_cache[cache_key]

    issues = {path.stem: load_issue(path) for path in issues_dir.glob("*.json")}
    _closed_cache[cache_key] = issues
    return issues


def load_all_issues(worktree: Path) -> dict[str, dict[str, Any]]:
    """Load all issues (active + closed) into a dict keyed by ID."""
    active = load_active_issues(worktree)
    closed = load_closed_issues(worktree)
    return {**active, **closed}


def list_issues(
    worktree: Path,
    status: Status | None = None,
    priority: int | None = None,
    label: str | None = None,
    issue_type: IssueType | None = None,
    _cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """List issues with optional filtering.

    Performance optimization: Only loads closed issues when status=closed is requested.
    """
    if _cache is not None:
        all_issues = _cache
    elif status == Status.CLOSED:
        # Only load closed issues when explicitly requested
        all_issues = load_closed_issues(worktree)
    elif status is not None:
        # Specific non-closed status: only load active issues
        all_issues = load_active_issues(worktree)
    else:
        # No status filter: load all issues
        all_issues = load_all_issues(worktree)

    issues = []
    for issue in all_issues.values():
        # Apply filters
        if status is not None and issue.get("status") != status.value:
            continue
        if priority is not None and issue.get("priority") != priority:
            continue
        if label is not None and label not in issue.get("labels", []):
            continue
        if issue_type is not None and issue.get("type") != issue_type.value:
            continue

        issues.append(issue)

    # Sort by priority (lower is higher priority), then by created_at
    issues.sort(key=lambda x: (x.get("priority", 2), x.get("created_at", "")))

    return issues


def update_issue(
    worktree: Path,
    issue_id: str,
    status: Status | None = None,
    priority: int | None = None,
    title: str | None = None,
    description: str | None = None,
    labels: list[str] | None = None,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Update an issue's fields."""
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    if status is not None:
        issue["status"] = status.value
    if priority is not None:
        issue["priority"] = priority
    if title is not None:
        issue["title"] = title
    if description is not None:
        issue["description"] = description
    if labels is not None:
        issue["labels"] = labels
    if add_labels:
        current = set(issue.get("labels", []))
        issue["labels"] = sorted(current | set(add_labels))
    if remove_labels:
        current = set(issue.get("labels", []))
        issue["labels"] = sorted(current - set(remove_labels))

    issue["updated_at"] = now_iso()
    save_issue(worktree, issue)

    return issue


def close_issue(worktree: Path, issue_id: str, reason: str = "") -> dict[str, Any]:
    """Close an issue and move it to the closed directory."""
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    # Remove from active directory if it exists there
    active_path = repo.get_active_issues_path(worktree) / f"{full_id}.json"
    if active_path.exists():
        active_path.unlink()
        _remove_from_active_cache(worktree, full_id)

    issue["status"] = Status.CLOSED.value
    issue["closed_at"] = now_iso()
    issue["closed_reason"] = reason
    issue["updated_at"] = now_iso()

    # save_issue will save to closed directory since status is closed
    save_issue(worktree, issue)
    return issue


def reopen_issue(worktree: Path, issue_id: str) -> dict[str, Any]:
    """Reopen a closed issue and move it to the active directory."""
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    # Remove from closed directory if it exists there
    closed_path = repo.get_closed_issues_path(worktree) / f"{full_id}.json"
    if closed_path.exists():
        closed_path.unlink()
        _remove_from_closed_cache(worktree, full_id)

    issue["status"] = Status.OPEN.value
    issue["closed_at"] = None
    issue["closed_reason"] = None
    issue["updated_at"] = now_iso()

    # save_issue will save to active directory since status is open
    save_issue(worktree, issue)
    return issue


def add_dependency(worktree: Path, child_id: str, parent_id: str) -> dict[str, Any]:
    """Add a dependency: child depends on (is blocked by) parent."""
    child_full = resolve_issue_id(worktree, child_id)
    parent_full = resolve_issue_id(worktree, parent_id)

    if child_full is None:
        raise ValueError(f"Issue not found: {child_id}")
    if parent_full is None:
        raise ValueError(f"Issue not found: {parent_id}")

    child = get_issue(worktree, child_full)
    if child is None:
        raise ValueError(f"Issue not found: {child_id}")

    # Verify parent exists
    parent = get_issue(worktree, parent_full)
    if parent is None:
        raise ValueError(f"Issue not found: {parent_id}")

    deps = set(child.get("dependencies", []))
    deps.add(parent_full)
    child["dependencies"] = sorted(deps)
    child["updated_at"] = now_iso()

    save_issue(worktree, child)
    return child


def remove_dependency(worktree: Path, child_id: str, parent_id: str) -> dict[str, Any]:
    """Remove a dependency."""
    child_full = resolve_issue_id(worktree, child_id)
    parent_full = resolve_issue_id(worktree, parent_id)

    if child_full is None:
        raise ValueError(f"Issue not found: {child_id}")

    child = get_issue(worktree, child_full)
    if child is None:
        raise ValueError(f"Issue not found: {child_id}")

    deps = set(child.get("dependencies", []))
    if parent_full:
        deps.discard(parent_full)
    child["dependencies"] = sorted(deps)
    child["updated_at"] = now_iso()

    save_issue(worktree, child)
    return child


def is_issue_closed(worktree: Path, issue_id: str) -> bool:
    """Check if an issue is closed by checking the closed directory.

    This is an optimization to avoid loading all closed issues just to check status.
    """
    closed_path = repo.get_closed_issues_path(worktree) / f"{issue_id}.json"
    return closed_path.exists()


def get_open_blockers(
    issue: dict[str, Any],
    active_cache: dict[str, dict[str, Any]],
    worktree: Path | None = None,
) -> list[dict[str, Any]]:
    """Get all open/in_progress issues that block this issue.

    Uses active_cache for active issues. If a dependency is not in active_cache,
    checks if it exists in closed directory (meaning it's resolved).
    """
    blockers = []
    for dep_id in issue.get("dependencies", []):
        dep = active_cache.get(dep_id)
        if dep and dep.get("status") in (
            Status.OPEN.value,
            Status.IN_PROGRESS.value,
            Status.BLOCKED.value,
        ):
            blockers.append(dep)
        elif dep is None and worktree is not None:
            # Dependency not in active cache - check if it's closed
            # If not closed, it might be a dangling reference (treat as not blocking)
            pass
    return blockers


def get_ready_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are ready to work on (open/in_progress with no open blockers)."""
    cache = load_active_issues(worktree)
    ready = []

    for issue in cache.values():
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value):
            continue

        open_blockers = get_open_blockers(issue, cache, worktree)
        if not open_blockers:
            ready.append(issue)

    # Sort by priority, then created_at
    ready.sort(key=lambda x: (x.get("priority", 2), x.get("created_at", "")))
    return ready


def get_blocked_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are blocked by open dependencies."""
    cache = load_active_issues(worktree)
    blocked = []

    for issue in cache.values():
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value, Status.BLOCKED.value):
            continue

        open_blockers = get_open_blockers(issue, cache, worktree)
        if open_blockers:
            # Add blocker info to the issue
            issue["_blockers"] = [b["id"] for b in open_blockers]
            blocked.append(issue)

    # Sort by priority, then created_at
    blocked.sort(key=lambda x: (x.get("priority", 2), x.get("created_at", "")))
    return blocked


def build_dependency_tree(
    worktree: Path,
    issue_id: str,
    _visited: set[str] | None = None,
    _cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dependency tree for an issue.

    Uses memoization to avoid exponential complexity when dependencies
    form diamond patterns (A->B, A->C, B->D, C->D).
    """
    if _visited is None:
        _visited = set()
    if _cache is None:
        _cache = {}

    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        return {"id": issue_id, "error": "not found"}

    # Detect cycle (issue being processed in current path)
    if full_id in _visited:
        return {"id": full_id, "error": "cycle"}

    # Return cached result if we've already fully processed this issue
    if full_id in _cache:
        return _cache[full_id]

    _visited.add(full_id)

    issue = get_issue(worktree, full_id)
    if issue is None:
        _visited.discard(full_id)
        result = {"id": full_id, "error": "not found"}
        _cache[full_id] = result
        return result

    tree = {
        "id": issue["id"],
        "title": issue["title"],
        "status": issue.get("status"),
        "dependencies": [],
    }

    for dep_id in issue.get("dependencies", []):
        dep_tree = build_dependency_tree(worktree, dep_id, _visited, _cache)
        tree["dependencies"].append(dep_tree)

    _visited.discard(full_id)
    _cache[full_id] = tree

    return tree


def _detect_cycle(
    issue_id: str,
    all_issues: dict[str, dict[str, Any]],
    visited: set[str],
    rec_stack: set[str],
) -> list[str] | None:
    """Detect if there's a cycle starting from issue_id. Returns cycle path if found."""
    visited.add(issue_id)
    rec_stack.add(issue_id)

    issue = all_issues.get(issue_id)
    if issue:
        for dep_id in issue.get("dependencies", []):
            if dep_id not in visited:
                cycle = _detect_cycle(dep_id, all_issues, visited, rec_stack)
                if cycle is not None:
                    return cycle
            elif dep_id in rec_stack:
                # Found a cycle
                return [issue_id, dep_id]

    rec_stack.discard(issue_id)
    return None


def run_doctor(
    worktree: Path,
    fix: bool = False,
) -> dict[str, Any]:
    """Run health checks on issues and optionally fix problems.

    Checks for:
    - Orphaned dependencies (references to non-existent issues)
    - Stale blocked status (marked blocked but no open blockers)
    - Dependency cycles
    - Invalid field values

    Returns a dict with 'problems' list and 'fixed' list.
    """
    all_issues = load_all_issues(worktree)
    problems: list[dict[str, Any]] = []
    fixed: list[dict[str, Any]] = []

    valid_statuses = {s.value for s in Status}
    valid_types = {t.value for t in IssueType}

    for issue_id, issue in all_issues.items():
        issue_problems: list[str] = []
        issue_fixes: list[str] = []

        # Check for orphaned dependencies
        orphaned_deps = []
        for dep_id in issue.get("dependencies", []):
            if dep_id not in all_issues:
                orphaned_deps.append(dep_id)
                issue_problems.append(f"orphaned dependency: {dep_id}")

        if orphaned_deps and fix:
            current_deps = set(issue.get("dependencies", []))
            issue["dependencies"] = sorted(current_deps - set(orphaned_deps))
            issue["updated_at"] = now_iso()
            save_issue(worktree, issue)
            issue_fixes.append(f"removed orphaned dependencies: {', '.join(orphaned_deps)}")

        # Check for stale blocked status
        if issue.get("status") == Status.BLOCKED.value:
            open_blockers = get_open_blockers(issue, all_issues)
            if not open_blockers:
                issue_problems.append("marked blocked but has no open blockers")
                if fix:
                    issue["status"] = Status.OPEN.value
                    issue["updated_at"] = now_iso()
                    save_issue(worktree, issue)
                    issue_fixes.append("changed status from blocked to open")

        # Check for invalid status
        status = issue.get("status")
        if status and status not in valid_statuses:
            issue_problems.append(f"invalid status: {status}")
            if fix:
                issue["status"] = Status.OPEN.value
                issue["updated_at"] = now_iso()
                save_issue(worktree, issue)
                issue_fixes.append("reset status to open")

        # Check for invalid type
        issue_type = issue.get("type")
        if issue_type and issue_type not in valid_types:
            issue_problems.append(f"invalid type: {issue_type}")
            if fix:
                issue["type"] = IssueType.TASK.value
                issue["updated_at"] = now_iso()
                save_issue(worktree, issue)
                issue_fixes.append("reset type to task")

        # Check for invalid priority
        priority = issue.get("priority")
        if priority is not None and (not isinstance(priority, int) or priority < 0 or priority > 4):
            issue_problems.append(f"invalid priority: {priority}")
            if fix:
                issue["priority"] = 2
                issue["updated_at"] = now_iso()
                save_issue(worktree, issue)
                issue_fixes.append("reset priority to 2")

        if issue_problems:
            problems.append({"id": issue_id, "title": issue["title"], "problems": issue_problems})
        if issue_fixes:
            fixed.append({"id": issue_id, "fixes": issue_fixes})

    # Check for dependency cycles (separate pass)
    visited: set[str] = set()
    for issue_id in all_issues:
        if issue_id not in visited:
            cycle = _detect_cycle(issue_id, all_issues, visited, set())
            if cycle:
                problems.append(
                    {
                        "id": cycle[0],
                        "title": all_issues[cycle[0]]["title"],
                        "problems": [f"dependency cycle detected: {cycle[0]} -> {cycle[1]}"],
                    }
                )

    return {
        "problems": problems,
        "fixed": fixed,
        "total_issues": len(all_issues),
    }


def migrate_flat_to_status_dirs(worktree: Path) -> int:
    """Migrate issues from flat structure to active/closed directories.

    Returns the number of issues migrated.
    """
    issues_dir = repo.get_issues_path(worktree)
    active_dir = repo.get_active_issues_path(worktree)
    closed_dir = repo.get_closed_issues_path(worktree)

    if not issues_dir.exists():
        return 0

    # Create subdirectories
    active_dir.mkdir(parents=True, exist_ok=True)
    closed_dir.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for path in issues_dir.glob("*.json"):
        # Skip if this is not a file in the root issues dir
        if path.parent != issues_dir:
            continue

        issue = load_issue(path)
        is_closed = issue.get("status") == Status.CLOSED.value

        # Move to appropriate directory
        if is_closed:
            dest = closed_dir / path.name
        else:
            dest = active_dir / path.name

        path.rename(dest)
        migrated += 1

    # Clear cache after migration
    clear_cache(worktree)

    return migrated
