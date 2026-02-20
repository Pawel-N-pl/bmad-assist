"""Tests for PatternLibrary class."""

from pathlib import Path

import pytest
import yaml

from bmad_assist.core.exceptions import PatternLibraryError, PatternNotFoundError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.patterns.library import (
    PATTERN_ID_REGEX,
    PatternLibrary,
    _parse_yaml_signal,
)


class TestParseYamlSignal:
    """Tests for _parse_yaml_signal helper."""

    def test_parse_exact_signal(self) -> None:
        """Test parsing an exact signal."""
        signal = _parse_yaml_signal("race condition")
        assert signal.type == "exact"
        assert signal.pattern == "race condition"
        assert signal.weight == 1.0

    def test_parse_regex_signal(self) -> None:
        """Test parsing a regex signal."""
        signal = _parse_yaml_signal(r"regex:\bgo\s+func\(")
        assert signal.type == "regex"
        assert signal.pattern == r"\bgo\s+func\("
        assert signal.weight == 1.0

    def test_parse_regex_with_complex_pattern(self) -> None:
        """Test parsing a complex regex signal."""
        signal = _parse_yaml_signal(r"regex:\bif\s+.*len\s*\(.*\).*append")
        assert signal.type == "regex"
        assert signal.pattern == r"\bif\s+.*len\s*\(.*\).*append"


class TestPatternIdRegex:
    """Tests for pattern ID regex validation."""

    def test_valid_pattern_ids(self) -> None:
        """Test valid pattern ID formats."""
        assert PATTERN_ID_REGEX.match("CC-001")
        assert PATTERN_ID_REGEX.match("SEC-004")
        assert PATTERN_ID_REGEX.match("DB-100")
        assert PATTERN_ID_REGEX.match("CQ-999")

    def test_invalid_pattern_ids(self) -> None:
        """Test invalid pattern ID formats."""
        assert not PATTERN_ID_REGEX.match("C-001")  # Too short prefix
        assert not PATTERN_ID_REGEX.match("CCCC-001")  # Too long prefix (4 chars)
        assert not PATTERN_ID_REGEX.match("cc-001")  # Lowercase
        assert not PATTERN_ID_REGEX.match("CC-01")  # Too few digits
        assert not PATTERN_ID_REGEX.match("CC-0001")  # Too many digits
        assert not PATTERN_ID_REGEX.match("CC001")  # Missing dash
        assert not PATTERN_ID_REGEX.match("001-CC")  # Wrong order


class TestPatternLibraryCreation:
    """Tests for PatternLibrary initialization."""

    def test_empty_library(self) -> None:
        """Test creating an empty library."""
        library = PatternLibrary()
        assert len(library) == 0
        assert library.get_all_patterns() == []

    def test_library_repr(self) -> None:
        """Test library repr."""
        library = PatternLibrary()
        assert "PatternLibrary" in repr(library)
        assert "patterns=0" in repr(library)


