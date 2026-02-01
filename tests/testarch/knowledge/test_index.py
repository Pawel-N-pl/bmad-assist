"""Tests for CSV index parsing."""

import pytest
from pathlib import Path

from bmad_assist.core.exceptions import ParserError
from bmad_assist.testarch.knowledge.index import parse_index, REQUIRED_COLUMNS


class TestParseIndex:
    """Tests for parse_index function."""

    def test_parse_valid_index(self, mock_knowledge_dir: Path) -> None:
        """Test parsing a valid index file."""
        index_path = mock_knowledge_dir / "_bmad" / "tea" / "testarch" / "tea-index.csv"
        fragments = parse_index(index_path)

        assert len(fragments) == 4
        assert fragments[0].id == "fixture-architecture"
        assert fragments[0].name == "Fixture Architecture"
        assert fragments[0].tags == ("fixtures", "architecture", "playwright")
        assert fragments[0].fragment_file == "knowledge/fixture-architecture.md"

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        """Test parsing a missing file returns empty list."""
        index_path = tmp_path / "nonexistent.csv"
        fragments = parse_index(index_path)
        assert fragments == []

    def test_parse_empty_file(self, tmp_path: Path) -> None:
        """Test parsing an empty file returns empty list."""
        index_path = tmp_path / "empty.csv"
        index_path.write_text("")
        fragments = parse_index(index_path)
        assert fragments == []

    def test_parse_whitespace_only_file(self, tmp_path: Path) -> None:
        """Test parsing file with only whitespace returns empty list."""
        index_path = tmp_path / "whitespace.csv"
        index_path.write_text("   \n  \n")
        fragments = parse_index(index_path)
        assert fragments == []

    def test_parse_missing_required_columns(
        self, tmp_path: Path, malformed_index_content: str
    ) -> None:
        """Test parsing file with missing required columns raises error."""
        index_path = tmp_path / "malformed.csv"
        index_path.write_text(malformed_index_content)

        with pytest.raises(ParserError, match="missing required columns"):
            parse_index(index_path)

    def test_parse_quoted_fields(self, tmp_path: Path, quoted_fields_index_content: str) -> None:
        """Test parsing CSV with quoted fields containing commas."""
        index_path = tmp_path / "quoted.csv"
        index_path.write_text(quoted_fields_index_content)

        # Create the fragment file
        knowledge_dir = tmp_path / "knowledge"
        knowledge_dir.mkdir()
        (knowledge_dir / "test.md").write_text("content")

        fragments = parse_index(index_path)
        assert len(fragments) == 1
        # Name should include the comma
        assert fragments[0].name == "Test Name, with comma"
        # Description should include commas
        assert fragments[0].description == "Description, with comma, multiple"
        # Tags should be parsed correctly
        assert fragments[0].tags == ("tag1", "tag2", "tag3")

    def test_parse_tags_whitespace_handling(self, tmp_path: Path) -> None:
        """Test that tags are stripped of whitespace."""
        index_path = tmp_path / "tags.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test-id,Test,Desc," tag1 , tag2 , tag3 ",test.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].tags == ("tag1", "tag2", "tag3")

    def test_parse_empty_tags(self, tmp_path: Path) -> None:
        """Test that empty tags field results in empty tuple."""
        index_path = tmp_path / "empty_tags.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test-id,Test,Desc,,test.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].tags == ()

    def test_skip_row_missing_id(self, tmp_path: Path) -> None:
        """Test that rows with missing id are skipped."""
        index_path = tmp_path / "missing_id.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
,Test,Desc,tag1,test.md
valid-id,Test2,Desc2,tag2,test2.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].id == "valid-id"

    def test_skip_row_missing_fragment_file(self, tmp_path: Path) -> None:
        """Test that rows with missing fragment_file are skipped."""
        index_path = tmp_path / "missing_file.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test-id,Test,Desc,tag1,
valid-id,Test2,Desc2,tag2,test2.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].id == "valid-id"

    def test_reject_absolute_path(self, tmp_path: Path) -> None:
        """Test that absolute fragment paths are rejected."""
        index_path = tmp_path / "absolute.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test-id,Test,Desc,tag1,/etc/passwd
valid-id,Test2,Desc2,tag2,test2.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].id == "valid-id"

    def test_reject_path_traversal(self, tmp_path: Path) -> None:
        """Test that path traversal is rejected."""
        index_path = tmp_path / "traversal.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
test-id,Test,Desc,tag1,../../../etc/passwd
valid-id,Test2,Desc2,tag2,test2.md
"""
        )
        fragments = parse_index(index_path)
        assert len(fragments) == 1
        assert fragments[0].id == "valid-id"

    def test_required_columns_set(self) -> None:
        """Test that REQUIRED_COLUMNS contains expected columns."""
        assert REQUIRED_COLUMNS == {"id", "name", "description", "tags", "fragment_file"}

    def test_parse_preserves_order(self, tmp_path: Path) -> None:
        """Test that fragments are returned in CSV order."""
        index_path = tmp_path / "order.csv"
        index_path.write_text(
            """id,name,description,tags,fragment_file
z-last,Last,Desc,tag1,z.md
a-first,First,Desc,tag1,a.md
m-middle,Middle,Desc,tag1,m.md
"""
        )
        fragments = parse_index(index_path)
        ids = [f.id for f in fragments]
        assert ids == ["z-last", "a-first", "m-middle"]
