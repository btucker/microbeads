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


# Validation constants
MIN_PRIORITY = 0
MAX_PRIORITY = 4


class ValidationError(ValueError):
    """Raised when input validation fails."""

    pass


def validate_title(title: str) -> str:
    """Validate and normalize an issue title."""
    if not isinstance(title, str):
        raise ValidationError(f"Title must be a string, got {type(title).__name__}")
    title = title.strip()
    if not title:
        raise ValidationError("Title cannot be empty")
    if len(title) > 500:
        raise ValidationError(f"Title too long ({len(title)} chars). Maximum is 500 characters")
    return title


def validate_priority(priority: int) -> int:
    """Validate priority is in valid range (0-4)."""
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise ValidationError(f"Priority must be an integer, got {type(priority).__name__}")
    if priority < MIN_PRIORITY or priority > MAX_PRIORITY:
        raise ValidationError(
            f"Priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}, got {priority}"
        )
    return priority


def validate_labels(labels: list[str] | None) -> list[str]:
    """Validate labels list."""
    if labels is None:
        return []
    if not isinstance(labels, list):
        raise ValidationError(f"Labels must be a list, got {type(labels).__name__}")
    validated = []
    for i, label in enumerate(labels):
        if not isinstance(label, str):
            raise ValidationError(
                f"Label at index {i} must be a string, got {type(label).__name__}"
            )
        label = label.strip()
        if not label:
            raise ValidationError(f"Label at index {i} cannot be empty")
        if len(label) > 100:
            raise ValidationError(
                f"Label at index {i} too long ({len(label)} chars). Maximum is 100 characters"
            )
        validated.append(label)
    return validated


def validate_description(description: str) -> str:
    """Validate and normalize a description."""
    if not isinstance(description, str):
        raise ValidationError(f"Description must be a string, got {type(description).__name__}")
    return description.strip()


def generate_id(title: str, prefix: str = "mb", timestamp: datetime | None = None) -> str:
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
    """Create a new issue dictionary.

    Args:
        title: Issue title (required, non-empty)
        worktree: Path to the worktree
        description: Optional description
        issue_type: Type of issue (bug, feature, task, epic, chore)
        priority: Priority 0-4 (0=critical, 4=low)
        labels: Optional list of labels

    Raises:
        ValidationError: If any input validation fails
    """
    # Validate inputs
    title = validate_title(title)
    description = validate_description(description)
    priority = validate_priority(priority)
    labels = validate_labels(labels)

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
        "labels": labels,
        "priority": priority,
        "status": Status.OPEN.value,
        "title": title,
        "type": issue_type.value,
        "updated_at": now,
    }


def issue_to_json(issue: dict[str, Any]) -> str:
    """Serialize issue to JSON with sorted keys."""
    return json.dumps(issue, indent=2, sort_keys=True) + "\n"


class CorruptedFileError(ValueError):
    """Raised when a JSON file is corrupted and cannot be parsed."""

    def __init__(self, path: Path, original_error: Exception):
        self.path = path
        self.original_error = original_error
        super().__init__(f"Corrupted JSON file: {path} - {original_error}")


def load_issue(path: Path) -> dict[str, Any]:
    """Load an issue from a JSON file.

    Raises:
        CorruptedFileError: If the JSON file is corrupted
        FileNotFoundError: If the file doesn't exist
    """
    try:
        content = path.read_text()
        if not content.strip():
            raise CorruptedFileError(path, ValueError("File is empty"))
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise CorruptedFileError(path, e) from e


def save_issue(worktree: Path, issue: dict[str, Any]) -> Path:
    """Save an issue to a JSON file."""
    issues_dir = repo.get_issues_path(worktree)
    issues_dir.mkdir(parents=True, exist_ok=True)

    path = issues_dir / f"{issue['id']}.json"
    path.write_text(issue_to_json(issue))
    return path


def get_issue(worktree: Path, issue_id: str) -> dict[str, Any] | None:
    """Get an issue by ID.

    Raises:
        CorruptedFileError: If the exact match file exists but is corrupted

    Returns:
        Issue data, or None if not found. Skips corrupted files during partial matching.
    """
    issues_dir = repo.get_issues_path(worktree)
    path = issues_dir / f"{issue_id}.json"

    if path.exists():
        # Exact match - let CorruptedFileError propagate
        return load_issue(path)

    # Try partial match - skip corrupted files
    for p in issues_dir.glob("*.json"):
        if p.stem.startswith(issue_id) or issue_id in p.stem:
            try:
                return load_issue(p)
            except CorruptedFileError:
                # Skip corrupted files during partial matching
                continue

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


def load_all_issues(worktree: Path, skip_corrupted: bool = True) -> dict[str, dict[str, Any]]:
    """Load all issues into a dict keyed by ID. Single disk scan.

    Args:
        worktree: Path to the worktree
        skip_corrupted: If True, skip corrupted files silently.
                       If False, raise CorruptedFileError on first corruption.

    Returns:
        Dictionary mapping issue IDs to issue data

    Raises:
        CorruptedFileError: If skip_corrupted is False and a file is corrupted
    """
    issues_dir = repo.get_issues_path(worktree)

    if not issues_dir.exists():
        return {}

    issues = {}
    for path in issues_dir.glob("*.json"):
        try:
            issues[path.stem] = load_issue(path)
        except CorruptedFileError:
            if not skip_corrupted:
                raise
            # Silently skip corrupted files when skip_corrupted is True
    return issues


