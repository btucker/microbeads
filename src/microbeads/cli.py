"""Command-line interface for microbeads."""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import click

from . import get_command_name, issues, repo
from .issues import CorruptedFileError, ValidationError

# Condensed workflow instructions for Claude Code hooks
PRIME_TEMPLATE = """# Microbeads Issue Tracking

**IMPORTANT:** Always create an issue for new user requests before starting work.
Run `{cmd} ready` to check for existing issues first.

## Workflow
1. Check existing issues: `{cmd} ready`
2. Create issue if new request: `{cmd} create "title" -p N -t type`
3. Start work: `{cmd} update <id> -s in_progress`
4. Complete work: `{cmd} close <id> -r "reason"`
5. Sync: `{cmd} sync`

## Commands
```
{cmd} ready                         # Issues ready to work on
{cmd} create "title" -p N -t type   # Create issue (always do this!)
{cmd} update <id> -s in_progress    # Start work
{cmd} close <id> -r "reason"        # Complete work
{cmd} dep add <child> <parent>      # Add dependency
{cmd} sync                          # Save to git
{cmd} doctor                        # Check for problems
```

## Status: open | in_progress | blocked | closed
## Priority: P0 (critical) to P4 (low)
## Types: bug | feature | task | epic | chore

## Additional Fields (optional)
--design "approach" --notes "context" --acceptance-criteria "done when..."
"""


class Context:
    """CLI context holding common state."""

    def __init__(self, json_output: bool = False):
        self.json_output = json_output
        self._repo_root = None
        self._worktree = None

    @property
    def repo_root(self):
        if self._repo_root is None:
            self._repo_root = repo.find_repo_root()
            if self._repo_root is None:
                raise click.ClickException("Not in a git repository")
        return self._repo_root

    @property
    def worktree(self):
        if self._worktree is None:
            if not repo.is_initialized(self.repo_root):
                raise click.ClickException("Microbeads is not initialized. Run 'mb init' first.")
            self._worktree = repo.ensure_worktree(self.repo_root)
        return self._worktree


pass_context = click.make_pass_decorator(Context, ensure=True)


def output(ctx: Context, data: Any, human_format: str | None = None) -> None:
    """Output data in JSON or human-readable format."""
    if ctx.json_output:
        click.echo(json.dumps(data, indent=2, sort_keys=True))
    elif human_format:
        click.echo(human_format)
    else:
        click.echo(json.dumps(data, indent=2, sort_keys=True))


def format_issue_line(issue: dict[str, Any]) -> str:
    """Format an issue as a single line for list output."""
    status_icons = {
        "open": "○",
        "in_progress": "◐",
        "blocked": "⊗",
        "closed": "●",
    }
    icon = status_icons.get(issue.get("status", "open"), "○")
    priority = issue.get("priority", 2)
    labels = ",".join(issue.get("labels", []))
    labels_str = f" [{labels}]" if labels else ""

    return f"{icon} {issue['id']} P{priority} {issue['title']}{labels_str}"


def format_issue_detail(issue: dict[str, Any]) -> str:
    """Format an issue with full details."""
    lines = [
        f"ID:          {issue['id']}",
        f"Title:       {issue['title']}",
        f"Status:      {issue.get('status', 'open')}",
        f"Priority:    P{issue.get('priority', 2)}",
        f"Type:        {issue.get('type', 'task')}",
    ]

    if issue.get("labels"):
        lines.append(f"Labels:      {', '.join(issue['labels'])}")

    if issue.get("description"):
        lines.append(f"Description: {issue['description']}")

    if issue.get("design"):
        lines.append(f"Design:      {issue['design']}")

    if issue.get("notes"):
        lines.append(f"Notes:       {issue['notes']}")

    if issue.get("acceptance_criteria"):
        lines.append(f"Acceptance:  {issue['acceptance_criteria']}")

    if issue.get("dependencies"):
        lines.append(f"Depends on:  {', '.join(issue['dependencies'])}")

    lines.append(f"Created:     {issue.get('created_at', 'unknown')}")
    lines.append(f"Updated:     {issue.get('updated_at', 'unknown')}")

    if issue.get("closed_at"):
        lines.append(f"Closed:      {issue['closed_at']}")
        if issue.get("closed_reason"):
            lines.append(f"Reason:      {issue['closed_reason']}")

    # Show history if present
    history = issue.get("history", [])
    if history:
        lines.append("\nHistory:")
        for entry in history[-10:]:  # Show last 10 entries
            field = entry.get("field", "?")
            old_val = entry.get("old", "?")
            new_val = entry.get("new", "?")
            at = entry.get("at", "?")
            lines.append(f"  {at}: {field}: {old_val} -> {new_val}")
        if len(history) > 10:
            lines.append(f"  ... and {len(history) - 10} more entries")

    return "\n".join(lines)


