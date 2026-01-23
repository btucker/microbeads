"""Issue storage and management."""

import hashlib
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import orjson

from . import repo

# In-memory caches for loaded issues, keyed by directory path
_active_cache: dict[str, dict[str, dict[str, Any]]] = {}
_closed_cache: dict[str, dict[str, dict[str, Any]]] = {}

# Disk cache file names
_ACTIVE_CACHE_FILE = "active_issues.cache"
_CLOSED_CACHE_FILE = "closed_issues.cache"


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


def clear_cache(worktree: Path | None = None, include_disk: bool = False) -> None:
    """Clear the issues cache.

    Args:
        worktree: If provided, clear cache only for this worktree.
                  If None, clear all caches.
        include_disk: If True, also delete disk cache files.
                      Use after sync to ensure fresh data from git.
    """
    global _active_cache, _closed_cache
    if worktree is None:
        _active_cache = {}
        _closed_cache = {}
    else:
        _active_cache.pop(_get_active_cache_key(worktree), None)
        _closed_cache.pop(_get_closed_cache_key(worktree), None)

        if include_disk:
            _clear_disk_cache(worktree)


def _get_disk_cache_path(worktree: Path, cache_file: str) -> Path | None:
    """Get the path to a disk cache file.

    Returns None if we can't determine the repo root (e.g., in tests).
    """
    # Find repo root from worktree path
    # Worktree is at .git/microbeads-worktree, so repo root is 2 levels up
    # But we should use the git common dir approach
    git_dir = worktree.parent  # .git directory
    if git_dir.name == "microbeads-worktree":
        git_dir = git_dir.parent  # Go up one more level

    # Use repo.get_cache_dir if we can find the repo root
    repo_root = git_dir.parent if git_dir.name == ".git" else None
    if repo_root and repo_root.exists():
        cache_dir = repo.get_cache_dir(repo_root)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / cache_file

    return None


def _get_issues_max_mtime(issues_dir: Path) -> float:
    """Get the maximum modification time of all issue files in a directory."""
    if not issues_dir.exists():
        return 0.0

    max_mtime = 0.0
    for path in issues_dir.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
            if mtime > max_mtime:
                max_mtime = mtime
        except OSError:
            continue

    return max_mtime


def _load_disk_cache(cache_path: Path, issues_dir: Path) -> dict[str, dict[str, Any]] | None:
    """Load issues from disk cache if valid.

    Returns None if cache is invalid or doesn't exist.
    Cache is invalidated if any issue file is newer than the cache.
    """
    if not cache_path.exists():
        return None

    try:
        cache_mtime = cache_path.stat().st_mtime
        issues_max_mtime = _get_issues_max_mtime(issues_dir)

        # Cache is invalid if any issue file is newer
        if issues_max_mtime > cache_mtime:
            return None

        # Also check if directory has different file count than cache
        # (handles deletions)
        data = orjson.loads(cache_path.read_bytes())
        cached_count = data.get("_count", 0)
        actual_count = sum(1 for _ in issues_dir.glob("*.json")) if issues_dir.exists() else 0

        if cached_count != actual_count:
            return None

        # Remove metadata and return issues
        data.pop("_count", None)
        return data

    except (OSError, orjson.JSONDecodeError):
        return None


def _save_disk_cache(cache_path: Path, issues: dict[str, dict[str, Any]]) -> None:
    """Save issues to disk cache."""
    try:
        # Add metadata for validation
        data = dict(issues)
        data["_count"] = len(issues)

        cache_path.write_bytes(
            orjson.dumps(data, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS)
        )
    except OSError:
        pass  # Silently ignore cache write failures


def _clear_disk_cache(worktree: Path) -> None:
    """Delete disk cache files for a worktree.

    Used after sync to ensure fresh data is loaded from git.
    """
    for cache_file in [_ACTIVE_CACHE_FILE, _CLOSED_CACHE_FILE]:
        cache_path = _get_disk_cache_path(worktree, cache_file)
        if cache_path and cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass  # Silently ignore deletion failures


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
    design: str = "",
    notes: str = "",
    acceptance_criteria: str = "",
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
        "acceptance_criteria": acceptance_criteria,
        "closed_at": None,
        "closed_reason": None,
        "created_at": now,
        "dependencies": [],
        "description": description,
        "design": design,
        "id": issue_id,
        "labels": labels,
        "notes": notes,
        "priority": priority,
        "status": Status.OPEN.value,
        "title": title,
        "type": issue_type.value,
        "updated_at": now,
    }


