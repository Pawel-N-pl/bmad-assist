"""Abstract base class and data structures for CLI provider implementations.

This module defines the contract that all CLI providers (Claude Code, Codex,
Gemini CLI) must implement. The BaseProvider ABC enables the adapter pattern
for extensible provider support per NFR7.

Providers only know how to invoke CLI tools and parse their output. They have
no knowledge of the main loop or state management.

Output Capture:
    All providers use subprocess.run() with capture_output=True to capture
    stdout and stderr as separate strings. Memory handling is delegated to
    subprocess.run() which uses internal buffering via communicate().

    Typical output sizes for LLM CLI tools:
    - Code reviews: ~10KB-100KB
    - Comprehensive analysis: ~100KB-1MB
    - Large outputs: ~1MB-10MB
    - Extreme edge cases: >10MB (rare, may be slow but will complete)

    No artificial truncation or streaming is implemented. Python's subprocess
    module handles memory allocation internally. For the bmad-assist use case,
    LLM outputs are bounded by context windows and rarely exceed 10MB.

Example:
    >>> from bmad_assist.providers import BaseProvider, ProviderResult
    >>> class ClaudeProvider(BaseProvider):
    ...     @property
    ...     def provider_name(self) -> str:
    ...         return "claude"
    ...
    ...     def invoke(self, prompt: str, *, model: str | None = None,
    ...                timeout: int | None = None,
    ...                settings_file: Path | None = None) -> ProviderResult:
    ...         # Implementation using subprocess.run()
    ...         ...

"""

from __future__ import annotations

import contextlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# Shared Output Locking for Concurrent Providers
# =============================================================================

# Lock for synchronized console output (prevents interleaved lines)
# Shared across ALL providers for proper coordination
_OUTPUT_LOCK = threading.Lock()

# Thread-local storage for active provider context
# Each thread has its own provider name to enable provider identification
# in write_progress() without passing it through call stack
_active_provider = threading.local()


def set_active_provider(name: str | None) -> None:
    """Set active provider for current thread.

    Used to track which provider is generating output, enabling proper
    provider identification in dashboard output streaming.

    Args:
        name: Provider name (e.g., "claude", "gemini", "glm") or None to clear.

    """
    _active_provider.name = name


def get_active_provider() -> str | None:
    """Get active provider for current thread.

    Returns:
        Provider name if set, None otherwise.

    """
    return getattr(_active_provider, "name", None)


# ANSI color codes for provider differentiation
# Colors chosen to NOT conflict with Rich logging colors:
#   - Avoid Cyan (36, 96) - used by Rich for DEBUG
#   - Avoid Yellow (33, 93) - used by Rich for WARNING
#   - Avoid Red (31, 91) - used by Rich for ERROR
PROVIDER_COLORS: tuple[str, ...] = (
    "\033[35m",  # Magenta
    "\033[32m",  # Green
    "\033[34m",  # Blue
    "\033[95m",  # Bright Magenta
    "\033[92m",  # Bright Green
    "\033[94m",  # Bright Blue
    "\033[37m",  # White
    "\033[97m",  # Bright White
)
RESET_COLOR = "\033[0m"

# =============================================================================
# Shared Retry Constants
# =============================================================================

# Maximum number of retry attempts for transient failures
MAX_RETRIES: int = 5

# Base delay in seconds for exponential backoff
RETRY_BASE_DELAY: float = 2.0

# Maximum delay between retries in seconds
RETRY_MAX_DELAY: float = 30.0


def format_tag(tag: str, color_index: int | None) -> str:
    """Format a tag like [ASSISTANT] with optional color.

    Args:
        tag: The tag text (e.g., "ASSISTANT", "TOOL Read").
        color_index: Index into PROVIDER_COLORS, or None for no color.

    Returns:
        Formatted tag string, colored if color_index provided.

    """
    if color_index is not None and color_index >= 0:
        color = PROVIDER_COLORS[color_index % len(PROVIDER_COLORS)]
        return f"{color}[{tag}]{RESET_COLOR}"
    return f"[{tag}]"


