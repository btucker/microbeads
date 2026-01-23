"""Tests for issue management functionality."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from microbeads.issues import (
    _ACTIVE_CACHE_FILE,
    CorruptedFileError,
    IssueType,
    Status,
    ValidationError,
    _add_history_entry,
    _get_disk_cache_path,
    add_dependency,
    clear_cache,
    close_issue,
    create_issue,
    generate_id,
    get_blocked_issues,
    get_issue,
    get_open_blockers,
    get_ready_issues,
    hours_since,
    issue_to_json,
    list_issues,
    load_active_issues,
    load_all_issues,
    load_issue,
    now_iso,
    remove_dependency,
    reopen_issue,
    resolve_issue_id,
    run_doctor,
    save_issue,
    update_issue,
    validate_description,
    validate_labels,
    validate_priority,
    validate_title,
)


class TestHoursSince:
    """Tests for the hours_since helper function."""

    def test_hours_since_valid_timestamp(self):
        """Test calculating hours from a valid timestamp."""
        result = hours_since("2020-01-01T00:00:00Z")
        assert result is not None
        assert result > 0

    def test_hours_since_none_timestamp(self):
        """Test that None timestamp returns None."""
        result = hours_since(None)
        assert result is None

    def test_hours_since_invalid_timestamp(self):
        """Test that invalid timestamp returns None."""
        result = hours_since("not-a-timestamp")
        assert result is None

    def test_hours_since_empty_string(self):
        """Test that empty string returns None."""
        result = hours_since("")
        assert result is None

    def test_hours_since_recent_timestamp(self):
        """Test that recent timestamp returns small value."""
        recent = now_iso()
        result = hours_since(recent)
        assert result is not None
        assert result < 1  # Less than 1 hour ago


class TestGenerateId:
    """Tests for ID generation."""

    def test_generate_id_default_prefix(self):
        """Test ID generation with default prefix."""
        ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        issue_id = generate_id("Test Issue", timestamp=ts)
        assert issue_id.startswith("mb-")
        assert len(issue_id) == 11  # "mb-" + 8 hex chars

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


class TestOwnershipTracking:
    """Tests for issue ownership tracking."""

    def test_claim_issue_sets_ownership(self, mock_worktree: Path):
        """Test that claiming an issue sets claimed_by and claimed_at."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(
            mock_worktree, issue["id"], status=Status.IN_PROGRESS, claimed_by="my-branch"
        )
        assert updated["claimed_by"] == "my-branch"
        assert "claimed_at" in updated

    def test_claim_without_owner_no_tracking(self, mock_worktree: Path):
        """Test that claiming without claimed_by doesn't set ownership."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], status=Status.IN_PROGRESS)
        assert "claimed_by" not in updated
        assert "claimed_at" not in updated

    def test_status_change_clears_ownership(self, mock_worktree: Path):
        """Test that changing status away from in_progress clears ownership."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        # Claim the issue
        updated = update_issue(
            mock_worktree, issue["id"], status=Status.IN_PROGRESS, claimed_by="my-branch"
        )
        assert updated["claimed_by"] == "my-branch"

        # Move back to open - should clear ownership
        updated = update_issue(mock_worktree, issue["id"], status=Status.OPEN)
        assert "claimed_by" not in updated
        assert "claimed_at" not in updated

    def test_ownership_tracked_in_history(self, mock_worktree: Path):
        """Test that ownership changes are recorded in history."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(
            mock_worktree, issue["id"], status=Status.IN_PROGRESS, claimed_by="branch-1"
        )

        history = updated.get("history", [])
        claim_entries = [h for h in history if h.get("field") == "claimed_by"]
        assert len(claim_entries) == 1
        assert claim_entries[0]["new"] == "branch-1"


class TestGetReadyIssuesWithOwnership:
    """Tests for get_ready_issues with ownership filtering."""

    def test_ready_issues_excludes_others_in_progress(self, mock_worktree: Path):
        """Test that in_progress issues owned by others are excluded."""
        # Create an open issue
        open_issue = create_issue("Open issue", mock_worktree)
        save_issue(mock_worktree, open_issue)

        # Create an in_progress issue owned by another branch
        claimed_issue = create_issue("Claimed issue", mock_worktree)
        save_issue(mock_worktree, claimed_issue)
        update_issue(
            mock_worktree,
            claimed_issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="other-branch",
        )

        # Get ready issues for "my-branch"
        ready = get_ready_issues(mock_worktree, include_owned_by="my-branch")

        ids = [i["id"] for i in ready]
        assert open_issue["id"] in ids
        assert claimed_issue["id"] not in ids

    def test_ready_issues_includes_own_in_progress(self, mock_worktree: Path):
        """Test that in_progress issues owned by current branch are included."""
        # Create an in_progress issue owned by my branch
        my_issue = create_issue("My issue", mock_worktree)
        save_issue(mock_worktree, my_issue)
        update_issue(
            mock_worktree,
            my_issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="my-branch",
        )

        # Get ready issues for "my-branch"
        ready = get_ready_issues(mock_worktree, include_owned_by="my-branch")

        ids = [i["id"] for i in ready]
        assert my_issue["id"] in ids

    def test_ready_issues_without_owner_excludes_all_in_progress(self, mock_worktree: Path):
        """Test that without owner filter, all in_progress issues are excluded."""
        # Create an open issue
        open_issue = create_issue("Open issue", mock_worktree)
        save_issue(mock_worktree, open_issue)

        # Create an in_progress issue
        claimed_issue = create_issue("Claimed issue", mock_worktree)
        save_issue(mock_worktree, claimed_issue)
        update_issue(
            mock_worktree,
            claimed_issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="some-branch",
        )

        # Get ready issues without owner filter
        ready = get_ready_issues(mock_worktree)

        ids = [i["id"] for i in ready]
        assert open_issue["id"] in ids
        assert claimed_issue["id"] not in ids


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


class TestValidateTitle:
    """Tests for title validation."""

    def test_valid_title(self):
        """Test that valid titles are accepted."""
        assert validate_title("Fix the bug") == "Fix the bug"

    def test_title_strips_whitespace(self):
        """Test that titles are stripped of whitespace."""
        assert validate_title("  padded title  ") == "padded title"

    def test_empty_title_raises(self):
        """Test that empty titles raise ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_title("")

    def test_whitespace_only_title_raises(self):
        """Test that whitespace-only titles raise ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_title("   ")

    def test_title_too_long_raises(self):
        """Test that titles over 500 chars raise ValidationError."""
        with pytest.raises(ValidationError, match="too long"):
            validate_title("x" * 501)

    def test_title_non_string_raises(self):
        """Test that non-string titles raise ValidationError."""
        with pytest.raises(ValidationError, match="must be a string"):
            validate_title(123)  # type: ignore


class TestValidatePriority:
    """Tests for priority validation."""

    def test_valid_priorities(self):
        """Test that valid priorities 0-4 are accepted."""
        for p in range(5):
            assert validate_priority(p) == p

    def test_priority_too_low_raises(self):
        """Test that negative priorities raise ValidationError."""
        with pytest.raises(ValidationError, match="must be between"):
            validate_priority(-1)

    def test_priority_too_high_raises(self):
        """Test that priorities above 4 raise ValidationError."""
        with pytest.raises(ValidationError, match="must be between"):
            validate_priority(5)

    def test_priority_non_int_raises(self):
        """Test that non-integer priorities raise ValidationError."""
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_priority("high")  # type: ignore

    def test_priority_bool_raises(self):
        """Test that bool (subclass of int) raises ValidationError."""
        with pytest.raises(ValidationError, match="must be an integer"):
            validate_priority(True)  # type: ignore


class TestValidateLabels:
    """Tests for labels validation."""

    def test_valid_labels(self):
        """Test that valid labels are accepted."""
        assert validate_labels(["frontend", "urgent"]) == ["frontend", "urgent"]

    def test_labels_none_returns_empty(self):
        """Test that None returns empty list."""
        assert validate_labels(None) == []

    def test_labels_strips_whitespace(self):
        """Test that labels are stripped of whitespace."""
        assert validate_labels(["  padded  "]) == ["padded"]

    def test_empty_label_raises(self):
        """Test that empty labels raise ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_labels(["valid", ""])

    def test_label_too_long_raises(self):
        """Test that labels over 100 chars raise ValidationError."""
        with pytest.raises(ValidationError, match="too long"):
            validate_labels(["x" * 101])

    def test_labels_non_list_raises(self):
        """Test that non-list labels raise ValidationError."""
        with pytest.raises(ValidationError, match="must be a list"):
            validate_labels("not-a-list")  # type: ignore

    def test_label_non_string_raises(self):
        """Test that non-string labels raise ValidationError."""
        with pytest.raises(ValidationError, match="must be a string"):
            validate_labels(["valid", 123])  # type: ignore


