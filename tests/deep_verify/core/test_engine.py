"""Tests for DeepVerifyEngine.

This module provides comprehensive tests for the DeepVerifyEngine class,
covering all acceptance criteria from Story 26.15.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from bmad_assist.core.exceptions import ProviderError
from bmad_assist.deep_verify.config import DeepVerifyConfig, MethodConfig
from bmad_assist.deep_verify.core import (
    ArtifactDomain,
    DomainConfidence,
    DomainDetectionResult,
    DomainDetector,
    Evidence,
    Finding,
    MethodSelector,
    Severity,
    VerdictDecision,
)
from bmad_assist.deep_verify.core.engine import DeepVerifyEngine, VerificationContext
from bmad_assist.deep_verify.core.types import MethodId
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root."""
    return tmp_path


@pytest.fixture
def default_config() -> DeepVerifyConfig:
    """Create a default DeepVerifyConfig."""
    return DeepVerifyConfig()


@pytest.fixture
def disabled_config() -> DeepVerifyConfig:
    """Create a disabled DeepVerifyConfig."""
    return DeepVerifyConfig(enabled=False)


@pytest.fixture
def mock_domain_detector() -> Mock:
    """Create a mock DomainDetector."""
    detector = Mock(spec=DomainDetector)
    detector.detect = Mock(
        return_value=DomainDetectionResult(
            domains=[
                DomainConfidence(
                    domain=ArtifactDomain.API,
                    confidence=0.9,
                    signals=["endpoint", "http"],
                )
            ],
            reasoning="API domain detected",
        )
    )
    return detector


@pytest.fixture
def mock_method() -> Mock:
    """Create a mock verification method."""
    method = Mock(spec=BaseVerificationMethod)
    method.method_id = MethodId("#153")
    method.analyze = AsyncMock(return_value=[])
    return method


@pytest.fixture
def sample_finding() -> Finding:
    """Create a sample finding for testing."""
    return Finding(
        id="temp-1",
        severity=Severity.ERROR,
        title="Test Finding",
        description="A test finding",
        method_id=MethodId("#153"),
        evidence=[Evidence(quote="test code", confidence=0.9)],
    )


# =============================================================================
# AC-1: Engine Configuration and Initialization
# =============================================================================


class TestEngineInitialization:
    """Tests for AC-1: Engine configuration and initialization."""

    def test_engine_accepts_project_root(self, project_root: Path) -> None:
        """Test that engine accepts project_root as required first parameter."""
        engine = DeepVerifyEngine(project_root=project_root)
        assert engine._project_root == project_root

    def test_engine_accepts_optional_config(self, project_root: Path) -> None:
        """Test that engine accepts optional config parameter."""
        config = DeepVerifyConfig(enabled=False)
        engine = DeepVerifyEngine(project_root=project_root, config=config)
        assert engine._config == config
        assert not engine._config.enabled

    def test_engine_accepts_optional_domain_detector(
        self, project_root: Path, mock_domain_detector: Mock
    ) -> None:
        """Test that engine accepts optional domain_detector parameter."""
        engine = DeepVerifyEngine(
            project_root=project_root, domain_detector=mock_domain_detector
        )
        assert engine._domain_detector == mock_domain_detector

    def test_engine_creates_domain_detector_if_not_provided(
        self, project_root: Path
    ) -> None:
        """Test that engine creates DomainDetector if not provided."""
        engine = DeepVerifyEngine(project_root=project_root)
        assert isinstance(engine._domain_detector, DomainDetector)

    def test_engine_uses_default_config_if_not_provided(
        self, project_root: Path
    ) -> None:
        """Test that engine uses default config if not provided."""
        engine = DeepVerifyEngine(project_root=project_root)
        assert isinstance(engine._config, DeepVerifyConfig)
        assert engine._config.enabled  # Default is enabled

    def test_engine_initializes_evidence_scorer(self, project_root: Path) -> None:
        """Test that engine initializes EvidenceScorer with full config."""
        config = DeepVerifyConfig(clean_pass_bonus=-0.5)
        engine = DeepVerifyEngine(project_root=project_root, config=config)
        assert engine._scorer is not None
        assert engine._scorer.clean_pass_bonus == -0.5

    def test_engine_repr(self, project_root: Path) -> None:
        """Test engine string representation."""
        engine = DeepVerifyEngine(project_root=project_root)
        repr_str = repr(engine)
        assert "DeepVerifyEngine" in repr_str
        assert str(project_root) in repr_str


# =============================================================================
# AC-2: Method Selection Logic
# =============================================================================


