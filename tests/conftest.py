"""Pytest configuration and shared fixtures."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()

    # Set up environment for git commands to ensure they work in CI
    env = {
        "GIT_AUTHOR_NAME": "Test User",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test User",
        "GIT_COMMITTER_EMAIL": "test@test.com",
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
    }

    # Initialize git repo with initial branch name
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True, env=env
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    )
    # Disable commit signing for tests
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    )

    # Create initial commit
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
        env=env,
    )

    return repo


@pytest.fixture
def mock_worktree(tmp_path: Path) -> Path:
    """Create a mock worktree directory for testing issues without full git setup."""
    worktree = tmp_path / "mock-worktree"
    worktree.mkdir()

    # Create the microbeads directory structure
    beads_dir = worktree / ".microbeads"
    beads_dir.mkdir()
    issues_dir = beads_dir / "issues"
    issues_dir.mkdir()

    # Create active and closed subdirectories
    (issues_dir / "active").mkdir()
    (issues_dir / "closed").mkdir()

    # Create metadata file
    metadata = {"version": "0.1.0", "id_prefix": "test"}
    (beads_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    return worktree


@pytest.fixture
def mock_worktree_with_cache(tmp_path: Path) -> Path:
    """Create a mock worktree with cache support for testing disk cache.

    This fixture simulates the real directory structure where the worktree
    is at .git/microbeads-worktree/ so the disk cache can be created.
    """
    # Create .git directory (simulating real repo structure)
    git_dir = tmp_path / ".git"
    git_dir.mkdir()

    # Create the worktree inside .git like the real implementation
    worktree = git_dir / "microbeads-worktree"
    worktree.mkdir()

    # Create the microbeads directory structure
    beads_dir = worktree / ".microbeads"
    beads_dir.mkdir()
    issues_dir = beads_dir / "issues"
    issues_dir.mkdir()

    # Create active and closed subdirectories
    (issues_dir / "active").mkdir()
    (issues_dir / "closed").mkdir()

    # Create metadata file
    metadata = {"version": "0.1.0", "id_prefix": "test"}
    (beads_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    return worktree
