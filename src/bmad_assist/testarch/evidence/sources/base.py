"""Abstract base class for evidence sources.

This module provides the EvidenceSource ABC that all evidence source
implementations must inherit from.

Usage:
    from bmad_assist.testarch.evidence.sources.base import EvidenceSource

    class MySource(EvidenceSource):
        @property
        def source_type(self) -> str:
            return "my_evidence"

        @property
        def default_patterns(self) -> tuple[str, ...]:
            return ("*.json",)

        def collect(self, project_root, config=None):
            # Implementation here
            ...
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bmad_assist.testarch.config import SourceConfigModel
    from bmad_assist.testarch.evidence.models import SourceConfig


class EvidenceSource(ABC):
    """Abstract base class for evidence sources.

    Defines the interface for collecting evidence from various sources
    such as coverage reports, test results, security scans, and
    performance metrics.

    """

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the type of evidence this source collects.

        Returns:
            Source type identifier (e.g., "coverage", "test_results").

        """
        ...

    @property
    @abstractmethod
    def default_patterns(self) -> tuple[str, ...]:
        """Return default glob patterns for file discovery.

        Returns:
            Tuple of glob patterns to search for evidence files.

        """
        ...

    @abstractmethod
    def collect(
        self,
        project_root: Path,
        config: "SourceConfigModel | SourceConfig | None" = None,
    ) -> Any | None:
        """Collect evidence from the project.

        Args:
            project_root: Root directory of the project.
            config: Optional source configuration. Accepts either:
                - SourceConfigModel (Pydantic model from YAML config)
                - SourceConfig (frozen dataclass for internal use)
                - None (use default patterns)

        Returns:
            Evidence dataclass instance, or None if evidence not found
            or collection failed (with warning logged).

        """
        ...

    def _get_patterns(
        self,
        config: "SourceConfigModel | SourceConfig | None",
    ) -> tuple[str, ...]:
        """Extract patterns from config, converting list to tuple if needed.

        Args:
            config: Source configuration (Pydantic model or dataclass).

        Returns:
            Tuple of patterns, or default_patterns if config is None.

        """
        if config is None:
            return self.default_patterns

        patterns = config.patterns
        if not patterns:
            return self.default_patterns

        # Convert list to tuple if needed (SourceConfigModel uses list)
        if isinstance(patterns, list):
            return tuple(patterns)

        return patterns

    def _get_timeout(
        self,
        config: "SourceConfigModel | SourceConfig | None",
        default: int = 30,
    ) -> int:
        """Extract timeout from config.

        Args:
            config: Source configuration.
            default: Default timeout if config is None.

        Returns:
            Timeout in seconds.

        """
        if config is None:
            return default
        return config.timeout
