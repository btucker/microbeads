"""Performance tests for microbeads with large numbers of issues."""

import time
from pathlib import Path

import pytest

from microbeads import issues


@pytest.fixture
def perf_worktree(tmp_path: Path) -> Path:
    """Create a mock worktree for performance testing."""
    worktree = tmp_path / "perf-worktree"
    worktree.mkdir()

    beads_dir = worktree / ".microbeads"
    beads_dir.mkdir()
    issues_dir = beads_dir / "issues"
    issues_dir.mkdir()
    (beads_dir / "metadata.json").write_text('{"version": "0.1.0", "id_prefix": "perf"}\n')

    return worktree


@pytest.mark.slow
class TestScalabilityWith10000Issues:
    """Test that microbeads performs well with 10,000+ issues."""

    NUM_ISSUES = 10_000

    @pytest.fixture(scope="class")
    def populated_worktree(self, tmp_path_factory) -> tuple[Path, list[dict]]:
        """Create a worktree with 10,000 issues for testing."""
        tmp_path = tmp_path_factory.mktemp("perf")
        worktree = tmp_path / "perf-worktree"
        worktree.mkdir()

        beads_dir = worktree / ".microbeads"
        beads_dir.mkdir()
        issues_dir = beads_dir / "issues"
        issues_dir.mkdir()
        (beads_dir / "metadata.json").write_text('{"version": "0.1.0", "id_prefix": "perf"}\n')

        created_issues = []

        # Create 10,000 issues with varied properties
        for i in range(self.NUM_ISSUES):
            issue = issues.create_issue(
                title=f"Test issue {i}",
                worktree=worktree,
                description=f"Description for issue {i}" if i % 100 == 0 else "",
                issue_type=issues.IssueType(["bug", "feature", "task", "chore"][i % 4]),
                priority=i % 5,
                labels=[f"label-{i % 20}"] if i % 3 == 0 else None,
            )
            issues.save_issue(worktree, issue)
            created_issues.append(issue)

            # Close some issues (20%)
            if i % 5 == 0:
                issues.close_issue(worktree, issue["id"], "Done")

            # Set some to in_progress (10%)
            elif i % 10 == 0:
                issues.update_issue(worktree, issue["id"], status=issues.Status.IN_PROGRESS)

            # Add dependencies - each issue depends on up to 3 previous issues
            if i > 10 and i % 4 == 0:
                for j in range(1, min(4, i)):
                    if (i - j) >= 0:
                        try:
                            issues.add_dependency(
                                worktree, issue["id"], created_issues[i - j * 3]["id"]
                            )
                        except ValueError:
                            pass  # Skip if dependency already exists or invalid

        return worktree, created_issues

    def test_create_10000_issues_performance(self, perf_worktree: Path):
        """Test that creating 10,000 issues completes in reasonable time."""
        start = time.perf_counter()

        for i in range(self.NUM_ISSUES):
            issue = issues.create_issue(
                title=f"Perf test issue {i}",
                worktree=perf_worktree,
                priority=i % 5,
            )
            issues.save_issue(perf_worktree, issue)

        elapsed = time.perf_counter() - start

        # Should complete in under 120 seconds (generous for CI variance)
        assert elapsed < 120, f"Creating 10,000 issues took {elapsed:.2f}s (expected <120s)"
        print(
            f"\nCreated 10,000 issues in {elapsed:.2f}s ({self.NUM_ISSUES / elapsed:.0f} issues/sec)"
        )

        # Verify all issues were created
        all_issues = issues.load_all_issues(perf_worktree)
        assert len(all_issues) == self.NUM_ISSUES

    def test_list_all_issues_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that listing all 10,000 issues is fast."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        result = issues.list_issues(worktree)
        elapsed = time.perf_counter() - start

        # Listing 10k should be under 10 seconds
        assert elapsed < 10, f"Listing 10,000 issues took {elapsed:.2f}s (expected <10s)"
        print(f"\nListed {len(result)} issues in {elapsed:.2f}s")
        assert len(result) > 0

    def test_filter_by_status_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that filtering by status is fast with 10,000 issues."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        open_issues = issues.list_issues(worktree, status=issues.Status.OPEN)
        closed_issues = issues.list_issues(worktree, status=issues.Status.CLOSED)
        in_progress = issues.list_issues(worktree, status=issues.Status.IN_PROGRESS)
        elapsed = time.perf_counter() - start

        # Three filtered queries should be under 15 seconds
        assert elapsed < 15, f"Three filtered queries took {elapsed:.2f}s (expected <15s)"
        print(
            f"\nFiltered queries: open={len(open_issues)}, closed={len(closed_issues)}, in_progress={len(in_progress)} in {elapsed:.2f}s"
        )

        # Verify we got results
        assert len(open_issues) > 0
        assert len(closed_issues) > 0

    def test_filter_by_label_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that filtering by label is fast with 10,000 issues."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        total_found = 0
        for i in range(20):
            result = issues.list_issues(worktree, label=f"label-{i}")
            total_found += len(result)
        elapsed = time.perf_counter() - start

        # 20 label queries should be under 30 seconds
        assert elapsed < 30, f"20 label queries took {elapsed:.2f}s (expected <30s)"
        print(f"\n20 label queries found {total_found} total issues in {elapsed:.2f}s")

    def test_filter_by_priority_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that filtering by priority is fast with 10,000 issues."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        total_found = 0
        for p in range(5):
            result = issues.list_issues(worktree, priority=p)
            total_found += len(result)
        elapsed = time.perf_counter() - start

        # 5 priority queries should be under 15 seconds
        assert elapsed < 15, f"5 priority queries took {elapsed:.2f}s (expected <15s)"
        print(f"\n5 priority queries found {total_found} total issues in {elapsed:.2f}s")

    def test_get_ready_issues_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that getting ready issues is fast with dependencies."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        ready = issues.get_ready_issues(worktree)
        elapsed = time.perf_counter() - start

        # Ready query with dependencies should be under 30 seconds
        assert elapsed < 30, f"Ready query took {elapsed:.2f}s (expected <30s)"
        print(f"\nFound {len(ready)} ready issues in {elapsed:.2f}s")
        assert len(ready) > 0

    def test_get_blocked_issues_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that getting blocked issues is fast with many dependencies."""
        worktree, _ = populated_worktree

        start = time.perf_counter()
        blocked = issues.get_blocked_issues(worktree)
        elapsed = time.perf_counter() - start

        # Blocked query should be under 30 seconds
        assert elapsed < 30, f"Blocked query took {elapsed:.2f}s (expected <30s)"
        print(f"\nFound {len(blocked)} blocked issues in {elapsed:.2f}s")

    def test_get_issue_by_id_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that getting individual issues by ID is fast."""
        worktree, created_issues = populated_worktree

        # Sample 500 IDs spread across all issues
        sample_ids = [created_issues[i * 20]["id"] for i in range(500)]

        start = time.perf_counter()
        for issue_id in sample_ids:
            issue = issues.get_issue(worktree, issue_id)
            assert issue is not None
        elapsed = time.perf_counter() - start

        # 500 lookups should be under 5 seconds
        assert elapsed < 5, f"500 ID lookups took {elapsed:.2f}s (expected <5s)"
        print(f"\n500 ID lookups in {elapsed:.2f}s ({500 / elapsed:.0f} lookups/sec)")

    def test_partial_id_lookup_performance(self, populated_worktree: tuple[Path, list[dict]]):
        """Test that partial ID lookup is reasonably fast with 10,000 issues."""
        worktree, created_issues = populated_worktree

        # Use first 6 chars of IDs (may have collisions with 10k issues)
        sample_partials = [created_issues[i * 50]["id"][:6] for i in range(100)]

        start = time.perf_counter()
        resolved = 0
        ambiguous = 0
        for partial in sample_partials:
            try:
                issues.resolve_issue_id(worktree, partial)
                resolved += 1
            except ValueError:
                ambiguous += 1
        elapsed = time.perf_counter() - start

        # 100 partial lookups should be under 10 seconds
        assert elapsed < 10, f"100 partial lookups took {elapsed:.2f}s (expected <10s)"
        print(
            f"\n100 partial lookups: {resolved} resolved, {ambiguous} ambiguous in {elapsed:.2f}s"
        )


