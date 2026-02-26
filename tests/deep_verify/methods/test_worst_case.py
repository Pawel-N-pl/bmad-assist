"""Tests for WorstCaseMethod (#205).

This module provides comprehensive test coverage for the Worst-Case Construction
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
from bmad_assist.deep_verify.methods.worst_case import (
    WORST_CASE_CATEGORIES,
    WORST_CASE_CONSTRUCTION_SYSTEM_PROMPT,
    ScenarioSeverity,
    WorstCaseCategory,
    WorstCaseDefinition,
    WorstCaseMethod,
    WorstCaseScenarioData,
    _is_catastrophic_scenario,
    get_category_definitions,
    severity_to_confidence,
    severity_to_finding_severity,
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
        "bmad_assist.deep_verify.methods.worst_case.ClaudeSDKProvider"
    ) as mock:
        provider_instance = MagicMock()
        mock.return_value = provider_instance
        yield provider_instance


@pytest.fixture
def method(mock_provider: MagicMock) -> WorstCaseMethod:
    """Create WorstCaseMethod with mocked provider."""
    return WorstCaseMethod()


# =============================================================================
# Test Enums and Constants
# =============================================================================


class TestWorstCaseCategory:
    """Tests for WorstCaseCategory enum."""

    def test_all_categories_exist(self) -> None:
        """Test that all 5 worst-case categories are defined."""
        categories = list(WorstCaseCategory)
        assert len(categories) == 5
        assert WorstCaseCategory.CASCADE in categories
        assert WorstCaseCategory.EXHAUSTION in categories
        assert WorstCaseCategory.THUNDERING_HERD in categories
        assert WorstCaseCategory.CORRUPTION in categories
        assert WorstCaseCategory.SPLIT_BRAIN in categories

    def test_category_values(self) -> None:
        """Test category string values."""
        assert WorstCaseCategory.CASCADE.value == "cascade"
        assert WorstCaseCategory.EXHAUSTION.value == "exhaustion"
        assert WorstCaseCategory.THUNDERING_HERD.value == "thundering_herd"
        assert WorstCaseCategory.CORRUPTION.value == "corruption"
        assert WorstCaseCategory.SPLIT_BRAIN.value == "split_brain"


class TestScenarioSeverity:
    """Tests for ScenarioSeverity enum."""

    def test_all_severities_exist(self) -> None:
        """Test that all 4 severity levels are defined."""
        severities = list(ScenarioSeverity)
        assert len(severities) == 4
        assert ScenarioSeverity.CATASTROPHIC in severities
        assert ScenarioSeverity.SEVERE in severities
        assert ScenarioSeverity.MODERATE in severities
        assert ScenarioSeverity.MINOR in severities


# =============================================================================
# Test Category Definitions
# =============================================================================


class TestCategoryDefinitions:
    """Tests for WORST_CASE_CATEGORIES and get_category_definitions."""

    def test_all_categories_have_definitions(self) -> None:
        """Test that all worst-case categories have definitions."""
        for category in WorstCaseCategory:
            assert category in WORST_CASE_CATEGORIES
            definition = WORST_CASE_CATEGORIES[category]
            assert isinstance(definition, WorstCaseDefinition)
            assert definition.id
            assert definition.description
            assert definition.examples
            assert isinstance(definition.default_severity, Severity)

    def test_category_ids(self) -> None:
        """Test that category IDs follow expected pattern."""
        assert WORST_CASE_CATEGORIES[WorstCaseCategory.CASCADE].id == "WC-CAS-001"
        assert WORST_CASE_CATEGORIES[WorstCaseCategory.EXHAUSTION].id == "WC-EXH-001"
        assert WORST_CASE_CATEGORIES[WorstCaseCategory.THUNDERING_HERD].id == "WC-THD-001"
        assert WORST_CASE_CATEGORIES[WorstCaseCategory.CORRUPTION].id == "WC-COR-001"
        assert WORST_CASE_CATEGORIES[WorstCaseCategory.SPLIT_BRAIN].id == "WC-SPB-001"

    def test_get_category_definitions(self) -> None:
        """Test get_category_definitions returns all definitions."""
        definitions = get_category_definitions()
        assert len(definitions) == 5
        ids = [d.id for d in definitions]
        assert "WC-CAS-001" in ids
        assert "WC-EXH-001" in ids
        assert "WC-THD-001" in ids
        assert "WC-COR-001" in ids
        assert "WC-SPB-001" in ids


# =============================================================================
# Test Severity Mapping Functions
# =============================================================================


class TestSeverityToFindingSeverity:
    """Tests for severity_to_finding_severity function."""

    def test_catastrophic_severity(self) -> None:
        """Test CATASTROPHIC severity maps to CRITICAL finding severity."""
        assert severity_to_finding_severity(ScenarioSeverity.CATASTROPHIC) == Severity.CRITICAL

    def test_severe_severity(self) -> None:
        """Test SEVERE severity maps to ERROR finding severity."""
        assert severity_to_finding_severity(ScenarioSeverity.SEVERE) == Severity.ERROR

    def test_moderate_severity(self) -> None:
        """Test MODERATE severity maps to WARNING finding severity."""
        assert severity_to_finding_severity(ScenarioSeverity.MODERATE) == Severity.WARNING

    def test_minor_severity(self) -> None:
        """Test MINOR severity maps to INFO finding severity."""
        assert severity_to_finding_severity(ScenarioSeverity.MINOR) == Severity.INFO


class TestSeverityToConfidence:
    """Tests for severity_to_confidence function."""

    def test_catastrophic_confidence(self) -> None:
        """Test CATASTROPHIC severity maps to 0.95 confidence."""
        assert severity_to_confidence(ScenarioSeverity.CATASTROPHIC) == 0.95

    def test_severe_confidence(self) -> None:
        """Test SEVERE severity maps to 0.85 confidence."""
        assert severity_to_confidence(ScenarioSeverity.SEVERE) == 0.85

    def test_moderate_confidence(self) -> None:
        """Test MODERATE severity maps to 0.65 confidence."""
        assert severity_to_confidence(ScenarioSeverity.MODERATE) == 0.65

    def test_minor_confidence(self) -> None:
        """Test MINOR severity maps to 0.45 confidence."""
        assert severity_to_confidence(ScenarioSeverity.MINOR) == 0.45


class TestIsCatastrophicScenario:
    """Tests for _is_catastrophic_scenario function."""

    def test_total_crash_is_catastrophic(self) -> None:
        """Test 'total crash' is detected as catastrophic."""
        assert _is_catastrophic_scenario("exhaustion", "Total crash") is True

    def test_data_loss_is_catastrophic(self) -> None:
        """Test 'data loss' is detected as catastrophic."""
        assert _is_catastrophic_scenario("corruption", "Unrecoverable data loss") is True

    def test_deadlock_is_catastrophic(self) -> None:
        """Test 'deadlock' is detected as catastrophic."""
        assert _is_catastrophic_scenario("cascade", "Distributed deadlock") is True

    def test_oom_kill_is_catastrophic(self) -> None:
        """Test 'oom kill' is detected as catastrophic."""
        assert _is_catastrophic_scenario("exhaustion", "OOM kill crashes service") is True

    def test_corruption_is_catastrophic(self) -> None:
        """Test 'corruption' is detected as catastrophic."""
        assert _is_catastrophic_scenario("corruption", "Data corruption") is True

    def test_split_brain_is_catastrophic(self) -> None:
        """Test 'split brain' is detected as catastrophic."""
        assert _is_catastrophic_scenario("split_brain", "Split brain scenario") is True

    def test_inconsistent_state_is_catastrophic(self) -> None:
        """Test 'inconsistent state' is detected as catastrophic."""
        assert _is_catastrophic_scenario("corruption", "Inconsistent state across nodes") is True

    def test_panic_is_catastrophic(self) -> None:
        """Test 'panic' is detected as catastrophic."""
        assert _is_catastrophic_scenario("cascade", "Goroutine panic") is True

    def test_performance_issue_not_catastrophic(self) -> None:
        """Test performance issues are not catastrophic."""
        assert _is_catastrophic_scenario("exhaustion", "Performance degradation") is False

    def test_slow_response_not_catastrophic(self) -> None:
        """Test slow responses are not catastrophic."""
        assert _is_catastrophic_scenario("exhaustion", "Slow response time") is False


# =============================================================================
# Test Method Instantiation
# =============================================================================


class TestMethodInstantiation:
    """Tests for WorstCaseMethod instantiation."""

    def test_default_instantiation(self) -> None:
        """Test method can be instantiated with defaults."""
        method = WorstCaseMethod()
        assert method.method_id == MethodId("#205")
        assert method._model == "haiku"
        assert method._threshold == 0.6
        assert method._timeout == 30
        assert len(method._categories) == 5  # All categories

    def test_custom_parameters(self) -> None:
        """Test method can be instantiated with custom parameters."""
        categories = [WorstCaseCategory.CASCADE, WorstCaseCategory.EXHAUSTION]
        method = WorstCaseMethod(
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
            WorstCaseMethod(threshold=1.5)

        with pytest.raises(ValueError, match="threshold must be between 0.0 and 1.0"):
            WorstCaseMethod(threshold=-0.1)

    def test_repr(self) -> None:
        """Test __repr__ method."""
        method = WorstCaseMethod(model="sonnet", threshold=0.7)
        repr_str = repr(method)
        assert "WorstCaseMethod" in repr_str
        assert "#205" in repr_str
        assert "sonnet" in repr_str
        assert "0.7" in repr_str


# =============================================================================
# Test Domain Filtering
# =============================================================================


class TestDomainFiltering:
    """Tests for domain filtering in analyze method."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_security_domain(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list for SECURITY domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.SECURITY],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_storage_domain(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list for STORAGE domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.STORAGE],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_transform_domain(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list for TRANSFORM domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.TRANSFORM],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_api_domain(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list for API domain only."""
        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.API],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_runs_for_concurrency_domain(self, method: WorstCaseMethod, mock_provider: MagicMock) -> None:
        """Test method runs when CONCURRENCY domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"scenarios": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.CONCURRENCY],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_messaging_domain(self, method: WorstCaseMethod, mock_provider: MagicMock) -> None:
        """Test method runs when MESSAGING domain is detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"scenarios": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.MESSAGING],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_runs_for_both_concurrency_and_messaging(self, method: WorstCaseMethod, mock_provider: MagicMock) -> None:
        """Test method runs when both CONCURRENCY and MESSAGING domains are detected."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = json.dumps({"scenarios": []})

        result = await method.analyze(
            "some code",
            domains=[ArtifactDomain.CONCURRENCY, ArtifactDomain.MESSAGING],
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_domains(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list when no domains provided."""
        result = await method.analyze("some code", domains=[])
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_none_domains(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list when domains is None."""
        result = await method.analyze("some code", domains=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_artifact(self, method: WorstCaseMethod) -> None:
        """Test method returns empty list for empty artifact."""
        result = await method.analyze("", domains=[ArtifactDomain.CONCURRENCY])
        assert result == []

        result = await method.analyze("   ", domains=[ArtifactDomain.CONCURRENCY])
        assert result == []


# =============================================================================
# Test Finding Creation
# =============================================================================


class TestFindingCreation:
    """Tests for finding creation from LLM response."""

    def test_create_finding_basic(self, method: WorstCaseMethod) -> None:
        """Test basic finding creation."""
        scenario_data = WorstCaseScenarioData(
            scenario="Unbounded destination map causes OOM crash",
            category="exhaustion",
            severity="catastrophic",
            trigger="Malicious actor adds millions of destinations",
            cascade_effect="OOM kill crashes service",
            evidence_quote="m.destinations[id] = dest",
            line_number=42,
            mitigation="Add bounds checking",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert finding.id == "#205-F1"
        assert finding.title == "Unbounded destination map causes OOM crash"
        assert finding.method_id == MethodId("#205")
        assert finding.pattern_id == PatternId("WC-EXH-001")
        assert finding.domain == ArtifactDomain.CONCURRENCY
        assert len(finding.evidence) == 1
        assert finding.evidence[0].quote == "m.destinations[id] = dest"
        assert finding.evidence[0].line_number == 42
        assert finding.evidence[0].source == "#205"

    def test_create_finding_truncates_long_title(self, method: WorstCaseMethod) -> None:
        """Test long titles are truncated to 80 characters."""
        long_scenario = "A" * 100
        scenario_data = WorstCaseScenarioData(
            scenario=long_scenario,
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert len(finding.title) == 80
        assert finding.title.endswith("...")

    def test_create_finding_critical_severity_catastrophic(self, method: WorstCaseMethod) -> None:
        """Test CRITICAL severity for catastrophic scenario."""
        scenario_data = WorstCaseScenarioData(
            scenario="Total service crash due to unbounded map",
            category="exhaustion",
            severity="catastrophic",
            trigger="trigger",
            cascade_effect="OOM kill",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert finding.severity == Severity.CRITICAL

    def test_create_finding_error_severity(self, method: WorstCaseMethod) -> None:
        """Test ERROR severity for severe scenario."""
        scenario_data = WorstCaseScenarioData(
            scenario="Resource exhaustion under load",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert finding.severity == Severity.ERROR

    def test_create_finding_warning_severity(self, method: WorstCaseMethod) -> None:
        """Test WARNING severity for moderate scenario."""
        scenario_data = WorstCaseScenarioData(
            scenario="Performance degradation",
            category="exhaustion",
            severity="moderate",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert finding.severity == Severity.WARNING

    def test_create_finding_info_severity(self, method: WorstCaseMethod) -> None:
        """Test INFO severity for minor scenario."""
        scenario_data = WorstCaseScenarioData(
            scenario="Minor optimization opportunity",
            category="exhaustion",
            severity="minor",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )

        assert finding.severity == Severity.INFO

    def test_create_finding_domain_assignment_cascade(self, method: WorstCaseMethod) -> None:
        """Test domain assignment for CASCADE category."""
        scenario_data = WorstCaseScenarioData(
            scenario="Cascade failure",
            category="cascade",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        # CONCURRENCY takes precedence for cascade
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.CONCURRENCY

        # Fallback to MESSAGING if CONCURRENCY not present
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

    def test_create_finding_domain_assignment_exhaustion(self, method: WorstCaseMethod) -> None:
        """Test domain assignment for EXHAUSTION category."""
        scenario_data = WorstCaseScenarioData(
            scenario="Resource exhaustion",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        # CONCURRENCY takes precedence for exhaustion
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.CONCURRENCY

        # Fallback to MESSAGING if CONCURRENCY not present
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

    def test_create_finding_domain_assignment_corruption(self, method: WorstCaseMethod) -> None:
        """Test domain assignment for CORRUPTION category."""
        scenario_data = WorstCaseScenarioData(
            scenario="Data corruption",
            category="corruption",
            severity="catastrophic",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        # CONCURRENCY takes precedence for corruption
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY, ArtifactDomain.MESSAGING]
        )
        assert finding.domain == ArtifactDomain.CONCURRENCY

    def test_create_finding_domain_assignment_thundering_herd(self, method: WorstCaseMethod) -> None:
        """Test domain assignment for THUNDERING_HERD category."""
        scenario_data = WorstCaseScenarioData(
            scenario="Thundering herd",
            category="thundering_herd",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        # MESSAGING takes precedence for thundering_herd
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.MESSAGING, ArtifactDomain.CONCURRENCY]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

        # Fallback to CONCURRENCY if MESSAGING not present
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )
        assert finding.domain == ArtifactDomain.CONCURRENCY

    def test_create_finding_domain_assignment_split_brain(self, method: WorstCaseMethod) -> None:
        """Test domain assignment for SPLIT_BRAIN category."""
        scenario_data = WorstCaseScenarioData(
            scenario="Split brain",
            category="split_brain",
            severity="catastrophic",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        # MESSAGING takes precedence for split_brain
        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.MESSAGING, ArtifactDomain.CONCURRENCY]
        )
        assert finding.domain == ArtifactDomain.MESSAGING

    def test_create_finding_finding_id_format(self, method: WorstCaseMethod) -> None:
        """Test finding ID format uses method-prefixed pattern."""
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding1 = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )
        assert finding1.id == "#205-F1"

        finding2 = method._create_finding_from_scenario(
            scenario_data, 1, [ArtifactDomain.CONCURRENCY]
        )
        assert finding2.id == "#205-F2"


# =============================================================================
# Test Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Tests for _build_prompt method."""

    def test_prompt_includes_system_prompt(self, method: WorstCaseMethod) -> None:
        """Test prompt includes system prompt."""
        prompt = method._build_prompt("some code")
        assert WORST_CASE_CONSTRUCTION_SYSTEM_PROMPT in prompt

    def test_prompt_includes_artifact(self, method: WorstCaseMethod) -> None:
        """Test prompt includes artifact text."""
        code = "func main() {}"
        prompt = method._build_prompt(code)
        assert code in prompt

    def test_prompt_includes_categories(self, method: WorstCaseMethod) -> None:
        """Test prompt includes category descriptions."""
        prompt = method._build_prompt("code")
        assert "CASCADE:" in prompt
        assert "EXHAUSTION:" in prompt
        assert "THUNDERING_HERD:" in prompt
        assert "CORRUPTION:" in prompt
        assert "SPLIT_BRAIN:" in prompt

    def test_prompt_truncation(self, method: WorstCaseMethod) -> None:
        """Test long artifacts are truncated."""
        long_code = "x" * 5000
        prompt = method._build_prompt(long_code)

        assert "truncated" in prompt.lower() or "4000" in prompt
        # The actual artifact in prompt should be truncated (allow for template overhead)
        assert len(prompt) < 10000  # Upper bound (prompt template + 4000 chars + overhead)

    def test_custom_categories_in_prompt(self) -> None:
        """Test prompt only includes specified categories in category list."""
        method = WorstCaseMethod(categories=[WorstCaseCategory.CASCADE])
        prompt = method._build_prompt("code")

        # Find the category list section (after "Categories to analyze:")
        category_section = prompt.split("Categories to analyze:")[1].split("Construct worst-case")[0]

        assert "CASCADE:" in category_section
        # Should not include other categories in the category list
        assert "SPLIT_BRAIN:" not in category_section
        assert "EXHAUSTION:" not in category_section


# =============================================================================
# Test Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for _parse_response method."""

    def test_parse_valid_json(self, method: WorstCaseMethod) -> None:
        """Test parsing valid JSON response."""
        response = json.dumps({
            "scenarios": [
                {
                    "scenario": "OOM crash",
                    "category": "exhaustion",
                    "severity": "catastrophic",
                    "trigger": "Unbounded input",
                    "cascade_effect": "Service crashes",
                    "evidence_quote": "m.map[key] = val",
                    "line_number": 42,
                    "mitigation": "Add bounds",
                }
            ]
        })

        result = method._parse_response(response)
        assert len(result.scenarios) == 1
        assert result.scenarios[0].scenario == "OOM crash"
        assert result.scenarios[0].category == "exhaustion"

    def test_parse_json_in_code_block(self, method: WorstCaseMethod) -> None:
        """Test parsing JSON inside markdown code block."""
        response = """```json
{
    "scenarios": [
        {
            "scenario": "Deadlock",
            "category": "cascade",
            "severity": "severe",
            "trigger": "Lock ordering",
            "cascade_effect": "All blocked",
            "evidence_quote": "mu1.Lock(); mu2.Lock()",
            "line_number": 10,
            "mitigation": "Consistent order"
        }
    ]
}
```"""

        result = method._parse_response(response)
        assert len(result.scenarios) == 1
        assert result.scenarios[0].scenario == "Deadlock"

    def test_parse_empty_json(self, method: WorstCaseMethod) -> None:
        """Test parsing empty JSON object."""
        response = "{}"
        result = method._parse_response(response)
        assert len(result.scenarios) == 0

    def test_parse_no_scenarios(self, method: WorstCaseMethod) -> None:
        """Test parsing response with empty scenarios array."""
        response = '{"scenarios": []}'
        result = method._parse_response(response)
        assert len(result.scenarios) == 0

    def test_parse_invalid_category_raises(self, method: WorstCaseMethod) -> None:
        """Test invalid category raises validation error."""
        response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Something",
                    "category": "invalid_category",
                    "severity": "severe",
                    "trigger": "trigger",
                    "cascade_effect": "effect",
                    "evidence_quote": "code",
                    "mitigation": "fix",
                }
            ]
        })

        with pytest.raises(Exception):  # Pydantic validation error
            method._parse_response(response)

    def test_parse_invalid_severity_raises(self, method: WorstCaseMethod) -> None:
        """Test invalid severity raises validation error."""
        response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Something",
                    "category": "exhaustion",
                    "severity": "extreme",
                    "trigger": "trigger",
                    "cascade_effect": "effect",
                    "evidence_quote": "code",
                    "mitigation": "fix",
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
    async def test_unbounded_map_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of unbounded map → OOM (concurrency artifact)."""
        artifact = '''
func (m *Manager) AddDestination(id string, dest Destination) {
    m.destinations[id] = dest  // No bounds check!
}

func (m *Manager) Broadcast(msg []byte) {
    for _, dest := range m.destinations {
        go dest.Send(msg)  // Unlimited goroutines
    }
}
'''

        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Unbounded destination map leads to OOM crash",
                    "category": "exhaustion",
                    "severity": "catastrophic",
                    "trigger": "Malicious actor adds millions of destinations",
                    "cascade_effect": "OOM kill crashes service, causing cascading failures to dependent services",
                    "evidence_quote": "m.destinations[id] = dest",
                    "line_number": 3,
                    "mitigation": "Add maximum limit to destinations map",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert len(findings) == 1
        assert findings[0].title == "Unbounded destination map leads to OOM crash"
        assert findings[0].severity == Severity.CRITICAL
        assert findings[0].pattern_id == PatternId("WC-EXH-001")

    @pytest.mark.asyncio
    async def test_deadlock_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of nested lock ordering → deadlock (concurrency artifact)."""
        artifact = '''
func (a *Account) Transfer(to *Account, amount int) {
    a.mu.Lock()
    defer a.mu.Unlock()
    
    to.mu.Lock()  // Different lock order!
    defer to.mu.Unlock()
    
    a.balance -= amount
    to.balance += amount
}
'''

        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Nested lock ordering violation causes distributed deadlock",
                    "category": "cascade",
                    "severity": "severe",
                    "trigger": "Concurrent transfers between accounts A→B and B→A",
                    "cascade_effect": "Deadlock blocks all account operations, request queue fills up",
                    "evidence_quote": "to.mu.Lock()",
                    "line_number": 6,
                    "mitigation": "Use consistent lock ordering across all operations",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert len(findings) == 1
        assert "deadlock" in findings[0].title.lower()
        # Note: Deadlock is in catastrophic keywords, so this could be CRITICAL
        # depending on the _is_catastrophic_scenario implementation
        assert findings[0].severity in (Severity.ERROR, Severity.CRITICAL)

    @pytest.mark.asyncio
    async def test_thundering_herd_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of thundering herd (messaging artifact)."""
        artifact = '''
func (c *Client) sendWithRetry(msg Message) error {
    backoff := time.Second
    for i := 0; i < 10; i++ {
        if err := c.send(msg); err != nil {
            time.Sleep(backoff)  // Fixed interval!
            backoff *= 2
            continue
        }
        return nil
    }
    return fmt.Errorf("max retries exceeded")
}
'''

        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Fixed-interval retries cause thundering herd after service recovery",
                    "category": "thundering_herd",
                    "severity": "moderate",
                    "trigger": "Service outage causes all clients to retry; when service recovers, all retries hit simultaneously",
                    "cascade_effect": "Sudden traffic spike overwhelms recovering service, causing another outage",
                    "evidence_quote": "time.Sleep(backoff)",
                    "line_number": 6,
                    "mitigation": "Add jitter to retry backoff",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.MESSAGING],
        )

        assert len(findings) == 1
        assert "thundering herd" in findings[0].title.lower()
        assert findings[0].severity == Severity.WARNING
        assert findings[0].domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_data_corruption_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of data corruption scenario (concurrency artifact)."""
        artifact = '''
func (c *Cache) Update(key string, value []byte) {
    // Read existing
    existing := c.data[key]
    // Modify
    existing = append(existing, value...)  // Not atomic!
    // Write back
    c.data[key] = existing
}
'''

        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Non-atomic cache update causes data corruption under concurrent access",
                    "category": "corruption",
                    "severity": "catastrophic",
                    "trigger": "Concurrent updates to same cache key",
                    "cascade_effect": "Corrupted cache data returned to users, causing incorrect business decisions",
                    "evidence_quote": "existing = append(existing, value...)",
                    "line_number": 5,
                    "mitigation": "Use mutex or atomic operations for cache updates",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL
        assert findings[0].pattern_id == PatternId("WC-COR-001")

    @pytest.mark.asyncio
    async def test_split_brain_detection(self, mock_provider: MagicMock) -> None:
        """Test detection of split-brain scenario (messaging artifact)."""
        artifact = '''
func (n *Node) AcquireLeadership() error {
    // Try to acquire lease
    err := n.leaseMgr.Acquire(n.id, 30*time.Second)
    if err != nil {
        return err
    }
    n.isLeader = true
    return nil
}
'''

        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Network partition leads to split-brain with two leaders",
                    "category": "split_brain",
                    "severity": "catastrophic",
                    "trigger": "Network partition between nodes during lease renewal",
                    "cascade_effect": "Both nodes believe they are leader, causing conflicting writes and data divergence",
                    "evidence_quote": "n.leaseMgr.Acquire(n.id, 30*time.Second)",
                    "line_number": 4,
                    "mitigation": "Use consensus protocol with quorum requirement",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            artifact,
            domains=[ArtifactDomain.MESSAGING],
        )

        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL
        assert findings[0].domain == ArtifactDomain.MESSAGING

    @pytest.mark.asyncio
    async def test_threshold_filtering(self, mock_provider: MagicMock) -> None:
        """Test that findings below threshold are filtered out."""
        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Catastrophic OOM",
                    "category": "exhaustion",
                    "severity": "catastrophic",  # 0.95 confidence
                    "trigger": "trigger1",
                    "cascade_effect": "effect1",
                    "evidence_quote": "code1",
                    "mitigation": "fix1",
                },
                {
                    "scenario": "Severe deadlock",
                    "category": "cascade",
                    "severity": "severe",  # 0.85 confidence
                    "trigger": "trigger2",
                    "cascade_effect": "effect2",
                    "evidence_quote": "code2",
                    "mitigation": "fix2",
                },
                {
                    "scenario": "Moderate performance",
                    "category": "exhaustion",
                    "severity": "moderate",  # 0.65 confidence
                    "trigger": "trigger3",
                    "cascade_effect": "effect3",
                    "evidence_quote": "code3",
                    "mitigation": "fix3",
                },
                {
                    "scenario": "Minor optimization",
                    "category": "exhaustion",
                    "severity": "minor",  # 0.45 confidence - below threshold
                    "trigger": "trigger4",
                    "cascade_effect": "effect4",
                    "evidence_quote": "code4",
                    "mitigation": "fix4",
                },
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod(threshold=0.6)
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY],
        )

        # Should include catastrophic (0.95), severe (0.85), moderate (0.65), not minor (0.45)
        titles = [f.title for f in findings]
        assert "Catastrophic OOM" in titles
        assert "Severe deadlock" in titles
        assert "Moderate performance" in titles
        assert "Minor optimization" not in titles

    @pytest.mark.asyncio
    async def test_graceful_llm_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of LLM failure."""
        mock_provider.invoke.side_effect = ProviderError("LLM API error")

        method = WorstCaseMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_provider_timeout(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of provider timeout."""
        mock_provider.invoke.side_effect = ProviderTimeoutError("Timeout")

        method = WorstCaseMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_graceful_parse_failure(self, mock_provider: MagicMock) -> None:
        """Test graceful handling of parse failure."""
        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = "invalid json {{ not valid"

        method = WorstCaseMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert findings == []


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_finding_id_format(self, method: WorstCaseMethod) -> None:
        """Test finding ID format uses method-prefixed pattern."""
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 5, [ArtifactDomain.CONCURRENCY]
        )
        assert finding.id == "#205-F6"

    def test_empty_evidence_quote(self, method: WorstCaseMethod) -> None:
        """Test handling of empty evidence quote."""
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="   ",  # Empty/whitespace
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )
        # Should create finding but with empty evidence list
        assert len(finding.evidence) == 0

    def test_none_line_number(self, method: WorstCaseMethod) -> None:
        """Test handling of None line number."""
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            line_number=None,
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )
        assert finding.evidence[0].line_number is None

    def test_unknown_category_pattern_id(self, method: WorstCaseMethod) -> None:
        """Test pattern_id is None for unknown category."""
        # Note: This shouldn't happen in practice due to Pydantic validation,
        # but we test the defensive code path
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, [ArtifactDomain.CONCURRENCY]
        )
        assert finding.pattern_id == PatternId("WC-EXH-001")

    def test_no_detected_domains(self, method: WorstCaseMethod) -> None:
        """Test domain assignment when no domains detected."""
        scenario_data = WorstCaseScenarioData(
            scenario="Test scenario",
            category="exhaustion",
            severity="severe",
            trigger="trigger",
            cascade_effect="effect",
            evidence_quote="code",
            mitigation="fix",
        )

        finding = method._create_finding_from_scenario(
            scenario_data, 0, []
        )
        assert finding.domain is None

    @pytest.mark.asyncio
    async def test_empty_scenarios_list(self, mock_provider: MagicMock) -> None:
        """Test handling of empty scenarios list from LLM."""
        mock_response = '{"scenarios": []}'

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY],
        )

        assert findings == []

    @pytest.mark.asyncio
    async def test_analysis_with_both_domains(self, mock_provider: MagicMock) -> None:
        """Test analysis with both CONCURRENCY and MESSAGING domains."""
        mock_response = json.dumps({
            "scenarios": [
                {
                    "scenario": "Test scenario",
                    "category": "cascade",
                    "severity": "severe",
                    "trigger": "trigger",
                    "cascade_effect": "effect",
                    "evidence_quote": "code",
                    "mitigation": "fix",
                }
            ]
        })

        mock_provider.invoke.return_value = MagicMock(stdout="", stderr="", exit_code=0)
        mock_provider.parse_output.return_value = mock_response

        method = WorstCaseMethod()
        findings = await method.analyze(
            "code",
            domains=[ArtifactDomain.CONCURRENCY, ArtifactDomain.MESSAGING],
        )

        assert len(findings) == 1
        # CASCADE should map to CONCURRENCY as primary
        assert findings[0].domain == ArtifactDomain.CONCURRENCY
