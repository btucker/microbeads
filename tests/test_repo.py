"""Tests for repository management functionality."""

from pathlib import Path
from unittest.mock import patch

import pytest

from microbeads import _is_dogfooding, get_command_name
from microbeads.repo import (
    BEADS_DIR,
    ISSUES_DIR,
    WORKTREE_DIR,
    branch_exists,
    derive_prefix,
    find_repo_root,
    get_beads_path,
    get_git_common_dir,
    get_issues_path,
    get_mode,
    get_prefix,
    get_worktree_path,
    is_initialized,
    run_git,
)


class TestRunGit:
    """Tests for git command execution."""

    def test_run_git_success(self, temp_git_repo: Path):
        """Test running a successful git command."""
        result = run_git("status", cwd=temp_git_repo)
        assert result.returncode == 0

    def test_run_git_failure_raises(self, temp_git_repo: Path):
        """Test that failed git command raises error."""
        with pytest.raises(RuntimeError, match="failed"):
            run_git("invalid-command", cwd=temp_git_repo)

    def test_run_git_failure_no_check(self, temp_git_repo: Path):
        """Test that check=False doesn't raise."""
        result = run_git("invalid-command", cwd=temp_git_repo, check=False)
        assert result.returncode != 0


class TestFindRepoRoot:
    """Tests for repository root detection."""

    def test_find_repo_root_at_root(self, temp_git_repo: Path):
        """Test finding root when at root."""
        root = find_repo_root(temp_git_repo)
        assert root == temp_git_repo

    def test_find_repo_root_subdirectory(self, temp_git_repo: Path):
        """Test finding root from subdirectory."""
        subdir = temp_git_repo / "subdir"
        subdir.mkdir()

        root = find_repo_root(subdir)
        assert root == temp_git_repo

    def test_find_repo_root_not_repo(self, tmp_path: Path):
        """Test finding root in non-repo directory."""
        root = find_repo_root(tmp_path)
        assert root is None


class TestPathHelpers:
    """Tests for path helper functions."""

    def test_get_worktree_path(self, temp_git_repo: Path):
        """Test worktree path calculation."""
        path = get_worktree_path(temp_git_repo)
        assert path == temp_git_repo / WORKTREE_DIR

    def test_get_beads_path(self, tmp_path: Path):
        """Test beads path calculation."""
        path = get_beads_path(tmp_path)
        assert path == tmp_path / BEADS_DIR

    def test_get_issues_path(self, tmp_path: Path):
        """Test issues path calculation."""
        path = get_issues_path(tmp_path)
        assert path == tmp_path / ISSUES_DIR


class TestDerivePrefix:
    """Tests for issue ID prefix derivation."""

    def test_derive_prefix_multi_word_hyphen(self, tmp_path: Path):
        """Test prefix from hyphenated name."""
        repo = tmp_path / "my-test-project"
        repo.mkdir()
        prefix = derive_prefix(repo)
        assert prefix == "mtp"

    def test_derive_prefix_multi_word_underscore(self, tmp_path: Path):
        """Test prefix from underscored name."""
        repo = tmp_path / "foo_bar_baz"
        repo.mkdir()
        prefix = derive_prefix(repo)
        assert prefix == "fbb"

    def test_derive_prefix_single_word(self, tmp_path: Path):
        """Test prefix from single word name."""
        repo = tmp_path / "microbeads"
        repo.mkdir()
        prefix = derive_prefix(repo)
        assert prefix == "mi"

    def test_derive_prefix_short_name(self, tmp_path: Path):
        """Test prefix from short name."""
        repo = tmp_path / "ab"
        repo.mkdir()
        prefix = derive_prefix(repo)
        assert prefix == "ab"

    def test_derive_prefix_max_parts(self, tmp_path: Path):
        """Test prefix limits to 4 parts."""
        repo = tmp_path / "a-b-c-d-e-f"
        repo.mkdir()
        prefix = derive_prefix(repo)
        assert prefix == "abcd"


class TestGetPrefix:
    """Tests for prefix retrieval from metadata."""

    def test_get_prefix_from_metadata(self, mock_worktree: Path):
        """Test reading prefix from metadata."""
        prefix = get_prefix(mock_worktree)
        assert prefix == "test"

    def test_get_prefix_default(self, tmp_path: Path):
        """Test default prefix when no metadata."""
        prefix = get_prefix(tmp_path)
        assert prefix == "bd"


class TestBranchExists:
    """Tests for branch existence checks."""

    def test_branch_exists_main(self, temp_git_repo: Path):
        """Test detecting existing branch."""
        # main or master should exist
        result = branch_exists(temp_git_repo, "master") or branch_exists(temp_git_repo, "main")
        assert result

    def test_branch_exists_nonexistent(self, temp_git_repo: Path):
        """Test detecting non-existent branch."""
        assert not branch_exists(temp_git_repo, "nonexistent-branch")


class TestIsInitialized:
    """Tests for initialization detection."""

    def test_is_initialized_false(self, temp_git_repo: Path):
        """Test detection of uninitialized repo."""
        assert not is_initialized(temp_git_repo)

    def test_is_initialized_true(self, temp_git_repo: Path):
        """Test detection of initialized repo."""
        worktree = get_worktree_path(temp_git_repo)
        worktree.mkdir(parents=True)
        beads_dir = worktree / BEADS_DIR
        beads_dir.mkdir()

        assert is_initialized(temp_git_repo)


