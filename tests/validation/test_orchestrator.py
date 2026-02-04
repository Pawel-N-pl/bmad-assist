"""Tests for validation orchestrator module.

Story 11.7: Validation Phase Loop Integration
Tests for orchestrator functionality that coordinates Multi-LLM validation.

NOTE: Tests use asyncio.run() instead of pytest-asyncio to avoid adding
a new dependency. The Dev Notes specify this approach.
"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bmad_assist.core.config import (
    BenchmarkingConfig,
    Config,
    MasterProviderConfig,
    MultiProviderConfig,
    ProviderConfig,
)
from bmad_assist.providers.base import BaseProvider, ProviderResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_provider() -> MagicMock:
    """Create a mock provider."""
    provider = MagicMock(spec=BaseProvider)
    provider.provider_name = "mock"
    provider.invoke.return_value = ProviderResult(
        stdout="Mock validation output",
        stderr="",
        exit_code=0,
        duration_ms=1000,
        model="mock-model",
        command=("mock", "command"),
    )
    return provider


@pytest.fixture
def validation_config(tmp_path: Path) -> Config:
    """Config with multi providers for validation tests."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus-4"),
            multi=[
                MultiProviderConfig(provider="claude", model="sonnet-4"),
                MultiProviderConfig(provider="gemini", model="gemini-2.5-pro"),
            ],
        ),
        timeout=300,
        benchmarking=BenchmarkingConfig(enabled=False),
        parallel_delay=0,  # Disable stagger for tests expecting immediate parallel start
    )


@pytest.fixture
def minimal_config() -> Config:
    """Minimal config with just master provider."""
    return Config(
        providers=ProviderConfig(
            master=MasterProviderConfig(provider="claude", model="opus-4"),
            multi=[],
        ),
        timeout=300,
        benchmarking=BenchmarkingConfig(enabled=False),
    )


@pytest.fixture
def project_with_story(tmp_path: Path) -> Path:
    """Create a project with a story file."""
    from bmad_assist.core.paths import init_paths

    # Initialize paths singleton for this test
    paths = init_paths(tmp_path)
    paths.ensure_directories()

    # Create a story file in the new location
    story_file = paths.stories_dir / "11-7-validation-phase-loop-integration.md"
    story_file.write_text("""# Story 11.7: Validation Phase Loop Integration

Status: in-progress
Estimate: 3 SP

## Acceptance Criteria

### AC1: Test AC
**Given** a story exists
**Then** validation should work

## Tasks / Subtasks

- [ ] Task 1: Implement feature
""")

    return tmp_path


# =============================================================================
# Test ValidationPhaseResult dataclass (AC: #3)
# =============================================================================


class TestValidationPhaseResult:
    """Tests for ValidationPhaseResult dataclass."""

    def test_dataclass_exists(self) -> None:
        """ValidationPhaseResult can be imported."""
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        assert ValidationPhaseResult is not None

    def test_all_fields(self) -> None:
        """All required fields are present."""
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        result = ValidationPhaseResult(
            anonymized_validations=[
                AnonymizedValidation(
                    validator_id="Validator A",
                    content="Test",
                    original_ref="ref-1",
                )
            ],
            session_id="test-session",
            validation_count=3,
            validators=["claude", "gemini", "master"],
            failed_validators=["gpt"],
        )

        assert len(result.anonymized_validations) == 1
        assert result.session_id == "test-session"
        assert result.validation_count == 3
        assert result.validators == ["claude", "gemini", "master"]
        assert result.failed_validators == ["gpt"]

    def test_to_dict(self) -> None:
        """to_dict() returns serializable dict for PhaseResult.outputs."""
        from bmad_assist.validation.orchestrator import ValidationPhaseResult

        result = ValidationPhaseResult(
            anonymized_validations=[],
            session_id="sess-123",
            validation_count=2,
            validators=["claude", "gemini"],
            failed_validators=[],
        )

        d = result.to_dict()

        assert d["session_id"] == "sess-123"
        assert d["validation_count"] == 2
        assert d["validators"] == ["claude", "gemini"]
        assert d["failed_validators"] == []


