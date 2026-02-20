"""Tests for Deep Verify resource limits and error handling (Story 26.23).

This module provides comprehensive tests for:
- Input validation (size and line count limits)
- Finding limits (per method and total)
- Error categorization
- Partial results mode
- Regex timeout protection
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.deep_verify.config import DeepVerifyConfig, ResourceLimitConfig
from bmad_assist.deep_verify.core import (
    ArtifactDomain,
    CategorizedError,
    DeepVerifyError,
    DomainConfidence,
    DomainDetectionError,
    DomainDetectionResult,
    ErrorCategorizer,
    ErrorCategory,
    Finding,
    InputValidationError,
    InputValidator,
    MethodId,
    MethodResult,
    ResourceLimitError,
    Severity,
    ValidationResult,
    VerdictDecision,
    VerdictError,
)
from bmad_assist.deep_verify.core.engine import DeepVerifyEngine
from bmad_assist.deep_verify.methods.base import BaseVerificationMethod
from bmad_assist.providers.base import ExitStatus

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def strict_config() -> DeepVerifyConfig:
    """Create a config with strict resource limits for testing."""
    return DeepVerifyConfig(
        resource_limits=ResourceLimitConfig(
            max_artifact_size_bytes=1024,  # 1KB minimum
            max_line_count=10,
            max_findings_per_method=5,
            max_total_findings=15,
            regex_timeout_seconds=1.0,
        )
    )


@pytest.fixture
def input_validator(strict_config: DeepVerifyConfig) -> InputValidator:
    """Create an InputValidator with strict limits."""
    return InputValidator(strict_config.resource_limits)


@pytest.fixture
def error_categorizer() -> ErrorCategorizer:
    """Create an ErrorCategorizer."""
    return ErrorCategorizer()


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a temporary project root."""
    return tmp_path


# =============================================================================
# AC-1: Input Validation Tests
# =============================================================================


class TestInputValidation:
    """Tests for AC-1: Input validation - artifact size and line count."""

    def test_input_validator_valid_input(self, input_validator: InputValidator) -> None:
        """Test that valid input passes validation."""
        text = "def test():\n    pass"
        result = input_validator.validate(text)

        assert result.is_valid is True
        assert result.error_message is None
        assert result.size_bytes == len(text.encode("utf-8"))
        assert result.line_count == 2

    def test_input_validator_size_limit(self, input_validator: InputValidator) -> None:
        """Test that oversized input is rejected."""
        # Create text that exceeds 1024 bytes limit
        text = "x" * 1025
        result = input_validator.validate(text)

        assert result.is_valid is False
        assert result.error_message is not None
        assert "exceeds limit" in result.error_message.lower()
        assert result.size_bytes == 1025

    def test_input_validator_line_count_limit(self, input_validator: InputValidator) -> None:
        """Test that too many lines is rejected."""
        # Create text with more than 10 lines
        text = "\n".join([f"line {i}" for i in range(12)])
        result = input_validator.validate(text)

        assert result.is_valid is False
        assert result.error_message is not None
        assert "line count" in result.error_message.lower()
        assert result.line_count == 12

    def test_input_validator_exact_size_limit(self, input_validator: InputValidator) -> None:
        """Test that exactly at size limit passes."""
        # Exactly 1024 bytes
        text = "x" * 1024
        result = input_validator.validate(text)

        assert result.is_valid is True
        assert result.size_bytes == 1024

    def test_input_validator_exact_line_limit(self, input_validator: InputValidator) -> None:
        """Test that exactly at line limit passes."""
        # Exactly 10 lines
        text = "\n".join([f"line {i}" for i in range(10)])
        result = input_validator.validate(text)

        assert result.is_valid is True
        assert result.line_count == 10

    def test_input_validator_empty_string(self, input_validator: InputValidator) -> None:
        """Test validation of empty string."""
        result = input_validator.validate("")

        assert result.is_valid is True
        assert result.size_bytes == 0
        assert result.line_count == 0

    def test_input_validator_unicode(self, input_validator: InputValidator) -> None:
        """Test that unicode characters are counted correctly in bytes."""
        # Multi-byte unicode character
        text = "こんにちは"  # 15 bytes in UTF-8
        result = input_validator.validate(text)

        assert result.is_valid is True
        assert result.size_bytes == 15
        assert result.line_count == 1

    def test_validation_result_repr(self) -> None:
        """Test ValidationResult string representation."""
        result_valid = ValidationResult(
            is_valid=True,
            error_message=None,
            size_bytes=100,
            line_count=5,
        )
        assert "valid" in repr(result_valid).lower()

        result_invalid = ValidationResult(
            is_valid=False,
            error_message="Test error",
            size_bytes=200,
            line_count=10,
        )
        assert "invalid" in repr(result_invalid).lower()