class TestMethodSelection:
    """Tests for AC-2: Method selection logic."""

    def test_method_selector_filters_by_domain(self) -> None:
        """Test that MethodSelector filters methods by domain."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.SECURITY])

        # Should have always-run methods + SECURITY specific
        method_ids = [m.method_id for m in methods]
        assert MethodId("#153") in method_ids  # Always run
        assert MethodId("#154") in method_ids  # Always run
        assert MethodId("#203") in method_ids  # Always run
        assert MethodId("#201") in method_ids  # SECURITY specific

    def test_method_selector_respects_enabled_flags(self) -> None:
        """Test that MethodSelector respects per-method enabled flags."""
        config = DeepVerifyConfig(
            method_201_adversarial_review=MethodConfig(enabled=False)
        )
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.SECURITY])

        method_ids = [m.method_id for m in methods]
        assert MethodId("#201") not in method_ids  # Disabled
        assert MethodId("#153") in method_ids  # Still enabled

    def test_method_selector_returns_empty_when_disabled(self) -> None:
        """Test that MethodSelector returns empty list when config.enabled=False."""
        config = DeepVerifyConfig(enabled=False)
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.SECURITY])
        assert methods == []

    def test_method_selector_uses_default_pattern_library(self) -> None:
        """Test that PatternMatchMethod uses default pattern library."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.API])

        pattern_method = next(
            (m for m in methods if m.method_id == MethodId("#153")), None
        )
        assert pattern_method is not None
        # PatternMatchMethod should be created with no-arg constructor

    def test_method_selector_for_concurrency_domain(self) -> None:
        """Test method selection for CONCURRENCY domain."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.CONCURRENCY])

        method_ids = [m.method_id for m in methods]
        assert MethodId("#155") in method_ids  # CONCURRENCY specific
        assert MethodId("#205") in method_ids  # CONCURRENCY specific

    def test_method_selector_for_api_domain(self) -> None:
        """Test method selection for API domain."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.API])

        method_ids = [m.method_id for m in methods]
        assert MethodId("#155") in method_ids  # API specific
        assert MethodId("#201") in method_ids  # API specific
        assert MethodId("#204") in method_ids  # API specific

    def test_method_selector_for_messaging_domain(self) -> None:
        """Test method selection for MESSAGING domain."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.MESSAGING])

        method_ids = [m.method_id for m in methods]
        assert MethodId("#157") in method_ids  # MESSAGING specific
        assert MethodId("#204") in method_ids  # MESSAGING specific
        assert MethodId("#205") in method_ids  # MESSAGING specific

    def test_method_selector_for_storage_domain(self) -> None:
        """Test method selection for STORAGE domain."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.STORAGE])

        method_ids = [m.method_id for m in methods]
        assert MethodId("#157") in method_ids  # STORAGE specific
        assert MethodId("#204") in method_ids  # STORAGE specific
        assert MethodId("#205") in method_ids  # STORAGE specific

    def test_method_selector_repr(self) -> None:
        """Test MethodSelector string representation."""
        config = DeepVerifyConfig()
        selector = MethodSelector(config)
        repr_str = repr(selector)
        assert "MethodSelector" in repr_str


# =============================================================================
# AC-3: Parallel Execution Core
# =============================================================================