# =============================================================================
# Test run_validation_phase (AC: #3, #4, #5)
# =============================================================================


class TestRunValidationPhase:
    """Tests for run_validation_phase() async function."""

    def test_function_exists(self) -> None:
        """run_validation_phase can be imported."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        assert run_validation_phase is not None

    def test_successful_validation_with_mocked_providers(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Successful validation returns ValidationPhaseResult (AC: #3)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        # Mock providers and registry
        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            # Setup mock provider
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="Validation output from claude",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-sonnet-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            # Setup mock compiler
            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=11,
                    story_num=7,
                )
            )

            assert result is not None
            assert result.validation_count >= 2
            assert result.session_id
            assert len(result.validators) >= 2

    def test_minimum_threshold_not_met_fails(
        self,
        minimal_config: Config,
        project_with_story: Path,
    ) -> None:
        """Returns failure when fewer than 2 validators succeed (AC: #6)."""
        from bmad_assist.validation.orchestrator import (
            InsufficientValidationsError,
            run_validation_phase,
        )

        # Mock providers - only master, which alone is insufficient
        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            # Setup mock provider that times out for all
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.side_effect = TimeoutError("Timed out")
            mock_get_provider.return_value = mock_provider

            # Setup mock compiler
            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            with pytest.raises(InsufficientValidationsError) as exc_info:
                asyncio.run(
                    run_validation_phase(
                        config=minimal_config,
                        project_path=project_with_story,
                        epic_num=11,
                        story_num=7,
                    )
                )

            assert "0" in str(exc_info.value) or "Insufficient" in str(exc_info.value)

    def test_timeout_handling_partial_success(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Single validator timeout doesn't break others (AC: #5)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        call_count = 0

        def invoke_side_effect(*args: Any, **kwargs: Any) -> ProviderResult:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Validator 1 timed out")
            return ProviderResult(
                stdout=f"Validation output {call_count}",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="test-model",
                command=("test",),
            )

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "test"
            mock_provider.invoke.side_effect = invoke_side_effect
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=11,
                    story_num=7,
                )
            )

            # Should succeed with remaining validators
            assert result.validation_count >= 2
            assert len(result.failed_validators) >= 1


# =============================================================================
# Test parallel invocation (AC: #4)
# =============================================================================


class TestParallelInvocation:
    """Tests for parallel provider invocation."""

    def test_validators_run_concurrently(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Validators run in parallel, not sequentially (AC: #4)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        invocation_times: list[float] = []

        def invoke_with_delay(*args: Any, **kwargs: Any) -> ProviderResult:
            """Simulate invocation with timing."""
            import time

            invocation_times.append(time.time())
            return ProviderResult(
                stdout="Validation output",
                stderr="",
                exit_code=0,
                duration_ms=100,
                model="test-model",
                command=("test",),
            )

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "test"
            mock_provider.invoke.side_effect = invoke_with_delay
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=11,
                    story_num=7,
                )
            )

            # All invocations should start very close together (< 0.5s apart)
            # If sequential, they would be spread out by sleep time
            if len(invocation_times) >= 2:
                time_spread = max(invocation_times) - min(invocation_times)
                assert time_spread < 0.5, f"Invocations not parallel: spread={time_spread}s"


# =============================================================================
# Test all-fail scenario (AC: #11)
# =============================================================================