def write_progress(line: str) -> None:
    r"""Write a progress line to stdout with locking.

    Ensures lines are not interleaved when multiple providers run concurrently.
    All providers should use this function for console output.

    Uses print() instead of sys.stdout.write() to ensure proper line ending
    handling across platforms (especially WSL where \n alone may not reset
    the cursor position properly).

    Also calls the output hook (if registered) for dashboard SSE streaming.
    Hook is called OUTSIDE the lock to prevent potential deadlocks.

    Provider identification for the hook follows AC3 priority:
    1. Primary: Thread-local context via get_active_provider()
    2. Fallback: Regex detection via detect_provider_from_line()
    3. Default: None (generic bmad-assist output)

    Args:
        line: The line to write (newline will be added).

    """
    # Print inside lock to prevent interleaved output
    with _OUTPUT_LOCK:
        print(line, flush=True)

    # Call hook OUTSIDE lock to prevent deadlock
    # Import here to avoid circular import
    from bmad_assist.dashboard import get_output_hook

    hook = get_output_hook()
    if hook is not None:
        # Primary: thread-local context; Fallback: regex detection
        provider = get_active_provider()
        if provider is None:
            from bmad_assist.dashboard import detect_provider_from_line

            provider = detect_provider_from_line(line)
        # Fire-and-forget: suppress all errors from hook
        with contextlib.suppress(Exception):
            hook(line, provider)


# =============================================================================
# Shared Stream Reading Helpers
# =============================================================================


def read_stream_lines(
    stream: Any,
    chunks: list[str],
    print_lines: bool,
    color_idx: int | None,
    tag_prefix: str = "OUT",
) -> None:
    """Read lines from a stream into chunks, optionally printing progress.

    This is a shared helper for reading stdout/stderr from subprocess
    in a threaded manner. Used by subprocess-based providers.

    Args:
        stream: The stream to read from (process.stdout or process.stderr).
        chunks: List to accumulate lines into.
        print_lines: If True, print each line with write_progress().
        color_idx: Color index for terminal output differentiation.
        tag_prefix: Prefix for the progress tag (e.g., "OUT" or "ERR").

    """
    for line in iter(stream.readline, ""):
        chunks.append(line)
        if print_lines:
            stripped = line.rstrip()
            tag = format_tag(tag_prefix, color_idx)
            write_progress(f"{tag} {stripped}")
    stream.close()


def start_stream_reader_threads(
    process: Any,
    stdout_chunks: list[str],
    stderr_chunks: list[str],
    print_output: bool,
    color_index: int | None,
) -> tuple[threading.Thread, threading.Thread]:
    """Start threads for reading stdout and stderr concurrently.

    This is a shared helper for subprocess-based providers that need to
    read both streams simultaneously to avoid blocking.

    Args:
        process: The subprocess.Popen process with stdout/stderr pipes.
        stdout_chunks: List to accumulate stdout lines into.
        stderr_chunks: List to accumulate stderr lines into.
        print_output: If True, print lines with write_progress().
        color_index: Color index for terminal output differentiation.

    Returns:
        Tuple of (stdout_thread, stderr_thread) that have been started.
        Caller is responsible for joining the threads.

    """
    stdout_thread = threading.Thread(
        target=read_stream_lines,
        args=(process.stdout, stdout_chunks, print_output, color_index, "OUT"),
    )
    stderr_thread = threading.Thread(
        target=read_stream_lines,
        args=(process.stderr, stderr_chunks, print_output, color_index, "ERR"),
    )
    stdout_thread.start()
    stderr_thread.start()
    return stdout_thread, stderr_thread


# =============================================================================
# Shared Retry Helpers
# =============================================================================


def calculate_retry_delay(attempt: int) -> float:
    """Calculate exponential backoff delay for retry attempts.

    Args:
        attempt: Current retry attempt number (0-indexed).

    Returns:
        Delay in seconds using exponential backoff with jitter ceiling.

    """
    return min(RETRY_BASE_DELAY * (2**attempt), RETRY_MAX_DELAY)


def is_transient_error(
    stderr_content: str,
    exit_status: ExitStatus,
) -> bool:
    """Check if an error is transient and suitable for retry.

    Transient errors are those that may succeed on retry, such as
    temporary network issues or CLI internal errors.

    Args:
        stderr_content: The stderr output from the failed invocation.
        exit_status: The ExitStatus classification of the exit code.

    Returns:
        True if the error appears transient and retry is warranted.

    """
    # Empty stderr with ERROR status is often a transient CLI issue
    return not stderr_content.strip() and exit_status == ExitStatus.ERROR


