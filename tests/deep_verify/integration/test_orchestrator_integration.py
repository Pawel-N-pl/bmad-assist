"""Tests for Deep Verify integration with validation orchestrator.

Story 26.16: Validate Story Integration Hook - Orchestrator Tests
"""

import json
from datetime import UTC, datetime

from bmad_assist.deep_verify.core.types import (
    ArtifactDomain,
    DeepVerifyValidationResult,
    DomainConfidence,
    Finding,
    MethodId,
    Severity,
    VerdictDecision,
)
from bmad_assist.validation.orchestrator import (
    ValidationPhaseResult,
    load_validations_for_synthesis,
    save_validations_for_synthesis,
)


class TestValidationPhaseResult:
    """Tests for ValidationPhaseResult with DV data."""

    def test_result_with_dv_data(self):
        """Test ValidationPhaseResult includes DV result."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        dv_result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.ACCEPT,
            score=0.0,
            duration_ms=1000,
        )

        result = ValidationPhaseResult(
            anonymized_validations=[
                AnonymizedValidation(
                    validator_id="Validator A",
                    content="Test validation",
                    original_ref="ref-1",
                )
            ],
            session_id="test-session",
            validation_count=1,
            validators=["claude"],
            failed_validators=[],
            evaluation_records=[],
            evidence_aggregate=None,
            deep_verify_result=dv_result,
        )

        assert result.deep_verify_result is not None
        assert result.deep_verify_result.verdict == VerdictDecision.ACCEPT
        assert result.deep_verify_result.score == 0.0

    def test_result_without_dv_data(self):
        """Test ValidationPhaseResult without DV result (backward compat)."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        result = ValidationPhaseResult(
            anonymized_validations=[
                AnonymizedValidation(
                    validator_id="Validator A",
                    content="Test validation",
                    original_ref="ref-1",
                )
            ],
            session_id="test-session",
            validation_count=1,
            validators=["claude"],
            failed_validators=[],
            evaluation_records=[],
            evidence_aggregate=None,
            deep_verify_result=None,
        )

        assert result.deep_verify_result is None

    def test_to_dict_with_dv(self):
        """Test to_dict includes DV status."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.ERROR,
                    title="Test Issue",
                    description="Test",
                    method_id=MethodId("#153"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                )
            ],
            domains_detected=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.8)],
            methods_executed=[MethodId("#153")],
            verdict=VerdictDecision.REJECT,
            score=6.5,
            duration_ms=2000,
        )

        result = ValidationPhaseResult(
            anonymized_validations=[
                AnonymizedValidation(
                    validator_id="Validator A",
                    content="Test",
                    original_ref="ref-1",
                )
            ],
            session_id="test-session",
            validation_count=1,
            validators=["claude"],
            deep_verify_result=dv_result,
        )

        data = result.to_dict()
        assert data["session_id"] == "test-session"
        assert data["validation_count"] == 1

        # Story 26.16: Verify Deep Verify data is included in to_dict()
        assert "deep_verify" in data
        assert data["deep_verify"]["verdict"] == "REJECT"
        assert data["deep_verify"]["score"] == 6.5
        assert data["deep_verify"]["findings_count"] == 1
        assert data["deep_verify"]["has_critical"] is False  # ERROR severity, not CRITICAL


class TestCacheV3:
    """Tests for cache version 3 with Deep Verify data."""

    def test_save_with_dv_result(self, tmp_path):
        """Test saving validations with DV result creates v3 cache."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        anonymized = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test validation content",
                original_ref="ref-1",
            )
        ]

        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.CRITICAL,
                    title="Security Issue",
                    description="Critical security finding",
                    method_id=MethodId("#201"),
                    domain=ArtifactDomain.SECURITY,
                    evidence=[],
                )
            ],
            domains_detected=[
                DomainConfidence(
                    domain=ArtifactDomain.SECURITY,
                    confidence=0.95,
                    signals=["auth"],
                )
            ],
            methods_executed=[MethodId("#153"), MethodId("#201")],
            verdict=VerdictDecision.REJECT,
            score=8.0,
            duration_ms=3500,
        )

        session_id = save_validations_for_synthesis(
            anonymized=anonymized,
            project_root=tmp_path,
            session_id="test-dv-session",
            deep_verify_result=dv_result,
        )

        cache_file = tmp_path / ".bmad-assist" / "cache" / f"validations-{session_id}.json"
        assert cache_file.exists()

        data = json.loads(cache_file.read_text())
        assert data["cache_version"] == 3
        assert "deep_verify" in data
        assert data["deep_verify"]["verdict"] == "REJECT"
        assert data["deep_verify"]["score"] == 8.0
        assert len(data["deep_verify"]["findings"]) == 1
        assert data["deep_verify"]["findings"][0]["id"] == "F1"

    def test_load_with_dv_result(self, tmp_path):
        """Test loading validations with DV result from v3 cache."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        anonymized = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test validation",
                original_ref="ref-1",
            )
        ]

        dv_result = DeepVerifyValidationResult(
            findings=[],
            domains_detected=[],
            methods_executed=[MethodId("#153")],
            verdict=VerdictDecision.ACCEPT,
            score=-2.0,
            duration_ms=1500,
        )

        session_id = save_validations_for_synthesis(
            anonymized=anonymized,
            project_root=tmp_path,
            session_id="test-load-session",
            deep_verify_result=dv_result,
        )

        validations, failed_validators, evidence_score, loaded_dv = load_validations_for_synthesis(
            session_id=session_id,
            project_root=tmp_path,
        )

        assert len(validations) == 1
        assert loaded_dv is not None
        assert loaded_dv.verdict == VerdictDecision.ACCEPT
        assert loaded_dv.score == -2.0
        assert loaded_dv.duration_ms == 1500

    def test_backward_compat_v2_cache(self, tmp_path):
        """Test loading v2 cache without DV data returns None for DV."""
        # Create a v2 cache file manually
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "validations-v2-session.json"

        v2_data = {
            "cache_version": 2,
            "session_id": "v2-session",
            "timestamp": datetime.now(UTC).isoformat(),
            "validations": [
                {
                    "validator_id": "Validator A",
                    "content": "Test",
                    "original_ref": "ref-1",
                }
            ],
            "failed_validators": [],
            "evidence_score": {
                "total_score": 10.0,
                "verdict": "REJECT",
            },
        }

        cache_file.write_text(json.dumps(v2_data))

        validations, failed_validators, evidence_score, dv_result = load_validations_for_synthesis(
            session_id="v2-session",
            project_root=tmp_path,
        )

        assert len(validations) == 1
        assert dv_result is None  # No DV data in v2 cache
        assert evidence_score is not None
        assert evidence_score["total_score"] == 10.0

    def test_backward_compat_no_dv_param(self, tmp_path):
        """Test saving without DV result param works."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        anonymized = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Test",
                original_ref="ref-1",
            )
        ]

        # Save without deep_verify_result parameter
        session_id = save_validations_for_synthesis(
            anonymized=anonymized,
            project_root=tmp_path,
            session_id="test-no-dv",
        )

        cache_file = tmp_path / ".bmad-assist" / "cache" / f"validations-{session_id}.json"
        data = json.loads(cache_file.read_text())

        assert data["cache_version"] == 3
        assert "deep_verify" not in data  # No DV data saved

    def test_load_corrupted_dv_data(self, tmp_path):
        """Test loading cache with corrupted DV data returns None gracefully."""
        cache_dir = tmp_path / ".bmad-assist" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "validations-corrupted.json"

        v3_data = {
            "cache_version": 3,
            "session_id": "corrupted",
            "timestamp": datetime.now(UTC).isoformat(),
            "validations": [],
            "deep_verify": {
                "verdict": "INVALID_VERDICT",  # Invalid value
                "score": "not_a_number",  # Invalid type
            },
        }

        cache_file.write_text(json.dumps(v3_data))

        # Should not raise, just return None for DV
        validations, failed, evidence, dv = load_validations_for_synthesis(
            session_id="corrupted",
            project_root=tmp_path,
        )

        assert dv is None  # Failed to deserialize, returns None