class TestAllFailScenario:
    """Tests for all validators failing (AC: #11)."""

    def test_all_validators_fail_error_message(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Clear error message when all validators fail (AC: #11)."""
        from bmad_assist.validation.orchestrator import (
            InsufficientValidationsError,
            run_validation_phase,
        )

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "test"
            mock_provider.invoke.side_effect = TimeoutError("All timed out")
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            with pytest.raises(InsufficientValidationsError) as exc_info:
                asyncio.run(
                    run_validation_phase(
                        config=validation_config,
                        project_path=project_with_story,
                        epic_num=11,
                        story_num=7,
                    )
                )

            error_msg = str(exc_info.value)
            assert "0" in error_msg or "Insufficient" in error_msg


# =============================================================================
# Test InsufficientValidationsError (AC: #6)
# =============================================================================


class TestInsufficientValidationsError:
    """Tests for InsufficientValidationsError exception."""

    def test_exception_exists(self) -> None:
        """InsufficientValidationsError can be imported."""
        from bmad_assist.validation.orchestrator import InsufficientValidationsError

        assert InsufficientValidationsError is not None

    def test_inherits_from_bmad_error(self) -> None:
        """InsufficientValidationsError inherits from BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError
        from bmad_assist.validation.orchestrator import InsufficientValidationsError

        assert issubclass(InsufficientValidationsError, BmadAssistError)

    def test_error_attributes(self) -> None:
        """Error has count and minimum attributes."""
        from bmad_assist.validation.orchestrator import InsufficientValidationsError

        error = InsufficientValidationsError(count=1, minimum=2)

        assert error.count == 1
        assert error.minimum == 2
        assert "1" in str(error)
        assert "2" in str(error)


# =============================================================================
# Test ValidationError (base class)
# =============================================================================


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_exception_exists(self) -> None:
        """ValidationError can be imported."""
        from bmad_assist.validation.orchestrator import ValidationError

        assert ValidationError is not None

    def test_inherits_from_bmad_error(self) -> None:
        """ValidationError inherits from BmadAssistError."""
        from bmad_assist.core.exceptions import BmadAssistError
        from bmad_assist.validation.orchestrator import ValidationError

        assert issubclass(ValidationError, BmadAssistError)


# =============================================================================
# Test anonymization integration (AC: #3)
# =============================================================================


class TestAnonymizationIntegration:
    """Tests for anonymizer integration in orchestrator."""

    def test_calls_anonymize_validations(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Orchestrator calls anonymize_validations after collection (AC: #3)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
            patch("bmad_assist.validation.orchestrator.anonymize_validations") as mock_anon,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "test"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="Validation output",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="test-model",
                command=("test",),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            # Setup mock anonymization
            from bmad_assist.validation import AnonymizationMapping, AnonymizedValidation

            mock_anon.return_value = (
                [
                    AnonymizedValidation(
                        validator_id="Validator A",
                        content="Anonymized",
                        original_ref="ref-1",
                    )
                ],
                AnonymizationMapping(
                    session_id="test-session",
                    timestamp=datetime.now(UTC),
                    mapping={},
                ),
            )

            asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=11,
                    story_num=7,
                )
            )

            # Verify anonymization was called
            mock_anon.assert_called_once()


# =============================================================================
# Test inter-handler data passing (AC: #8)
# =============================================================================


class TestInterHandlerDataPassing:
    """Tests for save/load validations for synthesis (cache v2 with Evidence Score)."""

    def _make_mock_evidence_aggregate(self):
        """Create a mock EvidenceScoreAggregate for testing."""
        from bmad_assist.validation.evidence_score import (
            EvidenceScoreAggregate,
            Severity,
            Verdict,
        )

        return EvidenceScoreAggregate(
            total_score=2.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Validator A": 2.5},
            per_validator_verdicts={"Validator A": Verdict.PASS},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 2,
            },
            total_findings=3,
            total_clean_passes=5,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

    def test_save_validations_creates_file(self, tmp_path: Path) -> None:
        """save_validations_for_synthesis creates cache file with v2 format."""
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import save_validations_for_synthesis

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test content",
                original_ref="ref-1",
            ),
        ]

        session_id = save_validations_for_synthesis(
            validations,
            tmp_path,
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )

        # Check file was created
        cache_file = tmp_path / ".bmad-assist" / "cache" / f"validations-{session_id}.json"
        assert cache_file.exists()

        # Verify v3 format (Story 26.16: cache v3 includes Deep Verify data)
        import json

        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert data.get("cache_version") == 3
        assert "evidence_score" in data

    def test_load_validations_round_trip(self, tmp_path: Path) -> None:
        """Round trip: save then load returns same data (v2 format)."""
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import (
            load_validations_for_synthesis,
            save_validations_for_synthesis,
        )

        original = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Content A",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Content B",
                original_ref="ref-b",
            ),
        ]

        session_id = save_validations_for_synthesis(
            original,
            tmp_path,
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )
        # TIER 2: Now returns tuple (validations, failed_validators, evidence_score, dv_result)
        loaded, failed, evidence_score, dv_result = load_validations_for_synthesis(session_id, tmp_path)

        assert len(loaded) == 2
        assert loaded[0].validator_id == "Validator A"
        assert loaded[0].content == "Content A"
        assert loaded[1].validator_id == "Validator B"
        assert failed == []  # No failed validators in this test
        assert evidence_score is not None
        assert evidence_score["total_score"] == 2.5
        assert dv_result is None  # No DV result in this test

    def test_load_validations_not_found(self, tmp_path: Path) -> None:
        """load_validations_for_synthesis raises ValidationError if not found."""
        from bmad_assist.validation.orchestrator import (
            ValidationError,
            load_validations_for_synthesis,
        )

        with pytest.raises(ValidationError, match="not found"):
            load_validations_for_synthesis("nonexistent-session", tmp_path)

    def test_load_validations_rejects_v1_cache(self, tmp_path: Path) -> None:
        """load_validations_for_synthesis raises CacheVersionError for v1 cache."""
        import json

        from bmad_assist.validation.evidence_score import CacheVersionError
        from bmad_assist.validation.orchestrator import load_validations_for_synthesis

        # Create v1-format cache file (without cache_version)
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True)

        session_id = "v1-session-123"
        v1_format_data = {
            "session_id": session_id,
            "timestamp": "2026-01-20T12:00:00Z",
            "validations": [
                {
                    "validator_id": "Validator A",
                    "content": "V1 content",
                    "original_ref": "ref-v1",
                }
            ],
        }

        cache_file = cache_dir / f"validations-{session_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(v1_format_data, f)

        # Should raise CacheVersionError
        with pytest.raises(CacheVersionError, match="version"):
            load_validations_for_synthesis(session_id, tmp_path)

    def test_save_uses_atomic_write(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save_validations_for_synthesis uses atomic write pattern."""
        import os

        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import save_validations_for_synthesis

        replace_calls: list[tuple[Path, Path]] = []
        original_replace = os.replace

        def tracked_replace(src: str, dst: str) -> None:
            replace_calls.append((Path(src), Path(dst)))
            original_replace(src, dst)

        monkeypatch.setattr(os, "replace", tracked_replace)

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test",
                original_ref="ref-1",
            ),
        ]

        save_validations_for_synthesis(
            validations,
            tmp_path,
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )

        assert len(replace_calls) == 1
        src, dst = replace_calls[0]
        assert src.suffix == ".tmp"
        assert "validations-" in dst.name


