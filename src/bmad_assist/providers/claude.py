"""Claude Code CLI subprocess-based provider implementation.

This module implements the ClaudeSubprocessProvider class that adapts Claude Code CLI
for use within bmad-assist via subprocess invocation. This provider is retained for
benchmarking and comparison purposes where fair subprocess-based comparison with
Codex and Gemini providers is required.

For the primary Claude integration, use ClaudeSDKProvider (claude_sdk.py) which
provides native async support, typed messages, and proper SDK error handling.

Example:
    >>> from bmad_assist.providers import ClaudeSubprocessProvider
    >>> provider = ClaudeSubprocessProvider()
    >>> result = provider.invoke("What is 2+2?", model="sonnet")
    >>> response = provider.parse_output(result)

"""

import contextlib
import json
import logging
import os
import signal
import threading
import time
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Any

from bmad_assist.core.debug_logger import DebugJsonLogger
from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderExitCodeError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    IS_WINDOWS,
    BaseProvider,
    ExitStatus,
    ProviderResult,
    extract_tool_details,
    format_tag,
    get_popen_kwargs_for_new_session,
    is_full_stream,
    register_child_pgid,
    register_child_process,
    should_print_progress,
    unregister_child_pgid,
    unregister_child_process,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# Supported short model names accepted by Claude Code CLI
SUPPORTED_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# Maximum prompt length in error messages before truncation
PROMPT_TRUNCATE_LENGTH: int = 100

# Maximum stderr length in error messages before truncation (AC2)
STDERR_TRUNCATE_LENGTH: int = 200

# =============================================================================
# Concurrent Output Formatting
# =============================================================================


def _truncate_prompt(prompt: str) -> str:
    """Truncate prompt for error messages.

    Args:
        prompt: The original prompt text.

    Returns:
        Original prompt if <= PROMPT_TRUNCATE_LENGTH chars,
        otherwise first PROMPT_TRUNCATE_LENGTH chars + "..."

    """
    if len(prompt) <= PROMPT_TRUNCATE_LENGTH:
        return prompt
    return prompt[:PROMPT_TRUNCATE_LENGTH] + "..."