class TestPatternLibraryLoad:
    """Tests for loading patterns from YAML files."""

    @pytest.fixture
    def temp_yaml_file(self, tmp_path: Path) -> Path:
        """Create a temporary YAML file with valid patterns."""
        yaml_file = tmp_path / "test_patterns.yaml"
        data = {
            "patterns": [
                {
                    "id": "CC-001",
                    "domain": "concurrency",
                    "severity": "critical",
                    "signals": ["race condition", "regex:\\bgo\\s+func\\("],
                    "description": "Race condition pattern",
                    "remediation": "Use mutex",
                },
                {
                    "id": "SEC-001",
                    "domain": "security",
                    "severity": "error",
                    "signals": ["timing attack"],
                    "description": "Timing attack pattern",
                },
            ]
        }
        yaml_file.write_text(yaml.dump(data))
        return yaml_file

    @pytest.fixture
    def temp_yaml_dir(self, tmp_path: Path) -> Path:
        """Create a temporary directory with YAML files."""
        patterns_dir = tmp_path / "patterns"
        patterns_dir.mkdir()

        # File 1
        file1 = patterns_dir / "concurrency.yaml"
        data1 = {
            "patterns": [
                {
                    "id": "CC-001",
                    "domain": "concurrency",
                    "severity": "critical",
                    "signals": ["race"],
                }
            ]
        }
        file1.write_text(yaml.dump(data1))

        # File 2
        file2 = patterns_dir / "security.yaml"
        data2 = {
            "patterns": [
                {
                    "id": "SEC-001",
                    "domain": "security",
                    "severity": "error",
                    "signals": ["timing"],
                }
            ]
        }
        file2.write_text(yaml.dump(data2))

        return patterns_dir

    def test_load_from_file(self, temp_yaml_file: Path) -> None:
        """Test loading patterns from a single file."""
        library = PatternLibrary.load([temp_yaml_file])
        assert len(library) == 2

    def test_load_from_directory(self, temp_yaml_dir: Path) -> None:
        """Test loading patterns from a directory."""
        library = PatternLibrary.load([temp_yaml_dir])
        assert len(library) == 2

    def test_load_empty_file(self, tmp_path: Path) -> None:
        """Test loading from an empty YAML file."""
        empty_file = tmp_path / "empty.yaml"
        empty_file.write_text("")
        library = PatternLibrary.load([empty_file])
        assert len(library) == 0

    def test_load_no_patterns_key(self, tmp_path: Path) -> None:
        """Test loading YAML without 'patterns' key."""
        yaml_file = tmp_path / "no_patterns.yaml"
        yaml_file.write_text(yaml.dump({"other": "data"}))
        library = PatternLibrary.load([yaml_file])
        assert len(library) == 0

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        """Test loading invalid YAML raises error."""
        invalid_file = tmp_path / "invalid.yaml"
        invalid_file.write_text("not: valid: yaml: [")
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([invalid_file])
        assert "Invalid YAML" in str(exc_info.value)

    def test_load_non_dict_root(self, tmp_path: Path) -> None:
        """Test loading YAML with non-dict root raises error."""
        yaml_file = tmp_path / "list_root.yaml"
        yaml_file.write_text(yaml.dump(["not", "a", "dict"]))
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "dictionary" in str(exc_info.value).lower()

    def test_load_patterns_not_list(self, tmp_path: Path) -> None:
        """Test loading YAML with non-list patterns raises error."""
        yaml_file = tmp_path / "bad_patterns.yaml"
        yaml_file.write_text(yaml.dump({"patterns": "not a list"}))
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "list" in str(exc_info.value).lower()

    def test_load_missing_id(self, tmp_path: Path) -> None:
        """Test loading pattern without ID raises error."""
        yaml_file = tmp_path / "no_id.yaml"
        yaml_file.write_text(
            yaml.dump(
                {"patterns": [{"domain": "concurrency", "severity": "critical"}]}
            )
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "id" in str(exc_info.value).lower()

    def test_load_invalid_id_format(self, tmp_path: Path) -> None:
        """Test loading pattern with invalid ID format raises error."""
        yaml_file = tmp_path / "bad_id.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "invalid-id",
                            "domain": "concurrency",
                            "severity": "critical",
                        }
                    ]
                }
            )
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "CC-001" in str(exc_info.value)

    def test_load_missing_domain(self, tmp_path: Path) -> None:
        """Test loading pattern without domain raises error."""
        yaml_file = tmp_path / "no_domain.yaml"
        yaml_file.write_text(
            yaml.dump({"patterns": [{"id": "CC-001", "severity": "critical"}]})
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "domain" in str(exc_info.value).lower()

    def test_load_invalid_domain(self, tmp_path: Path) -> None:
        """Test loading pattern with invalid domain raises error."""
        yaml_file = tmp_path / "bad_domain.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "invalid_domain",
                            "severity": "critical",
                        }
                    ]
                }
            )
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "domain" in str(exc_info.value).lower()

    def test_load_missing_severity(self, tmp_path: Path) -> None:
        """Test loading pattern without severity raises error."""
        yaml_file = tmp_path / "no_severity.yaml"
        yaml_file.write_text(
            yaml.dump({"patterns": [{"id": "CC-001", "domain": "concurrency"}]})
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "severity" in str(exc_info.value).lower()

    def test_load_invalid_severity(self, tmp_path: Path) -> None:
        """Test loading pattern with invalid severity raises error."""
        yaml_file = tmp_path / "bad_severity.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "concurrency",
                            "severity": "invalid_severity",
                        }
                    ]
                }
            )
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "severity" in str(exc_info.value).lower()

    def test_load_invalid_regex(self, tmp_path: Path) -> None:
        """Test loading pattern with invalid regex raises error."""
        yaml_file = tmp_path / "bad_regex.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "concurrency",
                            "severity": "critical",
                            "signals": ["regex:[invalid regex("],
                        }
                    ]
                }
            )
        )
        with pytest.raises(PatternLibraryError) as exc_info:
            PatternLibrary.load([yaml_file])
        assert "regex" in str(exc_info.value).lower()