class TestValidateDescription:
    """Tests for description validation."""

    def test_valid_description(self):
        """Test that valid descriptions are accepted."""
        assert validate_description("Some description") == "Some description"

    def test_description_strips_whitespace(self):
        """Test that descriptions are stripped of whitespace."""
        assert validate_description("  padded  ") == "padded"

    def test_description_non_string_raises(self):
        """Test that non-string descriptions raise ValidationError."""
        with pytest.raises(ValidationError, match="must be a string"):
            validate_description(123)  # type: ignore


class TestValidationInCreateIssue:
    """Tests for validation in create_issue."""

    def test_create_with_empty_title_raises(self, mock_worktree: Path):
        """Test that creating with empty title raises ValidationError."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            create_issue("", mock_worktree)

    def test_create_with_invalid_priority_raises(self, mock_worktree: Path):
        """Test that creating with invalid priority raises ValidationError."""
        with pytest.raises(ValidationError, match="must be between"):
            create_issue("Valid Title", mock_worktree, priority=10)

    def test_create_with_invalid_labels_raises(self, mock_worktree: Path):
        """Test that creating with invalid labels raises ValidationError."""
        with pytest.raises(ValidationError, match="must be a string"):
            create_issue("Valid Title", mock_worktree, labels=[123])  # type: ignore


class TestValidationInUpdateIssue:
    """Tests for validation in update_issue."""

    def test_update_with_empty_title_raises(self, mock_worktree: Path):
        """Test that updating with empty title raises ValidationError."""
        issue = create_issue("Original", mock_worktree)
        save_issue(mock_worktree, issue)

        with pytest.raises(ValidationError, match="cannot be empty"):
            update_issue(mock_worktree, issue["id"], title="")

    def test_update_with_invalid_priority_raises(self, mock_worktree: Path):
        """Test that updating with invalid priority raises ValidationError."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        with pytest.raises(ValidationError, match="must be between"):
            update_issue(mock_worktree, issue["id"], priority=99)