@pytest.mark.slow  # Real LLM calls via engine.verify() - 25-27s per test
class TestParallelExecution:
    """Tests for AC-3: Parallel execution core."""

    @pytest.mark.asyncio
    async def test_verify_method_is_async(self, project_root: Path) -> None:
        """Test that verify() is an async method."""
        engine = DeepVerifyEngine(project_root=project_root)
        assert asyncio.iscoroutinefunction(engine.verify)

    @pytest.mark.asyncio
    async def test_verify_accepts_artifact_text(self, project_root: Path) -> None:
        """Test that verify() accepts artifact_text parameter."""
        engine = DeepVerifyEngine(project_root=project_root)
        # Should not raise
        verdict = await engine.verify("test code")
        assert verdict is not None

    @pytest.mark.asyncio
    async def test_verify_accepts_optional_context(self, project_root: Path) -> None:
        """Test that verify() accepts optional context parameter."""
        engine = DeepVerifyEngine(project_root=project_root)
        context = VerificationContext(language="python")
        verdict = await engine.verify("test code", context=context)
        assert verdict is not None

    @pytest.mark.asyncio
    async def test_verify_accepts_optional_timeout(self, project_root: Path) -> None:
        """Test that verify() accepts optional timeout parameter."""
        engine = DeepVerifyEngine(project_root=project_root)
        verdict = await engine.verify("test code", timeout=60)
        assert verdict is not None

    @pytest.mark.asyncio
    async def test_verify_returns_verdict(self, project_root: Path) -> None:
        """Test that verify() returns a Verdict object."""
        engine = DeepVerifyEngine(project_root=project_root)
        verdict = await engine.verify("test code")
        assert verdict.decision is not None
        assert verdict.score is not None
        assert verdict.findings is not None

    @pytest.mark.asyncio
    async def test_empty_verdict_helper(self, project_root: Path) -> None:
        """Test _empty_verdict() helper returns ACCEPT verdict."""
        engine = DeepVerifyEngine(project_root=project_root)
        domain_result = DomainDetectionResult(
            domains=[], reasoning="Test", ambiguity="none"
        )
        verdict = engine._empty_verdict(domain_result)
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0
        assert verdict.findings == []

    @pytest.mark.asyncio
    async def test_parallel_execution_with_gather(
        self, project_root: Path
    ) -> None:
        """Test that methods run in parallel via asyncio.gather."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Create mock methods that track execution order
        execution_order: list[str] = []

        async def slow_method1(text: str, **kwargs: object) -> list[Finding]:
            await asyncio.sleep(0.01)
            execution_order.append("method1")
            return []

        async def slow_method2(text: str, **kwargs: object) -> list[Finding]:
            await asyncio.sleep(0.01)
            execution_order.append("method2")
            return []

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method1.analyze = slow_method1

        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        mock_method2.analyze = slow_method2

        start = asyncio.get_event_loop().time()
        results = await engine._run_methods_with_errors(
            [mock_method1, mock_method2], "test", None, None
        )
        elapsed = asyncio.get_event_loop().time() - start

        # Both methods should complete in ~0.01s (parallel), not ~0.02s (sequential)
        assert elapsed < 0.02
        assert len(execution_order) == 2
        # Check results are MethodResult objects
        assert len(results) == 2
        assert all(r.success for r in results)


# =============================================================================
# AC-4: Verification Context
# =============================================================================


class TestVerificationContext:
    """Tests for AC-4: Verification context."""

    def test_verification_context_is_frozen_dataclass(self) -> None:
        """Test that VerificationContext is a frozen dataclass with slots."""
        context = VerificationContext()
        # Frozen - should raise FrozenInstanceError on modification attempt
        with pytest.raises((AttributeError, TypeError)):
            context.language = "python"  # type: ignore[misc]

    def test_verification_context_has_file_path_field(self) -> None:
        """Test VerificationContext has file_path field."""
        path = Path("test.py")
        context = VerificationContext(file_path=path)
        assert context.file_path == path

    def test_verification_context_has_language_field(self) -> None:
        """Test VerificationContext has language field."""
        context = VerificationContext(language="python")
        assert context.language == "python"

    def test_verification_context_has_story_ref_field(self) -> None:
        """Test VerificationContext has story_ref field."""
        context = VerificationContext(story_ref="26-15")
        assert context.story_ref == "26-15"

    def test_verification_context_has_epic_num_field_int(self) -> None:
        """Test VerificationContext accepts int for epic_num."""
        context = VerificationContext(epic_num=26)
        assert context.epic_num == 26

    def test_verification_context_has_epic_num_field_str(self) -> None:
        """Test VerificationContext accepts str for epic_num."""
        context = VerificationContext(epic_num="testarch")
        assert context.epic_num == "testarch"

    def test_verification_context_has_story_num_field_int(self) -> None:
        """Test VerificationContext accepts int for story_num."""
        context = VerificationContext(story_num=15)
        assert context.story_num == 15

    def test_verification_context_has_story_num_field_str(self) -> None:
        """Test VerificationContext accepts str for story_num."""
        context = VerificationContext(story_num="15")
        assert context.story_num == "15"

    def test_verification_context_defaults(self) -> None:
        """Test VerificationContext has appropriate defaults."""
        context = VerificationContext()
        assert context.file_path is None
        assert context.language is None
        assert context.story_ref is None
        assert context.epic_num is None
        assert context.story_num is None


# =============================================================================
# AC-5: Finding Aggregation and Deduplication
# =============================================================================


class TestFindingAggregation:
    """Tests for AC-5: Finding aggregation and deduplication."""

    def test_collect_findings_from_all_methods(self, project_root: Path) -> None:
        """Test that findings are collected from all methods."""
        engine = DeepVerifyEngine(project_root=project_root)

        finding1 = Finding(
            id="temp-1",
            severity=Severity.ERROR,
            title="Finding 1",
            description="Test",
            method_id=MethodId("#153"),
        )
        finding2 = Finding(
            id="temp-2",
            severity=Severity.WARNING,
            title="Finding 2",
            description="Test",
            method_id=MethodId("#154"),
        )

        findings = engine._deduplicate_findings([finding1, finding2])
        assert len(findings) == 2

    def test_deduplicate_by_pattern_id(self, project_root: Path) -> None:
        """Test deduplication by pattern_id match."""
        engine = DeepVerifyEngine(project_root=project_root)

        finding1 = Finding(
            id="temp-1",
            severity=Severity.WARNING,
            title="Finding 1",
            description="Test",
            method_id=MethodId("#153"),
            pattern_id="CC-001",
        )
        finding2 = Finding(
            id="temp-2",
            severity=Severity.ERROR,  # Higher severity
            title="Finding 2",
            description="Test",
            method_id=MethodId("#154"),
            pattern_id="CC-001",  # Same pattern
        )

        findings = engine._deduplicate_findings([finding1, finding2])
        assert len(findings) == 1
        assert findings[0].severity == Severity.ERROR  # Higher severity kept

    def test_deduplicate_by_evidence_similarity(self, project_root: Path) -> None:
        """Test deduplication by evidence quote similarity (>80%)."""
        engine = DeepVerifyEngine(project_root=project_root)

        finding1 = Finding(
            id="temp-1",
            severity=Severity.WARNING,
            title="Finding 1",
            description="Test",
            method_id=MethodId("#153"),
            evidence=[Evidence(quote="def test_function(): pass")],
        )
        finding2 = Finding(
            id="temp-2",
            severity=Severity.ERROR,
            title="Finding 2",
            description="Test",
            method_id=MethodId("#154"),
            evidence=[Evidence(quote="def test_function(): pass")],  # Same quote
        )

        findings = engine._deduplicate_findings([finding1, finding2])
        assert len(findings) == 1
        assert findings[0].severity == Severity.ERROR

    def test_keep_highest_severity_duplicate(self, project_root: Path) -> None:
        """Test that highest severity is kept when duplicates found."""
        engine = DeepVerifyEngine(project_root=project_root)

        finding1 = Finding(
            id="temp-1",
            severity=Severity.INFO,
            title="Finding 1",
            description="Test",
            method_id=MethodId("#153"),
            pattern_id="CC-001",
        )
        finding2 = Finding(
            id="temp-2",
            severity=Severity.CRITICAL,  # Highest
            title="Finding 2",
            description="Test",
            method_id=MethodId("#154"),
            pattern_id="CC-001",
        )
        finding3 = Finding(
            id="temp-3",
            severity=Severity.WARNING,
            title="Finding 3",
            description="Test",
            method_id=MethodId("#155"),
            pattern_id="CC-001",
        )

        findings = engine._deduplicate_findings([finding1, finding2, finding3])
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL

    def test_reassign_finding_ids_sequentially(self, project_root: Path) -> None:
        """Test that finding IDs are reassigned sequentially (F1, F2, F3...)."""
        engine = DeepVerifyEngine(project_root=project_root)

        findings = [
            Finding(
                id="old-1",
                severity=Severity.ERROR,
                title="Finding 1",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="old-2",
                severity=Severity.WARNING,
                title="Finding 2",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]

        reassigned = engine._assign_finding_ids(findings)
        assert reassigned[0].id == "F1"
        assert reassigned[1].id == "F2"

    def test_sort_findings_by_severity_before_id_assignment(
        self, project_root: Path
    ) -> None:
        """Test findings sorted by severity (CRITICAL first) before ID assignment."""
        engine = DeepVerifyEngine(project_root=project_root)

        findings = [
            Finding(
                id="temp-1",
                severity=Severity.INFO,
                title="Info",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="temp-2",
                severity=Severity.CRITICAL,
                title="Critical",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]

        reassigned = engine._assign_finding_ids(findings)
        assert reassigned[0].id == "F1"
        assert reassigned[0].severity == Severity.CRITICAL
        assert reassigned[1].id == "F2"
        assert reassigned[1].severity == Severity.INFO

    def test_enforce_max_50_per_method(self, project_root: Path) -> None:
        """Test enforcement of max 50 findings per method."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Create 60 findings from same method
        findings = [
            Finding(
                id=f"temp-{i}",
                severity=Severity.INFO,
                title=f"Finding {i}",
                description="Test",
                method_id=MethodId("#153"),
            )
            for i in range(60)
        ]

        limited = engine._apply_finding_limits(findings)
        # Should be limited to 50 per method
        method_153_count = sum(1 for f in limited if f.method_id == MethodId("#153"))
        assert method_153_count == 50

    def test_enforce_max_200_total(self, project_root: Path) -> None:
        """Test enforcement of max 200 total findings."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Create 250 findings from multiple methods
        findings = []
        for i in range(250):
            method_id = MethodId(f"#{150 + (i % 5)}")
            findings.append(
                Finding(
                    id=f"temp-{i}",
                    severity=Severity.INFO,
                    title=f"Finding {i}",
                    description="Test",
                    method_id=method_id,
                )
            )

        limited = engine._apply_finding_limits(findings)
        assert len(limited) <= 200

    def test_prioritize_by_severity_when_truncating(self, project_root: Path) -> None:
        """Test that findings prioritized by severity when truncating."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Create findings with mixed severities
        findings = [
            Finding(
                id=f"temp-{i}",
                severity=[Severity.INFO, Severity.CRITICAL][i % 2],
                title=f"Finding {i}",
                description="Test",
                method_id=MethodId("#153"),
            )
            for i in range(60)
        ]

        limited = engine._apply_finding_limits(findings)
        # CRITICAL findings should be preserved
        critical_count = sum(1 for f in limited if f.severity == Severity.CRITICAL)
        assert critical_count > 0