class TestPatternLibraryDeduplication:
    """Tests for pattern deduplication behavior."""

    def test_duplicate_override(self, tmp_path: Path) -> None:
        """Test that later patterns override earlier ones."""
        file1 = tmp_path / "file1.yaml"
        file1.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "concurrency",
                            "severity": "critical",
                            "signals": ["first"],
                            "description": "First pattern",
                        }
                    ]
                }
            )
        )

        file2 = tmp_path / "file2.yaml"
        file2.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "storage",
                            "severity": "error",
                            "signals": ["second"],
                            "description": "Second pattern",
                        }
                    ]
                }
            )
        )

        library = PatternLibrary.load([file1, file2])
        assert len(library) == 1
        pattern = library.get_pattern(PatternId("CC-001"))
        assert pattern is not None
        assert pattern.domain == ArtifactDomain.STORAGE
        assert pattern.severity == Severity.ERROR
        assert pattern.description == "Second pattern"


class TestPatternLibraryGetPattern:
    """Tests for get_pattern method."""

    @pytest.fixture
    def library_with_patterns(self, tmp_path: Path) -> PatternLibrary:
        """Create a library with test patterns."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "concurrency",
                            "severity": "critical",
                            "signals": ["race"],
                        }
                    ]
                }
            )
        )
        return PatternLibrary.load([yaml_file])

    def test_get_existing_pattern(self, library_with_patterns: PatternLibrary) -> None:
        """Test getting an existing pattern."""
        pattern = library_with_patterns.get_pattern(PatternId("CC-001"))
        assert pattern is not None
        assert pattern.id == PatternId("CC-001")

    def test_get_nonexistent_pattern(self, library_with_patterns: PatternLibrary) -> None:
        """Test getting a non-existent pattern returns None."""
        pattern = library_with_patterns.get_pattern(PatternId("NOT-FOUND"))
        assert pattern is None

    def test_get_pattern_raise_on_missing(self, library_with_patterns: PatternLibrary) -> None:
        """Test getting a non-existent pattern with raise_on_missing=True."""
        with pytest.raises(PatternNotFoundError) as exc_info:
            library_with_patterns.get_pattern(
                PatternId("NOT-FOUND"), raise_on_missing=True
            )
        assert "NOT-FOUND" in str(exc_info.value)

    def test_get_pattern_with_string_id(self, library_with_patterns: PatternLibrary) -> None:
        """Test getting a pattern with string ID."""
        pattern = library_with_patterns.get_pattern("CC-001")
        assert pattern is not None
        assert pattern.id == PatternId("CC-001")


class TestPatternLibraryGetPatterns:
    """Tests for get_patterns method."""

    @pytest.fixture
    def library_with_multiple_patterns(self, tmp_path: Path) -> PatternLibrary:
        """Create a library with multiple test patterns."""
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text(
            yaml.dump(
                {
                    "patterns": [
                        {
                            "id": "CC-001",
                            "domain": "concurrency",
                            "severity": "critical",
                            "signals": ["race"],
                        },
                        {
                            "id": "CC-002",
                            "domain": "concurrency",
                            "severity": "error",
                            "signals": ["deadlock"],
                        },
                        {
                            "id": "SEC-001",
                            "domain": "security",
                            "severity": "critical",
                            "signals": ["timing"],
                        },
                        {
                            "id": "DB-001",
                            "domain": "storage",
                            "severity": "warning",
                            "signals": ["index"],
                        },
                    ]
                }
            )
        )
        return PatternLibrary.load([yaml_file])

    def test_get_all_patterns(self, library_with_multiple_patterns: PatternLibrary) -> None:
        """Test getting all patterns."""
        patterns = library_with_multiple_patterns.get_patterns()
        assert len(patterns) == 4

    def test_get_patterns_by_single_domain(
        self, library_with_multiple_patterns: PatternLibrary
    ) -> None:
        """Test filtering by single domain."""
        patterns = library_with_multiple_patterns.get_patterns(
            [ArtifactDomain.CONCURRENCY]
        )
        assert len(patterns) == 2
        assert all(p.domain == ArtifactDomain.CONCURRENCY for p in patterns)

    def test_get_patterns_by_multiple_domains(
        self, library_with_multiple_patterns: PatternLibrary
    ) -> None:
        """Test filtering by multiple domains."""
        patterns = library_with_multiple_patterns.get_patterns(
            [ArtifactDomain.CONCURRENCY, ArtifactDomain.SECURITY]
        )
        assert len(patterns) == 3

    def test_get_patterns_sorted_by_id(
        self, library_with_multiple_patterns: PatternLibrary
    ) -> None:
        """Test that patterns are sorted by ID."""
        patterns = library_with_multiple_patterns.get_patterns()
        ids = [p.id for p in patterns]
        assert ids == sorted(ids)

    def test_get_all_patterns_alias(
        self, library_with_multiple_patterns: PatternLibrary
    ) -> None:
        """Test get_all_patterns is equivalent to get_patterns(None)."""
        all_via_get = library_with_multiple_patterns.get_patterns(None)
        all_via_get_all = library_with_multiple_patterns.get_all_patterns()
        assert all_via_get == all_via_get_all


class TestPatternLibraryLoadRealData:
    """Tests for loading actual pattern data."""

    def test_load_concurrency_patterns(self) -> None:
        """Test loading actual concurrency patterns."""
        patterns_dir = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "bmad_assist"
            / "deep_verify"
            / "patterns"
            / "data"
            / "spec"
        )
        yaml_file = patterns_dir / "concurrency.yaml"
        if yaml_file.exists():
            library = PatternLibrary.load([yaml_file])
            assert len(library) >= 5  # At least 5 concurrency patterns

            # Check CC-001 exists and has correct structure
            pattern = library.get_pattern(PatternId("CC-001"))
            assert pattern is not None
            assert pattern.domain == ArtifactDomain.CONCURRENCY
            assert pattern.severity == Severity.CRITICAL
            assert len(pattern.signals) > 0

    def test_load_all_spec_patterns(self) -> None:
        """Test loading all spec pattern files."""
        patterns_dir = (
            Path(__file__).parent.parent.parent.parent
            / "src"
            / "bmad_assist"
            / "deep_verify"
            / "patterns"
            / "data"
            / "spec"
        )
        if patterns_dir.exists():
            library = PatternLibrary.load([patterns_dir])
            # Should have at least 25 patterns (5 per file)
            assert len(library) >= 25
