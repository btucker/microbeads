"""Git repository and orphan branch management."""

import subprocess
from pathlib import Path

BRANCH_NAME = "microbeads"
WORKTREE_DIR = ".git/microbeads-worktree"
BEADS_DIR = ".microbeads"
ISSUES_DIR = ".microbeads/issues"


def run_git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result


def find_repo_root(start: Path | None = None) -> Path | None:
    """Find the root of the git repository."""
    if start is None:
        start = Path.cwd()

    result = run_git("rev-parse", "--show-toplevel", cwd=start, check=False)
    if result.returncode == 0:
        return Path(result.stdout.strip())
    return None


def get_worktree_path(repo_root: Path) -> Path:
    """Get the path to the microbeads worktree."""
    return repo_root / WORKTREE_DIR


def get_beads_path(worktree: Path) -> Path:
    """Get the path to the .microbeads directory in the worktree."""
    return worktree / BEADS_DIR


def get_issues_path(worktree: Path) -> Path:
    """Get the path to the issues directory in the worktree."""
    return worktree / ISSUES_DIR


def derive_prefix(repo_root: Path) -> str:
    """Derive an issue ID prefix from the repository name.

    Takes first letters of each word, or first 2-3 chars if single word.
    Examples: "my-project" -> "mp", "microbeads" -> "mb", "foo_bar_baz" -> "fbb"
    """
    name = repo_root.name.lower()
    # Split on common separators
    parts = name.replace("-", "_").replace(".", "_").split("_")
    parts = [p for p in parts if p]  # Remove empty

    if len(parts) > 1:
        # Multi-word: take first letter of each
        prefix = "".join(p[0] for p in parts[:4])
    else:
        # Single word: take first 2 chars
        prefix = name[:2]

    return prefix


def get_prefix(worktree: Path) -> str:
    """Get the issue ID prefix from metadata."""
    import json
    metadata_path = get_beads_path(worktree) / "metadata.json"
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
        return metadata.get("id_prefix", "bd")
    return "bd"


def is_initialized(repo_root: Path) -> bool:
    """Check if microbeads is initialized in this repo."""
    worktree = get_worktree_path(repo_root)
    return worktree.exists() and (worktree / BEADS_DIR).exists()


def branch_exists(repo_root: Path, branch: str = BRANCH_NAME) -> bool:
    """Check if the microbeads branch exists."""
    result = run_git("rev-parse", "--verify", f"refs/heads/{branch}", cwd=repo_root, check=False)
    return result.returncode == 0


def remote_branch_exists(repo_root: Path, branch: str = BRANCH_NAME, remote: str = "origin") -> bool:
    """Check if the remote branch exists."""
    result = run_git("ls-remote", "--heads", remote, branch, cwd=repo_root, check=False)
    return result.returncode == 0 and branch in result.stdout


def init(repo_root: Path) -> Path:
    """Initialize microbeads in the repository.

    Creates an orphan branch and sets up a worktree.
    Returns the path to the worktree.
    """
    worktree = get_worktree_path(repo_root)

    if is_initialized(repo_root):
        return worktree

    # Check if branch exists (locally or remotely)
    if branch_exists(repo_root):
        # Branch exists locally, just set up worktree
        run_git("worktree", "add", str(worktree), BRANCH_NAME, cwd=repo_root)
    elif remote_branch_exists(repo_root):
        # Branch exists on remote, fetch and create worktree
        run_git("fetch", "origin", BRANCH_NAME, cwd=repo_root)
        run_git("worktree", "add", str(worktree), BRANCH_NAME, cwd=repo_root)
    else:
        # Create new orphan branch
        # First create a temporary worktree for the orphan branch
        run_git("worktree", "add", "--detach", str(worktree), cwd=repo_root)

        # Switch to orphan branch in worktree
        run_git("checkout", "--orphan", BRANCH_NAME, cwd=worktree)

        # Remove all files from the orphan branch
        run_git("rm", "-rf", "--cached", ".", cwd=worktree, check=False)

        # Remove actual files (except .git which is a file pointing to main repo)
        for item in worktree.iterdir():
            if item.name != ".git":
                if item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                else:
                    item.unlink()

        # Create the microbeads directory structure
        issues_dir = get_issues_path(worktree)
        issues_dir.mkdir(parents=True, exist_ok=True)

        # Create metadata file
        import json
        prefix = derive_prefix(repo_root)
        metadata = {
            "version": "0.1.0",
            "id_prefix": prefix
        }
        metadata_path = get_beads_path(worktree) / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")

        # Create .gitattributes for JSON merge driver
        gitattributes = worktree / ".gitattributes"
        gitattributes.write_text("*.json merge=microbeads-json\n")

        # Initial commit
        run_git("add", ".", cwd=worktree)
        run_git("commit", "-m", "Initialize microbeads", cwd=worktree)

        # Push the new branch
        result = run_git("push", "-u", "origin", BRANCH_NAME, cwd=worktree, check=False)
        if result.returncode != 0 and "does not appear to be a git repository" not in result.stderr:
            # Only raise if it's not a "no remote" error
            if "403" not in result.stderr and "rejected" not in result.stderr:
                raise RuntimeError(f"Push failed: {result.stderr}")

    # Configure the JSON merge driver in the main repo
    configure_merge_driver(repo_root)

    return worktree