def format_dependency_tree(tree: dict[str, Any], indent: int = 0) -> str:
    """Format a dependency tree for display."""
    prefix = "  " * indent
    status_icons = {
        "open": "○",
        "in_progress": "◐",
        "blocked": "⊗",
        "closed": "●",
    }

    if tree.get("error"):
        return f"{prefix}└─ {tree['id']} ({tree['error']})"

    icon = status_icons.get(tree.get("status", "open"), "○")
    line = f"{prefix}{'└─ ' if indent > 0 else ''}{icon} {tree['id']}: {tree.get('title', '')}"

    lines = [line]
    for dep in tree.get("dependencies", []):
        lines.append(format_dependency_tree(dep, indent + 1))

    return "\n".join(lines)


@click.group()
@click.option("--json", "json_output", is_flag=True, help="Output in JSON format")
@click.pass_context
def main(ctx, json_output: bool):
    """Microbeads - A simplified git-backed issue tracker."""
    ctx.ensure_object(Context)
    ctx.obj.json_output = json_output


def import_from_beads(worktree, json_output: bool = False) -> int:
    """Import issues from the reference beads CLI.

    Returns the number of issues imported.
    """
    # Check if bd is available
    result = subprocess.run(["bd", "--version"], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException("'bd' (beads CLI) not found. Install it first or skip import.")

    # Get all issues from beads
    result = subprocess.run(["bd", "list", "--json", "-s", "open"], capture_output=True, text=True)
    if result.returncode != 0:
        raise click.ClickException(f"Failed to get issues from beads: {result.stderr}")

    try:
        beads_issues = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Failed to parse beads output: {result.stdout}") from exc

    imported = 0
    skipped = 0

    for beads_issue in beads_issues:
        issue_id = beads_issue.get("id")
        if not issue_id:
            continue

        # Check if already exists
        existing = issues.get_issue(worktree, issue_id)
        if existing:
            skipped += 1
            continue

        # Map beads fields to microbeads format
        issue = {
            "closed_at": beads_issue.get("closed_at"),
            "closed_reason": beads_issue.get("close_reason"),
            "created_at": beads_issue.get("created_at"),
            "dependencies": [
                d.get("depends_on")
                for d in beads_issue.get("dependencies", [])
                if d.get("depends_on")
            ],
            "description": beads_issue.get("description", ""),
            "id": issue_id,
            "labels": beads_issue.get("labels", []),
            "priority": beads_issue.get("priority", 2),
            "status": beads_issue.get("status", "open"),
            "title": beads_issue.get("title", ""),
            "type": beads_issue.get("issue_type", "task"),
            "updated_at": beads_issue.get("updated_at"),
        }

        issues.save_issue(worktree, issue)
        imported += 1

    if not json_output:
        if imported > 0:
            click.echo(f"Imported {imported} issues from beads.")
        if skipped > 0:
            click.echo(f"Skipped {skipped} existing issues.")

    return imported


def update_agents_md(repo_root: Path, json_output: bool = False) -> bool:
    """Update AGENTS.md with microbeads section.

    - Removes any existing beads section
    - Adds microbeads section if not present
    - Returns True if file was modified
    """
    agents_path = repo_root / "AGENTS.md"

    if agents_path.exists():
        content = agents_path.read_text()
    else:
        content = "# Agent Instructions\n\n"

    modified = False

    # Check if microbeads section already exists (various formats)
    if "microbeads" in content.lower() and ("mb ready" in content or "mb sync" in content):
        if not json_output:
            click.echo("AGENTS.md: microbeads section already present")
        return False

    # Remove beads section if present (matches ## Beads or ## Issue Tracking with bd commands)
    # Pattern matches section starting with ## that contains "bd " commands until next ## or end
    beads_patterns = [
        # Match "## Beads" or "## Beads Issue Tracking" section
        r"## Beads[^\n]*\n(?:(?!## ).)*",
        # Match any section containing "bd " commands (reference beads CLI)
        r"## [^\n]*\n(?:(?!## )(?:.*\bbd\s+\w+.*\n|[^\n]*\n))*(?=## |\Z)",
    ]

    for pattern in beads_patterns:
        if re.search(pattern, content, re.MULTILINE | re.DOTALL):
            # Only remove if it contains bd commands
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
            if match and "bd " in match.group(0):
                content = re.sub(pattern, "", content, flags=re.MULTILINE | re.DOTALL)
                modified = True
                if not json_output:
                    click.echo("AGENTS.md: removed beads section")

    # Clean up multiple blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Append microbeads section (reuse PRIME_TEMPLATE)
    cmd = get_command_name()
    section = PRIME_TEMPLATE.format(cmd=cmd)

    if not content.endswith("\n"):
        content += "\n"
    content += section
    modified = True

    agents_path.write_text(content)
    if not json_output:
        click.echo("AGENTS.md: added microbeads section")

    return modified


@main.command()
@click.option("--import-beads", is_flag=True, help="Import issues from existing beads installation")
@click.option("--stealth", is_flag=True, help="Local-only mode (issues not pushed to remote)")
@click.option(
    "--contributor",
    "contributor_repo",
    help="External repo path for contributor mode (keeps planning separate from PRs)",
)
@pass_context
def init(ctx: Context, import_beads: bool, stealth: bool, contributor_repo: str | None):
    """Initialize microbeads in this repository.

    By default, issues are synced to the remote repository.

    Use --stealth for local-only issue tracking (useful for experiments).
    Use --contributor to route issues to a personal/external repo.
    """
    if stealth and contributor_repo:
        raise click.ClickException("Cannot use both --stealth and --contributor")

    worktree = repo.init(ctx.repo_root, stealth=stealth, contributor_repo=contributor_repo)

    imported = 0
    if import_beads:
        imported = import_from_beads(worktree, ctx.json_output)

    # Update AGENTS.md
    update_agents_md(ctx.repo_root, ctx.json_output)

    # Auto-setup Claude hooks if Claude artifacts exist
    claude_dir = ctx.repo_root / ".claude"
    claude_md = ctx.repo_root / "CLAUDE.md"
    if claude_dir.exists() or claude_md.exists():
        if not ctx.json_output:
            click.echo("Detected Claude Code artifacts, setting up hooks...")
        settings_dir = ctx.repo_root / ".claude"
        settings_path = settings_dir / "settings.json"
        _install_claude_hooks(settings_dir, settings_path, "project")

    mode = "stealth" if stealth else ("contributor" if contributor_repo else "normal")
    mode_msg = ""
    if stealth:
        mode_msg = " (stealth mode - local only)"
    elif contributor_repo:
        mode_msg = f" (contributor mode - using {contributor_repo})"

    output(
        ctx,
        {"status": "initialized", "worktree": str(worktree), "imported": imported, "mode": mode},
        f"Microbeads initialized{mode_msg}. Issues stored on orphan branch '{repo.BRANCH_NAME}'.",
    )


@main.command()
@click.argument("title")
@click.option("-d", "--description", default="", help="Issue description")
@click.option(
    "-t",
    "--type",
    "issue_type",
    default="task",
    type=click.Choice(["bug", "feature", "task", "epic", "chore"]),
    help="Issue type",
)
@click.option(
    "-p", "--priority", default=2, type=click.IntRange(0, 4), help="Priority (0=critical, 4=low)"
)
@click.option("-l", "--label", multiple=True, help="Labels (can specify multiple)")
@click.option("--design", default="", help="Design notes or approach")
@click.option("--notes", default="", help="General notes")
@click.option(
    "--acceptance-criteria",
    "acceptance_criteria",
    default="",
    help="Acceptance criteria / definition of done",
)
@pass_context
def create(
    ctx: Context,
    title: str,
    description: str,
    issue_type: str,
    priority: int,
    label: tuple,
    design: str,
    notes: str,
    acceptance_criteria: str,
):
    """Create a new issue."""
    try:
        issue = issues.create_issue(
            title=title,
            worktree=ctx.worktree,
            description=description,
            issue_type=issues.IssueType(issue_type),
            priority=priority,
            labels=list(label) if label else None,
            design=design,
            notes=notes,
            acceptance_criteria=acceptance_criteria,
        )
        issues.save_issue(ctx.worktree, issue)
        output(ctx, issue, f"Created {issue['id']}: {title}")
    except ValidationError as e:
        raise click.ClickException(str(e)) from None


@main.command("list")
@click.option(
    "-s",
    "--status",
    type=click.Choice(["open", "in_progress", "blocked", "closed"]),
    help="Filter by status",
)
@click.option("-p", "--priority", type=click.IntRange(0, 4), help="Filter by priority")
@click.option("-l", "--label", help="Filter by label")
@click.option(
    "-t",
    "--type",
    "issue_type",
    type=click.Choice(["bug", "feature", "task", "epic", "chore"]),
    help="Filter by type",
)
@pass_context
def list_cmd(
    ctx: Context,
    status: str | None,
    priority: int | None,
    label: str | None,
    issue_type: str | None,
):
    """List issues."""
    status_enum = issues.Status(status) if status else None
    type_enum = issues.IssueType(issue_type) if issue_type else None

    result = issues.list_issues(
        ctx.worktree,
        status=status_enum,
        priority=priority,
        label=label,
        issue_type=type_enum,
    )

    if ctx.json_output:
        output(ctx, result)
    else:
        if not result:
            click.echo("No issues found.")
        else:
            for issue in result:
                click.echo(format_issue_line(issue))


@main.command()
@click.argument("issue_id")
@pass_context
def show(ctx: Context, issue_id: str):
    """Show issue details."""
    try:
        issue = issues.get_issue(ctx.worktree, issue_id)
    except CorruptedFileError as e:
        raise click.ClickException(f"Issue file is corrupted: {e.path}") from None

    if issue is None:
        raise click.ClickException(f"Issue not found: {issue_id}")

    output(ctx, issue, format_issue_detail(issue))


@main.command()
@click.argument("issue_id")
@click.option(
    "-s",
    "--status",
    type=click.Choice(["open", "in_progress", "blocked", "closed"]),
    help="Update status",
)
@click.option("-p", "--priority", type=click.IntRange(0, 4), help="Update priority")
@click.option("-t", "--title", help="Update title")
@click.option("-d", "--description", help="Update description")
@click.option("-l", "--label", multiple=True, help="Set labels (replaces existing)")
@click.option("--add-label", multiple=True, help="Add labels")
@click.option("--remove-label", multiple=True, help="Remove labels")
@click.option("--design", help="Update design notes")
@click.option("--notes", help="Update notes")
@click.option("--acceptance-criteria", "acceptance_criteria", help="Update acceptance criteria")
@pass_context
def update(
    ctx: Context,
    issue_id: str,
    status: str | None,
    priority: int | None,
    title: str | None,
    description: str | None,
    label: tuple,
    add_label: tuple,
    remove_label: tuple,
    design: str | None,
    notes: str | None,
    acceptance_criteria: str | None,
):
    """Update an issue.

    Note: When setting status to 'in_progress', automatically syncs to
    prevent race conditions with multiple agents picking up the same task.
    """
    try:
        status_enum = issues.Status(status) if status else None
        issue = issues.update_issue(
            ctx.worktree,
            issue_id,
            status=status_enum,
            priority=priority,
            title=title,
            description=description,
            labels=list(label) if label else None,
            add_labels=list(add_label) if add_label else None,
            remove_labels=list(remove_label) if remove_label else None,
            design=design,
            notes=notes,
            acceptance_criteria=acceptance_criteria,
        )
        output(ctx, issue, f"Updated {issue['id']}")

        # Auto-sync when claiming a task to prevent race conditions
        if status == "in_progress":
            repo.sync(ctx.repo_root, f"Claim {issue_id}")
            issues.clear_cache(ctx.worktree, include_disk=True)
    except (ValueError, ValidationError) as e:
        raise click.ClickException(str(e)) from None


@main.command()
@click.argument("issue_id")
@click.option("-r", "--reason", default="", help="Reason for closing")
@pass_context
def close(ctx: Context, issue_id: str, reason: str):
    """Close an issue."""
    try:
        issue = issues.close_issue(ctx.worktree, issue_id, reason)
        output(ctx, issue, f"Closed {issue['id']}")
    except ValueError as e:
        raise click.ClickException(str(e)) from None


@main.command()
@click.argument("issue_id")
@pass_context
def reopen(ctx: Context, issue_id: str):
    """Reopen a closed issue."""
    try:
        issue = issues.reopen_issue(ctx.worktree, issue_id)
        output(ctx, issue, f"Reopened {issue['id']}")
    except ValueError as e:
        raise click.ClickException(str(e)) from None


@main.command()
@pass_context
def ready(ctx: Context):
    """Show issues ready to work on (no open blockers)."""
    result = issues.get_ready_issues(ctx.worktree)

    if ctx.json_output:
        output(ctx, result)
    else:
        if not result:
            click.echo("No ready issues.")
        else:
            for issue in result:
                click.echo(format_issue_line(issue))


@main.command()
@pass_context
def blocked(ctx: Context):
    """Show issues blocked by dependencies."""
    result = issues.get_blocked_issues(ctx.worktree)

    if ctx.json_output:
        output(ctx, result)
    else:
        if not result:
            click.echo("No blocked issues.")
        else:
            for issue in result:
                blockers = issue.get("_blockers", [])
                blockers_str = f" (blocked by: {', '.join(blockers)})" if blockers else ""
                click.echo(f"{format_issue_line(issue)}{blockers_str}")


@main.group()
def dep():
    """Manage dependencies."""
    pass


@dep.command("add")
@click.argument("child_id")
@click.argument("parent_id")
@pass_context
def dep_add(ctx: Context, child_id: str, parent_id: str):
    """Add a dependency (child depends on parent)."""
    try:
        issue = issues.add_dependency(ctx.worktree, child_id, parent_id)
        output(ctx, issue, f"{issue['id']} now depends on {parent_id}")
    except (ValueError, ValidationError) as e:
        raise click.ClickException(str(e)) from None


@dep.command("rm")
@click.argument("child_id")
@click.argument("parent_id")
@pass_context
def dep_rm(ctx: Context, child_id: str, parent_id: str):
    """Remove a dependency."""
    try:
        issue = issues.remove_dependency(ctx.worktree, child_id, parent_id)
        output(ctx, issue, f"Removed dependency from {issue['id']} to {parent_id}")
    except ValueError as e:
        raise click.ClickException(str(e)) from None


@dep.command("tree")
@click.argument("issue_id")
@pass_context
def dep_tree(ctx: Context, issue_id: str):
    """Show dependency tree for an issue."""
    tree = issues.build_dependency_tree(ctx.worktree, issue_id)

    if ctx.json_output:
        output(ctx, tree)
    else:
        click.echo(format_dependency_tree(tree))


@main.command()
@pass_context
def check(ctx: Context):
    """Check for corrupted issue files."""
    issues_dir = repo.get_issues_path(ctx.worktree)

    if not issues_dir.exists():
        output(ctx, {"corrupted": [], "total": 0}, "No issues directory found.")
        return

    corrupted = []
    total = 0
    for path in issues_dir.glob("*.json"):
        total += 1
        try:
            issues.load_issue(path)
        except CorruptedFileError as e:
            corrupted.append({"id": path.stem, "path": str(path), "error": str(e.original_error)})

    if ctx.json_output:
        output(ctx, {"corrupted": corrupted, "total": total})
    elif corrupted:
        click.echo(f"Found {len(corrupted)} corrupted file(s) out of {total}:")
        for c in corrupted:
            click.echo(f"  - {c['id']}: {c['error']}")
    else:
        click.echo(f"All {total} issue file(s) are valid.")


@main.command()
@click.option("-m", "--message", help="Commit message")
@pass_context
def sync(ctx: Context, message: str | None):
    """Commit and push changes to the microbeads branch."""
    repo.sync(ctx.repo_root, message)
    # Clear cache after sync since git may have updated files
    issues.clear_cache(ctx.worktree, include_disk=True)
    output(ctx, {"status": "synced"}, "Changes synced.")


@main.command()
@click.option("--fix", is_flag=True, help="Automatically fix problems where possible")
@pass_context
def doctor(ctx: Context, fix: bool):
    """Run health checks on issues and detect problems.

    Checks for:
    - Orphaned dependencies (references to non-existent issues)
    - Stale blocked status (marked blocked but no open blockers)
    - Dependency cycles
    - Invalid field values (status, type, priority)

    Use --fix to automatically fix problems where possible.
    Note: Dependency cycles cannot be automatically fixed.
    """
    result = issues.run_doctor(ctx.worktree, fix=fix)

    if ctx.json_output:
        output(ctx, result)
        return

    total = result["total_issues"]
    problems = result["problems"]
    fixed = result["fixed"]

    click.echo(f"Checked {total} issues.")

    if fixed:
        click.echo(f"\nFixed {len(fixed)} issues:")
        for item in fixed:
            for fix_msg in item["fixes"]:
                click.echo(f"  ✓ {item['id']}: {fix_msg}")

    if problems:
        # Filter out problems that were fixed
        fixed_ids = {item["id"] for item in fixed}
        remaining = [p for p in problems if p["id"] not in fixed_ids or not fix]

        if remaining:
            click.echo(f"\nFound {len(remaining)} issues with problems:")
            for item in remaining:
                click.echo(f"  {item['id']}: {item['title']}")
                for problem in item["problems"]:
                    click.echo(f"    - {problem}")

            if not fix:
                click.echo("\nRun with --fix to automatically fix problems.")
    else:
        click.echo("No problems found.")


@main.command("merge-driver", hidden=True)
@click.argument("base_path")
@click.argument("ours_path")
@click.argument("theirs_path")
def merge_driver(base_path: str, ours_path: str, theirs_path: str):
    """Git merge driver for JSON files (internal use)."""
    from . import merge

    sys.exit(merge.merge_json_files(base_path, ours_path, theirs_path))


def _get_current_branch() -> str | None:
    """Get the current git branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _is_feature_branch(branch: str | None) -> bool:
    """Check if branch appears to be a feature/work branch."""
    if not branch:
        return False
    # Common feature branch patterns
    prefixes = ("feature/", "fix/", "bugfix/", "chore/", "claude/", "user/")
    return branch.startswith(prefixes) or "/" in branch


def _filter_related_issues(
    ready_issues: list[dict[str, Any]], branch: str | None
) -> list[dict[str, Any]]:
    """Filter issues to those related to the current branch context.

    Matches issues by:
    - Issue ID appearing in branch name
    - Issue labels matching branch name components
    """
    if not branch or not _is_feature_branch(branch):
        # On main/master, all issues are relevant
        return ready_issues

    related = []
    branch_lower = branch.lower()

    for issue in ready_issues:
        issue_id = issue.get("id", "")
        labels = issue.get("labels", [])
        title = issue.get("title", "").lower()

        # Check if issue ID is in branch name
        if issue_id.lower() in branch_lower:
            related.append(issue)
            continue

        # Check if any label matches branch components
        branch_parts = set(branch_lower.replace("-", "/").replace("_", "/").split("/"))
        for label in labels:
            if label.lower() in branch_parts:
                related.append(issue)
                break

        # Check if keywords from title are in branch
        title_words = set(title.split())
        if len(title_words & branch_parts) >= 2:
            related.append(issue)

    return related


@main.command("continue")
def continue_cmd():
    """Check for ready issues and optionally block agent from stopping.

    Designed for Claude Code Stop hooks. Reads hook input from stdin
    and outputs JSON to block stopping if there are ready issues.

    Branch-aware: On feature branches (claude/, feature/, etc.), only
    suggests issues related to that branch context. On main/master,
    suggests all ready issues.

    Returns {"decision": "block", "reason": "..."} if agent should continue,
    or exits silently to allow stopping.
    """
    # Read hook input from stdin
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, Exception):
        # If no valid input, allow stop
        sys.exit(0)

    # Prevent infinite loops - if already continuing from a stop hook, allow stop
    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    # Check if we're in a git repo with microbeads
    repo_root = repo.find_repo_root()
    if repo_root is None or not repo.is_initialized(repo_root):
        sys.exit(0)

    # Get ready issues
    worktree = repo.get_worktree_path(repo_root)
    ready_issues = issues.get_ready_issues(worktree)

    if not ready_issues:
        # No ready issues, allow stop
        sys.exit(0)

    # Filter to issues related to current branch context
    current_branch = _get_current_branch()
    related_issues = _filter_related_issues(ready_issues, current_branch)

    if not related_issues:
        # No related issues for this branch, allow stop
        # (Agent shouldn't mix unrelated work into feature branches)
        sys.exit(0)

    # Format issues for the agent
    cmd = get_command_name()
    issue_lines = []
    for issue in related_issues[:5]:  # Limit to top 5 by priority
        priority = issue.get("priority", 2)
        issue_lines.append(f"  - {issue['id']} (P{priority}): {issue['title']}")

    issues_text = "\n".join(issue_lines)
    reason = f"""There are {len(related_issues)} related issue(s) ready to work on:

{issues_text}

Please review the issues above. To continue working:
1. Run `{cmd} update <id> -s in_progress` to start the next issue
2. Work on the issue
3. Run `{cmd} close <id> -r "reason"` when done

If no issues are appropriate to work on now, tell the user what's available."""

    # Output decision to block stopping
    output = {"decision": "block", "reason": reason}
    click.echo(json.dumps(output))


@main.command()
def prime():
    """Output workflow context for AI agents.

    Designed for Claude Code hooks (SessionStart) to remind
    agents of the microbeads workflow.

    Auto-initializes microbeads if not already initialized, and syncs
    to pull any remote changes.
    """
    # Check if we're in a git repo
    repo_root = repo.find_repo_root()
    if repo_root is None:
        # Silent exit - not in a git repo
        sys.exit(0)

    # Auto-init if not initialized
    if not repo.is_initialized(repo_root):
        repo.init(repo_root)

    # Sync to pull any remote changes
    repo.sync(repo_root)

    # Clear cache after sync since git may have updated files
    worktree = repo.get_worktree_path(repo_root)
    issues.clear_cache(worktree, include_disk=True)

    # Check for custom PRIME.md override
    custom_prime = repo_root / ".microbeads" / "PRIME.md"
    if custom_prime.exists():
        click.echo(custom_prime.read_text())
    else:
        cmd = get_command_name()
        click.echo(PRIME_TEMPLATE.format(cmd=cmd))


@main.group()
def setup():
    """Setup integrations."""
    pass


@setup.command("claude")
@click.option("--global", "global_", is_flag=True, help="Install globally for all projects")
@click.option("--remove", is_flag=True, help="Remove hooks instead of installing")
def setup_claude(global_: bool, remove: bool):
    """Install Claude Code hooks for microbeads.

    Adds SessionStart hook that runs 'mb prime' which:
    - Auto-initializes microbeads if not already set up
    - Syncs to pull any remote changes
    - Outputs workflow context for the AI agent

    By default, installs for the current project (.claude/settings.json).
    Use --global to install for all projects (~/.claude/settings.json).
    """
    # Determine settings path
    # Project settings.json = shared (committed) - DEFAULT
    # Global settings.json = user-wide
    if global_:
        home = Path.home()
        settings_dir = home / ".claude"
        settings_path = settings_dir / "settings.json"
        scope = "global"
    else:
        settings_dir = Path.cwd() / ".claude"
        settings_path = settings_dir / "settings.json"
        scope = "project"

    if remove:
        _remove_claude_hooks(settings_path, scope)
    else:
        _install_claude_hooks(settings_dir, settings_path, scope)


def _install_claude_hooks(settings_dir: Path, settings_path: Path, scope: str) -> None:
    """Install Claude Code hooks."""
    click.echo(f"Installing Claude hooks ({scope})...")

    # Ensure directory exists
    settings_dir.mkdir(parents=True, exist_ok=True)

    # Load existing settings
    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            click.echo(f"Warning: Could not parse {settings_path}, creating new file")

    # Get or create hooks section
    hooks = settings.setdefault("hooks", {})

    # Add microbeads prime to SessionStart
    # Use get_command_name() to detect if mb is available
    command = f"{get_command_name()} prime"
    hook_entry = {"matcher": "", "hooks": [{"type": "command", "command": command}]}

    for event in ["SessionStart"]:
        event_hooks = hooks.get(event, [])
        if not isinstance(event_hooks, list):
            event_hooks = []

        # Check if already installed
        already_installed = False
        for hook in event_hooks:
            if isinstance(hook, dict):
                for h in hook.get("hooks", []):
                    if isinstance(h, dict) and h.get("command") == command:
                        already_installed = True
                        break

        if already_installed:
            click.echo(f"  {event}: already installed")
        else:
            event_hooks.append(hook_entry)
            hooks[event] = event_hooks
            click.echo(f"  {event}: installed")

    # Write settings
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")

    click.echo(f"\nClaude hooks installed: {settings_path}")
    click.echo("Restart Claude Code for changes to take effect.")


def _remove_claude_hooks(settings_path: Path, scope: str) -> None:
    """Remove Claude Code hooks."""
    click.echo(f"Removing Claude hooks ({scope})...")

    if not settings_path.exists():
        click.echo("No settings file found.")
        return

    try:
        settings = json.loads(settings_path.read_text())
    except json.JSONDecodeError:
        click.echo(f"Could not parse {settings_path}")
        return

    hooks = settings.get("hooks", {})
    # Check for both old and new command formats
    commands_to_remove = ["uvx microbeads prime", "mb prime"]

    for event in ["SessionStart"]:
        event_hooks = hooks.get(event, [])
        if not isinstance(event_hooks, list):
            continue

        # Filter out microbeads prime hooks
        filtered = []
        removed = False
        for hook in event_hooks:
            if isinstance(hook, dict):
                hook_commands = hook.get("hooks", [])
                has_microbeads_prime = any(
                    isinstance(h, dict) and h.get("command") in commands_to_remove
                    for h in hook_commands
                )
                if has_microbeads_prime:
                    removed = True
                    continue
            filtered.append(hook)

        if removed:
            if filtered:
                hooks[event] = filtered
            else:
                del hooks[event]
            click.echo(f"  {event}: removed")

    # Write settings
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    click.echo("Claude hooks removed.")


# Git hook script template
GIT_HOOK_SCRIPT = """#!/bin/sh
# Microbeads git hook - auto-sync issues
# Installed by: mb setup hooks

# Only run if microbeads is initialized
if [ -d ".git/microbeads-worktree" ]; then
    {cmd} sync 2>/dev/null || true
fi
"""


@main.group()
def hooks():
    """Manage git hooks for automatic synchronization."""
    pass


@hooks.command("install")
@click.option(
    "--hook",
    multiple=True,
    type=click.Choice(["post-merge", "post-checkout", "pre-push"]),
    help="Specific hooks to install (default: all)",
)
@pass_context
def hooks_install(ctx: Context, hook: tuple):
    """Install git hooks for automatic issue synchronization.

    Installs hooks that automatically sync microbeads issues:
    - post-merge: Sync after merging branches
    - post-checkout: Sync after switching branches
    - pre-push: Sync before pushing

    These hooks ensure your local issues stay in sync with remote changes.
    """
    hooks_dir = ctx.repo_root / ".git" / "hooks"
    hooks_to_process = list(hook) if hook else ["post-merge", "post-checkout", "pre-push"]
    _install_git_hooks(hooks_dir, hooks_to_process)


@hooks.command("remove")
@click.option(
    "--hook",
    multiple=True,
    type=click.Choice(["post-merge", "post-checkout", "pre-push"]),
    help="Specific hooks to remove (default: all)",
)
@pass_context
def hooks_remove(ctx: Context, hook: tuple):
    """Remove microbeads git hooks."""
    hooks_dir = ctx.repo_root / ".git" / "hooks"
    hooks_to_process = list(hook) if hook else ["post-merge", "post-checkout", "pre-push"]
    _remove_git_hooks(hooks_dir, hooks_to_process)


def _install_git_hooks(hooks_dir: Path, hooks: list[str]) -> None:
    """Install git hooks."""
    click.echo("Installing git hooks...")

    hooks_dir.mkdir(parents=True, exist_ok=True)
    cmd = get_command_name()
    script = GIT_HOOK_SCRIPT.format(cmd=cmd)

    for hook_name in hooks:
        hook_path = hooks_dir / hook_name

        # Check if hook already exists
        if hook_path.exists():
            content = hook_path.read_text()
            if "microbeads" in content.lower():
                click.echo(f"  {hook_name}: already installed")
                continue
            else:
                # Append to existing hook
                click.echo(f"  {hook_name}: appending to existing hook")
                content = content.rstrip() + "\n\n" + script
                hook_path.write_text(content)
        else:
            hook_path.write_text(script)
            click.echo(f"  {hook_name}: installed")

        # Make executable
        hook_path.chmod(0o755)

    click.echo("\nGit hooks installed.")


def _remove_git_hooks(hooks_dir: Path, hooks: list[str]) -> None:
    """Remove git hooks."""
    click.echo("Removing git hooks...")

    for hook_name in hooks:
        hook_path = hooks_dir / hook_name

        if not hook_path.exists():
            click.echo(f"  {hook_name}: not found")
            continue

        content = hook_path.read_text()
        if "microbeads" not in content.lower():
            click.echo(f"  {hook_name}: no microbeads hook found")
            continue

        # Check if this is a microbeads-only hook or mixed
        lines = content.split("\n")
        non_microbeads_lines = []
        in_microbeads_section = False

        for line in lines:
            if "Microbeads git hook" in line:
                in_microbeads_section = True
            elif in_microbeads_section and line.strip() == "fi":
                in_microbeads_section = False
                continue
            elif not in_microbeads_section:
                non_microbeads_lines.append(line)

        # Check if anything remains
        remaining = "\n".join(non_microbeads_lines).strip()
        if remaining and remaining != "#!/bin/sh":
            # Keep the non-microbeads parts
            hook_path.write_text(remaining + "\n")
            click.echo(f"  {hook_name}: removed microbeads section")
        else:
            # Remove the entire hook file
            hook_path.unlink()
            click.echo(f"  {hook_name}: removed")

    click.echo("Git hooks removed.")


if __name__ == "__main__":
    main()