# =============================================================================
# Test validation report persistence integration (Story 11.8 AC: #1)
# =============================================================================


class TestValidationReportPersistenceIntegration:
    """Tests for orchestrator calling save_validation_report (AC1)."""

    def test_orchestrator_saves_validation_reports_with_frontmatter(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Orchestrator calls save_validation_report for each successful validator."""
        import frontmatter

        from bmad_assist.validation.orchestrator import run_validation_phase

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="## Validation Issues\n\n1. Test issue found",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-sonnet-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=11,
                    story_num=7,
                )
            )

            # Check validation reports were created with YAML frontmatter
            from bmad_assist.core.paths import get_paths

            paths = get_paths()
            validations_dir = paths.validations_dir
            assert validations_dir.exists()

            validation_files = list(validations_dir.glob("validation-11-7-*.md"))
            assert len(validation_files) >= 2  # Multi + Master validators

            # Verify frontmatter structure
            for vf in validation_files:
                with open(vf, "r", encoding="utf-8") as f:
                    post = frontmatter.load(f)

                # Required frontmatter fields per AC1
                assert post.metadata["type"] == "validation"
                assert "validator_id" in post.metadata
                assert "timestamp" in post.metadata
                assert post.metadata["epic"] == 11
                assert post.metadata["story"] == 7
                assert post.metadata["phase"] == "VALIDATE_STORY"
                assert "duration_ms" in post.metadata
                assert "token_count" in post.metadata

                # Content should be the validation output
                assert "Validation Issues" in post.content or "Test issue" in post.content


# =============================================================================
# Test Story 22.8: Validation Synthesis Saving
# =============================================================================


class TestStory22_8ValidationSynthesisSaving:
    """Tests for Story 22.8: Validation synthesis saving improvements.

    AC #1: All validator reports are saved (N reports for N successful validators)
    AC #2: Individual validator reports are saved with correct naming
    AC #3: Synthesis document is saved with anonymized references
    AC #4: Partial success - only successful validators' reports persisted
    AC #5: Report save failure is logged but doesn't crash
    """

    def test_threshold_check_after_saving_reports(
        self,
        minimal_config: Config,
        project_with_story: Path,
    ) -> None:
        """Threshold check is AFTER saving reports (Story 22.8).

        AC #4: When threshold check fails, reports should still be saved.
        This prevents data loss when only 1 validator succeeds.
        """
        from bmad_assist.validation.orchestrator import (
            InsufficientValidationsError,
            run_validation_phase,
        )

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            # Only 1 validator (master) - insufficient for threshold
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="Validation output from single validator",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-opus-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            # Should raise InsufficientValidationsError
            with pytest.raises(InsufficientValidationsError):
                asyncio.run(
                    run_validation_phase(
                        config=minimal_config,
                        project_path=project_with_story,
                        epic_num=22,
                        story_num=8,
                    )
                )

            # AC #4: BUT the single report should still be saved (data loss prevention)
            validations_dir = (
                project_with_story
                / "_bmad-output"
                / "implementation-artifacts"
                / "story-validations"
            )
            validation_files = list(validations_dir.glob("validation-22-8-*.md"))
            assert len(validation_files) >= 1, (
                "At least 1 report should be saved even when threshold fails"
            )

    def test_report_save_failure_logged_but_continues(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Report save failure is logged but doesn't crash validation phase (AC #5)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
            patch("bmad_assist.validation.orchestrator.save_validation_report") as mock_save,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="Validation output",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-sonnet-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            # Mock save_validation_report to fail with OSError
            import os

            mock_save.side_effect = OSError("Permission denied")

            # Should NOT crash - should continue and log warning
            # The validation phase should succeed (threshold met) even though saves failed
            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=22,
                    story_num=8,
                )
            )

            # Verify validation phase completed despite save failures
            assert result is not None
            assert result.validation_count >= 2

    def test_all_n_validators_generate_n_report_files(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """All N validators generate N separate report files (AC #1, AC #2)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="Validation output from claude",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-sonnet-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=22,
                    story_num=8,
                )
            )

            # AC #1: N report files for N successful validators
            validations_dir = (
                project_with_story
                / "_bmad-output"
                / "implementation-artifacts"
                / "story-validations"
            )
            validation_files = list(validations_dir.glob("validation-22-8-*.md"))

            assert len(validation_files) >= result.validation_count, (
                f"Expected at least {result.validation_count} report files, got {len(validation_files)}"
            )

            # AC #2: Verify file naming follows convention: validation-{epic}-{story}-{role_id}-{timestamp}.md
            # New format uses single letter role_id (a, b, c...)
            import re

            for vf in validation_files:
                # Pattern: validation-22-8-{a|b|c...}-{timestamp}.md
                assert "validation-22-8-" in vf.name
                # Check for single letter role_id (new format) or legacy format
                pattern = r"validation-22-8-[a-z]-\d{8}T\d{6}Z?\.md"
                legacy_pattern = r"validation-22-8-(validator-[a-z]|master)-"
                assert re.match(pattern, vf.name) or re.search(legacy_pattern, vf.name), (
                    f"Filename {vf.name} doesn't match expected pattern"
                )

    def test_partial_success_saves_only_successful_reports(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Partial success - only successful validators' reports persisted (AC #4)."""
        from bmad_assist.validation.orchestrator import run_validation_phase

        call_count = 0

        def invoke_side_effect(*args: Any, **kwargs: Any) -> ProviderResult:
            nonlocal call_count
            call_count += 1
            # First call (multi provider) times out
            if call_count == 1:
                raise TimeoutError("Validator timed out")
            # Rest succeed
            return ProviderResult(
                stdout=f"Validation output {call_count}",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="test-model",
                command=("test",),
            )

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "test"
            mock_provider.invoke.side_effect = invoke_side_effect
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=22,
                    story_num=8,
                )
            )

            # AC #4: Only successful validators' reports should exist
            validations_dir = (
                project_with_story
                / "_bmad-output"
                / "implementation-artifacts"
                / "story-validations"
            )
            validation_files = list(validations_dir.glob("validation-22-8-*.md"))

            assert len(validation_files) == result.validation_count, (
                f"Expected {result.validation_count} reports for successful validators, got {len(validation_files)}"
            )
            assert len(result.failed_validators) > 0, "Should have at least 1 failed validator"


