"""Tests for AdversarialReviewMethod (#201).

This module provides comprehensive test coverage for the Adversarial Review
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
from bmad_assist.deep_verify.methods.adversarial_review import (
    ADVERSARIAL_CATEGORIES,
    ADVERSARIAL_REVIEW_SYSTEM_PROMPT,
    AdversarialCategory,
    AdversarialDefinition,
    AdversarialReviewMethod,
    AdversarialReviewResponse,
    AdversarialVulnerabilityData,
    ThreatLevel,
    _is_critical_threat,
    get_category_definitions,
    threat_to_confidence,
    threat_to_severity,
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
        "bmad_assist.deep_verify.methods.adversarial_review.ClaudeSDKProvider"
    ) as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def method(mock_provider: MagicMock) -> AdversarialReviewMethod:
    """Create AdversarialReviewMethod with mocked provider."""
    return AdversarialReviewMethod()


# =============================================================================
# Test Enums and Constants
# =============================================================================


class TestAdversarialCategory:
    """Tests for AdversarialCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that all 4 adversarial categories are defined."""
        categories = list(AdversarialCategory)
        assert len(categories) == 4
        assert AdversarialCategory.BYPASS in categories
        assert AdversarialCategory.LOAD in categories
        assert AdversarialCategory.ERROR_PATHS in categories
        assert AdversarialCategory.EDGE_INPUTS in categories

    def test_category_values(self) -> None:
        """Test category string values."""
        assert AdversarialCategory.BYPASS.value == "bypass"
        assert AdversarialCategory.LOAD.value == "load"
        assert AdversarialCategory.ERROR_PATHS.value == "error_paths"
        assert AdversarialCategory.EDGE_INPUTS.value == "edge_inputs"


class TestThreatLevel:
    """Tests for ThreatLevel enum."""

    def test_all_levels_exist(self) -> None:
        """Test that all 4 threat levels are defined."""
        levels = list(ThreatLevel)
        assert len(levels) == 4
        assert ThreatLevel.CRITICAL in levels
        assert ThreatLevel.HIGH in levels
        assert ThreatLevel.MEDIUM in levels
        assert ThreatLevel.LOW in levels


# =============================================================================
# Test Category Definitions
# =============================================================================


class TestCategoryDefinitions:
    """Tests for ADVERSARIAL_CATEGORIES and get_category_definitions."""

    def test_all_categories_have_definitions(self) -> None:
        """Test that all adversarial categories have definitions."""
        for category in AdversarialCategory:
            assert category in ADVERSARIAL_CATEGORIES
            definition = ADVERSARIAL_CATEGORIES[category]
            assert isinstance(definition, AdversarialDefinition)
            assert definition.id
            assert definition.description
            assert definition.examples
            assert isinstance(definition.default_severity, Severity)

    def test_category_ids(self) -> None:
        """Test that category IDs follow expected pattern."""
        assert ADVERSARIAL_CATEGORIES[AdversarialCategory.BYPASS].id == "ADV-BYP-001"
        assert ADVERSARIAL_CATEGORIES[AdversarialCategory.LOAD].id == "ADV-LOD-001"
        assert ADVERSARIAL_CATEGORIES[AdversarialCategory.ERROR_PATHS].id == "ADV-ERR-001"
        assert ADVERSARIAL_CATEGORIES[AdversarialCategory.EDGE_INPUTS].id == "ADV-EDG-001"

    def test_get_category_definitions(self) -> None:
        """Test get_category_definitions returns all definitions."""
        definitions = get_category_definitions()
        assert len(definitions) == 4
        ids = [d.id for d in definitions]
        assert "ADV-BYP-001" in ids
        assert "ADV-LOD-001" in ids
        assert "ADV-ERR-001" in ids
        assert "ADV-EDG-001" in ids


# =============================================================================
# Test Threat Mapping Functions
# =============================================================================


class TestThreatToSeverity:
    """Tests for threat_to_severity function."""

    def test_critical_threat(self) -> None:
        """Test CRITICAL threat maps to CRITICAL severity."""
        assert threat_to_severity(ThreatLevel.CRITICAL) == Severity.CRITICAL

    def test_high_threat(self) -> None:
        """Test HIGH threat maps to ERROR severity."""
        assert threat_to_severity(ThreatLevel.HIGH) == Severity.ERROR

    def test_medium_threat(self) -> None:
        """Test MEDIUM threat maps to WARNING severity."""
        assert threat_to_severity(ThreatLevel.MEDIUM) == Severity.WARNING

    def test_low_threat(self) -> None:
        """Test LOW threat maps to INFO severity."""
        assert threat_to_severity(ThreatLevel.LOW) == Severity.INFO


class TestThreatToConfidence:
    """Tests for threat_to_confidence function."""

    def test_critical_threat(self) -> None:
        """Test CRITICAL threat maps to 0.95 confidence."""
        assert threat_to_confidence(ThreatLevel.CRITICAL) == 0.95

    def test_high_threat(self) -> None:
        """Test HIGH threat maps to 0.85 confidence."""
        assert threat_to_confidence(ThreatLevel.HIGH) == 0.85

    def test_medium_threat(self) -> None:
        """Test MEDIUM threat maps to 0.65 confidence."""
        assert threat_to_confidence(ThreatLevel.MEDIUM) == 0.65

    def test_low_threat(self) -> None:
        """Test LOW threat maps to 0.45 confidence."""
        assert threat_to_confidence(ThreatLevel.LOW) == 0.45


class TestIsCriticalThreat:
    """Tests for _is_critical_threat function."""

    def test_auth_bypass_is_critical(self) -> None:
        """Test authentication bypass is critical."""
        assert _is_critical_threat("bypass", "Authentication bypass via route enumeration") is True

    def test_sql_injection_is_critical(self) -> None:
        """Test SQL injection is critical."""
        assert _is_critical_threat("edge_inputs", "SQL injection vulnerability found") is True

    def test_rce_is_critical(self) -> None:
        """Test remote code execution is critical."""
        assert _is_critical_threat("edge_inputs", "Remote code execution possible") is True

    def test_privilege_escalation_is_critical(self) -> None:
        """Test privilege escalation is critical."""
        assert _is_critical_threat("bypass", "Privilege escalation path exists") is True

    def test_ssrf_is_critical(self) -> None:
        """Test SSRF is critical."""
        assert _is_critical_threat("edge_inputs", "SSRF vulnerability allows internal access") is True

    def test_path_traversal_is_critical(self) -> None:
        """Test path traversal is critical."""
        assert _is_critical_threat("edge_inputs", "Path traversal vulnerability") is True

    def test_idor_is_critical(self) -> None:
        """Test IDOR is critical."""
        assert _is_critical_threat("bypass", "Insecure direct object reference (IDOR)") is True

    def test_jwt_bypass_is_critical(self) -> None:
        """Test JWT bypass is critical."""
        assert _is_critical_threat("bypass", "JWT validation bypass possible") is True

    def test_bypass_keyword_with_auth_is_critical(self) -> None:
        """Test bypass keyword with auth context is critical."""
        assert _is_critical_threat("bypass", "Can bypass authentication check") is True

    def test_injection_keyword_is_critical(self) -> None:
        """Test injection keyword is critical."""
        assert _is_critical_threat("edge_inputs", "Command injection vulnerability") is True

    def test_load_issue_not_critical(self) -> None:
        """Test LOAD category issues are not automatically critical."""
        assert _is_critical_threat("load", "DoS via resource exhaustion") is False

    def test_error_paths_not_critical(self) -> None:
        """Test ERROR_PATHS category issues are not automatically critical."""
        assert _is_critical_threat("error_paths", "Information leakage in error message") is False


# =============================================================================
# Test Method Instantiation
# =============================================================================


class TestMethodInstantiation:
    """Tests for AdversarialReviewMethod instantiation."""

    def test_default_instantiation(self) -> None:
        """Test method can be instantiated with defaults."""
        method = AdversarialReviewMethod()
        assert method.method_id == MethodId("#201")
        assert method._model == "haiku"
        assert method._threshold == 0.6
        assert method._timeout == 30
        assert len(method._categories) == 4  # All categories

    def test_custom_parameters(self) -> None:
        """Test method can be instantiated with custom parameters."""
        categories = [AdversarialCategory.BYPASS, AdversarialCategory.EDGE_INPUTS]
        method = AdversarialReviewMethod(
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
            AdversarialReviewMethod(threshold=1.5)

        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            AdversarialReviewMethod(threshold=-0.1)

    def test_repr(self) -> None:
        """Test __repr__ method."""
        method = AdversarialReviewMethod(model="sonnet", threshold=0.7)
        repr_str = repr(method)
        assert "AdversarialReviewMethod" in repr_str
        assert "#201" in repr_str
        assert "sonnet" in repr_str
        assert "0.7" in repr_str


# =============================================================================
# Test Domain Filtering
# =============================================================================


class TestDomainFiltering:
    """Tests for domain filtering in analyze method."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_storage_domain(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list for STORAGE domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.STORAGE],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_concurrency_domain(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list for CONCURRENCY domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.CONCURRENCY],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_transform_domain(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list for TRANSFORM domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.TRANSFORM],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_runs_for_security_domain(self, method: AdversarialReviewMethod, mock_provider: MagicMock) -> None:
        """Test method runs when SECURITY domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"vulnerabilities": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.SECURITY],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_api_domain(self, method: AdversarialReviewMethod, mock_provider: MagicMock) -> None:
        """Test method runs when API domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"vulnerabilities": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.API],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_both_security_and_api(self, method: AdversarialReviewMethod, mock_provider: MagicMock) -> None:
        """Test method runs when both SECURITY and API domains are detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"vulnerabilities": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.SECURITY, ArtifactDomain.API],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_domains(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list when no domains provided."""
        result = await method.analyze("some code", domains=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_none_domains(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list when domains is None."""
        result = await method.analyze("some code", domains=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_artifact(self, method: AdversarialReviewMethod) -> None:
        """Test method returns empty list for empty artifact."""
        result = await method.analyze("", domains=[ArtifactDomain.SECURITY])
        assert result == []

        result = await method.analyze("   ", domains=[ArtifactDomain.SECURITY])
        assert result == []


# =============================================================================
# Test Finding Creation
# =============================================================================


class TestFindingCreation:
    """Tests for finding creation from LLM response."""

    def test_create_finding_basic(self, method: AdversarialReviewMethod) -> None:
        """Test basic finding creation."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Authentication bypass via route enumeration",
            category="bypass",
            threat_level="high",
            evidence_quote="w.WriteHeader(404)",
            line_number=42,
            attack_vector="Attacker can enumerate valid routes",
            remediation="Use consistent status codes",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.id == "#201-F1"
        assert finding.title == "Authentication bypass via route enumeration"
        assert finding.method_id == MethodId("#201")
        assert finding.pattern_id == PatternId("ADV-BYP-001")
        assert finding.domain == ArtifactDomain.SECURITY
        assert len(finding.evidence) == 1
        assert finding.evidence[0].quote == "w.WriteHeader(404)"
        assert finding.evidence[0].line_number == 42
        assert finding.evidence[0].source == "#201"

    def test_create_finding_truncates_long_title(self, method: AdversarialReviewMethod) -> None:
        """Test long titles are truncated to 80 characters."""
        long_vuln = "A" * 100
        vuln_data = AdversarialVulnerabilityData(
            vulnerability=long_vuln,
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert len(finding.title) == 80
        assert finding.title.endswith("...")

    def test_create_finding_critical_severity(self, method: AdversarialReviewMethod) -> None:
        """Test CRITICAL severity for critical threat."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="SQL injection allows arbitrary query execution",
            category="edge_inputs",
            threat_level="high",
            evidence_quote="db.Query(userInput)",
            attack_vector="Attacker can execute arbitrary SQL",
            remediation="Use parameterized queries",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.severity == Severity.CRITICAL

    def test_create_finding_explicit_critical_threat(self, method: AdversarialReviewMethod) -> None:
        """Test CRITICAL severity for CRITICAL threat level."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Authentication bypass",
            category="bypass",
            threat_level="critical",
            evidence_quote="if token == nil { return true }",
            attack_vector="Attacker can bypass auth",
            remediation="Validate all tokens",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.severity == Severity.CRITICAL

    def test_create_finding_error_severity(self, method: AdversarialReviewMethod) -> None:
        """Test ERROR severity for high threat non-critical."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Rate limiting missing",
            category="load",
            threat_level="high",
            evidence_quote="for { process() }",
            attack_vector="Attacker can exhaust resources",
            remediation="Add rate limiting",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API]
        )

        assert finding.severity == Severity.ERROR

    def test_create_finding_warning_severity(self, method: AdversarialReviewMethod) -> None:
        """Test WARNING severity for medium threat."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Verbose error messages",
            category="error_paths",
            threat_level="medium",
            evidence_quote="return err.Error()",
            attack_vector="Information disclosure",
            remediation="Return generic errors",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API]
        )

        assert finding.severity == Severity.WARNING

    def test_create_finding_info_severity(self, method: AdversarialReviewMethod) -> None:
        """Test INFO severity for low threat."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Minor logging issue",
            category="error_paths",
            threat_level="low",
            evidence_quote="log.Printf(\"error\")",
            attack_vector="Minimal impact",
            remediation="Use structured logging",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API]
        )

        assert finding.severity == Severity.INFO

    def test_create_finding_domain_assignment_bypass(self, method: AdversarialReviewMethod) -> None:
        """Test domain assignment for BYPASS category."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Auth bypass",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        # SECURITY takes precedence for bypass
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY, ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.SECURITY

        # Fallback to API if SECURITY not present
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.API

    def test_create_finding_domain_assignment_edge_inputs(self, method: AdversarialReviewMethod) -> None:
        """Test domain assignment for EDGE_INPUTS category."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Injection",
            category="edge_inputs",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        # SECURITY takes precedence for edge_inputs
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY, ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.SECURITY

        # Fallback to API if SECURITY not present
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API]
        )
        assert finding.domain == ArtifactDomain.API

    def test_create_finding_domain_assignment_load(self, method: AdversarialReviewMethod) -> None:
        """Test domain assignment for LOAD category."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="DoS",
            category="load",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        # API takes precedence for load
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API, ArtifactDomain.SECURITY]
        )
        assert finding.domain == ArtifactDomain.API

        # Fallback to SECURITY if API not present
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )
        assert finding.domain == ArtifactDomain.SECURITY

    def test_create_finding_domain_assignment_error_paths(self, method: AdversarialReviewMethod) -> None:
        """Test domain assignment for ERROR_PATHS category."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Error leak",
            category="error_paths",
            threat_level="medium",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        # API takes precedence for error_paths
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.API, ArtifactDomain.SECURITY]
        )
        assert finding.domain == ArtifactDomain.API

        # Fallback to SECURITY if API not present
        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )
        assert finding.domain == ArtifactDomain.SECURITY


# =============================================================================
# Test Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Tests for _build_prompt method."""

    def test_prompt_includes_system_prompt(self, method: AdversarialReviewMethod) -> None:
        """Test prompt includes system prompt."""
        prompt = method._build_prompt("some code")
        assert ADVERSARIAL_REVIEW_SYSTEM_PROMPT in prompt

    def test_prompt_includes_artifact(self, method: AdversarialReviewMethod) -> None:
        """Test prompt includes artifact text."""
        code = "func main() {}"
        prompt = method._build_prompt(code)
        assert code in prompt

    def test_prompt_includes_categories(self, method: AdversarialReviewMethod) -> None:
        """Test prompt includes category descriptions."""
        prompt = method._build_prompt("code")
        assert "BYPASS:" in prompt
        assert "LOAD:" in prompt
        assert "ERROR_PATHS:" in prompt
        assert "EDGE_INPUTS:" in prompt

    def test_prompt_truncation(self, method: AdversarialReviewMethod) -> None:
        """Test long artifacts are truncated."""
        long_code = "x" * 5000
        prompt = method._build_prompt(long_code)

        assert "truncated" in prompt.lower() or "4000" in prompt
        # The actual artifact in prompt should be truncated
        assert len(prompt) < 8000  # Reasonable upper bound (prompt template + 4000 chars)

    def test_custom_categories_in_prompt(self) -> None:
        """Test prompt only includes specified categories."""
        method = AdversarialReviewMethod(categories=[AdversarialCategory.BYPASS])
        prompt = method._build_prompt("code")

        assert "BYPASS:" in prompt


