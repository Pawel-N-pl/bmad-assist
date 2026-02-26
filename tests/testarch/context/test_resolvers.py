"""Tests for TEA context resolvers."""

from pathlib import Path

from bmad_assist.testarch.context.resolvers import (
    RESOLVER_REGISTRY,
    ATDDResolver,
    TestDesignResolver,
    TestReviewResolver,
    TraceResolver,
)


class TestResolverRegistry:
    """Tests for resolver registry."""

    def test_registry_has_all_artifact_types(self) -> None:
        """Test that registry contains all expected artifact types."""
        assert "test-design" in RESOLVER_REGISTRY
        assert "atdd" in RESOLVER_REGISTRY
        assert "test-review" in RESOLVER_REGISTRY
        assert "trace" in RESOLVER_REGISTRY

    def test_registry_classes(self) -> None:
        """Test registry maps to correct resolver classes."""
        assert RESOLVER_REGISTRY["test-design"] is TestDesignResolver
        assert RESOLVER_REGISTRY["atdd"] is ATDDResolver
        assert RESOLVER_REGISTRY["test-review"] is TestReviewResolver
        assert RESOLVER_REGISTRY["trace"] is TraceResolver


class TestBaseResolver:
    """Tests for BaseResolver functionality."""

    def test_truncate_content_within_budget(self, tmp_path: Path) -> None:
        """Test truncation doesn't truncate if within budget."""
        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        content = "Short content"
        result = resolver._truncate_content(content, 1000)
        assert result == content
        assert "truncated" not in result

    def test_truncate_content_exceeds_budget(self, tmp_path: Path) -> None:
        """Test truncation adds marker when exceeding budget."""
        resolver = TestDesignResolver(tmp_path, max_tokens=100)
        # Long content (~400 chars = ~100 tokens)
        content = "Line " * 100
        result = resolver._truncate_content(content, 10)
        assert "<!-- truncated: exceeded token budget -->" in result
        assert len(result) < len(content)

    def test_safe_read_file_not_found(self, tmp_path: Path) -> None:
        """Test _safe_read returns None for missing file."""
        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver._safe_read(tmp_path / "nonexistent.md")
        assert result is None

    def test_safe_read_empty_file(self, tmp_path: Path) -> None:
        """Test _safe_read returns None for empty file."""
        empty_file = tmp_path / "empty.md"
        empty_file.write_text("")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver._safe_read(empty_file)
        assert result is None

    def test_safe_read_valid_file(self, tmp_path: Path) -> None:
        """Test _safe_read returns content for valid file."""
        valid_file = tmp_path / "valid.md"
        valid_file.write_text("# Valid content")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver._safe_read(valid_file)
        assert result == "# Valid content"

    def test_safe_read_path_traversal_blocked(self, tmp_path: Path) -> None:
        """Test _safe_read blocks path traversal (F17 Fix)."""
        # Create a file outside base_path
        outside_file = tmp_path.parent / "outside.md"
        outside_file.write_text("secret")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver._safe_read(outside_file)
        assert result is None