def issue_to_json(issue: dict[str, Any]) -> str:
    """Serialize issue to JSON with sorted keys."""
    return orjson.dumps(issue, option=orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS).decode() + "\n"


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
        content = path.read_bytes()
        if not content.strip():
            raise CorruptedFileError(path, ValueError("File is empty"))
        return orjson.loads(content)
    except orjson.JSONDecodeError as e:
        raise CorruptedFileError(path, e) from e


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
    """Get an issue by ID, checking active first then closed.

    Raises:
        CorruptedFileError: If the exact match file exists but is corrupted

    Returns:
        Issue data, or None if not found. Skips corrupted files during partial matching.
    """
    active_dir = repo.get_active_issues_path(worktree)
    closed_dir = repo.get_closed_issues_path(worktree)

    # Check active first (most common case)
    path = active_dir / f"{issue_id}.json"
    if path.exists():
        # Exact match - let CorruptedFileError propagate
        return load_issue(path)

    # Check closed
    path = closed_dir / f"{issue_id}.json"
    if path.exists():
        return load_issue(path)

    # Try partial match in active - skip corrupted files
    if active_dir.exists():
        for p in active_dir.glob("*.json"):
            if p.stem.startswith(issue_id) or issue_id in p.stem:
                try:
                    return load_issue(p)
                except CorruptedFileError:
                    continue

    # Try partial match in closed - skip corrupted files
    if closed_dir.exists():
        for p in closed_dir.glob("*.json"):
            if p.stem.startswith(issue_id) or issue_id in p.stem:
                try:
                    return load_issue(p)
                except CorruptedFileError:
                    continue

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


def load_active_issues(worktree: Path, skip_corrupted: bool = True) -> dict[str, dict[str, Any]]:
    """Load active issues (open, in_progress, blocked) into a dict keyed by ID.

    Args:
        worktree: Path to the worktree
        skip_corrupted: If True, skip corrupted files silently.
                       If False, raise CorruptedFileError on first corruption.

    Returns:
        Dictionary mapping issue IDs to issue data

    Raises:
        CorruptedFileError: If skip_corrupted is False and a file is corrupted
    """
    issues_dir = repo.get_active_issues_path(worktree)

    if not issues_dir.exists():
        return {}

    # Check in-memory cache first
    cache_key = _get_active_cache_key(worktree)
    if cache_key in _active_cache:
        return _active_cache[cache_key]

    # Check disk cache
    disk_cache_path = _get_disk_cache_path(worktree, _ACTIVE_CACHE_FILE)
    if disk_cache_path:
        cached = _load_disk_cache(disk_cache_path, issues_dir)
        if cached is not None:
            _active_cache[cache_key] = cached
            return cached

    # Load from individual files
    issues = {}
    for path in issues_dir.glob("*.json"):
        try:
            issues[path.stem] = load_issue(path)
        except CorruptedFileError:
            if not skip_corrupted:
                raise
            # Silently skip corrupted files when skip_corrupted is True

    # Save to both caches
    _active_cache[cache_key] = issues
    if disk_cache_path:
        _save_disk_cache(disk_cache_path, issues)

    return issues


def load_closed_issues(worktree: Path, skip_corrupted: bool = True) -> dict[str, dict[str, Any]]:
    """Load closed issues into a dict keyed by ID.

    Args:
        worktree: Path to the worktree
        skip_corrupted: If True, skip corrupted files silently.
                       If False, raise CorruptedFileError on first corruption.

    Returns:
        Dictionary mapping issue IDs to issue data

    Raises:
        CorruptedFileError: If skip_corrupted is False and a file is corrupted
    """
    issues_dir = repo.get_closed_issues_path(worktree)

    if not issues_dir.exists():
        return {}

    # Check in-memory cache first
    cache_key = _get_closed_cache_key(worktree)
    if cache_key in _closed_cache:
        return _closed_cache[cache_key]

    # Check disk cache
    disk_cache_path = _get_disk_cache_path(worktree, _CLOSED_CACHE_FILE)
    if disk_cache_path:
        cached = _load_disk_cache(disk_cache_path, issues_dir)
        if cached is not None:
            _closed_cache[cache_key] = cached
            return cached

    # Load from individual files
    issues = {}
    for path in issues_dir.glob("*.json"):
        try:
            issues[path.stem] = load_issue(path)
        except CorruptedFileError:
            if not skip_corrupted:
                raise
            # Silently skip corrupted files when skip_corrupted is True

    # Save to both caches
    _closed_cache[cache_key] = issues
    if disk_cache_path:
        _save_disk_cache(disk_cache_path, issues)

    return issues


