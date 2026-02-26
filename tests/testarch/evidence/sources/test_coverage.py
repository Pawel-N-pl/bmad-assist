"""Tests for CoverageSource."""

from pathlib import Path

from bmad_assist.testarch.evidence.models import SourceConfig
from bmad_assist.testarch.evidence.sources.coverage import (
    DEFAULT_COVERAGE_PATTERNS,
    CoverageSource,
)


class TestCoverageSourceProperties:
    """Tests for CoverageSource properties."""

    def test_source_type(self) -> None:
        """Test source_type property."""
        source = CoverageSource()
        assert source.source_type == "coverage"

    def test_default_patterns(self) -> None:
        """Test default_patterns property."""
        source = CoverageSource()
        assert source.default_patterns == DEFAULT_COVERAGE_PATTERNS
        assert "coverage/lcov.info" in source.default_patterns
        assert "**/coverage-summary.json" in source.default_patterns
        assert ".coverage" in source.default_patterns


class TestLcovParsing:
    """Tests for LCOV format parsing."""

    def test_parse_lcov_file(self, tmp_path: Path) -> None:
        """Test parsing a valid lcov.info file."""
        lcov_content = """TN:Test
SF:/src/index.js
DA:1,1
DA:2,1
DA:3,0
LF:3
LH:2
end_of_record
SF:/src/utils.js
DA:1,0
LF:1
LH:0
end_of_record
"""
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        lcov_file = coverage_dir / "lcov.info"
        lcov_file.write_text(lcov_content)

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total_lines == 4
        assert evidence.covered_lines == 2
        assert evidence.coverage_percent == 50.0
        assert "/src/utils.js" in evidence.uncovered_files

    def test_parse_lcov_empty_file(self, tmp_path: Path) -> None:
        """Test parsing an empty lcov file."""
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        lcov_file = coverage_dir / "lcov.info"
        lcov_file.write_text("")

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total_lines == 0
        assert evidence.coverage_percent == 0.0

    def test_parse_lcov_malformed_numbers(self, tmp_path: Path) -> None:
        """Test parsing lcov with malformed numbers (graceful handling)."""
        lcov_content = """TN:Test
SF:/src/index.js
LF:invalid
LH:also_invalid
end_of_record
"""
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        lcov_file = coverage_dir / "lcov.info"
        lcov_file.write_text(lcov_content)

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        # Should handle gracefully with zeros
        assert evidence is not None
        assert evidence.total_lines == 0


class TestIstanbulParsing:
    """Tests for Istanbul JSON format parsing."""

    def test_parse_istanbul_json(self, tmp_path: Path) -> None:
        """Test parsing a valid Istanbul coverage-summary.json."""
        istanbul_content = """{
  "total": {
    "lines": {"total": 100, "covered": 85, "pct": 85}
  },
  "/src/index.js": {
    "lines": {"total": 50, "covered": 45, "pct": 90}
  },
  "/src/legacy.js": {
    "lines": {"total": 50, "covered": 0, "pct": 0}
  }
}"""
        json_file = tmp_path / "coverage-summary.json"
        json_file.write_text(istanbul_content)

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        assert evidence is not None
        assert evidence.total_lines == 100
        assert evidence.covered_lines == 85
        assert evidence.coverage_percent == 85.0
        assert "/src/legacy.js" in evidence.uncovered_files

    def test_parse_istanbul_invalid_json(self, tmp_path: Path) -> None:
        """Test parsing invalid JSON returns None."""
        json_file = tmp_path / "coverage-summary.json"
        json_file.write_text("not valid json {{{")

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        assert evidence is None


class TestPytestCovParsing:
    """Tests for pytest-cov .coverage parsing."""

    def test_no_coverage_file(self, tmp_path: Path) -> None:
        """Test when no coverage file exists."""
        source = CoverageSource()
        evidence = source.collect(tmp_path)
        assert evidence is None


class TestFileDiscovery:
    """Tests for evidence file discovery."""

    def test_prefers_most_recent_file(self, tmp_path: Path) -> None:
        """Test that most recently modified file is used."""
        import time

        # Create older file
        coverage_dir = tmp_path / "coverage"
        coverage_dir.mkdir()
        old_file = coverage_dir / "lcov.info"
        old_file.write_text("""TN:Old
SF:/old.js
LF:10
LH:5
end_of_record
""")

        # Wait a bit to ensure different mtime
        time.sleep(0.1)

        # Create newer file
        new_file = tmp_path / "coverage-summary.json"
        new_file.write_text("""{
  "total": {
    "lines": {"total": 200, "covered": 180, "pct": 90}
  }
}""")

        source = CoverageSource()
        evidence = source.collect(tmp_path)

        # Should use the newer file
        assert evidence is not None
        assert evidence.total_lines == 200
        assert "coverage-summary.json" in evidence.source

    def test_custom_patterns_with_source_config(self, tmp_path: Path) -> None:
        """Test using custom patterns from SourceConfig (frozen dataclass)."""
        custom_file = tmp_path / "my-coverage.info"
        custom_file.write_text("""TN:Custom
SF:/custom.js
LF:50
LH:50
end_of_record
""")

        config = SourceConfig(patterns=("my-coverage.info",))
        source = CoverageSource()
        evidence = source.collect(tmp_path, config)

        assert evidence is not None
        assert evidence.total_lines == 50

    def test_custom_patterns_with_source_config_model(self, tmp_path: Path) -> None:
        """Test using custom patterns from SourceConfigModel (Pydantic model)."""
        from bmad_assist.testarch.config import SourceConfigModel

        custom_file = tmp_path / "my-coverage-pydantic.info"
        custom_file.write_text("""TN:Pydantic
SF:/pydantic.js
LF:100
LH:75
end_of_record
""")

        # SourceConfigModel uses list[str] for patterns
        config = SourceConfigModel(patterns=["my-coverage-pydantic.info"])
        source = CoverageSource()
        evidence = source.collect(tmp_path, config)

        assert evidence is not None
        assert evidence.total_lines == 100
        assert evidence.covered_lines == 75


class TestFromFixtures:
    """Tests using fixture files."""

    def test_parse_sample_lcov(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-lcov.info fixture."""
        # Create temp project with fixture
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            coverage_dir = tmp_path / "coverage"
            coverage_dir.mkdir()
            shutil.copy(
                evidence_fixtures_dir / "sample-lcov.info",
                coverage_dir / "lcov.info",
            )

            source = CoverageSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.total_lines == 10  # 4 + 2 + 4 from sample
            assert evidence.covered_lines == 7  # 3 + 0 + 4 from sample
            assert "/src/utils.js" in evidence.uncovered_files

    def test_parse_sample_istanbul(self, evidence_fixtures_dir: Path) -> None:
        """Test parsing sample-coverage-summary.json fixture."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shutil.copy(
                evidence_fixtures_dir / "sample-coverage-summary.json",
                tmp_path / "coverage-summary.json",
            )

            source = CoverageSource()
            evidence = source.collect(tmp_path)

            assert evidence is not None
            assert evidence.total_lines == 100
            assert evidence.covered_lines == 85
            assert evidence.coverage_percent == 85.0
            assert "/src/legacy.js" in evidence.uncovered_files
