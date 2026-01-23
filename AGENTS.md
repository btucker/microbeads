# Agent Instructions for Microbeads

Microbeads is a simplified git-backed issue tracker. Issues are JSON files on the `microbeads` orphan branch.

**Note:** Initialization (`mb init`) is done by the human before agent sessions begin.

## Quick Reference

```bash
mb create "Title" -d "Description of the work" -p 1 -t bug   # Create issue
mb list                                     # All issues
mb ready                                    # Issues with no blockers
mb show mi-abc                              # Show details
mb update mi-abc -s in_progress             # Change status
mb close mi-abc -r "Completed"              # Close with reason
mb dep add mi-child mi-parent               # Add dependency
mb sync                                     # Commit and push to orphan branch
```

**Always use `--json` for programmatic access:** `mb --json list`

## Test-Driven Development (TDD)

**Always follow TDD when implementing features or fixing bugs:**

1. **Write tests first** - Before writing implementation code, write failing tests that define the expected behavior
2. **Run tests to see them fail** - Verify the tests fail for the right reason
3. **Write minimal code** - Implement just enough to make tests pass
4. **Refactor** - Clean up while keeping tests green

This ensures code is testable by design and provides confidence that changes work correctly.

## Session Workflow (Task-Driven)

Your TodoWrite tasks are **automatically synced** to microbeads issues via hooks.
Include the issue ID in task names for linking.

```bash
# 1. Session Start: Check issues and create tasks
mb ready                                    # See what's available
mb create "New feature" -d "Implement X for Y" -p 1 -t feature   # Create issue

# 2. Create TodoWrite tasks with issue IDs:
#    "[mi-abc123] Implement feature"
#    "[mi-abc123] Write tests"
#    "[mi-def456] Fix related bug"

# 3. During Work: Update tasks via TodoWrite
#    - Tasks auto-sync to microbeads (claude-task label)
#    - Status mapping: pending→open, in_progress→in_progress, completed→closed

# 4. Exploration: file issues for anything worth addressing later
mb create "Found edge case" -d "When X happens, Y breaks" -p 2 -t bug
mb dep add mi-new mi-existing

# 5. Session End: Close issues and sync
mb close mi-abc123 -r "Implemented and tested"
mb sync
```

### Task Naming Convention
Include issue IDs in task names for traceability:
- `[mi-abc123] Implement the feature` - Links task to issue
- `[mi-abc123] Write tests for feature` - Multiple tasks per issue OK
- `Review code changes` - Standalone tasks (no issue link) also work

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
