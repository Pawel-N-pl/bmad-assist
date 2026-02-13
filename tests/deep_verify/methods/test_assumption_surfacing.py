"""Tests for Assumption Surfacing Method (#155).

This module tests the AssumptionSurfacingMethod class that identifies
implicit assumptions in implementation artifacts.
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    Evidence,
    Finding,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.methods.assumption_surfacing import (
    ASSUMPTION_CATEGORIES,
    ASSUMPTION_SURFACING_SYSTEM_PROMPT,
    AssumptionAnalysisResponse,
    AssumptionCategory,
    AssumptionDefinition,
    AssumptionFindingData,
    AssumptionSurfacingMethod,
    RiskLevel,
    get_category_definitions,
    risk_to_confidence,
    risk_to_severity,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock ClaudeSDKProvider."""
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(
        stdout="",
        stderr="",
        exit_code=0,
        duration_ms=100,
        model="haiku",
        command=["claude", "--model", "haiku"],
    )
    return mock


@pytest.fixture
def method(mock_provider: MagicMock) -> AssumptionSurfacingMethod:
    """Create an AssumptionSurfacingMethod with mocked provider."""
    with patch(
        "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider",
        return_value=mock_provider,
    ):
        m = AssumptionSurfacingMethod()
        return m


@pytest.fixture
def concurrency_artifact() -> str:
    """Sample concurrency artifact for testing."""
    return """
func deliver(payload []byte, destinations []string) {
    for _, dest := range destinations {
        go func(d string) {
            sender.Send(d, payload)
        }(dest)
    }
}
"""


@pytest.fixture
def api_artifact() -> str:
    """Sample API artifact for testing."""
    return """
func handleRequest(ctx context.Context, req *Request) error {
    user := auth.ValidateToken(req.Header.Get("Authorization"))
    return processUser(user)
}
"""


@pytest.fixture
def storage_artifact() -> str:
    """Sample storage artifact (should be skipped)."""
    return """
func saveToDB(db *sql.DB, data Data) error {
    _, err := db.Exec("INSERT INTO data (value) VALUES (?)", data.Value)
    return err
}
"""


@pytest.fixture
def mock_llm_response_payload_immutability() -> str:
    """Mock LLM response for payload immutability assumption."""
    return json.dumps({
        "assumptions": [
            {
                "assumption": "payload is immutable during concurrent delivery",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "sender.Send(d, payload)",
                "line_number": 5,
                "consequences": "Race condition if payload modified by another goroutine",
                "recommendation": "Copy payload before sending or document immutability requirement",
            }
        ]
    })


@pytest.fixture
def mock_llm_response_channel_close() -> str:
    """Mock LLM response for channel close assumption."""
    return json.dumps({
        "assumptions": [
            {
                "assumption": "channel close exactly once guarantee",
                "category": "ordering",
                "violation_risk": "high",
                "evidence_quote": "close(m.stopCh)",
                "line_number": 3,
                "consequences": "Panic if Stop() called multiple times",
                "recommendation": "Add sync.Once or check if already closed",
            }
        ]
    })


@pytest.fixture
def mock_llm_response_context_respect() -> str:
    """Mock LLM response for API context respect assumption."""
    return json.dumps({
        "assumptions": [
            {
                "assumption": "external client.Send respects context cancellation",
                "category": "contract",
                "violation_risk": "medium",
                "evidence_quote": "client.Send(ctx, req)",
                "line_number": 10,
                "consequences": "Request may continue after context cancelled",
                "recommendation": "Verify client respects context or add timeout wrapper",
            }
        ]
    })


@pytest.fixture
def mock_llm_response_multiple_assumptions() -> str:
    """Mock LLM response with multiple assumptions."""
    return json.dumps({
        "assumptions": [
            {
                "assumption": "payload is immutable during concurrent delivery",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "sender.Send(d, payload)",
                "line_number": 5,
                "consequences": "Race condition if payload modified",
                "recommendation": "Copy payload before sending",
            },
            {
                "assumption": "system has sufficient memory for all goroutines",
                "category": "environmental",
                "violation_risk": "low",
                "evidence_quote": "go func(d string)",
                "line_number": 4,
                "consequences": "OOM if too many destinations",
                "recommendation": "Limit concurrent goroutines with semaphore",
            },
            {
                "assumption": "network is available for all sends",
                "category": "environmental",
                "violation_risk": "medium",
                "evidence_quote": "sender.Send(d, payload)",
                "line_number": 5,
                "consequences": "Silent failures if network down",
                "recommendation": "Add error handling and retry logic",
            },
        ]
    })