def list_issues(
    worktree: Path,
    status: Status | None = None,
    priority: int | None = None,
    label: str | None = None,
    issue_type: IssueType | None = None,
    _cache: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """List issues with optional filtering."""
    all_issues = _cache if _cache is not None else load_all_issues(worktree)

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
    """Update an issue's fields.

    Args:
        worktree: Path to the worktree
        issue_id: Full or partial issue ID
        status: New status (optional)
        priority: New priority 0-4 (optional)
        title: New title (optional)
        description: New description (optional)
        labels: Replace all labels (optional)
        add_labels: Labels to add (optional)
        remove_labels: Labels to remove (optional)

    Raises:
        ValidationError: If any input validation fails
        ValueError: If issue not found
    """
    full_id = resolve_issue_id(worktree, issue_id)
    if full_id is None:
        raise ValueError(f"Issue not found: {issue_id}")

    issue = get_issue(worktree, full_id)
    if issue is None:
        raise ValueError(f"Issue not found: {issue_id}")

    # Validate and apply updates
    if status is not None:
        issue["status"] = status.value
    if priority is not None:
        priority = validate_priority(priority)
        issue["priority"] = priority
    if title is not None:
        title = validate_title(title)
        issue["title"] = title
    if description is not None:
        description = validate_description(description)
        issue["description"] = description
    if labels is not None:
        labels = validate_labels(labels)
        issue["labels"] = labels
    if add_labels:
        add_labels = validate_labels(add_labels)
        current = set(issue.get("labels", []))
        issue["labels"] = sorted(current | set(add_labels))
    if remove_labels:
        remove_labels = validate_labels(remove_labels)
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


def would_create_cycle(
    cache: dict[str, dict[str, Any]],
    child_id: str,
    parent_id: str,
) -> bool:
    """Check if adding child -> parent dependency would create a cycle.

    Returns True if parent_id depends on child_id (directly or transitively).
    """

    def has_path_to(start_id: str, target_id: str, visited: set[str]) -> bool:
        """Check if there's a dependency path from start to target."""
        if start_id in visited:
            return False
        if start_id == target_id:
            return True

        visited.add(start_id)
        issue = cache.get(start_id)
        if not issue:
            return False

        for dep_id in issue.get("dependencies", []):
            if has_path_to(dep_id, target_id, visited):
                return True
        return False

    # Check if parent depends on child (which would create a cycle)
    return has_path_to(parent_id, child_id, set())


def add_dependency(worktree: Path, child_id: str, parent_id: str) -> dict[str, Any]:
    """Add a dependency: child depends on (is blocked by) parent.

    Args:
        worktree: Path to the worktree
        child_id: ID of the issue that depends on parent
        parent_id: ID of the issue that blocks child

    Raises:
        ValidationError: If trying to add self-dependency or circular dependency
        ValueError: If issue not found
    """
    child_full = resolve_issue_id(worktree, child_id)
    parent_full = resolve_issue_id(worktree, parent_id)

    if child_full is None:
        raise ValueError(f"Issue not found: {child_id}")
    if parent_full is None:
        raise ValueError(f"Issue not found: {parent_id}")

    # Prevent self-dependency
    if child_full == parent_full:
        raise ValidationError("An issue cannot depend on itself")

    # Load all issues to check for circular dependencies
    cache = load_all_issues(worktree)

    child = cache.get(child_full)
    if child is None:
        raise ValueError(f"Issue not found: {child_id}")

    # Verify parent exists
    parent = cache.get(parent_full)
    if parent is None:
        raise ValueError(f"Issue not found: {parent_id}")

    # Check for circular dependency
    if would_create_cycle(cache, child_full, parent_full):
        raise ValidationError(
            f"Adding this dependency would create a circular dependency: "
            f"{parent_full} already depends on {child_full}"
        )

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


def get_open_blockers(
    issue: dict[str, Any],
    cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Get all open/in_progress issues that block this issue."""
    blockers = []
    for dep_id in issue.get("dependencies", []):
        dep = cache.get(dep_id)
        if dep and dep.get("status") in (
            Status.OPEN.value,
            Status.IN_PROGRESS.value,
            Status.BLOCKED.value,
        ):
            blockers.append(dep)
    return blockers


def get_ready_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are ready to work on (open/in_progress with no open blockers)."""
    cache = load_all_issues(worktree)
    ready = []

    for issue in cache.values():
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value):
            continue

        open_blockers = get_open_blockers(issue, cache)
        if not open_blockers:
            ready.append(issue)

    # Sort by priority, then created_at
    ready.sort(key=lambda x: (x.get("priority", 2), x.get("created_at", "")))
    return ready


def get_blocked_issues(worktree: Path) -> list[dict[str, Any]]:
    """Get issues that are blocked by open dependencies."""
    cache = load_all_issues(worktree)
    blocked = []

    for issue in cache.values():
        status = issue.get("status")
        if status not in (Status.OPEN.value, Status.IN_PROGRESS.value, Status.BLOCKED.value):
            continue

        open_blockers = get_open_blockers(issue, cache)
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
