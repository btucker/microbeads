"""Tests for issue management functionality."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from microbeads.issues import (
    IssueType,
    Status,
    add_dependency,
    close_issue,
    create_issue,
    generate_id,
    get_blocked_issues,
    get_issue,
    get_open_blockers,
    get_ready_issues,
    issue_to_json,
    list_issues,
    load_active_issues,
    load_all_issues,
    load_issue,
    now_iso,
    remove_dependency,
    reopen_issue,
    resolve_issue_id,
    save_issue,
    update_issue,
)


class TestGenerateId:
    """Tests for ID generation."""

    def test_generate_id_default_prefix(self):
        """Test ID generation with default prefix."""
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        issue_id = generate_id("Test Issue", timestamp=ts)
        assert issue_id.startswith("bd-")
        assert len(issue_id) == 11  # "bd-" + 8 hex chars

    def test_generate_id_custom_prefix(self):
        """Test ID generation with custom prefix."""
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        issue_id = generate_id("Test Issue", prefix="mb", timestamp=ts)
        assert issue_id.startswith("mb-")

    def test_generate_id_deterministic(self):
        """Test that same input produces same ID."""
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        id1 = generate_id("Test Issue", timestamp=ts)
        id2 = generate_id("Test Issue", timestamp=ts)
        assert id1 == id2

    def test_generate_id_different_titles(self):
        """Test that different titles produce different IDs."""
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        id1 = generate_id("Issue A", timestamp=ts)
        id2 = generate_id("Issue B", timestamp=ts)
        assert id1 != id2


class TestNowIso:
    """Tests for timestamp generation."""

    def test_now_iso_format(self):
        """Test ISO timestamp format."""
        timestamp = now_iso()
        assert timestamp.endswith("Z")
        # Should be parseable
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


class TestCreateIssue:
    """Tests for issue creation."""

    def test_create_issue_defaults(self, mock_worktree: Path):
        """Test issue creation with default values."""
        issue = create_issue("Test Issue", mock_worktree)

        assert issue["title"] == "Test Issue"
        assert issue["status"] == "open"
        assert issue["type"] == "task"
        assert issue["priority"] == 2
        assert issue["description"] == ""
        assert issue["labels"] == []
        assert issue["dependencies"] == []
        assert issue["closed_at"] is None
        assert issue["closed_reason"] is None
        assert "id" in issue
        assert "created_at" in issue
        assert "updated_at" in issue

    def test_create_issue_with_options(self, mock_worktree: Path):
        """Test issue creation with custom values."""
        issue = create_issue(
            "Bug Report",
            mock_worktree,
            description="Something is broken",
            issue_type=IssueType.BUG,
            priority=1,
            labels=["urgent", "backend"],
        )

        assert issue["title"] == "Bug Report"
        assert issue["type"] == "bug"
        assert issue["priority"] == 1
        assert issue["description"] == "Something is broken"
        assert issue["labels"] == ["urgent", "backend"]


class TestIssueToJson:
    """Tests for JSON serialization."""

    def test_issue_to_json_sorted_keys(self, mock_worktree: Path):
        """Test that JSON output has sorted keys."""
        issue = create_issue("Test", mock_worktree)
        json_str = issue_to_json(issue)

        # Parse and check key order
        parsed = json.loads(json_str)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_issue_to_json_trailing_newline(self, mock_worktree: Path):
        """Test that JSON output has trailing newline."""
        issue = create_issue("Test", mock_worktree)
        json_str = issue_to_json(issue)
        assert json_str.endswith("\n")


class TestSaveLoadIssue:
    """Tests for issue persistence."""

    def test_save_and_load_issue(self, mock_worktree: Path):
        """Test saving and loading an issue."""
        issue = create_issue("Test Issue", mock_worktree)
        path = save_issue(mock_worktree, issue)

        assert path.exists()
        loaded = load_issue(path)
        assert loaded == issue

    def test_save_issue_creates_directory(self, tmp_path: Path):
        """Test that save_issue creates the issues directory if needed."""
        worktree = tmp_path / "new-worktree"
        worktree.mkdir()
        beads_dir = worktree / ".microbeads"
        beads_dir.mkdir()
        (beads_dir / "metadata.json").write_text('{"id_prefix": "test"}')

        issue = {
            "id": "test-1234",
            "title": "Test",
            "status": "open",
        }
        path = save_issue(worktree, issue)
        assert path.exists()


class TestGetIssue:
    """Tests for issue retrieval."""

    def test_get_issue_exact_id(self, mock_worktree: Path):
        """Test getting an issue by exact ID."""
        issue = create_issue("Test Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        retrieved = get_issue(mock_worktree, issue["id"])
        assert retrieved == issue

    def test_get_issue_partial_id(self, mock_worktree: Path):
        """Test getting an issue by partial ID."""
        issue = create_issue("Test Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Try partial match
        partial = issue["id"][:4]
        retrieved = get_issue(mock_worktree, partial)
        assert retrieved is not None
        assert retrieved["id"] == issue["id"]

    def test_get_issue_not_found(self, mock_worktree: Path):
        """Test getting a non-existent issue."""
        result = get_issue(mock_worktree, "nonexistent-id")
        assert result is None


class TestResolveIssueId:
    """Tests for issue ID resolution."""

    def test_resolve_exact_id(self, mock_worktree: Path):
        """Test resolving an exact ID."""
        issue = create_issue("Test Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        resolved = resolve_issue_id(mock_worktree, issue["id"])
        assert resolved == issue["id"]

    def test_resolve_partial_id_unique(self, mock_worktree: Path):
        """Test resolving a unique partial ID."""
        issue = create_issue("Test Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        partial = issue["id"][:4]
        resolved = resolve_issue_id(mock_worktree, partial)
        assert resolved == issue["id"]

    def test_resolve_id_not_found(self, mock_worktree: Path):
        """Test resolving a non-existent ID."""
        resolved = resolve_issue_id(mock_worktree, "nonexistent")
        assert resolved is None


class TestLoadAllIssues:
    """Tests for loading all issues."""

    def test_load_all_issues_empty(self, mock_worktree: Path):
        """Test loading from empty directory."""
        issues = load_all_issues(mock_worktree)
        assert issues == {}

    def test_load_all_issues_multiple(self, mock_worktree: Path):
        """Test loading multiple issues."""
        issue1 = create_issue("Issue 1", mock_worktree)
        issue2 = create_issue("Issue 2", mock_worktree)
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        issues = load_all_issues(mock_worktree)
        assert len(issues) == 2
        assert issue1["id"] in issues
        assert issue2["id"] in issues


class TestListIssues:
    """Tests for issue listing with filters."""

    def test_list_issues_no_filter(self, mock_worktree: Path):
        """Test listing all issues."""
        issue1 = create_issue("Issue 1", mock_worktree, priority=1)
        issue2 = create_issue("Issue 2", mock_worktree, priority=2)
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        issues = list_issues(mock_worktree)
        assert len(issues) == 2
        # Should be sorted by priority
        assert issues[0]["priority"] == 1
        assert issues[1]["priority"] == 2

    def test_list_issues_filter_status(self, mock_worktree: Path):
        """Test filtering by status."""
        issue1 = create_issue("Open Issue", mock_worktree)
        issue2 = create_issue("Closed Issue", mock_worktree)
        issue2["status"] = Status.CLOSED.value
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        open_issues = list_issues(mock_worktree, status=Status.OPEN)
        assert len(open_issues) == 1
        assert open_issues[0]["title"] == "Open Issue"

    def test_list_issues_filter_type(self, mock_worktree: Path):
        """Test filtering by type."""
        issue1 = create_issue("Bug", mock_worktree, issue_type=IssueType.BUG)
        issue2 = create_issue("Feature", mock_worktree, issue_type=IssueType.FEATURE)
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        bugs = list_issues(mock_worktree, issue_type=IssueType.BUG)
        assert len(bugs) == 1
        assert bugs[0]["type"] == "bug"

    def test_list_issues_filter_label(self, mock_worktree: Path):
        """Test filtering by label."""
        issue1 = create_issue("With Label", mock_worktree, labels=["urgent"])
        issue2 = create_issue("Without Label", mock_worktree)
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        labeled = list_issues(mock_worktree, label="urgent")
        assert len(labeled) == 1
        assert "urgent" in labeled[0]["labels"]


class TestUpdateIssue:
    """Tests for issue updates."""

    def test_update_status(self, mock_worktree: Path):
        """Test updating issue status."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], status=Status.IN_PROGRESS)
        assert updated["status"] == "in_progress"

    def test_update_priority(self, mock_worktree: Path):
        """Test updating issue priority."""
        issue = create_issue("Test", mock_worktree, priority=2)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], priority=1)
        assert updated["priority"] == 1

    def test_update_add_labels(self, mock_worktree: Path):
        """Test adding labels."""
        issue = create_issue("Test", mock_worktree, labels=["existing"])
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], add_labels=["new"])
        assert "existing" in updated["labels"]
        assert "new" in updated["labels"]

    def test_update_remove_labels(self, mock_worktree: Path):
        """Test removing labels."""
        issue = create_issue("Test", mock_worktree, labels=["keep", "remove"])
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], remove_labels=["remove"])
        assert "keep" in updated["labels"]
        assert "remove" not in updated["labels"]

    def test_update_not_found(self, mock_worktree: Path):
        """Test updating non-existent issue."""
        with pytest.raises(ValueError, match="Issue not found"):
            update_issue(mock_worktree, "nonexistent", status=Status.CLOSED)