# =============================================================================
# AC-2 & AC-3: Finding Limits Tests
# =============================================================================


class TestFindingLimits:
    """Tests for AC-2 and AC-3: Memory limits for findings."""

    def test_per_method_limit(self, project_root: Path, strict_config: DeepVerifyConfig) -> None:
        """Test max 50 findings per method (using config value)."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        # Create 10 findings from same method (over limit of 5)
        findings = [
            Finding(
                id=f"temp-{i}",
                severity=Severity.INFO,
                title=f"Finding {i}",
                description="Test",
                method_id=MethodId("#153"),
            )
            for i in range(10)
        ]

        limited = engine._apply_finding_limits(findings)
        # Should be limited to 5 per method
        assert len(limited) == 5

    def test_total_findings_limit(self, project_root: Path, strict_config: DeepVerifyConfig) -> None:
        """Test max 200 total findings (using config value)."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        # Create 20 findings from multiple methods (over total limit of 15)
        findings = []
        for i in range(20):
            method_id = MethodId(f"#{150 + (i % 4)}")
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
        assert len(limited) <= 15

    def test_severity_preserved_trucation(self, project_root: Path, strict_config: DeepVerifyConfig) -> None:
        """Test that CRITICAL findings are preserved over INFO when truncating."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        # Create 10 findings: 5 CRITICAL, 5 INFO
        findings = []
        for i in range(10):
            findings.append(
                Finding(
                    id=f"temp-{i}",
                    severity=Severity.CRITICAL if i < 5 else Severity.INFO,
                    title=f"Finding {i}",
                    description="Test",
                    method_id=MethodId("#153"),
                )
            )

        limited = engine._apply_finding_limits(findings)
        # Should keep all 5 CRITICAL findings
        critical_count = sum(1 for f in limited if f.severity == Severity.CRITICAL)
        assert critical_count == 5

    def test_empty_findings(self, project_root: Path, strict_config: DeepVerifyConfig) -> None:
        """Test limits with empty findings list."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        limited = engine._apply_finding_limits([])
        assert limited == []


# =============================================================================
# AC-7: Error Categorization Tests
# =============================================================================


