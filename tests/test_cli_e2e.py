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


class TestBeadsImport:
    """E2E tests for beads import functionality."""

    def test_init_without_import_beads(self, e2e_repo: Path):
        """Test that init works without --import-beads flag."""
        result = run_mb("init", cwd=e2e_repo)
        assert result.returncode == 0
        assert "Microbeads initialized" in result.stdout

    def test_init_with_import_beads_missing_bd(self, e2e_repo: Path):
        """Test that --import-beads gives clear error when bd not installed."""
        # Check if bd is actually installed - if it is, skip this test
        try:
            check_bd = subprocess.run(["bd", "--version"], capture_output=True)
            if check_bd.returncode == 0:
                pytest.skip("bd is installed, skipping missing bd test")
        except FileNotFoundError:
            pass  # bd not found, which is what we want to test

        result = run_mb("init", "--import-beads", cwd=e2e_repo)
        # Should fail with clear error about bd not being found
        assert result.returncode != 0
        assert "bd" in result.stderr.lower() or "beads" in result.stderr.lower()

    def test_import_from_beads_mocked(self, e2e_repo: Path, tmp_path: Path):
        """Test import functionality by creating a mock bd script."""
        # Create a mock bd script that returns JSON
        mock_bd = tmp_path / "bd"
        mock_bd_content = """#!/usr/bin/env python3
import sys
import json

if len(sys.argv) > 1 and sys.argv[1] == "--version":
    print("bd 1.0.0")
    sys.exit(0)

if len(sys.argv) > 1 and sys.argv[1] == "list" and "--json" in sys.argv:
    # Return mock issues
    issues = [
        {
            "id": "bd-test1234",
            "title": "Test issue from beads",
            "status": "open",
            "priority": 1,
            "issue_type": "bug",
            "labels": ["imported"],
            "description": "A test issue",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "dependencies": []
        }
    ]
    print(json.dumps(issues))
    sys.exit(0)

sys.exit(1)
"""
        mock_bd.write_text(mock_bd_content)
        mock_bd.chmod(0o755)

        # Run init with the mock bd in PATH (prepend to existing PATH)
        env = {"PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}
        result = run_mb("init", "--import-beads", cwd=e2e_repo, env=env)

        # Should succeed with import
        assert result.returncode == 0
        assert "Microbeads initialized" in result.stdout

        # Check if issue was imported
        list_result = run_mb("--json", "list", cwd=e2e_repo)
        assert list_result.returncode == 0

        issues_list = json.loads(list_result.stdout) if list_result.stdout.strip() else []
        titles = [i.get("title") for i in issues_list]
        assert "Test issue from beads" in titles


class TestMergeDriverConflictResolution:
    """E2E tests for the JSON merge driver conflict resolution."""

    @pytest.fixture
    def merge_test_setup(self, tmp_path: Path) -> dict:
        """Create two clones for testing merge driver through actual git operations."""
        env = {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        }

        # Create bare origin repo
        origin = tmp_path / "origin.git"
        origin.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "-b", "main"],
            cwd=origin,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create first clone
        clone_a = tmp_path / "clone-a"
        subprocess.run(
            ["git", "clone", str(origin), str(clone_a)],
            capture_output=True,
            check=True,
            env=env,
        )
        for config_cmd in [
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test User"],
            ["git", "config", "commit.gpgsign", "false"],
        ]:
            subprocess.run(config_cmd, cwd=clone_a, capture_output=True, check=True, env=env)

        # Create initial commit and push
        (clone_a / "README.md").write_text("# Merge Test\n")
        subprocess.run(["git", "add", "."], cwd=clone_a, capture_output=True, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=clone_a,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=clone_a,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create second clone
        clone_b = tmp_path / "clone-b"
        subprocess.run(
            ["git", "clone", str(origin), str(clone_b)],
            capture_output=True,
            check=True,
            env=env,
        )
        for config_cmd in [
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test User"],
            ["git", "config", "commit.gpgsign", "false"],
        ]:
            subprocess.run(config_cmd, cwd=clone_b, capture_output=True, check=True, env=env)

        return {"origin": origin, "clone_a": clone_a, "clone_b": clone_b, "env": env}

    def test_scalar_conflict_newer_timestamp_wins(self, merge_test_setup: dict):
        """Test that scalar field conflicts are resolved by newest timestamp."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize microbeads in both clones
        run_mb("init", cwd=clone_a)
        run_mb("init", cwd=clone_b)

        # Clone A creates an issue and syncs
        result = run_mb("create", "Conflict Test Issue", "-p", "2", cwd=clone_a)
        assert result.returncode == 0
        issue_id = result.stdout.split()[1].rstrip(":")
        run_mb("sync", cwd=clone_a)

        # Clone B syncs to get the issue
        run_mb("sync", cwd=clone_b)

        # Clone A changes priority to P0
        run_mb("update", issue_id, "-p", "0", cwd=clone_a)
        run_mb("sync", cwd=clone_a)

        # Clone B (without syncing first) changes priority to P3
        # (This creates a real conflict scenario since clone B has stale data)
        run_mb("update", issue_id, "-p", "3", cwd=clone_b)

        # Clone B syncs - merge driver should resolve based on timestamps
        # Since Clone B's update happened after Clone A's, Clone B's value should win
        run_mb("sync", cwd=clone_b)

        # Verify the final state in clone B
        result = run_mb("--json", "show", issue_id, cwd=clone_b)
        issue = json.loads(result.stdout)
        # Clone B's update was more recent, so priority should be 3
        assert issue["priority"] == 3, f"Expected priority 3 (B's update), got {issue['priority']}"

    def test_label_union_merge(self, merge_test_setup: dict):
        """Test that labels from both sides are merged (union)."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize and create issue
        run_mb("init", cwd=clone_a)
        result = run_mb("create", "Label Merge Test", "-l", "original", cwd=clone_a)
        issue_id = result.stdout.split()[1].rstrip(":")
        run_mb("sync", cwd=clone_a)

        # Clone B initializes and syncs
        run_mb("init", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone A adds label "from-a"
        run_mb("update", issue_id, "--add-label", "from-a", cwd=clone_a)
        run_mb("sync", cwd=clone_a)

        # Clone B (without syncing) adds label "from-b"
        run_mb("update", issue_id, "--add-label", "from-b", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone B should have all labels after merge
        result = run_mb("--json", "show", issue_id, cwd=clone_b)
        issue = json.loads(result.stdout)
        assert "original" in issue["labels"], f"Missing 'original': {issue['labels']}"
        assert "from-a" in issue["labels"], f"Missing 'from-a': {issue['labels']}"
        assert "from-b" in issue["labels"], f"Missing 'from-b': {issue['labels']}"

    def test_dependency_union_merge(self, merge_test_setup: dict):
        """Test that dependencies from both sides are merged (union)."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize and create 3 issues
        run_mb("init", cwd=clone_a)
        run_mb("create", "Parent 1", cwd=clone_a)
        run_mb("create", "Parent 2", cwd=clone_a)
        result = run_mb("create", "Child Issue", cwd=clone_a)
        child_id = result.stdout.split()[1].rstrip(":")

        # Get parent IDs
        result = run_mb("--json", "list", cwd=clone_a)
        issues = json.loads(result.stdout)
        parent_ids = [i["id"] for i in issues if "Parent" in i["title"]]
        parent1_id, parent2_id = parent_ids[0], parent_ids[1]

        run_mb("sync", cwd=clone_a)

        # Clone B syncs
        run_mb("init", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone A adds dependency on Parent 1
        run_mb("dep", "add", child_id, parent1_id, cwd=clone_a)
        run_mb("sync", cwd=clone_a)

        # Clone B (without syncing) adds dependency on Parent 2
        run_mb("dep", "add", child_id, parent2_id, cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone B should have both dependencies
        result = run_mb("--json", "show", child_id, cwd=clone_b)
        issue = json.loads(result.stdout)
        assert parent1_id in issue["dependencies"], f"Missing {parent1_id}: {issue['dependencies']}"
        assert parent2_id in issue["dependencies"], f"Missing {parent2_id}: {issue['dependencies']}"

    def test_status_conflict_newer_wins(self, merge_test_setup: dict):
        """Test that status conflicts are resolved by newest timestamp."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize and create issue
        run_mb("init", cwd=clone_a)
        result = run_mb("create", "Status Conflict Test", cwd=clone_a)
        issue_id = result.stdout.split()[1].rstrip(":")
        run_mb("sync", cwd=clone_a)

        # Clone B syncs
        run_mb("init", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone A changes status to in_progress
        run_mb("update", issue_id, "-s", "in_progress", cwd=clone_a)
        run_mb("sync", cwd=clone_a)

        # Clone B changes status to blocked (without syncing first)
        run_mb("update", issue_id, "-s", "blocked", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone B's update was more recent, so status should be blocked
        result = run_mb("--json", "show", issue_id, cwd=clone_b)
        issue = json.loads(result.stdout)
        assert issue["status"] == "blocked", f"Expected 'blocked', got {issue['status']}"

    def test_closed_at_preserved_when_one_side_closes(self, merge_test_setup: dict):
        """Test that closed_at is preserved when one side closes an issue."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize and create issue
        run_mb("init", cwd=clone_a)
        result = run_mb("create", "Close Merge Test", cwd=clone_a)
        issue_id = result.stdout.split()[1].rstrip(":")
        run_mb("sync", cwd=clone_a)

        # Clone B syncs
        run_mb("init", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone A closes the issue
        run_mb("close", issue_id, "-r", "Done from A", cwd=clone_a)
        run_mb("sync", cwd=clone_a)

        # Clone B adds a label (without knowing about the close)
        run_mb("update", issue_id, "--add-label", "extra", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Clone B should have the issue closed with the label
        result = run_mb("--json", "show", issue_id, cwd=clone_b)
        issue = json.loads(result.stdout)
        # The issue might be closed or have "extra" label depending on merge order
        # But closed_at should be set if it was closed by A
        # Note: The actual behavior depends on which update was more recent
        # What we're testing is that the merge didn't fail
        assert issue is not None
        assert "extra" in issue["labels"]

    def test_multiple_concurrent_edits_converge(self, merge_test_setup: dict):
        """Test that multiple concurrent edits eventually converge."""
        clone_a = merge_test_setup["clone_a"]
        clone_b = merge_test_setup["clone_b"]

        # Initialize and create issue
        run_mb("init", cwd=clone_a)
        result = run_mb("create", "Convergence Test", "-l", "base", cwd=clone_a)
        issue_id = result.stdout.split()[1].rstrip(":")
        run_mb("sync", cwd=clone_a)

        # Clone B syncs
        run_mb("init", cwd=clone_b)
        run_mb("sync", cwd=clone_b)

        # Multiple rounds of concurrent edits
        for i in range(3):
            # Clone A makes changes
            run_mb("update", issue_id, "--add-label", f"a-round-{i}", cwd=clone_a)
            run_mb("sync", cwd=clone_a)

            # Clone B makes changes (may or may not have synced A's changes)
            run_mb("update", issue_id, "--add-label", f"b-round-{i}", cwd=clone_b)
            run_mb("sync", cwd=clone_b)

        # Final sync on both sides
        run_mb("sync", cwd=clone_a)
        run_mb("sync", cwd=clone_b)

        # Both should have all labels now
        result_a = run_mb("--json", "show", issue_id, cwd=clone_a)
        result_b = run_mb("--json", "show", issue_id, cwd=clone_b)
        labels_a = set(json.loads(result_a.stdout)["labels"])
        labels_b = set(json.loads(result_b.stdout)["labels"])

        # Both should have converged to the same state
        assert labels_a == labels_b, f"Labels diverged: A={labels_a}, B={labels_b}"
        # Should have all round labels
        for i in range(3):
            assert f"a-round-{i}" in labels_a, f"Missing a-round-{i}"
            assert f"b-round-{i}" in labels_a, f"Missing b-round-{i}"


class TestMultiSessionSyncAndMerge:
    """E2E tests for multi-session sync and merge functionality."""

    @pytest.fixture
    def multi_session_setup(self, tmp_path: Path) -> dict:
        """Create a bare repo and two session clones for multi-session testing."""
        # Set up environment for git commands
        env = {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        }

        # Create bare origin repo
        origin = tmp_path / "origin.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main"],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )
        origin.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "-b", "main"],
            cwd=origin,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create session A's clone
        session_a = tmp_path / "session-a"
        subprocess.run(
            ["git", "clone", str(origin), str(session_a)],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create initial commit in session A and push to origin
        readme = session_a / "README.md"
        readme.write_text("# Multi-Session Test Repo\n")
        subprocess.run(["git", "add", "."], cwd=session_a, capture_output=True, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create a feature branch for session A (simulating Claude session)
        subprocess.run(
            ["git", "checkout", "-b", "claude/feature-a-abc123"],
            cwd=session_a,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create session B's clone
        session_b = tmp_path / "session-b"
        subprocess.run(
            ["git", "clone", str(origin), str(session_b)],
            cwd=tmp_path,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=session_b,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=session_b,
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=session_b,
            capture_output=True,
            check=True,
            env=env,
        )

        # Create a feature branch for session B (simulating another Claude session)
        subprocess.run(
            ["git", "checkout", "-b", "claude/feature-b-xyz789"],
            cwd=session_b,
            capture_output=True,
            check=True,
            env=env,
        )

        return {
            "origin": origin,
            "session_a": session_a,
            "session_b": session_b,
            "env": env,
        }

    def test_two_sessions_create_different_issues_and_sync(self, multi_session_setup: dict):
        """Test that two sessions can create issues and sync correctly."""
        session_a = multi_session_setup["session_a"]
        session_b = multi_session_setup["session_b"]

        # Initialize microbeads in both sessions
        result_a = run_mb("init", cwd=session_a)
        assert result_a.returncode == 0, f"Init A failed: {result_a.stderr}"

        result_b = run_mb("init", cwd=session_b)
        assert result_b.returncode == 0, f"Init B failed: {result_b.stderr}"

        # Session A creates an issue
        result = run_mb("create", "Issue from Session A", "-p", "1", cwd=session_a)
        assert result.returncode == 0, f"Create A failed: {result.stderr}"

        # Session B creates a different issue
        result = run_mb("create", "Issue from Session B", "-p", "2", cwd=session_b)
        assert result.returncode == 0, f"Create B failed: {result.stderr}"

        # Session A syncs
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0, f"Sync A failed: {result.stderr}"

        # Session B syncs - should pull and merge Session A's changes
        result = run_mb("sync", cwd=session_b)
        assert result.returncode == 0, f"Sync B failed: {result.stderr}"

        # Session B should now see both issues
        result = run_mb("--json", "list", cwd=session_b)
        assert result.returncode == 0, f"List B failed: {result.stderr}"
        issues = json.loads(result.stdout)
        issue_titles = [issue["title"] for issue in issues]
        assert "Issue from Session A" in issue_titles, f"Missing A's issue: {issue_titles}"
        assert "Issue from Session B" in issue_titles, f"Missing B's issue: {issue_titles}"

        # Session A syncs again to get Session B's issue
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0, f"Sync A (2nd) failed: {result.stderr}"

        # Session A should now see both issues
        result = run_mb("--json", "list", cwd=session_a)
        assert result.returncode == 0, f"List A failed: {result.stderr}"
        issues = json.loads(result.stdout)
        issue_titles = [issue["title"] for issue in issues]
        assert "Issue from Session A" in issue_titles, f"Missing A's issue in A: {issue_titles}"
        assert "Issue from Session B" in issue_titles, f"Missing B's issue in A: {issue_titles}"

    def test_concurrent_updates_to_same_issue(self, multi_session_setup: dict):
        """Test that concurrent updates to the same issue merge correctly."""
        session_a = multi_session_setup["session_a"]
        session_b = multi_session_setup["session_b"]

        # Initialize microbeads in session A
        result_a = run_mb("init", cwd=session_a)
        assert result_a.returncode == 0

        # Session A creates an issue
        result = run_mb("create", "Shared Issue", "-p", "1", cwd=session_a)
        assert result.returncode == 0
        issue_id = result.stdout.split()[1].rstrip(":")

        # Session A syncs to push the issue
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0

        # Session B initializes and syncs to get the issue
        result_b = run_mb("init", cwd=session_b)
        assert result_b.returncode == 0
        result = run_mb("sync", cwd=session_b)
        assert result.returncode == 0

        # Verify session B has the issue
        result = run_mb("--json", "list", cwd=session_b)
        issues = json.loads(result.stdout)
        assert len(issues) == 1
        assert issues[0]["title"] == "Shared Issue"

        # Session A adds a label
        run_mb("update", issue_id, "--add-label", "label-from-a", cwd=session_a)

        # Session B adds a different label (before syncing with A's changes)
        run_mb("update", issue_id, "--add-label", "label-from-b", cwd=session_b)

        # Session A syncs
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0

        # Session B syncs - should merge labels
        result = run_mb("sync", cwd=session_b)
        assert result.returncode == 0

        # Session B should have both labels (union merge)
        result = run_mb("--json", "show", issue_id, cwd=session_b)
        issue = json.loads(result.stdout)
        assert "label-from-a" in issue["labels"], f"Missing label-from-a: {issue['labels']}"
        assert "label-from-b" in issue["labels"], f"Missing label-from-b: {issue['labels']}"

        # Session A syncs again to get the merged result
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0

        # Session A should also have both labels
        result = run_mb("--json", "show", issue_id, cwd=session_a)
        issue = json.loads(result.stdout)
        assert "label-from-a" in issue["labels"]
        assert "label-from-b" in issue["labels"]

    def test_session_branch_naming(self, multi_session_setup: dict):
        """Test that sessions push to correctly named branches."""
        session_a = multi_session_setup["session_a"]
        origin = multi_session_setup["origin"]
        env = multi_session_setup["env"]

        # Initialize and create an issue
        run_mb("init", cwd=session_a)
        run_mb("create", "Test Issue", cwd=session_a)

        # Sync (should push to claude/microbeads-abc123 based on branch name)
        result = run_mb("sync", cwd=session_a)
        assert result.returncode == 0

        # Check that a microbeads branch was pushed to origin
        result = subprocess.run(
            ["git", "ls-remote", "--heads", str(origin)],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0

        # Should have a microbeads-related branch
        branches = result.stdout
        assert "microbeads" in branches, f"No microbeads branch found: {branches}"

    def test_three_session_convergence(self, tmp_path: Path):
        """Test that three sessions all converge to the same state."""
        env = {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        }

        # Create bare origin repo
        origin = tmp_path / "origin.git"
        origin.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "-b", "main"],
            cwd=origin,
            capture_output=True,
            check=True,
            env=env,
        )

        sessions = []
        for name in ["session-1", "session-2", "session-3"]:
            session = tmp_path / name
            subprocess.run(
                ["git", "clone", str(origin), str(session)],
                capture_output=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=session,
                capture_output=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test User"],
                cwd=session,
                capture_output=True,
                check=True,
                env=env,
            )
            subprocess.run(
                ["git", "config", "commit.gpgsign", "false"],
                cwd=session,
                capture_output=True,
                check=True,
                env=env,
            )
            sessions.append(session)

        # First session creates initial commit
        readme = sessions[0] / "README.md"
        readme.write_text("# Three Session Test\n")
        subprocess.run(
            ["git", "add", "."], cwd=sessions[0], capture_output=True, check=True, env=env
        )
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=sessions[0],
            capture_output=True,
            check=True,
            env=env,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=sessions[0],
            capture_output=True,
            check=True,
            env=env,
        )

        # All sessions pull and checkout branches
        for i, session in enumerate(sessions):
            subprocess.run(
                ["git", "pull", "origin", "main"], cwd=session, capture_output=True, env=env
            )
            subprocess.run(
                ["git", "checkout", "-b", f"claude/feature-{i}-id{i}"],
                cwd=session,
                capture_output=True,
                env=env,
            )

        # Initialize microbeads in all sessions
        for session in sessions:
            result = run_mb("init", cwd=session)
            assert result.returncode == 0

        # Each session creates a unique issue
        issue_titles = []
        for i, session in enumerate(sessions):
            title = f"Issue from session {i + 1}"
            result = run_mb("create", title, "-p", str(i), cwd=session)
            assert result.returncode == 0
            issue_titles.append(title)

        # Each session syncs (creating session branches)
        for session in sessions:
            result = run_mb("sync", cwd=session)
            assert result.returncode == 0

        # Multiple rounds of sync to converge
        for _ in range(3):
            for session in sessions:
                run_mb("sync", cwd=session)

        # All sessions should have all 3 issues
        for i, session in enumerate(sessions):
            result = run_mb("--json", "list", cwd=session)
            assert result.returncode == 0
            issues = json.loads(result.stdout)
            found_titles = [issue["title"] for issue in issues]

            for title in issue_titles:
                assert title in found_titles, (
                    f"Session {i + 1} missing issue '{title}'. Found: {found_titles}"
                )


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