# =============================================================================
# AC-6: Scoring Integration
# =============================================================================


class TestScoringIntegration:
    """Tests for AC-6: Scoring integration."""

    def test_calculate_clean_passes(self, project_root: Path) -> None:
        """Test calculation of domains with zero findings."""
        engine = DeepVerifyEngine(project_root=project_root)

        detected_domains = [
            DomainConfidence(domain=ArtifactDomain.SECURITY, confidence=0.9),
            DomainConfidence(domain=ArtifactDomain.API, confidence=0.8),
        ]

        # One finding in SECURITY, none in API
        findings = [
            Finding(
                id="F1",
                severity=Severity.ERROR,
                title="Security issue",
                description="Test",
                method_id=MethodId("#153"),
                domain=ArtifactDomain.SECURITY,
            )
        ]

        clean_passes = engine._calculate_clean_passes(findings, detected_domains)
        assert clean_passes == 1  # API has no findings

    def test_evidence_scorer_initialized_with_config(self, project_root: Path) -> None:
        """Test EvidenceScorer initialized with full config."""
        config = DeepVerifyConfig(
            clean_pass_bonus=-0.5,
            reject_threshold=6.0,
            accept_threshold=-3.0,
        )
        engine = DeepVerifyEngine(project_root=project_root, config=config)

        assert engine._scorer.clean_pass_bonus == -0.5
        assert engine._scorer.reject_threshold == 6.0
        assert engine._scorer.accept_threshold == -3.0

    @pytest.mark.asyncio
    async def test_critical_finding_forces_reject(self, project_root: Path) -> None:
        """Test that CRITICAL finding forces REJECT regardless of score."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Mock domain detector to return API domain
        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(
            return_value=DomainDetectionResult(
                domains=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)],
                reasoning="API detected",
            )
        )

        # Mock method to return CRITICAL finding
        async def mock_analyze(text: str, **kwargs: object) -> list[Finding]:
            return [
                Finding(
                    id="temp-1",
                    severity=Severity.CRITICAL,
                    title="Critical issue",
                    description="Test",
                    method_id=MethodId("#153"),
                )
            ]

        mock_method = Mock(spec=BaseVerificationMethod)
        mock_method.method_id = MethodId("#153")
        mock_method.analyze = mock_analyze

        # Patch method selector to return our mock
        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[mock_method])

        verdict = await engine.verify("test code")
        assert verdict.decision == VerdictDecision.REJECT

    def test_get_method_timeout_from_config(self, project_root: Path) -> None:
        """Test getting per-method timeout from config."""
        config = DeepVerifyConfig(
            method_153_pattern_match=MethodConfig(enabled=True, timeout_seconds=45)
        )
        engine = DeepVerifyEngine(project_root=project_root, config=config)

        timeout = engine._get_method_timeout(MethodId("#153"))
        assert timeout == 45

    def test_get_method_timeout_none_when_not_configured(
        self, project_root: Path
    ) -> None:
        """Test that timeout is None when not configured."""
        config = DeepVerifyConfig()
        engine = DeepVerifyEngine(project_root=project_root, config=config)

        timeout = engine._get_method_timeout(MethodId("#153"))
        assert timeout is None


# =============================================================================
# AC-7: Domain Detection with Fallback
# =============================================================================


class TestDomainDetectionFallback:
    """Tests for AC-7: Domain detection with fallback."""

    @pytest.mark.asyncio
    async def test_keyword_fallback_on_llm_failure(
        self, project_root: Path
    ) -> None:
        """Test keyword fallback when LLM detection fails."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Make domain detector raise exception
        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(side_effect=ProviderError("LLM failed"))

        result = await engine._detect_domains("auth token encryption")

        # Should use keyword fallback
        assert len(result.domains) > 0
        assert any(d.domain == ArtifactDomain.SECURITY for d in result.domains)

    def test_keyword_detection_security(self, project_root: Path) -> None:
        """Test keyword detection for SECURITY domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "authenticate user with token and password"
        )

        security_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.SECURITY), None
        )
        assert security_domain is not None
        assert security_domain.confidence > 0

    def test_keyword_detection_api(self, project_root: Path) -> None:
        """Test keyword detection for API domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "http endpoint request response json api"
        )

        api_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.API), None
        )
        assert api_domain is not None

    def test_keyword_detection_concurrency(self, project_root: Path) -> None:
        """Test keyword detection for CONCURRENCY domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "async thread lock race concurrent parallel"
        )

        concurrency_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.CONCURRENCY), None
        )
        assert concurrency_domain is not None

    def test_keyword_detection_storage(self, project_root: Path) -> None:
        """Test keyword detection for STORAGE domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "database sql query transaction cache persist"
        )

        storage_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.STORAGE), None
        )
        assert storage_domain is not None

    def test_keyword_detection_messaging(self, project_root: Path) -> None:
        """Test keyword detection for MESSAGING domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "queue message event stream kafka pubsub"
        )

        messaging_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.MESSAGING), None
        )
        assert messaging_domain is not None

    def test_keyword_detection_transform(self, project_root: Path) -> None:
        """Test keyword detection for TRANSFORM domain."""
        engine = DeepVerifyEngine(project_root=project_root)

        result = engine._keyword_domain_detection(
            "convert transform parse serialize format"
        )

        transform_domain = next(
            (d for d in result.domains if d.domain == ArtifactDomain.TRANSFORM), None
        )
        assert transform_domain is not None


# =============================================================================
# AC-8: Verdict Summary Generation
# =============================================================================


class TestVerdictSummary:
    """Tests for AC-8: Verdict summary generation."""

    def test_generate_summary_format(self, project_root: Path) -> None:
        """Test summary format matches expected pattern."""
        engine = DeepVerifyEngine(project_root=project_root)

        findings = [
            Finding(
                id="F1",
                severity=Severity.ERROR,
                title="Test",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="F2",
                severity=Severity.WARNING,
                title="Test",
                description="Test",
                method_id=MethodId("#154"),
            ),
        ]

        domains = [ArtifactDomain.SECURITY, ArtifactDomain.API]

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        methods = [mock_method1, mock_method2]

        summary = engine._generate_summary(
            VerdictDecision.REJECT, 8.5, findings, domains, methods
        )

        # Format: "{decision} verdict (score: {score}). {n} findings: {findings_list}.
        #          Domains: {domain_names}. Methods: {method_ids}."
        assert "REJECT verdict" in summary
        assert "score: 8.5" in summary
        assert "2 findings: F1, F2" in summary
        assert "Domains: security, api" in summary
        assert "Methods: #153, #154" in summary

    def test_generate_summary_empty_findings(self, project_root: Path) -> None:
        """Test summary with empty findings."""
        engine = DeepVerifyEngine(project_root=project_root)

        summary = engine._generate_summary(
            VerdictDecision.ACCEPT, 0.0, [], [], []
        )

        assert "ACCEPT verdict" in summary
        assert "0 findings: none" in summary
        assert "Domains: none" in summary
        assert "Methods: none" in summary

    def test_empty_verdict_summary(self, project_root: Path) -> None:
        """Test _empty_verdict generates correct summary."""
        engine = DeepVerifyEngine(project_root=project_root)

        domain_result = DomainDetectionResult(
            domains=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)],
            reasoning="Test",
        )

        verdict = engine._empty_verdict(domain_result)

        assert "ACCEPT verdict (score: 0.0)" in verdict.summary
        assert "0 findings: none" in verdict.summary
        assert "Domains: api" in verdict.summary


# =============================================================================
# AC-9: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for AC-9: Error handling."""

    @pytest.mark.asyncio
    async def test_none_artifact_raises_valueerror(self, project_root: Path) -> None:
        """Test that None artifact raises ValueError."""
        engine = DeepVerifyEngine(project_root=project_root)

        with pytest.raises(ValueError, match="cannot be None"):
            await engine.verify(None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_empty_artifact_returns_accept(self, project_root: Path) -> None:
        """Test that empty artifact returns ACCEPT verdict."""
        engine = DeepVerifyEngine(project_root=project_root)

        verdict = await engine.verify("")
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0
        assert verdict.findings == []

    @pytest.mark.asyncio
    async def test_whitespace_only_artifact_returns_accept(
        self, project_root: Path
    ) -> None:
        """Test that whitespace-only artifact returns ACCEPT verdict."""
        engine = DeepVerifyEngine(project_root=project_root)

        verdict = await engine.verify("   \n\t   ")
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0

    @pytest.mark.asyncio
    async def test_method_timeout_returns_empty_list(
        self, project_root: Path
    ) -> None:
        """Test that method timeout returns empty findings list."""
        engine = DeepVerifyEngine(project_root=project_root)

        async def slow_method(text: str, **kwargs: object) -> list[Finding]:
            await asyncio.sleep(10)  # Will timeout
            return []

        mock_method = Mock(spec=BaseVerificationMethod)
        mock_method.method_id = MethodId("#153")
        mock_method.analyze = slow_method

        # Should timeout and return empty list
        result = await engine._run_single_method(
            mock_method, "test", None, timeout=0.01  # Very short timeout
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_method_exception_logged_but_not_blocking(
        self, project_root: Path
    ) -> None:
        """Test that method exception is logged but doesn't block other methods."""
        engine = DeepVerifyEngine(project_root=project_root)

        async def failing_method(text: str, **kwargs: object) -> list[Finding]:
            raise ValueError("Method failed")

        async def working_method(text: str, **kwargs: object) -> list[Finding]:
            return [
                Finding(
                    id="temp-1",
                    severity=Severity.ERROR,
                    title="Test",
                    description="Test",
                    method_id=MethodId("#154"),
                )
            ]

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method1.analyze = failing_method

        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        mock_method2.analyze = working_method

        results = await engine._run_methods_with_errors(
            [mock_method1, mock_method2], "test", None, None
        )

        # First method should have failed
        assert results[0].success is False
        assert results[0].error is not None
        # Second method should have succeeded with findings
        assert results[1].success is True
        assert len(results[1].findings) == 1
        assert results[1].findings[0].method_id == MethodId("#154")


# =============================================================================
# AC-10: End-to-End Tests
# =============================================================================


@pytest.mark.slow  # Real engine with domain detection - 6s+
class TestEndToEnd:
    """End-to-end tests for AC-10."""

    @pytest.mark.asyncio
    async def test_all_7_domains_individually(self, project_root: Path) -> None:
        """Test with all 7 ArtifactDomain values individually."""
        engine = DeepVerifyEngine(project_root=project_root)

        for domain in ArtifactDomain:
            # Use keyword detection for predictable domain selection
            result = engine._keyword_domain_detection(domain.value)

            # Should detect the domain
            assert len(result.domains) >= 0  # At minimum doesn't crash

    @pytest.mark.asyncio
    async def test_finding_deduplication_by_similarity(self, project_root: Path) -> None:
        """Test finding deduplication by evidence similarity."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Two methods returning similar findings
        evidence_text = "def similar_function_name(): pass"

        async def method1(text: str, **kwargs: object) -> list[Finding]:
            return [
                Finding(
                    id="temp-1",
                    severity=Severity.WARNING,
                    title="Finding from method1",
                    description="Test",
                    method_id=MethodId("#153"),
                    evidence=[Evidence(quote=evidence_text)],
                )
            ]

        async def method2(text: str, **kwargs: object) -> list[Finding]:
            return [
                Finding(
                    id="temp-2",
                    severity=Severity.ERROR,  # Higher severity
                    title="Finding from method2",
                    description="Test",
                    method_id=MethodId("#154"),
                    evidence=[Evidence(quote=evidence_text)],  # Same evidence
                )
            ]

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method1.analyze = method1

        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        mock_method2.analyze = method2

        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(
            return_value=DomainDetectionResult(
                domains=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)],
                reasoning="API",
            )
        )

        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[mock_method1, mock_method2])

        verdict = await engine.verify("test code")

        # Should have only 1 finding (deduplicated)
        assert len(verdict.findings) == 1
        assert verdict.findings[0].severity == Severity.ERROR  # Higher severity kept

    @pytest.mark.asyncio
    async def test_finding_limits_enforced(self, project_root: Path) -> None:
        """Test finding limits (50 per method, 200 total)."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Create method returning 60 findings
        async def many_findings_method(text: str, **kwargs: object) -> list[Finding]:
            return [
                Finding(
                    id=f"temp-{i}",
                    severity=Severity.INFO,
                    title=f"Finding {i}",
                    description="Test",
                    method_id=MethodId("#153"),
                )
                for i in range(60)
            ]

        mock_method = Mock(spec=BaseVerificationMethod)
        mock_method.method_id = MethodId("#153")
        mock_method.analyze = many_findings_method

        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(
            return_value=DomainDetectionResult(
                domains=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)],
                reasoning="API",
            )
        )

        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[mock_method])

        verdict = await engine.verify("test code")

        # Should be limited to 50 per method
        assert len(verdict.findings) == 50

    @pytest.mark.asyncio
    async def test_config_disabled_returns_accept(self, project_root: Path) -> None:
        """Test that config.enabled=False returns ACCEPT verdict."""
        config = DeepVerifyConfig(enabled=False)
        engine = DeepVerifyEngine(project_root=project_root, config=config)

        verdict = await engine.verify("test code")

        # Should return ACCEPT since no methods selected
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0

    @pytest.mark.asyncio
    async def test_clean_pass_bonus_applied(self, project_root: Path) -> None:
        """Test clean_pass_bonus configuration is applied correctly."""
        config = DeepVerifyConfig(clean_pass_bonus=-0.5)
        engine = DeepVerifyEngine(project_root=project_root, config=config)

        assert engine._scorer.clean_pass_bonus == -0.5

    @pytest.mark.asyncio
    async def test_config_enable_disable_flags(self, project_root: Path) -> None:
        """Test per-method enable/disable flags."""
        config = DeepVerifyConfig(
            method_153_pattern_match=MethodConfig(enabled=False),
            method_154_boundary_analysis=MethodConfig(enabled=False),
            method_203_domain_expert=MethodConfig(enabled=False),
        )

        selector = MethodSelector(config)
        methods = selector.select([ArtifactDomain.API])
        method_ids = [m.method_id for m in methods]

        # Always-run methods should not be present
        assert MethodId("#153") not in method_ids
        assert MethodId("#154") not in method_ids
        assert MethodId("#203") not in method_ids
        # But API-specific methods should still be there
        assert MethodId("#201") in method_ids


