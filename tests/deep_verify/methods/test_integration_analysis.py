"""Tests for IntegrationAnalysisMethod (#204).

This module provides comprehensive test coverage for the Integration Analysis
verification method, including domain filtering, finding creation, and
LLM response parsing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.exceptions import ProviderError, ProviderTimeoutError
from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    MethodId,
    PatternId,
    Severity,
)
from bmad_assist.deep_verify.methods.integration_analysis import (
    INTEGRATION_ANALYSIS_SYSTEM_PROMPT,
    INTEGRATION_CATEGORIES,
    IntegrationAnalysisMethod,
    IntegrationAnalysisResponse,
    IntegrationCategory,
    IntegrationDefinition,
    IntegrationIssueData,
    IntegrationRiskLevel,
    _is_critical_issue,
    get_integration_category_definitions,
    risk_to_confidence,
    risk_to_severity,
)

if TYPE_CHECKING:
    from collections.abc import Generator


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider() -> Generator[MagicMock, None, None]:
    """Mock the ClaudeSDKProvider - must be before method fixture."""
    with patch(
        "bmad_assist.deep_verify.methods.integration_analysis.ClaudeSDKProvider"
    ) as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def method(mock_provider: MagicMock) -> IntegrationAnalysisMethod:
    """Create IntegrationAnalysisMethod with mocked provider."""
    return IntegrationAnalysisMethod()


# =============================================================================
# Test Enums and Constants
# =============================================================================


class TestIntegrationCategory:
    """Tests for IntegrationCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that all 5 integration categories are defined."""
        categories = list(IntegrationCategory)
        assert len(categories) == 5
        assert IntegrationCategory.CONTRACT in categories
        assert IntegrationCategory.FAILURE_MODES in categories
        assert IntegrationCategory.VERSIONING in categories
        assert IntegrationCategory.IDEMPOTENCY in categories
        assert IntegrationCategory.RETRY in categories

    def test_category_values(self) -> None:
        """Test category string values."""
        assert IntegrationCategory.CONTRACT.value == "contract"
        assert IntegrationCategory.FAILURE_MODES.value == "failure_modes"
        assert IntegrationCategory.VERSIONING.value == "versioning"
        assert IntegrationCategory.IDEMPOTENCY.value == "idempotency"
        assert IntegrationCategory.RETRY.value == "retry"


class TestIntegrationRiskLevel:
    """Tests for IntegrationRiskLevel enum."""

    def test_all_levels_exist(self) -> None:
        """Test that all 4 risk levels are defined."""
        levels = list(IntegrationRiskLevel)
        assert len(levels) == 4
        assert IntegrationRiskLevel.CRITICAL in levels
        assert IntegrationRiskLevel.HIGH in levels
        assert IntegrationRiskLevel.MEDIUM in levels
        assert IntegrationRiskLevel.LOW in levels

    def test_risk_level_values(self) -> None:
        """Test risk level string values."""
        assert IntegrationRiskLevel.CRITICAL.value == "critical"
        assert IntegrationRiskLevel.HIGH.value == "high"
        assert IntegrationRiskLevel.MEDIUM.value == "medium"
        assert IntegrationRiskLevel.LOW.value == "low"


# =============================================================================
# Test Category Definitions
# =============================================================================


class TestCategoryDefinitions:
    """Tests for INTEGRATION_CATEGORIES and get_integration_category_definitions."""

    def test_all_categories_have_definitions(self) -> None:
        """Test that all integration categories have definitions."""
        for category in IntegrationCategory:
            assert category in INTEGRATION_CATEGORIES
            definition = INTEGRATION_CATEGORIES[category]
            assert isinstance(definition, IntegrationDefinition)
            assert definition.id
            assert definition.description
            assert definition.examples
            assert isinstance(definition.default_severity, Severity)

    def test_category_ids(self) -> None:
        """Test that category IDs follow expected pattern."""
        assert INTEGRATION_CATEGORIES[IntegrationCategory.CONTRACT].id == "INT-CTR-001"
        assert INTEGRATION_CATEGORIES[IntegrationCategory.FAILURE_MODES].id == "INT-FLM-001"
        assert INTEGRATION_CATEGORIES[IntegrationCategory.VERSIONING].id == "INT-VER-001"
        assert INTEGRATION_CATEGORIES[IntegrationCategory.IDEMPOTENCY].id == "INT-IDM-001"
        assert INTEGRATION_CATEGORIES[IntegrationCategory.RETRY].id == "INT-RTY-001"

    def test_get_integration_category_definitions(self) -> None:
        """Test get_integration_category_definitions returns all definitions."""
        definitions = get_integration_category_definitions()
        assert len(definitions) == 5
        ids = [d.id for d in definitions]
        assert "INT-CTR-001" in ids
        assert "INT-FLM-001" in ids
        assert "INT-VER-001" in ids
        assert "INT-IDM-001" in ids
        assert "INT-RTY-001" in ids


# =============================================================================
# Test Risk Mapping Functions
# =============================================================================


class TestRiskToSeverity:
    """Tests for risk_to_severity function."""

    def test_critical_risk(self) -> None:
        """Test CRITICAL risk maps to CRITICAL severity."""
        assert risk_to_severity(IntegrationRiskLevel.CRITICAL) == Severity.CRITICAL

    def test_high_risk(self) -> None:
        """Test HIGH risk maps to ERROR severity."""
        assert risk_to_severity(IntegrationRiskLevel.HIGH) == Severity.ERROR

    def test_medium_risk(self) -> None:
        """Test MEDIUM risk maps to WARNING severity."""
        assert risk_to_severity(IntegrationRiskLevel.MEDIUM) == Severity.WARNING

    def test_low_risk(self) -> None:
        """Test LOW risk maps to INFO severity."""
        assert risk_to_severity(IntegrationRiskLevel.LOW) == Severity.INFO


class TestRiskToConfidence:
    """Tests for risk_to_confidence function."""

    def test_critical_risk(self) -> None:
        """Test CRITICAL risk maps to 0.95 confidence."""
        assert risk_to_confidence(IntegrationRiskLevel.CRITICAL) == 0.95

    def test_high_risk(self) -> None:
        """Test HIGH risk maps to 0.85 confidence."""
        assert risk_to_confidence(IntegrationRiskLevel.HIGH) == 0.85

    def test_medium_risk(self) -> None:
        """Test MEDIUM risk maps to 0.65 confidence."""
        assert risk_to_confidence(IntegrationRiskLevel.MEDIUM) == 0.65

    def test_low_risk(self) -> None:
        """Test LOW risk maps to 0.45 confidence."""
        assert risk_to_confidence(IntegrationRiskLevel.LOW) == 0.45


class TestIsCriticalIssue:
    """Tests for _is_critical_issue function."""

    def test_data_loss_is_critical(self) -> None:
        """Test data loss is critical."""
        assert _is_critical_issue("contract", "Potential data loss on timeout") is True

    def test_duplicate_processing_is_critical(self) -> None:
        """Test duplicate processing is critical."""
        assert _is_critical_issue("idempotency", "Duplicate processing without key") is True

    def test_inconsistent_state_is_critical(self) -> None:
        """Test inconsistent state is critical."""
        assert _is_critical_issue("contract", "Inconsistent state on failure") is True

    def test_unbounded_is_critical(self) -> None:
        """Test unbounded growth is critical."""
        assert _is_critical_issue("retry", "Unbounded retry queue") is True

    def test_infinite_loop_is_critical(self) -> None:
        """Test infinite loop is critical."""
        assert _is_critical_issue("retry", "Infinite loop on retry") is True

    def test_no_fallback_is_critical(self) -> None:
        """Test no fallback is critical."""
        assert _is_critical_issue("failure_modes", "No fallback when service down") is True

    def test_cascade_failure_is_critical(self) -> None:
        """Test cascade failure is critical."""
        assert _is_critical_issue("failure_modes", "Cascade failure risk") is True

    def test_idempotency_duplicate_is_critical(self) -> None:
        """Test idempotency duplicate is critical."""
        assert _is_critical_issue("idempotency", "Duplicate requests processed multiple times") is True

    def test_non_critical_issue(self) -> None:
        """Test non-critical issue returns False."""
        assert _is_critical_issue("versioning", "Deprecated API version") is False

    def test_contract_issue_not_critical(self) -> None:
        """Test normal contract issue is not critical."""
        assert _is_critical_issue("contract", "Missing field validation") is False


# =============================================================================
# Test Method Instantiation
# =============================================================================


class TestMethodInstantiation:
    """Tests for IntegrationAnalysisMethod instantiation."""

    def test_default_instantiation(self) -> None:
        """Test method can be instantiated with defaults."""
        method = IntegrationAnalysisMethod()
        assert method.method_id == MethodId("#204")
        assert method._model == "haiku"
        assert method._threshold == 0.6
        assert method._timeout == 30
        assert len(method._categories) == 5  # All categories

    def test_custom_parameters(self) -> None:
        """Test method can be instantiated with custom parameters."""
        categories = [IntegrationCategory.CONTRACT, IntegrationCategory.IDEMPOTENCY]
        method = IntegrationAnalysisMethod(
            model="sonnet",
            threshold=0.7,
            timeout=60,
            categories=categories,
        )
        assert method._model == "sonnet"
        assert method._threshold == 0.7
        assert method._timeout == 60
        assert method._categories == categories

    def test_invalid_threshold_raises(self) -> None:
        """Test invalid threshold raises ValueError."""
        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            IntegrationAnalysisMethod(threshold=1.5)

        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            IntegrationAnalysisMethod(threshold=-0.1)

    def test_repr(self) -> None:
        """Test __repr__ method."""
        method = IntegrationAnalysisMethod(model="sonnet", threshold=0.7)
        repr_str = repr(method)
        assert "IntegrationAnalysisMethod" in repr_str
        assert "#204" in repr_str
        assert "sonnet" in repr_str
        assert "0.7" in repr_str


# =============================================================================
# Test Domain Filtering
# =============================================================================


class TestDomainFiltering:
    """Tests for domain filtering in analyze method."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_storage_domain(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list for STORAGE domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.STORAGE],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_concurrency_domain(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list for CONCURRENCY domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.CONCURRENCY],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_transform_domain(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list for TRANSFORM domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.TRANSFORM],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_security_domain(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list for SECURITY domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.SECURITY],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_runs_for_api_domain(self, method: IntegrationAnalysisMethod, mock_provider: MagicMock) -> None:
        """Test method runs when API domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"integration_issues": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.API],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_messaging_domain(self, method: IntegrationAnalysisMethod, mock_provider: MagicMock) -> None:
        """Test method runs when MESSAGING domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"integration_issues": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.MESSAGING],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_both_api_and_messaging(self, method: IntegrationAnalysisMethod, mock_provider: MagicMock) -> None:
        """Test method runs when both API and MESSAGING domains are detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"integration_issues": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.API, ArtifactDomain.MESSAGING],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_domains(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list when no domains provided."""
        result = await method.analyze("some code", domains=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_none_domains(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list when domains is None."""
        result = await method.analyze("some code", domains=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_artifact(self, method: IntegrationAnalysisMethod) -> None:
        """Test method returns empty list for empty artifact."""
        result = await method.analyze("", domains=[ArtifactDomain.API])
        assert result == []

        result = await method.analyze("   ", domains=[ArtifactDomain.API])
        assert result == []


# =============================================================================
# Test Finding Creation
# =============================================================================


class TestFindingCreation:
    """Tests for finding creation from LLM response."""

    def test_create_finding_basic(self, method: IntegrationAnalysisMethod) -> None:
        """Test basic finding creation."""
        issue_data = IntegrationIssueData(
            issue="Missing request schema validation",
            category="contract",
            risk="high",
            evidence_quote="user := r.URL.Query().Get(\"user\")",
            line_number=42,
            consequences="Invalid data may cause processing errors",
            recommendation="Add schema validation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert finding.id == "#204-F1"
        assert finding.title == "Missing request schema validation"
        assert finding.method_id == MethodId("#204")
        assert finding.pattern_id == PatternId("INT-CTR-001")
        assert finding.domain == ArtifactDomain.API
        assert len(finding.evidence) == 1
        assert finding.evidence[0].quote == 'user := r.URL.Query().Get("user")'
        assert finding.evidence[0].line_number == 42
        assert finding.evidence[0].source == "#204"

    def test_create_finding_truncates_long_title(self, method: IntegrationAnalysisMethod) -> None:
        """Test long titles are truncated to 80 characters."""
        long_issue = "A" * 100
        issue_data = IntegrationIssueData(
            issue=long_issue,
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert len(finding.title) == 80
        assert finding.title.endswith("...")

    def test_create_finding_critical_severity(self, method: IntegrationAnalysisMethod) -> None:
        """Test CRITICAL severity for critical issue with is_critical flag."""
        issue_data = IntegrationIssueData(
            issue="Duplicate processing without idempotency key causes data corruption",
            category="idempotency",
            risk="high",
            evidence_quote="client.Post(\"/charge\", body)",
            consequences="Duplicate charges processed",
            recommendation="Add Idempotency-Key header",
        )

        # Pass is_critical=True to trigger CRITICAL severity override
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API], is_critical=True
        )

        assert finding.severity == Severity.CRITICAL
        assert finding.evidence[0].confidence == 0.95

    def test_create_finding_explicit_critical_risk(self, method: IntegrationAnalysisMethod) -> None:
        """Test CRITICAL severity for CRITICAL risk level."""
        issue_data = IntegrationIssueData(
            issue="Data loss on timeout",
            category="failure_modes",
            risk="critical",
            evidence_quote="err != nil { return nil }",
            consequences="Data not persisted",
            recommendation="Add retry with persistence",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.MESSAGING]
        )

        assert finding.severity == Severity.CRITICAL
        assert finding.evidence[0].confidence == 0.95

    def test_create_finding_error_severity(self, method: IntegrationAnalysisMethod) -> None:
        """Test ERROR severity for high risk non-critical."""
        issue_data = IntegrationIssueData(
            issue="No timeout configured for external call",
            category="failure_modes",
            risk="high",
            evidence_quote="http.Get(url)",
            consequences="Request may hang indefinitely",
            recommendation="Add timeout context",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert finding.severity == Severity.ERROR

    def test_create_finding_warning_severity(self, method: IntegrationAnalysisMethod) -> None:
        """Test WARNING severity for medium risk."""
        issue_data = IntegrationIssueData(
            issue="Hardcoded API version in URL",
            category="versioning",
            risk="medium",
            evidence_quote="url := \"/v1/users\"",
            consequences="Breaking changes require code updates",
            recommendation="Use version negotiation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert finding.severity == Severity.WARNING

    def test_create_finding_info_severity(self, method: IntegrationAnalysisMethod) -> None:
        """Test INFO severity for low risk."""
        issue_data = IntegrationIssueData(
            issue="Retry logging could be improved",
            category="retry",
            risk="low",
            evidence_quote="log.Printf(\"retrying\")",
            consequences="Harder to debug issues",
            recommendation="Use structured logging",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.MESSAGING]
        )

        assert finding.severity == Severity.INFO

    def test_create_finding_domain_assignment_contract(self, method: IntegrationAnalysisMethod) -> None:
        """Test domain assignment for CONTRACT category."""
        issue_data = IntegrationIssueData(
            issue="Missing validation",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # API takes precedence for contract
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.API

        # Fallback to MESSAGING if API not present
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

    def test_create_finding_domain_assignment_versioning(self, method: IntegrationAnalysisMethod) -> None:
        """Test domain assignment for VERSIONING category."""
        issue_data = IntegrationIssueData(
            issue="Version issue",
            category="versioning",
            risk="medium",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # API takes precedence for versioning
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.API

    def test_create_finding_domain_assignment_idempotency(self, method: IntegrationAnalysisMethod) -> None:
        """Test domain assignment for IDEMPOTENCY category."""
        issue_data = IntegrationIssueData(
            issue="Duplicate issue",
            category="idempotency",
            risk="critical",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # API takes precedence for idempotency
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.API

    def test_create_finding_domain_assignment_failure_modes(self, method: IntegrationAnalysisMethod) -> None:
        """Test domain assignment for FAILURE_MODES category."""
        issue_data = IntegrationIssueData(
            issue="Timeout issue",
            category="failure_modes",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # MESSAGING takes precedence for failure_modes
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.MESSAGING, ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

        # Fallback to API if MESSAGING not present
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.API

    def test_create_finding_domain_assignment_retry(self, method: IntegrationAnalysisMethod) -> None:
        """Test domain assignment for RETRY category."""
        issue_data = IntegrationIssueData(
            issue="No backoff",
            category="retry",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # MESSAGING takes precedence for retry
        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.MESSAGING, ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.MESSAGING


# =============================================================================
# Test Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Tests for _build_prompt method."""

    def test_prompt_includes_system_prompt(self, method: IntegrationAnalysisMethod) -> None:
        """Test prompt includes system prompt."""
        prompt = method._build_prompt("some code")
        assert INTEGRATION_ANALYSIS_SYSTEM_PROMPT in prompt

    def test_prompt_includes_artifact(self, method: IntegrationAnalysisMethod) -> None:
        """Test prompt includes artifact text."""
        code = "func main() {}"
        prompt = method._build_prompt(code)
        assert code in prompt

    def test_prompt_includes_categories(self, method: IntegrationAnalysisMethod) -> None:
        """Test prompt includes category descriptions."""
        prompt = method._build_prompt("code")
        assert "CONTRACT:" in prompt
        assert "FAILURE_MODES:" in prompt
        assert "VERSIONING:" in prompt
        assert "IDEMPOTENCY:" in prompt
        assert "RETRY:" in prompt

    def test_prompt_truncation(self, method: IntegrationAnalysisMethod) -> None:
        """Test long artifacts are truncated."""
        long_code = "x" * 5000
        prompt = method._build_prompt(long_code)

        assert "truncated" in prompt.lower() or "4000" in prompt
        # The actual artifact in prompt should be truncated
        assert len(prompt) < 8000  # Reasonable upper bound (prompt template + 4000 chars)

    def test_custom_categories_in_prompt(self) -> None:
        """Test prompt only includes specified categories."""
        method = IntegrationAnalysisMethod(categories=[IntegrationCategory.CONTRACT])
        prompt = method._build_prompt("code")

        assert "CONTRACT:" in prompt


# =============================================================================
# Test Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for _parse_response method."""

    def test_parse_valid_json(self, method: IntegrationAnalysisMethod) -> None:
        """Test parsing valid JSON response."""
        response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Missing timeout",
                    "category": "failure_modes",
                    "risk": "high",
                    "evidence_quote": "http.Get(url)",
                    "line_number": 42,
                    "consequences": "Request may hang",
                    "recommendation": "Add timeout context",
                }
            ]
        })

        result = method._parse_response(response)
        assert len(result.integration_issues) == 1
        assert result.integration_issues[0].issue == "Missing timeout"
        assert result.integration_issues[0].category == "failure_modes"

    def test_parse_json_in_code_block(self, method: IntegrationAnalysisMethod) -> None:
        """Test parsing JSON inside markdown code block."""
        response = """```json
{
    "integration_issues": [
        {
            "issue": "No retry",
            "category": "retry",
            "risk": "high",
            "evidence_quote": "client.Do(req)",
            "consequences": "Transient failures not handled",
            "recommendation": "Add retry with backoff"
        }
    ]
}
```"""

        result = method._parse_response(response)
        assert len(result.integration_issues) == 1
        assert result.integration_issues[0].issue == "No retry"

    def test_parse_empty_json(self, method: IntegrationAnalysisMethod) -> None:
        """Test parsing empty JSON object."""
        response = "{}"
        result = method._parse_response(response)
        assert len(result.integration_issues) == 0

    def test_parse_no_issues(self, method: IntegrationAnalysisMethod) -> None:
        """Test parsing response with empty integration_issues array."""
        response = '{"integration_issues": []}'
        result = method._parse_response(response)
        assert len(result.integration_issues) == 0

    def test_parse_invalid_category_raises(self, method: IntegrationAnalysisMethod) -> None:
        """Test invalid category raises validation error."""
        response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Something",
                    "category": "invalid_category",
                    "risk": "high",
                    "evidence_quote": "code",
                    "consequences": "consequences",
                    "recommendation": "recommendation",
                }
            ]
        })

        with pytest.raises(Exception):  # Pydantic validation error
            method._parse_response(response)

    def test_parse_invalid_risk_raises(self, method: IntegrationAnalysisMethod) -> None:
        """Test invalid risk raises validation error."""
        response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Something",
                    "category": "contract",
                    "risk": "extreme",
                    "evidence_quote": "code",
                    "consequences": "consequences",
                    "recommendation": "recommendation",
                }
            ]
        })

        with pytest.raises(Exception):  # Pydantic validation error
            method._parse_response(response)


