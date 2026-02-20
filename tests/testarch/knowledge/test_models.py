"""Tests for KnowledgeFragment and KnowledgeIndex models."""

from datetime import datetime

import pytest

from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex


class TestKnowledgeFragment:
    """Tests for KnowledgeFragment dataclass."""

    def test_create_valid_fragment(self) -> None:
        """Test creating a valid fragment."""
        fragment = KnowledgeFragment(
            id="fixture-architecture",
            name="Fixture Architecture",
            description="Composable patterns",
            tags=("fixtures", "architecture"),
            fragment_file="knowledge/fixture-architecture.md",
        )
        assert fragment.id == "fixture-architecture"
        assert fragment.name == "Fixture Architecture"
        assert fragment.tags == ("fixtures", "architecture")
        assert fragment.fragment_file == "knowledge/fixture-architecture.md"

    def test_empty_id_raises_error(self) -> None:
        """Test that empty id raises ValueError."""
        with pytest.raises(ValueError, match="id cannot be empty"):
            KnowledgeFragment(
                id="",
                name="Test",
                description="Desc",
                tags=(),
                fragment_file="test.md",
            )

    def test_empty_fragment_file_raises_error(self) -> None:
        """Test that empty fragment_file raises ValueError."""
        with pytest.raises(ValueError, match="fragment_file cannot be empty"):
            KnowledgeFragment(
                id="test",
                name="Test",
                description="Desc",
                tags=(),
                fragment_file="",
            )

    def test_fragment_is_immutable(self) -> None:
        """Test that fragment is frozen (immutable)."""
        fragment = KnowledgeFragment(
            id="test",
            name="Test",
            description="Desc",
            tags=("tag1",),
            fragment_file="test.md",
        )
        with pytest.raises(AttributeError):
            fragment.id = "new-id"  # type: ignore

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        fragment = KnowledgeFragment(
            id="test",
            name="Test",
            description="Desc",
            tags=("tag1", "tag2"),
            fragment_file="test.md",
        )
        d = fragment.to_dict()
        assert d["id"] == "test"
        assert d["tags"] == ["tag1", "tag2"]  # List, not tuple
        assert isinstance(d["tags"], list)


class TestKnowledgeIndex:
    """Tests for KnowledgeIndex dataclass."""

    def test_create_empty_index(self) -> None:
        """Test creating an empty index."""
        index = KnowledgeIndex(path="/path/to/index.csv")
        assert index.path == "/path/to/index.csv"
        assert index.fragments == {}
        assert index.fragment_order == ()

    def test_create_index_with_fragments(self) -> None:
        """Test creating index with fragments."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=("tag1",),
            fragment_file="f1.md",
        )
        f2 = KnowledgeFragment(
            id="f2",
            name="Fragment 2",
            description="Desc",
            tags=("tag2",),
            fragment_file="f2.md",
        )
        index = KnowledgeIndex(
            path="/path/to/index.csv",
            fragments={"f1": f1, "f2": f2},
            fragment_order=("f1", "f2"),
        )
        assert len(index.fragments) == 2
        assert index.fragment_order == ("f1", "f2")

    def test_get_fragment(self) -> None:
        """Test getting fragment by ID."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=(),
            fragment_file="f1.md",
        )
        index = KnowledgeIndex(
            path="/path",
            fragments={"f1": f1},
            fragment_order=("f1",),
        )
        assert index.get_fragment("f1") == f1
        assert index.get_fragment("nonexistent") is None

    def test_get_fragments_by_ids(self) -> None:
        """Test getting multiple fragments by ID list."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=(),
            fragment_file="f1.md",
        )
        f2 = KnowledgeFragment(
            id="f2",
            name="Fragment 2",
            description="Desc",
            tags=(),
            fragment_file="f2.md",
        )
        index = KnowledgeIndex(
            path="/path",
            fragments={"f1": f1, "f2": f2},
            fragment_order=("f1", "f2"),
        )
        result = index.get_fragments_by_ids(["f2", "f1", "nonexistent"])
        assert len(result) == 2
        # Order matches input, not fragment_order
        assert result[0].id == "f2"
        assert result[1].id == "f1"

    def test_get_fragments_by_tags_or_logic(self) -> None:
        """Test getting fragments by tags (OR logic)."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=("fixtures", "architecture"),
            fragment_file="f1.md",
        )
        f2 = KnowledgeFragment(
            id="f2",
            name="Fragment 2",
            description="Desc",
            tags=("network", "stability"),
            fragment_file="f2.md",
        )
        f3 = KnowledgeFragment(
            id="f3",
            name="Fragment 3",
            description="Desc",
            tags=("data", "fixtures"),
            fragment_file="f3.md",
        )
        index = KnowledgeIndex(
            path="/path",
            fragments={"f1": f1, "f2": f2, "f3": f3},
            fragment_order=("f1", "f2", "f3"),
        )
        # OR logic: matches any tag
        result = index.get_fragments_by_tags(["fixtures"])
        assert len(result) == 2
        assert result[0].id == "f1"
        assert result[1].id == "f3"

    def test_get_fragments_by_tags_with_exclusion(self) -> None:
        """Test excluding fragments by tags."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=("fixtures", "playwright"),
            fragment_file="f1.md",
        )
        f2 = KnowledgeFragment(
            id="f2",
            name="Fragment 2",
            description="Desc",
            tags=("fixtures", "playwright-utils"),
            fragment_file="f2.md",
        )
        index = KnowledgeIndex(
            path="/path",
            fragments={"f1": f1, "f2": f2},
            fragment_order=("f1", "f2"),
        )
        result = index.get_fragments_by_tags(["fixtures"], exclude_tags=["playwright-utils"])
        assert len(result) == 1
        assert result[0].id == "f1"

    def test_get_fragments_preserves_order(self) -> None:
        """Test that results preserve fragment_order."""
        fragments = {}
        for i in range(5):
            fragments[f"f{i}"] = KnowledgeFragment(
                id=f"f{i}",
                name=f"Fragment {i}",
                description="Desc",
                tags=("common",),
                fragment_file=f"f{i}.md",
            )
        index = KnowledgeIndex(
            path="/path",
            fragments=fragments,
            fragment_order=("f4", "f2", "f0", "f3", "f1"),
        )
        result = index.get_fragments_by_tags(["common"])
        ids = [f.id for f in result]
        assert ids == ["f4", "f2", "f0", "f3", "f1"]

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        f1 = KnowledgeFragment(
            id="f1",
            name="Fragment 1",
            description="Desc",
            tags=("tag1",),
            fragment_file="f1.md",
        )
        now = datetime.now()
        index = KnowledgeIndex(
            path="/path",
            fragments={"f1": f1},
            loaded_at=now,
            fragment_order=("f1",),
        )
        d = index.to_dict()
        assert d["path"] == "/path"
        assert "f1" in d["fragments"]
        assert d["fragment_order"] == ["f1"]
        assert d["loaded_at"] == now.isoformat()
