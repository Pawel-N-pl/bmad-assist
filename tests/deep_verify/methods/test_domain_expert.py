"""Tests for DomainExpertMethod (#203).

This module provides comprehensive test coverage for the Domain Expert
verification method, including knowledge base integration, finding creation,
and LLM response parsing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.knowledge import KnowledgeCategory, KnowledgeRule
from bmad_assist.deep_verify.methods.constants import (
    DEFAULT_MODEL,
    DEFAULT_THRESHOLD,
    DEFAULT_TIMEOUT,
)
from bmad_assist.deep_verify.methods.domain_expert import (
    DOMAIN_EXPERT_SYSTEM_PROMPT,
    DomainExpertAnalysisResponse,
    DomainExpertMethod,
    DomainExpertViolationData,
    resolve_finding_severity,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider() -> Generator[MagicMock, None, None]:
    """Mock the ClaudeSDKProvider.

    This fixture MUST be applied BEFORE creating DomainExpertMethod instances
    to ensure they use the mocked provider instead of making real API calls.
    """
    with patch(
        "bmad_assist.deep_verify.methods.domain_expert.ClaudeSDKProvider"
    ) as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def method(mock_provider: MagicMock) -> DomainExpertMethod:
    """Create a DomainExpertMethod instance with mocked provider.

    Depends on mock_provider to ensure the provider is mocked before
    DomainExpertMethod is instantiated.
    """
    return DomainExpertMethod()


@pytest.fixture
def sample_rules() -> list[KnowledgeRule]:
    """Create sample knowledge rules for testing."""
    return [
        KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="SQL Injection Prevention",
            description="Use parameterized queries to prevent SQL injection.",
            severity=Severity.CRITICAL,
            references=["https://example.com/sql"],
        ),
        KnowledgeRule(
            id="GEN-001",
            domain="general",
            category=KnowledgeCategory.BEST_PRACTICES,
            title="Input Validation",
            description="Validate all function inputs.",
            severity=Severity.WARNING,
        ),
        KnowledgeRule(
            id="HEUR-001",
            domain="general",
            category=KnowledgeCategory.HEURISTICS,
            title="Magic Numbers",
            description="Avoid magic numbers in code.",
            severity=Severity.INFO,
        ),
    ]


@pytest.fixture
def sample_violation() -> DomainExpertViolationData:
    """Create a sample violation for testing."""
    return DomainExpertViolationData(
        rule_id="SEC-001",
        rule_title="SQL Injection Prevention",
        evidence_quote="query = f'SELECT * FROM users WHERE id = {user_id}'",
        line_number=42,
        violation_explanation="String interpolation in SQL query allows injection.",
        remediation="Use parameterized queries instead.",
        confidence=0.95,
    )


# =============================================================================
# Test Method Initialization
# =============================================================================


class TestMethodInitialization:
    """Tests for DomainExpertMethod initialization."""

    def test_default_initialization(self) -> None:
        """Test method initializes with default values."""
        method = DomainExpertMethod()

        assert method.method_id == MethodId("#203")
        assert method._model == DEFAULT_MODEL
        assert method._threshold == DEFAULT_THRESHOLD
        assert method._timeout == DEFAULT_TIMEOUT

    def test_custom_initialization(self) -> None:
        """Test method initializes with custom values."""
        method = DomainExpertMethod(
            model="opus",
            threshold=0.8,
            timeout=60,
        )

        assert method._model == "opus"
        assert method._threshold == 0.8
        assert method._timeout == 60

    def test_invalid_threshold(self) -> None:
        """Test that invalid threshold raises ValueError."""
        with pytest.raises(ValueError, match="threshold must be between"):
            DomainExpertMethod(threshold=1.5)

        with pytest.raises(ValueError, match="threshold must be between"):
            DomainExpertMethod(threshold=-0.1)

    def test_method_repr(self, method: DomainExpertMethod) -> None:
        """Test method repr."""
        repr_str = repr(method)

        assert "DomainExpertMethod" in repr_str
        assert "#203" in repr_str
        assert DEFAULT_MODEL in repr_str
        assert str(DEFAULT_THRESHOLD) in repr_str


# =============================================================================
# Test Severity Resolution
# =============================================================================


class TestResolveFindingSeverity:
    """Tests for resolve_finding_severity function."""

    def test_standards_critical(self) -> None:
        """Test STANDARDS rule with CRITICAL severity."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test",
            description="Test",
            severity=Severity.CRITICAL,
        )

        assert resolve_finding_severity(rule) == Severity.CRITICAL

    def test_standards_error(self) -> None:
        """Test STANDARDS rule with ERROR severity."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test",
            description="Test",
            severity=Severity.ERROR,
        )

        assert resolve_finding_severity(rule) == Severity.ERROR

    def test_standards_warning_defaults_to_error(self) -> None:
        """Test STANDARDS rule with WARNING severity defaults to ERROR."""
        rule = KnowledgeRule(
            id="SEC-001",
            domain="security",
            category=KnowledgeCategory.STANDARDS,
            title="Test",
            description="Test",
            severity=Severity.WARNING,
        )

        # Standards rules default to ERROR if not CRITICAL/ERROR
        assert resolve_finding_severity(rule) == Severity.ERROR

    def test_compliance_critical(self) -> None:
        """Test COMPLIANCE rule with CRITICAL severity."""
        rule = KnowledgeRule(
            id="COMP-001",
            domain="compliance",
            category=KnowledgeCategory.COMPLIANCE,
            title="Test",
            description="Test",
            severity=Severity.CRITICAL,
        )

        assert resolve_finding_severity(rule) == Severity.CRITICAL

    def test_compliance_no_explicit_severity_defaults_error(self) -> None:
        """Test COMPLIANCE rule without explicit CRITICAL/ERROR defaults to ERROR."""
        rule = KnowledgeRule(
            id="COMP-001",
            domain="compliance",
            category=KnowledgeCategory.COMPLIANCE,
            title="Test",
            description="Test",
            severity=Severity.INFO,
        )

        assert resolve_finding_severity(rule) == Severity.ERROR

    def test_best_practices_always_warning(self) -> None:
        """Test BEST_PRACTICES always returns WARNING."""
        rule = KnowledgeRule(
            id="BP-001",
            domain="general",
            category=KnowledgeCategory.BEST_PRACTICES,
            title="Test",
            description="Test",
            severity=Severity.CRITICAL,  # Even with CRITICAL, should be WARNING
        )

        assert resolve_finding_severity(rule) == Severity.WARNING

    def test_heuristics_always_info(self) -> None:
        """Test HEURISTICS always returns INFO."""
        rule = KnowledgeRule(
            id="HEUR-001",
            domain="general",
            category=KnowledgeCategory.HEURISTICS,
            title="Test",
            description="Test",
            severity=Severity.CRITICAL,  # Even with CRITICAL, should be INFO
        )

        assert resolve_finding_severity(rule) == Severity.INFO


# =============================================================================
# Test Pydantic Models
# =============================================================================


class TestDomainExpertViolationData:
    """Tests for DomainExpertViolationData model."""

    def test_valid_violation(self) -> None:
        """Test creating valid violation data."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test Rule",
            evidence_quote="code snippet",
            line_number=42,
            violation_explanation="Explanation",
            remediation="Fix it",
            confidence=0.85,
        )

        assert violation.rule_id == "SEC-001"
        assert violation.confidence == 0.85

    def test_optional_line_number(self) -> None:
        """Test violation without line number."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test Rule",
            evidence_quote="code snippet",
            line_number=None,
            violation_explanation="Explanation",
            remediation="Fix it",
            confidence=0.85,
        )

        assert violation.line_number is None

    def test_confidence_bounds(self) -> None:
        """Test confidence must be between 0.0 and 1.0."""
        # Valid
        DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.0,
        )

        DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=1.0,
        )

        # Invalid
        with pytest.raises(ValueError):
            DomainExpertViolationData(
                rule_id="SEC-001",
                rule_title="Test",
                evidence_quote="code",
                violation_explanation="Test",
                remediation="Fix",
                confidence=1.5,
            )

    def test_required_fields(self) -> None:
        """Test required fields must not be empty."""
        with pytest.raises(ValueError):
            DomainExpertViolationData(
                rule_id="",  # Empty not allowed
                rule_title="Test",
                evidence_quote="code",
                violation_explanation="Test",
                remediation="Fix",
                confidence=0.5,
            )


class TestDomainExpertAnalysisResponse:
    """Tests for DomainExpertAnalysisResponse model."""

    def test_empty_response(self) -> None:
        """Test empty response (no violations)."""
        response = DomainExpertAnalysisResponse()

        assert response.violations == []

    def test_with_violations(self, sample_violation: DomainExpertViolationData) -> None:
        """Test response with violations."""
        response = DomainExpertAnalysisResponse(violations=[sample_violation])

        assert len(response.violations) == 1
        assert response.violations[0].rule_id == "SEC-001"

    def test_multiple_violations(self) -> None:
        """Test response with multiple violations."""
        violations = [
            DomainExpertViolationData(
                rule_id=f"SEC-{i:03d}",
                rule_title=f"Rule {i}",
                evidence_quote="code",
                violation_explanation="Test",
                remediation="Fix",
                confidence=0.8,
            )
            for i in range(5)
        ]

        response = DomainExpertAnalysisResponse(violations=violations)

        assert len(response.violations) == 5


# =============================================================================
# Test LLM Response Parsing
# =============================================================================


class TestParseResponse:
    """Tests for _parse_response method."""

    def test_parse_json_code_block(self, method: DomainExpertMethod) -> None:
        """Test parsing JSON inside markdown code block."""
        raw_response = """
        ```json
        {
            "violations": [
                {
                    "rule_id": "SEC-001",
                    "rule_title": "Test Rule",
                    "evidence_quote": "code",
                    "line_number": 42,
                    "violation_explanation": "Test",
                    "remediation": "Fix",
                    "confidence": 0.85
                }
            ]
        }
        ```
        """

        response = method._parse_response(raw_response)

        assert len(response.violations) == 1
        assert response.violations[0].rule_id == "SEC-001"

    def test_parse_plain_json(self, method: DomainExpertMethod) -> None:
        """Test parsing plain JSON without code block."""
        raw_response = """
        {
            "violations": [
                {
                    "rule_id": "SEC-001",
                    "rule_title": "Test Rule",
                    "evidence_quote": "code",
                    "violation_explanation": "Test",
                    "remediation": "Fix",
                    "confidence": 0.85
                }
            ]
        }
        """

        response = method._parse_response(raw_response)

        assert len(response.violations) == 1

    def test_parse_empty_response(self, method: DomainExpertMethod) -> None:
        """Test parsing empty JSON object."""
        raw_response = "{}"

        response = method._parse_response(raw_response)

        assert response.violations == []

    def test_parse_violations_array_directly(self, method: DomainExpertMethod) -> None:
        """Test parsing when violations array is in JSON-like format."""
        raw_response = '{"violations": []}'

        # This should parse successfully
        response = method._parse_response(raw_response)
        assert response.violations == []

    def test_parse_invalid_json(self, method: DomainExpertMethod) -> None:
        """Test parsing invalid JSON raises error."""
        raw_response = "not valid json"

        with pytest.raises(ValueError):
            method._parse_response(raw_response)


# =============================================================================
# Test Finding Creation
# =============================================================================


class TestCreateFindingFromViolation:
    """Tests for _create_finding_from_violation method."""

    def test_create_finding_basic(
        self,
        method: DomainExpertMethod,
        sample_violation: DomainExpertViolationData,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test basic finding creation."""
        finding = method._create_finding_from_violation(
            sample_violation, index=1, rules=sample_rules
        )

        assert isinstance(finding, Finding)
        assert finding.id == "#203-F1"
        assert finding.method_id == MethodId("#203")
        assert finding.pattern_id == PatternId("SEC-001")
        assert finding.severity == Severity.CRITICAL  # From rule

    def test_finding_id_1_based_indexing(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test finding IDs use 1-based indexing."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding1 = method._create_finding_from_violation(violation, index=1, rules=sample_rules)
        finding2 = method._create_finding_from_violation(violation, index=2, rules=sample_rules)

        assert finding1.id == "#203-F1"
        assert finding2.id == "#203-F2"

    def test_title_truncation(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test title is truncated to 80 characters."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="A" * 100,  # Very long title
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert len(finding.title) <= 80
        assert finding.title.endswith("...")

    def test_title_not_truncated_if_short(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test short title is not truncated."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Short Title",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert finding.title == "Short Title"

    def test_evidence_creation(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test evidence is created from violation data."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="code snippet here",
            line_number=42,
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert len(finding.evidence) == 1
        evidence = finding.evidence[0]
        assert isinstance(evidence, Evidence)
        assert evidence.quote == "code snippet here"
        assert evidence.line_number == 42
        assert evidence.source == "#203"
        assert evidence.confidence == 0.85

    def test_evidence_skipped_if_empty(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test evidence is skipped if quote is empty."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="   ",  # Empty/whitespace
            line_number=42,
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert len(finding.evidence) == 0

    def test_description_includes_rule_details(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test description includes rule description and references."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="SQL Injection",
            evidence_quote="code",
            violation_explanation="SQL injection vulnerability found",
            remediation="Use parameterized queries",
            confidence=0.95,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        # Description uses rule_title from violation and rule description
        assert "SQL Injection" in finding.description
        assert "parameterized queries" in finding.description.lower()
        assert "https://example.com/sql" in finding.description
        assert "Use parameterized queries" in finding.description

    def test_domain_from_rule(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test domain is extracted from rule."""
        violation = DomainExpertViolationData(
            rule_id="SEC-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert finding.domain == ArtifactDomain.SECURITY

    def test_domain_none_for_general(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test domain is None for general rules."""
        violation = DomainExpertViolationData(
            rule_id="GEN-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert finding.domain is None

    def test_severity_from_best_practices_rule(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test severity resolution for best practices rule."""
        violation = DomainExpertViolationData(
            rule_id="GEN-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        # BEST_PRACTICES always returns WARNING
        assert finding.severity == Severity.WARNING

    def test_severity_from_heuristics_rule(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test severity resolution for heuristics rule."""
        violation = DomainExpertViolationData(
            rule_id="HEUR-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        # HEURISTICS always returns INFO
        assert finding.severity == Severity.INFO

    def test_pattern_id_from_violation(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test pattern_id is set from violation rule_id."""
        violation = DomainExpertViolationData(
            rule_id="SEC-OWASP-A01",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=sample_rules)

        assert finding.pattern_id == PatternId("SEC-OWASP-A01")

    def test_fallback_severity_if_rule_not_found(
        self,
        method: DomainExpertMethod,
    ) -> None:
        """Test fallback severity if rule not found."""
        violation = DomainExpertViolationData(
            rule_id="UNKNOWN-001",
            rule_title="Test",
            evidence_quote="code",
            violation_explanation="Test",
            remediation="Fix",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=[])

        # Should fallback to WARNING
        assert finding.severity == Severity.WARNING


# =============================================================================
# Test Analyze Method
# =============================================================================


class TestAnalyze:
    """Tests for analyze method."""

    @pytest.mark.asyncio
    async def test_empty_artifact(self, method: DomainExpertMethod) -> None:
        """Test analyze with empty artifact returns empty list."""
        findings = await method.analyze("")
        assert findings == []

        findings = await method.analyze("   ")
        assert findings == []

    @pytest.mark.asyncio
    async def test_no_rules_available(
        self,
        method: DomainExpertMethod,
    ) -> None:
        """Test analyze when no rules are available."""
        # Mock loader to return empty list
        method._loader.load = MagicMock(return_value=[])

        findings = await method.analyze("some code")

        assert findings == []

    @pytest.mark.asyncio
    async def test_analyze_with_violations(
        self,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test analyze finds violations."""
        with patch(
            "bmad_assist.deep_verify.methods.domain_expert.ClaudeSDKProvider"
        ) as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider_class.return_value = mock_provider

            method = DomainExpertMethod()
            method._loader.load = MagicMock(return_value=sample_rules)

            # Mock provider response
            mock_result = MagicMock()
            mock_result.stdout = json.dumps({
                "violations": [
                    {
                        "rule_id": "SEC-001",
                        "rule_title": "SQL Injection",
                        "evidence_quote": "f'SELECT * FROM users'",
                        "line_number": 10,
                        "violation_explanation": "SQL injection risk",
                        "remediation": "Use params",
                        "confidence": 0.9,
                    }
                ]
            })
            mock_result.exit_code = 0
            mock_provider.invoke.return_value = mock_result
            mock_provider.parse_output.return_value = mock_result.stdout

            findings = await method.analyze("some code with sql")

            assert len(findings) == 1
            assert findings[0].id == "#203-F1"

    @pytest.mark.asyncio
    async def test_analyze_threshold_filtering(
        self,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test that violations below threshold are filtered."""
        with patch(
            "bmad_assist.deep_verify.methods.domain_expert.ClaudeSDKProvider"
        ) as mock_provider_class:
            mock_provider = MagicMock()
            mock_provider_class.return_value = mock_provider

            method = DomainExpertMethod(threshold=0.7)
            method._loader.load = MagicMock(return_value=sample_rules)

            mock_result = MagicMock()
            mock_result.stdout = json.dumps({
                "violations": [
                    {
                        "rule_id": "SEC-001",
                        "rule_title": "High Confidence",
                        "evidence_quote": "code",
                        "violation_explanation": "Test",
                        "remediation": "Fix",
                        "confidence": 0.9,  # Above threshold
                    },
                    {
                        "rule_id": "GEN-001",
                        "rule_title": "Low Confidence",
                        "evidence_quote": "code",
                        "violation_explanation": "Test",
                        "remediation": "Fix",
                        "confidence": 0.5,  # Below threshold
                    },
                ]
            })
            mock_result.exit_code = 0
            mock_provider.invoke.return_value = mock_result
            mock_provider.parse_output.return_value = mock_result.stdout

            findings = await method.analyze("some code")

            # Only high confidence finding should be included
            assert len(findings) == 1
            assert findings[0].title == "High Confidence"

    @pytest.mark.asyncio
    async def test_analyze_provider_error(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test handling of provider error."""
        method._loader.load = MagicMock(return_value=sample_rules)
        mock_provider.invoke.side_effect = ProviderError("API error")

        findings = await method.analyze("some code")

        # Should return empty list, not raise
        assert findings == []

    @pytest.mark.asyncio
    async def test_analyze_timeout_error(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test handling of timeout error."""
        method._loader.load = MagicMock(return_value=sample_rules)
        mock_provider.invoke.side_effect = ProviderTimeoutError("Timeout")

        findings = await method.analyze("some code")

        assert findings == []

    @pytest.mark.asyncio
    async def test_analyze_json_decode_error(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test handling of JSON decode error."""
        method._loader.load = MagicMock(return_value=sample_rules)

        mock_result = MagicMock()
        mock_result.stdout = "not valid json"
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = "not valid json"

        findings = await method.analyze("some code")

        assert findings == []

    @pytest.mark.asyncio
    async def test_analyze_no_violations(
        self,
        method: DomainExpertMethod,
        mock_provider: MagicMock,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test analyze when no violations found."""
        method._loader.load = MagicMock(return_value=sample_rules)

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze("clean code")

        assert findings == []


# =============================================================================
# Test Prompt Building
# =============================================================================


class TestBuildPrompt:
    """Tests for _build_prompt method."""

    def test_prompt_includes_system_prompt(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test prompt includes system prompt."""
        prompt = method._build_prompt("some code", sample_rules)

        assert DOMAIN_EXPERT_SYSTEM_PROMPT in prompt

    def test_prompt_includes_artifact_text(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test prompt includes artifact text."""
        prompt = method._build_prompt("def test(): pass", sample_rules)

        assert "def test(): pass" in prompt

    def test_prompt_includes_rules(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test prompt includes rules."""
        prompt = method._build_prompt("code", sample_rules)

        assert "SEC-001" in prompt
        assert "SQL Injection Prevention" in prompt
        assert "GEN-001" in prompt

    def test_prompt_truncation_notice(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test prompt includes truncation notice for long artifacts."""
        long_code = "x" * 4000  # Longer than MAX_ARTIFACT_LENGTH

        prompt = method._build_prompt(long_code, sample_rules)

        assert "truncated" in prompt.lower() or "IMPORTANT" in prompt

    def test_prompt_format_instructions(
        self,
        method: DomainExpertMethod,
        sample_rules: list[KnowledgeRule],
    ) -> None:
        """Test prompt includes format instructions."""
        prompt = method._build_prompt("code", sample_rules)

        assert "rule_id" in prompt
        assert "evidence_quote" in prompt
        assert "confidence" in prompt


# =============================================================================
# Test Integration with Real Knowledge Base
# =============================================================================


class TestRealKnowledgeBaseIntegration:
    """Tests using real knowledge base files."""

    @pytest.mark.asyncio
    async def test_loads_real_rules(self) -> None:
        """Test that method loads real knowledge base rules."""
        method = DomainExpertMethod()

        # Load rules with security domain
        rules = method._loader.load([ArtifactDomain.SECURITY])

        # Should have base + security rules
        assert len(rules) >= 15

        # Check for expected rules
        ids = {r.id for r in rules}
        assert "GEN-001" in ids  # From base.yaml
        assert "SEC-OWASP-A01" in ids  # From security.yaml

    @pytest.mark.asyncio
    async def test_finding_with_real_security_rule(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test finding creation with real security rule."""
        method = DomainExpertMethod()

        # Get real security rules
        rules = method._loader.load([ArtifactDomain.SECURITY])

        # Create a violation for OWASP A01
        violation = DomainExpertViolationData(
            rule_id="SEC-OWASP-A01",
            rule_title="Broken Access Control",
            evidence_quote="user_id = request.args.get('id')",
            line_number=25,
            violation_explanation="No authorization check before accessing user data",
            remediation="Add authorization check to verify user can access this resource",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.CRITICAL
        assert finding.pattern_id == PatternId("SEC-OWASP-A01")
        assert finding.domain == ArtifactDomain.SECURITY
        assert finding.description.find("https://owasp.org") >= 0

    def test_finding_with_real_api_rule(self) -> None:
        """Test finding creation with real API rule."""
        method = DomainExpertMethod()

        # Get real API rules
        rules = method._loader.load([ArtifactDomain.API])

        # Create a violation for rate limiting rule
        violation = DomainExpertViolationData(
            rule_id="API-RATE-001",
            rule_title="Missing Rate Limiting",
            evidence_quote="@app.route('/api/data')\ndef get_data():",
            line_number=15,
            violation_explanation="API endpoint has no rate limiting protection",
            remediation="Add rate limiting middleware or decorator",
            confidence=0.85,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.CRITICAL
        assert finding.pattern_id == PatternId("API-RATE-001")
        assert finding.domain == ArtifactDomain.API
        assert finding.description.find("https://tools.ietf.org") >= 0

    def test_finding_with_real_concurrency_rule(self) -> None:
        """Test finding creation with real CONCURRENCY rule."""
        method = DomainExpertMethod()

        # Get real concurrency rules
        rules = method._loader.load([ArtifactDomain.CONCURRENCY])

        # Create a violation for goroutine leak rule
        violation = DomainExpertViolationData(
            rule_id="CC-PATTERN-001",
            rule_title="Goroutine Leak Risk",
            evidence_quote="go func() { for { data := <-ch } }()",
            line_number=42,
            violation_explanation="Goroutine has no exit condition and will leak",
            remediation="Add context cancellation or close channel to signal exit",
            confidence=0.9,
        )

        finding = method._create_finding_from_violation(violation, index=1, rules=rules)

        assert finding.id == "#203-F1"
        assert finding.severity == Severity.CRITICAL
        assert finding.pattern_id == PatternId("CC-PATTERN-001")
        assert finding.domain == ArtifactDomain.CONCURRENCY
        assert finding.description.find("https://go.dev") >= 0

    def test_api_rules_loaded_with_api_domain(self) -> None:
        """Test that API rules are loaded when API domain is specified."""
        method = DomainExpertMethod()

        rules = method._loader.load([ArtifactDomain.API])

        # Check API rules are present
        api_rules = [r for r in rules if r.domain == "api"]
        assert len(api_rules) == 17

        # Check specific rules exist
        ids = {r.id for r in rules}
        assert "API-REST-001" in ids
        assert "API-RATE-001" in ids
        assert "API-IDEMPOTENCY-001" in ids

    def test_concurrency_rules_loaded_with_concurrency_domain(self) -> None:
        """Test that CONCURRENCY rules are loaded when CONCURRENCY domain is specified."""
        method = DomainExpertMethod()

        rules = method._loader.load([ArtifactDomain.CONCURRENCY])

        # Check CONCURRENCY rules are present
        cc_rules = [r for r in rules if r.domain == "concurrency"]
        assert len(cc_rules) == 17

        # Check specific rules exist
        ids = {r.id for r in rules}
        assert "CC-PATTERN-001" in ids
        assert "CC-MUTEX-001" in ids
        assert "CC-CHANNEL-001" in ids

    def test_api_and_concurrency_rules_together(self) -> None:
        """Test that both API and CONCURRENCY rules can be loaded together."""
        method = DomainExpertMethod()

        rules = method._loader.load([ArtifactDomain.API, ArtifactDomain.CONCURRENCY])

        api_rules = [r for r in rules if r.domain == "api"]
        cc_rules = [r for r in rules if r.domain == "concurrency"]
        base_rules = [r for r in rules if r.domain == "general"]

        assert len(api_rules) == 17
        assert len(cc_rules) == 17
        assert len(base_rules) == 8
        assert len(rules) == 42  # Total unique rules


# =============================================================================
# Test Constants
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_system_prompt_defined(self) -> None:
        """Test that system prompt is defined."""
        assert DOMAIN_EXPERT_SYSTEM_PROMPT is not None
        assert len(DOMAIN_EXPERT_SYSTEM_PROMPT) > 100
        assert "domain expert" in DOMAIN_EXPERT_SYSTEM_PROMPT.lower()

    def test_system_prompt_includes_instructions(self) -> None:
        """Test system prompt includes key instructions."""
        prompt_lower = DOMAIN_EXPERT_SYSTEM_PROMPT.lower()
        assert "rule" in prompt_lower
        assert "evidence" in prompt_lower
        assert "json" in prompt_lower
        assert "JSON" in DOMAIN_EXPERT_SYSTEM_PROMPT


# =============================================================================
# Test Async Behavior
# =============================================================================


class TestAsyncBehavior:
    """Tests for async behavior."""

    @pytest.mark.asyncio
    async def test_analyze_is_async(self, method: DomainExpertMethod) -> None:
        """Test that analyze method is async."""
        # Should not raise when awaited
        result = await method.analyze("")
        assert isinstance(result, list)

    def test_analyze_requires_await(self, method: DomainExpertMethod) -> None:
        """Test that analyze returns a coroutine when not awaited."""
        result = method.analyze("")
        # In Python 3.8+, coroutines are not detected by inspect.iscoroutine
        # So we just check it's not a list yet
        assert not isinstance(result, list)
        # Clean up the coroutine
        result.close()


# =============================================================================
# Test Runs for All Domains
# =============================================================================


class TestRunsForAllDomains:
    """Tests that method runs for all domains (not conditional)."""

    @pytest.mark.asyncio
    async def test_runs_with_no_domains(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs even with no domains (loads base rules)."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze("some code", domains=None)

        # Should still run with base rules
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_runs_with_security_domain(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs with security domain."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze("some code", domains=[ArtifactDomain.SECURITY])

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_runs_with_multiple_domains(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs with multiple domains."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze(
            "some code",
            domains=[ArtifactDomain.SECURITY, ArtifactDomain.API]
        )

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_runs_with_api_domain(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs with API domain."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze("some code", domains=[ArtifactDomain.API])

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_runs_with_concurrency_domain(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs with CONCURRENCY domain."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze("some code", domains=[ArtifactDomain.CONCURRENCY])

        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_runs_with_api_and_concurrency_domains(
        self,
        mock_provider: MagicMock,
    ) -> None:
        """Test method runs with both API and CONCURRENCY domains."""
        method = DomainExpertMethod()

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"violations": []})
        mock_provider.invoke.return_value = mock_result
        mock_provider.parse_output.return_value = mock_result.stdout

        findings = await method.analyze(
            "some code",
            domains=[ArtifactDomain.API, ArtifactDomain.CONCURRENCY]
        )

        assert isinstance(findings, list)
