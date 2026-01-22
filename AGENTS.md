# Agent Instructions for Microbeads

Microbeads is a simplified git-backed issue tracker. Issues are JSON files on the `microbeads` orphan branch.

**Note:** Initialization (`mb init`) is done by the human before agent sessions begin.

## Quick Reference

```bash
mb create "Title" -p 1 -t bug -l backend   # Create issue
mb list                                     # All issues
mb ready                                    # Issues with no blockers
mb show bd-abc                              # Show details
mb update bd-abc -s in_progress             # Change status
mb close bd-abc -r "Completed"              # Close with reason
mb dep add bd-child bd-parent               # Add dependency
mb sync                                     # Commit and push to orphan branch
```

**Always use `--json` for programmatic access:** `mb --json list`

## Session Workflow

```bash
# Start: pick an issue
mb ready
mb update bd-abc -s in_progress

# During: create issues for discovered work
mb create "Found edge case" -p 2 -t bug
mb dep add bd-new bd-existing

# End: close and sync
mb close bd-abc -r "Implemented and tested"
mb sync
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
   mb sync                    # Commits issues to orphan branch
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
