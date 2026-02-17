"""Claude Agent SDK-based provider implementation.

This module implements the ClaudeSDKProvider class - the PRIMARY Claude integration
for bmad-assist. It uses the official claude-agent-sdk package which provides:
- Native Python async/await API
- Typed message classes (AssistantMessage, ResultMessage, etc.)
- Proper error types (CLINotFoundError, ProcessError, etc.)
- Session management for multi-turn conversations

This is the default Claude provider. The subprocess-based ClaudeSubprocessProvider
(claude.py) is retained only for benchmarking and fair comparison with Codex and
Gemini providers which only have subprocess interfaces.

Key Design Decision: NO FALLBACK
- If SDK fails, the operation fails immediately
- No silent fallback to subprocess - errors must be visible
- Subprocess provider only used when explicitly requested

Example:
    >>> from bmad_assist.providers import ClaudeSDKProvider
    >>> provider = ClaudeSDKProvider()
    >>> result = provider.invoke("What is 2+2?", model="sonnet")
    >>> response = provider.parse_output(result)

"""

import asyncio
import contextlib
import logging
import os
import shutil
import sys
import threading
import time
import uuid
import warnings
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

# Suppress noisy Windows transport warnings on cleanup
# (_ProactorBasePipeTransport.__del__ raises ValueError on closed pipes)
warnings.filterwarnings(
    "ignore",
    message="unclosed transport",
    category=ResourceWarning,
)

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    CLINotFoundError,
    ProcessError,
    TextBlock,
    ToolUseBlock,
)

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ProviderResult,
    extract_tool_details,
    format_tag,
    is_full_stream,
    is_verbose_stream,
    should_print_progress,
    validate_settings_file,
    write_progress,
)
from bmad_assist.providers.progress import (
    clear_progress_line,
    ensure_spinner_running,
    print_completion,
    print_error,
    register_agent,
    stop_spinner_if_last,
    unregister_agent,
    update_agent,
)

logger = logging.getLogger(__name__)

# Supported short model names accepted by Claude Code
SUPPORTED_MODELS: frozenset[str] = frozenset({"opus", "sonnet", "haiku"})

# Track SDK init failures across invocations within same process.
# Once SDK fails to init, all subsequent calls go straight to subprocess.
_sdk_init_failed: bool = False

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300


