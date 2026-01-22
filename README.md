# Microbeads

A simplified git-backed issue tracker for AI agents. Issues are stored as individual JSON files on a dedicated orphan branch. A custom merge strategy ensures you never need to deal with conflicts. Unlike beads, microbeads fully supports Claude Code Web sessions with automatic branch routing.

## Installation

```bash
# Run directly with uvx (no install needed)
uvx microbeads init

# Or install globally for the `mb` command
uv tool install microbeads
mb init
```

After `uv tool install`, you get two commands: `mb` (short) and `microbeads` (full).

## Quick Start

### 1. Initialize in your repository

```bash
cd your-repo
mb init

# Or use stealth mode (local-only, no remote push)
mb init --stealth

# Or contributor mode (route issues to external repo)
mb init --contributor /path/to/personal/repo
```

This creates:
- An orphan branch named `microbeads` for issue storage
- A git worktree at `.git/microbeads-worktree/`
- A JSON merge driver for automatic conflict resolution

### 2. Import from existing beads (optional)

If you have [beads](https://github.com/steveyegge/beads) (`bd`) installed with existing issues:

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
  -d, --description TEXT       Issue description
  -t, --type TYPE              bug|feature|task|epic|chore (default: task)
  -p, --priority 0-4           0=critical, 4=low (default: 2)
  -l, --label LABEL            Labels (can specify multiple)
  --design TEXT                Design notes or approach
  --notes TEXT                 General notes
  --acceptance-criteria TEXT   Definition of done
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
mb update <id> --design "New approach"
mb update <id> --notes "Additional context"
mb close <id> -r "Completed"
mb reopen <id>
```

All changes are tracked in issue history, visible with `mb show <id>`.

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

### Maintenance

```bash
mb doctor              # Check for issues (orphan deps, cycles, missing files)
mb doctor --fix        # Auto-fix problems where possible
```

### JSON Output

Add `--json` for machine-readable output:

```bash
mb --json list
mb --json show mi-abc
mb --json ready
```

## How It Works

Unlike beads (SQLite + JSONL), microbeads stores each issue as a separate JSON file:

```
.git/microbeads-worktree/
└── .microbeads/
    ├── metadata.json
    └── issues/
        ├── active/
        │   ├── mi-a1b2.json
        │   └── mi-c3d4.json
        └── closed/
            └── mi-e5f6.json
```

Active issues (open, in_progress, blocked) are stored separately from closed issues for faster loading—most operations only need active issues.

Benefits:
- **No database** - Just JSON files, easy to inspect and debug
- **Git-native** - Issues sync with normal git operations
- **Merge-friendly** - Custom merge driver handles conflicts automatically
- **Multi-agent safe** - Multiple agents can work on different issues
- **Fast loading** - Only loads closed issues when explicitly requested

The `microbeads` orphan branch keeps issue data completely separate from your code.

## Modes

### Stealth Mode

Stealth mode keeps issues local-only without pushing to any remote:

```bash
mb init --stealth
```

In stealth mode:
- Issues are stored locally in the worktree
- `mb sync` commits but skips all remote operations
- Useful for personal tracking without team visibility

### Contributor Mode

Contributor mode routes issues to an external repository:

```bash
mb init --contributor /path/to/personal/repo
```

This is useful when:
- You're contributing to a project that doesn't use microbeads
- You want to track your own issues separately from the main project
- You need a personal issue database across multiple projects

The external repo must already have microbeads initialized.

## Branch Strategy

Microbeads uses a branching strategy to support multiple concurrent sessions, especially in Claude Code web environments.

### Canonical Branch

The main branch for issue storage is `microbeads` (an orphan branch). In normal operation, `mb sync` commits and pushes directly to this branch.

### Claude Code Web Session Branches

Claude Code web sessions run on restricted branches like `claude/feature-name-XXXX` where `XXXX` is a session ID. These sessions can only push to branches matching their `claude/*` prefix.

**The workaround:** When microbeads detects it's running in a Claude Code web session (by checking if the current branch starts with `claude/`), it automatically pushes to a session-specific branch:

```
claude/microbeads-XXXX
```

Where `XXXX` matches the session ID from the code branch (e.g., `claude/fix-bug-abc123` → `claude/microbeads-abc123`).

### Multi-Session Sync

When you run `mb sync`, microbeads:

1. **Fetches** all remote branches matching `microbeads` or `claude/microbeads-*`
2. **Merges** changes from other sessions into your local `microbeads` branch
3. **Commits** your local changes
4. **Pushes** to the appropriate target branch (canonical or session-specific)
5. **Cleans up** stale session branches that have been successfully merged

This ensures all sessions eventually converge to the same state, even when Claude Code web sessions can't push directly to the canonical branch.

### Branch Flow Diagram

```
Session A (local/CLI)     Session B (Claude Code web)
        │                         │
        │                         │
        ▼                         ▼
   microbeads ◄─── merge ───► claude/microbeads-abc123
        │                         │
        └─────────┬───────────────┘
                  │
                  ▼
            origin/microbeads
            (canonical state)
```

## Claude Code Integration

Install hooks so Claude Code automatically loads workflow context:

```bash
# Install for this project (default)
mb hooks install

# Or install globally (all projects)
mb hooks install --global

# Remove hooks
mb hooks remove
mb hooks remove --global
```

This adds a `SessionStart` hook that runs `mb prime` to remind the AI agent of the microbeads workflow.

## For AI Agents

See [AGENTS.md](AGENTS.md) for detailed agent instructions including:
- Session workflow
- JSON output mode
- Landing the plane (session completion checklist)

## Differences from Beads

| Feature | Beads | Microbeads |
|---------|----------------|------------|
| Storage | SQLite + JSONL | JSON files |
| Sync | Daemon + auto-export | Manual `sync` |
| Branch | Configurable | Always `microbeads` orphan |
| Merge | JSONL conflicts | JSON merge driver |
| Doctor | `bd doctor` | `mb doctor` |
| History | Full tracking | Full tracking |
| Hooks | Git hooks | Claude Code hooks |
| Modes | Stealth, contributor | Stealth, contributor |
| Federation | Yes | No |
| Daemon | Yes | No |

Microbeads focuses on the essentials for AI agent issue tracking, without the complexity of federation or background daemons.

## Performance

### Benchmarks (vs `bd`)

| Operation | mb | bd |
|-----------|-----|-----|
| List 500 issues (10x) | 0.93s | 0.70s |
| Ready 200 issues (10x) | 0.85s | 0.65s |
| Update 50 issues | 4.2s | 2.1s |
| Create 100 issues | 8.5s | 4.2s |

The gap is primarily Python interpreter startup overhead (~100ms per invocation).

```bash
# Run benchmarks (requires bd binary)
uv run pytest tests/test_performance.py -m slow -v
```
