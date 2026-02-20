"""Tests for TestResultsSource."""

from pathlib import Path

from bmad_assist.testarch.evidence.models import SourceConfig
from bmad_assist.testarch.evidence.sources.test_results import (
    DEFAULT_TEST_RESULTS_PATTERNS,
    TestResultsSource,
)


class TestTestResultsSourceProperties:
    """Tests for TestResultsSource properties."""

    def test_source_type(self) -> None:
        """Test source_type property."""
        source = TestResultsSource()
        assert source.source_type == "test_results"

    def test_default_patterns(self) -> None:
        """Test default_patterns property."""
        source = TestResultsSource()
        assert source.default_patterns == DEFAULT_TEST_RESULTS_PATTERNS
        assert "**/junit.xml" in source.default_patterns
        assert "**/test-results.json" in source.default_patterns
        assert "**/playwright-report/results.json" in source.default_patterns


class TestJUnitXMLParsing:
    """Tests for JUnit XML format parsing."""

    def test_parse_junit_xml(self, tmp_path: Path) -> None:
        """Test parsing a valid JUnit XML file."""
        junit_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites tests="5" failures="1" errors="1" skipped="1" time="10.5">
  <testsuite name="TestClass" tests="5" failures="1" errors="1" skipped="1">
    <testcase name="test_pass" classname="TestClass" time="1.0"/>
    <testcase name="test_pass2" classname="TestClass" time="1.0"/>
    <testcase name="test_fail" classname="TestClass" time="1.0">
      <failure message="Expected true"/>
    </testcase>
    <testcase name="test_error" classname="TestClass" time="1.0">
      <error message="Connection error"/>
    </testcase>
    <testcase name="test_skip" classname="TestClass" time="0.0">
      <skipped message="Not implemented"/>
    </testcase>
  </testsuite>
</testsuites>"""
        junit_file = tmp_path / "junit.xml"
        junit_file.write_text(junit_content)

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total == 5
        assert evidence.passed == 2
        assert evidence.failed == 1
        assert evidence.errors == 1
        assert evidence.skipped == 1
        assert evidence.duration_ms == 10500
        assert "TestClass.test_fail" in evidence.failed_tests
        assert "TestClass.test_error" in evidence.failed_tests

    def test_parse_junit_single_testsuite(self, tmp_path: Path) -> None:
        """Test parsing JUnit XML with testsuite as root."""
        junit_content = """<?xml version="1.0" encoding="UTF-8"?>
<testsuite name="Test" tests="2" failures="0" errors="0" skipped="0" time="1.0">
  <testcase name="test_one" classname="Test" time="0.5"/>
  <testcase name="test_two" classname="Test" time="0.5"/>
