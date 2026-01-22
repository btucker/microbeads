"""End-to-end tests for the microbeads CLI."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from microbeads import repo


def run_mb(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the mb CLI command."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        ["uv", "run", "mb", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=full_env,
    )


@pytest.fixture
def e2e_repo(tmp_path: Path) -> Path:
    """Create a full git repository for E2E testing."""
    repo_dir = tmp_path / "e2e-repo"
    repo_dir.mkdir()

    # Set up environment for git commands
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
    }

    # Initialize git repo
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo_dir, capture_output=True, check=True, env=env
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env=env,
    )
    # Disable GPG signing for tests
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env=env,
    )

    # Create initial commit
    readme = repo_dir / "README.md"
    readme.write_text("# E2E Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        capture_output=True,
        check=True,
        env=env,
    )

    return repo_dir


class TestHappyPathWorkflow:
    """E2E tests for the happy path workflow."""

    def test_init_creates_microbeads_branch(self, e2e_repo: Path):
        """Test that init creates the microbeads orphan branch."""
        result = run_mb("init", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Microbeads initialized" in result.stdout

        # Verify branch exists
        assert repo.is_initialized(e2e_repo)

    def test_full_issue_lifecycle(self, e2e_repo: Path):
        """Test creating, updating, and closing an issue."""
        # Initialize
        run_mb("init", cwd=e2e_repo)

        # Create issue
        result = run_mb("create", "Fix the bug", "-p", "1", "-t", "bug", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Created" in result.stdout

        # Extract issue ID from output (e.g., "Created e2e-abc1: Fix the bug")
        issue_id = result.stdout.split()[1].rstrip(":")

        # List issues - should show the new issue
        result = run_mb("list", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Fix the bug" in result.stdout

        # Show issue details
        result = run_mb("show", issue_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "Fix the bug" in result.stdout
        assert "bug" in result.stdout
        assert "P1" in result.stdout

        # Update status to in_progress
        result = run_mb("update", issue_id, "-s", "in_progress", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Updated" in result.stdout

        # Verify status changed
        result = run_mb("show", issue_id, cwd=e2e_repo)
        assert "in_progress" in result.stdout

        # Close issue
        result = run_mb("close", issue_id, "-r", "Fixed in commit abc123", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Closed" in result.stdout

        # Verify issue is closed
        result = run_mb("show", issue_id, cwd=e2e_repo)
        assert "closed" in result.stdout
        assert "Fixed in commit abc123" in result.stdout

    def test_ready_shows_actionable_issues(self, e2e_repo: Path):
        """Test that ready command shows issues without blockers."""
        run_mb("init", cwd=e2e_repo)

        # Create two issues
        run_mb("create", "Task A", "-p", "1", cwd=e2e_repo)
        run_mb("create", "Task B", "-p", "2", cwd=e2e_repo)

        # Both should be ready
        result = run_mb("ready", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Task A" in result.stdout
        assert "Task B" in result.stdout

    def test_list_filters_by_status(self, e2e_repo: Path):
        """Test filtering issues by status."""
        run_mb("init", cwd=e2e_repo)

        # Create and close one issue
        result = run_mb("create", "Done task", cwd=e2e_repo)
        done_id = result.stdout.split()[1].rstrip(":")
        run_mb("close", done_id, cwd=e2e_repo)

        # Create open issue
        run_mb("create", "Open task", cwd=e2e_repo)

        # Filter by open
        result = run_mb("list", "-s", "open", cwd=e2e_repo)
        assert "Open task" in result.stdout
        assert "Done task" not in result.stdout

        # Filter by closed
        result = run_mb("list", "-s", "closed", cwd=e2e_repo)
        assert "Done task" in result.stdout
        assert "Open task" not in result.stdout

    def test_json_output_format(self, e2e_repo: Path):
        """Test that --json flag returns valid JSON."""
        run_mb("init", cwd=e2e_repo)
        run_mb("create", "JSON test", "-p", "0", "-t", "feature", cwd=e2e_repo)

        result = run_mb("--json", "list", cwd=e2e_repo)
        assert result.returncode == 0

        # Should be valid JSON
        issues = json.loads(result.stdout)
        assert isinstance(issues, list)
        assert len(issues) == 1
        assert issues[0]["title"] == "JSON test"
        assert issues[0]["priority"] == 0
        assert issues[0]["type"] == "feature"


class TestDependencyManagement:
    """E2E tests for dependency management."""

    def test_add_dependency(self, e2e_repo: Path):
        """Test adding a dependency between issues."""
        run_mb("init", cwd=e2e_repo)

        # Create parent and child issues
        result = run_mb("create", "Parent task", cwd=e2e_repo)
        parent_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Child task", cwd=e2e_repo)
        child_id = result.stdout.split()[1].rstrip(":")

        # Add dependency
        result = run_mb("dep", "add", child_id, parent_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "depends on" in result.stdout

        # Verify child shows dependency
        result = run_mb("show", child_id, cwd=e2e_repo)
        assert parent_id in result.stdout

    def test_dependency_blocks_ready(self, e2e_repo: Path):
        """Test that issues with open dependencies are not ready."""
        run_mb("init", cwd=e2e_repo)

        # Create parent and child
        result = run_mb("create", "Blocker", cwd=e2e_repo)
        blocker_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Blocked task", cwd=e2e_repo)
        blocked_id = result.stdout.split()[1].rstrip(":")

        # Add dependency
        run_mb("dep", "add", blocked_id, blocker_id, cwd=e2e_repo)

        # Only blocker should be ready
        result = run_mb("ready", cwd=e2e_repo)
        assert "Blocker" in result.stdout
        assert "Blocked task" not in result.stdout

        # Blocked command should show the blocked issue
        result = run_mb("blocked", cwd=e2e_repo)
        assert "Blocked task" in result.stdout

    def test_closing_blocker_unblocks_child(self, e2e_repo: Path):
        """Test that closing a blocker makes child ready."""
        run_mb("init", cwd=e2e_repo)

        # Create parent and child
        result = run_mb("create", "Blocker", cwd=e2e_repo)
        blocker_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Blocked task", cwd=e2e_repo)
        blocked_id = result.stdout.split()[1].rstrip(":")

        # Add dependency
        run_mb("dep", "add", blocked_id, blocker_id, cwd=e2e_repo)

        # Close the blocker
        run_mb("close", blocker_id, cwd=e2e_repo)

        # Now blocked task should be ready
        result = run_mb("ready", cwd=e2e_repo)
        assert "Blocked task" in result.stdout

    def test_remove_dependency(self, e2e_repo: Path):
        """Test removing a dependency."""
        run_mb("init", cwd=e2e_repo)

        # Create and link issues
        result = run_mb("create", "Parent", cwd=e2e_repo)
        parent_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Child", cwd=e2e_repo)
        child_id = result.stdout.split()[1].rstrip(":")

        run_mb("dep", "add", child_id, parent_id, cwd=e2e_repo)

        # Remove dependency
        result = run_mb("dep", "rm", child_id, parent_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "Removed dependency" in result.stdout

        # Both should now be ready
        result = run_mb("ready", cwd=e2e_repo)
        assert "Parent" in result.stdout
        assert "Child" in result.stdout

    def test_dependency_tree(self, e2e_repo: Path):
        """Test viewing the dependency tree."""
        run_mb("init", cwd=e2e_repo)

        # Create chain: grandparent -> parent -> child
        result = run_mb("create", "Grandparent", cwd=e2e_repo)
        gp_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Parent", cwd=e2e_repo)
        p_id = result.stdout.split()[1].rstrip(":")

        result = run_mb("create", "Child", cwd=e2e_repo)
        c_id = result.stdout.split()[1].rstrip(":")

        run_mb("dep", "add", p_id, gp_id, cwd=e2e_repo)
        run_mb("dep", "add", c_id, p_id, cwd=e2e_repo)

        # View tree from child
        result = run_mb("dep", "tree", c_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "Child" in result.stdout
        assert "Parent" in result.stdout
        assert "Grandparent" in result.stdout


class TestPartialIdMatching:
    """E2E tests for partial ID matching."""

    def test_partial_id_in_show(self, e2e_repo: Path):
        """Test that partial IDs work in show command."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Test issue", cwd=e2e_repo)
        full_id = result.stdout.split()[1].rstrip(":")
        # Use first 4 chars as partial ID
        partial_id = full_id[:4]

        result = run_mb("show", partial_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "Test issue" in result.stdout

    def test_partial_id_in_update(self, e2e_repo: Path):
        """Test that partial IDs work in update command."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Update me", cwd=e2e_repo)
        full_id = result.stdout.split()[1].rstrip(":")
        partial_id = full_id[:4]

        result = run_mb("update", partial_id, "-s", "in_progress", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Updated" in result.stdout

    def test_partial_id_in_close(self, e2e_repo: Path):
        """Test that partial IDs work in close command."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Close me", cwd=e2e_repo)
        full_id = result.stdout.split()[1].rstrip(":")
        partial_id = full_id[:4]

        result = run_mb("close", partial_id, cwd=e2e_repo)
        assert result.returncode == 0
        assert "Closed" in result.stdout