class TestStory22_8FailedValidatorsInCache:
    """Story 22.8 AC #4: failed_validators passed through cache for synthesis context (v2 format)."""

    def _make_mock_evidence_aggregate(self):
        """Create a mock EvidenceScoreAggregate for testing."""
        from bmad_assist.validation.evidence_score import (
            EvidenceScoreAggregate,
            Severity,
            Verdict,
        )

        return EvidenceScoreAggregate(
            total_score=2.5,
            verdict=Verdict.PASS,
            per_validator_scores={"Validator A": 2.5},
            per_validator_verdicts={"Validator A": Verdict.PASS},
            findings_by_severity={
                Severity.CRITICAL: 0,
                Severity.IMPORTANT: 1,
                Severity.MINOR: 2,
            },
            total_findings=3,
            total_clean_passes=5,
            consensus_findings=(),
            unique_findings=(),
            consensus_ratio=0.5,
        )

    def test_save_validations_with_failed_validators(self, tmp_path: Path) -> None:
        """save_validations_for_synthesis persists failed_validators in cache."""
        import json

        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import save_validations_for_synthesis

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test content",
                original_ref="ref-1",
            ),
        ]

        session_id = save_validations_for_synthesis(
            validations,
            tmp_path,
            failed_validators=["claude-haiku", "gemini-flash"],
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )

        # Verify cache file contains failed_validators
        cache_file = tmp_path / ".bmad-assist" / "cache" / f"validations-{session_id}.json"
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "failed_validators" in data
        assert data["failed_validators"] == ["claude-haiku", "gemini-flash"]
        assert data.get("cache_version") == 3  # Story 26.16: cache v3

    def test_save_validations_empty_failed_validators(self, tmp_path: Path) -> None:
        """save_validations_for_synthesis handles empty failed_validators list (omits from cache)."""
        import json

        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import save_validations_for_synthesis

        validations = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test content",
                original_ref="ref-1",
            ),
        ]

        session_id = save_validations_for_synthesis(
            validations,
            tmp_path,
            failed_validators=[],  # Empty list - treated same as None
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )

        cache_file = tmp_path / ".bmad-assist" / "cache" / f"validations-{session_id}.json"
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Empty list is omitted (same as None) for cleaner JSON
        assert "failed_validators" not in data

    def test_load_validations_returns_failed_validators(self, tmp_path: Path) -> None:
        """load_validations_for_synthesis returns tuple with failed_validators (AC #4)."""
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import (
            load_validations_for_synthesis,
            save_validations_for_synthesis,
        )

        original = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Content A",
                original_ref="ref-a",
            ),
        ]

        session_id = save_validations_for_synthesis(
            original,
            tmp_path,
            failed_validators=["failed-provider-1", "failed-provider-2"],
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )

        # TIER 2: Load returns tuple: (validations, failed_validators, evidence_score, dv_result)
        loaded_validations, loaded_failed, evidence_score, dv_result = load_validations_for_synthesis(
            session_id, tmp_path
        )

        assert len(loaded_validations) == 1
        assert loaded_validations[0].validator_id == "Validator A"
        assert loaded_failed == ["failed-provider-1", "failed-provider-2"]
        assert evidence_score is not None
        assert dv_result is None  # No DV result in this test

    def test_save_load_round_trip_with_failed_validators(self, tmp_path: Path) -> None:
        """Complete round-trip test for failed_validators through cache (v2 format)."""
        from bmad_assist.validation import AnonymizedValidation
        from bmad_assist.validation.orchestrator import (
            load_validations_for_synthesis,
            save_validations_for_synthesis,
        )

        original = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Content A",
                original_ref="ref-a",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Content B",
                original_ref="ref-b",
            ),
        ]
        failed = ["timeout-validator", "error-validator"]

        session_id = save_validations_for_synthesis(
            original,
            tmp_path,
            failed_validators=failed,
            evidence_aggregate=self._make_mock_evidence_aggregate(),
        )
        # TIER 2: Load returns 4-element tuple (includes dv_result)
        loaded_validations, loaded_failed, evidence_score, dv_result = load_validations_for_synthesis(
            session_id, tmp_path
        )

        # Validate round-trip
        assert len(loaded_validations) == 2
        assert loaded_validations[0].validator_id == "Validator A"
        assert loaded_validations[1].validator_id == "Validator B"
        assert loaded_failed == ["timeout-validator", "error-validator"]
        assert evidence_score is not None
        assert dv_result is None  # No DV result in this test