class TestSelfDependencyValidation:
    """Tests for self-dependency prevention."""

    def test_self_dependency_raises(self, mock_worktree: Path):
        """Test that adding self as dependency raises ValidationError."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        with pytest.raises(ValidationError, match="cannot depend on itself"):
            add_dependency(mock_worktree, issue["id"], issue["id"])

    def test_self_dependency_partial_id_raises(self, mock_worktree: Path):
        """Test that self-dependency with partial ID raises ValidationError."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        # Use partial ID for both child and parent that resolve to the same issue
        partial = issue["id"][:4]
        with pytest.raises(ValidationError, match="cannot depend on itself"):
            add_dependency(mock_worktree, partial, issue["id"])


class TestCircularDependencyPrevention:
    """Tests for circular dependency prevention."""

    def test_direct_circular_dependency_raises(self, mock_worktree: Path):
        """Test that A->B, B->A raises ValidationError."""
        issue_a = create_issue("Issue A", mock_worktree)
        issue_b = create_issue("Issue B", mock_worktree)
        save_issue(mock_worktree, issue_a)
        save_issue(mock_worktree, issue_b)

        # A depends on B
        add_dependency(mock_worktree, issue_a["id"], issue_b["id"])

        # B depends on A should fail
        with pytest.raises(ValidationError, match="circular dependency"):
            add_dependency(mock_worktree, issue_b["id"], issue_a["id"])

    def test_transitive_circular_dependency_raises(self, mock_worktree: Path):
        """Test that A->B->C, C->A raises ValidationError."""
        issue_a = create_issue("Issue A", mock_worktree)
        issue_b = create_issue("Issue B", mock_worktree)
        issue_c = create_issue("Issue C", mock_worktree)
        save_issue(mock_worktree, issue_a)
        save_issue(mock_worktree, issue_b)
        save_issue(mock_worktree, issue_c)

        # A depends on B
        add_dependency(mock_worktree, issue_a["id"], issue_b["id"])
        # B depends on C
        add_dependency(mock_worktree, issue_b["id"], issue_c["id"])

        # C depends on A should fail (would create C->A->B->C)
        with pytest.raises(ValidationError, match="circular dependency"):
            add_dependency(mock_worktree, issue_c["id"], issue_a["id"])

    def test_long_chain_circular_dependency_raises(self, mock_worktree: Path):
        """Test detection with longer dependency chains."""
        issues = []
        for i in range(5):
            issue = create_issue(f"Issue {i}", mock_worktree)
            save_issue(mock_worktree, issue)
            issues.append(issue)

        # Create chain: 0 -> 1 -> 2 -> 3 -> 4
        for i in range(4):
            add_dependency(mock_worktree, issues[i]["id"], issues[i + 1]["id"])

        # 4 -> 0 should fail
        with pytest.raises(ValidationError, match="circular dependency"):
            add_dependency(mock_worktree, issues[4]["id"], issues[0]["id"])

    def test_diamond_dependency_allowed(self, mock_worktree: Path):
        """Test that diamond patterns (non-circular) are allowed."""
        #     A
        #    / \
        #   B   C
        #    \ /
        #     D
        issue_a = create_issue("Issue A", mock_worktree)
        issue_b = create_issue("Issue B", mock_worktree)
        issue_c = create_issue("Issue C", mock_worktree)
        issue_d = create_issue("Issue D", mock_worktree)
        save_issue(mock_worktree, issue_a)
        save_issue(mock_worktree, issue_b)
        save_issue(mock_worktree, issue_c)
        save_issue(mock_worktree, issue_d)

        # D depends on B and C
        add_dependency(mock_worktree, issue_d["id"], issue_b["id"])
        add_dependency(mock_worktree, issue_d["id"], issue_c["id"])

        # B and C depend on A
        add_dependency(mock_worktree, issue_b["id"], issue_a["id"])
        add_dependency(mock_worktree, issue_c["id"], issue_a["id"])

        # Verify D has both dependencies
        d = get_issue(mock_worktree, issue_d["id"])
        assert issue_b["id"] in d["dependencies"]
        assert issue_c["id"] in d["dependencies"]

    def test_existing_dependency_ok(self, mock_worktree: Path):
        """Test that re-adding an existing dependency is OK."""
        issue_a = create_issue("Issue A", mock_worktree)
        issue_b = create_issue("Issue B", mock_worktree)
        save_issue(mock_worktree, issue_a)
        save_issue(mock_worktree, issue_b)

        # A depends on B
        add_dependency(mock_worktree, issue_a["id"], issue_b["id"])

        # Adding the same dependency again should be fine
        add_dependency(mock_worktree, issue_a["id"], issue_b["id"])

        a = get_issue(mock_worktree, issue_a["id"])
        assert issue_b["id"] in a["dependencies"]


