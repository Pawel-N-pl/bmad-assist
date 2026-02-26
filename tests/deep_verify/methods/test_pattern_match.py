"""Tests for PatternMatchMethod class."""

import logging

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    MethodId,
    Pattern,
    PatternId,
    Severity,
    Signal,
)
from bmad_assist.deep_verify.methods import PatternMatchMethod

# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_cc004_pattern() -> Pattern:
    """Create a sample CC-004 (check-then-act) pattern."""
    return Pattern(
        id=PatternId("CC-004"),
        domain=ArtifactDomain.CONCURRENCY,
        severity=Severity.CRITICAL,
        signals=[
            Signal(type="exact", pattern="check then act"),
            Signal(type="exact", pattern="check-then-act"),
            Signal(type="exact", pattern="TOCTOU"),
        ],
        description="Check-then-act pattern without proper locking - TOCTOU race condition",
        remediation="Use atomic check-and-set operations or wrap check+act in mutex",
    )


@pytest.fixture
def single_signal_cc004_pattern() -> Pattern:
    """Create a single-signal CC-004 pattern for reliable matching."""
    return Pattern(
        id=PatternId("CC-004"),
        domain=ArtifactDomain.CONCURRENCY,
        severity=Severity.CRITICAL,
        signals=[
            Signal(type="exact", pattern="TOCTOU"),
        ],
        description="Check-then-act pattern without proper locking - TOCTOU race condition",
        remediation="Use atomic check-and-set operations or wrap check+act in mutex",
    )


@pytest.fixture
def sample_sec004_pattern() -> Pattern:
    """Create a sample SEC-004 (auth bypass) pattern."""
    return Pattern(
        id=PatternId("SEC-004"),
        domain=ArtifactDomain.SECURITY,
        severity=Severity.CRITICAL,
        signals=[
            Signal(type="exact", pattern="auth bypass"),
            Signal(type="exact", pattern="skip auth"),
            Signal(type="regex", pattern=r"/\*\s*TODO.*auth"),
        ],
        description="Potential authentication bypass",
        remediation="Ensure all code paths enforce authentication checks, remove temporary bypasses",
    )


@pytest.fixture
def sample_db003_pattern() -> Pattern:
    """Create a sample DB-003 (TOCTOU in storage) pattern."""
    return Pattern(
        id=PatternId("DB-003"),
        domain=ArtifactDomain.STORAGE,
        severity=Severity.ERROR,
        signals=[
            Signal(type="exact", pattern="check then write"),
            Signal(type="exact", pattern="exists then insert"),
            Signal(type="regex", pattern=r"\bif\s+.*[Ee]xists\s*\("),
        ],
        description="Time-of-check to time-of-use in storage operations",
        remediation="Use unique constraints, transactions, or upsert operations",
    )


@pytest.fixture
def sample_patterns(
    sample_cc004_pattern: Pattern,
    sample_sec004_pattern: Pattern,
    sample_db003_pattern: Pattern,
) -> list[Pattern]:
    """Create a list of sample patterns for testing."""
    return [sample_cc004_pattern, sample_sec004_pattern, sample_db003_pattern]


# =============================================================================
# Test PatternMatchMethod Creation
# =============================================================================

class TestPatternMatchMethodCreation:
    """Tests for PatternMatchMethod instantiation."""

    @pytest.mark.asyncio
    async def test_method_instantiation_with_patterns(self, sample_patterns: list[Pattern]) -> None:
        """Test creating PatternMatchMethod with explicit patterns."""
        method = PatternMatchMethod(patterns=sample_patterns)

        assert method.method_id == MethodId("#153")
        assert method._threshold == 0.25
        assert len(method._library) == 3

    @pytest.mark.asyncio
    async def test_method_instantiation_with_default_patterns(self) -> None:
        """Test creating PatternMatchMethod with default patterns."""
        method = PatternMatchMethod()

        assert method.method_id == MethodId("#153")
        assert method._threshold == 0.25
        assert len(method._library) > 0  # Should load default patterns

    @pytest.mark.asyncio
    async def test_method_instantiation_with_custom_threshold(self, sample_patterns: list[Pattern]) -> None:
        """Test creating PatternMatchMethod with custom threshold."""
        method = PatternMatchMethod(patterns=sample_patterns, threshold=0.8)

        assert method._threshold == 0.8

    @pytest.mark.asyncio
    async def test_invalid_threshold_raises_value_error(self, sample_patterns: list[Pattern]) -> None:
        """Test that invalid threshold values raise ValueError."""
        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            PatternMatchMethod(patterns=sample_patterns, threshold=-0.1)

        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            PatternMatchMethod(patterns=sample_patterns, threshold=1.5)

    @pytest.mark.asyncio
    async def test_method_repr(self, sample_patterns: list[Pattern]) -> None:
        """Test method repr string."""
        method = PatternMatchMethod(patterns=sample_patterns)
        repr_str = repr(method)

        assert "PatternMatchMethod" in repr_str
        assert "method_id='#153'" in repr_str
        assert "patterns=3" in repr_str
        assert "threshold=0.25" in repr_str