# =============================================================================
# Test Full Analysis Flow
# =============================================================================


class TestFullAnalysisFlow:
    """Integration-style tests for the full analysis flow."""

    @pytest.mark.asyncio
    async def test_contract_validation_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of missing contract validation."""
        artifact = '''
func (h *Handler) CreateUser(w http.ResponseWriter, r *http.Request) {
    var req CreateUserRequest
    json.NewDecoder(r.Body).Decode(&req)
    
    // Direct use without validation
    user := h.db.CreateUser(req.Name, req.Email)
    json.NewEncoder(w).Encode(user)
}
'''

        mock_response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Missing request schema validation",
                    "category": "contract",
                    "risk": "high",
                    "evidence_quote": "json.NewDecoder(r.Body).Decode(&req)",
                    "line_number": 3,
                    "consequences": "Invalid data may cause processing errors or security issues",
                    "recommendation": "Add request schema validation before processing",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.API],
        )

        assert len(findings) == 1
        assert findings[0].title == "Missing request schema validation"
        assert findings[0].severity == Severity.ERROR  # HIGH risk, not critical
        assert findings[0].pattern_id == PatternId("INT-CTR-001")

    @pytest.mark.asyncio
    async def test_idempotency_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of missing idempotency."""
        artifact = '''
func (c *Client) Charge(amount int, userID string) error {
    resp, err := c.httpClient.Post(
        "/api/charge",
        "application/json",
        strings.NewReader(fmt.Sprintf(`{"amount":%d,"user":"%s"}`, amount, userID)),
    )
    if err != nil {
        return err
    }
    defer resp.Body.Close()
    return nil
}
'''

        mock_response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Non-idempotent payment charge without idempotency key",
                    "category": "idempotency",
                    "risk": "critical",
                    "evidence_quote": "c.httpClient.Post(\"/api/charge\"",
                    "line_number": 3,
                    "consequences": "Duplicate charges may be processed if retry occurs",
                    "recommendation": "Add Idempotency-Key header for idempotent requests",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.API],
        )

        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL  # CRITICAL risk
        assert "idempotent" in findings[0].title.lower()

    @pytest.mark.asyncio
    async def test_failure_modes_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of missing failure handling."""
        artifact = '''
func (c *Client) SendMessage(topic string, msg []byte) error {
    client, err := c.getClient()
    if err != nil {
        return err
    }
    return client.Publish(topic, msg)
}
'''

        mock_response = json.dumps({
            "integration_issues": [
                {
                    "issue": "No timeout configured for message publishing",
                    "category": "failure_modes",
                    "risk": "high",
                    "evidence_quote": "return client.Publish(topic, msg)",
                    "line_number": 6,
                    "consequences": "Publish may block indefinitely if broker is slow",
                    "recommendation": "Add timeout context to publish call",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.MESSAGING],
        )

        assert len(findings) == 1
        assert "timeout" in findings[0].title.lower()
        assert findings[0].severity == Severity.ERROR
        assert findings[0].domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_retry_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of missing retry."""
        artifact = '''
func (c *Client) CallAPI(req *http.Request) (*http.Response, error) {
    resp, err := c.httpClient.Do(req)
    if err != nil {
        return nil, err
    }
    if resp.StatusCode >= 500 {
        return nil, fmt.Errorf("server error: %d", resp.StatusCode)
    }
    return resp, nil
}
'''

        mock_response = json.dumps({
            "integration_issues": [
                {
                    "issue": "No retry for transient 5xx errors",
                    "category": "retry",
                    "risk": "high",
                    "evidence_quote": "if resp.StatusCode >= 500 { return nil, fmt.Errorf",
                    "line_number": 6,
                    "consequences": "Temporary server errors cause immediate failure",
                    "recommendation": "Add retry with exponential backoff for 5xx errors",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.API],
        )

        assert len(findings) == 1
        assert "retry" in findings[0].title.lower()
        assert findings[0].severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_threshold_filtering(self, mock_provider: MagicMock) -> None:
        """Test that findings below threshold are filtered out."""
        mock_response = json.dumps({
            "integration_issues": [
                {
                    "issue": "Critical data loss",
                    "category": "failure_modes",
                    "risk": "critical",  # 0.95 confidence
                    "evidence_quote": "code1",
                    "consequences": "consequences1",
                    "recommendation": "recommendation1",
                },
                {
                    "issue": "High severity issue",
                    "category": "contract",
                    "risk": "high",  # 0.85 confidence
                    "evidence_quote": "code2",
                    "consequences": "consequences2",
                    "recommendation": "recommendation2",
                },
                {
                    "issue": "Medium severity issue",
                    "category": "versioning",
                    "risk": "medium",  # 0.65 confidence
                    "evidence_quote": "code3",
                    "consequences": "consequences3",
                    "recommendation": "recommendation3",
                },
                {
                    "issue": "Low severity issue",
                    "category": "retry",
                    "risk": "low",  # 0.45 confidence - below threshold
                    "evidence_quote": "code4",
                    "consequences": "consequences4",
                    "recommendation": "recommendation4",
                },
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = IntegrationAnalysisMethod(threshold=0.6)
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.API],
        )

        # Should include critical (0.95), high (0.85), medium (0.65), not low (0.45)
        titles = [f.title for f in findings]
        assert "Critical data loss" in titles
        assert "High severity issue" in titles
        assert "Medium severity issue" in titles
        assert "Low severity issue" not in titles

    @pytest.mark.asyncio
    async def test_graceful_llm_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of LLM failure."""
        mock_provider.invoke.side_effect = ProviderError("LLM API error")

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.API],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_provider_timeout(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of provider timeout."""
        mock_provider.invoke.side_effect = ProviderTimeoutError("Timeout")

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.API],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_parse_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of parse failure."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = "invalid json {{ not valid"

        method = IntegrationAnalysisMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.API],
        )

        assert findings == []


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_finding_id_format(self, method: IntegrationAnalysisMethod) -> None:
        """Test finding IDs use correct format (1-based indexing)."""
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        # _create_finding_from_issue uses index for ID
        finding1 = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )
        finding2 = method._create_finding_from_issue(
            issue_data, 1, [ArtifactDomain.API]
        )

        assert finding1.id == "#204-F1"
        assert finding2.id == "#204-F2"

    def test_evidence_without_line_number(self, method: IntegrationAnalysisMethod) -> None:
        """Test evidence creation when line number is None."""
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="some code",
            line_number=None,
            consequences="consequences",
            recommendation="recommendation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert finding.evidence[0].line_number is None

    def test_description_includes_all_parts(self, method: IntegrationAnalysisMethod) -> None:
        """Test description includes issue, consequences, and recommendation."""
        issue_data = IntegrationIssueData(
            issue="Test issue description",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="Bad things happen",
            recommendation="Fix it this way",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert "Test issue description" in finding.description
        assert "Bad things happen" in finding.description
        assert "Fix it this way" in finding.description

    def test_no_evidence_when_quote_empty(self, method: IntegrationAnalysisMethod) -> None:
        """Test no evidence created when evidence_quote is empty."""
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="   ",
            consequences="consequences",
            recommendation="recommendation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        # Empty/whitespace quote should not create evidence
        assert len(finding.evidence) == 0

    def test_unknown_category_no_pattern_id(self, method: IntegrationAnalysisMethod) -> None:
        """Test pattern_id is None for unknown category."""
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )
        # Manually change category after creation
        object.__setattr__(issue_data, 'category', 'unknown_category')

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API]
        )

        assert finding.pattern_id is None

    def test_first_detected_domain_fallback(self, method: IntegrationAnalysisMethod) -> None:
        """Test first detected domain is used when no specific mapping."""
        # Test with unknown category - should fallback to first detected domain
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, [ArtifactDomain.API, ArtifactDomain.MESSAGING]
        )

        # CONTRACT maps to API first
        assert finding.domain == ArtifactDomain.API

    def test_no_domain_returns_none(self, method: IntegrationAnalysisMethod) -> None:
        """Test None is returned when no domains detected."""
        issue_data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )

        finding = method._create_finding_from_issue(
            issue_data, 0, []
        )

        assert finding.domain is None


