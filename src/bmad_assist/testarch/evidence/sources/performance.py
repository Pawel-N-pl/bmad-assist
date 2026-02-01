"""Performance evidence source.

This module provides the PerformanceSource class for collecting performance
metrics from Lighthouse JSON and k6 JSON files.

Usage:
    from bmad_assist.testarch.evidence.sources.performance import PerformanceSource

    source = PerformanceSource()
    evidence = source.collect(project_root)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.testarch.evidence.models import PerformanceEvidence
from bmad_assist.testarch.evidence.sources.base import EvidenceSource

if TYPE_CHECKING:
    from bmad_assist.testarch.config import SourceConfigModel
    from bmad_assist.testarch.evidence.models import SourceConfig

logger = logging.getLogger(__name__)

# Default patterns for performance files
DEFAULT_PERFORMANCE_PATTERNS = (
    "**/lighthouse-report.json",
    "**/k6-summary.json",
)


class PerformanceSource(EvidenceSource):
    """Evidence source for performance metrics.

    Supports parsing:
    - Lighthouse JSON format (performance scores, Core Web Vitals)
    - k6 JSON format (handleSummary output)

    """

    @property
    def source_type(self) -> str:
        """Return the type of evidence this source collects."""
        return "performance"

    @property
    def default_patterns(self) -> tuple[str, ...]:
        """Return default glob patterns for file discovery."""
        return DEFAULT_PERFORMANCE_PATTERNS

    def collect(
        self,
        project_root: Path,
        config: SourceConfigModel | SourceConfig | None = None,
    ) -> PerformanceEvidence | None:
        """Collect performance evidence from the project.

        Args:
            project_root: Root directory of the project.
            config: Optional source configuration. Accepts either:
                - SourceConfigModel (Pydantic model from YAML config)
                - SourceConfig (frozen dataclass for internal use)
                - None (use default patterns)

        Returns:
            PerformanceEvidence if found, None otherwise.

        """
        patterns = self._get_patterns(config)

        # Find the most recently modified matching file
        best_file: Path | None = None
        best_mtime: float = 0.0

        for pattern in patterns:
            for match in project_root.glob(pattern):
                if match.is_file():
                    try:
                        mtime = match.stat().st_mtime
                        if mtime > best_mtime:
                            best_mtime = mtime
                            best_file = match
                    except OSError:
                        continue

        if best_file is None:
            logger.debug("No performance files found in %s", project_root)
            return None

        logger.debug("Parsing performance file: %s", best_file)

        # Determine format and parse
        try:
            content = best_file.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse performance file %s: %s", best_file, e)
            return None

        # Detect format
        if "categories" in data or "lighthouseVersion" in data:
            return self._parse_lighthouse(data, best_file)
        elif "metrics" in data:
            return self._parse_k6(data, best_file)
        else:
            logger.warning("Unknown performance format in %s", best_file)
            return None

    def _parse_lighthouse(
        self,
        data: dict[str, Any],
        file_path: Path,
    ) -> PerformanceEvidence | None:
        """Parse Lighthouse JSON format.

        Format:
        {
          "categories": {
            "performance": {"score": 0.89},
            "accessibility": {"score": 0.95}
          },
          "audits": {
            "first-contentful-paint": {"numericValue": 1234.5}
          }
        }

        """
        categories = data.get("categories", {})
        scores: dict[str, float] = {}

        for cat_name, cat_data in categories.items():
            score = cat_data.get("score")
            if score is not None:
                scores[cat_name] = float(score)

        if not scores:
            logger.warning("No scores found in Lighthouse report: %s", file_path)
            return PerformanceEvidence(
                lighthouse_scores=None,
                k6_metrics=None,
                source=str(file_path),
            )

        return PerformanceEvidence(
            lighthouse_scores=scores,
            k6_metrics=None,
            source=str(file_path),
        )

    def _parse_k6(
        self,
        data: dict[str, Any],
        file_path: Path,
    ) -> PerformanceEvidence | None:
        """Parse k6 JSON format (handleSummary output).

        Format:
        {
          "metrics": {
            "http_reqs": {"values": {"count": 100, "rate": 9.77}},
            "http_req_duration": {"values": {"avg": 234.56, "p(95)": 567.89}}
          }
        }

        """
        metrics_data = data.get("metrics", {})
        k6_metrics: dict[str, Any] = {}

        # Extract key metrics
        http_reqs = metrics_data.get("http_reqs", {}).get("values", {})
        if http_reqs:
            k6_metrics["requests_count"] = http_reqs.get("count", 0)
            k6_metrics["requests_per_sec"] = http_reqs.get("rate", 0)

        http_duration = metrics_data.get("http_req_duration", {}).get("values", {})
        if http_duration:
            k6_metrics["response_time_avg_ms"] = http_duration.get("avg", 0)
            k6_metrics["response_time_p95_ms"] = http_duration.get("p(95)", 0)

        # Error rate
        http_req_failed = metrics_data.get("http_req_failed", {}).get("values", {})
        if http_req_failed:
            k6_metrics["error_rate"] = http_req_failed.get("rate", 0)

        # Iterations
        iterations = metrics_data.get("iterations", {}).get("values", {})
        if iterations:
            k6_metrics["iterations_count"] = iterations.get("count", 0)
            k6_metrics["iterations_per_sec"] = iterations.get("rate", 0)

        if not k6_metrics:
            logger.warning("No metrics found in k6 report: %s", file_path)
            return PerformanceEvidence(
                lighthouse_scores=None,
                k6_metrics=None,
                source=str(file_path),
            )

        return PerformanceEvidence(
            lighthouse_scores=None,
            k6_metrics=k6_metrics,
            source=str(file_path),
        )
