# Microbeads

A simplified git-backed issue tracker for AI agents. Issues are stored as individual JSON files on a dedicated orphan branch.

## Installation

```bash
# Run directly with uvx (recommended)
uvx microbeads --help

# Or install globally
uv tool install microbeads
```

## Quick Start

### 1. Initialize in your repository

```bash
cd your-repo
uvx microbeads init
```

This creates:
- An orphan branch named `microbeads` for issue storage
- A git worktree at `.git/microbeads-worktree/`
- A JSON merge driver for automatic conflict resolution

### 2. Import from existing beads (optional)

If you have the reference beads implementation (`bd`) installed with existing issues:

```bash
uvx microbeads init --import-beads
```

This imports all issues from your existing beads database.

### 3. Start tracking issues

```bash
# Create an issue
uvx microbeads create "Fix authentication bug" -p 1 -t bug

# List issues
uvx microbeads list

# See what's ready to work on
uvx microbeads ready
```

## Usage

### Creating Issues

```bash
uvx microbeads create "Title" [options]

Options:
  -d, --description TEXT  Issue description
  -t, --type TYPE         bug|feature|task|epic|chore (default: task)
  -p, --priority 0-4      0=critical, 4=low (default: 2)
  -l, --label LABEL       Labels (can specify multiple)
```

### Viewing Issues

```bash
uvx microbeads list              # All issues
uvx microbeads list -s open      # Filter by status
uvx microbeads list -p 1         # Filter by priority
uvx microbeads list -l backend   # Filter by label
uvx microbeads show <id>         # Show issue details
uvx microbeads ready             # Issues with no blockers
uvx microbeads blocked           # Issues waiting on dependencies
```

### Updating Issues

```bash
uvx microbeads update <id> -s in_progress    # Change status
uvx microbeads update <id> -p 1              # Change priority
uvx microbeads update <id> --add-label urgent
uvx microbeads close <id> -r "Completed"
uvx microbeads reopen <id>
```

### Dependencies

```bash
uvx microbeads dep add <child> <parent>   # child depends on parent
uvx microbeads dep rm <child> <parent>    # remove dependency
uvx microbeads dep tree <id>              # show dependency tree
```

### Syncing

```bash
uvx microbeads sync    # Commit and push to orphan branch
```

### JSON Output

Add `--json` for machine-readable output:

```bash
uvx microbeads --json list
uvx microbeads --json show bd-abc
uvx microbeads --json ready
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