class TestIsDogfooding:
    """Tests for _is_dogfooding helper."""

    def test_returns_true_in_microbeads_repo(self, tmp_path: Path):
        """Test that True is returned when in microbeads repo."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "microbeads"\n')

        with patch("microbeads.Path.cwd", return_value=tmp_path):
            assert _is_dogfooding() is True

    def test_returns_true_in_subdirectory(self, tmp_path: Path):
        """Test that True is returned when in a subdirectory of microbeads repo."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "microbeads"\n')
        subdir = tmp_path / "src" / "microbeads"
        subdir.mkdir(parents=True)

        with patch("microbeads.Path.cwd", return_value=subdir):
            assert _is_dogfooding() is True

    def test_returns_false_for_other_project(self, tmp_path: Path):
        """Test that False is returned for non-microbeads projects."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "other-project"\n')

        with patch("microbeads.Path.cwd", return_value=tmp_path):
            assert _is_dogfooding() is False

    def test_returns_false_when_no_pyproject(self, tmp_path: Path):
        """Test that False is returned when no pyproject.toml exists."""
        with patch("microbeads.Path.cwd", return_value=tmp_path):
            assert _is_dogfooding() is False


class TestGetCommandName:
    """Tests for get_command_name utility."""

    def test_returns_uv_run_mb_when_dogfooding(self):
        """Test that 'uv run mb' is returned when in microbeads repo."""
        with patch("microbeads._is_dogfooding", return_value=True):
            assert get_command_name() == "uv run mb"

    def test_returns_mb_when_invoked_as_mb(self):
        """Test that mb is returned when invoked as mb."""
        with patch("microbeads._is_dogfooding", return_value=False):
            with patch("microbeads.sys.argv", ["/usr/bin/mb", "list"]):
                with patch("shutil.which", return_value=None):
                    assert get_command_name() == "mb"

    def test_returns_mb_when_in_path(self):
        """Test that mb is returned when available in PATH."""
        with patch("microbeads._is_dogfooding", return_value=False):
            with patch("microbeads.sys.argv", ["/some/other/script", "list"]):
                with patch("shutil.which", return_value="/usr/local/bin/mb"):
                    assert get_command_name() == "mb"

    def test_returns_uvx_when_mb_not_available(self):
        """Test fallback to uvx microbeads when mb not available."""
        with patch("microbeads._is_dogfooding", return_value=False):
            with patch("microbeads.sys.argv", ["/some/script", "list"]):
                with patch("shutil.which", return_value=None):
                    assert get_command_name() == "uvx microbeads"


class TestGetGitCommonDir:
    """Tests for git common directory detection (worktree support)."""

    def test_get_git_common_dir_normal_repo(self, temp_git_repo: Path):
        """Test that common dir is .git for normal repos."""
        common = get_git_common_dir(temp_git_repo)
        assert common == temp_git_repo / ".git"

    def test_get_git_common_dir_returns_absolute(self, temp_git_repo: Path):
        """Test that common dir path is always absolute."""
        common = get_git_common_dir(temp_git_repo)
        assert common.is_absolute()


class TestStealthMode:
    """Tests for stealth mode functionality."""

    def test_get_mode_returns_stealth(self, mock_worktree: Path):
        """Test that get_mode returns 'stealth' when metadata specifies it."""
        import json

        metadata_path = mock_worktree / ".microbeads" / "metadata.json"
        metadata = {"version": "0.1.0", "id_prefix": "test", "mode": "stealth"}
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

        assert get_mode(mock_worktree) == "stealth"

    def test_get_mode_returns_normal_default(self, mock_worktree: Path):
        """Test that get_mode returns 'normal' when mode is not specified."""
        # mock_worktree already has metadata without mode field
        assert get_mode(mock_worktree) == "normal"

    def test_get_mode_with_explicit_normal(self, mock_worktree: Path):
        """Test that get_mode returns 'normal' when explicitly set."""
        import json

        metadata_path = mock_worktree / ".microbeads" / "metadata.json"
        metadata = {"version": "0.1.0", "id_prefix": "test", "mode": "normal"}
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

        assert get_mode(mock_worktree) == "normal"


class TestContributorMode:
    """Tests for contributor mode functionality."""

    def test_get_mode_returns_contributor(self, mock_worktree: Path):
        """Test that get_mode returns 'contributor' when metadata specifies it."""
        import json

        metadata_path = mock_worktree / ".microbeads" / "metadata.json"
        metadata = {
            "version": "0.1.0",
            "id_prefix": "test",
            "mode": "contributor",
            "contributor_repo": "/path/to/external/repo",
        }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")

        assert get_mode(mock_worktree) == "contributor"


class TestWorktreePath:
    """Tests for worktree path calculation."""

    def test_worktree_uses_common_dir(self, temp_git_repo: Path):
        """Test that worktree path uses git common dir."""
        worktree = get_worktree_path(temp_git_repo)
        expected = temp_git_repo / ".git" / "microbeads-worktree"
        assert worktree == expected