@pytest.mark.slow
class TestDependencyScalability:
    """Test dependency operations scale with many issues and complex dependency graphs."""

    NUM_ISSUES = 1000
    DEPS_PER_ISSUE = 5

    @pytest.fixture(scope="class")
    def dependency_worktree(self, tmp_path_factory) -> tuple[Path, list[dict]]:
        """Create issues with complex dependency graphs."""
        tmp_path = tmp_path_factory.mktemp("deps")
        worktree = tmp_path / "dep-worktree"
        worktree.mkdir()

        beads_dir = worktree / ".microbeads"
        beads_dir.mkdir()
        issues_dir = beads_dir / "issues"
        issues_dir.mkdir()
        (beads_dir / "metadata.json").write_text('{"version": "0.1.0", "id_prefix": "dep"}\n')

        created_issues = []

        # Create 1000 issues
        for i in range(self.NUM_ISSUES):
            issue = issues.create_issue(
                title=f"Dep test issue {i}",
                worktree=worktree,
            )
            issues.save_issue(worktree, issue)
            created_issues.append(issue)

        # Create complex dependency graph:
        # - Each issue (after first 20) depends on 5 previous issues
        # - This creates ~5000 dependencies total
        deps_created = 0
        for i in range(20, self.NUM_ISSUES):
            for j in range(1, self.DEPS_PER_ISSUE + 1):
                dep_idx = i - j * 4  # Spread out dependencies
                if dep_idx >= 0:
                    try:
                        issues.add_dependency(
                            worktree,
                            created_issues[i]["id"],
                            created_issues[dep_idx]["id"],
                        )
                        deps_created += 1
                    except ValueError:
                        pass

        # Close ~20% of issues to create varied dependency states
        for i in range(0, self.NUM_ISSUES, 5):
            issues.close_issue(worktree, created_issues[i]["id"], "Done")

        print(f"\nCreated {self.NUM_ISSUES} issues with {deps_created} dependencies")
        return worktree, created_issues

    def test_get_blocked_issues_with_complex_graph(
        self, dependency_worktree: tuple[Path, list[dict]]
    ):
        """Test getting blocked issues with ~5000 dependencies."""
        worktree, _ = dependency_worktree

        start = time.perf_counter()
        blocked = issues.get_blocked_issues(worktree)
        elapsed = time.perf_counter() - start

        # Should complete in under 15 seconds
        assert elapsed < 15, f"Blocked query took {elapsed:.2f}s (expected <15s)"
        print(f"\nFound {len(blocked)} blocked issues in {elapsed:.2f}s")

    def test_get_ready_with_complex_graph(self, dependency_worktree: tuple[Path, list[dict]]):
        """Test getting ready issues with complex dependency graph."""
        worktree, _ = dependency_worktree

        start = time.perf_counter()
        ready = issues.get_ready_issues(worktree)
        elapsed = time.perf_counter() - start

        # Should complete in under 15 seconds
        assert elapsed < 15, f"Ready query took {elapsed:.2f}s (expected <15s)"
        print(f"\nFound {len(ready)} ready issues in {elapsed:.2f}s")

    def test_dependency_tree_deep_graph(self, dependency_worktree: tuple[Path, list[dict]]):
        """Test building dependency trees for issues deep in the graph."""
        worktree, created_issues = dependency_worktree

        start = time.perf_counter()
        # Build trees for last 50 issues (deepest dependencies)
        for i in range(self.NUM_ISSUES - 50, self.NUM_ISSUES):
            issues.build_dependency_tree(worktree, created_issues[i]["id"])
        elapsed = time.perf_counter() - start

        # 50 tree builds should be under 30 seconds
        assert elapsed < 30, f"50 tree builds took {elapsed:.2f}s (expected <30s)"
        print(f"\nBuilt 50 dependency trees in {elapsed:.2f}s")

    def test_add_dependency_performance(self, perf_worktree: Path):
        """Test adding many dependencies is fast."""
        created_issues = []

        # Create 200 issues
        for i in range(200):
            issue = issues.create_issue(
                title=f"Add dep test {i}",
                worktree=perf_worktree,
            )
            issues.save_issue(perf_worktree, issue)
            created_issues.append(issue)

        start = time.perf_counter()
        deps_added = 0
        # Add 500 dependencies
        for i in range(50, 200):
            for j in range(1, 4):
                dep_idx = i - j * 10
                if dep_idx >= 0:
                    try:
                        issues.add_dependency(
                            perf_worktree,
                            created_issues[i]["id"],
                            created_issues[dep_idx]["id"],
                        )
                        deps_added += 1
                    except ValueError:
                        pass
        elapsed = time.perf_counter() - start

        # Adding 500 dependencies should be under 10 seconds
        assert elapsed < 10, f"Adding {deps_added} dependencies took {elapsed:.2f}s (expected <10s)"
        print(f"\nAdded {deps_added} dependencies in {elapsed:.2f}s")


