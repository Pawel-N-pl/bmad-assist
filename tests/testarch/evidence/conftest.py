"""Fixtures for evidence module tests."""

import shutil
from pathlib import Path

import pytest


@pytest.fixture
def evidence_fixtures_dir() -> Path:
    """Return the path to evidence test fixtures."""
    return Path(__file__).parent.parent.parent / "fixtures" / "evidence"


@pytest.fixture
def temp_project_root(tmp_path: Path, evidence_fixtures_dir: Path) -> Path:
    """Create a temporary project with evidence files."""
    # Create directory structure
    coverage_dir = tmp_path / "coverage"
    coverage_dir.mkdir()

    # Copy sample files
    shutil.copy(
        evidence_fixtures_dir / "sample-lcov.info",
        coverage_dir / "lcov.info",
    )
    shutil.copy(
        evidence_fixtures_dir / "sample-junit.xml",
        tmp_path / "junit.xml",
    )
    shutil.copy(
        evidence_fixtures_dir / "sample-npm-audit.json",
        tmp_path / "npm-audit.json",
    )
    shutil.copy(
        evidence_fixtures_dir / "sample-lighthouse.json",
        tmp_path / "lighthouse-report.json",
    )

    return tmp_path


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """Create an empty temporary project."""
    return tmp_path


@pytest.fixture
def lcov_content() -> str:
    """Sample lcov content."""
    return """TN:Test
SF:/src/index.js
DA:1,1
DA:2,0
LF:2
LH:1
end_of_record
"""


@pytest.fixture
def istanbul_content() -> str:
    """Sample Istanbul JSON content."""
    return """{
  "total": {
    "lines": {"total": 100, "covered": 80, "pct": 80}
  }
}"""


@pytest.fixture
def junit_content() -> str:
    """Sample JUnit XML content."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="3" failures="1" errors="0" skipped="0" time="1.5">
  <testsuite name="Test" tests="3" failures="1">
    <testcase name="test_pass" classname="Test" time="0.5"/>
    <testcase name="test_fail" classname="Test" time="0.5">
      <failure message="Failed"/>
    </testcase>
    <testcase name="test_pass2" classname="Test" time="0.5"/>
  </testsuite>
</testsuites>"""


@pytest.fixture
def npm_audit_content() -> str:
    """Sample npm audit JSON content."""
    return """{
  "vulnerabilities": {
    "lodash": {
      "name": "lodash",
      "severity": "high",
      "range": "<4.17.21",
      "fixAvailable": true,
      "via": [{"title": "Prototype Pollution"}]
    }
  },
  "metadata": {
    "vulnerabilities": {
      "critical": 0,
      "high": 1,
      "moderate": 0,
      "low": 0,
      "info": 0,
      "total": 1
    }
  }
}"""


@pytest.fixture
def lighthouse_content() -> str:
    """Sample Lighthouse JSON content."""
    return """{
  "categories": {
    "performance": {"score": 0.85},
    "accessibility": {"score": 0.90}
  }
}"""


@pytest.fixture
def k6_content() -> str:
    """Sample k6 JSON content."""
    return """{
  "metrics": {
    "http_reqs": {
      "values": {"count": 1000, "rate": 50}
    },
    "http_req_duration": {
      "values": {"avg": 100, "p(95)": 250}
    }
  }
}"""