class TestTestDesignResolver:
    """Tests for TestDesignResolver."""

    def test_artifact_type(self, tmp_path: Path) -> None:
        """Test artifact_type property."""
        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        assert resolver.artifact_type == "test-design"

    def test_resolve_epic_specific_takes_priority(self, tmp_path: Path) -> None:
        """Test epic-specific test-plan has priority over system (F9)."""
        # Create test-designs directory
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir()

        # Create both files
        (test_designs_dir / "test-design-epic-25.md").write_text("# Epic 25 plan")
        (tmp_path / "test-design-architecture.md").write_text("# System plan")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25)

        assert len(result) == 1
        assert any("epic-25" in path for path in result.keys())
        assert "# Epic 25 plan" in list(result.values())[0]

    def test_resolve_fallback_to_system(self, tmp_path: Path) -> None:
        """Test fallback to system test-design if no epic-specific."""
        (tmp_path / "test-design-architecture.md").write_text("# System plan")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25)

        assert len(result) == 1
        assert "# System plan" in list(result.values())[0]

    def test_resolve_not_found(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict if no artifacts found."""
        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25)
        assert result == {}

    def test_resolve_string_epic_id(self, tmp_path: Path) -> None:
        """Test resolve handles string epic ID (F2 Fix)."""
        test_designs_dir = tmp_path / "test-designs"
        test_designs_dir.mkdir()
        (test_designs_dir / "test-design-epic-testarch.md").write_text("# Testarch plan")

        resolver = TestDesignResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id="testarch")

        assert len(result) == 1
        assert "# Testarch plan" in list(result.values())[0]


class TestATDDResolver:
    """Tests for ATDDResolver."""

    def test_artifact_type(self, tmp_path: Path) -> None:
        """Test artifact_type property."""
        resolver = ATDDResolver(tmp_path, max_tokens=1000)
        assert resolver.artifact_type == "atdd"

    def test_resolve_requires_story_id(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict without story_id."""
        resolver = ATDDResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id=None)
        assert result == {}

    def test_resolve_finds_dotted_format(self, tmp_path: Path) -> None:
        """Test resolve finds files with dot format (F7 Fix)."""
        atdd_dir = tmp_path / "atdd-checklists"
        atdd_dir.mkdir()
        (atdd_dir / "atdd-checklist-25.1.md").write_text("# ATDD checklist")

        resolver = ATDDResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id="25.1")

        assert len(result) == 1
        assert "# ATDD checklist" in list(result.values())[0]

    def test_resolve_finds_hyphenated_format(self, tmp_path: Path) -> None:
        """Test resolve finds files with hyphen format (F7 Fix)."""
        atdd_dir = tmp_path / "atdd-checklists"
        atdd_dir.mkdir()
        (atdd_dir / "atdd-checklist-25-1.md").write_text("# ATDD checklist")

        resolver = ATDDResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id="25.1")

        assert len(result) == 1
        assert "# ATDD checklist" in list(result.values())[0]

    def test_resolve_respects_max_files(self, tmp_path: Path) -> None:
        """Test resolve respects max_files limit."""
        atdd_dir = tmp_path / "atdd-checklists"
        atdd_dir.mkdir()

        # Create 5 files
        for i in range(5):
            (atdd_dir / f"atdd-checklist-25-1-v{i}.md").write_text(f"# ATDD v{i}")

        resolver = ATDDResolver(tmp_path, max_tokens=10000, max_files=2)
        result = resolver.resolve(epic_id=25, story_id="25.1")

        # Should only load 2 files
        assert len(result) == 2

    def test_resolve_not_found(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict if no artifacts found."""
        resolver = ATDDResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id="25.1")
        assert result == {}


class TestTestReviewResolver:
    """Tests for TestReviewResolver."""

    def test_artifact_type(self, tmp_path: Path) -> None:
        """Test artifact_type property."""
        resolver = TestReviewResolver(tmp_path, max_tokens=1000)
        assert resolver.artifact_type == "test-review"

    def test_resolve_requires_story_id(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict without story_id."""
        resolver = TestReviewResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id=None)
        assert result == {}

    def test_resolve_finds_file(self, tmp_path: Path) -> None:
        """Test resolve finds test-review file."""
        reviews_dir = tmp_path / "test-reviews"
        reviews_dir.mkdir()
        (reviews_dir / "test-review-25.1.md").write_text("# Test review")

        resolver = TestReviewResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id="25.1")

        assert len(result) == 1
        assert "# Test review" in list(result.values())[0]

    def test_resolve_not_found(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict if no artifacts found."""
        resolver = TestReviewResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25, story_id="25.1")
        assert result == {}


class TestTraceResolver:
    """Tests for TraceResolver."""

    def test_artifact_type(self, tmp_path: Path) -> None:
        """Test artifact_type property."""
        resolver = TraceResolver(tmp_path, max_tokens=1000)
        assert resolver.artifact_type == "trace"

    def test_resolve_finds_file(self, tmp_path: Path) -> None:
        """Test resolve finds trace matrix file."""
        trace_dir = tmp_path / "traceability"
        trace_dir.mkdir()
        (trace_dir / "trace-matrix-epic-25.md").write_text("# Trace matrix")

        resolver = TraceResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25)

        assert len(result) == 1
        assert "# Trace matrix" in list(result.values())[0]

    def test_resolve_string_epic_id(self, tmp_path: Path) -> None:
        """Test resolve handles string epic ID (F2 Fix)."""
        trace_dir = tmp_path / "traceability"
        trace_dir.mkdir()
        (trace_dir / "trace-matrix-epic-testarch.md").write_text("# Testarch trace")

        resolver = TraceResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id="testarch")

        assert len(result) == 1
        assert "# Testarch trace" in list(result.values())[0]

    def test_resolve_not_found_is_ok(self, tmp_path: Path) -> None:
        """Test resolve returns empty dict if no artifacts (F19 Fix)."""
        resolver = TraceResolver(tmp_path, max_tokens=1000)
        result = resolver.resolve(epic_id=25)
        assert result == {}  # INFO log, no error