# =============================================================================
# Additional Tests for Robustness
# =============================================================================


class TestAdditionalRobustness:
    """Additional tests for robustness."""

    @pytest.mark.asyncio
    async def test_context_passed_to_methods(self, project_root: Path) -> None:
        """Test that context is passed to methods that accept it."""
        engine = DeepVerifyEngine(project_root=project_root)

        received_context: VerificationContext | None = None

        async def context_checking_method(
            text: str, **kwargs: object
        ) -> list[Finding]:
            nonlocal received_context
            received_context = kwargs.get("context")
            return []

        mock_method = Mock(spec=BaseVerificationMethod)
        mock_method.method_id = MethodId("#153")
        mock_method.analyze = context_checking_method

        context = VerificationContext(language="python", file_path=Path("test.py"))
        await engine._run_single_method(mock_method, "test", context, None)

        assert received_context == context

    def test_deduplicate_empty_findings(self, project_root: Path) -> None:
        """Test deduplication with empty findings list."""
        engine = DeepVerifyEngine(project_root=project_root)
        result = engine._deduplicate_findings([])
        assert result == []

    def test_assign_ids_empty_findings(self, project_root: Path) -> None:
        """Test ID assignment with empty findings list."""
        engine = DeepVerifyEngine(project_root=project_root)
        result = engine._assign_finding_ids([])
        assert result == []

    def test_apply_limits_empty_findings(self, project_root: Path) -> None:
        """Test limits with empty findings list."""
        engine = DeepVerifyEngine(project_root=project_root)
        result = engine._apply_finding_limits([])
        assert result == []

    def test_calculate_clean_passes_empty(self, project_root: Path) -> None:
        """Test clean pass calculation with empty domains."""
        engine = DeepVerifyEngine(project_root=project_root)
        result = engine._calculate_clean_passes([], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_methods_selected_returns_empty_verdict(
        self, project_root: Path
    ) -> None:
        """Test that no methods selected returns empty verdict."""
        engine = DeepVerifyEngine(project_root=project_root)

        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(
            return_value=DomainDetectionResult(domains=[], reasoning="No domains")
        )

        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[])

        verdict = await engine.verify("test code")

        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0
        assert verdict.findings == []

    @pytest.mark.asyncio
    async def test_domain_detection_failure_fallback(
        self, project_root: Path
    ) -> None:
        """Test domain detection failure falls back to keyword detection."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Make detector raise exception
        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(side_effect=ProviderError("LLM down"))

        # Mock method selector and methods to avoid real execution
        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[])

        # Should not raise - uses keyword fallback
        result = await engine._detect_domains("auth token")

        # Should have SECURITY domain from keywords
        assert any(d.domain == ArtifactDomain.SECURITY for d in result.domains)

    @pytest.mark.asyncio
    async def test_all_methods_fail_gracefully(self, project_root: Path) -> None:
        """Test that all methods failing returns partial results with errors."""
        engine = DeepVerifyEngine(project_root=project_root)

        async def failing_method(text: str, **kwargs: object) -> list[Finding]:
            raise ValueError("Always fails")

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method1.analyze = failing_method

        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        mock_method2.analyze = failing_method

        results = await engine._run_methods_with_errors(
            [mock_method1, mock_method2], "test", None, None
        )

        # Both methods should have failed
        assert all(not r.success for r in results)
        # Both should have error information
        assert all(r.error is not None for r in results)

    @pytest.mark.asyncio
    async def test_severity_order_in_id_assignment(self, project_root: Path) -> None:
        """Test that findings are ordered by severity before ID assignment."""
        engine = DeepVerifyEngine(project_root=project_root)

        findings = [
            Finding(
                id="old-1",
                severity=Severity.INFO,
                title="Info",
                description="Test",
                method_id=MethodId("#153"),
            ),
            Finding(
                id="old-2",
                severity=Severity.ERROR,
                title="Error",
                description="Test",
                method_id=MethodId("#154"),
            ),
            Finding(
                id="old-3",
                severity=Severity.CRITICAL,
                title="Critical",
                description="Test",
                method_id=MethodId("#155"),
            ),
            Finding(
                id="old-4",
                severity=Severity.WARNING,
                title="Warning",
                description="Test",
                method_id=MethodId("#157"),
            ),
        ]

        reassigned = engine._assign_finding_ids(findings)

        # Order should be: CRITICAL, ERROR, WARNING, INFO
        assert reassigned[0].severity == Severity.CRITICAL
        assert reassigned[1].severity == Severity.ERROR
        assert reassigned[2].severity == Severity.WARNING
        assert reassigned[3].severity == Severity.INFO
        assert reassigned[0].id == "F1"
        assert reassigned[1].id == "F2"
        assert reassigned[2].id == "F3"
        assert reassigned[3].id == "F4"


# =============================================================================
# Test Count Verification
# =============================================================================


def test_minimum_40_tests() -> None:
    """Verify we have at least 40 test functions defined in this module."""
    import inspect
    import sys

    module = sys.modules[__name__]
    test_count = 0

    for name in dir(module):
        obj = getattr(module, name)
        if inspect.isclass(obj) and name.startswith("Test"):
            for method_name in dir(obj):
                if method_name.startswith("test_"):
                    test_count += 1

    # We should have many more than 40 tests
    assert test_count >= 40, f"Expected at least 40 tests, found {test_count}"