class TestCacheRoundtrip:
    """Tests for cache save/load roundtrip."""

    def test_cache_save_load_roundtrip(self, tmp_path):
        """Test full save/load roundtrip with DV data."""
        from bmad_assist.validation.anonymizer import AnonymizedValidation

        # Create sample data
        anonymized = [
            AnonymizedValidation(
                validator_id="Validator A",
                content="Validation from Claude",
                original_ref="ref-claude",
            ),
            AnonymizedValidation(
                validator_id="Validator B",
                content="Validation from Gemini",
                original_ref="ref-gemini",
            ),
        ]

        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.ERROR,
                    title="API Design Issue",
                    description="Endpoint lacks rate limiting",
                    method_id=MethodId("#201"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                ),
                Finding(
                    id="F2",
                    severity=Severity.WARNING,
                    title="Documentation Gap",
                    description="Missing parameter docs",
                    method_id=MethodId("#153"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                ),
            ],
            domains_detected=[
                DomainConfidence(domain=ArtifactDomain.API, confidence=0.85, signals=["endpoint"])
            ],
            methods_executed=[MethodId("#153"), MethodId("#201")],
            verdict=VerdictDecision.UNCERTAIN,
            score=3.5,
            duration_ms=5000,
        )

        # Save
        session_id = save_validations_for_synthesis(
            anonymized=anonymized,
            project_root=tmp_path,
            session_id="roundtrip-test",
            failed_validators=["gemini-failed"],
            deep_verify_result=dv_result,
        )

        # Load
        loaded_validations, loaded_failed, loaded_evidence, loaded_dv = load_validations_for_synthesis(
            session_id=session_id,
            project_root=tmp_path,
        )

        # Verify
        assert len(loaded_validations) == 2
        assert loaded_validations[0].validator_id == "Validator A"
        assert loaded_validations[1].validator_id == "Validator B"
        assert loaded_failed == ["gemini-failed"]
        assert loaded_dv is not None
        assert loaded_dv.verdict == VerdictDecision.UNCERTAIN
        assert loaded_dv.score == 3.5
        assert len(loaded_dv.findings) == 2
        assert loaded_dv.findings[0].id == "F1"
        assert loaded_dv.findings[1].id == "F2"


