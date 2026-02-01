"""Coverage evidence source.

This module provides the CoverageSource class for collecting coverage
data from lcov.info, Istanbul JSON, and pytest-cov .coverage files.

Usage:
    from bmad_assist.testarch.evidence.sources.coverage import CoverageSource

    source = CoverageSource()
    evidence = source.collect(project_root)
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from bmad_assist.testarch.evidence.models import CoverageEvidence
from bmad_assist.testarch.evidence.sources.base import EvidenceSource

if TYPE_CHECKING:
    from bmad_assist.testarch.config import SourceConfigModel
    from bmad_assist.testarch.evidence.models import SourceConfig

logger = logging.getLogger(__name__)

# Default patterns for coverage files
DEFAULT_COVERAGE_PATTERNS = (
    "coverage/lcov.info",
    "**/coverage-summary.json",
    ".coverage",
)


class CoverageSource(EvidenceSource):
    """Evidence source for code coverage data.

    Supports parsing:
    - lcov.info format (line-based text)
    - Istanbul/NYC coverage-summary.json format
    - pytest-cov .coverage SQLite database

    """

    @property
    def source_type(self) -> str:
        """Return the type of evidence this source collects."""
        return "coverage"

    @property
    def default_patterns(self) -> tuple[str, ...]:
        """Return default glob patterns for file discovery."""
        return DEFAULT_COVERAGE_PATTERNS

    def collect(
        self,
        project_root: Path,
        config: SourceConfigModel | SourceConfig | None = None,
    ) -> CoverageEvidence | None:
        """Collect coverage evidence from the project.

        Args:
            project_root: Root directory of the project.
            config: Optional source configuration. Accepts either:
                - SourceConfigModel (Pydantic model from YAML config)
                - SourceConfig (frozen dataclass for internal use)
                - None (use default patterns)

        Returns:
            CoverageEvidence if found, None otherwise.

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
            logger.debug("No coverage files found in %s", project_root)
            return None

        logger.debug("Parsing coverage file: %s", best_file)

        # Determine format and parse
        if best_file.name == "lcov.info" or best_file.suffix == ".info":
            return self._parse_lcov(best_file)
        elif best_file.name == "coverage-summary.json" or best_file.suffix == ".json":
            return self._parse_istanbul(best_file)
        elif best_file.name == ".coverage":
            return self._parse_pytest_cov(best_file)
        else:
            logger.warning("Unknown coverage format: %s", best_file)
            return None

    def _parse_lcov(self, file_path: Path) -> CoverageEvidence | None:
        """Parse lcov.info format.

        LCOV format:
        TN:TestName
        SF:/path/to/file.js
        DA:1,1
        DA:2,0
        LF:20  (lines found)
        LH:15  (lines hit)
        end_of_record

        """
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("Failed to read lcov file %s: %s", file_path, e)
            return None

        total_lines = 0
        covered_lines = 0
        uncovered_files: list[str] = []
        current_file: str | None = None
        file_hits = 0
        file_lines = 0

        for line in content.splitlines():
            line = line.strip()
            if line.startswith("SF:"):
                current_file = line[3:]
                file_hits = 0
                file_lines = 0
            elif line.startswith("LF:"):
                with contextlib.suppress(ValueError):
                    file_lines = int(line[3:])
            elif line.startswith("LH:"):
                with contextlib.suppress(ValueError):
                    file_hits = int(line[3:])
            elif line == "end_of_record":
                total_lines += file_lines
                covered_lines += file_hits
                if current_file and file_hits == 0 and file_lines > 0:
                    uncovered_files.append(current_file)
                current_file = None

        if total_lines == 0:
            logger.warning("No coverage data found in lcov file: %s", file_path)
            return CoverageEvidence(
                total_lines=0,
                covered_lines=0,
                coverage_percent=0.0,
                uncovered_files=(),
                source=str(file_path),
            )

        coverage_percent = (covered_lines / total_lines) * 100

        return CoverageEvidence(
            total_lines=total_lines,
            covered_lines=covered_lines,
            coverage_percent=round(coverage_percent, 2),
            uncovered_files=tuple(uncovered_files),
            source=str(file_path),
        )

    def _parse_istanbul(self, file_path: Path) -> CoverageEvidence | None:
        """Parse Istanbul/NYC coverage-summary.json format.

        Format:
        {
          "total": {
            "lines": {"total": 161, "covered": 161, "pct": 100},
            ...
          }
        }

        """
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse Istanbul JSON %s: %s", file_path, e)
            return None

        total_data = data.get("total", {})
        lines_data = total_data.get("lines", {})

        total_lines = lines_data.get("total", 0)
        covered_lines = lines_data.get("covered", 0)
        coverage_percent = lines_data.get("pct", 0.0)

        # Find uncovered files
        uncovered_files: list[str] = []
        for file_path_key, file_data in data.items():
            if file_path_key == "total":
                continue
            file_lines = file_data.get("lines", {})
            if file_lines.get("covered", 0) == 0 and file_lines.get("total", 0) > 0:
                uncovered_files.append(file_path_key)

        return CoverageEvidence(
            total_lines=total_lines,
            covered_lines=covered_lines,
            coverage_percent=float(coverage_percent),
            uncovered_files=tuple(uncovered_files),
            source=str(file_path),
        )

    def _parse_pytest_cov(self, file_path: Path) -> CoverageEvidence | None:
        """Parse pytest-cov .coverage SQLite database.

        Uses the coverage library API when available, falls back to
        sqlite3 for basic parsing.

        """
        try:
            from coverage import Coverage

            cov = Coverage(data_file=str(file_path))
            cov.load()

            # Get coverage data
            data = cov.get_data()
            measured_files = data.measured_files()

            total_lines = 0
            covered_lines = 0
            uncovered_files: list[str] = []

            for file_name in measured_files:
                # Get lines that were executed (covered)
                executed_lines = data.lines(file_name) or []
                file_covered = len(executed_lines)

                # Get all measurable lines using the coverage API
                # _analyze provides arc data which includes executable lines
                try:
                    arcs = data._arcs(file_name) if hasattr(data, "_arcs") else None
                    if arcs:
                        # Extract unique line numbers from arcs
                        measurable_lines = set()
                        for start, end in arcs:
                            measurable_lines.add(start)
                            if end is not None:
                                measurable_lines.add(end)
                        file_total = len(measurable_lines)
                    else:
                        # Fallback: use executed lines as total (may over-report coverage)
                        file_total = file_covered
                except Exception:
                    # Fallback if arcs unavailable
                    file_total = file_covered

                total_lines += file_total
                covered_lines += file_covered

                if file_covered == 0 and file_total > 0:
                    uncovered_files.append(file_name)

            # For proper coverage we need to get missing lines too
            # This requires analysis which is more complex
            # For now, report what we have
            coverage_percent = (covered_lines / total_lines * 100) if total_lines > 0 else 0.0

            return CoverageEvidence(
                total_lines=total_lines,
                covered_lines=covered_lines,
                coverage_percent=round(coverage_percent, 2),
                uncovered_files=tuple(uncovered_files),
                source=str(file_path),
            )

        except ImportError:
            logger.debug("coverage library not available, using sqlite3 fallback")
            return self._parse_pytest_cov_sqlite(file_path)
        except Exception as e:
            logger.warning("Failed to parse .coverage file %s: %s", file_path, e)
            return None

    def _parse_pytest_cov_sqlite(self, file_path: Path) -> CoverageEvidence | None:
        """Fallback parser using sqlite3 directly."""
        import sqlite3

        try:
            conn = sqlite3.connect(str(file_path))
            cursor = conn.cursor()

            # Get file list
            cursor.execute("SELECT id, path FROM file")
            files = cursor.fetchall()

            total_lines = 0
            covered_lines = 0
            uncovered_files: list[str] = []

            for file_id, file_path_str in files:
                # Get line data for each file
                cursor.execute(
                    "SELECT numbits FROM line_bits WHERE file_id = ?",
                    (file_id,),
                )
                row = cursor.fetchone()
                if row:
                    # numbits is a blob of bit-packed line numbers
                    # Count bits to get covered lines
                    bits = row[0]
                    if bits:
                        line_count = sum(bin(b).count("1") for b in bits)
                        total_lines += line_count
                        covered_lines += line_count
                else:
                    uncovered_files.append(file_path_str)

            conn.close()

            coverage_percent = (covered_lines / total_lines * 100) if total_lines > 0 else 0.0

            return CoverageEvidence(
                total_lines=total_lines,
                covered_lines=covered_lines,
                coverage_percent=round(coverage_percent, 2),
                uncovered_files=tuple(uncovered_files),
                source=str(file_path),
            )

        except sqlite3.Error as e:
            logger.warning("Failed to parse .coverage sqlite db %s: %s", file_path, e)
            return None