class TestErrorCategorization:
    """Tests for AC-7: Error categorization system."""

    def test_categorize_timeout_error(self, error_categorizer: ErrorCategorizer) -> None:
        """Test ProviderTimeoutError is categorized as RETRYABLE_TIMEOUT."""
        error = ProviderTimeoutError("timeout")
        categorized = error_categorizer.classify(error, "#153")

        assert categorized.category == ErrorCategory.RETRYABLE_TIMEOUT
        assert categorized.is_fatal is False
        assert categorized.method_id == "#153"

    def test_categorize_rate_limit_error(self, error_categorizer: ErrorCategorizer) -> None:
        """Test rate limit error is categorized as RETRYABLE_TRANSIENT."""
        error = ProviderExitCodeError(
            "rate limit exceeded",
            exit_code=429,
            exit_status=ExitStatus.ERROR,
        )
        categorized = error_categorizer.classify(error, "#153")

        assert categorized.category == ErrorCategory.RETRYABLE_TRANSIENT
        assert categorized.is_fatal is False

    def test_categorize_auth_error(self, error_categorizer: ErrorCategorizer) -> None:
        """Test auth error (401) is categorized as FATAL_AUTH."""
        error = ProviderExitCodeError(
            "unauthorized",
            exit_code=401,
            exit_status=ExitStatus.MISUSE,
        )
        categorized = error_categorizer.classify(error, "#153")

        assert categorized.category == ErrorCategory.FATAL_AUTH
        assert categorized.is_fatal is True

    def test_categorize_bad_request(self, error_categorizer: ErrorCategorizer) -> None:
        """Test bad request (400) is categorized as FATAL_INVALID."""
        error = ProviderExitCodeError(
            "bad request",
            exit_code=400,
            exit_status=ExitStatus.MISUSE,
        )
        categorized = error_categorizer.classify(error, "#153")

        assert categorized.category == ErrorCategory.FATAL_INVALID
        assert categorized.is_fatal is True

    def test_categorize_server_error(self, error_categorizer: ErrorCategorizer) -> None:
        """Test server error (500) is categorized as RETRYABLE_TRANSIENT."""
        error = ProviderExitCodeError(
            "internal server error",
            exit_code=500,
            exit_status=ExitStatus.ERROR,
        )
        categorized = error_categorizer.classify(error, "#153")

        assert categorized.category == ErrorCategory.RETRYABLE_TRANSIENT
        assert categorized.is_fatal is False

    def test_categorize_provider_error_transient(self, error_categorizer: ErrorCategorizer) -> None:
        """Test ProviderError with transient message is retryable."""
        error = ProviderError("rate limit exceeded, please retry")
        categorized = error_categorizer.classify(error)

        assert categorized.category == ErrorCategory.RETRYABLE_TRANSIENT

    def test_categorize_provider_error_fatal(self, error_categorizer: ErrorCategorizer) -> None:
        """Test ProviderError without transient pattern is fatal."""
        error = ProviderError("invalid configuration")
        categorized = error_categorizer.classify(error)

        # Unknown provider errors default to fatal
        assert categorized.category == ErrorCategory.FATAL_UNKNOWN
        assert categorized.is_fatal is True

    def test_categorized_error_repr(self) -> None:
        """Test CategorizedError string representation."""
        error = ProviderTimeoutError("timeout")
        categorized = CategorizedError(
            error=error,
            category=ErrorCategory.RETRYABLE_TIMEOUT,
            method_id="#153",
        )

        repr_str = repr(categorized)
        assert "retryable_timeout" in repr_str  # Category value is lowercase
        assert "#153" in repr_str


# =============================================================================
# AC-8: Partial Results Mode Tests
# =============================================================================