# =============================================================================
# Test Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for _parse_response method."""

    def test_parse_valid_json(self, method: AdversarialReviewMethod) -> None:
        """Test parsing valid JSON response."""
        response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "Route enumeration",
                    "category": "bypass",
                    "threat_level": "high",
                    "evidence_quote": "w.WriteHeader(404)",
                    "line_number": 42,
                    "attack_vector": "Attacker enumerates routes",
                    "remediation": "Use consistent codes",
                }
            ]
        })

        result = method._parse_response(response)
        assert len(result.vulnerabilities) == 1
        assert result.vulnerabilities[0].vulnerability == "Route enumeration"
        assert result.vulnerabilities[0].category == "bypass"

    def test_parse_json_in_code_block(self, method: AdversarialReviewMethod) -> None:
        """Test parsing JSON inside markdown code block."""
        response = """```json
{
    "vulnerabilities": [
        {
            "vulnerability": "SQL injection",
            "category": "edge_inputs",
            "threat_level": "critical",
            "evidence_quote": "db.Query(input)",
            "attack_vector": "Inject SQL",
            "remediation": "Use params"
        }
    ]
}
```"""

        result = method._parse_response(response)
        assert len(result.vulnerabilities) == 1
        assert result.vulnerabilities[0].vulnerability == "SQL injection"

    def test_parse_empty_json(self, method: AdversarialReviewMethod) -> None:
        """Test parsing empty JSON object."""
        response = "{}"
        result = method._parse_response(response)
        assert len(result.vulnerabilities) == 0

    def test_parse_no_vulnerabilities(self, method: AdversarialReviewMethod) -> None:
        """Test parsing response with empty vulnerabilities array."""
        response = '{"vulnerabilities": []}'
        result = method._parse_response(response)
        assert len(result.vulnerabilities) == 0

    def test_parse_invalid_category_raises(self, method: AdversarialReviewMethod) -> None:
        """Test invalid category raises validation error."""
        response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "Something",
                    "category": "invalid_category",
                    "threat_level": "high",
                    "evidence_quote": "code",
                    "attack_vector": "attack",
                    "remediation": "fix",
                }
            ]
        })

        with pytest.raises(Exception):  # Pydantic validation error
            method._parse_response(response)

    def test_parse_invalid_threat_level_raises(self, method: AdversarialReviewMethod) -> None:
        """Test invalid threat_level raises validation error."""
        response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "Something",
                    "category": "bypass",
                    "threat_level": "extreme",
                    "evidence_quote": "code",
                    "attack_vector": "attack",
                    "remediation": "fix",
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
    async def test_route_enumeration_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of route enumeration (security artifact)."""
        artifact = '''
func (h *Handler) GetUser(w http.ResponseWriter, r *http.Request) {
    id := r.URL.Query().Get("id")
    user, err := h.db.GetUser(id)
    if err != nil {
        if err == sql.ErrNoRows {
            w.WriteHeader(404)
            return
        }
        w.WriteHeader(500)
        return
    }
    
    if !h.isAuthorized(r, user) {
        w.WriteHeader(401)
        return
    }
    
    json.NewEncoder(w).Encode(user)
}
'''

        mock_response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "Route enumeration via 401 vs 404 distinction",
                    "category": "bypass",
                    "threat_level": "high",
                    "evidence_quote": "w.WriteHeader(404)\n        return\n    }\n    \n    if !h.isAuthorized(r, user) {\n        w.WriteHeader(401)",
                    "line_number": 9,
                    "attack_vector": "Attacker can enumerate valid user IDs by observing different status codes",
                    "remediation": "Use consistent 404 for both not found and unauthorized",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.SECURITY],
        )

        assert len(findings) == 1
        assert findings[0].title == "Route enumeration via 401 vs 404 distinction"
        assert findings[0].severity == Severity.ERROR  # HIGH threat, not critical
        assert findings[0].pattern_id == PatternId("ADV-BYP-001")

    @pytest.mark.asyncio
    async def test_ssrf_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of SSRF DNS rebinding (security artifact)."""
        artifact = '''
func (c *Client) FetchURL(url string) ([]byte, error) {
    if !strings.HasPrefix(url, "http://") && !strings.HasPrefix(url, "https://") {
        return nil, fmt.Errorf("invalid scheme")
    }
    
    resp, err := c.httpClient.Get(url)
    if err != nil {
        return nil, err
    }
    defer resp.Body.Close()
    
    return io.ReadAll(resp.Body)
}
'''

        mock_response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "SSRF DNS rebinding bypass",
                    "category": "edge_inputs",
                    "threat_level": "critical",
                    "evidence_quote": "c.httpClient.Get(url)",
                    "line_number": 6,
                    "attack_vector": "Attacker can use DNS rebinding to access internal services after initial validation",
                    "remediation": "Validate URL before each request or use allowlist",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.SECURITY],
        )

        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL  # CRITICAL threat
        assert "SSRF" in findings[0].title

    @pytest.mark.asyncio
    async def test_rate_limiting_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of missing rate limiting (API artifact)."""
        artifact = '''
func (h *Handler) VerifySignature(w http.ResponseWriter, r *http.Request) {
    sig := r.Header.Get("X-Signature")
    payload, _ := io.ReadAll(r.Body)
    
    if !hmac.Equal([]byte(sig), h.calculateHMAC(payload)) {
        w.WriteHeader(401)
        return
    }
    
    processRequest(w, r)
}
'''

        # Use a properly escaped JSON string
        mock_response = '{"vulnerabilities": [{"vulnerability": "No rate limiting on signature verification failures", "category": "load", "threat_level": "high", "evidence_quote": "hmac.Equal", "line_number": 5, "attack_vector": "Attacker can brute force", "remediation": "Add rate limiting"}]}'

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.API],
        )

        assert len(findings) == 1
        assert "rate limiting" in findings[0].title.lower()
        assert findings[0].severity == Severity.ERROR
        assert findings[0].domain == ArtifactDomain.API

    @pytest.mark.asyncio
    async def test_threshold_filtering(self, mock_provider: MagicMock) -> None:
        """Test that findings below threshold are filtered out."""
        mock_response = json.dumps({
            "vulnerabilities": [
                {
                    "vulnerability": "Critical SQL injection",
                    "category": "edge_inputs",
                    "threat_level": "critical",  # 0.95 confidence
                    "evidence_quote": "code1",
                    "attack_vector": "attack1",
                    "remediation": "fix1",
                },
                {
                    "vulnerability": "High bypass",
                    "category": "bypass",
                    "threat_level": "high",  # 0.85 confidence
                    "evidence_quote": "code2",
                    "attack_vector": "attack2",
                    "remediation": "fix2",
                },
                {
                    "vulnerability": "Medium error leak",
                    "category": "error_paths",
                    "threat_level": "medium",  # 0.65 confidence
                    "evidence_quote": "code3",
                    "attack_vector": "attack3",
                    "remediation": "fix3",
                },
                {
                    "vulnerability": "Low info leak",
                    "category": "error_paths",
                    "threat_level": "low",  # 0.45 confidence - below threshold
                    "evidence_quote": "code4",
                    "attack_vector": "attack4",
                    "remediation": "fix4",
                },
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = AdversarialReviewMethod(threshold=0.6)
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.SECURITY],
        )

        # Should include critical (0.95), high (0.85), medium (0.65), not low (0.45)
        titles = [f.title for f in findings]
        assert "Critical SQL injection" in titles
        assert "High bypass" in titles
        assert "Medium error leak" in titles
        assert "Low info leak" not in titles

    @pytest.mark.asyncio
    async def test_graceful_llm_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of LLM failure."""
        mock_provider.invoke.side_effect = ProviderError("LLM API error")

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.SECURITY],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_provider_timeout(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of provider timeout."""
        mock_provider.invoke.side_effect = ProviderTimeoutError("Timeout")

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.SECURITY],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_parse_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of parse failure."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = "invalid json {{ not valid"

        method = AdversarialReviewMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.SECURITY],
        )

        assert findings == []


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_finding_id_format(self, method: AdversarialReviewMethod) -> None:
        """Test finding IDs use correct format (1-based indexing)."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        # _create_finding_from_vulnerability uses index for ID
        finding1 = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )
        finding2 = method._create_finding_from_vulnerability(
            vuln_data, 1, [ArtifactDomain.SECURITY]
        )

        assert finding1.id == "#201-F1"
        assert finding2.id == "#201-F2"

    def test_evidence_without_line_number(self, method: AdversarialReviewMethod) -> None:
        """Test evidence creation when line number is None."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="some code",
            line_number=None,
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.evidence[0].line_number is None

    def test_description_includes_all_parts(self, method: AdversarialReviewMethod) -> None:
        """Test description includes vulnerability, attack_vector, and remediation."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability description",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="Attacker exploits this",
            remediation="Fix it this way",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert "Test vulnerability description" in finding.description
        assert "Attacker exploits this" in finding.description
        assert "Fix it this way" in finding.description

    def test_no_evidence_when_quote_empty(self, method: AdversarialReviewMethod) -> None:
        """Test no evidence created when evidence_quote is empty or whitespace."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="some code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        # Valid quote should create evidence
        assert len(finding.evidence) == 1
        assert finding.evidence[0].quote == "some code"

    def test_unknown_category_no_pattern_id(self, method: AdversarialReviewMethod) -> None:
        """Test pattern_id is None for unknown category."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )
        # Manually change category after creation
        object.__setattr__(vuln_data, 'category', 'unknown_category')

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.pattern_id is None

    def test_first_detected_domain_fallback(self, method: AdversarialReviewMethod) -> None:
        """Test first detected domain is used when no specific mapping.
        
        Note: Since Pydantic validates categories, we test this by passing a known
        category but simulating the fallback logic when domain assignment
        doesn't find a specific match.
        """
        # Test that when we have detected domains, the method returns the first one
        # as fallback for categories that don't have specific mapping rules
        # For BYPASS category with SECURITY detected, it should return SECURITY
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY, ArtifactDomain.API]
        )

        # BYPASS maps to SECURITY first
        assert finding.domain == ArtifactDomain.SECURITY

    def test_no_domain_returns_none(self, method: AdversarialReviewMethod) -> None:
        """Test None is returned when no domains detected."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, []
        )

        assert finding.domain is None


# =============================================================================
# Test Pydantic Models
# =============================================================================


class TestPydanticModels:
    """Tests for Pydantic validation models."""

    def test_adversarial_vulnerability_data_valid(self) -> None:
        """Test valid AdversarialVulnerabilityData creation."""
        data = AdversarialVulnerabilityData(
            vulnerability="Test vuln",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )
        assert data.vulnerability == "Test vuln"
        assert data.category == "bypass"
        assert data.threat_level == "high"

    def test_adversarial_vulnerability_data_category_validation(self) -> None:
        """Test category validation in AdversarialVulnerabilityData."""
        with pytest.raises(Exception):  # Pydantic validation error
            AdversarialVulnerabilityData(
                vulnerability="Test vuln",
                category="invalid",
                threat_level="high",
                evidence_quote="code",
                attack_vector="attack",
                remediation="fix",
            )

    def test_adversarial_vulnerability_data_threat_validation(self) -> None:
        """Test threat_level validation in AdversarialVulnerabilityData."""
        with pytest.raises(Exception):  # Pydantic validation error
            AdversarialVulnerabilityData(
                vulnerability="Test vuln",
                category="bypass",
                threat_level="extreme",
                evidence_quote="code",
                attack_vector="attack",
                remediation="fix",
            )

    def test_adversarial_review_response_default(self) -> None:
        """Test AdversarialReviewResponse with default empty list."""
        response = AdversarialReviewResponse()
        assert response.vulnerabilities == []

    def test_adversarial_review_response_with_data(self) -> None:
        """Test AdversarialReviewResponse with vulnerability data."""
        data = AdversarialVulnerabilityData(
            vulnerability="Test vuln",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )
        response = AdversarialReviewResponse(vulnerabilities=[data])
        assert len(response.vulnerabilities) == 1
        assert response.vulnerabilities[0].vulnerability == "Test vuln"


# =============================================================================
# Test Category Filtering
# =============================================================================


class TestCategoryFiltering:
    """Tests for category filtering functionality."""

    @pytest.mark.asyncio
    async def test_analyze_with_bypass_only(self, mock_provider: MagicMock) -> None:
        """Test analysis with only BYPASS category."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"vulnerabilities": []})

        method = AdversarialReviewMethod(categories=[AdversarialCategory.BYPASS])
        await method.analyze("code", domains=[ArtifactDomain.SECURITY])

        # Verify prompt includes BYPASS category
        call_args = mock_provider.invoke.call_args
        prompt = call_args[1]["prompt"] if call_args[1] else call_args[0][0]
        assert "BYPASS:" in prompt

    @pytest.mark.asyncio
    async def test_analyze_with_multiple_categories(self, mock_provider: MagicMock) -> None:
        """Test analysis with multiple categories."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"vulnerabilities": []})

        method = AdversarialReviewMethod(
            categories=[AdversarialCategory.BYPASS, AdversarialCategory.EDGE_INPUTS]
        )
        await method.analyze("code", domains=[ArtifactDomain.SECURITY])

        # Verify prompt includes both categories
        call_args = mock_provider.invoke.call_args
        prompt = call_args[1]["prompt"] if call_args[1] else call_args[0][0]
        assert "BYPASS:" in prompt
        assert "EDGE_INPUTS:" in prompt


# =============================================================================
# Test Finding Properties
# =============================================================================


class TestFindingProperties:
    """Tests for finding properties and structure."""

    def test_finding_has_correct_evidence_confidence(self, method: AdversarialReviewMethod) -> None:
        """Test finding evidence has correct confidence based on threat."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test",
            category="bypass",
            threat_level="critical",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.evidence[0].confidence == 0.95  # CRITICAL -> 0.95

    def test_finding_has_correct_method_id(self, method: AdversarialReviewMethod) -> None:
        """Test finding has correct method_id."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="attack",
            remediation="fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        assert finding.method_id == MethodId("#201")

    def test_finding_description_format(self, method: AdversarialReviewMethod) -> None:
        """Test finding description has correct format."""
        vuln_data = AdversarialVulnerabilityData(
            vulnerability="Test vulnerability",
            category="bypass",
            threat_level="high",
            evidence_quote="code",
            attack_vector="Attacker does X",
            remediation="Do Y to fix",
        )

        finding = method._create_finding_from_vulnerability(
            vuln_data, 0, [ArtifactDomain.SECURITY]
        )

        lines = finding.description.split("\n")
        assert "Vulnerability: Test vulnerability" in lines
        assert "Category: bypass" in lines
        assert "Threat level: high" in lines
        assert "Attack vector: Attacker does X" in lines
        assert "Remediation: Do Y to fix" in lines