# =============================================================================
# Test Pydantic Models
# =============================================================================


class TestPydanticModels:
    """Tests for Pydantic validation models."""

    def test_integration_issue_data_valid(self) -> None:
        """Test valid IntegrationIssueData creation."""
        data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )
        assert data.issue == "Test issue"
        assert data.category == "contract"
        assert data.risk == "high"

    def test_integration_issue_data_category_validation(self) -> None:
        """Test category validation in IntegrationIssueData."""
        with pytest.raises(Exception):  # Pydantic validation error
            IntegrationIssueData(
                issue="Test issue",
                category="invalid",
                risk="high",
                evidence_quote="code",
                consequences="consequences",
                recommendation="recommendation",
            )

    def test_integration_issue_data_risk_validation(self) -> None:
        """Test risk validation in IntegrationIssueData."""
        with pytest.raises(Exception):  # Pydantic validation error
            IntegrationIssueData(
                issue="Test issue",
                category="contract",
                risk="extreme",
                evidence_quote="code",
                consequences="consequences",
                recommendation="recommendation",
            )

    def test_integration_analysis_response_default(self) -> None:
        """Test IntegrationAnalysisResponse with default empty list."""
        response = IntegrationAnalysisResponse()
        assert response.integration_issues == []

    def test_integration_analysis_response_with_data(self) -> None:
        """Test IntegrationAnalysisResponse with issue data."""
        data = IntegrationIssueData(
            issue="Test issue",
            category="contract",
            risk="high",
            evidence_quote="code",
            consequences="consequences",
            recommendation="recommendation",
        )
        response = IntegrationAnalysisResponse(integration_issues=[data])
        assert len(response.integration_issues) == 1
        assert response.integration_issues[0].issue == "Test issue"
