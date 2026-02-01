"""Data models for TEA Knowledge Base.

This module provides immutable data classes for knowledge fragment
metadata and index state.

Usage:
    from bmad_assist.testarch.knowledge.models import KnowledgeFragment, KnowledgeIndex

    fragment = KnowledgeFragment(
        id="fixture-architecture",
        name="Fixture Architecture",
        description="Composable fixture patterns",
        tags=["fixtures", "architecture"],
        fragment_file="knowledge/fixture-architecture.md",
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class KnowledgeFragment:
    """Immutable knowledge fragment metadata.

    Represents a single entry in the TEA knowledge index with
    metadata about the knowledge fragment content.

    Attributes:
        id: Unique identifier (kebab-case).
        name: Human-readable title.
        description: 1-sentence summary.
        tags: List of metadata tags (frameworks, domains, patterns).
        fragment_file: Relative path to markdown file.

    """

    id: str
    name: str
    description: str
    tags: tuple[str, ...]  # Tuple for immutability
    fragment_file: str

    def __post_init__(self) -> None:
        """Validate fragment data."""
        if not self.id:
            raise ValueError("Fragment id cannot be empty")
        if not self.fragment_file:
            raise ValueError("Fragment fragment_file cannot be empty")

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "fragment_file": self.fragment_file,
        }


@dataclass(frozen=True)
class KnowledgeIndex:
    """Immutable knowledge index state.

    Represents the parsed state of tea-index.csv with
    all fragment metadata indexed by ID.

    Attributes:
        path: Path to the tea-index.csv file.
        fragments: Dictionary mapping fragment ID to KnowledgeFragment.
        loaded_at: Timestamp when index was loaded.
        fragment_order: Ordered list of fragment IDs (preserves CSV order).

    """

    path: str
    fragments: dict[str, KnowledgeFragment] = field(default_factory=dict)
    loaded_at: datetime = field(default_factory=datetime.now)
    fragment_order: tuple[str, ...] = field(default_factory=tuple)

    def get_fragment(self, fragment_id: str) -> KnowledgeFragment | None:
        """Get fragment by ID.

        Args:
            fragment_id: Fragment identifier.

        Returns:
            KnowledgeFragment if found, None otherwise.

        """
        return self.fragments.get(fragment_id)

    def get_fragments_by_ids(
        self,
        ids: list[str],
    ) -> list[KnowledgeFragment]:
        """Get fragments by ID list, preserving order.

        Args:
            ids: List of fragment IDs.

        Returns:
            List of found fragments in ID order.

        """
        return [self.fragments[fid] for fid in ids if fid in self.fragments]

    def get_fragments_by_tags(
        self,
        tags: list[str],
        exclude_tags: list[str] | None = None,
    ) -> list[KnowledgeFragment]:
        """Get fragments matching any tag, excluding specified tags.

        Args:
            tags: Tags to match (OR logic).
            exclude_tags: Tags to exclude.

        Returns:
            List of matching fragments in index order.

        """
        exclude_set = set(exclude_tags) if exclude_tags else set()
        result = []

        for fragment_id in self.fragment_order:
            fragment = self.fragments.get(fragment_id)
            if fragment is None:
                continue

            # Check for excluded tags
            if exclude_set and exclude_set.intersection(fragment.tags):
                continue

            # Check for matching tags (OR logic)
            if set(tags).intersection(fragment.tags):
                result.append(fragment)

        return result

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation suitable for YAML/JSON serialization.

        """
        return {
            "path": self.path,
            "fragments": {fid: f.to_dict() for fid, f in self.fragments.items()},
            "loaded_at": self.loaded_at.isoformat(),
            "fragment_order": list(self.fragment_order),
        }