class ClaudeSubprocessProvider(BaseProvider):
    """Claude Code CLI subprocess-based provider implementation.

    Adapts Claude Code CLI for use within bmad-assist via subprocess invocation.
    This provider is retained for benchmarking and fair comparison with Codex
    and Gemini providers which only have subprocess interfaces.

    For the primary Claude integration with native async support and typed
    messages, use ClaudeSDKProvider (claude_sdk.py) instead.

    Claude Code supports these models:
        - opus: Most capable model
        - sonnet: Balanced model (default)
        - haiku: Fastest model
        - Any full identifier starting with "claude-"

    Settings File Handling:
        When settings_file is provided to invoke(), it is validated for
        existence before CLI execution. If the file is missing or is not
        a regular file, a warning is logged and --settings flag is omitted
        (graceful degradation). This ensures the CLI uses defaults rather
        than failing on missing settings files.

    Cancel Support:
        This provider supports mid-invocation cancellation via cancel_token.
        When cancel_token.is_set() becomes True, the subprocess is terminated
        using SIGTERM with escalation to SIGKILL after 3 seconds.

    Example:
        >>> provider = ClaudeSubprocessProvider()
        >>> result = provider.invoke("Hello", model="opus", timeout=60)
        >>> print(provider.parse_output(result))

    """

    def __init__(self) -> None:
        """Initialize provider with no active process."""
        self._current_process: Popen[str] | None = None
        self._process_lock = threading.Lock()

    def _terminate_process(self, process: Popen[str]) -> None:
        """Terminate process with SIGTERM→SIGKILL escalation.

        Uses process groups for clean termination of child processes.
        First sends SIGTERM, waits up to 3 seconds, then escalates to SIGKILL.

        Args:
            process: The Popen process to terminate.

        """
        if process.poll() is not None:
            return  # Already exited

        try:
            pgid = os.getpgid(process.pid)
        except (ProcessLookupError, OSError):
            return  # Process already gone

        logger.info("Terminating process group %d (SIGTERM)", pgid)

        # Phase 1: SIGTERM to process group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            return  # Process already gone

        # Wait up to 3 seconds for graceful exit
        try:
            process.wait(timeout=3)
            logger.debug("Process terminated gracefully")
            return
        except TimeoutExpired:
            pass

        # Phase 2: SIGKILL if still running
        logger.warning("Process did not terminate, escalating to SIGKILL")
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(pgid, signal.SIGKILL)

    def cancel(self) -> None:
        """Cancel current operation by terminating subprocess.

        Thread-safe: Can be called from any thread while invoke() runs.
        Uses SIGTERM→SIGKILL escalation for clean termination.
        """
        with self._process_lock:
            if self._current_process is not None:
                logger.info("Cancelling Claude subprocess")
                self._terminate_process(self._current_process)

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "claude-subprocess" as the provider identifier.

        """
        return "claude-subprocess"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "sonnet" as the balanced default choice.

        """
        return "sonnet"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Validates both short model names (opus, sonnet, haiku) and
        full Claude model identifiers (strings starting with "claude-").

        Args:
            model: Model identifier to check.

        Returns:
            True if provider supports the model, False otherwise.

        Example:
            >>> provider = ClaudeProvider()
            >>> provider.supports_model("sonnet")
            True
            >>> provider.supports_model("claude-3-5-sonnet-20241022")
            True
            >>> provider.supports_model("gpt-4")
            False

        """
        return model in SUPPORTED_MODELS or model.startswith("claude-")

    def _resolve_settings(
        self,
        settings_file: Path | None,
        model: str,
    ) -> Path | None:
        """Resolve and validate settings file for invocation.

        Internal helper that validates settings file existence and logs
        a warning if missing. Called after model validation, before
        command building.

        Args:
            settings_file: Settings file path from caller, or None.
            model: Model identifier for logging context.

        Returns:
            Validated settings file Path if exists and is a file,
            None otherwise (triggers graceful degradation to defaults).

        """
        if settings_file is None:
            return None

        return validate_settings_file(
            settings_file=settings_file,
            provider_name=self.provider_name,
            model=model,
        )

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
        display_model: str | None = None,
        thinking: bool | None = None,
        cancel_token: threading.Event | None = None,
        reasoning_effort: str | None = None,
    ) -> ProviderResult:
        """Execute Claude Code CLI with the given prompt.

        Invokes Claude Code CLI via Popen with streaming output capture.

        Output Encoding:
            Uses explicit encoding='utf-8' and errors='replace' for consistent
            cross-platform behavior. Invalid UTF-8 bytes are replaced with the
            Unicode replacement character (U+FFFD) rather than raising errors.
            Replacement characters are logged at DEBUG level when detected.

        Output Size:
            No artificial truncation is applied. Outputs are streamed line by
            line for immediate collection. Typical LLM CLI outputs are <10MB.

        Settings File Validation:
            The settings_file path is validated for existence before CLI
            execution using validate_settings_file(). If the file is missing
            or is a directory (not a regular file), a warning is logged with
            provider and model context, and --settings flag is omitted from
            the CLI command (graceful degradation to defaults per AC2-AC4).

        Args:
            prompt: The prompt text to send to Claude.
            model: Model to use (opus, sonnet, haiku, or claude-* identifier).
                If None, uses default_model ("sonnet").
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to Claude settings JSON file.
            cwd: Working directory for the CLI process. If None, uses current
                directory.
            disable_tools: If True, disables all tools (--tools ""). Useful for
                pure text transformation tasks where tool usage is unwanted.
            allowed_tools: List of tool names to allow (e.g., ["TodoWrite"]).
                Uses --allowedTools CLI flag. Mutually exclusive with disable_tools.
                When set, only specified tools are available to the agent.
            no_cache: If True, disables prompt caching. Useful for one-shot
                prompts where caching overhead is wasteful.
            color_index: Index for console output color (0-7). When multiple
                providers run concurrently, each gets a different color for
                easy visual distinction. None means no color.
            display_model: Human-readable model name for progress output.
                If provided, shown instead of the CLI model (e.g., "glm-4.7"
                instead of "sonnet" when using GLM via settings file).
            cancel_token: Optional threading.Event for cancellation.
                When set, the subprocess is terminated using SIGTERM→SIGKILL
                escalation. Returns partial result with exit_code=-15.

        Returns:
            ProviderResult containing stdout, stderr, exit code, and timing.
            Both stdout and stderr are string type (never bytes), captured
            separately without mixing.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If CLI execution fails due to:
                - Unsupported model specified
                - CLI executable not found (FileNotFoundError)
            ProviderExitCodeError: If CLI returns non-zero exit code.
                Contains exit_code, exit_status, stderr, and command context.
            ProviderTimeoutError: If CLI execution exceeds timeout.
                Contains partial_result if output was captured before timeout.

        Example:
            >>> provider = ClaudeProvider()
            >>> result = provider.invoke("Hello", model="sonnet", timeout=60)
            >>> result.exit_code
            0

        """
        # Validate timeout parameter (AC7)
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "sonnet"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate and resolve settings file (AC2, AC3, AC4)
        # This happens AFTER model validation, BEFORE command building
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Build tools info for logging (distinguish empty list from None)
        tools_info: str
        if disable_tools:
            tools_info = "disabled"
        elif allowed_tools is not None:
            tools_info = ",".join(allowed_tools) if allowed_tools else "disabled (empty list)"
        else:
            tools_info = "all"
        logger.debug(
            "Invoking Claude CLI: model=%s, display_model=%s, timeout=%ds, "
            "prompt_len=%d, settings=%s, tools=%s",
            effective_model,
            display_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            tools_info,
        )

        # Build command with stream-json for real-time output
        # Note: prompt passed via stdin to avoid "Argument list too long" error
        # --dangerously-skip-permissions: required for automated workflows
        # (slash commands, file edits, etc. need auto-approval)
        # --verbose: required when using --output-format=stream-json with --print
        command: list[str] = [
            "claude",
            "-p",
            "-",  # Read prompt from stdin
            "--model",
            effective_model,
            "--output-format",
            "stream-json",
            "--verbose",  # Required for stream-json with --print
            "--dangerously-skip-permissions",
        ]

        # Add settings file only if validated (exists and is a file)
        if validated_settings is not None:
            command.extend(["--settings", str(validated_settings)])

        # CRITICAL: Only add --add-dir for non-validator invocations!
        # Validators (allowed_tools != None) MUST NOT get file write access.
        # --add-dir gives LLM ability to Edit/Write files in the directory,
        # which validators should NOT have. They should only read via <file> embeds.
        # This prevents validators from modifying story files, code, etc.
        should_add_dir = cwd is not None and allowed_tools is None
        if should_add_dir:
            command.extend(["--add-dir", str(cwd)])

        # Disable all tools if requested (for pure text transformation)
        if disable_tools:
            command.extend(["--tools", ""])
        elif allowed_tools is not None:
            # Restrict to ONLY specified tools (e.g., ["TodoWrite"] for validators)
            # Use --tools to explicitly set the tool list, not --allowedTools which filters
            # Empty list [] means disable all tools (allowed_tools=[] is falsy but explicit)
            if allowed_tools:
                command.extend(["--tools", ",".join(allowed_tools)])
            else:
                command.extend(["--tools", ""])

        # Prepare environment (inherit current + optionally disable caching)
        env = os.environ.copy()
        # Strip CLAUDECODE marker to prevent nested session guard (Claude Code 2.1.41+)
        env.pop("CLAUDECODE", None)
        # Strip all inherited experimental features to prevent uncontrolled
        # behavior (e.g. AGENT_TEAMS spawns 5-6 teammate processes at 100% CPU).
        for key in list(env):
            if key.startswith("CLAUDE_CODE_EXPERIMENTAL_"):
                env.pop(key)
        # Re-enable agent teams if explicitly configured in bmad-assist.yaml
        if os.environ.get("BMAD_AGENT_TEAMS") == "1":
            env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        if no_cache:
            env["DISABLE_PROMPT_CACHING"] = "1"

        start_time = time.perf_counter()

        # Debug JSON logger - writes raw JSON to file for debugging
        # Enabled only in DEBUG mode, writes immediately to survive crashes
        debug_json_logger = DebugJsonLogger()

        # Accumulators for stream-json parsing
        response_text_parts: list[str] = []
        stderr_chunks: list[str] = []
        raw_stdout_lines: list[str] = []
        child_pgid: int | None = None

        try:
            # Get platform-specific kwargs for process isolation
            popen_kwargs = get_popen_kwargs_for_new_session()

            process = Popen(
                command,
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=cwd,
                env=env,
                **popen_kwargs,
            )

            # Store process for cancel() method
            with self._process_lock:
                self._current_process = process

            # Register child process for signal handler cleanup (Ctrl+C)
            # Platform-specific: Windows tracks process objects, POSIX tracks pgids
            if IS_WINDOWS:
                register_child_process(process)
            else:
                try:
                    child_pgid = os.getpgid(process.pid)
                    register_child_pgid(child_pgid)
                except (ProcessLookupError, OSError):
                    pass

            # Write prompt to stdin and close it
            if process.stdin:
                process.stdin.write(prompt)
                process.stdin.close()

            def process_json_stream(
                stream: Any,
                text_parts: list[str],
                raw_lines: list[str],
                json_logger: DebugJsonLogger,
                color_idx: int | None,
                term_event: threading.Event | None = None,
            ) -> None:
                """Process stream-json output, extracting text and showing progress.

                Early Termination Detection:
                    Detects common output markers and completion phrases to terminate
                    the stream early, preventing timeout when LLM doesn't close stream
                    (known issue with GLM-4.7 and similar models via Claude CLI).

                    Termination triggers:
                    - End markers: <!-- *_END --> (VALIDATION_REPORT_END, etc.)
                    - Completion phrases: "successfully completed", "task is done"
                    - After final assistant summary following tool use
                """
                # Early termination markers (common end markers from extraction.py + others)
                end_markers = [
                    "<!-- VALIDATION_REPORT_END -->",
                    "<!-- CODE_REVIEW_REPORT_END -->",
                    "<!-- CODE_REVIEW_SYNTHESIS_END -->",
                    "<!-- VALIDATION_SYNTHESIS_END -->",
                    "<!-- RETROSPECTIVE_REPORT_END -->",
                    "<!-- SECURITY_REPORT_END -->",
                    "<!-- QA_PLAN_END -->",
                    "<!-- REMEDIATE_ESCALATIONS_END -->",
                    "BMAD Method Quality Competition v1.0",
                ]

                # Completion phrases that indicate task is done
                completion_phrases = [
                    "successfully completed",
                    "task is done",
                    "task is complete",
                    "synthesis complete",
                    "review complete",
                    "validation complete",
                ]

                for line in iter(stream.readline, ""):
                    raw_lines.append(line)
                    stripped = line.strip()
                    if not stripped:
                        continue

                    # Log raw JSON immediately (survives crashes)
                    json_logger.append(stripped)

                    try:
                        msg = json.loads(stripped)
                        msg_type = msg.get("type", "")

                        if msg_type == "system" and msg.get("subtype") == "init":
                            # Session started
                            session_id = msg.get("session_id", "?")
                            if should_print_progress():
                                tag = format_tag("INIT", color_idx)
                                write_progress(f"{tag} Session: {session_id}")

                        elif msg_type == "assistant":
                            # Assistant message with content
                            message = msg.get("message", {})
                            for block in message.get("content", []):
                                if block.get("type") == "text":
                                    text = block.get("text", "")
                                    text_parts.append(text)

                                    # Check for early termination markers/phrases
                                    text_lower = text.lower()
                                    should_terminate = False

                                    # Check end markers
                                    for marker in end_markers:
                                        if marker in text:
                                            logger.info(
                                                "Early termination: detected end marker %s", marker
                                            )
                                            should_terminate = True
                                            break

                                    # Check completion phrases
                                    if not should_terminate:
                                        for phrase in completion_phrases:
                                            if phrase in text_lower:
                                                logger.info(
                                                    "Early termination: detected completion phrase '%s'",
                                                    phrase,
                                                )
                                                should_terminate = True
                                                break

                                    if should_print_progress():
                                        if is_full_stream():
                                            tag = format_tag("ASSISTANT", color_idx)
                                            write_progress(f"{tag} {text}")
                                        else:
                                            preview = text[:100].replace("\n", " ")
                                            if len(text) > 100:
                                                preview += "..."
                                            tag = format_tag("ASSISTANT", color_idx)
                                            write_progress(f"{tag} {preview}")

                                    # Terminate stream if marker/phrase detected
                                    if should_terminate:
                                        if should_print_progress():
                                            tag = format_tag("TERM", color_idx)
                                            write_progress(f"{tag} Stream terminated early")
                                        if term_event is not None:
                                            term_event.set()
                                        stream.close()
                                        return
                                elif block.get("type") == "tool_use":
                                    tool_name = block.get("name", "?")
                                    tool_input = block.get("input", {})
                                    if should_print_progress():
                                        if is_full_stream():
                                            import json as _json

                                            tag = format_tag(f"TOOL {tool_name}", color_idx)
                                            write_progress(
                                                f"{tag} {_json.dumps(tool_input, indent=2)}"
                                            )
                                        else:
                                            details = extract_tool_details(tool_name, tool_input)
                                            tag = format_tag(f"TOOL {tool_name}", color_idx)
                                            if details:
                                                write_progress(f"{tag} {details}")
                                            else:
                                                write_progress(f"{tag}")

                        elif msg_type == "result":
                            # Final result with stats
                            if should_print_progress():
                                cost = msg.get("total_cost_usd", 0)
                                duration = msg.get("duration_ms", 0)
                                turns = msg.get("num_turns", 0)
                                tag = format_tag("RESULT", color_idx)
                                write_progress(f"{tag} ${cost:.4f} | {duration}ms | {turns} turns")
                            # Extract final result text if present
                            if "result" in msg:
                                text_parts.append(msg["result"])

                    except json.JSONDecodeError:
                        # Non-JSON line, just accumulate
                        if should_print_progress():
                            tag = format_tag("RAW", color_idx)
                            write_progress(f"{tag} {stripped}")

                stream.close()

            def read_stderr(
                stream: Any,
                chunks: list[str],
                color_idx: int | None,
            ) -> None:
                """Read stderr stream."""
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    if should_print_progress():
                        tag = format_tag("ERR", color_idx)
                        write_progress(f"{tag} {line.rstrip()}")
                stream.close()

            # Event signaled by stdout reader on early termination
            early_term_event = threading.Event()

            # Start reader threads
            stdout_thread = threading.Thread(
                target=process_json_stream,
                args=(
                    process.stdout,
                    response_text_parts,
                    raw_stdout_lines,
                    debug_json_logger,
                    color_index,
                    early_term_event,
                ),
            )
            stderr_thread = threading.Thread(
                target=read_stderr,
                args=(process.stderr, stderr_chunks, color_index),
            )
            stdout_thread.start()
            stderr_thread.start()

            if should_print_progress():
                shown_model = display_model or effective_model
                tag = format_tag("START", color_index)
                write_progress(f"{tag} Invoking Claude CLI (model={shown_model})...")
                tag = format_tag("PROMPT", color_index)
                write_progress(f"{tag} {len(prompt):,} chars")
                tag = format_tag("WAITING", color_index)
                write_progress(f"{tag} Streaming response...")

            # Wait for process with timeout and cancel check
            deadline = time.perf_counter() + effective_timeout
            returncode: int | None = None
            cancelled = False

            while True:
                # Check for cancellation
                if cancel_token is not None and cancel_token.is_set():
                    logger.info("Cancel token set, terminating subprocess")
                    self._terminate_process(process)
                    cancelled = True
                    returncode = -15  # SIGTERM
                    break

                # Check for early termination (end marker detected)
                if early_term_event.is_set():
                    logger.info("Early termination signaled, killing process")
                    self._terminate_process(process)
                    returncode = 0
                    break

                # Check for timeout
                if time.perf_counter() >= deadline:
                    process.kill()
                    stdout_thread.join(timeout=1)
                    stderr_thread.join(timeout=1)
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    truncated = _truncate_prompt(prompt)

                    partial_result = ProviderResult(
                        stdout="".join(response_text_parts),
                        stderr="".join(stderr_chunks),
                        exit_code=-1,
                        duration_ms=duration_ms,
                        model=effective_model,
                        command=tuple(command),
                    )

                    logger.warning(
                        "Provider timeout: provider=%s, model=%s, timeout=%ds, "
                        "duration_ms=%d, prompt=%s",
                        self.provider_name,
                        effective_model,
                        effective_timeout,
                        duration_ms,
                        truncated,
                    )

                    # Close debug logger and clear process before raising
                    debug_json_logger.close()
                    # Unregister from signal handler (platform-specific)
                    if IS_WINDOWS:
                        unregister_child_process(process)
                    elif child_pgid is not None:
                        unregister_child_pgid(child_pgid)
                    with self._process_lock:
                        self._current_process = None

                    raise ProviderTimeoutError(
                        f"Claude CLI timeout after {effective_timeout}s: {truncated}",
                        partial_result=partial_result,
                    )

                # Block on process (0.5s intervals for cancel responsiveness)
                try:
                    returncode = process.wait(timeout=0.5)
                    break
                except TimeoutExpired:
                    continue

            # Wait for threads to finish (timeout prevents hang if reader stuck)
            stdout_thread.join(timeout=10)
            stderr_thread.join(timeout=10)

            # Clear current process and unregister from signal handler (platform-specific)
            if IS_WINDOWS:
                unregister_child_process(process)
            elif child_pgid is not None:
                unregister_child_pgid(child_pgid)
            with self._process_lock:
                self._current_process = None

            # Handle cancellation - return partial result
            if cancelled:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                debug_json_logger.close()
                logger.info("Returning cancelled result after %dms", duration_ms)
                return ProviderResult(
                    stdout="".join(response_text_parts),
                    stderr="Cancelled by user",
                    exit_code=-15,
                    duration_ms=duration_ms,
                    model=effective_model,
                    command=tuple(command),
                )

            # Store results for unified handling below
            final_returncode = returncode
            # Use extracted text parts, not raw JSON stream
            final_stdout = "".join(response_text_parts)
            final_stderr = "".join(stderr_chunks)

        except FileNotFoundError as e:
            logger.error("Claude CLI not found in PATH")
            # Note: FileNotFoundError from Popen means process was never created,
            # so nothing was registered with the signal handler
            with self._process_lock:
                self._current_process = None
            debug_json_logger.close()
            raise ProviderError("Claude CLI not found. Is 'claude' in PATH?") from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        if final_returncode != 0:
            exit_status = ExitStatus.from_code(final_returncode)
            stderr_content = final_stderr or ""
            stderr_truncated = (
                stderr_content[:STDERR_TRUNCATE_LENGTH] if stderr_content else "(empty)"
            )

            logger.error(
                "Claude CLI failed: exit_code=%d, status=%s, model=%s, stderr=%s",
                final_returncode,
                exit_status.name,
                effective_model,
                stderr_truncated,
            )

            # Build human-readable message based on exit status
            # All messages include exit code per AC2 format requirement
            if exit_status == ExitStatus.SIGNAL:
                signal_num = ExitStatus.get_signal_number(final_returncode)
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(signal {signal_num}): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.NOT_FOUND:
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(command not found - check PATH): {stderr_truncated}"
                )
            elif exit_status == ExitStatus.CANNOT_EXECUTE:
                message = (
                    f"Claude CLI failed with exit code {final_returncode} "
                    f"(permission denied): {stderr_truncated}"
                )
            else:
                message = f"Claude CLI failed with exit code {final_returncode}: {stderr_truncated}"

            debug_json_logger.close()
            raise ProviderExitCodeError(
                message,
                exit_code=final_returncode,
                exit_status=exit_status,
                stderr=stderr_content,
                stdout=final_stdout,  # Preserve output even on failure
                command=tuple(command),
            )

        # Log if replacement characters found in output (AC2, AC8)
        # Only scan if debug logging is enabled (performance optimization)
        if logger.isEnabledFor(logging.DEBUG):
            replacement_char = "\ufffd"
            stdout_has_replacement = replacement_char in final_stdout
            stderr_has_replacement = replacement_char in final_stderr
            if stdout_has_replacement or stderr_has_replacement:
                logger.debug(
                    "Encoding replacements in output: stdout=%s, stderr=%s",
                    stdout_has_replacement,
                    stderr_has_replacement,
                )

        logger.info(
            "Claude CLI completed: duration=%dms, exit_code=%d",
            duration_ms,
            final_returncode,
        )

        # Extract provider session_id before closing logger
        provider_session_id = debug_json_logger.provider_session_id

        # Close debug logger on success
        debug_json_logger.close()

        return ProviderResult(
            stdout=final_stdout,
            stderr=final_stderr,
            exit_code=final_returncode,
            duration_ms=duration_ms,
            model=display_model or effective_model,
            command=tuple(command),
            provider_session_id=provider_session_id,
        )

    def parse_output(self, result: ProviderResult) -> str:
        r"""Extract response text from Claude CLI output.

        Claude Code with --print flag returns plain text directly to stdout.
        No JSON parsing is needed - the response is the raw stdout with
        leading/trailing whitespace stripped.

        Args:
            result: ProviderResult from invoke() containing raw output.

        Returns:
            Extracted response text with whitespace stripped.
            Empty string if stdout is empty.

        Example:
            >>> result = ProviderResult(stdout="  Hello world  \n", ...)
            >>> provider.parse_output(result)
            'Hello world'

        """
        return result.stdout.strip()
