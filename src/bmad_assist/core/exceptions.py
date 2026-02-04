"""Custom exception hierarchy for bmad-assist.

All custom exceptions inherit from BmadAssistError to enable:
- Unified exception handling
- Clear distinction from built-in exceptions
- Consistent error messaging patterns
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bmad_assist.providers.base import ExitStatus, ProviderResult

__all__ = [
    "BmadAssistError",
    "CancelledError",
    "ConfigError",
    "ConfigValidationError",
    "ParserError",
    "ReconciliationError",
    "StateError",
    "ProviderError",
    "ProviderTimeoutError",
    "CompilerError",
    "TokenBudgetError",
    "PatchError",
    "AmbiguousFileError",
    "VariableError",
    "PreflightError",
    "ProviderExitCodeError",
    "QuotaExhaustedError",
    "ContextError",
    "DashboardError",
    "IsolationError",
    "ManifestError",
    "EvidenceError",
    "PatternError",
    "PatternLibraryError",
    "PatternMatchError",
    "PatternNotFoundError",
]


class BmadAssistError(Exception):
    """Base exception for all bmad-assist errors.

    All custom exceptions in bmad-assist should inherit from this class
    to enable unified exception handling and clear error boundaries.
    """

    pass


class CancelledError(BmadAssistError):
    """Raised when operation is cancelled via CancellationContext.

    This is NOT asyncio.CancelledError - it's for sync cancellation via
    threading.Event in the LoopController/provider integration.

    Used at safe checkpoints in run_loop() when the cancel token is set,
    allowing the loop to exit gracefully with state preserved.
    """

    pass


class ConfigError(BmadAssistError):
    """Configuration loading or validation error.

    Raised when:
    - Configuration has not been loaded before access
    - Configuration data is not a valid dictionary
    - Configuration validation fails (note: Pydantic raises ValidationError)
    """

    pass


class ConfigValidationError(ConfigError):
    """Validation error with structured Pydantic details.

    Raised when Pydantic validation fails with detailed error information.
    Provides structured access to validation errors for API responses.

    Attributes:
        errors: List of error dicts with 'loc', 'msg', and 'type' fields.
            - loc: Tuple of field path components (e.g., ('testarch', 'playwright', 'timeout'))
            - msg: Human-readable error message
            - type: Pydantic error type code (e.g., 'greater_than_equal')

    Example:
        >>> try:
        ...     editor.validate()
        ... except ConfigValidationError as e:
        ...     for err in e.errors:
        ...         path = ".".join(str(x) for x in err["loc"])
        ...         print(f"{path}: {err['msg']}")

    """

    def __init__(self, message: str, errors: list[dict[str, Any]]) -> None:
        """Initialize ConfigValidationError with message and structured errors.

        Args:
            message: Human-readable error message.
            errors: List of error dicts from Pydantic ValidationError.
                Each dict has 'loc' (tuple), 'msg' (str), and 'type' (str).

        """
        super().__init__(message)
        self.errors = errors


class ParserError(BmadAssistError):
    """BMAD file parsing error.

    Raised when:
    - YAML frontmatter is malformed
    - File encoding issues occur
    - Unexpected parsing failures
    """

    pass


class ReconciliationError(BmadAssistError):
    """State reconciliation or correction error.

    Raised when:
    - Required callback is missing for correction
    - Invalid correction options are provided
    """

    pass


class StateError(BmadAssistError):
    """State persistence or recovery error.

    Raised when:
    - State file cannot be written (permissions, disk full)
    - State file cannot be read (corrupted, missing)
    - Atomic write operation fails
    """

    pass


class ProviderError(BmadAssistError):
    """CLI provider execution error.

    Raised when:
    - CLI execution times out
    - CLI returns non-zero exit code
    - CLI executable not found (FileNotFoundError)
    - Permission denied executing CLI
    """

    pass


class ProviderTimeoutError(ProviderError):
    """CLI provider timeout error with optional partial output.

    Raised when a CLI invocation exceeds the configured timeout.
    May contain partial output captured before the timeout occurred.

    This is a specialized subclass of ProviderError that allows:
    - Selective catching of timeout errors vs other provider errors
    - Access to partial output captured before timeout
    - Guardian analysis of timeout-specific anomalies
    - Future retry logic to treat timeouts differently

    Attributes:
        partial_result: Partial ProviderResult if output was captured
            before timeout, or None if no output was available.
            When present, partial_result.stdout and partial_result.stderr
            are always strings (never None).

    Example:
        >>> try:
        ...     result = provider.invoke("prompt", timeout=5)
        ... except ProviderTimeoutError as e:
        ...     if e.partial_result:
        ...         print(f"Partial output: {e.partial_result.stdout[:100]}")

    """

    def __init__(
        self,
        message: str,
        partial_result: "ProviderResult | None" = None,
    ) -> None:
        """Initialize ProviderTimeoutError with message and optional partial result.

        Args:
            message: Error message describing the timeout.
            partial_result: Optional ProviderResult containing partial output
                captured before the timeout occurred.

        """
        super().__init__(message)
        self.partial_result = partial_result


class QuotaExhaustedError(ProviderError):
    """Provider quota exhausted error (non-retryable, triggers fallback).

    Raised when a provider's API returns quota/rate limit exhaustion errors
    that are persistent (not transient). Unlike transient rate limits that
    resolve with retry, quota exhaustion means the model is unavailable
    for the remainder of the phase.

    Used by orchestrators to trigger fallback to alternative models on
    the same provider (e.g., gemini-3-pro -> gemini-2.5-flash).

    Attributes:
        provider_name: Name of the provider that hit quota (e.g., "gemini").
        model: Model that was quota-exhausted (e.g., "gemini-3-pro-preview").
        stderr: Raw stderr content from the CLI for debugging.

    """

    def __init__(
        self,
        message: str,
        provider_name: str = "",
        model: str = "",
        stderr: str = "",
    ) -> None:
        """Initialize QuotaExhaustedError with context.

        Args:
            message: Human-readable error message.
            provider_name: Name of the provider that hit quota.
            model: Model that was quota-exhausted.
            stderr: Raw stderr content from the CLI.

        """
        super().__init__(message)
        self.provider_name = provider_name
        self.model = model
        self.stderr = stderr


class CompilerError(BmadAssistError):
    """BMAD workflow compilation error.

    Raised when:
    - Workflow module doesn't exist (includes attempted import path)
    - Workflow module has syntax/import errors (includes error details)
    - Workflow name is empty or contains only whitespace
    - Context validation fails during compilation
    """

    pass


class TokenBudgetError(CompilerError):
    """Token budget exceeded during compilation.

    Raised when:
    - Compiled prompt token count exceeds configured hard limit
    - Hard limit defaults to 20,000 tokens (per NFR10)
    - Custom limit can be set via --max-tokens CLI flag
    """

    pass


class ContextError(CompilerError):
    """Context building error during BMAD workflow compilation.

    Raised when:
    - Required context file is missing (e.g., project_context.md with required=True)
    - Context file cannot be read (permissions, encoding issues)
    - Path resolution fails for context file

    Used by ContextBuilder to signal missing required files during context assembly.
    Optional files that are missing will log warnings instead of raising this error.
    """

    pass


class PatchError(CompilerError):
    """Workflow patch compilation error.

    Raised when:
    - Patch file has malformed YAML (includes line number if available)
    - Master provider is not configured for patch compilation
    - LLM transform fails after retries (missing workflow tag, timeout)
    - Validation fails after retries (must_contain/must_not_contain)
    - Success threshold not met (< 75% transforms succeeded)
    - Cache directory is not writable
    """

    pass


class AmbiguousFileError(BmadAssistError):
    """Ambiguous file match in BMAD workflow compilation.

    Raised when:
    - Multiple files match a pattern with SELECTIVE_LOAD strategy
    - User must specify which file to use

    Attributes:
        pattern_name: Name of the pattern that matched multiple files (e.g., 'epics').
        candidates: List of file paths that matched.
        suggestion: Actionable suggestion for resolving the ambiguity.

    Example:
        >>> raise AmbiguousFileError(
        ...     "Multiple files match pattern 'epics' with SELECTIVE_LOAD strategy",
        ...     pattern_name="epics",
        ...     candidates=[Path("/docs/epics.md"), Path("/docs/epics-old.md")],
        ...     suggestion="Specify exact file via --epics-file flag"
        ... )

    """

    def __init__(
        self,
        message: str,
        pattern_name: str = "",
        candidates: list["Path"] | None = None,
        suggestion: str = "",
    ) -> None:
        """Initialize AmbiguousFileError with context.

        Args:
            message: Human-readable error message.
            pattern_name: Name of the pattern that matched multiple files.
            candidates: List of file paths that matched.
            suggestion: Actionable suggestion for resolving the ambiguity.

        """
        super().__init__(message)
        self.pattern_name = pattern_name
        self.candidates = candidates or []
        self.suggestion = suggestion


class VariableError(BmadAssistError):
    """Variable resolution error in BMAD workflow compilation.

    Raised when:
    - Required variable cannot be resolved from any source
    - Config source file does not exist
    - Config source file exists but requested key is missing
    - Circular variable reference detected
    - Path traversal attempted in config source path
    - Maximum recursion depth exceeded during resolution

    Attributes:
        variable_name: Name of the variable that failed to resolve.
        sources_checked: List of sources that were checked (e.g., ['invocation params', 'config']).
        suggestion: Actionable suggestion for fixing the error.

    Example:
        >>> raise VariableError(
        ...     "Cannot resolve variable 'epic_num'",
        ...     variable_name="epic_num",
        ...     sources_checked=["invocation params", "config values"],
        ...     suggestion="Provide --epic flag or ensure sprint-status.yaml has backlog story"
        ... )

    """

    def __init__(
        self,
        message: str,
        variable_name: str = "",
        sources_checked: list[str] | None = None,
        suggestion: str = "",
    ) -> None:
        """Initialize VariableError with context.

        Args:
            message: Human-readable error message.
            variable_name: Name of the variable that failed to resolve.
            sources_checked: List of sources that were checked.
            suggestion: Actionable suggestion for fixing the error.

        """
        super().__init__(message)
        self.variable_name = variable_name
        self.sources_checked = sources_checked or []
        self.suggestion = suggestion


class PreflightError(BmadAssistError):
    """Error during preflight infrastructure checks.

    Raised when:
    - Project root does not exist
    - Project root is not a directory
    - Other preflight check failures

    """

    pass


class ProviderExitCodeError(ProviderError):
    """CLI provider exit code error with semantic classification.

    Raised when a CLI invocation returns a non-zero exit code.
    Contains rich context for error handling and debugging.

    This is a specialized subclass of ProviderError that allows:
    - Selective catching of exit code errors vs other provider errors
    - Access to semantic classification via ExitStatus enum
    - Rich context including stderr, command, and exit code
    - Guardian analysis of exit-code-specific anomalies

    Attributes:
        exit_code: The actual process exit code.
        exit_status: Semantic classification (ExitStatus enum).
        stderr: Captured stderr content (empty string if none).
        stdout: Captured stdout content (empty string if none).
        command: Executed command as tuple of strings.

    Example:
        >>> try:
        ...     result = provider.invoke("prompt")
        ... except ProviderExitCodeError as e:
        ...     if e.exit_status == ExitStatus.NOT_FOUND:
        ...         print("Command not found - check PATH")
        ...     print(f"Exit code: {e.exit_code}, stderr: {e.stderr}")

    """

    def __init__(
        self,
        message: str,
        exit_code: int,
        exit_status: "ExitStatus",
        stderr: str = "",
        stdout: str = "",
        command: tuple[str, ...] = (),
    ) -> None:
        """Initialize ProviderExitCodeError with context.

        Args:
            message: Human-readable error message.
            exit_code: The actual process exit code.
            exit_status: Semantic classification of the exit code.
            stderr: Captured stderr content.
            stdout: Captured stdout content (preserved even on failure).
            command: Executed command as tuple.

        """
        super().__init__(message)
        self.exit_code = exit_code
        self.exit_status = exit_status
        self.stderr = stderr
        self.stdout = stdout
        self.command = command


class DashboardError(BmadAssistError):
    """Dashboard server error.

    Raised when:
    - No available port found after max attempts
    - Dashboard server configuration fails
    """

    pass


class IsolationError(BmadAssistError):
    """Error during fixture isolation operation.

    Raised when:
    - Copy operation fails (disk full, permissions, etc.)
    - Verification fails (file count/size mismatch)
    - Timeout exceeded during copy
    - Fixture contains no copyable files after skip patterns

    Attributes:
        source_path: Source fixture path (optional).
        snapshot_path: Target snapshot path (optional).

    Example:
        >>> try:
        ...     result = isolator.isolate(fixture_path, "run-001")
        ... except IsolationError as e:
        ...     print(f"Isolation failed: {e}")
        ...     if e.source_path:
        ...         print(f"  Source: {e.source_path}")
        ...     if e.snapshot_path:
        ...         print(f"  Snapshot: {e.snapshot_path}")

    """

    def __init__(
        self,
        message: str,
        source_path: "Path | None" = None,
        snapshot_path: "Path | None" = None,
    ) -> None:
        """Initialize IsolationError with message and optional context.

        Args:
            message: Human-readable error message.
            source_path: Source fixture path (optional).
            snapshot_path: Target snapshot path (optional).

        """
        super().__init__(message)
        self.source_path = source_path
        self.snapshot_path = snapshot_path


class ManifestError(BmadAssistError):
    """Error during manifest operation.

    Raised when:
    - Attempting to modify a finalized manifest
    - Invalid status transitions
    - Save operations fail
    - Manifest not found or invalid

    Attributes:
        run_id: Run identifier for context.

    Example:
        >>> try:
        ...     manager.add_phase_result(result)
        ... except ManifestError as e:
        ...     print(f"Manifest error: {e}")
        ...     if e.run_id:
        ...         print(f"  Run ID: {e.run_id}")

    """

    def __init__(self, message: str, run_id: str | None = None) -> None:
        """Initialize ManifestError with message and optional run ID.

        Args:
            message: Human-readable error message.
            run_id: Run identifier for context.

        """
        super().__init__(message)
        self.run_id = run_id


class EvidenceError(BmadAssistError):
    """Evidence collection or parsing error.

    Raised when:
    - Evidence file cannot be parsed
    - Evidence command execution fails critically
    - Other evidence collection failures that should stop processing

    Note: Most evidence collection failures are handled gracefully
    (return None, log warning). This exception is for critical failures.

    """

    pass


class PatternError(BmadAssistError):
    """Base exception for Deep Verify pattern module.

    Raised when:
    - Pattern validation fails
    - Pattern matching encounters errors
    - Pattern library operations fail
    """

    pass


class PatternLibraryError(PatternError):
    """Error loading or validating pattern library.

    Raised when:
    - Pattern YAML file has invalid structure
    - Pattern ID format is invalid
    - Required pattern fields are missing
    - Regex pattern has syntax errors
    - Domain or severity enum values are invalid

    Attributes:
        file_path: Path to the file that caused the error (if applicable).
        pattern_id: ID of the pattern that caused the error (if applicable).

    """

    def __init__(
        self,
        message: str,
        file_path: "Path | None" = None,
        pattern_id: str | None = None,
    ) -> None:
        """Initialize PatternLibraryError with context.

        Args:
            message: Human-readable error message.
            file_path: Path to the file that caused the error.
            pattern_id: ID of the pattern that caused the error.

        """
        super().__init__(message)
        self.file_path = file_path
        self.pattern_id = pattern_id


class PatternMatchError(PatternError):
    """Error during pattern matching.

    Raised when:
    - Signal matching fails due to invalid regex
    - Text analysis encounters unexpected errors
    """

    pass


class PatternNotFoundError(PatternError):
    """Pattern ID not found in library.

    Raised when:
    - Requested pattern ID does not exist in the library
    - Pattern lookup with raise_on_missing=True fails

    Attributes:
        pattern_id: The pattern ID that was not found.

    """

    def __init__(self, message: str, pattern_id: str | None = None) -> None:
        """Initialize PatternNotFoundError with context.

        Args:
            message: Human-readable error message.
            pattern_id: The pattern ID that was not found.

        """
        super().__init__(message)
        self.pattern_id = pattern_id