def extract_tool_details(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extract human-readable details from tool input.

    Shared utility for formatting tool usage display across providers.
    Supports both Claude-style (file_path) and Gemini-style (path) parameters.

    Args:
        tool_name: Name of the tool (e.g., "Read", "Bash", "run_shell_command").
        tool_input: The input dict passed to the tool.

    Returns:
        Brief description of what the tool is doing, or empty string for unknown tools.

    """
    # Normalize tool names (Gemini uses run_shell_command, Claude uses Bash)
    normalized_name = tool_name
    if tool_name == "run_shell_command":
        normalized_name = "Bash"
    elif tool_name == "read_file":
        normalized_name = "Read"
    elif tool_name == "edit_file":
        normalized_name = "Edit"
    elif tool_name == "write_file":
        normalized_name = "Write"
    elif tool_name == "list_directory" or tool_name == "glob":
        normalized_name = "Glob"
    elif tool_name == "grep" or tool_name == "search_file_content":
        normalized_name = "Grep"

    if normalized_name in ("Read", "Edit", "Write"):
        # Support Claude "file_path", Gemini "path", and GLM "file_id"
        file_path: str = str(
            tool_input.get("file_path") or tool_input.get("path") or tool_input.get("file_id", "?")
        )
        # Make path relative if possible (strip common prefixes)
        if "/" in file_path:
            # Show last 3 path components for context
            parts = file_path.split("/")
            if len(parts) > 3:
                file_path = ".../" + "/".join(parts[-3:])
        if normalized_name == "Edit":
            old_str: str = str(tool_input.get("old_string", ""))
            preview = old_str[:40].replace("\n", "\\n")
            if len(old_str) > 40:
                preview += "..."
            return f"{file_path} :: {preview}"
        return file_path

    elif normalized_name == "Bash":
        # Support Claude "command" and GLM "args"
        command: str = str(tool_input.get("command") or tool_input.get("args", "?"))
        preview = command[:60].replace("\n", " ")
        if len(command) > 60:
            preview += "..."
        return preview

    elif normalized_name == "TodoWrite":
        todos = tool_input.get("todos", [])
        if todos and isinstance(todos, list):
            todo_item = todos[0]
            if isinstance(todo_item, dict):
                first_todo = todo_item.get("content", "?")
            else:
                first_todo = str(todo_item)
            preview = first_todo[:40]
            if len(first_todo) > 40:
                preview += "..."
            return f"{len(todos)} items: {preview}"
        return f"{len(todos)} items"

    elif normalized_name == "Grep":
        pattern = tool_input.get("pattern", "?")
        path = tool_input.get("path", ".")
        return f"'{pattern}' in {path}"

    elif normalized_name == "Glob":
        # Claude uses "pattern", Gemini list_directory uses "path"
        pattern = tool_input.get("pattern") or tool_input.get("path", "?")
        return f"'{pattern}'"

    elif tool_name == "WebFetch":
        url: str = str(tool_input.get("url", "?"))
        return url[:60] + ("..." if len(url) > 60 else "")

    elif tool_name == "WebSearch":
        query = tool_input.get("query", "?")
        return f"'{query}'"

    return ""


class ExitStatus(Enum):
    """Semantic classification of process exit codes.

    Follows Unix conventions for exit code interpretation:
    - 0: Success
    - 1-125: Error codes (1=general, 2=misuse)
    - 126: Cannot execute (permission denied)
    - 127: Command not found
    - 128: Invalid exit argument
    - 128+N: Killed by signal N (e.g., 137=SIGKILL, 143=SIGTERM)

    Example:
        >>> status = ExitStatus.from_code(137)
        >>> status
        <ExitStatus.SIGNAL: 7>
        >>> ExitStatus.get_signal_number(137)
        9

    """

    SUCCESS = auto()  # Exit code 0
    ERROR = auto()  # Exit codes 1, 3-125 (general error)
    MISUSE = auto()  # Exit code 2 (incorrect usage)
    CANNOT_EXECUTE = auto()  # Exit code 126 (permission denied)
    NOT_FOUND = auto()  # Exit code 127 (command not found)
    INVALID_EXIT = auto()  # Exit code 128 (invalid exit argument)
    SIGNAL = auto()  # Exit codes 129+ (killed by signal)

    @classmethod
    def from_code(cls, exit_code: int) -> ExitStatus:
        """Classify exit code into semantic status.

        Args:
            exit_code: Process exit code to classify.

        Returns:
            ExitStatus enum value corresponding to the exit code.

        """
        if exit_code == 0:
            return cls.SUCCESS
        if exit_code == 2:
            return cls.MISUSE
        if exit_code == 126:
            return cls.CANNOT_EXECUTE
        if exit_code == 127:
            return cls.NOT_FOUND
        if exit_code == 128:
            return cls.INVALID_EXIT
        if exit_code > 128:
            return cls.SIGNAL
        return cls.ERROR

    @staticmethod
    def get_signal_number(exit_code: int) -> int | None:
        """Extract signal number from exit code.

        Args:
            exit_code: Process exit code (should be >128 for signal).

        Returns:
            Signal number if exit_code > 128, None otherwise.

        """
        if exit_code > 128:
            return exit_code - 128
        return None


def resolve_settings_file(
    settings_path: str | None,
    base_dir: Path,
) -> Path | None:
    """Resolve settings file path from configuration.

    Resolves relative paths against base_dir, expands tilde (~),
    and converts to absolute Path object. Does NOT validate file existence.

    Args:
        settings_path: Settings file path from config, or None.
        base_dir: Base directory for relative path resolution (typically project root).

    Returns:
        Resolved Path object if settings_path is not None, None otherwise.
        Does NOT validate file existence - caller is responsible for validation.

    Example:
        >>> resolve_settings_file("./provider-configs/master.json", Path("/project"))
        PosixPath('/project/provider-configs/master.json')
        >>> resolve_settings_file("~/custom.json", Path("/project"))
        PosixPath('/home/user/custom.json')
        >>> resolve_settings_file(None, Path("/project"))
        None
        >>> resolve_settings_file("/absolute/path.json", Path("/project"))
        PosixPath('/absolute/path.json')

    """
    if settings_path is None:
        return None

    path = Path(settings_path).expanduser()

    if not path.is_absolute():
        path = base_dir / path

    return path.resolve()


def validate_settings_file(
    settings_file: Path | None,
    provider_name: str,
    model: str,
) -> Path | None:
    """Validate settings file existence, logging warning if missing.

    Validates that the settings file exists and is a regular file.
    If the file is missing or is a directory, logs a warning with context
    and returns None (graceful degradation, not an error).

    Args:
        settings_file: Resolved settings file path from resolve_settings_file(),
            or None if no settings configured.
        provider_name: Name of provider (for logging context).
        model: Model identifier (for logging context).

    Returns:
        settings_file if it exists and is a file, None otherwise.
        Does NOT raise exceptions for missing files.

    Example:
        >>> validate_settings_file(Path("/exists.json"), "claude", "opus")
        PosixPath('/exists.json')
        >>> validate_settings_file(Path("/missing.json"), "claude", "opus")
        None  # Also logs warning

    """
    if settings_file is None:
        return None

    if not settings_file.exists():
        logger.warning(
            "Settings file not found, using defaults: path=%s, provider=%s, model=%s",
            settings_file,
            provider_name,
            model,
        )
        return None

    if not settings_file.is_file():
        logger.warning(
            "Settings path is not a file, using defaults: path=%s, provider=%s, model=%s",
            settings_file,
            provider_name,
            model,
        )
        return None

    return settings_file


@dataclass(frozen=True)
class ProviderResult:
    """Result of a CLI provider invocation.

    Captures all output from subprocess execution for processing
    by parse_output() and error handling.

    This is an immutable dataclass (frozen=True) representing the
    complete output from a single CLI invocation.

    Attributes:
        stdout: Captured standard output from CLI.
        stderr: Captured standard error from CLI.
        exit_code: Process exit code (0 = success).
        duration_ms: Execution time in milliseconds.
        model: Model identifier used (if applicable).
        command: Actual command executed as immutable tuple (for debugging).
        provider_session_id: Session/thread ID from provider (for traceability).
            Claude: session_id from init message.
            Codex: thread_id from thread.started message.
            Gemini: session_id from init message.

    Example:
        >>> result = ProviderResult(
        ...     stdout="Response text here",
        ...     stderr="",
        ...     exit_code=0,
        ...     duration_ms=1500,
        ...     model="opus_4",
        ...     command=("claude", "-p", "prompt text"),
        ...     provider_session_id="session-abc123"
        ... )
        >>> result.exit_code
        0

    """

    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    model: str | None
    command: tuple[str, ...]
    provider_session_id: str | None = None


class BaseProvider(ABC):
    """Abstract base class for CLI provider implementations.

    Defines the contract that all CLI providers (Claude Code, Codex,
    Gemini CLI) must implement. Enables the adapter pattern for
    extensible provider support.

    Concrete implementations must override:
        - provider_name: Unique identifier for this provider
        - invoke(): Execute CLI and capture output
        - parse_output(): Extract response from CLI output
        - supports_model(): Check model compatibility

    Optionally override:
        - default_model: Default model when none specified

    Example:
        >>> class ClaudeProvider(BaseProvider):
        ...     @property
        ...     def provider_name(self) -> str:
        ...         return "claude"
        ...
        ...     @property
        ...     def default_model(self) -> str | None:
        ...         return "sonnet_4"
        ...
        ...     def invoke(self, prompt: str, *, model: str | None = None,
        ...                timeout: int | None = None,
        ...                settings_file: Path | None = None) -> ProviderResult:
        ...         # Implementation
        ...         ...
        ...
        ...     def parse_output(self, result: ProviderResult) -> str:
        ...         return result.stdout
        ...
        ...     def supports_model(self, model: str) -> bool:
        ...         return model in ["opus_4", "sonnet_4", "haiku_4"]

    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this provider (e.g., 'claude', 'codex', 'gemini')."""
        ...

    @property
    def default_model(self) -> str | None:
        """Default model to use if none specified in invoke().

        Returns:
            Default model identifier, or None if no default.

        """
        return None

    @abstractmethod
    def invoke(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
        cwd: Path | None = None,
        disable_tools: bool = False,
        allowed_tools: list[str] | None = None,
        no_cache: bool = False,
        color_index: int | None = None,
    ) -> ProviderResult:
        """Execute LLM provider with the given prompt.

        Invokes the provider's backend (subprocess CLI or native SDK) with
        the specified prompt and optional configuration. Implementations
        may use subprocess.run() or native SDK calls as appropriate.

        Args:
            prompt: The prompt text to send to the LLM.
            model: Model identifier to use. If None, uses default_model.
            timeout: Timeout in seconds. If None, uses default from config.
            settings_file: Path to provider settings JSON file.
            disable_tools: If True, disables all tools. Not all providers
                support this; implementations should ignore if unsupported.
            allowed_tools: List of tool names to allow (e.g., ["TodoWrite"]).
                Mutually exclusive with disable_tools. When set, only specified
                tools are available. Not all providers support this.
            cwd: Working directory for the provider process. If None, uses
                current directory.
            no_cache: If True, disables prompt caching. Useful for one-shot
                prompts where caching overhead is wasteful.
            color_index: Index for console output color (0-7). Used for visual
                distinction when multiple providers run concurrently. Not all
                providers support this; implementations should ignore if unsupported.

        Returns:
            ProviderResult containing stdout, stderr, exit code, and timing.

        Raises:
            ProviderError: If execution fails due to:
                - Timeout exceeded
                - Non-zero exit code or SDK error
                - Provider executable/SDK not found
                - Permission denied
            ProviderTimeoutError: If invocation exceeds timeout.

        Note:
            Implementations must:
            - Enforce explicit timeout (via subprocess or asyncio.wait_for)
            - Never use shell=True for subprocess implementations (security)
            - Record execution duration in milliseconds
            - Raise ProviderError subclasses on failure, not raw exceptions

        """
        ...

    @abstractmethod
    def parse_output(self, result: ProviderResult) -> str:
        """Extract the response text from CLI output.

        Provider-specific parsing logic to extract the actual LLM response
        from the CLI stdout. Different CLIs have different output formats:
        - Claude Code: Returns plain text (with --print flag)
        - Codex: Returns plain text
        - Gemini CLI: Returns formatted text

        Args:
            result: ProviderResult from invoke() containing raw output.

        Returns:
            Extracted response text from the CLI output.

        Note:
            This method should handle provider-specific output formats
            and return clean, usable response text. It does not raise
            exceptions - parsing failures should return empty string
            or the raw stdout.

        """
        ...

    @abstractmethod
    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Args:
            model: Model identifier to check (e.g., 'opus_4', 'sonnet_4').

        Returns:
            True if provider supports the model, False otherwise.

        Example:
            >>> provider = ClaudeProvider()
            >>> provider.supports_model("opus_4")
            True
            >>> provider.supports_model("gpt-4")
            False

        """
        ...
