"""Tests for JSON merge driver."""

import json
from pathlib import Path

from microbeads.merge import merge_issues, merge_json_files


class TestMergeIssues:
    """Tests for 3-way merge logic."""

    def test_merge_no_conflict(self):
        """Test merge with no conflicts."""
        base = {
            "id": "test-1",
            "title": "Original",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": ["a"],
            "dependencies": [],
        }
        ours = {**base, "title": "Our Change", "updated_at": "2024-01-02T00:00:00Z"}
        theirs = base.copy()

        result = merge_issues(base, ours, theirs)
        assert result["title"] == "Our Change"

    def test_merge_scalar_conflict_newer_wins(self):
        """Test that newer timestamp wins for scalar conflicts."""
        base = {
            "id": "test-1",
            "title": "Original",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "dependencies": [],
        }
        ours = {
            **base,
            "title": "Our Title",
            "updated_at": "2024-01-03T00:00:00Z",
        }
        theirs = {
            **base,
            "title": "Their Title",
            "updated_at": "2024-01-02T00:00:00Z",
        }

        result = merge_issues(base, ours, theirs)
        # Ours is newer, so our title wins
        assert result["title"] == "Our Title"

    def test_merge_labels_union(self):
        """Test that labels are union merged."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": ["shared"],
            "dependencies": [],
        }
        ours = {**base, "labels": ["shared", "ours"], "updated_at": "2024-01-02T00:00:00Z"}
        theirs = {**base, "labels": ["shared", "theirs"], "updated_at": "2024-01-02T00:00:00Z"}

        result = merge_issues(base, ours, theirs)
        # All labels should be present
        assert "shared" in result["labels"]
        assert "ours" in result["labels"]
        assert "theirs" in result["labels"]

    def test_merge_dependencies_union(self):
        """Test that dependencies are union merged."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "dependencies": ["dep-1"],
        }
        ours = {**base, "dependencies": ["dep-1", "dep-2"], "updated_at": "2024-01-02T00:00:00Z"}
        theirs = {**base, "dependencies": ["dep-1", "dep-3"], "updated_at": "2024-01-02T00:00:00Z"}

        result = merge_issues(base, ours, theirs)
        assert "dep-1" in result["dependencies"]
        assert "dep-2" in result["dependencies"]
        assert "dep-3" in result["dependencies"]

    def test_merge_timestamps_latest_wins(self):
        """Test that latest timestamp is kept."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "dependencies": [],
        }
        ours = {**base, "updated_at": "2024-01-05T00:00:00Z"}
        theirs = {**base, "updated_at": "2024-01-03T00:00:00Z"}

        result = merge_issues(base, ours, theirs)
        assert result["updated_at"] == "2024-01-05T00:00:00Z"

    def test_merge_id_preserved(self):
        """Test that ID is always preserved."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "dependencies": [],
        }

        result = merge_issues(base, base, base)
        assert result["id"] == "test-1"

    def test_merge_closed_at_takes_value(self):
        """Test closed_at handling when one has value."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "closed_at": None,
            "labels": [],
            "dependencies": [],
        }
        ours = {**base, "closed_at": "2024-01-02T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z"}
        theirs = base.copy()

        result = merge_issues(base, ours, theirs)
        assert result["closed_at"] == "2024-01-02T00:00:00Z"

    def test_merge_label_removal(self):
        """Test that removed labels stay removed if both kept them gone."""
        base = {
            "id": "test-1",
            "title": "Test",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": ["remove-me", "keep"],
            "dependencies": [],
        }
        ours = {**base, "labels": ["keep"], "updated_at": "2024-01-02T00:00:00Z"}
        theirs = {**base, "labels": ["keep"], "updated_at": "2024-01-02T00:00:00Z"}

        result = merge_issues(base, ours, theirs)
        assert "remove-me" not in result["labels"]
        assert "keep" in result["labels"]


class TestMergeJsonFiles:
    """Tests for file-based merge."""

    def test_merge_json_files(self, tmp_path: Path):
        """Test merging JSON files."""
        base_data = {
            "id": "test-1",
            "title": "Original",
            "status": "open",
            "updated_at": "2024-01-01T00:00:00Z",
            "labels": [],
            "dependencies": [],
        }
        ours_data = {**base_data, "title": "Changed", "updated_at": "2024-01-02T00:00:00Z"}
        theirs_data = base_data.copy()

        base_path = tmp_path / "base.json"
        ours_path = tmp_path / "ours.json"
        theirs_path = tmp_path / "theirs.json"

        base_path.write_text(json.dumps(base_data))
        ours_path.write_text(json.dumps(ours_data))
        theirs_path.write_text(json.dumps(theirs_data))

        result = merge_json_files(str(base_path), str(ours_path), str(theirs_path))
        assert result == 0

        # Check the merged result
        merged = json.loads(ours_path.read_text())
        assert merged["title"] == "Changed"

    def test_merge_json_files_invalid_json(self, tmp_path: Path):
        """Test handling of invalid JSON."""
        base_path = tmp_path / "base.json"
        ours_path = tmp_path / "ours.json"
        theirs_path = tmp_path / "theirs.json"

        base_path.write_text("not json")
        ours_path.write_text("{}")
        theirs_path.write_text("{}")

        result = merge_json_files(str(base_path), str(ours_path), str(theirs_path))
        assert result == 1

    def test_merge_json_files_empty_base(self, tmp_path: Path):
        """Test merging when base file is empty (unrelated histories)."""
        base_path = tmp_path / "base.json"
        ours_path = tmp_path / "ours.json"
        theirs_path = tmp_path / "theirs.json"

        # Empty base file simulates unrelated histories
        base_path.write_text("")
        ours_path.write_text(
            json.dumps(
                {
                    "id": "test-1",
                    "title": "Ours",
                    "status": "open",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "labels": [],
                    "dependencies": [],
                }
            )
        )
        theirs_path.write_text(
            json.dumps(
                {
                    "id": "test-1",
                    "title": "Theirs",
                    "status": "open",
                    "updated_at": "2024-01-02T00:00:00Z",
                    "labels": [],
                    "dependencies": [],
                }
            )
        )

        result = merge_json_files(str(base_path), str(ours_path), str(theirs_path))
        assert result == 0

        merged = json.loads(ours_path.read_text())
        # Theirs is newer, so should win
        assert merged["title"] == "Theirs"

    def test_merge_json_files_metadata_prefers_theirs(self, tmp_path: Path):
        """Test that metadata.json always prefers theirs (remote)."""
        base_path = tmp_path / "base.json"
        ours_path = tmp_path / "ours.json"
        theirs_path = tmp_path / "theirs.json"

        # Metadata files have 'version' but no 'id'
        ours_data = {"version": "0.1.0", "id_prefix": "ours"}
        theirs_data = {"version": "0.2.0", "id_prefix": "theirs"}

        base_path.write_text("")
        ours_path.write_text(json.dumps(ours_data))
        theirs_path.write_text(json.dumps(theirs_data))

        result = merge_json_files(str(base_path), str(ours_path), str(theirs_path))
        assert result == 0

        merged = json.loads(ours_path.read_text())
        # Should prefer theirs for metadata
        assert merged["id_prefix"] == "theirs"
        assert merged["version"] == "0.2.0"