@pytest.fixture
def mock_llm_response_empty() -> str:
    """Mock LLM response with no assumptions."""
    return json.dumps({"assumptions": []})


# =============================================================================
# Category and Risk Tests
# =============================================================================


class TestAssumptionCategory:
    """Tests for AssumptionCategory enum."""

    def test_enum_values(self) -> None:
        """Test that all expected categories exist."""
        assert AssumptionCategory.ENVIRONMENTAL.value == "environmental"
        assert AssumptionCategory.ORDERING.value == "ordering"
        assert AssumptionCategory.DATA.value == "data"
        assert AssumptionCategory.TIMING.value == "timing"
        assert AssumptionCategory.CONTRACT.value == "contract"

    def test_all_categories_in_definitions(self) -> None:
        """Test that all categories have definitions."""
        assert len(ASSUMPTION_CATEGORIES) == 5
        for cat in AssumptionCategory:
            assert cat in ASSUMPTION_CATEGORIES


class TestRiskLevel:
    """Tests for RiskLevel enum."""

    def test_enum_values(self) -> None:
        """Test that all expected risk levels exist."""
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.LOW.value == "low"


class TestRiskToSeverity:
    """Tests for risk_to_severity function."""

    def test_high_risk_not_dangerous(self) -> None:
        """Test HIGH risk without danger flag maps to ERROR."""
        assert risk_to_severity(RiskLevel.HIGH, is_dangerous=False) == Severity.ERROR

    def test_high_risk_dangerous(self) -> None:
        """Test HIGH risk with danger flag maps to CRITICAL."""
        assert risk_to_severity(RiskLevel.HIGH, is_dangerous=True) == Severity.CRITICAL

    def test_medium_risk(self) -> None:
        """Test MEDIUM risk maps to WARNING."""
        assert risk_to_severity(RiskLevel.MEDIUM) == Severity.WARNING

    def test_low_risk(self) -> None:
        """Test LOW risk maps to INFO."""
        assert risk_to_severity(RiskLevel.LOW) == Severity.INFO


class TestRiskToConfidence:
    """Tests for risk_to_confidence function."""

    def test_high_risk(self) -> None:
        """Test HIGH risk maps to 0.85 confidence."""
        assert risk_to_confidence(RiskLevel.HIGH) == 0.85

    def test_medium_risk(self) -> None:
        """Test MEDIUM risk maps to 0.65 confidence."""
        assert risk_to_confidence(RiskLevel.MEDIUM) == 0.65

    def test_low_risk(self) -> None:
        """Test LOW risk maps to 0.45 confidence."""
        assert risk_to_confidence(RiskLevel.LOW) == 0.45


class TestAssumptionDefinitions:
    """Tests for assumption category definitions."""

    def test_get_category_definitions(self) -> None:
        """Test that get_category_definitions returns all definitions."""
        defs = get_category_definitions()
        assert len(defs) == 5

    def test_definition_structure(self) -> None:
        """Test that each definition has required fields."""
        for cat, definition in ASSUMPTION_CATEGORIES.items():
            assert isinstance(definition, AssumptionDefinition)
            assert definition.id.startswith(("ENV-", "ORD-", "DAT-", "TIM-", "CON-"))
            assert len(definition.description) > 0
            assert len(definition.examples) > 0
            assert isinstance(definition.default_severity, Severity)


# =============================================================================
# Method Instantiation Tests
# =============================================================================