class TestJsonCorruptionHandling:
    """Tests for JSON corruption handling."""

    def test_load_issue_corrupted_json(self, mock_worktree: Path):
        """Test that loading corrupted JSON raises CorruptedFileError."""
        from microbeads import repo

        issues_dir = repo.get_issues_path(mock_worktree)
        corrupted_path = issues_dir / "corrupted-1234.json"
        corrupted_path.write_text("{ invalid json")

        with pytest.raises(CorruptedFileError) as exc_info:
            load_issue(corrupted_path)

        assert exc_info.value.path == corrupted_path
        assert "JSONDecodeError" in str(type(exc_info.value.original_error).__name__)

    def test_load_issue_empty_file(self, mock_worktree: Path):
        """Test that loading empty file raises CorruptedFileError."""
        from microbeads import repo

        issues_dir = repo.get_issues_path(mock_worktree)
        empty_path = issues_dir / "empty-1234.json"
        empty_path.write_text("")

        with pytest.raises(CorruptedFileError, match="empty"):
            load_issue(empty_path)

    def test_load_all_issues_skips_corrupted(self, mock_worktree: Path):
        """Test that load_all_issues skips corrupted files by default."""
        from microbeads import repo
        from microbeads.issues import clear_cache

        # Create valid issues
        issue1 = create_issue("Valid Issue 1", mock_worktree)
        issue2 = create_issue("Valid Issue 2", mock_worktree)
        save_issue(mock_worktree, issue1)
        save_issue(mock_worktree, issue2)

        # Clear cache so we re-read from disk
        clear_cache(mock_worktree)

        # Create corrupted file in active directory
        issues_dir = repo.get_active_issues_path(mock_worktree)
        corrupted_path = issues_dir / "corrupted-1234.json"
        corrupted_path.write_text("{ invalid json")

        # Should load only valid issues
        all_issues = load_all_issues(mock_worktree, skip_corrupted=True)
        assert len(all_issues) == 2
        assert issue1["id"] in all_issues
        assert issue2["id"] in all_issues
        assert "corrupted-1234" not in all_issues

    def test_load_all_issues_raises_on_corrupted(self, mock_worktree: Path):
        """Test that load_all_issues raises when skip_corrupted is False."""
        from microbeads import repo
        from microbeads.issues import clear_cache

        # Create valid issue
        issue = create_issue("Valid Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Clear cache so we re-read from disk
        clear_cache(mock_worktree)

        # Create corrupted file in active directory
        issues_dir = repo.get_active_issues_path(mock_worktree)
        corrupted_path = issues_dir / "corrupted-1234.json"
        corrupted_path.write_text("{ invalid json")

        with pytest.raises(CorruptedFileError):
            load_all_issues(mock_worktree, skip_corrupted=False)

    def test_get_issue_with_corrupted_exact_match(self, mock_worktree: Path):
        """Test that get_issue raises for corrupted exact match."""
        from microbeads import repo

        issues_dir = repo.get_active_issues_path(mock_worktree)
        corrupted_path = issues_dir / "test-corrupted.json"
        corrupted_path.write_text("not json at all")

        with pytest.raises(CorruptedFileError):
            get_issue(mock_worktree, "test-corrupted")

    def test_get_issue_skips_corrupted_partial_match(self, mock_worktree: Path):
        """Test that get_issue skips corrupted files during partial matching."""
        from microbeads import repo

        # Create valid issue with prefix "ab"
        issue = create_issue("Valid Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Create corrupted file with different ID but same prefix as we'll search
        issues_dir = repo.get_active_issues_path(mock_worktree)
        # The issue ID starts with "test-" (from mock_worktree prefix)
        # Create a corrupted file that starts with "test-" too
        corrupted_path = issues_dir / "test-aaacorrupt.json"
        corrupted_path.write_text("corrupted")

        # Search for partial ID should skip corrupted and find valid issue
        # (Note: depends on glob order, but at minimum should not raise)
        # Let's search for the valid issue specifically
        partial = issue["id"][:4]
        result = get_issue(mock_worktree, partial)
        assert result is not None
        assert result["id"] == issue["id"]


class TestHistoryTracking:
    """Tests for issue history tracking."""

    def test_add_history_entry_creates_history(self):
        """Test that _add_history_entry creates history list if not present."""
        issue = {"id": "test-1", "title": "Test"}
        _add_history_entry(issue, "status", "open", "closed", "2024-01-01T00:00:00Z")

        assert "history" in issue
        assert len(issue["history"]) == 1
        assert issue["history"][0]["field"] == "status"
        assert issue["history"][0]["old"] == "open"
        assert issue["history"][0]["new"] == "closed"
        assert issue["history"][0]["at"] == "2024-01-01T00:00:00Z"

    def test_add_history_entry_appends(self):
        """Test that _add_history_entry appends to existing history."""
        issue = {"id": "test-1", "title": "Test", "history": [{"field": "old"}]}
        _add_history_entry(issue, "priority", 2, 1)

        assert len(issue["history"]) == 2
        assert issue["history"][1]["field"] == "priority"

    def test_update_tracks_status_change(self, mock_worktree: Path):
        """Test that update_issue tracks status changes in history."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], status=Status.IN_PROGRESS)

        assert "history" in updated
        history = [h for h in updated["history"] if h["field"] == "status"]
        assert len(history) == 1
        assert history[0]["old"] == "open"
        assert history[0]["new"] == "in_progress"

    def test_update_tracks_priority_change(self, mock_worktree: Path):
        """Test that update_issue tracks priority changes in history."""
        issue = create_issue("Test", mock_worktree, priority=2)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], priority=0)

        assert "history" in updated
        history = [h for h in updated["history"] if h["field"] == "priority"]
        assert len(history) == 1
        assert history[0]["old"] == 2
        assert history[0]["new"] == 0

    def test_close_tracks_status_in_history(self, mock_worktree: Path):
        """Test that close_issue records status change in history."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        closed = close_issue(mock_worktree, issue["id"], reason="Done")

        assert "history" in closed
        history = [h for h in closed["history"] if h["field"] == "status"]
        assert len(history) == 1
        assert history[0]["old"] == "open"
        assert history[0]["new"] == "closed"

    def test_reopen_tracks_status_in_history(self, mock_worktree: Path):
        """Test that reopen_issue records status change in history."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)
        close_issue(mock_worktree, issue["id"])

        reopened = reopen_issue(mock_worktree, issue["id"])

        assert "history" in reopened
        history = [h for h in reopened["history"] if h["field"] == "status"]
        # Should have two entries: open->closed and closed->open
        assert len(history) == 2
        assert history[1]["old"] == "closed"
        assert history[1]["new"] == "open"


class TestAdditionalIssueFields:
    """Tests for additional issue fields (design, notes, acceptance_criteria)."""

    def test_create_issue_with_additional_fields(self, mock_worktree: Path):
        """Test creating issue with design, notes, and acceptance_criteria."""
        issue = create_issue(
            "Test Feature",
            mock_worktree,
            design="Use strategy pattern",
            notes="Consider performance",
            acceptance_criteria="All tests pass",
        )

        assert issue["design"] == "Use strategy pattern"
        assert issue["notes"] == "Consider performance"
        assert issue["acceptance_criteria"] == "All tests pass"

    def test_update_design_field(self, mock_worktree: Path):
        """Test updating the design field."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], design="New design approach")

        assert updated["design"] == "New design approach"
        history = [h for h in updated.get("history", []) if h["field"] == "design"]
        assert len(history) == 1

    def test_update_notes_field(self, mock_worktree: Path):
        """Test updating the notes field."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(mock_worktree, issue["id"], notes="Important context")

        assert updated["notes"] == "Important context"

    def test_update_acceptance_criteria_field(self, mock_worktree: Path):
        """Test updating the acceptance_criteria field."""
        issue = create_issue("Test", mock_worktree)
        save_issue(mock_worktree, issue)

        updated = update_issue(
            mock_worktree, issue["id"], acceptance_criteria="Feature complete and tested"
        )

        assert updated["acceptance_criteria"] == "Feature complete and tested"


class TestDoctorCommand:
    """Tests for the doctor (health check) command."""

    def test_doctor_no_problems(self, mock_worktree: Path):
        """Test doctor returns no problems for healthy issues."""
        issue = create_issue("Healthy Issue", mock_worktree)
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree)

        assert result["problems"] == []
        assert result["fixed"] == []
        assert result["total_issues"] == 1

    def test_doctor_detects_orphaned_dependency(self, mock_worktree: Path):
        """Test doctor detects references to non-existent issues."""
        issue = create_issue("Issue with orphan dep", mock_worktree)
        issue["dependencies"] = ["nonexistent-1234"]
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree)

        assert len(result["problems"]) == 1
        assert "orphaned dependency" in result["problems"][0]["problems"][0]

    def test_doctor_fixes_orphaned_dependency(self, mock_worktree: Path):
        """Test doctor can fix orphaned dependencies."""
        issue = create_issue("Issue with orphan dep", mock_worktree)
        issue["dependencies"] = ["nonexistent-1234"]
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree, fix=True)

        assert len(result["fixed"]) == 1
        assert "removed orphaned dependencies" in result["fixed"][0]["fixes"][0]

        # Verify issue was fixed
        fixed_issue = get_issue(mock_worktree, issue["id"])
        assert fixed_issue["dependencies"] == []

    def test_doctor_detects_stale_blocked_status(self, mock_worktree: Path):
        """Test doctor detects issues marked blocked with no blockers."""
        issue = create_issue("Stale blocked", mock_worktree)
        issue["status"] = Status.BLOCKED.value
        issue["dependencies"] = []
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree)

        assert len(result["problems"]) == 1
        assert "marked blocked but has no open blockers" in result["problems"][0]["problems"][0]

    def test_doctor_fixes_stale_blocked_status(self, mock_worktree: Path):
        """Test doctor can fix stale blocked status."""
        issue = create_issue("Stale blocked", mock_worktree)
        issue["status"] = Status.BLOCKED.value
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree, fix=True)

        assert len(result["fixed"]) == 1

        fixed_issue = get_issue(mock_worktree, issue["id"])
        assert fixed_issue["status"] == Status.OPEN.value

    def test_doctor_detects_invalid_priority(self, mock_worktree: Path):
        """Test doctor detects invalid priority values."""
        issue = create_issue("Invalid priority", mock_worktree)
        issue["priority"] = 10  # Invalid - should be 0-4
        save_issue(mock_worktree, issue)

        result = run_doctor(mock_worktree)

        assert len(result["problems"]) == 1
        assert "invalid priority" in result["problems"][0]["problems"][0]

    def test_doctor_detects_dependency_cycle(self, mock_worktree: Path):
        """Test doctor detects dependency cycles."""
        issue_a = create_issue("Issue A", mock_worktree)
        issue_b = create_issue("Issue B", mock_worktree)
        # Create a cycle: A depends on B, B depends on A
        issue_a["dependencies"] = [issue_b["id"]]
        issue_b["dependencies"] = [issue_a["id"]]
        save_issue(mock_worktree, issue_a)
        save_issue(mock_worktree, issue_b)

        result = run_doctor(mock_worktree)

        # Should detect cycle
        cycle_problems = [
            p for p in result["problems"] if any("cycle" in prob for prob in p["problems"])
        ]
        assert len(cycle_problems) >= 1

    def test_doctor_detects_stale_ownership(self, mock_worktree: Path):
        """Test doctor detects stale ownership (branch gone, old claim)."""
        issue = create_issue("Stale issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Claim with a non-existent branch and old timestamp
        updated = update_issue(
            mock_worktree,
            issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="deleted-branch-xyz",
        )
        # Manually set claimed_at to 48 hours ago
        old_time = "2020-01-01T00:00:00Z"
        updated["claimed_at"] = old_time
        save_issue(mock_worktree, updated)

        # Run doctor with a short stale threshold
        result = run_doctor(mock_worktree, stale_hours=1.0)

        stale_problems = [
            p
            for p in result["problems"]
            if any("stale ownership" in prob for prob in p["problems"])
        ]
        assert len(stale_problems) == 1

    def test_doctor_fixes_stale_ownership(self, mock_worktree: Path):
        """Test doctor can fix stale ownership by clearing and reopening."""
        issue = create_issue("Stale issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Claim with a non-existent branch and old timestamp
        updated = update_issue(
            mock_worktree,
            issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="deleted-branch-xyz",
        )
        updated["claimed_at"] = "2020-01-01T00:00:00Z"
        save_issue(mock_worktree, updated)

        # Run doctor with fix=True
        result = run_doctor(mock_worktree, fix=True, stale_hours=1.0)

        assert len(result["fixed"]) == 1
        assert "cleared stale ownership" in result["fixed"][0]["fixes"][0]

        # Verify the issue was fixed
        fixed_issue = get_issue(mock_worktree, issue["id"])
        assert fixed_issue["status"] == "open"
        assert "claimed_by" not in fixed_issue

    def test_doctor_ignores_active_ownership(self, mock_worktree: Path):
        """Test doctor doesn't flag ownership on branches that exist."""
        issue = create_issue("Active issue", mock_worktree)
        save_issue(mock_worktree, issue)

        # Claim with a recent timestamp (branch check will fail but timestamp is recent)
        update_issue(
            mock_worktree,
            issue["id"],
            status=Status.IN_PROGRESS,
            claimed_by="some-branch",
        )

        # Run doctor - should not detect as stale because timestamp is recent
        result = run_doctor(mock_worktree, stale_hours=24.0)

        stale_problems = [
            p
            for p in result["problems"]
            if any("stale ownership" in prob for prob in p["problems"])
        ]
        assert len(stale_problems) == 0


class TestDiskCache:
    """Tests for the persistent disk cache functionality."""

    def test_disk_cache_path_determined_correctly(self, mock_worktree_with_cache: Path):
        """Test that disk cache path is determined correctly from worktree."""
        cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)

        assert cache_path is not None
        # Cache should be in .git/microbeads-cache/
        assert "microbeads-cache" in str(cache_path)
        assert cache_path.name == _ACTIVE_CACHE_FILE

    def test_disk_cache_created_on_first_load(self, mock_worktree_with_cache: Path):
        """Test that disk cache is created when loading issues."""
        # Clear any in-memory cache
        clear_cache()

        # Create some issues
        issue1 = create_issue("Issue 1", mock_worktree_with_cache)
        issue2 = create_issue("Issue 2", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue1)
        save_issue(mock_worktree_with_cache, issue2)

        # Clear in-memory cache to force disk read
        clear_cache()

        # Load issues - this should create the disk cache
        loaded = load_active_issues(mock_worktree_with_cache)
        assert len(loaded) == 2

        # Verify disk cache was created
        cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        assert cache_path is not None
        assert cache_path.exists()

    def test_disk_cache_hit_on_subsequent_load(self, mock_worktree_with_cache: Path):
        """Test that disk cache is used on subsequent loads."""
        import time

        clear_cache()

        # Create an issue
        issue = create_issue("Test Issue", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue)

        # First load creates cache
        clear_cache()
        load_active_issues(mock_worktree_with_cache)

        cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        assert cache_path is not None

        # Record cache mtime
        cache_mtime_before = cache_path.stat().st_mtime

        # Small delay to ensure time passes
        time.sleep(0.01)

        # Second load should use cache (not rewrite it)
        clear_cache()
        loaded = load_active_issues(mock_worktree_with_cache)

        # Cache file should not have been rewritten
        cache_mtime_after = cache_path.stat().st_mtime
        assert cache_mtime_before == cache_mtime_after

        # Data should still be correct
        assert issue["id"] in loaded

    def test_disk_cache_invalidated_on_file_modification(self, mock_worktree_with_cache: Path):
        """Test that disk cache is invalidated when an issue file is modified."""
        import time

        clear_cache()

        # Create and load an issue
        issue = create_issue("Test Issue", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue)

        clear_cache()
        load_active_issues(mock_worktree_with_cache)

        cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        cache_mtime_before = cache_path.stat().st_mtime

        # Small delay
        time.sleep(0.01)

        # Modify the issue file (update the issue)
        issue["title"] = "Modified Issue"
        save_issue(mock_worktree_with_cache, issue)

        # Clear in-memory cache
        clear_cache()

        # Load should detect stale cache and rebuild
        loaded = load_active_issues(mock_worktree_with_cache)

        # Verify the modified title is loaded
        assert loaded[issue["id"]]["title"] == "Modified Issue"

        # Cache should have been rewritten
        cache_mtime_after = cache_path.stat().st_mtime
        assert cache_mtime_after > cache_mtime_before

    def test_disk_cache_invalidated_on_file_deletion(self, mock_worktree_with_cache: Path):
        """Test that disk cache is invalidated when an issue file is deleted."""
        clear_cache()

        # Create two issues
        issue1 = create_issue("Issue 1", mock_worktree_with_cache)
        issue2 = create_issue("Issue 2", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue1)
        save_issue(mock_worktree_with_cache, issue2)

        # Load to create cache
        clear_cache()
        loaded = load_active_issues(mock_worktree_with_cache)
        assert len(loaded) == 2

        # Close issue1 (moves it from active to closed)
        close_issue(mock_worktree_with_cache, issue1["id"])

        # Clear in-memory cache
        clear_cache()

        # Load should detect count mismatch and rebuild
        loaded = load_active_issues(mock_worktree_with_cache)

        # Only issue2 should be in active issues now
        assert len(loaded) == 1
        assert issue2["id"] in loaded
        assert issue1["id"] not in loaded

    def test_disk_cache_with_no_issues(self, mock_worktree_with_cache: Path):
        """Test disk cache behavior with no issues."""
        clear_cache()

        # Load empty issues - should work without errors
        loaded = load_active_issues(mock_worktree_with_cache)
        assert loaded == {}

    def test_disk_cache_corrupted_is_rebuilt(self, mock_worktree_with_cache: Path):
        """Test that corrupted disk cache is detected and rebuilt."""
        clear_cache()

        # Create an issue
        issue = create_issue("Test Issue", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue)

        # Load to create cache
        clear_cache()
        load_active_issues(mock_worktree_with_cache)

        # Corrupt the cache
        cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        assert cache_path is not None
        cache_path.write_text("not valid json {{{")

        # Clear in-memory cache
        clear_cache()

        # Load should detect corruption and rebuild
        loaded = load_active_issues(mock_worktree_with_cache)

        # Data should still be correct
        assert issue["id"] in loaded
        assert loaded[issue["id"]]["title"] == "Test Issue"

    def test_clear_cache_include_disk_deletes_cache_files(self, mock_worktree_with_cache: Path):
        """Test that clear_cache with include_disk=True deletes disk cache files."""
        clear_cache()

        # Create an issue and load to create disk cache
        issue = create_issue("Test Issue", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue)
        clear_cache()
        load_active_issues(mock_worktree_with_cache)

        # Verify disk cache was created
        active_cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        assert active_cache_path is not None
        assert active_cache_path.exists()

        # Clear with include_disk=True
        clear_cache(mock_worktree_with_cache, include_disk=True)

        # Disk cache should be deleted
        assert not active_cache_path.exists()

    def test_clear_cache_without_include_disk_preserves_cache_files(
        self, mock_worktree_with_cache: Path
    ):
        """Test that clear_cache without include_disk preserves disk cache files."""
        clear_cache()

        # Create an issue and load to create disk cache
        issue = create_issue("Test Issue", mock_worktree_with_cache)
        save_issue(mock_worktree_with_cache, issue)
        clear_cache()
        load_active_issues(mock_worktree_with_cache)

        # Verify disk cache was created
        active_cache_path = _get_disk_cache_path(mock_worktree_with_cache, _ACTIVE_CACHE_FILE)
        assert active_cache_path is not None
        assert active_cache_path.exists()

        # Clear without include_disk (default)
        clear_cache(mock_worktree_with_cache)

        # Disk cache should still exist
        assert active_cache_path.exists()
