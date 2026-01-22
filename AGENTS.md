# Agent Instructions for Microbeads

Microbeads is a simplified git-backed issue tracker designed for AI agents. Issues are stored as individual JSON files on a dedicated orphan branch.

## Quick Reference

```bash
# Initialize (once per repo)
bd init

# Create issues
bd create "Fix authentication bug" -p 1 -t bug -l backend
bd create "Add user dashboard" -p 2 -t feature -d "Description here"

# View issues
bd list                          # All issues
bd list -s open                  # Filter by status
bd ready                         # Issues with no blockers
bd blocked                       # Issues waiting on dependencies
bd show bd-abc                   # Show issue details

# Update issues
bd update bd-abc -s in_progress  # Change status
bd update bd-abc -p 1            # Change priority
bd update bd-abc --add-label urgent

# Close/reopen
bd close bd-abc -r "Completed"
bd reopen bd-abc

# Dependencies
bd dep add bd-child bd-parent    # child depends on parent
bd dep rm bd-child bd-parent     # remove dependency
bd dep tree bd-abc               # show dependency tree

# Sync to remote
bd sync                          # Commit and push to orphan branch
```

## JSON Output Mode

**Always use `--json` for programmatic access:**

```bash
bd --json list
bd --json show bd-abc
bd --json ready
bd --json create "New issue" -p 2
```

JSON output provides structured data suitable for parsing and automation.

## Agent Session Workflow

### Starting a Session

```bash
# 1. Check what's ready to work on
bd ready

# 2. Pick an issue and mark it in progress
bd update bd-abc -s in_progress

# 3. Do the work...
```

### During Work

```bash
# Create issues for discovered work
bd create "Found edge case in validation" -p 2 -t bug

# Add dependencies as you discover them
bd dep add bd-new bd-existing

# Update status as work progresses
bd update bd-abc -s in_progress
```

### Ending a Session

```bash
# Close completed work
bd close bd-abc -r "Implemented and tested"

# Sync issues to remote
bd sync
```

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync                    # Commits issues to orphan branch
   git push                   # Push your code branch
   git status                 # MUST show "up to date with origin"
   ```
5. **Verify** - All changes committed AND pushed
6. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

## Visual Design

**Use small Unicode symbols** for status display:
- `○` open
- `◐` in_progress
- `⊗` blocked
- `●` closed
- `✓` completed

**Priority format:** `P0` (critical) through `P4` (low)

## Storage Architecture

Microbeads stores issues differently from the reference beads implementation:

- **No SQLite database** - Issues are individual JSON files
- **Orphan branch** - All issue data lives on the `microbeads` branch
- **Git worktree** - The orphan branch is checked out at `.git/microbeads-worktree/`
- **JSON files** - Each issue is `.microbeads/issues/<id>.json`
- **Sorted keys** - JSON files have alphabetically sorted keys for clean diffs
- **Merge driver** - Git is configured to auto-merge JSON conflicts

This design means:
- Issues sync automatically with git pull/push on the orphan branch
- No database corruption issues
- Easy to inspect issues directly
- Works well with multiple agents/collaborators

## Issue Schema

```json
{
  "closed_at": null,
  "closed_reason": null,
  "created_at": "2025-01-22T10:00:00Z",
  "dependencies": ["bd-parent1", "bd-parent2"],
  "description": "Detailed description",
  "id": "bd-a1b2",
  "labels": ["backend", "urgent"],
  "priority": 2,
  "status": "open",
  "title": "Issue title",
  "type": "bug",
  "updated_at": "2025-01-22T10:00:00Z"
}
```

**Status values:** `open`, `in_progress`, `blocked`, `closed`

**Type values:** `bug`, `feature`, `task`, `epic`, `chore`

**Priority values:** `0` (critical) through `4` (low)

## Differences from Reference Beads

| Feature | Reference Beads | Microbeads |
|---------|----------------|------------|
| Storage | SQLite + JSONL | JSON files |
| Sync | Daemon + auto-export | `bd sync` manual |
| Branch | Configurable | Always `microbeads` orphan |
| Merge | JSONL conflicts | JSON merge driver |
| Features | Full (daemon, hooks, federation) | Core only |

Microbeads is intentionally minimal - it provides the essential issue tracking workflow without the complexity of the full beads implementation.