@pytest.mark.slow
class TestMemoryEfficiency:
    """Test memory usage doesn't explode with many issues."""

    def test_load_all_doesnt_keep_file_handles(self, perf_worktree: Path):
        """Test that loading issues properly closes file handles."""
        # Create 500 issues with unique titles to avoid ID collisions
        num_created = 0
        for i in range(500):
            issue = issues.create_issue(
                title=f"Memory test {i} - unique suffix {time.time_ns()}",
                worktree=perf_worktree,
            )
            issues.save_issue(perf_worktree, issue)
            num_created += 1

        # Load all issues multiple times
        for _ in range(10):
            all_issues = issues.load_all_issues(perf_worktree)
            # Allow for potential ID collisions (should be rare with unique suffixes)
            assert len(all_issues) >= num_created - 5, (
                f"Expected ~{num_created} issues, got {len(all_issues)}"
            )

        # If file handles leaked, we'd hit OS limits
        # This test passes if no exception is raised


def _print_benchmark_table(results: list[dict]) -> None:
    """Print benchmark results as a formatted table."""
    print("\n" + "=" * 70)
    print("BENCHMARK RESULTS: microbeads vs bd")
    print("=" * 70)
    print(f"{'Operation':<25} {'mb (s)':<10} {'bd (s)':<10} {'Ratio':<10} {'Winner':<10}")
    print("-" * 70)

    for r in results:
        ratio = r["bd"] / r["mb"] if r["mb"] > 0 else 0
        winner = "mb" if ratio > 1 else "bd" if ratio < 1 else "tie"
        ratio_str = f"{ratio:.2f}x"
        print(f"{r['name']:<25} {r['mb']:<10.2f} {r['bd']:<10.2f} {ratio_str:<10} {winner:<10}")

    print("-" * 70)
    print("Ratio > 1.0 means microbeads is faster")
    print("=" * 70 + "\n")