def configure_merge_driver(repo_root: Path) -> None:
    """Configure the JSON merge driver in git config."""
    # Check if already configured
    result = run_git("config", "--get", "merge.microbeads-json.driver", cwd=repo_root, check=False)
    if result.returncode == 0:
        return

    # Configure the merge driver
    run_git("config", "merge.microbeads-json.name", "Microbeads JSON merge driver", cwd=repo_root)
    run_git("config", "merge.microbeads-json.driver", "bd merge-driver %O %A %B", cwd=repo_root)


def ensure_worktree(repo_root: Path) -> Path:
    """Ensure the worktree exists and return its path."""
    worktree = get_worktree_path(repo_root)

    if not worktree.exists():
        if branch_exists(repo_root) or remote_branch_exists(repo_root):
            # Re-create worktree from existing branch
            if remote_branch_exists(repo_root) and not branch_exists(repo_root):
                run_git("fetch", "origin", BRANCH_NAME, cwd=repo_root)
            run_git("worktree", "add", str(worktree), BRANCH_NAME, cwd=repo_root)
        else:
            raise RuntimeError("Microbeads is not initialized. Run 'mb init' first.")

    return worktree


def _sync_from_remote_microbeads(worktree: Path, current_session_id: str) -> list[str]:
    """Fetch and merge any existing microbeads branches to stay in sync.

    Looks for:
    1. origin/microbeads (canonical branch)
    2. origin/claude/microbeads-* (session branches from other sessions)

    Merges them into the local microbeads branch so all sessions share state.
    Returns list of stale branches that were merged (candidates for cleanup).
    """
    # Fetch all remote refs
    run_git("fetch", "origin", cwd=worktree, check=False)

    # Get list of remote microbeads branches
    result = run_git("ls-remote", "--heads", "origin", cwd=worktree, check=False)
    if result.returncode != 0:
        return []

    remote_branches = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        _, ref = line.split("\t", 1)
        branch = ref.replace("refs/heads/", "")
        # Look for microbeads or claude/microbeads-* branches
        if branch == BRANCH_NAME or branch.startswith(f"claude/{BRANCH_NAME}-"):
            remote_branches.append(branch)

    # Merge each remote branch (skip our own session)
    our_branch = f"claude/{BRANCH_NAME}-{current_session_id}"
    merged_branches = []
    for branch in remote_branches:
        if branch == our_branch:
            continue  # Skip our own session branch
        if branch == BRANCH_NAME:
            continue  # Don't delete canonical branch

        # Try to merge (allow conflicts to be auto-resolved by merge driver)
        result = run_git(
            "pull", "--no-edit", "origin", branch,
            cwd=worktree, check=False
        )
        if result.returncode == 0:
            merged_branches.append(branch)
        elif "CONFLICT" not in result.stdout:
            run_git("merge", "--abort", cwd=worktree, check=False)

    return merged_branches


def _cleanup_stale_branches(worktree: Path, branches: list[str]) -> None:
    """Delete stale remote branches that have been merged."""
    for branch in branches:
        # Delete remote branch
        result = run_git(
            "push", "origin", "--delete", branch,
            cwd=worktree, check=False
        )
        # Ignore errors (might not have permission, branch might be gone, etc.)


def sync(repo_root: Path, message: str | None = None) -> None:
    """Commit and push changes to the microbeads branch."""
    worktree = ensure_worktree(repo_root)

    # Check for changes
    result = run_git("status", "--porcelain", cwd=worktree)
    if not result.stdout.strip():
        return  # No changes

    # Stage all changes
    run_git("add", ".", cwd=worktree)

    # Commit
    commit_msg = message or "Update issues"
    run_git("commit", "-m", commit_msg, cwd=worktree)

    # Determine push target - detect Claude Code web environment
    push_target = BRANCH_NAME
    session_id = None
    current = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=False)
    if current.returncode == 0:
        branch = current.stdout.strip()
        # If on a claude/* branch, use session-compatible naming
        if branch.startswith("claude/") and "-" in branch:
            session_id = branch.rsplit("-", 1)[-1]
            push_target = f"claude/{BRANCH_NAME}-{session_id}"

    # Fetch and merge any existing microbeads branches to stay in sync
    stale_branches = []
    if session_id:
        stale_branches = _sync_from_remote_microbeads(worktree, session_id)

    # Push (try to push, don't fail if remote doesn't exist or permission denied)
    result = run_git("push", "-u", "origin", f"{BRANCH_NAME}:{push_target}", cwd=worktree, check=False)
    push_succeeded = False
    if result.returncode != 0:
        # Check if it's because remote doesn't exist or permission issue
        if "does not appear to be a git repository" in result.stderr:
            pass  # No remote configured, that's OK
        elif "has no upstream branch" in result.stderr:
            # First push, set upstream
            run_git("push", "--set-upstream", "origin", f"{BRANCH_NAME}:{push_target}", cwd=worktree)
            push_succeeded = True
        elif "403" in result.stderr or "Permission denied" in result.stderr:
            pass  # Permission issue, skip push silently
        else:
            raise RuntimeError(f"Push failed: {result.stderr}")
    else:
        push_succeeded = True

    # Clean up stale branches after successful push
    if push_succeeded and stale_branches:
        _cleanup_stale_branches(worktree, stale_branches)