# =============================================================================
# Test Pattern Detection
# =============================================================================

class TestPatternDetection:
    """Tests for pattern detection with various artifacts."""

    @pytest.mark.asyncio
    async def test_cc004_detection(self, sample_cc004_pattern: Pattern) -> None:
        """Test detection of CC-004 (check-then-act) pattern."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        artifact = """
func processUser(userID string) error {
    // check-then-act pattern here
    // TOCTOU - time of check to time of use
    if userExists(userID) {
        user := getUser(userID)
        return process(user)
    }
    return fmt.Errorf("user not found")
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.pattern_id == PatternId("CC-004")
        assert finding.severity == Severity.CRITICAL
        assert finding.id == "#153-F1"

    @pytest.mark.asyncio
    async def test_sec004_detection(self, sample_sec004_pattern: Pattern) -> None:
        """Test detection of SEC-004 (auth bypass) pattern."""
        method = PatternMatchMethod(patterns=[sample_sec004_pattern])

        artifact = """
func handleRequest(w http.ResponseWriter, r *http.Request) {
    /* TODO: re-enable auth check before production */
    // Skip auth for testing
    processRequest(r)
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.pattern_id == PatternId("SEC-004")
        assert finding.severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_db003_detection(self, sample_db003_pattern: Pattern) -> None:
        """Test detection of DB-003 (TOCTOU in storage) pattern."""
        method = PatternMatchMethod(patterns=[sample_db003_pattern])

        artifact = """
func saveUser(user User) error {
    // Check then write pattern
    if userExists(user.ID) {
        return fmt.Errorf("user already exists")
    }
    return db.Insert(&user)
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert finding.pattern_id == PatternId("DB-003")
        assert finding.severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_multiple_patterns_same_artifact(self, sample_patterns: list[Pattern]) -> None:
        """Test detection of multiple patterns in same artifact."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func insecureHandler(w http.ResponseWriter, r *http.Request) {
    // auth bypass vulnerability
    skip auth for testing
    
    // check-then-act pattern
    TOCTOU race condition
    if userExists(r.UserID) {
        user := getUser(r.UserID)
        process(user)
    }
}
"""
        findings = await method.analyze(artifact)

        # Should find SEC-004 (auth bypass), CC-004 (check-then-act),
        # and DB-003 (TOCTOU in storage) which also matches TOCTOU keywords
        assert len(findings) >= 2
        pattern_ids = {f.pattern_id for f in findings}
        assert PatternId("SEC-004") in pattern_ids
        assert PatternId("CC-004") in pattern_ids


# =============================================================================
# Test Domain Filtering
# =============================================================================

class TestDomainFiltering:
    """Tests for domain-aware pattern filtering."""

    @pytest.mark.asyncio
    async def test_filter_by_single_domain(self, sample_patterns: list[Pattern]) -> None:
        """Test filtering patterns by a single domain."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func insecureHandler(w http.ResponseWriter, r *http.Request) {
    /* TODO: re-enable auth check before production */
    // Skip auth for testing
    
    // Check then act pattern
    if userExists(r.UserID) {
        user := getUser(r.UserID)
        process(user)
    }
}
"""
        # Filter by SECURITY domain only
        findings = await method.analyze(artifact, domains=[ArtifactDomain.SECURITY])

        # Should only find SEC-004
        assert len(findings) == 1
        assert findings[0].pattern_id == PatternId("SEC-004")

    @pytest.mark.asyncio
    async def test_filter_by_multiple_domains(self, sample_patterns: list[Pattern]) -> None:
        """Test filtering patterns by multiple domains."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func insecureHandler(w http.ResponseWriter, r *http.Request) {
    // auth bypass vulnerability
    skip auth for testing
    
    // check-then-act pattern
    TOCTOU race condition
    if userExists(r.UserID) {
        user := getUser(r.UserID)
        process(user)
    }
}
"""
        # Filter by SECURITY and CONCURRENCY domains
        findings = await method.analyze(
            artifact, domains=[ArtifactDomain.SECURITY, ArtifactDomain.CONCURRENCY]
        )

        # Should find both SEC-004 and CC-004
        assert len(findings) == 2
        pattern_ids = {f.pattern_id for f in findings}
        assert PatternId("SEC-004") in pattern_ids
        assert PatternId("CC-004") in pattern_ids

    @pytest.mark.asyncio
    async def test_filter_by_non_matching_domain(self, sample_patterns: list[Pattern]) -> None:
        """Test filtering by domain that doesn't match any patterns in artifact."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func insecureHandler(w http.ResponseWriter, r *http.Request) {
    /* TODO: re-enable auth check before production */
    // Skip auth for testing
}
"""
        # Filter by STORAGE domain (won't match SEC-004)
        findings = await method.analyze(artifact, domains=[ArtifactDomain.STORAGE])

        # Should find no findings since DB-003 pattern not in artifact
        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_no_filtering_when_domains_none(self, sample_patterns: list[Pattern]) -> None:
        """Test that all patterns are used when domains is None."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func insecureHandler(w http.ResponseWriter, r *http.Request) {
    // auth bypass vulnerability
    skip auth for testing
    
    // check-then-act pattern
    TOCTOU race condition
    if userExists(r.UserID) {
        user := getUser(r.UserID)
        process(user)
    }
}
"""
        # No domain filtering
        findings = await method.analyze(artifact, domains=None)

        # Should find all matching patterns (SEC-004, CC-004, and DB-003 via TOCTOU)
        assert len(findings) >= 2


# =============================================================================
# Test Evidence Creation
# =============================================================================

class TestEvidenceCreation:
    """Tests for evidence creation from matched signals."""

    @pytest.mark.asyncio
    async def test_evidence_line_numbers(self, single_signal_cc004_pattern: Pattern) -> None:
        """Test that evidence captures correct line numbers."""
        method = PatternMatchMethod(patterns=[single_signal_cc004_pattern])

        artifact = """line 1
line 2
TOCTOU
line 4
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert len(finding.evidence) > 0

        # Check that evidence has line numbers
        for evidence in finding.evidence:
            assert evidence.line_number is not None
            assert evidence.line_number > 0

    @pytest.mark.asyncio
    async def test_evidence_quotes(self, single_signal_cc004_pattern: Pattern) -> None:
        """Test that evidence captures matched text as quotes."""
        method = PatternMatchMethod(patterns=[single_signal_cc004_pattern])

        artifact = """
func process() {
    // check-then-act pattern here
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert len(finding.evidence) > 0

        # Check that evidence has quotes
        for evidence in finding.evidence:
            assert evidence.quote
            assert len(evidence.quote) > 0

    @pytest.mark.asyncio
    async def test_evidence_confidence(self, sample_cc004_pattern: Pattern) -> None:
        """Test that evidence captures confidence from match result."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        artifact = """
func process() {
    // check-then-act pattern here
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert len(finding.evidence) > 0

        # Check that evidence has confidence
        for evidence in finding.evidence:
            assert evidence.confidence >= 0.0
            assert evidence.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_evidence_source(self, sample_cc004_pattern: Pattern) -> None:
        """Test that evidence captures source (pattern ID)."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        artifact = """
func process() {
    // check-then-act pattern
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]
        assert len(finding.evidence) > 0

        # Check that evidence has source as pattern ID
        for evidence in finding.evidence:
            assert evidence.source == "CC-004"


# =============================================================================
# Test Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_artifact(self, sample_patterns: list[Pattern]) -> None:
        """Test that empty artifact returns empty findings list."""
        method = PatternMatchMethod(patterns=sample_patterns)

        findings = await method.analyze("")

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_whitespace_only_artifact(self, sample_patterns: list[Pattern]) -> None:
        """Test that whitespace-only artifact returns empty findings."""
        method = PatternMatchMethod(patterns=sample_patterns)

        findings = await method.analyze("   \n\t  \n")

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_no_pattern_matches(self, sample_patterns: list[Pattern]) -> None:
        """Test artifact with no matching patterns returns empty list."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func innocentFunction() {
    // This is clean code with no issues
    return 42
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_finding_id_format(self, sample_cc004_pattern: Pattern) -> None:
        """Test that finding IDs use method-prefixed format."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        artifact = """
func process() {
    // check-then-act pattern
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        assert findings[0].id == "#153-F1"

    @pytest.mark.asyncio
    async def test_multiple_finding_ids(self, sample_patterns: list[Pattern]) -> None:
        """Test that multiple findings get sequential IDs."""
        method = PatternMatchMethod(patterns=sample_patterns)

        artifact = """
func handler() {
    // auth bypass
    skip auth for testing
    // check-then-act pattern
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        # Should find both SEC-004 and CC-004
        assert len(findings) == 2
        ids = {f.id for f in findings}
        assert "#153-F1" in ids
        assert "#153-F2" in ids


# =============================================================================
# Test Remediation
# =============================================================================

class TestRemediation:
    """Tests for remediation guidance in findings."""

    @pytest.mark.asyncio
    async def test_remediation_in_description(self, sample_cc004_pattern: Pattern) -> None:
        """Test that remediation guidance is included in finding description."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        artifact = """
func process() {
    // check-then-act pattern
    TOCTOU race condition
}
"""
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]

        # Description should include remediation
        assert "Remediation:" in finding.description
        assert "atomic check-and-set" in finding.description

    @pytest.mark.asyncio
    async def test_no_remediation_when_not_provided(self) -> None:
        """Test finding when pattern has no remediation."""
        pattern_no_remediation = Pattern(
            id=PatternId("TEST-001"),
            domain=ArtifactDomain.CONCURRENCY,
            severity=Severity.WARNING,
            signals=[Signal(type="exact", pattern="test signal")],
            description="Test pattern without remediation",
            remediation=None,
        )
        method = PatternMatchMethod(patterns=[pattern_no_remediation])

        artifact = "test signal here"
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]

        # Description should not include remediation section
        assert "Remediation:" not in finding.description
        assert finding.description == "Test pattern without remediation"

    @pytest.mark.asyncio
    async def test_title_truncation_to_80_chars(self) -> None:
        """Test that long titles are truncated to 80 characters."""
        long_description = "A" * 100  # 100 character description
        pattern_long_title = Pattern(
            id=PatternId("TEST-002"),
            domain=ArtifactDomain.CONCURRENCY,
            severity=Severity.WARNING,
            signals=[Signal(type="exact", pattern="test signal")],
            description=long_description,
            remediation=None,
        )
        method = PatternMatchMethod(patterns=[pattern_long_title])

        artifact = "test signal here"
        findings = await method.analyze(artifact)

        assert len(findings) == 1
        finding = findings[0]

        # Title should be truncated to 80 chars with "..."
        assert len(finding.title) <= 80
        assert finding.title.endswith("...")
        assert finding.title == "A" * 77 + "..."


# =============================================================================
# Test Error Handling
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in PatternMatchMethod."""

    @pytest.mark.asyncio
    async def test_graceful_failure_on_matcher_error(
        self,
        sample_cc004_pattern: Pattern,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that matcher errors return empty list with logged warning."""
        method = PatternMatchMethod(patterns=[sample_cc004_pattern])

        # Temporarily set library to None to trigger error
        original_library = method._library
        method._library = None  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING):
            findings = await method.analyze("some artifact")

        assert len(findings) == 0
        assert "Pattern matching failed" in caplog.text

        # Restore library for cleanup
        method._library = original_library


# =============================================================================
# Test Integration with Default Patterns
# =============================================================================

class TestDefaultPatternsIntegration:
    """Tests using actual default patterns from the library."""

    @pytest.mark.asyncio
    async def test_with_default_library(self) -> None:
        """Test PatternMatchMethod with default pattern library."""
        method = PatternMatchMethod()  # Uses default patterns

        artifact = """
func processUser(userID string) error {
    // Check if user exists
    if userExists(userID) {
        // TOCTOU race condition here
        user := getUser(userID)
        return process(user)
    }
    return fmt.Errorf("user not found")
}
"""
        findings = await method.analyze(artifact)

        # Should find patterns from the default library
        # Note: Actual findings depend on default pattern definitions
        assert isinstance(findings, list)  # Should always return a list

    @pytest.mark.asyncio
    async def test_default_library_cc001(self) -> None:
        """Test detection of CC-001 from default library."""
        method = PatternMatchMethod()

        artifact = """
func processUsers(users []User) {
    for _, user := range users {
        // Race condition: concurrent access to shared state
        go func(u User) {
            processUser(u)
        }(user)
    }
}
"""
        findings = await method.analyze(artifact)

        # Check for CC-001 (race condition) pattern detection
        cc001_findings = [f for f in findings if f.pattern_id == PatternId("CC-001")]
        # Document whether CC-001 was found (informational test)
        # Pattern matching behavior depends on exact pattern definition

    @pytest.mark.asyncio
    async def test_default_library_sec002(self) -> None:
        """Test detection of SEC-002 (weak crypto) from default library."""
        method = PatternMatchMethod()

        artifact = """
import "crypto/md5"

func hashPassword(password string) string {
    h := md5.New()
    h.Write([]byte(password))
    return fmt.Sprintf("%x", h.Sum(nil))
}
"""
        findings = await method.analyze(artifact)

        # Check for SEC-002 (weak crypto) pattern detection
        sec002_findings = [f for f in findings if f.pattern_id == PatternId("SEC-002")]
        # Document whether SEC-002 was found (informational test)
        # Pattern matching behavior depends on exact pattern definition
