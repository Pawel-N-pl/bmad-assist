"""Test results evidence source.

This module provides the TestResultsSource class for collecting test
results from JUnit XML, pytest JSON, and Playwright JSON files.

Usage:
    from bmad_assist.testarch.evidence.sources.test_results import TestResultsSource

    source = TestResultsSource()
    evidence = source.collect(project_root)
"""

from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bmad_assist.testarch.evidence.models import TestResultsEvidence
from bmad_assist.testarch.evidence.sources.base import EvidenceSource

if TYPE_CHECKING:
    from bmad_assist.testarch.config import SourceConfigModel
    from bmad_assist.testarch.evidence.models import SourceConfig

logger = logging.getLogger(__name__)

# Default patterns for test result files
DEFAULT_TEST_RESULTS_PATTERNS = (
    "**/junit.xml",
    "**/test-results.json",
    "**/playwright-report/results.json",
)


class TestResultsSource(EvidenceSource):
    """Evidence source for test results.

    Supports parsing:
    - JUnit XML format
    - pytest JSON format (pytest-json-report)
    - Playwright JSON format

    """

    @property
    def source_type(self) -> str:
        """Return the type of evidence this source collects."""
        return "test_results"

    @property
    def default_patterns(self) -> tuple[str, ...]:
        """Return default glob patterns for file discovery."""
        return DEFAULT_TEST_RESULTS_PATTERNS

    def collect(
        self,
        project_root: Path,
        config: SourceConfigModel | SourceConfig | None = None,
    ) -> TestResultsEvidence | None:
        """Collect test results evidence from the project.

        Args:
            project_root: Root directory of the project.
            config: Optional source configuration. Accepts either:
                - SourceConfigModel (Pydantic model from YAML config)
                - SourceConfig (frozen dataclass for internal use)
                - None (use default patterns)

        Returns:
            TestResultsEvidence if found, None otherwise.

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
            logger.debug("No test result files found in %s", project_root)
            return None

        logger.debug("Parsing test results file: %s", best_file)

        # Determine format and parse
        if best_file.suffix == ".xml":
            return self._parse_junit_xml(best_file)
        elif best_file.suffix == ".json":
            # Try to detect format from content
            return self._parse_json_results(best_file)
        else:
            logger.warning("Unknown test results format: %s", best_file)
            return None

    def _parse_junit_xml(self, file_path: Path) -> TestResultsEvidence | None:
        """Parse JUnit XML format.

        Format:
        <testsuites tests="10" failures="2" errors="1" skipped="1">
          <testsuite name="TestClass" tests="5" failures="1">
            <testcase name="test_one" classname="TestClass" time="0.123"/>
            <testcase name="test_fail" classname="TestClass">
              <failure message="Expected true"/>
            </testcase>
          </testsuite>
        </testsuites>

        """
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except (ET.ParseError, OSError) as e:
            logger.warning("Failed to parse JUnit XML %s: %s", file_path, e)
            return None

        # Handle both <testsuites> and <testsuite> as root
        if root.tag == "testsuite":
            testsuites = [root]
            # Get totals from root attributes
            total = int(root.get("tests", 0))
            failures = int(root.get("failures", 0))
            errors = int(root.get("errors", 0))
            skipped = int(root.get("skipped", 0))
            time_str = root.get("time", "0")
        else:
            testsuites = root.findall("testsuite")
            # Get totals from root or sum from children
            total = int(root.get("tests", 0))
            failures = int(root.get("failures", 0))
            errors = int(root.get("errors", 0))
            skipped = int(root.get("skipped", 0))
            time_str = root.get("time", "0")

            # If no root totals, sum from testsuites
            if total == 0:
                for ts in testsuites:
                    total += int(ts.get("tests", 0))
                    failures += int(ts.get("failures", 0))
                    errors += int(ts.get("errors", 0))
                    skipped += int(ts.get("skipped", 0))

        # Parse duration
        try:
            duration_sec = float(time_str)
            duration_ms = int(duration_sec * 1000)
        except ValueError:
            duration_ms = 0

        # Collect failed tests
        failed_tests: list[str] = []
        for testsuite in testsuites:
            for testcase in testsuite.findall("testcase"):
                if testcase.find("failure") is not None or testcase.find("error") is not None:
                    classname = testcase.get("classname", "")
                    name = testcase.get("name", "unknown")
                    if classname:
                        failed_tests.append(f"{classname}.{name}")
                    else:
                        failed_tests.append(name)

        # Calculate passed, clamp to non-negative if data inconsistent
        passed = total - failures - errors - skipped
        if passed < 0:
            logger.warning(
                "Inconsistent JUnit data in %s: total=%d, failures=%d, errors=%d, skipped=%d",
                file_path, total, failures, errors, skipped,
            )
            passed = 0  # Clamp to avoid negative values

        return TestResultsEvidence(
            total=total,
            passed=passed,
            failed=failures,
            errors=errors,
            skipped=skipped,
            duration_ms=duration_ms,
            failed_tests=tuple(failed_tests),
            source=str(file_path),
        )

    def _parse_json_results(self, file_path: Path) -> TestResultsEvidence | None:
        """Parse JSON test results (pytest or Playwright format)."""
        try:
            content = file_path.read_text(encoding="utf-8")
            data = json.loads(content)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Failed to parse JSON results %s: %s", file_path, e)
            return None

        # Detect format
        if "report" in data or "summary" in data:
            return self._parse_pytest_json(data, file_path)
        elif "stats" in data:
            return self._parse_playwright_json(data, file_path)
        else:
            logger.warning("Unknown JSON format in %s", file_path)
            return None

    def _parse_pytest_json(
        self,
        data: dict[str, Any],
        file_path: Path,
    ) -> TestResultsEvidence | None:
        """Parse pytest JSON format (pytest-json-report).

        Format:
        {
          "report": {
            "summary": {
              "total": 150,
              "passed": 145,
              "failed": 3,
              "skipped": 1,
              "duration": 45200
            }
          },
          "tests": [
            {"name": "test_api.test_auth_failure", "outcome": "failed", "duration": 123}
          ]
        }

        """
        # Handle nested report structure
        # Note: tests array can be at root level even when report.summary exists
        if "report" in data:
            report = data["report"]
            summary = report.get("summary", {})
            # Tests can be inside report OR at root level
            tests = report.get("tests", data.get("tests", []))
        else:
            summary = data.get("summary", {})
            tests = data.get("tests", [])

        total = summary.get("total", 0)
        passed = summary.get("passed", 0)
        failed = summary.get("failed", 0)
        errors = summary.get("error", 0)
        skipped = summary.get("skipped", 0)
        duration_ms = summary.get("duration", 0)

        # Convert duration from seconds if needed
        if isinstance(duration_ms, float) and duration_ms < 1000:
            # Likely in seconds, convert to ms
            duration_ms = int(duration_ms * 1000)
        else:
            duration_ms = int(duration_ms)

        # Collect failed tests
        failed_tests: list[str] = []
        for test in tests:
            outcome = test.get("outcome", "")
            if outcome in ("failed", "error"):
                name = test.get("name", test.get("nodeid", "unknown"))
                failed_tests.append(name)

        return TestResultsEvidence(
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_ms=duration_ms,
            failed_tests=tuple(failed_tests),
            source=str(file_path),
        )

    def _parse_playwright_json(
        self,
        data: dict[str, Any],
        file_path: Path,
    ) -> TestResultsEvidence | None:
        """Parse Playwright JSON format.

        Format:
        {
          "stats": {
            "expected": 10,
            "unexpected": 1,
            "flaky": 0,
            "skipped": 1,
            "duration": 5000
          }
        }

        """
        stats = data.get("stats", {})

        expected = stats.get("expected", 0)
        unexpected = stats.get("unexpected", 0)
        flaky = stats.get("flaky", 0)
        skipped = stats.get("skipped", 0)
        duration_ms = stats.get("duration", 0)

        # In Playwright: expected = passed, unexpected = failed
        total = expected + unexpected + flaky + skipped
        passed = expected + flaky  # Flaky tests eventually passed
        failed = unexpected

        # Collect failed tests from suites if available
        failed_tests: list[str] = []
        suites = data.get("suites", [])
        self._collect_playwright_failures(suites, failed_tests)

        return TestResultsEvidence(
            total=total,
            passed=passed,
            failed=failed,
            errors=0,  # Playwright doesn't distinguish errors
            skipped=skipped,
            duration_ms=int(duration_ms),
            failed_tests=tuple(failed_tests),
            source=str(file_path),
        )

    def _collect_playwright_failures(
        self,
        suites: list[dict[str, Any]],
        failed_tests: list[str],
    ) -> None:
        """Recursively collect failed tests from Playwright suites."""
        for suite in suites:
            # Check tests in this suite
            for spec in suite.get("specs", []):
                for test in spec.get("tests", []):
                    status = test.get("status", "")
                    if status in ("unexpected", "failed"):
                        title = spec.get("title", "unknown")
                        failed_tests.append(title)

            # Recurse into child suites
            child_suites = suite.get("suites", [])
            if child_suites:
                self._collect_playwright_failures(child_suites, failed_tests)
