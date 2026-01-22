# Microbeads

A simplified git-backed issue tracker for AI agents. Issues are stored as individual JSON files on a dedicated orphan branch.

## Installation

```bash
# Run directly with uvx (no install needed)
uvx microbeads --help

# Or install globally for the `mb` command
uv tool install microbeads
mb --help
```

After `uv tool install`, you get two commands: `mb` (short) and `microbeads` (full).

## Quick Start

### 1. Initialize in your repository

```bash
cd your-repo
mb init
```

This creates:
- An orphan branch named `microbeads` for issue storage
- A git worktree at `.git/microbeads-worktree/`
- A JSON merge driver for automatic conflict resolution

### 2. Import from existing beads (optional)

If you have the reference beads implementation (`bd`) installed with existing issues:

```bash
mb init --import-beads
```

This imports all issues from your existing beads database.

### 3. Start tracking issues

```bash
# Create an issue
mb create "Fix authentication bug" -p 1 -t bug

# List issues
mb list

# See what's ready to work on
mb ready
```

## Usage

### Creating Issues

```bash
mb create "Title" [options]

Options:
  -d, --description TEXT  Issue description
  -t, --type TYPE         bug|feature|task|epic|chore (default: task)
  -p, --priority 0-4      0=critical, 4=low (default: 2)
  -l, --label LABEL       Labels (can specify multiple)
```

### Viewing Issues

```bash
mb list              # All issues
mb list -s open      # Filter by status
mb list -p 1         # Filter by priority
mb list -l backend   # Filter by label
mb show <id>         # Show issue details
mb ready             # Issues with no blockers
mb blocked           # Issues waiting on dependencies
```

### Updating Issues

```bash
mb update <id> -s in_progress    # Change status
mb update <id> -p 1              # Change priority
mb update <id> --add-label urgent
mb close <id> -r "Completed"
mb reopen <id>
```

### Dependencies

```bash
mb dep add <child> <parent>   # child depends on parent
mb dep rm <child> <parent>    # remove dependency
mb dep tree <id>              # show dependency tree
```

### Syncing

```bash
mb sync    # Commit and push to orphan branch
```

### JSON Output

Add `--json` for machine-readable output:

```bash
mb --json list
mb --json show bd-abc
mb --json ready
```

## How It Works

Unlike the reference beads implementation (SQLite + JSONL), microbeads stores each issue as a separate JSON file:

```
.git/microbeads-worktree/
└── .microbeads/
    ├── metadata.json
    └── issues/
        ├── bd-a1b2.json
        ├── bd-c3d4.json
        └── ...
```

Benefits:
- **No database** - Just JSON files, easy to inspect and debug
- **Git-native** - Issues sync with normal git operations
- **Merge-friendly** - Custom merge driver handles conflicts automatically
- **Multi-agent safe** - Multiple agents can work on different issues

The `microbeads` orphan branch keeps issue data completely separate from your code.

## Claude Code Integration

Install hooks so Claude Code automatically loads workflow context:

```bash
# Install for this project (default)
mb setup claude

# Or install globally (all projects)
mb setup claude --global

# Remove hooks
mb setup claude --remove
```

This adds `SessionStart` and `PreCompact` hooks that run `mb prime` to remind the AI agent of the microbeads workflow.

## For AI Agents

See [AGENTS.md](AGENTS.md) for detailed agent instructions including:
- Session workflow
- JSON output mode
- Landing the plane (session completion checklist)

## Differences from Reference Beads

| Feature | Reference Beads | Microbeads |
|---------|----------------|------------|
| Storage | SQLite + JSONL | JSON files |
| Sync | Daemon + auto-export | Manual `sync` |
| Branch | Configurable | Always `microbeads` orphan |
| Merge | JSONL conflicts | JSON merge driver |
| Features | Full (daemon, hooks, federation) | Core only |

Microbeads is intentionally minimal - just the essentials for AI agent issue tracking.
