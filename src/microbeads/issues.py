"""Issue storage and management."""

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from . import repo


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
    data = f"{title}{timestamp.isoformat()}".encode()
    hash_hex = hashlib.sha256(data).hexdigest()[:4]

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
    """Save an issue to a JSON file."""
    issues_dir = repo.get_issues_path(worktree)
    issues_dir.mkdir(parents=True, exist_ok=True)

    path = issues_dir / f"{issue['id']}.json"
    path.write_text(issue_to_json(issue))
    return path


def get_issue(worktree: Path, issue_id: str) -> dict[str, Any] | None:
    """Get an issue by ID."""
    issues_dir = repo.get_issues_path(worktree)
    path = issues_dir / f"{issue_id}.json"

    if path.exists():
        return load_issue(path)

    # Try partial match
    for p in issues_dir.glob("*.json"):
        if p.stem.startswith(issue_id) or issue_id in p.stem:
            return load_issue(p)

    return None


def resolve_issue_id(worktree: Path, issue_id: str) -> str | None:
    """Resolve a partial issue ID to a full ID."""
    issues_dir = repo.get_issues_path(worktree)
    path = issues_dir / f"{issue_id}.json"

    if path.exists():
        return issue_id

    # Try partial match
    matches = []
    for p in issues_dir.glob("*.json"):
        if p.stem.startswith(issue_id) or issue_id in p.stem:
            matches.append(p.stem)

    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        raise ValueError(f"Ambiguous issue ID '{issue_id}'. Matches: {', '.join(matches)}")

    return None


def list_issues(
    worktree: Path,
    status: Status | None = None,
    priority: int | None = None,
    label: str | None = None,
    issue_type: IssueType | None = None,
) -> list[dict[str, Any]]:
    """List issues with optional filtering."""
    issues_dir = repo.get_issues_path(worktree)

    if not issues_dir.exists():
        return []

    issues = []
    for path in issues_dir.glob("*.json"):
        issue = load_issue(path)

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
    """Close an issue."""
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue["status"] = Status.CLOSED.value
    issue["closed_at"] = now_iso()
    issue["closed_reason"] = reason
    issue["updated_at"] = now_iso()

    save_issue(worktree, issue)
    return issue


def reopen_issue(worktree: Path, issue_id: str) -> dict[str, Any]:
    """Reopen a closed issue."""
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue["status"] = Status.OPEN.value
    issue["closed_at"] = None
    issue["closed_reason"] = None
    issue["updated_at"] = now_iso()

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


def get_open_blockers(worktree: Path, issue: dict[str, Any]) -> list[dict[str, Any]]:
    """Get all open/in_progress issues that block this issue."""
    blockers = []
    for dep_id in issue.get("dependencies", []):
        dep = get_issue(worktree, dep_id)
        if dep and dep.get("status") in (Status.OPEN.value, Status.IN_PROGRESS.value, Status.BLOCKED.value):
            blockers.append(dep)
    return blockers


def get_ready_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are ready to work on (open/in_progress with no open blockers)."""
    all_issues = list_issues(worktree)
    ready = []

    for issue in all_issues:
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value):
            continue

        open_blockers = get_open_blockers(worktree, issue)
        if not open_blockers:
            ready.append(issue)

    return ready


def get_blocked_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are blocked by open dependencies."""
    all_issues = list_issues(worktree)
    blocked = []

    for issue in all_issues:
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value, Status.BLOCKED.value):
            continue

        open_blockers = get_open_blockers(worktree, issue)
        if open_blockers:
            # Add blocker info to the issue
            issue["_blockers"] = [b["id"] for b in open_blockers]
            blocked.append(issue)

    return blocked


def build_dependency_tree(worktree: Path, issue_id: str, visited: set[str] | None = None) -> dict[str, Any]:
    """Build a dependency tree for an issue."""
    if visited is None:
        visited = set()

    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        return {"id": issue_id, "error": "not found"}

    if full_id in visited:
        return {"id": full_id, "error": "cycle"}

    visited.add(full_id)

    issue = get_issue(worktree, full_id)
    if issue is None:
        return {"id": full_id, "error": "not found"}

    tree = {
        "id": issue["id"],
        "title": issue["title"],
        "status": issue.get("status"),
        "dependencies": [],
    }

    for dep_id in issue.get("dependencies", []):
        dep_tree = build_dependency_tree(worktree, dep_id, visited.copy())
        tree["dependencies"].append(dep_tree)

    return tree
