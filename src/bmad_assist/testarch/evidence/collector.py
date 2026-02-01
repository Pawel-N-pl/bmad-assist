"""Evidence Context Collector for TEA workflows.

This module provides the main collector class for gathering evidence
from test artifacts, coverage reports, security scans, and performance metrics.

Usage:
    from bmad_assist.testarch.evidence import get_evidence_collector

    collector = get_evidence_collector(project_root)
    evidence = collector.collect_all()

With configuration (Story 25.5):
    from bmad_assist.testarch.config import EvidenceConfig, SourceConfigModel

    config = EvidenceConfig(
        enabled=True,
        coverage=SourceConfigModel(patterns=["coverage/lcov.info"]),
        security=SourceConfigModel(enabled=False),
    )
    evidence = collector.collect_all(config)
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from bmad_assist.testarch.evidence.models import EvidenceContext

if TYPE_CHECKING:
    from bmad_assist.testarch.config import EvidenceConfig

logger = logging.getLogger(__name__)

# Singleton storage for collectors (per project root)
_collectors: dict[Path, EvidenceContextCollector] = {}
_collector_lock = Lock()


def get_evidence_collector(project_root: Path) -> EvidenceContextCollector:
    """Get or create collector for project root (singleton per root).

    Thread-safe: Uses lock to prevent race conditions on concurrent access.

    Args:
        project_root: Project root directory.

    Returns:
        EvidenceContextCollector instance for the project.

    """
    resolved = project_root.resolve()
    with _collector_lock:
        if resolved not in _collectors:
            _collectors[resolved] = EvidenceContextCollector(resolved)
        return _collectors[resolved]


def clear_all_collectors() -> None:
    """Clear all singleton collectors.

    Removes all cached EvidenceContextCollector instances from the singleton
    storage. Used primarily for testing to ensure test isolation.

    """
    with _collector_lock:
        _collectors.clear()


class EvidenceContextCollector:
    """Collector for all evidence types with caching.

    Provides lazy loading of evidence with mtime-based cache invalidation.

    Attributes:
        project_root: Project root directory.

    """

    def __init__(self, project_root: Path) -> None:
        """Initialize collector with project root.

        Args:
            project_root: Project root directory.

        """
        self._project_root = project_root.resolve()
        self._cache_lock = Lock()
        self._cached_evidence: EvidenceContext | None = None
        self._cached_at: float = 0.0
        self._cached_file_mtimes: dict[str, float] = {}

    @property
    def project_root(self) -> Path:
        """Get project root path."""
        return self._project_root

    def _is_cache_valid(self) -> bool:
        """Check if cached evidence is still valid based on file mtimes.

        Returns:
            True if cache is valid (no evidence files modified since caching).

        """
        if self._cached_evidence is None:
            return False

        # Check if source files have been modified
        current_file_mtimes = self._get_evidence_file_mtmes()
        return current_file_mtimes == self._cached_file_mtimes

    def _get_evidence_file_mtmes(self) -> dict[str, float]:
        """Get mtimes of all discovered evidence files.

        Returns:
            Dictionary mapping file paths to their mtimes.

        """
        from bmad_assist.testarch.evidence.sources.coverage import CoverageSource
        from bmad_assist.testarch.evidence.sources.performance import PerformanceSource
        from bmad_assist.testarch.evidence.sources.security import SecuritySource
        from bmad_assist.testarch.evidence.sources.test_results import TestResultsSource

        mtimes: dict[str, float] = {}

        # Collect mtimes from all source types
        for source_cls in (CoverageSource, TestResultsSource, SecuritySource, PerformanceSource):
            source = source_cls()
            for pattern in source.default_patterns:
                for match in self._project_root.glob(pattern):
                    if match.is_file():
                        try:
                            mtimes[str(match)] = match.stat().st_mtime
                        except OSError:
                            continue

        return mtimes

    def collect_all(
        self,
        config: EvidenceConfig | None = None,
    ) -> EvidenceContext:
        """Collect all available evidence with mtime-based caching.

        Args:
            config: Optional EvidenceConfig for controlling collection.
                If None, uses default patterns for all sources.
                If config.enabled is False, returns empty EvidenceContext.
                Individual source configs control per-source behavior.

        Returns:
            EvidenceContext with all collected evidence.
            Fields are None for sources that failed, are disabled, or have no data.

        """
        # Check cache validity first
        with self._cache_lock:
            if self._is_cache_valid() and self._cached_evidence is not None:
                logger.debug("Returning cached evidence for: %s", self._project_root)
                return self._cached_evidence

            logger.debug("Starting evidence collection for: %s", self._project_root)

            # Check master switch - if disabled, return empty context
            if config is not None and not config.enabled:
                logger.debug("Evidence collection disabled by config")
                collected_at = datetime.now(UTC).isoformat()
                return EvidenceContext(
                    coverage=None,
                    test_results=None,
                    security=None,
                    performance=None,
                    collected_at=collected_at,
                )

            # Import sources lazily to avoid circular imports
            from bmad_assist.testarch.evidence.sources.coverage import CoverageSource
            from bmad_assist.testarch.evidence.sources.performance import PerformanceSource
            from bmad_assist.testarch.evidence.sources.security import SecuritySource
            from bmad_assist.testarch.evidence.sources.test_results import TestResultsSource

            # Collect from each source, passing per-source config
            coverage_source = CoverageSource()
            test_results_source = TestResultsSource()
            security_source = SecuritySource()
            performance_source = PerformanceSource()

            # Collect coverage if enabled
            coverage_config = config.coverage if config else None
            if coverage_config is not None and not coverage_config.enabled:
                coverage = None
            else:
                coverage = coverage_source.collect(self._project_root, coverage_config)

            # Collect test results if enabled
            test_results_config = config.test_results if config else None
            if test_results_config is not None and not test_results_config.enabled:
                test_results = None
            else:
                test_results = test_results_source.collect(
                    self._project_root, test_results_config
                )

            # Collect security if enabled
            security_config = config.security if config else None
            if security_config is not None and not security_config.enabled:
                security = None
            else:
                security = security_source.collect(self._project_root, security_config)

            # Collect performance if enabled
            performance_config = config.performance if config else None
            if performance_config is not None and not performance_config.enabled:
                performance = None
            else:
                performance = performance_source.collect(
                    self._project_root, performance_config
                )

            collected_at = datetime.now(UTC).isoformat()

            evidence = EvidenceContext(
                coverage=coverage,
                test_results=test_results,
                security=security,
                performance=performance,
                collected_at=collected_at,
            )

            # Update cache
            self._cached_evidence = evidence
            self._cached_at = time.time()
            self._cached_file_mtimes = self._get_evidence_file_mtmes()

            logger.debug("Evidence collection complete and cached")
            return evidence