@pytest.mark.slow
class TestBenchmarkVsBd:
    """Benchmark microbeads against bd (beads) CLI for comparison.

    These tests require bd to be installed. They are skipped if bd is not available.
    Install bd from: https://github.com/btucker/bd-binaries
    """

    NUM_ISSUES = 1000

    @pytest.fixture
    def bd_available(self):
        """Check if bd is installed."""
        import shutil

        bd_path = shutil.which("bd") or "/tmp/bd"
        if not Path(bd_path).exists():
            pytest.skip("bd not installed - install from github.com/btucker/bd-binaries")
        return bd_path

    @pytest.fixture
    def benchmark_repos(self, tmp_path: Path, bd_available: str) -> tuple[Path, Path]:
        """Create two git repos for benchmarking - one for mb, one for bd."""
        import os
        import subprocess

        env = {
            "GIT_AUTHOR_NAME": "Test User",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test User",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
        }

        # Create mb repo
        mb_repo = tmp_path / "mb-repo"
        mb_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=mb_repo, capture_output=True, env=env)
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"], cwd=mb_repo, capture_output=True, env=env
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=mb_repo,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=mb_repo, capture_output=True, env=env
        )
        (mb_repo / "README.md").write_text("# MB Test\n")
        subprocess.run(["git", "add", "."], cwd=mb_repo, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=mb_repo, capture_output=True, check=True, env=env
        )

        # Create bd repo
        bd_repo = tmp_path / "bd-repo"
        bd_repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=bd_repo, capture_output=True, env=env)
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"], cwd=bd_repo, capture_output=True, env=env
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=bd_repo,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=bd_repo, capture_output=True, env=env
        )
        (bd_repo / "README.md").write_text("# BD Test\n")
        subprocess.run(["git", "add", "."], cwd=bd_repo, capture_output=True, env=env)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=bd_repo, capture_output=True, check=True, env=env
        )

        return mb_repo, bd_repo

    def test_benchmark_create_issues(self, benchmark_repos: tuple[Path, Path], bd_available: str):
        """Benchmark creating issues: microbeads vs bd."""
        import os
        import subprocess

        mb_repo, bd_repo = benchmark_repos

        env = os.environ.copy()
        env["HOME"] = str(mb_repo.parent)

        # Initialize both
        subprocess.run(["uv", "run", "mb", "init"], cwd=mb_repo, capture_output=True, env=env)
        subprocess.run([bd_available, "init"], cwd=bd_repo, capture_output=True, env=env)

        # Benchmark microbeads
        mb_start = time.perf_counter()
        for i in range(self.NUM_ISSUES):
            subprocess.run(
                ["uv", "run", "mb", "create", f"Issue {i}", "-p", str(i % 5)],
                cwd=mb_repo,
                capture_output=True,
                env=env,
            )
        mb_elapsed = time.perf_counter() - mb_start

        # Benchmark bd
        bd_start = time.perf_counter()
        for i in range(self.NUM_ISSUES):
            subprocess.run(
                [bd_available, "create", f"Issue {i}", "-p", str(i % 5)],
                cwd=bd_repo,
                capture_output=True,
                env=env,
            )
        bd_elapsed = time.perf_counter() - bd_start

        _print_benchmark_table(
            [
                {"name": f"Create {self.NUM_ISSUES} issues", "mb": mb_elapsed, "bd": bd_elapsed},
            ]
        )

    def test_benchmark_list_issues(self, benchmark_repos: tuple[Path, Path], bd_available: str):
        """Benchmark listing issues: microbeads vs bd."""
        import os
        import subprocess

        mb_repo, bd_repo = benchmark_repos

        env = os.environ.copy()
        env["HOME"] = str(mb_repo.parent)

        # Initialize and create issues
        subprocess.run(["uv", "run", "mb", "init"], cwd=mb_repo, capture_output=True, env=env)
        subprocess.run([bd_available, "init"], cwd=bd_repo, capture_output=True, env=env)

        # Create 500 issues in each
        for i in range(500):
            subprocess.run(
                ["uv", "run", "mb", "create", f"Issue {i}"],
                cwd=mb_repo,
                capture_output=True,
                env=env,
            )
            subprocess.run(
                [bd_available, "create", f"Issue {i}"], cwd=bd_repo, capture_output=True, env=env
            )

        # Benchmark list operations (10 times each)
        mb_start = time.perf_counter()
        for _ in range(10):
            subprocess.run(["uv", "run", "mb", "list"], cwd=mb_repo, capture_output=True, env=env)
        mb_elapsed = time.perf_counter() - mb_start

        bd_start = time.perf_counter()
        for _ in range(10):
            subprocess.run([bd_available, "list"], cwd=bd_repo, capture_output=True, env=env)
        bd_elapsed = time.perf_counter() - bd_start

        _print_benchmark_table(
            [
                {"name": "List 500 issues (10x)", "mb": mb_elapsed, "bd": bd_elapsed},
            ]
        )