</testsuite>"""
        junit_file = tmp_path / "junit.xml"
        junit_file.write_text(junit_content)

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total == 2
        assert evidence.passed == 2
        assert evidence.failed == 0

    def test_parse_junit_invalid_xml(self, tmp_path: Path) -> None:
        """Test parsing invalid XML returns None."""
        junit_file = tmp_path / "junit.xml"
        junit_file.write_text("<invalid>")

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is None


class TestPytestJSONParsing:
    """Tests for pytest JSON format parsing."""

    def test_parse_pytest_json(self, tmp_path: Path) -> None:
        """Test parsing pytest-json-report format."""
        json_content = """{
  "report": {
    "summary": {
      "total": 10,
      "passed": 8,
      "failed": 1,
      "error": 1,
      "skipped": 0,
      "duration": 5000
    }
  },
  "tests": [
    {"name": "test_a", "outcome": "passed"},
    {"name": "test_b", "outcome": "failed"},
    {"name": "test_c", "outcome": "error"}
  ]
}"""
        json_file = tmp_path / "test-results.json"
        json_file.write_text(json_content)

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total == 10
        assert evidence.passed == 8
        assert evidence.failed == 1
        assert evidence.errors == 1
        assert "test_b" in evidence.failed_tests
        assert "test_c" in evidence.failed_tests

    def test_parse_pytest_json_duration_in_seconds(self, tmp_path: Path) -> None:
        """Test parsing pytest JSON with duration in seconds."""
        json_content = """{
  "summary": {
    "total": 5,
    "passed": 5,
    "failed": 0,
    "skipped": 0,
    "duration": 2.5
  },
  "tests": []
}"""
        json_file = tmp_path / "test-results.json"
        json_file.write_text(json_content)

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.duration_ms == 2500  # Converted from 2.5s


class TestPlaywrightJSONParsing:
    """Tests for Playwright JSON format parsing."""

    def test_parse_playwright_json(self, tmp_path: Path) -> None:
        """Test parsing Playwright results format."""
        json_content = """{
  "stats": {
    "expected": 10,
    "unexpected": 2,
    "flaky": 1,
    "skipped": 1,
    "duration": 5000
  },
  "suites": [
    {
      "title": "Login",
      "specs": [
        {
          "title": "should login",
          "tests": [{"status": "expected"}]
        },
        {
          "title": "should fail",
          "tests": [{"status": "unexpected"}]
        }
      ]
    }
  ]
}"""
        # Create playwright-report directory
        playwright_dir = tmp_path / "playwright-report"
        playwright_dir.mkdir()
        json_file = playwright_dir / "results.json"
        json_file.write_text(json_content)

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total == 14  # 10 + 2 + 1 + 1
        assert evidence.passed == 11  # 10 expected + 1 flaky
        assert evidence.failed == 2
        assert evidence.skipped == 1
        assert evidence.duration_ms == 5000
        assert "should fail" in evidence.failed_tests


class TestFileDiscovery:
    """Tests for evidence file discovery."""

    def test_no_files_returns_none(self, tmp_path: Path) -> None:
        """Test when no test result files exist."""
        source = TestResultsSource()
        evidence = source.collect(tmp_path)
        assert evidence is None

    def test_prefers_most_recent_file(self, tmp_path: Path) -> None:
        """Test that most recently modified file is used."""
        import time

        # Create older file
        old_file = tmp_path / "junit.xml"
        old_file.write_text("""<?xml version="1.0"?>
<testsuites tests="1" failures="0"><testsuite tests="1"><testcase name="old"/></testsuite></testsuites>""")

        time.sleep(0.1)

        # Create newer file
        new_file = tmp_path / "test-results.json"
        new_file.write_text("""{
  "summary": {"total": 100, "passed": 100, "failed": 0, "skipped": 0},
  "tests": []
}""")

        source = TestResultsSource()
        evidence = source.collect(tmp_path)

        # Should use the newer file
        assert evidence is not None
        assert evidence.total == 100
        assert "test-results.json" in evidence.source

    def test_custom_patterns(self, tmp_path: Path) -> None:
        """Test using custom patterns from config."""
        custom_file = tmp_path / "my-results.xml"
        custom_file.write_text("""<?xml version="1.0"?>
<testsuites tests="5" failures="0"><testsuite tests="5"><testcase name="t1"/></testsuite></testsuites>""")

        config = SourceConfig(patterns=("my-results.xml",))
        source = TestResultsSource()
        evidence = source.collect(tmp_path, config)

        assert evidence is not None
        assert evidence.total == 5


class TestFromFixtures:
    """Tests using fixture files."""

    def test_parse_sample_junit(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-junit.xml fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-junit.xml",
                tmp_path / "junit.xml",
            )

            source = TestResultsSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.total == 10
            assert evidence.failures == 2 if hasattr(evidence, "failures") else evidence.failed == 2
            assert evidence.errors == 1
            assert evidence.skipped == 1
            assert "TestAPI.test_delete_user" in evidence.failed_tests
            assert "TestAuth.test_token_refresh" in evidence.failed_tests

    def test_parse_sample_pytest_json(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-test-results.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-test-results.json",
                tmp_path / "test-results.json",
            )

            source = TestResultsSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.total == 150
            assert evidence.passed == 142
            assert evidence.failed == 5
            assert evidence.errors == 2
            assert "test_api::test_delete_user" in evidence.failed_tests

    def test_parse_sample_playwright(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-playwright-results.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            playwright_dir = tmp_path / "playwright-report"
            playwright_dir.mkdir()
            shutil.copy(
                evidence_fixtures_dir / "sample-playwright-results.json",
                playwright_dir / "results.json",
            )

            source = TestResultsSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.total == 55  # 45 + 3 + 2 + 5
            assert evidence.passed == 47  # 45 + 2 flaky
            assert evidence.failed == 3
            assert evidence.skipped == 5