class TestMethodInstantiation:
    """Tests for AssumptionSurfacingMethod instantiation."""

    def test_default_instantiation(self, method: AssumptionSurfacingMethod) -> None:
        """Test method instantiation with default parameters."""
        assert method.method_id == MethodId("#155")
        assert method._model == "haiku"
        assert method._threshold == 0.6
        assert method._timeout == 30
        assert len(method._categories) == 5

    def test_custom_parameters(self) -> None:
        """Test method instantiation with custom parameters."""
        with patch(
            "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider"
        ):
            method = AssumptionSurfacingMethod(
                model="opus",
                threshold=0.7,
                timeout=60,
                categories=[AssumptionCategory.DATA, AssumptionCategory.CONTRACT],
            )
            assert method._model == "opus"
            assert method._threshold == 0.7
            assert method._timeout == 60
            assert len(method._categories) == 2

    def test_invalid_threshold(self) -> None:
        """Test that invalid threshold raises ValueError."""
        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            with patch(
                "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider"
            ):
                AssumptionSurfacingMethod(threshold=1.5)

    def test_repr(self, method: AssumptionSurfacingMethod) -> None:
        """Test __repr__ method."""
        repr_str = repr(method)
        assert "AssumptionSurfacingMethod" in repr_str
        assert "#155" in repr_str
        assert "haiku" in repr_str
        assert "0.6" in repr_str


# =============================================================================
# Domain Filtering Tests
# =============================================================================