class TestErrorHandling:
    """E2E tests for error handling."""

    def test_show_nonexistent_issue(self, e2e_repo: Path):
        """Test error when showing non-existent issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("show", "nonexistent-123", cwd=e2e_repo)
        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()

    def test_update_nonexistent_issue(self, e2e_repo: Path):
        """Test error when updating non-existent issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("update", "nonexistent-123", "-s", "closed", cwd=e2e_repo)
        assert result.returncode != 0

    def test_close_nonexistent_issue(self, e2e_repo: Path):
        """Test error when closing non-existent issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("close", "nonexistent-123", cwd=e2e_repo)
        assert result.returncode != 0

    def test_commands_before_init(self, e2e_repo: Path):
        """Test error when running commands before init."""
        result = run_mb("list", cwd=e2e_repo)
        assert result.returncode != 0
        assert "not initialized" in result.stderr.lower() or "init" in result.stderr.lower()

    def test_reopen_open_issue(self, e2e_repo: Path):
        """Test reopening an already open issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Open issue", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        # Try to reopen an open issue - should work or give appropriate feedback
        result = run_mb("reopen", issue_id, cwd=e2e_repo)
        # Either succeeds (no-op) or gives an error
        # The important thing is it doesn't crash


class TestInitAutoSetupClaude:
    """E2E tests for auto-setup Claude hooks during init."""

    def test_init_auto_setup_claude_with_claude_dir(self, e2e_repo: Path):
        """Test that init auto-runs setup claude when .claude directory exists."""
        # Create .claude directory
        claude_dir = e2e_repo / ".claude"
        claude_dir.mkdir()

        result = run_mb("init", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Detected Claude Code artifacts" in result.stdout
        assert "Installing Claude hooks" in result.stdout

        # Verify hooks were installed
        settings_path = claude_dir / "settings.json"
        assert settings_path.exists()
        settings = json.loads(settings_path.read_text())
        assert "hooks" in settings
        assert "SessionStart" in settings["hooks"]

    def test_init_auto_setup_claude_with_claude_md(self, e2e_repo: Path):
        """Test that init auto-runs setup claude when CLAUDE.md file exists."""
        # Create CLAUDE.md file
        claude_md = e2e_repo / "CLAUDE.md"
        claude_md.write_text("# Claude Instructions\n")

        result = run_mb("init", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Detected Claude Code artifacts" in result.stdout
        assert "Installing Claude hooks" in result.stdout

        # Verify hooks were installed
        settings_path = e2e_repo / ".claude" / "settings.json"
        assert settings_path.exists()

    def test_init_no_auto_setup_without_claude_artifacts(self, e2e_repo: Path):
        """Test that init does NOT auto-run setup claude when no Claude artifacts exist."""
        result = run_mb("init", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Detected Claude Code artifacts" not in result.stdout

        # Verify hooks were NOT installed (no .claude/settings.json)
        settings_path = e2e_repo / ".claude" / "settings.json"
        assert not settings_path.exists()


class TestLabels:
    """E2E tests for label management."""

    def test_create_with_labels(self, e2e_repo: Path):
        """Test creating an issue with labels."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Labeled issue", "-l", "frontend", "-l", "urgent", cwd=e2e_repo)
        assert result.returncode == 0

        result = run_mb("--json", "list", cwd=e2e_repo)
        issues = json.loads(result.stdout)
        assert "frontend" in issues[0]["labels"]
        assert "urgent" in issues[0]["labels"]

    def test_filter_by_label(self, e2e_repo: Path):
        """Test filtering issues by label."""
        run_mb("init", cwd=e2e_repo)

        run_mb("create", "Frontend bug", "-l", "frontend", cwd=e2e_repo)
        run_mb("create", "Backend bug", "-l", "backend", cwd=e2e_repo)

        result = run_mb("list", "-l", "frontend", cwd=e2e_repo)
        assert "Frontend bug" in result.stdout
        assert "Backend bug" not in result.stdout

    def test_add_label_to_existing(self, e2e_repo: Path):
        """Test adding a label to an existing issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Unlabeled", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        run_mb("update", issue_id, "--add-label", "new-label", cwd=e2e_repo)

        result = run_mb("--json", "show", issue_id, cwd=e2e_repo)
        issue = json.loads(result.stdout)
        assert "new-label" in issue["labels"]

    def test_remove_label(self, e2e_repo: Path):
        """Test removing a label from an issue."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Has label", "-l", "removeme", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        run_mb("update", issue_id, "--remove-label", "removeme", cwd=e2e_repo)

        result = run_mb("--json", "show", issue_id, cwd=e2e_repo)
        issue = json.loads(result.stdout)
        assert "removeme" not in issue["labels"]


class TestAdditionalFields:
    """E2E tests for additional issue fields (design, notes, acceptance_criteria)."""

    def test_create_with_design_field(self, e2e_repo: Path):
        """Test creating an issue with design field."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Feature", "--design", "Use singleton pattern", cwd=e2e_repo)
        assert result.returncode == 0

        result = run_mb("--json", "list", cwd=e2e_repo)
        issues = json.loads(result.stdout)
        assert issues[0]["design"] == "Use singleton pattern"

    def test_create_with_notes_field(self, e2e_repo: Path):
        """Test creating an issue with notes field."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Task", "--notes", "Consider edge cases", cwd=e2e_repo)
        assert result.returncode == 0

        result = run_mb("--json", "list", cwd=e2e_repo)
        issues = json.loads(result.stdout)
        assert issues[0]["notes"] == "Consider edge cases"

    def test_create_with_acceptance_criteria(self, e2e_repo: Path):
        """Test creating an issue with acceptance_criteria field."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb(
            "create", "Feature", "--acceptance-criteria", "All tests pass", cwd=e2e_repo
        )
        assert result.returncode == 0

        result = run_mb("--json", "list", cwd=e2e_repo)
        issues = json.loads(result.stdout)
        assert issues[0]["acceptance_criteria"] == "All tests pass"

    def test_update_design_field(self, e2e_repo: Path):
        """Test updating the design field."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Feature", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        run_mb("update", issue_id, "--design", "New architecture", cwd=e2e_repo)

        result = run_mb("--json", "show", issue_id, cwd=e2e_repo)
        issue = json.loads(result.stdout)
        assert issue["design"] == "New architecture"

    def test_show_displays_additional_fields(self, e2e_repo: Path):
        """Test that show command displays additional fields."""
        run_mb("init", cwd=e2e_repo)

        run_mb(
            "create",
            "Feature",
            "--design",
            "Strategy pattern",
            "--notes",
            "Important note",
            "--acceptance-criteria",
            "Tests pass",
            cwd=e2e_repo,
        )

        result = run_mb("list", cwd=e2e_repo)
        # Get the issue id from list
        result = run_mb("--json", "list", cwd=e2e_repo)
        issues = json.loads(result.stdout)
        issue_id = issues[0]["id"]

        result = run_mb("show", issue_id, cwd=e2e_repo)
        assert "Strategy pattern" in result.stdout
        assert "Important note" in result.stdout
        assert "Tests pass" in result.stdout


class TestHistoryTracking:
    """E2E tests for issue history tracking."""

    def test_show_displays_history(self, e2e_repo: Path):
        """Test that show command displays history."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Issue", "-p", "2", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        # Make some changes
        run_mb("update", issue_id, "-p", "0", cwd=e2e_repo)
        run_mb("update", issue_id, "-s", "in_progress", cwd=e2e_repo)

        result = run_mb("show", issue_id, cwd=e2e_repo)
        # Should show history section
        assert "History" in result.stdout or "history" in result.stdout.lower()

    def test_json_output_includes_history(self, e2e_repo: Path):
        """Test that JSON output includes history."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("create", "Issue", cwd=e2e_repo)
        issue_id = result.stdout.split()[1].rstrip(":")

        run_mb("update", issue_id, "-s", "in_progress", cwd=e2e_repo)

        result = run_mb("--json", "show", issue_id, cwd=e2e_repo)
        issue = json.loads(result.stdout)

        assert "history" in issue
        assert len(issue["history"]) >= 1


class TestDoctorCommand:
    """E2E tests for the doctor command."""

    def test_doctor_no_issues(self, e2e_repo: Path):
        """Test doctor with no issues."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("doctor", cwd=e2e_repo)
        assert result.returncode == 0
        assert "0 issues" in result.stdout or "No problems" in result.stdout

    def test_doctor_healthy_issues(self, e2e_repo: Path):
        """Test doctor with healthy issues."""
        run_mb("init", cwd=e2e_repo)
        run_mb("create", "Issue 1", cwd=e2e_repo)
        run_mb("create", "Issue 2", cwd=e2e_repo)

        result = run_mb("doctor", cwd=e2e_repo)
        assert result.returncode == 0
        # Should report checking 2 issues
        assert "2" in result.stdout

    def test_doctor_with_fix_flag(self, e2e_repo: Path):
        """Test doctor with --fix flag."""
        run_mb("init", cwd=e2e_repo)
        run_mb("create", "Issue", cwd=e2e_repo)

        result = run_mb("doctor", "--fix", cwd=e2e_repo)
        assert result.returncode == 0


class TestCompactCommand:
    """E2E tests for the compact command."""

    def test_compact_no_closed_issues(self, e2e_repo: Path):
        """Test compact with no closed issues."""
        run_mb("init", cwd=e2e_repo)
        run_mb("create", "Open Issue", cwd=e2e_repo)

        result = run_mb("compact", cwd=e2e_repo)
        assert result.returncode == 0
        assert "0" in result.stdout or "No issues" in result.stdout

    def test_compact_with_days_option(self, e2e_repo: Path):
        """Test compact with --days option."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("compact", "--days", "30", cwd=e2e_repo)
        assert result.returncode == 0


class TestHooksCommand:
    """E2E tests for the hooks install/remove commands."""

    def test_hooks_install(self, e2e_repo: Path):
        """Test installing git hooks."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("hooks", "install", cwd=e2e_repo)
        assert result.returncode == 0
        assert "installed" in result.stdout.lower() or "hooks" in result.stdout.lower()

        # Verify git hooks were created
        hooks_dir = e2e_repo / ".git" / "hooks"
        assert (hooks_dir / "post-merge").exists()
        assert (hooks_dir / "post-checkout").exists()
        assert (hooks_dir / "pre-push").exists()

    def test_hooks_install_specific(self, e2e_repo: Path):
        """Test installing specific hooks only."""
        run_mb("init", cwd=e2e_repo)

        result = run_mb("hooks", "install", "--hook", "post-merge", cwd=e2e_repo)
        assert result.returncode == 0

        # Verify only post-merge was created
        hooks_dir = e2e_repo / ".git" / "hooks"
        assert (hooks_dir / "post-merge").exists()

    def test_hooks_remove(self, e2e_repo: Path):
        """Test removing hooks."""
        run_mb("init", cwd=e2e_repo)

        # First install
        run_mb("hooks", "install", cwd=e2e_repo)

        # Then remove
        result = run_mb("hooks", "remove", cwd=e2e_repo)
        assert result.returncode == 0


class TestStealthMode:
    """E2E tests for stealth mode."""

    def test_init_with_stealth_flag(self, e2e_repo: Path):
        """Test initializing with --stealth flag."""
        result = run_mb("init", "--stealth", cwd=e2e_repo)
        assert result.returncode == 0
        assert "stealth" in result.stdout.lower() or "Microbeads initialized" in result.stdout

    def test_stealth_mode_allows_create_and_list(self, e2e_repo: Path):
        """Test that stealth mode allows normal issue operations."""
        run_mb("init", "--stealth", cwd=e2e_repo)

        result = run_mb("create", "Stealth Issue", cwd=e2e_repo)
        assert result.returncode == 0

        result = run_mb("list", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Stealth Issue" in result.stdout


class TestContributorMode:
    """E2E tests for contributor mode."""

    def test_init_with_contributor_flag(self, e2e_repo: Path, tmp_path: Path):
        """Test initializing with --contributor flag."""
        external_repo = tmp_path / "external"
        external_repo.mkdir()

        result = run_mb("init", "--contributor", str(external_repo), cwd=e2e_repo)
        assert result.returncode == 0
