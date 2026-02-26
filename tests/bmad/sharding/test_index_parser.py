"""Tests for sharding index_parser module."""

from __future__ import annotations

from pathlib import Path

from bmad_assist.bmad.sharding.index_parser import (
    MARKDOWN_LINK_PATTERN,
    parse_index_references,
)


class TestMarkdownLinkPattern:
    """Tests for MARKDOWN_LINK_PATTERN regex."""

    def test_matches_relative_link(self) -> None:
        """Pattern matches [text](./file.md) format."""
        match = MARKDOWN_LINK_PATTERN.search("[Epic 1](./epic-1.md)")
        assert match is not None
        assert match.group(1) == "Epic 1"
        assert match.group(2) == "epic-1.md"

    def test_matches_bare_link(self) -> None:
        """Pattern matches [text](file.md) format."""
        match = MARKDOWN_LINK_PATTERN.search("[Overview](overview.md)")
        assert match is not None
        assert match.group(1) == "Overview"
        assert match.group(2) == "overview.md"

    def test_matches_with_slash_prefix(self) -> None:
        """Pattern matches [text](/file.md) format."""
        match = MARKDOWN_LINK_PATTERN.search("[File](/core.md)")
        assert match is not None
        assert match.group(2) == "core.md"

    def test_no_match_for_non_md_link(self) -> None:
        """Pattern doesn't match non-.md links."""
        match = MARKDOWN_LINK_PATTERN.search("[Image](./image.png)")
        assert match is None

    def test_no_match_for_external_link(self) -> None:
        """Pattern doesn't match external URLs."""
        match = MARKDOWN_LINK_PATTERN.search("[Docs](https://example.com/docs.md)")
        assert match is None

    def test_multiple_matches(self) -> None:
        """Pattern finds all matches in content."""
        content = """
        - [First](./first.md)
        - [Second](second.md)
        - [Third](./third.md)
        """
        matches = MARKDOWN_LINK_PATTERN.findall(content)
        assert len(matches) == 3


class TestParseIndexReferences:
    """Tests for parse_index_references function."""

    def test_extracts_references_in_order(self, tmp_path: Path) -> None:
        """Extracts file references in document order."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""# Index

- [Epic 2](./epic-2-integration.md)
- [Epic 1](./epic-1-foundation.md)
""")
        refs = parse_index_references(index_path)

        assert refs == ["epic-2-integration.md", "epic-1-foundation.md"]

    def test_normalizes_relative_paths(self, tmp_path: Path) -> None:
        """Removes ./ prefix from paths."""
        index_path = tmp_path / "index.md"
        index_path.write_text("- [File](./file.md)")

        refs = parse_index_references(index_path)

        assert refs == ["file.md"]

    def test_excludes_index_md_self_reference(self, tmp_path: Path) -> None:
        """Excludes index.md if referenced."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""
- [Home](./index.md)
- [Content](./content.md)
""")
        refs = parse_index_references(index_path)

        assert refs == ["content.md"]

    def test_excludes_subdirectory_paths(self, tmp_path: Path) -> None:
        """Excludes paths with subdirectories (security)."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""
- [File](./file.md)
- [Subdir](./subdir/nested.md)
- [Escape](../../../etc/passwd.md)
""")
        refs = parse_index_references(index_path)

        assert refs == ["file.md"]

    def test_preserves_duplicates(self, tmp_path: Path) -> None:
        """Preserves duplicate references (caller handles)."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""
- [A](./file.md)
- [B](./file.md)
""")
        refs = parse_index_references(index_path)

        assert refs == ["file.md", "file.md"]

    def test_handles_missing_file(self, tmp_path: Path) -> None:
        """Returns empty list for missing index.md."""
        missing = tmp_path / "nonexistent" / "index.md"

        refs = parse_index_references(missing)

        assert refs == []

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Returns empty list for empty index.md."""
        index_path = tmp_path / "index.md"
        index_path.write_text("")

        refs = parse_index_references(index_path)

        assert refs == []

    def test_handles_no_links(self, tmp_path: Path) -> None:
        """Returns empty list for index with no links."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""# Index

Just text, no links here.
""")
        refs = parse_index_references(index_path)

        assert refs == []

    def test_extracts_from_table_of_contents(self, tmp_path: Path) -> None:
        """Extracts from typical ToC format."""
        index_path = tmp_path / "index.md"
        index_path.write_text("""# Architecture Document

## Table of Contents

- [Project Context](./project-context.md)
- [Core Decisions](./core-decisions.md)
- [Implementation Patterns](./implementation-patterns.md)
""")
        refs = parse_index_references(index_path)

        assert refs == [
            "project-context.md",
            "core-decisions.md",
            "implementation-patterns.md",
        ]

    def test_handles_encoding(self, tmp_path: Path) -> None:
        """Handles UTF-8 content correctly."""
        index_path = tmp_path / "index.md"
        index_path.write_text("- [Übersicht](./overview.md)", encoding="utf-8")

        refs = parse_index_references(index_path)

        assert refs == ["overview.md"]