class TestDomainFiltering:
    """Tests for domain-based conditional execution."""

    @pytest.mark.asyncio
    async def test_skips_for_storage_domain(self, method: AssumptionSurfacingMethod, storage_artifact: str) -> None:
        """Test that method returns empty list for STORAGE domain."""
        findings = await method.analyze(storage_artifact, domains=[ArtifactDomain.STORAGE])
        assert findings == []

    @pytest.mark.asyncio
    async def test_skips_for_transform_domain(self, method: AssumptionSurfacingMethod) -> None:
        """Test that method returns empty list for TRANSFORM domain."""
        findings = await method.analyze("some code", domains=[ArtifactDomain.TRANSFORM])
        assert findings == []

    @pytest.mark.asyncio
    async def test_skips_for_empty_domains(self, method: AssumptionSurfacingMethod) -> None:
        """Test that method returns empty list for empty domains."""
        findings = await method.analyze("some code", domains=[])
        assert findings == []

    @pytest.mark.asyncio
    async def test_skips_for_none_domains(self, method: AssumptionSurfacingMethod) -> None:
        """Test that method returns empty list for None domains."""
        findings = await method.analyze("some code", domains=None)
        assert findings == []

    @pytest.mark.asyncio
    async def test_runs_for_concurrency_domain(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that method runs for CONCURRENCY domain."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1
        assert findings[0].id == "#155-F1"

    @pytest.mark.asyncio
    async def test_runs_for_api_domain(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_context_respect: str,
        api_artifact: str,
    ) -> None:
        """Test that method runs for API domain."""
        mock_provider.parse_output.return_value = mock_llm_response_context_respect

        findings = await method.analyze(api_artifact, domains=[ArtifactDomain.API])

        assert len(findings) == 1
        assert findings[0].id == "#155-F1"

    @pytest.mark.asyncio
    async def test_runs_for_both_domains(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that method runs when both CONCURRENCY and API domains detected."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(
            concurrency_artifact,
            domains=[ArtifactDomain.CONCURRENCY, ArtifactDomain.API],
        )

        assert len(findings) == 1

    def test_should_run_for_domains_concurrency(self, method: AssumptionSurfacingMethod) -> None:
        """Test _should_run_for_domains with CONCURRENCY."""
        assert method._should_run_for_domains([ArtifactDomain.CONCURRENCY]) is True

    def test_should_run_for_domains_api(self, method: AssumptionSurfacingMethod) -> None:
        """Test _should_run_for_domains with API."""
        assert method._should_run_for_domains([ArtifactDomain.API]) is True

    def test_should_run_for_domains_storage(self, method: AssumptionSurfacingMethod) -> None:
        """Test _should_run_for_domains with STORAGE returns False."""
        assert method._should_run_for_domains([ArtifactDomain.STORAGE]) is False

    def test_should_run_for_domains_empty(self, method: AssumptionSurfacingMethod) -> None:
        """Test _should_run_for_domains with empty list."""
        assert method._should_run_for_domains([]) is False

    def test_should_run_for_domains_none(self, method: AssumptionSurfacingMethod) -> None:
        """Test _should_run_for_domains with None."""
        assert method._should_run_for_domains(None) is False


# =============================================================================
# Empty Artifact Tests
# =============================================================================


class TestEmptyArtifacts:
    """Tests for empty artifact handling."""

    @pytest.mark.asyncio
    async def test_empty_string(self, method: AssumptionSurfacingMethod) -> None:
        """Test that empty string returns empty list."""
        findings = await method.analyze("", domains=[ArtifactDomain.CONCURRENCY])
        assert findings == []

    @pytest.mark.asyncio
    async def test_whitespace_only(self, method: AssumptionSurfacingMethod) -> None:
        """Test that whitespace-only string returns empty list."""
        findings = await method.analyze("   \n\t  ", domains=[ArtifactDomain.CONCURRENCY])
        assert findings == []


# =============================================================================
# Finding Creation Tests
# =============================================================================


class TestFindingCreation:
    """Tests for finding creation from assumption data."""

    @pytest.mark.asyncio
    async def test_finding_id_format(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that finding IDs use correct format."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1
        assert findings[0].id == "#155-F1"

    @pytest.mark.asyncio
    async def test_multiple_findings_ids(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_multiple_assumptions: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that multiple findings get sequential IDs."""
        mock_provider.parse_output.return_value = mock_llm_response_multiple_assumptions

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        # With threshold 0.6, HIGH (0.85) and MEDIUM (0.65) pass, LOW (0.45) doesn't
        assert len(findings) == 2
        assert findings[0].id == "#155-F1"
        assert findings[1].id == "#155-F2"

    @pytest.mark.asyncio
    async def test_finding_title_truncation(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test that long titles are truncated to 80 chars."""
        long_assumption = "a" * 100
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": long_assumption,
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1
        title = findings[0].title
        assert len(title) <= 80
        assert title.startswith("Assumes")

    @pytest.mark.asyncio
    async def test_finding_method_id(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that finding has correct method_id."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].method_id == MethodId("#155")

    @pytest.mark.asyncio
    async def test_finding_pattern_id(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that finding has correct pattern_id."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].pattern_id == PatternId("DAT-001")

    @pytest.mark.asyncio
    async def test_finding_evidence(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test that finding has correct evidence."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings[0].evidence) == 1
        evidence = findings[0].evidence[0]
        assert isinstance(evidence, Evidence)
        assert evidence.quote == "sender.Send(d, payload)"
        assert evidence.line_number == 5
        assert evidence.source == "#155"
        assert evidence.confidence == 0.85  # HIGH risk


# =============================================================================
# Severity Tests
# =============================================================================


class TestSeverityAssignment:
    """Tests for severity assignment based on risk."""

    @pytest.mark.asyncio
    async def test_high_risk_error_severity(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test HIGH risk without dangerous keywords gets ERROR severity."""
        # Non-dangerous high risk assumption
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "network is available",  # Not dangerous
                "category": "environmental",
                "violation_risk": "high",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_high_risk_critical_severity_for_data_race(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test HIGH risk with 'race' keyword gets CRITICAL severity."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "payload is immutable during concurrent modification race",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_high_risk_critical_severity_for_deadlock(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test HIGH risk with 'deadlock' keyword gets CRITICAL severity."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "locks are acquired in order to prevent deadlock",
                "category": "ordering",
                "violation_risk": "high",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].severity == Severity.CRITICAL

    @pytest.mark.asyncio
    async def test_medium_risk_warning_severity(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test MEDIUM risk gets WARNING severity."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "network is available",
                "category": "environmental",
                "violation_risk": "medium",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings[0].severity == Severity.WARNING


# =============================================================================
# Threshold Filtering Tests
# =============================================================================


class TestThresholdFiltering:
    """Tests for confidence threshold filtering."""

    @pytest.mark.asyncio
    async def test_high_risk_passes_threshold(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test HIGH risk (0.85) passes default threshold (0.6)."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "test assumption",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_medium_risk_passes_threshold(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test MEDIUM risk (0.65) passes default threshold (0.6)."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "test assumption",
                "category": "data",
                "violation_risk": "medium",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1

    @pytest.mark.asyncio
    async def test_low_risk_fails_default_threshold(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test LOW risk (0.45) fails default threshold (0.6)."""
        mock_response = json.dumps({
            "assumptions": [{
                "assumption": "test assumption",
                "category": "data",
                "violation_risk": "low",
                "evidence_quote": "test",
            }]
        })
        mock_provider.parse_output.return_value = mock_response

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 0

    @pytest.mark.asyncio
    async def test_low_risk_passes_low_threshold(
        self,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test LOW risk passes when threshold is lowered to 0.4."""
        with patch(
            "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = AssumptionSurfacingMethod(threshold=0.4)
            mock_response = json.dumps({
                "assumptions": [{
                    "assumption": "test assumption",
                    "category": "data",
                    "violation_risk": "low",
                    "evidence_quote": "test",
                }]
            })
            mock_provider.parse_output.return_value = mock_response

            findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

            assert len(findings) == 1


# =============================================================================
# Domain Assignment Tests
# =============================================================================


class TestDomainAssignment:
    """Tests for domain assignment logic."""

    def test_contract_category_assigns_api(self, method: AssumptionSurfacingMethod) -> None:
        """Test CONTRACT category assigns API domain when available."""
        domain = method._assign_domain_for_assumption(
            "contract",
            [ArtifactDomain.CONCURRENCY, ArtifactDomain.API],
        )
        assert domain == ArtifactDomain.API

    def test_contract_category_fallback_concurrency(self, method: AssumptionSurfacingMethod) -> None:
        """Test CONTRACT category falls back to CONCURRENCY if API not available."""
        domain = method._assign_domain_for_assumption(
            "contract",
            [ArtifactDomain.CONCURRENCY],
        )
        assert domain == ArtifactDomain.CONCURRENCY

    def test_data_category_assigns_concurrency(self, method: AssumptionSurfacingMethod) -> None:
        """Test DATA category assigns CONCURRENCY domain."""
        domain = method._assign_domain_for_assumption(
            "data",
            [ArtifactDomain.CONCURRENCY, ArtifactDomain.API],
        )
        assert domain == ArtifactDomain.CONCURRENCY

    def test_data_category_fallback_api(self, method: AssumptionSurfacingMethod) -> None:
        """Test DATA category falls back to API if CONCURRENCY not available."""
        domain = method._assign_domain_for_assumption(
            "data",
            [ArtifactDomain.API],
        )
        assert domain == ArtifactDomain.API


# =============================================================================
# Dangerous Assumption Tests
# =============================================================================


class TestDangerousAssumptions:
    """Tests for dangerous assumption detection."""

    def test_data_race_is_dangerous(self, method: AssumptionSurfacingMethod) -> None:
        """Test that 'race' keyword marks assumption as dangerous."""
        assert method._is_dangerous_assumption("data", "payload race condition") is True

    def test_deadlock_is_dangerous(self, method: AssumptionSurfacingMethod) -> None:
        """Test that 'deadlock' keyword marks assumption as dangerous."""
        assert method._is_dangerous_assumption("ordering", "prevent deadlock") is True

    def test_auth_bypass_is_dangerous(self, method: AssumptionSurfacingMethod) -> None:
        """Test that 'auth' keyword marks assumption as dangerous."""
        assert method._is_dangerous_assumption("contract", "auth bypass") is True

    def test_close_once_is_dangerous(self, method: AssumptionSurfacingMethod) -> None:
        """Test that 'close exactly once' marks assumption as dangerous."""
        assert method._is_dangerous_assumption("ordering", "channel close exactly once") is True

    def test_normal_assumption_not_dangerous(self, method: AssumptionSurfacingMethod) -> None:
        """Test that normal assumptions are not marked dangerous."""
        assert method._is_dangerous_assumption("environmental", "network is available") is False


# =============================================================================
# Response Parsing Tests
# =============================================================================


class TestResponseParsing:
    """Tests for LLM response parsing."""

    def test_parse_valid_json(self, method: AssumptionSurfacingMethod) -> None:
        """Test parsing valid JSON response."""
        json_str = json.dumps({
            "assumptions": [{
                "assumption": "test assumption with enough length",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "test code",
            }]
        })

        result = method._parse_response(json_str)

        assert len(result.assumptions) == 1
        assert "test assumption" in result.assumptions[0].assumption

    def test_parse_markdown_json(self, method: AssumptionSurfacingMethod) -> None:
        """Test parsing JSON wrapped in markdown code block."""
        json_str = '''```json
        {
            "assumptions": [{
                "assumption": "test assumption with enough length",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "code"
            }]
        }
        ```'''

        result = method._parse_response(json_str)

        assert len(result.assumptions) == 1
        assert "test assumption" in result.assumptions[0].assumption

    def test_parse_empty_json(self, method: AssumptionSurfacingMethod) -> None:
        """Test parsing empty JSON object."""
        result = method._parse_response("{}")
        assert len(result.assumptions) == 0

    def test_parse_empty_assumptions(self, method: AssumptionSurfacingMethod) -> None:
        """Test parsing empty assumptions array."""
        result = method._parse_response('{"assumptions": []}')
        assert len(result.assumptions) == 0

    def test_parse_invalid_json_raises_error(self, method: AssumptionSurfacingMethod) -> None:
        """Test that invalid JSON raises ValueError."""
        with pytest.raises(ValueError):
            method._parse_response("not json at all")


class TestPartialJsonHandling:
    """Tests for partial/incomplete JSON handling - fallback parsing."""

    def test_parse_response_filters_assumption_missing_violation_risk(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that assumption missing violation_risk is filtered out with warning."""
        # Simulate LLM response where one assumption is missing violation_risk
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "complete assumption with enough length",
                    "category": "data",
                    "violation_risk": "high",
                    "evidence_quote": "complete code",
                },
                {
                    "assumption": "incomplete assumption missing risk",
                    "category": "ordering",
                    # violation_risk is MISSING
                    "evidence_quote": "incomplete code",
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        # Only the complete assumption should remain
        assert len(result.assumptions) == 1
        assert result.assumptions[0].assumption == "complete assumption with enough length"

        # Should have logged a warning about the incomplete assumption
        assert any("missing required fields" in record.message for record in caplog.records)

    def test_parse_response_filters_assumption_missing_evidence_quote(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that assumption missing evidence_quote is filtered out."""
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "complete assumption with enough length",
                    "category": "data",
                    "violation_risk": "high",
                    "evidence_quote": "code",
                },
                {
                    "assumption": "assumption missing evidence quote",
                    "category": "timing",
                    "violation_risk": "medium",
                    # evidence_quote is MISSING
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        # Only complete assumption should remain
        assert len(result.assumptions) == 1
        assert result.assumptions[0].assumption == "complete assumption with enough length"

    def test_parse_response_filters_assumption_missing_category(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that assumption missing category is filtered out."""
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "complete assumption with enough length",
                    "category": "data",
                    "violation_risk": "high",
                    "evidence_quote": "code",
                },
                {
                    "assumption": "assumption missing category",
                    # category is MISSING
                    "violation_risk": "low",
                    "evidence_quote": "code",
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        assert len(result.assumptions) == 1

    def test_parse_response_filters_assumption_with_empty_required_field(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that assumption with empty string for required field is filtered out."""
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "complete assumption with enough length",
                    "category": "data",
                    "violation_risk": "high",
                    "evidence_quote": "code",
                },
                {
                    "assumption": "",  # Empty assumption
                    "category": "ordering",
                    "violation_risk": "medium",
                    "evidence_quote": "code",
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        # Empty assumption should be filtered out
        assert len(result.assumptions) == 1

    def test_parse_response_returns_empty_when_all_incomplete(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that empty response is returned when all assumptions are incomplete."""
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "first incomplete",
                    # missing violation_risk
                    "category": "data",
                    "evidence_quote": "code1",
                },
                {
                    "assumption": "second incomplete",
                    "category": "timing",
                    # missing evidence_quote
                    "violation_risk": "medium",
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        # All assumptions filtered out
        assert len(result.assumptions) == 0

        # Should have warning about all being incomplete
        assert any("All" in record.message and "incomplete" in record.message for record in caplog.records)

    def test_parse_response_handles_multiple_missing_fields_in_single_assumption(
        self, method: AssumptionSurfacingMethod, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that assumption with multiple missing fields is filtered correctly."""
        partial_json = json.dumps({
            "assumptions": [
                {
                    "assumption": "complete assumption with enough length",
                    "category": "data",
                    "violation_risk": "high",
                    "evidence_quote": "code",
                },
                {
                    "assumption": "very incomplete",
                    # category MISSING
                    # violation_risk MISSING
                    # evidence_quote MISSING
                },
            ]
        })

        with caplog.at_level(logging.WARNING):
            result = method._parse_response(partial_json)

        # Only complete one remains
        assert len(result.assumptions) == 1
        # Warning should mention all missing fields
        assert any("missing required fields" in record.message for record in caplog.records)

    def test_parse_response_preserves_complete_assumptions_with_optional_fields_missing(
        self, method: AssumptionSurfacingMethod
    ) -> None:
        """Test that assumptions with only optional fields missing are kept."""
        # Optional fields: line_number, consequences, recommendation
        json_str = json.dumps({
            "assumptions": [{
                "assumption": "assumption with only required fields and enough length",
                "category": "data",
                "violation_risk": "high",
                "evidence_quote": "code snippet",
                # Optional fields not provided - should still work
            }]
        })

        result = method._parse_response(json_str)

        # Should parse successfully
        assert len(result.assumptions) == 1
        assert result.assumptions[0].line_number is None
        assert result.assumptions[0].consequences == ""
        assert result.assumptions[0].recommendation == ""


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty_list(
        self,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test that LLM failure returns empty list with logged warning."""
        mock_provider.invoke.side_effect = Exception("LLM failed")

        with patch(
            "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider",
            return_value=mock_provider,
        ):
            method = AssumptionSurfacingMethod()
            findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

            assert findings == []

    @pytest.mark.asyncio
    async def test_parse_error_returns_empty_list(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        concurrency_artifact: str,
    ) -> None:
        """Test that parse error returns empty list."""
        mock_provider.parse_output.return_value = "invalid json"

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert findings == []


# =============================================================================
# Prompt Building Tests
# =============================================================================


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_prompt_includes_system_prompt(self, method: AssumptionSurfacingMethod) -> None:
        """Test that prompt includes system prompt."""
        prompt = method._build_prompt("some code")
        assert ASSUMPTION_SURFACING_SYSTEM_PROMPT in prompt

    def test_prompt_includes_artifact(self, method: AssumptionSurfacingMethod) -> None:
        """Test that prompt includes artifact text."""
        artifact = "func main() {}"
        prompt = method._build_prompt(artifact)
        assert artifact in prompt

    def test_prompt_truncates_long_artifact(self, method: AssumptionSurfacingMethod) -> None:
        """Test that long artifacts are truncated to MAX_ARTIFACT_LENGTH."""
        long_artifact = "x" * 5000
        prompt = method._build_prompt(long_artifact)
        # The artifact portion should be truncated to 4000 chars
        # Prompt includes system prompt + truncated artifact + categories
        assert "x" * 4001 not in prompt  # Should not see untruncated artifact

    def test_prompt_includes_categories(self, method: AssumptionSurfacingMethod) -> None:
        """Test that prompt includes category descriptions."""
        prompt = method._build_prompt("code")
        assert "ENVIRONMENTAL" in prompt
        assert "ORDERING" in prompt
        assert "DATA" in prompt
        assert "TIMING" in prompt
        assert "CONTRACT" in prompt

    def test_prompt_with_limited_categories(self) -> None:
        """Test prompt with limited categories."""
        with patch(
            "bmad_assist.deep_verify.methods.assumption_surfacing.ClaudeSDKProvider"
        ):
            method = AssumptionSurfacingMethod(
                categories=[AssumptionCategory.DATA, AssumptionCategory.CONTRACT]
            )
            prompt = method._build_prompt("code")
            # Check that the prompt includes only the selected categories
            # in the user prompt section (not the system prompt)
            assert "DATA" in prompt or "data" in prompt.lower()
            assert "CONTRACT" in prompt or "contract" in prompt.lower()
            # The excluded categories should not appear in the user prompt section
            # Note: "environmental" might appear in system prompt, so we check the specific format
            lines = prompt.split("\n")
            in_user_section = False
            category_lines = []
            for line in lines:
                if "Categories to analyze:" in line:
                    in_user_section = True
                if in_user_section:
                    category_lines.append(line)
            user_section = "\n".join(category_lines)
            assert "DATA" in user_section or "data" in user_section.lower()
            assert "ENVIRONMENTAL" not in user_section


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for the full analysis flow."""

    @pytest.mark.asyncio
    async def test_payload_immutability_scenario(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_payload_immutability: str,
        concurrency_artifact: str,
    ) -> None:
        """Test the payload immutability spike example scenario."""
        mock_provider.parse_output.return_value = mock_llm_response_payload_immutability

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1
        finding = findings[0]
        assert finding.id == "#155-F1"
        assert finding.severity == Severity.CRITICAL  # "race" in consequences
        assert finding.method_id == MethodId("#155")
        assert finding.pattern_id == PatternId("DAT-001")
        assert finding.domain == ArtifactDomain.CONCURRENCY
        assert "payload is immutable" in finding.title.lower()
        assert len(finding.evidence) == 1
        assert finding.evidence[0].line_number == 5

    @pytest.mark.asyncio
    async def test_channel_close_scenario(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_channel_close: str,
    ) -> None:
        """Test the channel close exactly once scenario."""
        artifact = """
func (m *Manager) Stop() {
    close(m.stopCh)
}
"""
        mock_provider.parse_output.return_value = mock_llm_response_channel_close

        findings = await method.analyze(artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 1
        finding = findings[0]
        assert finding.severity == Severity.CRITICAL  # "close exactly once" = dangerous
        assert "channel" in finding.title.lower()  # Title contains assumption text

    @pytest.mark.asyncio
    async def test_context_respect_scenario(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_context_respect: str,
        api_artifact: str,
    ) -> None:
        """Test the context respect scenario."""
        mock_provider.parse_output.return_value = mock_llm_response_context_respect

        findings = await method.analyze(api_artifact, domains=[ArtifactDomain.API])

        assert len(findings) == 1
        finding = findings[0]
        assert finding.severity == Severity.WARNING  # MEDIUM risk
        assert finding.domain == ArtifactDomain.API
        assert "context" in finding.title.lower() or "respect" in finding.title.lower()

    @pytest.mark.asyncio
    async def test_empty_assumptions_response(
        self,
        method: AssumptionSurfacingMethod,
        mock_provider: MagicMock,
        mock_llm_response_empty: str,
        concurrency_artifact: str,
    ) -> None:
        """Test handling of empty assumptions response."""
        mock_provider.parse_output.return_value = mock_llm_response_empty

        findings = await method.analyze(concurrency_artifact, domains=[ArtifactDomain.CONCURRENCY])

        assert len(findings) == 0


# =============================================================================
# Pydantic Model Tests
# =============================================================================


class TestPydanticModels:
    """Tests for Pydantic validation models."""

    def test_assumption_finding_data_valid(self) -> None:
        """Test valid AssumptionFindingData."""
        data = AssumptionFindingData(
            assumption="test assumption",
            category="data",
            violation_risk="high",
            evidence_quote="code",
            line_number=42,
        )
        assert data.assumption == "test assumption"
        assert data.category == "data"
        assert data.violation_risk == "high"

    def test_assumption_finding_data_invalid_category(self) -> None:
        """Test invalid category raises validation error."""
        with pytest.raises(ValueError):
            AssumptionFindingData(
                assumption="test",
                category="invalid_category",
                violation_risk="high",
            )

    def test_assumption_finding_data_invalid_risk(self) -> None:
        """Test invalid risk raises validation error."""
        with pytest.raises(ValueError):
            AssumptionFindingData(
                assumption="test",
                category="data",
                violation_risk="extreme",  # Invalid
            )

    def test_assumption_finding_data_case_insensitive(self) -> None:
        """Test that category and risk are case-insensitive."""
        data = AssumptionFindingData(
            assumption="test assumption with enough length",
            category="DATA",  # Uppercase
            violation_risk="HIGH",  # Uppercase
            evidence_quote="test code",
        )
        assert data.category == "data"  # Normalized to lowercase
        assert data.violation_risk == "high"  # Normalized to lowercase

    def test_analysis_response_empty(self) -> None:
        """Test AssumptionAnalysisResponse with empty assumptions."""
        response = AssumptionAnalysisResponse(assumptions=[])
        assert len(response.assumptions) == 0

    def test_analysis_response_with_data(self) -> None:
        """Test AssumptionAnalysisResponse with data."""
        response = AssumptionAnalysisResponse(
            assumptions=[
                AssumptionFindingData(
                    assumption="test assumption with enough length",
                    category="data",
                    violation_risk="high",
                    evidence_quote="test code",
                )
            ]
        )
        assert len(response.assumptions) == 1