class TestBlockerDetection:
    """Tests for blocker detection in handler."""

    def test_critical_finding_detection(self):
        """Test detection of CRITICAL findings in DV result."""
        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.CRITICAL,
                    title="Security Issue",
                    description="Critical security finding",
                    method_id=MethodId("#201"),
                    domain=ArtifactDomain.SECURITY,
                    evidence=[],
                ),
                Finding(
                    id="F2",
                    severity=Severity.ERROR,
                    title="Other Issue",
                    description="Error level finding",
                    method_id=MethodId("#153"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                ),
            ],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.REJECT,
            score=8.0,
            duration_ms=3000,
        )

        has_critical = any(f.severity == Severity.CRITICAL for f in dv_result.findings)
        assert has_critical is True

        critical_count = sum(1 for f in dv_result.findings if f.severity == Severity.CRITICAL)
        assert critical_count == 1

    def test_reject_verdict_with_critical_blocks(self):
        """Test that REJECT + CRITICAL should block."""
        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.CRITICAL,
                    title="Security Issue",
                    description="Critical security finding",
                    method_id=MethodId("#201"),
                    domain=ArtifactDomain.SECURITY,
                    evidence=[],
                ),
            ],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.REJECT,
            score=8.0,
            duration_ms=3000,
        )

        should_block = (
            dv_result.verdict == VerdictDecision.REJECT
            and any(f.severity == Severity.CRITICAL for f in dv_result.findings)
        )
        assert should_block is True

    def test_reject_without_critical_does_not_block(self):
        """Test that REJECT without CRITICAL should not block (soft block)."""
        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.ERROR,
                    title="API Issue",
                    description="Error level finding",
                    method_id=MethodId("#153"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                ),
            ],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.REJECT,
            score=4.0,
            duration_ms=3000,
        )

        should_block = (
            dv_result.verdict == VerdictDecision.REJECT
            and any(f.severity == Severity.CRITICAL for f in dv_result.findings)
        )
        assert should_block is False

    def test_uncertain_does_not_block(self):
        """Test that UNCERTAIN verdict should not block."""
        dv_result = DeepVerifyValidationResult(
            findings=[
                Finding(
                    id="F1",
                    severity=Severity.WARNING,
                    title="Minor Issue",
                    description="Warning level finding",
                    method_id=MethodId("#153"),
                    domain=ArtifactDomain.API,
                    evidence=[],
                ),
            ],
            domains_detected=[],
            methods_executed=[],
            verdict=VerdictDecision.UNCERTAIN,
            score=2.0,
            duration_ms=3000,
        )

        should_block = (
            dv_result.verdict == VerdictDecision.REJECT
            and any(f.severity == Severity.CRITICAL for f in dv_result.findings)
        )
        assert should_block is False