class TestStory22_8SessionIdInValidationReports:
    """Story 22.8 AC #3: session_id passed to individual validation reports."""

    def test_orchestrator_passes_session_id_to_reports(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Orchestrator passes session_id to save_validation_report (AC #3)."""
        import frontmatter

        from bmad_assist.validation.orchestrator import run_validation_phase

        with (
            patch("bmad_assist.validation.orchestrator.get_provider") as mock_get_provider,
            patch("bmad_assist.validation.orchestrator.compile_workflow") as mock_compile,
        ):
            mock_provider = MagicMock(spec=BaseProvider)
            mock_provider.provider_name = "claude"
            mock_provider.invoke.return_value = ProviderResult(
                stdout="## Validation Issues\n\n1. Test issue",
                stderr="",
                exit_code=0,
                duration_ms=5000,
                model="claude-sonnet-4",
                command=("claude", "--print"),
            )
            mock_get_provider.return_value = mock_provider

            mock_compiled = MagicMock()
            mock_compiled.context = "<compiled-workflow>test</compiled-workflow>"
            mock_compile.return_value = mock_compiled

            result = asyncio.run(
                run_validation_phase(
                    config=validation_config,
                    project_path=project_with_story,
                    epic_num=22,
                    story_num=8,
                )
            )

            # Verify validation reports have session_id in frontmatter
            validations_dir = (
                project_with_story
                / "_bmad-output"
                / "implementation-artifacts"
                / "story-validations"
            )
            validation_files = list(validations_dir.glob("validation-22-8-*.md"))
            assert len(validation_files) >= 1

            # Check at least one report has session_id matching result.session_id
            found_session_id = False
            for vf in validation_files:
                with open(vf, "r", encoding="utf-8") as f:
                    post = frontmatter.load(f)
                if post.metadata.get("session_id") == result.session_id:
                    found_session_id = True
                    break

            assert found_session_id, (
                f"Expected session_id={result.session_id} in validation report frontmatter"
            )


# =============================================================================
# Test Quota-Aware Model Fallback
# =============================================================================


class TestQuotaFallback:
    """Tests for quota-aware model fallback in _invoke_validator."""

    def test_fallback_on_quota_exhaustion(
        self,
        validation_config: Config,
        project_with_story: Path,
    ) -> None:
        """Validator falls back to alternative model on QuotaExhaustedError."""
        from bmad_assist.core.exceptions import QuotaExhaustedError
        from bmad_assist.validation.orchestrator import _invoke_validator

        call_count = 0

        def invoke_side_effect(*args: Any, **kwargs: Any) -> ProviderResult:
            nonlocal call_count
            call_count += 1
            model = kwargs.get("model", "unknown")
            if model == "gemini-3-pro-preview":
                raise QuotaExhaustedError(
                    "Quota exhausted",
                    provider_name="gemini",
                    model=model,
                    stderr="Error when talking to Gemini API",
                )
            # Fallback model succeeds
            return ProviderResult(
                stdout="Validation from fallback",
                stderr="",
                exit_code=0,
                duration_ms=2000,
                model=model,
                command=("gemini", "-m", model),
            )

        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.invoke.side_effect = invoke_side_effect

        provider_id, output, _, error = asyncio.run(
            _invoke_validator(
                provider=mock_provider,
                prompt="test prompt",
                timeout=300,
                provider_id="gemini-gemini-3-pro-preview",
                model="gemini-3-pro-preview",
                fallback_models=["gemini-2.5-flash"],
            )
        )

        assert output is not None
        assert error is None
        assert output.model == "gemini-2.5-flash"
        assert call_count == 2

    def test_no_fallback_configured(
        self,
    ) -> None:
        """Without fallback_models, quota exhaustion returns error."""
        from bmad_assist.core.exceptions import QuotaExhaustedError
        from bmad_assist.validation.orchestrator import _invoke_validator

        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.invoke.side_effect = QuotaExhaustedError(
            "Quota exhausted",
            provider_name="gemini",
            model="gemini-3-pro",
            stderr="Error when talking to Gemini API",
        )

        provider_id, output, _, error = asyncio.run(
            _invoke_validator(
                provider=mock_provider,
                prompt="test prompt",
                timeout=300,
                provider_id="gemini-gemini-3-pro",
                model="gemini-3-pro",
                fallback_models=None,
            )
        )

        assert output is None
        assert error is not None
        assert "all models quota-exhausted" in error

    def test_all_fallbacks_exhausted(
        self,
    ) -> None:
        """All models exhausted returns error with last quota message."""
        from bmad_assist.core.exceptions import QuotaExhaustedError
        from bmad_assist.validation.orchestrator import _invoke_validator

        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.invoke.side_effect = QuotaExhaustedError(
            "Quota exhausted",
            provider_name="gemini",
            model="any",
            stderr="Error when talking to Gemini API",
        )

        provider_id, output, _, error = asyncio.run(
            _invoke_validator(
                provider=mock_provider,
                prompt="test prompt",
                timeout=300,
                provider_id="gemini-test",
                model="gemini-3-pro",
                fallback_models=["gemini-2.5-flash", "gemini-2.5-pro"],
            )
        )

        assert output is None
        assert error is not None
        assert "all models quota-exhausted" in error
        # Should have tried all 3 models
        assert mock_provider.invoke.call_count == 3

    def test_timeout_not_caught_by_fallback(
        self,
    ) -> None:
        """TimeoutError is NOT caught by fallback loop (immediate return)."""
        from bmad_assist.validation.orchestrator import _invoke_validator

        mock_provider = MagicMock(spec=BaseProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.invoke.side_effect = TimeoutError("timed out")

        provider_id, output, _, error = asyncio.run(
            _invoke_validator(
                provider=mock_provider,
                prompt="test prompt",
                timeout=300,
                provider_id="gemini-test",
                model="gemini-3-pro",
                fallback_models=["gemini-2.5-flash"],
            )
        )

        assert output is None
        assert error is not None
        assert "timed out" in error
        # Should only try once (timeout is not retried via fallback)
        assert mock_provider.invoke.call_count == 1
