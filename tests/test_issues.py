"""Tests for issue management functionality."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from microbeads.issues import (
    _ACTIVE_CACHE_FILE,
    IssueType,
    Status,
    _add_history_entry,
    _get_disk_cache_path,
    add_dependency,
    clear_cache,
    close_issue,
    compact_closed_issues,
    compact_issue,
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
    run_doctor,
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


class TestCompactCommand:
    """Tests for issue compaction."""

    def test_compact_issue_closed(self):
        """Test compacting a closed issue."""
        issue = {
            "id": "test-1234",
            "title": "Completed feature",
            "status": "closed",
            "type": "feature",
            "priority": 1,
            "description": "Long description\nwith multiple lines\nof text",
            "labels": ["frontend", "urgent"],
            "dependencies": ["dep-1", "dep-2"],
            "history": [{"field": "status", "old": "open", "new": "closed"}],
            "closed_at": "2024-01-01T00:00:00Z",
            "closed_reason": "Done",
            "design": "Some design notes",
            "notes": "Some notes",
        }

        compacted = compact_issue(issue)

        # Essential fields preserved
        assert compacted["id"] == "test-1234"
        assert compacted["title"] == "Completed feature"
        assert compacted["status"] == "closed"
        assert compacted["type"] == "feature"
        assert compacted["priority"] == 1
        assert compacted["closed_at"] == "2024-01-01T00:00:00Z"
        assert compacted["closed_reason"] == "Done"
        assert compacted["compacted"] is True

        # Verbose fields removed
        assert "description" not in compacted
        assert "history" not in compacted
        assert "design" not in compacted
        assert "notes" not in compacted
        assert "labels" not in compacted
        assert "dependencies" not in compacted

        # Counts preserved
        assert compacted["label_count"] == 2
        assert compacted["dependency_count"] == 2

        # Summary from first line of description
        assert compacted["summary"] == "Long description"

    def test_compact_issue_skips_open(self):
        """Test that compact_issue doesn't modify open issues."""
        issue = {
            "id": "test-1234",
            "title": "Open issue",
            "status": "open",
            "description": "Should not be compacted",
        }

        compacted = compact_issue(issue)

        assert compacted == issue  # Unchanged

    def test_compact_closed_issues_respects_age(self, mock_worktree: Path):
        """Test that compact_closed_issues respects the age threshold."""
        from datetime import datetime, timedelta, timezone

        # Create a recently closed issue
        recent = create_issue("Recent", mock_worktree)
        recent["status"] = Status.CLOSED.value
        recent["closed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        save_issue(mock_worktree, recent)

        # Create an old closed issue
        old = create_issue("Old", mock_worktree)
        old["status"] = Status.CLOSED.value
        old_date = datetime.now(timezone.utc) - timedelta(days=30)
        old["closed_at"] = old_date.isoformat().replace("+00:00", "Z")
        save_issue(mock_worktree, old)

        result = compact_closed_issues(mock_worktree, older_than_days=7)

        # Only old issue should be compacted
        assert len(result["compacted"]) == 1
        assert result["compacted"][0]["id"] == old["id"]

    def test_compact_closed_issues_skips_already_compacted(self, mock_worktree: Path):
        """Test that already compacted issues are skipped."""
        issue = create_issue("Already compacted", mock_worktree)
        issue["status"] = Status.CLOSED.value
        issue["compacted"] = True
        issue["closed_at"] = "2020-01-01T00:00:00Z"  # Old
        save_issue(mock_worktree, issue)

        result = compact_closed_issues(mock_worktree, older_than_days=1)

        assert result["compacted"] == []
        assert result["skipped"] == 1


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