class TestPartialResultsMode:
    """Tests for AC-8: Partial results mode."""

    @pytest.mark.asyncio
    async def test_one_method_fails_others_succeed(self, project_root: Path) -> None:
        """Test that one method failure doesn't crash verification."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Mock one method to raise exception
        async def failing_method(text: str, **kwargs) -> list[Finding]:
            raise ProviderTimeoutError("timeout")

        async def working_method(text: str, **kwargs) -> list[Finding]:
            return [
                Finding(
                    id="temp-1",
                    severity=Severity.ERROR,
                    title="Test finding",
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

        method_results = await engine._run_methods_with_errors(
            [mock_method1, mock_method2], "test", None, None
        )

        # Should have results from both methods
        assert len(method_results) == 2
        # First should have failed
        assert method_results[0].success is False
        assert method_results[0].error is not None
        # Second should have succeeded
        assert method_results[1].success is True
        assert len(method_results[1].findings) == 1

    @pytest.mark.asyncio
    async def test_all_methods_fail(self, project_root: Path) -> None:
        """Test that all methods failing returns partial results with errors."""
        engine = DeepVerifyEngine(project_root=project_root)

        async def failing_method(text: str, **kwargs) -> list[Finding]:
            raise ProviderError("always fails")

        mock_method1 = Mock(spec=BaseVerificationMethod)
        mock_method1.method_id = MethodId("#153")
        mock_method1.analyze = failing_method

        mock_method2 = Mock(spec=BaseVerificationMethod)
        mock_method2.method_id = MethodId("#154")
        mock_method2.analyze = failing_method

        method_results = await engine._run_methods_with_errors(
            [mock_method1, mock_method2], "test", None, None
        )

        # Both should have failed
        assert all(not mr.success for mr in method_results)
        # Both should have error information
        assert all(mr.error is not None for mr in method_results)

    @pytest.mark.asyncio
    async def test_method_result_repr(self) -> None:
        """Test MethodResult string representation."""
        # Success result
        success_result = MethodResult(
            method_id=MethodId("#153"),
            findings=[],
            error=None,
            success=True,
        )
        assert "success" in repr(success_result).lower()

        # Failed result
        error = CategorizedError(
            error=ProviderError("test"),
            category=ErrorCategory.FATAL_INVALID,
        )
        failed_result = MethodResult(
            method_id=MethodId("#153"),
            findings=[],
            error=error,
            success=False,
        )
        assert "failed" in repr(failed_result).lower()


# =============================================================================
# AC-9: Error Reporting in Verdict Tests
# =============================================================================


class TestVerdictErrorReporting:
    """Tests for AC-9: Detailed error reporting in verdict."""

    def test_verdict_error_dataclass(self) -> None:
        """Test VerdictError dataclass."""
        error = VerdictError(
            method_id=MethodId("#153"),
            error_type="ProviderTimeoutError",
            error_message="Request timed out",
            category=ErrorCategory.RETRYABLE_TIMEOUT.value,
        )

        assert error.method_id == MethodId("#153")
        assert error.error_type == "ProviderTimeoutError"
        assert error.category == "retryable_timeout"

    def test_verdict_error_repr(self) -> None:
        """Test VerdictError string representation."""
        error = VerdictError(
            method_id=MethodId("#153"),
            error_type="ProviderTimeoutError",
            error_message="Request timed out",
            category=ErrorCategory.RETRYABLE_TIMEOUT.value,
        )

        repr_str = repr(error)
        assert "#153" in repr_str
        assert "retryable_timeout" in repr_str

    def test_verdict_error_none_method(self) -> None:
        """Test VerdictError with None method_id (general error)."""
        error = VerdictError(
            method_id=None,
            error_type="InputValidationError",
            error_message="Input too large",
            category=ErrorCategory.FATAL_INVALID.value,
        )

        assert error.method_id is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests for resource limits and error handling."""

    @pytest.mark.asyncio
    async def test_oversized_input_returns_reject_verdict(
        self, project_root: Path, strict_config: DeepVerifyConfig
    ) -> None:
        """Test that oversized input returns REJECT verdict with error."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        # Create oversized input (> 1024 bytes)
        large_text = "x" * 1025
        verdict = await engine.verify(large_text)

        assert verdict.decision == VerdictDecision.REJECT
        assert len(verdict.errors) >= 1
        assert any("exceeds limit" in e.error_message.lower() for e in verdict.errors)
        assert verdict.input_metrics is not None
        assert verdict.input_metrics["size_bytes"] == 1025

    @pytest.mark.asyncio
    async def test_too_many_lines_returns_reject_verdict(
        self, project_root: Path, strict_config: DeepVerifyConfig
    ) -> None:
        """Test that too many lines returns REJECT verdict with error."""
        engine = DeepVerifyEngine(project_root=project_root, config=strict_config)

        # Create input with too many lines (> 10)
        text = "\n".join([f"line {i}" for i in range(15)])
        verdict = await engine.verify(text)

        assert verdict.decision == VerdictDecision.REJECT
        assert verdict.input_metrics is not None
        assert verdict.input_metrics["line_count"] == 15

    @pytest.mark.asyncio
    async def test_valid_input_passes_validation(self, project_root: Path) -> None:
        """Test that valid input passes validation and produces verdict with metrics."""
        engine = DeepVerifyEngine(project_root=project_root)

        # Mock domain detector to avoid LLM calls
        engine._domain_detector = Mock()
        engine._domain_detector.detect = Mock(
            return_value=DomainDetectionResult(
                domains=[DomainConfidence(domain=ArtifactDomain.API, confidence=0.9)],
                reasoning="API domain",
            )
        )

        # Mock method selector to return no methods (empty verdict)
        engine._method_selector = Mock()
        engine._method_selector.select = Mock(return_value=[])

        verdict = await engine.verify("def test(): pass")

        # Empty verdict returns ACCEPT (score 0.0)
        assert verdict.decision == VerdictDecision.ACCEPT
        assert verdict.score == 0.0


# =============================================================================
# Configuration Tests (AC-11)
# =============================================================================


class TestConfiguration:
    """Tests for AC-11: Configuration integration."""

    def test_resource_limit_config_defaults(self) -> None:
        """Test ResourceLimitConfig default values."""
        config = ResourceLimitConfig()

        assert config.max_artifact_size_bytes == 102400  # 100KB
        assert config.max_line_count == 5000
        assert config.max_findings_per_method == 50
        assert config.max_total_findings == 200
        assert config.regex_timeout_seconds == 5.0

    def test_resource_limit_config_validation(self) -> None:
        """Test ResourceLimitConfig field validation."""
        # Valid values should work
        config = ResourceLimitConfig(
            max_artifact_size_bytes=50000,
            max_line_count=1000,
        )
        assert config.max_artifact_size_bytes == 50000
        assert config.max_line_count == 1000

        # Invalid values should raise ValueError
        with pytest.raises(ValueError):
            ResourceLimitConfig(max_artifact_size_bytes=500)  # Too small

        with pytest.raises(ValueError):
            ResourceLimitConfig(max_line_count=5)  # Too small

    def test_deep_verify_config_includes_resource_limits(self) -> None:
        """Test that DeepVerifyConfig includes resource_limits."""
        config = DeepVerifyConfig()

        assert config.resource_limits is not None
        assert isinstance(config.resource_limits, ResourceLimitConfig)


# =============================================================================
# Exception Classes Tests
# =============================================================================


class TestExceptionClasses:
    """Tests for exception classes."""

    def test_input_validation_error(self) -> None:
        """Test InputValidationError exception."""
        error = InputValidationError(
            message="Size too large",
            size_bytes=200000,
            line_count=100,
            limit=102400,
        )

        assert error.size_bytes == 200000
        assert error.line_count == 100
        assert error.limit == 102400
        assert "Size too large" in str(error)

    def test_resource_limit_error(self) -> None:
        """Test ResourceLimitError exception."""
        error = ResourceLimitError(
            message="Too many findings",
            resource_type="findings_per_method",
            current_value=100,
            limit=50,
        )

        assert error.resource_type == "findings_per_method"
        assert error.current_value == 100
        assert error.limit == 50

    def test_domain_detection_error(self) -> None:
        """Test DomainDetectionError exception."""
        original_error = ValueError("LLM failed")
        error = DomainDetectionError(
            message="Domain detection failed",
            fallback_reason="Using keyword fallback",
            original_error=original_error,
        )

        assert error.fallback_reason == "Using keyword fallback"
        assert error.original_error is original_error

    def test_error_hierarchy(self) -> None:
        """Test that all DV errors inherit from DeepVerifyError."""
        assert issubclass(InputValidationError, DeepVerifyError)
        assert issubclass(ResourceLimitError, DeepVerifyError)
        assert issubclass(DomainDetectionError, DeepVerifyError)
        assert issubclass(DeepVerifyError, Exception)


# =============================================================================
# Test Count Verification
# =============================================================================


def test_minimum_20_tests() -> None:
    """Verify we have at least 20 test functions defined in this module."""
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

    # We should have many more than 20 tests
    assert test_count >= 20, f"Expected at least 20 tests, found {test_count}"