class ClaudeSDKProvider(BaseProvider):
    """Claude Code SDK-based provider implementation.

    The PRIMARY Claude integration for bmad-assist. Uses the official
    claude-agent-sdk package for native async support, typed messages,
    and proper SDK error handling.

    This provider should be used for all Claude invocations. The subprocess-based
    ClaudeSubprocessProvider is retained only for benchmarking purposes.

    Claude Code supports these models:
        - opus: Most capable model
        - sonnet: Balanced model (default)
        - haiku: Fastest model
        - Any full identifier starting with "claude-"

    Key Design: NO FALLBACK
        If the SDK fails for any reason, ProviderError is raised immediately.
        There is no silent fallback to subprocess - errors must be visible.
        This ensures predictable behavior and accurate error reporting.

    Settings File Handling:
        When settings_file is provided to invoke(), it is validated for
        existence before SDK invocation. If the file is missing or is not
        a regular file, a warning is logged and settings parameter is omitted
        (graceful degradation).

    Example:
        >>> provider = ClaudeSDKProvider()
        >>> result = provider.invoke("Hello", model="opus", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "claude" as the provider identifier.
            Note: Both ClaudeSDKProvider and ClaudeSubprocessProvider
            represent the "claude" logical provider, but SDK is primary.

        """
        return "claude"

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
            >>> provider = ClaudeSDKProvider()
            >>> provider.supports_model("sonnet")
            True
            >>> provider.supports_model("claude-sonnet-4-20250514")
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
        SDK invocation.

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

    @staticmethod
    async def _prompt_stream(prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Wrap prompt string as async stream-json iterator.

        Uses SDK streaming input mode (--input-format stream-json) to send
        prompt via stdin instead of CLI args. This avoids E2BIG (Argument
        list too long) errors with large compiled workflow prompts.

        Args:
            prompt: The prompt text to send.

        Yields:
            Single user message dict in SDK stream-json format.

        """
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }

    async def _invoke_async(
        self,
        prompt: str,
        model: str,
        settings: Path | None,
        cwd: Path | None,
        allowed_tools: list[str] | None = None,
        color_index: int | None = None,
        display_model: str | None = None,
    ) -> str:
        """Execute SDK query asynchronously using ClaudeSDKClient.

        Internal async helper that performs the actual SDK call. Uses streaming
        input mode to pass prompt via stdin (avoids CLI argument length limits).
        Iterates through SDK messages and extracts text content from
        AssistantMessage blocks.

        Uses ClaudeSDKClient (not the query() convenience function) because
        ClaudeSDKClient.connect() correctly reads CLAUDE_CODE_STREAM_CLOSE_TIMEOUT
        for the initialization timeout. The query() path hardcodes 60s.

        Args:
            prompt: The prompt text to send to Claude.
            model: Model identifier to use.
            settings: Optional validated settings file path.
            cwd: Working directory for the CLI process.
            allowed_tools: Optional list of tools to allow. If provided, uses
                the SDK's 'tools' parameter to restrict available tools.
            color_index: Color index for progress output.

        Returns:
            Response text extracted from AssistantMessage TextBlocks.

        Raises:
            CLINotFoundError: If Claude Code CLI is not found.
            ProcessError: If Claude Code process fails.
            ProviderError: If no response is received (empty iteration).

        """
        # CLI resolution: let SDK use its default (bundled first, then system).
        # The bundled CLI is version-matched to the SDK's streaming protocol.
        # User can override via BMAD_CLAUDE_CLI_PATH env var if needed.
        cli_override = os.environ.get("BMAD_CLAUDE_CLI_PATH")
        if cli_override:
            cli_path: str | None = cli_override
            logger.info("SDK using override CLI: %s", cli_override)
        else:
            # Let SDK resolve: bundled (version-matched) → system
            cli_path = None
            system_cli = shutil.which("claude")
            logger.info(
                "SDK CLI resolution: bundled preferred, system=%s",
                system_cli or "not found",
            )

        shown_model = display_model or model
        logger.info(
            "SDK init: model=%s, prompt=%d chars, cwd=%s, cli=%s, debug=%s",
            shown_model,
            len(prompt),
            cwd,
            cli_path or "sdk-default",
            "enabled" if os.environ.get("CLAUDE_SDK_DEBUG") else "disabled",
        )

        # Build extra_args for debug mode (if enabled via env)
        extra_args: dict[str, str | None] = {}
        if os.environ.get("CLAUDE_SDK_DEBUG"):
            extra_args["debug"] = None  # Boolean flag --debug
            logger.debug("Enabling Claude SDK debug mode via CLAUDE_SDK_DEBUG")

        # Stderr capture for diagnostics — collects CLI output on init failures
        # Stored on instance so invoke() can include it in timeout error messages
        self._last_stderr_lines: list[str] = []

        def _capture_stderr(line: str) -> None:
            self._last_stderr_lines.append(line)
            if len(self._last_stderr_lines) <= 5:
                logger.debug("CLI stderr: %s", line.rstrip())

        # Override env to strip experimental features that interfere with
        # bmad-assist orchestration (e.g. AGENT_TEAMS spawns sub-agents).
        # SDK transport merges: {**os.environ, **options.env}, so we override
        # with empty string to effectively disable inherited experimental flags.
        env_overrides: dict[str, str] = {}
        for key in os.environ:
            if key.startswith("CLAUDE_CODE_EXPERIMENTAL_"):
                env_overrides[key] = ""
        # Re-enable agent teams if explicitly configured in bmad-assist.yaml
        if os.environ.get("BMAD_AGENT_TEAMS") == "1":
            env_overrides["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "1"
        # Also strip nested session guard
        if os.environ.get("CLAUDECODE"):
            env_overrides["CLAUDECODE"] = ""

        # Build SDK options with explicit values
        options = ClaudeAgentOptions(
            model=model,
            permission_mode="acceptEdits",  # Explicit automation mode
            settings=str(settings) if settings is not None else None,
            cwd=cwd,
            cli_path=cli_path,  # None = SDK default (bundled → system)
            # Tool restrictions: use 'tools' parameter to set explicit list
            # IMPORTANT: empty list [] means "no tools", None means "all tools"
            # Use explicit check for None to distinguish [] from None
            tools=allowed_tools if allowed_tools is not None else None,
            # Increase buffer size for long-running conversations (default 1MB)
            # Dev story workflows can generate extensive conversation history
            max_buffer_size=10 * 1024 * 1024,  # 10MB buffer for conversation history
            extra_args=extra_args,
            stderr=_capture_stderr,  # Capture stderr for diagnostics
            env=env_overrides,  # Override experimental features
        )

        response_parts: list[str] = []
        terminated_early = False  # Flag for clean async loop exit

        # Early termination markers (same as claude.py for consistency)
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

        # Init timeout: CLI startup includes Node.js boot, CLAUDE.md loading,
        # MCP server init, settings parsing. On WSL2 with slow I/O this can
        # take 10-30s. We use asyncio.wait() (not wait_for) to avoid cancelling
        # the coroutine — asyncio.wait_for cancellation breaks anyio's cancel
        # scopes ("exit cancel scope in different task" error).
        # 30s to handle parallel invocations where Node.js cold starts compete.
        init_timeout = int(os.environ.get("BMAD_SDK_INIT_TIMEOUT", "30"))

        client = ClaudeSDKClient(options=options)
        try:
            # Use streaming input to avoid E2BIG with large prompts
            prompt_iter = self._prompt_stream(prompt)

            # Run connect as a task so we can timeout without cancelling
            connect_task = asyncio.ensure_future(
                client.connect(prompt=prompt_iter)
            )
            done, _pending = await asyncio.wait(
                {connect_task}, timeout=init_timeout
            )

            if not done:
                # Init timed out. We can't use client.disconnect() here because
                # it tries to exit anyio's TaskGroup from a different async context,
                # causing "'TaskGroup' has no attribute '_exceptions'".
                # Instead, close the transport directly to kill the subprocess,
                # then let the orphaned anyio task group be garbage collected.
                if client._transport:
                    await client._transport.close()
                connect_task.cancel()
                connect_task.add_done_callback(lambda _: None)

                stderr_tail = ""
                if self._last_stderr_lines:
                    stderr_tail = "; ".join(
                        line.rstrip() for line in self._last_stderr_lines[-5:]
                    )
                # Clear spinner before logging so error output isn't interleaved
                if is_verbose_stream() and should_print_progress():
                    print_error(shown_model, f"init timeout ({init_timeout}s)")
                logger.warning(
                    "SDK init timeout after %ds: model=%s, cli=%s, "
                    "stderr_lines=%d, stderr_tail=%s",
                    init_timeout,
                    shown_model,
                    cli_path or "sdk-default",
                    len(self._last_stderr_lines),
                    stderr_tail[:300] if stderr_tail else "(none captured)",
                )
                # Remember failure so subsequent calls skip SDK entirely
                global _sdk_init_failed
                _sdk_init_failed = True
                raise ProviderTimeoutError(
                    f"SDK initialization timeout ({init_timeout}s)"
                )

            # Re-raise any exception from connect
            connect_task.result()

            # Progress tracking for parallel agent display
            agent_id = str(uuid.uuid4())
            agent_color_idx = -1
            event_start = time.perf_counter()
            total_chars = 0

            # Register for parallel progress display (--stream preview mode)
            if is_verbose_stream() and should_print_progress():
                agent_color_idx = register_agent(
                    agent_id, shown_model, event_start, provider_tag="CC"
                )
                ensure_spinner_running()

            try:
                async for message in client.receive_messages():
                    # Check if we should exit outer loop
                    if terminated_early:
                        break

                    # Extract content from AssistantMessage only
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text = block.text
                                response_parts.append(text)
                                total_chars += len(text)

                                # Update agent state for preview spinner
                                if agent_color_idx >= 0:
                                    # Rough token estimate: ~4 chars per token
                                    out_tokens = total_chars // 4
                                    in_tokens = len(prompt) // 4
                                    update_agent(agent_id, in_tokens=in_tokens, out_tokens=out_tokens, status="streaming")

                                # Check for early termination markers/phrases
                                text_lower = text.lower()
                                should_terminate = False

                                # Check end markers
                                for marker in end_markers:
                                    if marker in text:
                                        logger.info("Early termination: detected end marker %s", marker)
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

                                # Show progress for assistant messages (full/debug modes only)
                                if should_print_progress() and not is_verbose_stream():
                                    tag = format_tag("ASSISTANT", color_index)
                                    if is_full_stream():
                                        write_progress(f"{tag} {text}")
                                    else:
                                        preview = text[:100].replace("\n", " ")
                                        if len(text) > 100:
                                            preview += "..."
                                        write_progress(f"{tag} {preview}")

                                # Terminate stream if marker/phrase detected
                                if should_terminate:
                                    if should_print_progress() and not is_verbose_stream():
                                        tag = format_tag("TERM", color_index)
                                        write_progress(f"{tag} Stream terminated early (SDK)")
                                    # Set flag to exit outer loop cleanly
                                    terminated_early = True
                                    break  # Exit inner loop

                            elif isinstance(block, ToolUseBlock):
                                # Log tool use
                                tool_name = block.name
                                tool_input = block.input
                                if should_print_progress() and not is_verbose_stream():
                                    tag = format_tag(f"TOOL {tool_name}", color_index)
                                    if is_full_stream():
                                        import json as _json

                                        write_progress(f"{tag} {_json.dumps(tool_input, indent=2)}")
                                    else:
                                        details = extract_tool_details(tool_name, tool_input, cwd)
                                        if details:
                                            write_progress(f"{tag} {details}")
                                        else:
                                            write_progress(f"{tag}")
                    # ResultMessage is metadata only (cost/usage) - skip
                    # Other message types (SystemMessage, UserMessage) - skip
            finally:
                # Unregister agent and stop spinner if last
                if agent_color_idx >= 0:
                    # Print completion message before unregistering
                    if is_verbose_stream() and should_print_progress():
                        elapsed = int(time.perf_counter() - event_start)
                        out_tokens = total_chars // 4
                        print_completion(agent_id, shown_model, elapsed, out_tokens)
                    unregister_agent(agent_id)
                    stop_spinner_if_last()

        except (CLINotFoundError, ProcessError):
            # Re-raise SDK errors for handling in invoke()
            raise
        finally:
            # Clean up subprocess. Use transport.close() directly because
            # client.disconnect() -> query.close() tries to exit anyio's
            # TaskGroup from a different async context, which crashes with
            # "Attempted to exit cancel scope in a different task".
            try:
                await client.disconnect()
            except Exception:
                # Fallback: close transport directly to kill subprocess
                if client._transport:
                    with contextlib.suppress(Exception):
                        await client._transport.close()

        # Validate we got a response (AC12)
        if not response_parts:
            raise ProviderError("No response received from SDK")

        return "".join(response_parts)

    async def _invoke_with_cancel(
        self,
        prompt: str,
        model: str,
        settings: Path | None,
        cwd: Path | None,
        allowed_tools: list[str] | None,
        cancel_token: threading.Event,
        timeout: int,
        color_index: int | None = None,
        display_model: str | None = None,
    ) -> str:
        """Execute SDK query with cancel_token support.

        Runs SDK query and cancel monitor as concurrent tasks. When
        cancel_token is set, the SDK task is cancelled — this propagates
        CancelledError into the async generator, killing the subprocess.

        Args:
            prompt: The prompt text to send to Claude.
            model: Model identifier to use.
            settings: Optional validated settings file path.
            cwd: Working directory for the CLI process.
            allowed_tools: Optional list of allowed tools.
            cancel_token: Threading event checked for cancellation.
            timeout: Timeout in seconds.
            color_index: Color index for progress output.

        Returns:
            Response text from SDK.

        Raises:
            asyncio.CancelledError: If cancel_token was set.
            TimeoutError: If timeout exceeded.
            CLINotFoundError: If Claude Code CLI is not found.
            ProcessError: If Claude Code process fails.

        """
        sdk_task = asyncio.create_task(
            self._invoke_async(prompt, model, settings, cwd, allowed_tools, color_index, display_model)
        )

        async def _wait_for_cancel() -> None:
            while not cancel_token.is_set():
                await asyncio.sleep(0.5)

        cancel_task = asyncio.create_task(_wait_for_cancel())

        try:
            done, pending = await asyncio.wait(
                {sdk_task, cancel_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            sdk_task.cancel()
            cancel_task.cancel()
            raise

        # Clean up pending tasks
        for task in pending:
            task.cancel()

        # Timeout — neither finished
        if not done:
            raise TimeoutError

        # Cancel was triggered
        if cancel_task in done and sdk_task not in done:
            logger.info("Cancel token set, cancelling SDK task")
            raise asyncio.CancelledError

        # SDK completed (cancel_task still pending — already cancelled above)
        return sdk_task.result()

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
        """Execute Claude Code SDK with the given prompt.

        Invokes Claude Code via the official SDK with the specified prompt
        and optional configuration. Uses asyncio.run() with wait_for() for
        timeout enforcement since SDK has no native timeout option.

        Args:
            prompt: The prompt text to send to Claude.
            model: Model to use (opus, sonnet, haiku, or claude-* identifier).
                If None, uses default_model ("sonnet").
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
                If None, uses DEFAULT_TIMEOUT (300s).
            settings_file: Path to Claude settings JSON file.
            cwd: Working directory for the CLI process.
            disable_tools: Disable tools (ignored - SDK doesn't support).
            allowed_tools: List of allowed tools (e.g., ["TodoWrite"]).
                When set, only specified tools are available to the agent.
                Uses SDK's 'tools' parameter to set explicit tool list.
            no_cache: Disable caching (ignored - SDK doesn't support).
            color_index: Color index for terminal output differentiation.

        Returns:
            ProviderResult containing:
                - stdout: response text extracted from AssistantMessage
                - stderr: empty string (SDK doesn't separate stderr)
                - exit_code: 0
                - duration_ms: execution time in milliseconds
                - model: the model used
                - command: list describing SDK invocation (e.g., ["sdk", "query", model])

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If SDK execution fails due to:
                - Unsupported model specified
                - CLI not found (CLINotFoundError)
                - Process failure (ProcessError)
                - No response received
                - Any unexpected exception
            ProviderTimeoutError: If SDK invocation exceeds timeout.

        Note:
            NO FALLBACK - If SDK fails, error is propagated immediately.
            No attempt to use subprocess is made.

        Example:
            >>> provider = ClaudeSDKProvider()
            >>> result = provider.invoke("Hello", model="sonnet", timeout=60)
            >>> result.exit_code
            0

        """
        # Auto-fallback: if SDK init previously failed in this process,
        # skip SDK entirely and delegate to subprocess (no more wasted timeouts).
        # Also handles nested Claude Code sessions (CLAUDECODE=1).
        # BMAD_SDK_FORCE=1 bypasses both checks (for testing).
        global _sdk_init_failed
        if not os.environ.get("BMAD_SDK_FORCE") and (
            _sdk_init_failed or os.environ.get("CLAUDECODE") == "1"
        ):
            from bmad_assist.providers.claude import ClaudeSubprocessProvider

            logger.info("Nested Claude Code session detected, delegating to subprocess provider")
            return ClaudeSubprocessProvider().invoke(
                prompt,
                model=model,
                timeout=timeout,
                settings_file=settings_file,
                cwd=cwd,
                disable_tools=disable_tools,
                allowed_tools=allowed_tools,
                no_cache=no_cache,
                color_index=color_index,
                display_model=display_model,
                cancel_token=cancel_token,
            )

        # Ignored parameters (SDK doesn't support these)
        _ = no_cache, color_index
        # Note: allowed_tools IS supported - passed to _invoke_async
        if disable_tools and allowed_tools is None:
            allowed_tools = []

        # Validate timeout parameter
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model with fallback chain: explicit -> default -> literal
        effective_model = model or self.default_model or "sonnet"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate model before SDK invocation (fail-fast)
        if not self.supports_model(effective_model):
            raise ProviderError(
                f"Unsupported model '{effective_model}' for Claude provider. "
                f"Supported: {', '.join(sorted(SUPPORTED_MODELS))} or claude-* identifiers"
            )

        # Validate and resolve settings file
        validated_settings = self._resolve_settings(settings_file, effective_model)

        # Resolve display model (model_name from config, e.g. "glm-4.7")
        shown_model = display_model or effective_model

        tools_info = allowed_tools if allowed_tools else "all"
        logger.debug(
            "Invoking Claude SDK: model=%s, display_model=%s, timeout=%ds, "
            "prompt_len=%d, settings=%s, tools=%s",
            effective_model,
            shown_model,
            effective_timeout,
            len(prompt),
            validated_settings,
            tools_info,
        )

        start_time = time.perf_counter()

        # Build command representation for ProviderResult
        command: tuple[str, ...] = ("sdk", "query", effective_model)

        try:
            # CRITICAL: Use run_async_in_thread() instead of asyncio.run() to avoid
            # shutting down the default executor when called via asyncio.to_thread()
            from bmad_assist.core.async_utils import run_async_in_thread

            if cancel_token is not None:
                response_text = run_async_in_thread(
                    self._invoke_with_cancel(
                        prompt,
                        effective_model,
                        validated_settings,
                        cwd,
                        allowed_tools,
                        cancel_token,
                        effective_timeout,
                        color_index,
                        display_model,
                    )
                )
            else:
                response_text = run_async_in_thread(
                    asyncio.wait_for(
                        self._invoke_async(
                            prompt,
                            effective_model,
                            validated_settings,
                            cwd,
                            allowed_tools,
                            color_index,
                            display_model,
                        ),
                        timeout=effective_timeout,
                    )
                )
        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info("SDK cancelled after %dms", duration_ms)
            return ProviderResult(
                stdout="",
                stderr="",
                exit_code=-15,
                duration_ms=duration_ms,
                model=shown_model,
                command=command,
            )
        except TimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            clear_progress_line()
            logger.warning(
                "SDK timeout: model=%s, timeout=%ds, duration_ms=%d",
                shown_model,
                effective_timeout,
                duration_ms,
            )
            raise ProviderTimeoutError(f"SDK timeout after {effective_timeout}s") from e
        except CLINotFoundError as e:
            clear_progress_line()
            logger.error("Claude Code not found")
            raise ProviderError("Claude Code not found. Is 'claude' installed and in PATH?") from e
        except ProcessError as e:
            # Extract exit code and stderr from ProcessError
            exit_code = e.exit_code if e.exit_code is not None else 1
            stderr = e.stderr or ""
            clear_progress_line()
            logger.error(
                "Claude SDK process error: exit_code=%s, stderr=%s",
                exit_code,
                stderr[:200] if stderr else "(empty)",
            )
            raise ProviderError(
                f"Claude SDK failed with exit code {exit_code}: {stderr[:200]}"
            ) from e
        except ProviderError:
            # Re-raise ProviderError (e.g., "No response received")
            clear_progress_line()
            raise
        except Exception as e:
            # Check if this is a timeout-related error that should be retryable
            error_str = str(e).lower()
            if "timeout" in error_str or "control request timeout" in error_str:
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                # Include captured stderr for diagnostics
                stderr_tail = ""
                if hasattr(self, "_last_stderr_lines") and self._last_stderr_lines:
                    stderr_tail = "; ".join(
                        line.rstrip() for line in self._last_stderr_lines[-10:]
                    )
                clear_progress_line()
                logger.warning(
                    "SDK initialization timeout: model=%s, duration_ms=%d, error=%s, "
                    "stderr_lines=%d, stderr_tail=%s",
                    effective_model,
                    duration_ms,
                    str(e)[:100],
                    len(getattr(self, "_last_stderr_lines", [])),
                    stderr_tail[:500] if stderr_tail else "(none captured)",
                )
                raise ProviderTimeoutError(f"SDK timeout: {e}") from e
            # Catch any unexpected exception and wrap in ProviderError
            # NO FALLBACK - error propagates immediately
            clear_progress_line()
            logger.error("Unexpected SDK error: %s", e)
            raise ProviderError(f"Unexpected SDK error: {e}") from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "Claude SDK completed: duration=%dms, response_len=%d",
            duration_ms,
            len(response_text),
        )

        return ProviderResult(
            stdout=response_text,
            stderr="",  # SDK doesn't separate stderr
            exit_code=0,
            duration_ms=duration_ms,
            model=shown_model,
            command=command,
        )

    def parse_output(self, result: ProviderResult) -> str:
        r"""Extract response text from SDK output.

        The SDK already returns clean text extracted from AssistantMessage.
        This method strips leading/trailing whitespace for consistency.

        Args:
            result: ProviderResult from invoke() containing response text.

        Returns:
            Extracted response text with whitespace stripped.
            Empty string if stdout is empty.

        Example:
            >>> result = ProviderResult(stdout="  Hello world  \n", ...)
            >>> provider.parse_output(result)
            'Hello world'

        """
        return result.stdout.strip()
