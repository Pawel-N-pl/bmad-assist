"""GitHub Copilot SDK-based provider implementation.

This module implements the CopilotSDKProvider class - an alternative Copilot
integration for bmad-assist using the official github-copilot-sdk package.
Instead of shelling out to the Copilot CLI via subprocess, this provider uses
the SDK's JSON-RPC protocol for programmatic control.

Benefits over subprocess-based CopilotProvider:
- Native async/await support via JSON-RPC
- Streaming events for real-time progress
- Session lifecycle management (create/destroy)
- Proper error propagation instead of exit code parsing
- No command-line length limits (prompts sent via JSON-RPC)

Key Design Decision: NO FALLBACK
- If SDK fails, the operation fails immediately
- No silent fallback to subprocess - errors must be visible
- Subprocess provider only used when explicitly requested via config

Example:
    >>> from bmad_assist.providers import CopilotSDKProvider
    >>> provider = CopilotSDKProvider()
    >>> result = provider.invoke("Review this code", model="claude-opus-4.6")
    >>> response = provider.parse_output(result)

"""

import asyncio
import logging
import os
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path

from bmad_assist.core.exceptions import (
    ProviderError,
    ProviderTimeoutError,
)
from bmad_assist.providers.base import (
    BaseProvider,
    ProviderResult,
    format_tag,
    get_preview_chars,
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

# Default timeout in seconds (5 minutes)
DEFAULT_TIMEOUT: int = 300

# =============================================================================
# Persistent Client Pool
# =============================================================================
# The SDK spawns a Copilot CLI subprocess per CopilotClient. Starting this
# process takes 2-5 seconds (auth, protocol negotiation). By keeping a
# module-level client alive, subsequent invocations skip the cold start.
#
# Thread safety: _client_lock guards creation; once stored the client is
# re-entered by different invoke() calls that each create their own session.
# =============================================================================

_shared_client: object | None = None  # CopilotClient instance (lazily imported)
_shared_client_cwd: str | None = None  # cwd used when creating the shared client
_client_lock: asyncio.Lock | None = None  # Lazy-init asyncio.Lock for async-safe access
_atexit_registered = False

# Persistent event loop — the CopilotClient's asyncio transport is bound to
# the loop it was started on.  Using asyncio.run() would create a new loop per
# invoke() and the shared client would become unusable after the first call.
# Instead we spin up a single daemon-thread loop that stays alive for the
# entire process lifetime and schedule all SDK work on it.
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop running in a daemon thread."""
    global _loop, _loop_thread

    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop

        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever, daemon=True, name="copilot-sdk-loop"
        )
        _loop_thread.start()
        return _loop


class CopilotSDKProvider(BaseProvider):
    """GitHub Copilot SDK-based provider implementation.

    Uses the official github-copilot-sdk package for native async JSON-RPC
    communication with GitHub Copilot CLI, replacing subprocess invocation.

    This provider accepts any model name — model validation is delegated
    to the Copilot CLI server.

    Thread Safety:
        A module-level CopilotClient is reused across invoke() calls to avoid
        the ~2-5s cold-start cost. Each invoke() creates its own session for
        isolation. All async work runs on a persistent daemon-thread event
        loop so the client's asyncio transport stays valid.

    Example:
        >>> provider = CopilotSDKProvider()
        >>> result = provider.invoke("Hello", model="claude-opus-4.6", timeout=60)
        >>> print(provider.parse_output(result))

    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider.

        Returns:
            The string "copilot-sdk" as the provider identifier.

        """
        return "copilot-sdk"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified.

        Returns:
            The string "claude-sonnet-4.5" as the default model.

        """
        return "claude-sonnet-4.5"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model.

        Args:
            model: Model identifier to check.

        Returns:
            Always True - model validation is delegated to Copilot CLI.

        """
        return True

    @staticmethod
    def _estimate_tokens(chars: int) -> int:
        """Estimate token count from character count (~4 chars/token)."""
        return max(1, chars // 4)

    @staticmethod
    def _log_progress_if_due(
        total_chars: int,
        start_time: float,
        last_progress_time: float,
        interval: float,
        model: str,
        input_tokens: int = 0,
    ) -> None:
        """Log periodic progress at INFO level for --verbose feedback.

        Args:
            total_chars: Total characters received so far.
            start_time: Time when invocation started (perf_counter).
            last_progress_time: Last time progress was logged.
            interval: Minimum seconds between progress logs.
            model: Model name for log message.
            input_tokens: Input token count to display.

        """
        now = time.perf_counter()
        if now - last_progress_time >= interval:
            elapsed = int(now - start_time)
            out_tokens = max(1, total_chars // 4)
            logger.info(
                "GH Copilot CLI SDK streaming (%s): %ds, in=~%d, out=~%d",
                model,
                elapsed,
                input_tokens,
                out_tokens,
            )

    def _resolve_settings(
        self,
        settings_file: Path | None,
        model: str,
    ) -> Path | None:
        """Resolve and validate settings file for invocation."""
        if settings_file is None:
            return None

        return validate_settings_file(
            settings_file=settings_file,
            provider_name=self.provider_name,
            model=model,
        )

    async def _get_or_create_client(
        self,
        cwd: Path | None,
    ) -> object:
        """Get or create a persistent CopilotClient.

        Reuses an existing client when the cwd matches, avoiding the expensive
        CLI subprocess spawn (~2-5s). Falls back to creating a new client if
        the existing one is in an error state.

        Args:
            cwd: Working directory for the CLI process.

        Returns:
            A started CopilotClient instance.

        Raises:
            ProviderError: If SDK is not installed.

        """
        global _shared_client, _shared_client_cwd, _client_lock

        try:
            from copilot import CopilotClient
        except ImportError as e:
            raise ProviderError(
                "github-copilot-sdk is not installed. "
                "Install it with: pip install github-copilot-sdk"
            ) from e

        cwd_str = str(cwd) if cwd else os.getcwd()

        # Lazy-init asyncio.Lock (must be created within event loop context)
        if _client_lock is None:
            _client_lock = asyncio.Lock()

        async with _client_lock:
            # Reuse existing client if cwd matches and client is healthy
            if (
                _shared_client is not None
                and _shared_client_cwd == cwd_str
                and _shared_client.get_state() == "connected"
            ):
                logger.debug("Reusing existing CopilotClient (cwd=%s)", cwd_str)
                return _shared_client

            # Clean up stale client
            if _shared_client is not None:
                old_state = _shared_client.get_state()
                if not is_verbose_stream():
                    logger.info(
                        "Replacing CopilotClient (state=%s, old_cwd=%s, new_cwd=%s)",
                        old_state, _shared_client_cwd, cwd_str,
                    )
                try:
                    await asyncio.wait_for(_shared_client.force_stop(), timeout=3)
                except Exception:
                    pass  # Best-effort cleanup
                _shared_client = None
                _shared_client_cwd = None

            # Create new client inside the lock to prevent race conditions
            # when multiple parallel agents all try to create at once
            cli_path = os.environ.get("COPILOT_CLI_PATH")

            client_opts: dict[str, object] = {
                "log_level": "warning",
                "auto_start": True,
                "auto_restart": True,  # Auto-restart if CLI crashes
            }
            if cli_path:
                client_opts["cli_path"] = cli_path
                if not is_verbose_stream():
                    logger.info("SDK using override CLI: %s", cli_path)
            client_opts["cwd"] = cwd_str

            start_time = time.perf_counter()
            client = CopilotClient(client_opts)
            await asyncio.wait_for(client.start(), timeout=30)
            start_ms = int((time.perf_counter() - start_time) * 1000)
            if not is_verbose_stream():
                logger.info("CopilotClient started in %dms (cwd=%s)", start_ms, cwd_str)

            # Store for reuse
            _shared_client = client
            _shared_client_cwd = cwd_str

            # Register atexit cleanup (once)
            global _atexit_registered
            if not _atexit_registered:
                import atexit
                atexit.register(shutdown_shared_client)
                _atexit_registered = True

            return client

    async def _invoke_async(
        self,
        prompt: str,
        model: str,
        cwd: Path | None,
        timeout: int,
        color_index: int | None = None,
        display_model: str | None = None,
    ) -> str:
        """Execute SDK query asynchronously using CopilotClient.

        Uses a persistent CopilotClient to avoid re-spawning the CLI process
        on each invocation. Creates a fresh session per call for isolation.

        Optimizations applied:
        - Persistent client reuse (saves ~2-5s per invocation)
        - streaming=True for real-time delta events
        - available_tools=[] disables CLI tools (faster session creation)
        - infinite_sessions disabled (no workspace persistence overhead)

        Args:
            prompt: The prompt text to send.
            model: Model identifier to use.
            cwd: Working directory for the CLI process.
            timeout: Timeout in seconds for the entire operation.
            color_index: Color index for progress output.
            display_model: Display name for the model (used in logs).

        Returns:
            Response text extracted from assistant messages.

        Raises:
            ProviderError: If SDK is not installed or communication fails.
            ProviderTimeoutError: If the operation exceeds the timeout.

        """
        shown_model = display_model or model
        input_tokens = self._estimate_tokens(len(prompt))
        # Skip INFO log in preview mode - spinner shows progress
        if not is_verbose_stream():
            logger.info(
                "Copilot SDK invoking: model=%s, input=~%d tokens (%d chars), cwd=%s",
                shown_model,
                input_tokens,
                len(prompt),
                cwd,
            )

        client = await self._get_or_create_client(cwd)
        response_parts: list[str] = []

        # Generate unique ID for parallel agent tracking
        agent_id = str(uuid.uuid4())[:8]
        agent_color_idx = -1  # Set when registered

        session = None
        try:
            session_start = time.perf_counter()
            session_config: dict[str, object] = {
                "model": model,
                "streaming": True,  # Enable delta streaming for real-time feedback
                "available_tools": [],  # Disable all CLI tools (we only need chat)
                "infinite_sessions": {"enabled": False},
            }
            session = await asyncio.wait_for(
                client.create_session(session_config),
                timeout=30,
            )
            session_ms = int((time.perf_counter() - session_start) * 1000)
            logger.debug("Session created in %dms", session_ms)

            # Event collector with progress tracking
            done = asyncio.Event()
            _chars_received = 0
            _delta_chars = 0
            _last_progress_time = time.perf_counter()
            _progress_interval = 10.0  # Log progress every 10 seconds
            _event_start = time.perf_counter()
            _is_verbose = logger.isEnabledFor(logging.INFO)

            # Register for parallel progress display
            if is_verbose_stream() and should_print_progress():
                agent_color_idx = register_agent(
                    agent_id, shown_model, _event_start, provider_tag="GH"
                )

            def on_event(event: object) -> None:
                nonlocal _chars_received, _delta_chars, _last_progress_time
                event_type = getattr(event, "type", None)
                if event_type is None:
                    return

                type_value = event_type.value if hasattr(event_type, "value") else str(event_type)

                if type_value == "assistant.message":
                    content = getattr(getattr(event, "data", None), "content", "")
                    if content:
                        response_parts.append(content)
                        _chars_received += len(content)
                        preview_limit = get_preview_chars()
                        if should_print_progress():
                            tag = format_tag("OUT", color_index)
                            if is_full_stream():
                                # Full streaming (--full-stream or --stream full)
                                write_progress(f"{tag} {content.rstrip()}")
                            elif is_verbose_stream():
                                # --stream preview: spinner task handles display, skip logging
                                pass
                            else:
                                # --debug mode: colored tags via write_progress
                                preview = content[:preview_limit] + "..." if len(content) > preview_limit else content
                                write_progress(f"{tag} {preview.rstrip()}")
                        elif _is_verbose:
                            # --verbose (no --stream): periodic info-level summary
                            preview = content[:preview_limit].replace("\n", " ")
                            if len(content) > preview_limit:
                                preview += "..."
                            elapsed = int(time.perf_counter() - _event_start)
                            out_tokens = self._estimate_tokens(_chars_received)
                            logger.info(
                                "GH Copilot CLI SDK [%s] (%ds, in=~%d, out=~%d): %s",
                                shown_model, elapsed, input_tokens, out_tokens, preview,
                            )

                elif type_value == "assistant.message_delta":
                    delta = getattr(getattr(event, "data", None), "delta_content", "")
                    if delta:
                        _delta_chars += len(delta)
                        total = _chars_received + _delta_chars
                        if should_print_progress():
                            if is_full_stream():
                                # Full streaming: write delta text inline
                                sys.stdout.write(delta)
                                sys.stdout.flush()
                            elif is_verbose_stream():
                                # --stream preview: update agent state for shared render
                                out_tokens = self._estimate_tokens(total)
                                update_agent(agent_id, in_tokens=input_tokens, out_tokens=out_tokens, status="streaming")
                            else:
                                # --debug: periodic delta progress
                                self._log_progress_if_due(
                                    total, _event_start, _last_progress_time,
                                    5.0, shown_model, input_tokens,
                                )
                                _last_progress_time = time.perf_counter()
                        elif _is_verbose:
                            # --verbose (no --stream): periodic progress with token count
                            self._log_progress_if_due(
                                total, _event_start, _last_progress_time,
                                _progress_interval, shown_model, input_tokens,
                            )
                            _last_progress_time = time.perf_counter()

                elif type_value == "session.idle":
                    # End streaming with newline for full stream mode only
                    # (verbose_stream gets newline from print_completion in finally)
                    if should_print_progress() and is_full_stream():
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                    done.set()

            session.on(on_event)

            if should_print_progress() and not is_verbose_stream():
                # Show START message for full/debug modes (preview uses spinner only)
                tag = format_tag("START", color_index)
                mode = "full" if is_full_stream() else "debug"
                write_progress(f"{tag} Invoking GH Copilot CLI SDK (model={shown_model}, stream={mode})...")
            elif _is_verbose and not is_verbose_stream():
                logger.info("Invoking GH Copilot CLI SDK (model=%s, timeout=%ds)...", shown_model, timeout)

            # Start spinner if in preview mode
            if is_verbose_stream() and should_print_progress():
                ensure_spinner_running()

            await session.send({"prompt": prompt})

            # Wait for session.idle with timeout
            try:
                await asyncio.wait_for(done.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                raise ProviderTimeoutError(
                    f"Copilot SDK timeout after {timeout}s",
                    partial_result=ProviderResult(
                        stdout="\n".join(response_parts),
                        stderr="",
                        exit_code=-1,
                        duration_ms=0,
                        model=model,
                        command=("copilot-sdk",),
                    ),
                ) from None

        finally:
            # Unregister agent and stop spinner if last
            if agent_color_idx >= 0:
                clear_progress_line()
                unregister_agent(agent_id)
                stop_spinner_if_last()
            # Always destroy the session, but keep the client alive for reuse
            if session is not None:
                try:
                    await asyncio.wait_for(session.destroy(), timeout=5)
                except Exception:
                    logger.debug("Session destroy timeout/error (non-fatal)")

        result = "\n".join(response_parts)
        if not result.strip():
            raise ProviderError(
                f"Copilot SDK returned empty response for model {model}"
            )

        return result

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
        """Execute Copilot SDK with the given prompt.

        Synchronous wrapper around the async SDK call. Creates an event loop
        if one is not running, otherwise uses asyncio.run().

        Args:
            prompt: The prompt text to send to Copilot.
            model: Model to use. If None, uses default_model.
            timeout: Timeout in seconds. Must be positive (>= 1) if specified.
            settings_file: Path to settings file (validated but unused by SDK).
            cwd: Working directory for Copilot CLI.
            disable_tools: Ignored by this provider.
            allowed_tools: Ignored by this provider.
            no_cache: Ignored by this provider.
            color_index: Color index for terminal output differentiation.
            display_model: Display name for the model (used in logs).
            thinking: Ignored by this provider.
            cancel_token: Ignored by this provider.
            reasoning_effort: Ignored by this provider.

        Returns:
            ProviderResult containing response text, timing, and metadata.

        Raises:
            ValueError: If timeout is not positive (<=0).
            ProviderError: If SDK execution fails.
            ProviderTimeoutError: If execution exceeds timeout.

        """
        _ = disable_tools, allowed_tools, no_cache, thinking, cancel_token, reasoning_effort

        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        effective_model = model or self.default_model or "gpt-4o"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate settings (informational — SDK doesn't use settings files)
        validated_settings = self._resolve_settings(settings_file, effective_model)
        if validated_settings is not None:
            logger.debug(
                "Settings file validated but not passed to Copilot SDK: %s",
                validated_settings,
            )

        logger.debug(
            "Invoking Copilot SDK: model=%s, timeout=%ds, prompt_len=%d, cwd=%s",
            effective_model,
            effective_timeout,
            len(prompt),
            cwd,
        )

        start_time = time.perf_counter()
        original_command: tuple[str, ...] = ("copilot-sdk", "--model", effective_model)

        try:
            # Schedule async work on the persistent SDK event loop.
            # This loop stays alive across invoke() calls so that the
            # shared CopilotClient (and its asyncio transport) remains valid.
            loop = _get_event_loop()
            future = asyncio.run_coroutine_threadsafe(
                self._invoke_async(
                    prompt=prompt,
                    model=effective_model,
                    cwd=cwd,
                    timeout=effective_timeout,
                    color_index=color_index,
                    display_model=display_model,
                ),
                loop,
            )
            response_text = future.result(timeout=effective_timeout + 30)

        except ProviderTimeoutError:
            clear_progress_line()
            raise
        except ProviderError:
            clear_progress_line()
            raise
        except TimeoutError as e:
            # future.result() raises bare TimeoutError — convert to retryable
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            clear_progress_line()
            raise ProviderTimeoutError(
                f"Copilot SDK timeout after {duration_ms}ms"
            ) from e
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            clear_progress_line()
            raise ProviderError(
                f"Copilot SDK error after {duration_ms}ms: {e}"
            ) from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        input_tokens = self._estimate_tokens(len(prompt))
        output_tokens = self._estimate_tokens(len(response_text))
        # Skip completion log in preview mode - spinner already shows it
        if not is_verbose_stream():
            logger.info(
                "Copilot SDK completed: duration=%dms, in=~%d tokens, out=~%d tokens",
                duration_ms,
                input_tokens,
                output_tokens,
            )

        return ProviderResult(
            stdout=response_text,
            stderr="",
            exit_code=0,
            duration_ms=duration_ms,
            model=effective_model,
            command=original_command,
        )

    def parse_output(self, result: ProviderResult) -> str:
        """Extract response text from Copilot SDK output.

        Args:
            result: ProviderResult from invoke() containing response text.

        Returns:
            Extracted response text with whitespace stripped.

        """
        return result.stdout.strip()


async def _shutdown_shared_client() -> None:
    """Shut down the shared CopilotClient if one exists.

    Called at process exit or when the bmad-assist run completes.
    """
    global _shared_client, _shared_client_cwd

    with _client_lock:
        client = _shared_client
        _shared_client = None
        _shared_client_cwd = None

    if client is not None:
        try:
            await asyncio.wait_for(client.stop(), timeout=5)
            logger.debug("Shared CopilotClient stopped")
        except Exception:
            try:
                await client.force_stop()
            except Exception:
                pass


def shutdown_shared_client() -> None:
    """Synchronous wrapper to shut down the shared client.

    Safe to call from any context (async or sync). Typically called
    at the end of a bmad-assist run or via atexit to clean up the CLI subprocess.
    Also stops the persistent event loop.
    """
    global _shared_client, _loop

    if _shared_client is None:
        return

    # Schedule the async shutdown on the persistent loop
    loop = _loop
    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(_shutdown_shared_client(), loop)
        try:
            future.result(timeout=10)
        except Exception:
            # Last resort: force-kill the subprocess
            with _client_lock:
                if _shared_client is not None:
                    try:
                        _shared_client._process.kill()
                    except Exception:
                        pass
                    _shared_client = None
                    _shared_client_cwd = None
        # Stop the loop
        loop.call_soon_threadsafe(loop.stop)
    else:
        # No running loop — try creating a temporary one
        try:
            asyncio.run(_shutdown_shared_client())
        except Exception:
            with _client_lock:
                if _shared_client is not None:
                    try:
                        _shared_client._process.kill()
                    except Exception:
                        pass
                    _shared_client = None
                    _shared_client_cwd = None