def load_all_issues(worktree: Path, skip_corrupted: bool = True) -> dict[str, dict[str, Any]]:
    """Load all issues (active + closed) into a dict keyed by ID.

    Args:
        worktree: Path to the worktree
        skip_corrupted: If True, skip corrupted files silently.
                       If False, raise CorruptedFileError on first corruption.

    Returns:
        Dictionary mapping issue IDs to issue data

    Raises:
        CorruptedFileError: If skip_corrupted is False and a file is corrupted
    """
    active = load_active_issues(worktree, skip_corrupted=skip_corrupted)
    closed = load_closed_issues(worktree, skip_corrupted=skip_corrupted)
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


def _add_history_entry(
    issue: dict[str, Any],
    field: str,
    old_value: Any,
    new_value: Any,
    timestamp: str | None = None,
) -> None:
    """Add a history entry to an issue."""
    if "history" not in issue:
        issue["history"] = []

    entry = {
        "field": field,
        "old": old_value,
        "new": new_value,
        "at": timestamp or now_iso(),
    }
    issue["history"].append(entry)


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
    design: str | None = None,
    notes: str | None = None,
    acceptance_criteria: str | None = None,
    claimed_by: str | None = None,
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
        claimed_by: Agent/session identifier when claiming (optional)

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

    timestamp = now_iso()

    # Validate and apply updates with history tracking
    if status is not None and issue.get("status") != status.value:
        _add_history_entry(issue, "status", issue.get("status"), status.value, timestamp)
        issue["status"] = status.value

        # Track ownership when claiming a task
        if status == Status.IN_PROGRESS and claimed_by:
            old_claimed = issue.get("claimed_by")
            if old_claimed != claimed_by:
                _add_history_entry(issue, "claimed_by", old_claimed, claimed_by, timestamp)
            issue["claimed_by"] = claimed_by
            issue["claimed_at"] = timestamp
        # Clear ownership when moving away from in_progress
        elif status != Status.IN_PROGRESS and issue.get("claimed_by"):
            _add_history_entry(issue, "claimed_by", issue.get("claimed_by"), None, timestamp)
            issue.pop("claimed_by", None)
            issue.pop("claimed_at", None)
    if priority is not None:
        priority = validate_priority(priority)
        if issue.get("priority") != priority:
            _add_history_entry(issue, "priority", issue.get("priority"), priority, timestamp)
            issue["priority"] = priority
    if title is not None:
        title = validate_title(title)
        if issue.get("title") != title:
            _add_history_entry(issue, "title", issue.get("title"), title, timestamp)
            issue["title"] = title
    if description is not None:
        description = validate_description(description)
        if issue.get("description") != description:
            _add_history_entry(issue, "description", "(changed)", "(changed)", timestamp)
            issue["description"] = description
    if labels is not None:
        labels = validate_labels(labels)
        old_labels = issue.get("labels", [])
        if sorted(old_labels) != sorted(labels):
            _add_history_entry(issue, "labels", old_labels, labels, timestamp)
        issue["labels"] = labels
    if add_labels:
        add_labels = validate_labels(add_labels)
        current = set(issue.get("labels", []))
        new_labels = sorted(current | set(add_labels))
        if new_labels != sorted(current):
            _add_history_entry(issue, "labels", sorted(current), new_labels, timestamp)
        issue["labels"] = new_labels
    if remove_labels:
        remove_labels = validate_labels(remove_labels)
        current = set(issue.get("labels", []))
        new_labels = sorted(current - set(remove_labels))
        if new_labels != sorted(current):
            _add_history_entry(issue, "labels", sorted(current), new_labels, timestamp)
        issue["labels"] = new_labels
    if design is not None and issue.get("design") != design:
        _add_history_entry(issue, "design", "(changed)", "(changed)", timestamp)
        issue["design"] = design
    if notes is not None and issue.get("notes") != notes:
        _add_history_entry(issue, "notes", "(changed)", "(changed)", timestamp)
        issue["notes"] = notes
    if acceptance_criteria is not None and issue.get("acceptance_criteria") != acceptance_criteria:
        _add_history_entry(issue, "acceptance_criteria", "(changed)", "(changed)", timestamp)
        issue["acceptance_criteria"] = acceptance_criteria

    issue["updated_at"] = timestamp
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

    timestamp = now_iso()
    _add_history_entry(issue, "status", issue.get("status"), Status.CLOSED.value, timestamp)

    issue["status"] = Status.CLOSED.value
    issue["closed_at"] = timestamp
    issue["closed_reason"] = reason
    issue["updated_at"] = timestamp

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

    timestamp = now_iso()
    _add_history_entry(issue, "status", issue.get("status"), Status.OPEN.value, timestamp)

    issue["status"] = Status.OPEN.value
    issue["closed_at"] = None
    issue["closed_reason"] = None
    issue["updated_at"] = timestamp

    # save_issue will save to active directory since status is open
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