class TestCloseReopenIssue:
    """Tests for closing and reopening issues."""

    def test_close_issue(self, mock_worktree: Path):
        """Test closing an issue."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        closed = close_issue(mock_worktree, issue["id"], reason="Done")
        assert closed["status"] == "closed"
        assert closed["closed_reason"] == "Done"
        assert closed["closed_at"] is not None

    def test_reopen_issue(self, mock_worktree: Path):
        """Test reopening a closed issue."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)
        close_issue(mock_worktree, issue["id"])

        reopened = reopen_issue(mock_worktree, issue["id"])
        assert reopened["status"] == "open"
        assert reopened["closed_at"] is None
        assert reopened["closed_reason"] is None


class TestDependencies:
    """Tests for issue dependencies."""

    def test_add_dependency(self, mock_worktree: Path):
        """Test adding a dependency."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)

        updated = add_dependency(mock_worktree, child["id"], parent["id"])
        assert parent["id"] in updated["dependencies"]

    def test_remove_dependency(self, mock_worktree: Path):
        """Test removing a dependency."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)

        add_dependency(mock_worktree, child["id"], parent["id"])
        updated = remove_dependency(mock_worktree, child["id"], parent["id"])
        assert parent["id"] not in updated["dependencies"]

    def test_get_open_blockers(self, mock_worktree: Path):
        """Test getting open blockers."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        child["dependencies"] = [parent["id"]]
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)

        cache = load_active_issues(mock_worktree)
        blockers = get_open_blockers(cache[child["id"]], cache, mock_worktree)
        assert len(blockers) == 1
        assert blockers[0]["id"] == parent["id"]

    def test_get_open_blockers_closed_parent(self, mock_worktree: Path):
        """Test that closed issues don't block."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        child["dependencies"] = [parent["id"]]
        # Save parent first, then close it (which moves it to closed dir)
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)
        close_issue(mock_worktree, parent["id"])

        cache = load_active_issues(mock_worktree)
        blockers = get_open_blockers(cache[child["id"]], cache, mock_worktree)
        assert len(blockers) == 0


class TestReadyAndBlockedIssues:
    """Tests for ready and blocked issue queries."""

    def test_get_ready_issues(self, mock_worktree: Path):
        """Test getting ready issues."""
        issue = create_issue("Ready Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        ready = get_ready_issues(mock_worktree)
        assert len(ready) == 1
        assert ready[0]["id"] == issue["id"]

    def test_get_ready_issues_excludes_blocked(self, mock_worktree: Path):
        """Test that blocked issues are excluded from ready."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)
        add_dependency(mock_worktree, child["id"], parent["id"])

        ready = get_ready_issues(mock_worktree)
        ready_ids = [i["id"] for i in ready]
        assert parent["id"] in ready_ids
        assert child["id"] not in ready_ids

    def test_get_blocked_issues(self, mock_worktree: Path):
        """Test getting blocked issues."""
        parent = create_issue("Parent", mock_worktree)
        child = create_issue("Child", mock_worktree)
        save_issue(mock_worktree, parent)
        save_issue(mock_worktree, child)
        add_dependency(mock_worktree, child["id"], parent["id"])

        blocked = get_blocked_issues(mock_worktree)
        assert len(blocked) == 1
        assert blocked[0]["id"] == child["id"]
