"""Command-line interface for microbeads."""

import json
import subprocess
import sys
from typing import Any

import click

from . import issues, merge, repo


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
                raise click.ClickException("Microbeads is not initialized. Run 'bd init' first.")
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
        "open": " ",
        "in_progress": "▶",
        "blocked": "⊗",
        "closed": "✓",
    }
    icon = status_icons.get(issue.get("status", "open"), " ")
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

    if issue.get("dependencies"):
        lines.append(f"Depends on:  {', '.join(issue['dependencies'])}")

    lines.append(f"Created:     {issue.get('created_at', 'unknown')}")
    lines.append(f"Updated:     {issue.get('updated_at', 'unknown')}")

    if issue.get("closed_at"):
        lines.append(f"Closed:      {issue['closed_at']}")
        if issue.get("closed_reason"):
            lines.append(f"Reason:      {issue['closed_reason']}")

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
    except json.JSONDecodeError:
        raise click.ClickException(f"Failed to parse beads output: {result.stdout}")

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
            "dependencies": [d.get("depends_on") for d in beads_issue.get("dependencies", []) if d.get("depends_on")],
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


@main.command()
@click.option("--import-beads", is_flag=True, help="Import issues from existing beads installation")
@pass_context
def init(ctx: Context, import_beads: bool):
    """Initialize microbeads in this repository."""
    worktree = repo.init(ctx.repo_root)

    imported = 0
    if import_beads:
        imported = import_from_beads(worktree, ctx.json_output)

    output(
        ctx,
        {"status": "initialized", "worktree": str(worktree), "imported": imported},
        f"Microbeads initialized. Issues stored on orphan branch '{repo.BRANCH_NAME}'.",
    )


@main.command()
@click.argument("title")
@click.option("-d", "--description", default="", help="Issue description")
@click.option("-t", "--type", "issue_type", default="task",
              type=click.Choice(["bug", "feature", "task", "epic", "chore"]),
              help="Issue type")
@click.option("-p", "--priority", default=2, type=click.IntRange(0, 4),
              help="Priority (0=critical, 4=low)")
@click.option("-l", "--label", multiple=True, help="Labels (can specify multiple)")
@pass_context
def create(ctx: Context, title: str, description: str, issue_type: str, priority: int, label: tuple):
    """Create a new issue."""
    issue = issues.create_issue(
        title=title,
        description=description,
        issue_type=issues.IssueType(issue_type),
        priority=priority,
        labels=list(label) if label else None,
    )
    issues.save_issue(ctx.worktree, issue)
    output(ctx, issue, f"Created {issue['id']}: {title}")


@main.command("list")
@click.option("-s", "--status", type=click.Choice(["open", "in_progress", "blocked", "closed"]),
              help="Filter by status")
@click.option("-p", "--priority", type=click.IntRange(0, 4), help="Filter by priority")
@click.option("-l", "--label", help="Filter by label")
@click.option("-t", "--type", "issue_type",
              type=click.Choice(["bug", "feature", "task", "epic", "chore"]),
              help="Filter by type")
@pass_context
def list_cmd(ctx: Context, status: str | None, priority: int | None, label: str | None, issue_type: str | None):
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
    issue = issues.get_issue(ctx.worktree, issue_id)
    if issue is None:
        raise click.ClickException(f"Issue not found: {issue_id}")

    output(ctx, issue, format_issue_detail(issue))


@main.command()
@click.argument("issue_id")
@click.option("-s", "--status", type=click.Choice(["open", "in_progress", "blocked", "closed"]),
              help="Update status")
@click.option("-p", "--priority", type=click.IntRange(0, 4), help="Update priority")
@click.option("-t", "--title", help="Update title")
@click.option("-d", "--description", help="Update description")
@click.option("-l", "--label", multiple=True, help="Set labels (replaces existing)")
@click.option("--add-label", multiple=True, help="Add labels")
@click.option("--remove-label", multiple=True, help="Remove labels")
@pass_context
def update(ctx: Context, issue_id: str, status: str | None, priority: int | None,
           title: str | None, description: str | None, label: tuple, add_label: tuple, remove_label: tuple):
    """Update an issue."""
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
        )
        output(ctx, issue, f"Updated {issue['id']}")
    except ValueError as e:
        raise click.ClickException(str(e))


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
        raise click.ClickException(str(e))


@main.command()
@click.argument("issue_id")
@pass_context
def reopen(ctx: Context, issue_id: str):
    """Reopen a closed issue."""
    try:
        issue = issues.reopen_issue(ctx.worktree, issue_id)
        output(ctx, issue, f"Reopened {issue['id']}")
    except ValueError as e:
        raise click.ClickException(str(e))


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
    except ValueError as e:
        raise click.ClickException(str(e))


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
        raise click.ClickException(str(e))


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
@click.option("-m", "--message", help="Commit message")
@pass_context
def sync(ctx: Context, message: str | None):
    """Commit and push changes to the microbeads branch."""
    repo.sync(ctx.repo_root, message)
    output(ctx, {"status": "synced"}, "Changes synced.")


@main.command("merge-driver", hidden=True)
@click.argument("base_path")
@click.argument("ours_path")
@click.argument("theirs_path")
def merge_driver(base_path: str, ours_path: str, theirs_path: str):
    """Git merge driver for JSON files (internal use)."""
    sys.exit(merge.merge_json_files(base_path, ours_path, theirs_path))


if __name__ == "__main__":
    main()
