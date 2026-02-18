"""OpenCode SDK-based provider implementation.

This module implements the OpenCodeSDKProvider class that uses the official
opencode-ai Python SDK to communicate with an auto-managed ``opencode serve``
HTTP server process. It follows the same async-core pattern as claude_sdk.py:
async operations via ``run_async_in_thread()``, cooldown-based fallback to
subprocess on server startup failures, and clean one-shot sessions per invoke.

Key Design:
    - Auto-managed server lifecycle (lazy start, health-check, signal cleanup)
    - One-shot sessions: create -> chat -> extract messages -> delete
    - Cooldown fallback to OpenCodeProvider on server startup failures ONLY
    - Bearer token auth for localhost security
    - Double-checked locking for concurrent validator access

Example:
    >>> from bmad_assist.providers.opencode_sdk import OpenCodeSDKProvider
    >>> provider = OpenCodeSDKProvider()
    >>> result = provider.invoke("Hello", model="opencode/claude-sonnet-4")
    >>> print(provider.parse_output(result))

"""

import asyncio
import atexit
import base64
import contextlib
import json
import logging
import os
import secrets
import shutil
import socket
import threading
import time
from pathlib import Path
from subprocess import DEVNULL, Popen

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
    register_child_pgid,
    should_print_progress,
    unregister_child_pgid,
    validate_settings_file,
    write_progress,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Module-Level Server State (singleton per process)
# =============================================================================

_server_process: Popen[bytes] | None = None
_server_port: int | None = None
_server_token: str | None = None
_server_lock = threading.Lock()
_atexit_registered: bool = False

# Cooldown-based retry for server startup failures
# Note: float assignment is GIL-atomic on CPython. Document this dependency
# for future free-threaded Python (PEP 703) compatibility.
_sdk_init_failed_at: float = 0.0
_SDK_RETRY_COOLDOWN: float = 120.0

# Constants
DEFAULT_TIMEOUT: int = 300
DEFAULT_SERVER_PORT: int = 14096
_MAX_PORT_RETRIES: int = 3
_HEALTH_CHECK_POLLS: int = 20
_HEALTH_CHECK_INTERVAL: float = 0.5

# PID file directory
_PID_DIR = Path.home() / ".bmad-assist"

# Display names for common tools (same as opencode.py)
_COMMON_TOOL_NAMES: frozenset[str] = frozenset(
    {"Edit", "Write", "Bash", "Glob", "Grep", "WebFetch", "WebSearch", "Read"}
)

# Tool name normalization: OpenCode returns lowercase, we use PascalCase
_TOOL_NAME_MAP: dict[str, str] = {
    "bash": "Bash",
    "edit": "Edit",
    "write": "Write",
    "read": "Read",
    "glob": "Glob",
    "grep": "Grep",
    "webfetch": "WebFetch",
    "websearch": "WebSearch",
}

# =============================================================================
# Auth Helpers
# =============================================================================

# OpenCode server uses Basic auth with fixed username "opencode" and the
# password from OPENCODE_SERVER_PASSWORD env var.
_BASIC_AUTH_USERNAME = "opencode"


def _basic_auth_header(password: str) -> str:
    """Build Basic auth header value for OpenCode server.

    Args:
        password: Server password (from OPENCODE_SERVER_PASSWORD).

    Returns:
        Header value string, e.g. "Basic b3BlbmNvZGU6cGFzcw==".

    """
    credentials = base64.b64encode(
        f"{_BASIC_AUTH_USERNAME}:{password}".encode()
    ).decode()
    return f"Basic {credentials}"


# =============================================================================
# Server Lifecycle Functions
# =============================================================================


def _health_check(port: int, token: str | None = None, timeout: float = 2.0) -> bool:
    """Check if OpenCode server is healthy AND accepts our credentials.

    Uses a one-shot httpx.get() to avoid resource leaks from persistent clients.
    Requires 2xx response (not just < 500) to confirm the server accepts our
    auth token. This prevents false positives from stale servers with different
    passwords that would respond with 401.

    Args:
        port: Server port to check.
        token: Optional auth token (password) to include as Basic auth.
        timeout: HTTP request timeout in seconds.

    Returns:
        True if server responds with 2xx, False otherwise.

    """
    try:
        import httpx

        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = _basic_auth_header(token)
        response = httpx.get(
            f"http://127.0.0.1:{port}/api/session",
            timeout=timeout,
            headers=headers if headers else None,
        )
        return response.is_success
    except Exception:
        return False


def _find_free_port() -> int:
    """Find a free port on localhost.

    Uses socket.bind() with port 0 to get OS-assigned port, then releases it.
    There is an inherent TOCTOU race between close() and server bind(), which
    is mitigated by retry logic in _ensure_server().

    Returns:
        Available port number.

    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _generate_auth_token() -> str:
    """Generate a random bearer token for server authentication.

    Returns:
        URL-safe random token string (43 characters).

    """
    return secrets.token_urlsafe(32)


def _write_pid_file(port: int, pid: int, token: str) -> None:
    """Write server PID file with port, PID, and auth token.

    Args:
        port: Server port number.
        pid: Server process PID.
        token: Bearer auth token.

    """
    _PID_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = _PID_DIR / f"opencode-server-{port}.pid"
    pid_file.write_text(json.dumps({"port": port, "pid": pid, "token": token}))
    pid_file.chmod(0o600)  # Restrict: owner-only read/write (token is sensitive)


def _read_pid_file(port: int) -> tuple[int, int, str] | None:
    """Read and validate a port-specific PID file.

    Args:
        port: Port number to look up.

    Returns:
        Tuple of (port, pid, token) if file exists and process is alive,
        None otherwise. Cleans up stale PID files.

    """
    pid_file = _PID_DIR / f"opencode-server-{port}.pid"
    if not pid_file.exists():
        return None

    try:
        data = json.loads(pid_file.read_text())
        pid = data["pid"]
        token = data["token"]
        file_port = data["port"]

        # Check if process is alive
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            # Process dead, clean up stale file
            pid_file.unlink(missing_ok=True)
            return None

        return (file_port, pid, token)
    except (json.JSONDecodeError, KeyError, OSError):
        # Corrupt file, clean up
        pid_file.unlink(missing_ok=True)
        return None


def _cleanup_pid_files() -> None:
    """Remove stale PID files for dead server processes."""
    if not _PID_DIR.exists():
        return

    for pid_file in _PID_DIR.glob("opencode-server-*.pid"):
        try:
            data = json.loads(pid_file.read_text())
            pid = data["pid"]
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                pid_file.unlink(missing_ok=True)
        except (json.JSONDecodeError, KeyError, OSError):
            pid_file.unlink(missing_ok=True)


def _cleanup_server() -> None:
    """Terminate the managed server process and clean up PID file."""
    global _server_process, _server_port, _server_token

    if _server_process is not None:
        try:
            _server_process.terminate()
            try:
                _server_process.wait(timeout=5)
            except Exception:
                _server_process.kill()
            unregister_child_pgid(_server_process.pid)
        except Exception:
            pass

    if _server_port is not None:
        pid_file = _PID_DIR / f"opencode-server-{_server_port}.pid"
        pid_file.unlink(missing_ok=True)

    _server_process = None
    _server_port = None
    _server_token = None


def _shutdown_server() -> None:
    """Atexit handler for graceful server shutdown."""
    _cleanup_server()


def _resolve_opencode_binary() -> str:
    """Resolve the opencode CLI binary path.

    Checks BMAD_OPENCODE_CLI_PATH env var first, then falls back to
    shutil.which("opencode").

    Returns:
        Path to opencode binary.

    Raises:
        ProviderError: If binary not found.

    """
    env_path = os.environ.get("BMAD_OPENCODE_CLI_PATH")
    if env_path:
        if os.path.isfile(env_path) and os.access(env_path, os.X_OK):
            return env_path
        raise ProviderError(f"BMAD_OPENCODE_CLI_PATH points to invalid path: {env_path}")

    binary = shutil.which("opencode")
    if binary:
        return binary

    raise ProviderError("OpenCode CLI not found. Install 'opencode' or set BMAD_OPENCODE_CLI_PATH")


def _ensure_server() -> tuple[int, str]:
    """Ensure OpenCode server is running and healthy.

    Uses double-checked locking: quick health check without lock first,
    then lock only if server needs starting. This prevents 10s serialization
    with 4 parallel validators.

    Returns:
        Tuple of (port, auth_token).

    Raises:
        ProviderError: If server cannot be started after retries.

    """
    global _server_process, _server_port, _server_token, _atexit_registered

    # Quick check WITHOUT lock
    if _server_port is not None and _health_check(_server_port, _server_token):
        return (_server_port, _server_token or "")

    with _server_lock:
        # Re-check under lock (double-checked locking)
        if _server_port is not None and _health_check(_server_port, _server_token):
            return (_server_port, _server_token or "")

        # Server unhealthy or not started -- clean up if needed
        if _server_port is not None:
            logger.warning("OpenCode server unhealthy, restarting...")
            _cleanup_server()

        # Clean up stale PID files from dead processes
        _cleanup_pid_files()

        # Check PID file for existing server on default port
        pid_info = _read_pid_file(DEFAULT_SERVER_PORT)
        if pid_info is not None:
            file_port, _, file_token = pid_info
            if _health_check(file_port, file_token):
                logger.info("Reusing existing OpenCode server on port %d", file_port)
                _server_port = file_port
                _server_token = file_token
                return (file_port, file_token)

        # Start new server with retry for port conflicts
        binary = _resolve_opencode_binary()
        last_error: Exception | None = None

        for attempt in range(_MAX_PORT_RETRIES):
            port = DEFAULT_SERVER_PORT if attempt == 0 else _find_free_port()
            token = _generate_auth_token()

            logger.info(
                "Starting OpenCode server: port=%d, attempt=%d/%d",
                port,
                attempt + 1,
                _MAX_PORT_RETRIES,
            )

            env = os.environ.copy()
            env["OPENCODE_SERVER_PASSWORD"] = token

            try:
                process = Popen(
                    [binary, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
                    stdout=DEVNULL,
                    stderr=DEVNULL,
                    start_new_session=True,
                    env=env,
                )
            except FileNotFoundError as e:
                raise ProviderError(f"OpenCode binary not found: {binary}") from e

            # Register for signal handler cleanup
            register_child_pgid(process.pid)

            # Poll health check
            healthy = False
            for _ in range(_HEALTH_CHECK_POLLS):
                time.sleep(_HEALTH_CHECK_INTERVAL)
                if process.poll() is not None:
                    # Process exited prematurely
                    unregister_child_pgid(process.pid)
                    logger.warning(
                        "OpenCode server exited prematurely: port=%d, returncode=%d",
                        port,
                        process.returncode,
                    )
                    break
                if _health_check(port, token):
                    healthy = True
                    break

            if healthy:
                _server_process = process
                _server_port = port
                _server_token = token
                _write_pid_file(port, process.pid, token)

                # Register atexit handler (once)
                if not _atexit_registered:
                    atexit.register(_shutdown_server)
                    _atexit_registered = True

                logger.info("OpenCode server started: port=%d, pid=%d", port, process.pid)
                return (port, token)

            # Port conflict or startup failure -- retry with new port
            last_error = ProviderError(f"OpenCode server failed to start on port {port}")
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                process.kill()
            unregister_child_pgid(process.pid)

        raise ProviderError(
            f"OpenCode server failed to start after {_MAX_PORT_RETRIES} attempts: {last_error}"
        )


# =============================================================================
# Provider Class
# =============================================================================


class OpenCodeSDKProvider(BaseProvider):
    """OpenCode SDK-based provider using auto-managed HTTP server.

    Uses the official opencode-ai Python SDK to communicate with an
    ``opencode serve`` process. Provides SDK-level session management,
    native cancel support via ``session.abort()``, and cooldown-based
    fallback to subprocess on server startup failures.

    Example:
        >>> provider = OpenCodeSDKProvider()
        >>> result = provider.invoke("Hello", model="opencode/claude-sonnet-4")
        >>> print(provider.parse_output(result))

    """

    def __init__(self) -> None:
        """Initialize provider with thread-safe session tracking."""
        self._active_sessions: dict[int, str] = {}  # thread_id -> session_id
        self._sessions_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider."""
        return "opencode-sdk"

    @property
    def default_model(self) -> str | None:
        """Return default model (matches subprocess provider)."""
        return "opencode/claude-sonnet-4"

    def supports_model(self, model: str) -> bool:
        """Check if model has valid 'provider/model' format.

        Args:
            model: Model identifier to check.

        Returns:
            True if model contains '/' and is non-empty, False otherwise.

        """
        return bool(model) and "/" in model

    def _resolve_settings(
        self,
        settings_file: Path | None,
        model: str,
    ) -> Path | None:
        """Validate settings file (OpenCode doesn't use them)."""
        if settings_file is None:
            return None

        validated = validate_settings_file(
            settings_file=settings_file,
            provider_name=self.provider_name,
            model=model,
        )
        if validated:
            logger.debug(
                "Settings file validated but OpenCode SDK doesn't use settings: %s",
                validated,
            )
        return validated

    async def _invoke_async(
        self,
        prompt: str,
        model: str,
        cwd: Path | None,
        allowed_tools: list[str] | None = None,
        color_index: int | None = None,
        display_model: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> tuple[str, str | None]:
        """Execute SDK query with live SSE event streaming for progress.

        Opens an SSE event stream (``event.list()``) before firing the chat
        request so we can display real-time progress (text deltas, tool calls,
        cost/tokens) while the LLM works. The chat response is used for the
        final text extraction; the event stream is purely for live display.

        Args:
            prompt: The prompt text.
            model: Model in 'provider/model' format.
            cwd: Working directory (reserved for future use).
            allowed_tools: Optional tool restriction list.
            color_index: Color index for progress output.
            display_model: Display name for the model.
            timeout: HTTP request timeout in seconds. Applied to the SDK
                client so the chat request doesn't hit the default 60s limit.

        Returns:
            Tuple of (response_text, session_id).

        Raises:
            ProviderError: If SDK call fails.

        """
        _ = cwd  # Reserved: server uses its own working directory
        port, token = _ensure_server()

        try:
            from opencode_ai import AsyncOpencode
            from opencode_ai.types import TextPart as SDKTextPart
            from opencode_ai.types.event_list_response import (
                EventMessagePartUpdated,
                EventSessionError,
                EventSessionIdle,
            )
            from opencode_ai.types.step_finish_part import (
                StepFinishPart as SDKStepFinishPart,
            )
            from opencode_ai.types.tool_part import ToolPart as SDKToolPart
        except ImportError as e:
            raise ProviderError(
                "opencode-ai package not installed. Install with: "
                "pip install 'opencode-ai>=0.1.0a36,<0.2.0'"
            ) from e

        # Build client with Basic auth header and sufficient timeout.
        # The SDK default read timeout is 60s which is too short for LLM
        # chat with tool use. Use our provider timeout for HTTP requests.
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = _basic_auth_header(token)

        client = AsyncOpencode(
            base_url=f"http://127.0.0.1:{port}",
            default_headers=headers if headers else None,
            timeout=float(timeout),
        )

        # Parse model: "provider_id/model_id"
        parts = model.split("/", 1)
        if len(parts) != 2:
            raise ProviderError(f"Invalid model format: {model}, expected 'provider/model'")
        provider_id, model_id = parts

        shown_model = display_model or model
        logger.info(
            "OpenCode SDK: model=%s, prompt=%d chars, port=%d",
            shown_model,
            len(prompt),
            port,
        )

        # Build tool restriction prompt if needed
        final_prompt = prompt
        if allowed_tools is not None:
            allowed_set = set(allowed_tools)
            restricted_tools = sorted(_COMMON_TOOL_NAMES - allowed_set)
            if restricted_tools:
                allowed_str = ", ".join(allowed_tools)
                restricted_str = ", ".join(restricted_tools)
                final_prompt = prompt + (
                    "\n\n**CRITICAL - TOOL ACCESS RESTRICTIONS (READ CAREFULLY):**\n"
                    f"You are a CODE REVIEWER with LIMITED tool access.\n\n"
                    f"ALLOWED tools ONLY: {allowed_str}\n"
                    f"FORBIDDEN tools (NEVER USE): {restricted_str}\n\n"
                    "**MANDATORY RULES:**\n"
                    "1. Use `Read` for files - NEVER use Bash for cat/head/tail\n"
                    "2. Use `Glob` for patterns - NEVER use Bash for ls/find\n"
                    "3. Use `Grep` for search - NEVER use Bash for grep/rg\n"
                    "4. You CANNOT modify any files - this is READ-ONLY\n"
                    "5. Using Bash will FAIL - these tools are disabled for reviewers.\n\n"
                    "Your task: Produce a CODE REVIEW REPORT. No file modifications.\n"
                )

        # Create session (extra_body={} works around SDK not sending JSON body)
        session = await client.session.create(extra_body={})
        session_id = session.id

        # Track session for cross-thread cancel
        with self._sessions_lock:
            self._active_sessions[threading.get_ident()] = session_id

        try:
            # --- SSE event stream for live progress ---
            # Open BEFORE chat so we don't miss early events.
            event_stream = None
            event_task: asyncio.Task[None] | None = None
            # Accumulate text from events (used as primary response source)
            streamed_text: dict[str, str] = {}  # part_id -> full text
            restricted_warned: set[str] = set()

            async def _consume_events() -> None:
                """Consume SSE events for live progress display."""
                nonlocal event_stream
                text_lens: dict[str, int] = {}  # part_id -> last seen char count
                try:
                    assert event_stream is not None
                    async for event in event_stream:
                        if isinstance(event, EventMessagePartUpdated):
                            part = event.properties.part
                            if part.session_id != session_id:
                                continue

                            if isinstance(part, SDKTextPart):
                                streamed_text[part.id] = part.text
                                old_len = text_lens.get(part.id, 0)
                                new_len = len(part.text)
                                if new_len > old_len and should_print_progress():
                                    delta = part.text[old_len:]
                                    text_lens[part.id] = new_len
                                    tag = format_tag("ASSISTANT", color_index)
                                    if is_full_stream():
                                        write_progress(f"{tag} {delta}")
                                    else:
                                        preview = delta[:200]
                                        if len(delta) > 200:
                                            preview += "..."
                                        write_progress(f"{tag} {preview}")

                            elif isinstance(part, SDKToolPart):
                                raw_tool = part.tool or "unknown"
                                # Normalize: SDK returns lowercase, allowed_tools uses PascalCase
                                tool_name = _TOOL_NAME_MAP.get(
                                    raw_tool.lower(), raw_tool.capitalize()
                                )
                                # Log restricted tool violations
                                if (
                                    allowed_tools is not None
                                    and tool_name not in (allowed_tools or [])
                                    and tool_name not in restricted_warned
                                ):
                                    restricted_warned.add(tool_name)
                                    logger.warning(
                                        "OpenCode SDK: Restricted tool '%s' attempted",
                                        tool_name,
                                    )

                                if should_print_progress():
                                    tag = format_tag(f"TOOL {tool_name}", color_index)
                                    details = ""
                                    state_input = getattr(part.state, "input", None)
                                    if state_input:
                                        details = extract_tool_details(
                                            tool_name,
                                            dict(state_input)
                                        )
                                    if details:
                                        write_progress(f"{tag} {details}")
                                    else:
                                        write_progress(f"{tag}")

                            elif isinstance(part, SDKStepFinishPart):
                                if should_print_progress():
                                    tag = format_tag("RESULT", color_index)
                                    cost = part.cost or 0
                                    tokens = part.tokens
                                    write_progress(
                                        f"{tag} cost={cost:.4f} tokens={tokens}"
                                    )

                        elif isinstance(event, EventSessionIdle):
                            if event.properties.session_id == session_id:
                                break

                        elif isinstance(event, EventSessionError):
                            sid = getattr(event.properties, "session_id", None)
                            if sid == session_id:
                                break

                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.debug("Event stream error (non-fatal): %s", e)

            try:
                event_stream = await client.event.list(timeout=float(timeout))
                event_task = asyncio.create_task(_consume_events())
            except Exception as e:
                logger.debug("Failed to open event stream (no live progress): %s", e)

            # --- Progress header ---
            if should_print_progress():
                tag = format_tag("START", color_index)
                write_progress(f"{tag} OpenCode SDK (model={shown_model})")
                tag = format_tag("PROMPT", color_index)
                write_progress(f"{tag} {len(prompt):,} chars")
                tag = format_tag("WAITING", color_index)
                write_progress(f"{tag} Streaming response...")

            # --- Fire chat (blocks until assistant completes) ---
            response = await client.session.chat(
                id=session_id,
                model_id=model_id,
                parts=[{"type": "text", "text": final_prompt}],
                provider_id=provider_id,
            )

            # Cancel event stream (chat is done)
            if event_task is not None:
                event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await event_task
            if event_stream is not None:
                with contextlib.suppress(Exception):
                    await event_stream.close()

            # Check for error in response
            if response.error is not None:
                error_info = str(response.error)
                raise ProviderError(f"OpenCode SDK error: {error_info}")

            # --- Extract response text ---
            # Primary: use text accumulated from SSE events (most reliable,
            # gives us the full text we already streamed to progress)
            response_text = "".join(streamed_text.values())

            if not response_text:
                # Fallback: fetch messages via REST
                messages = await client.session.messages(id=session_id)
                response_parts: list[str] = []
                for msg_item in reversed(messages):
                    if msg_item.info.role == "assistant":
                        for part in msg_item.parts:
                            if isinstance(part, SDKTextPart):
                                response_parts.append(part.text)
                        break
                response_text = "".join(response_parts)

            if not response_text:
                # Last resort: stringify response object
                fallback = str(response)
                logger.debug("No text parts found, using fallback: %s", fallback[:200])
                if fallback:
                    response_text = fallback

            if not response_text:
                raise ProviderError("No response received from OpenCode SDK")

            return (response_text, session_id)

        finally:
            # Best-effort session cleanup
            try:
                await client.session.delete(id=session_id)
            except Exception as e:
                logger.warning("Failed to delete session %s: %s", session_id, e)

            # Clear session tracking
            with self._sessions_lock:
                self._active_sessions.pop(threading.get_ident(), None)

    async def _invoke_with_cancel(
        self,
        prompt: str,
        model: str,
        cwd: Path | None,
        allowed_tools: list[str] | None,
        cancel_token: threading.Event,
        timeout: int,
        color_index: int | None = None,
        display_model: str | None = None,
    ) -> tuple[str, str | None]:
        """Execute SDK query with cancel_token support.

        Runs SDK query and cancel monitor as concurrent tasks.

        """
        sdk_task = asyncio.create_task(
            self._invoke_async(
                prompt, model, cwd, allowed_tools, color_index, display_model, timeout
            )
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

        # Timeout -- neither finished
        if not done:
            raise TimeoutError

        # Cancel was triggered
        if cancel_task in done and sdk_task not in done:
            logger.info("Cancel token set, aborting OpenCode SDK session")
            # Try to abort active session
            session_id: str | None = None
            with self._sessions_lock:
                thread_id = threading.get_ident()
                session_id = self._active_sessions.get(thread_id)

            if session_id:
                try:
                    port, token = _server_port or DEFAULT_SERVER_PORT, _server_token or ""
                    from opencode_ai import AsyncOpencode

                    abort_headers: dict[str, str] = {}
                    if token:
                        abort_headers["Authorization"] = _basic_auth_header(token)
                    abort_client = AsyncOpencode(
                        base_url=f"http://127.0.0.1:{port}",
                        default_headers=abort_headers if abort_headers else None,
                    )
                    await abort_client.session.abort(id=session_id)
                except Exception as e:
                    logger.debug("Failed to abort session %s: %s", session_id, e)

            raise asyncio.CancelledError

        # SDK completed
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
        """Execute OpenCode SDK with the given prompt.

        Args:
            prompt: The prompt text to send.
            model: Model in 'provider/model' format. Defaults to 'opencode/claude-sonnet-4'.
            timeout: Timeout in seconds. Defaults to 300.
            settings_file: Settings file (validated but not used by OpenCode).
            cwd: Working directory for the server.
            disable_tools: Disable tools (uses prompt injection).
            allowed_tools: List of allowed tool names.
            no_cache: Ignored (OpenCode doesn't support).
            color_index: Color index for progress output.
            display_model: Display name for the model.
            thinking: Ignored.
            cancel_token: Threading event for cancellation.
            reasoning_effort: Ignored.

        Returns:
            ProviderResult with response text.

        Raises:
            ProviderError: If execution fails.
            ProviderTimeoutError: If timeout exceeded.

        """
        # Normalize disable_tools early so cooldown fallback gets correct allowed_tools
        if disable_tools and allowed_tools is None:
            allowed_tools = []

        # Cooldown check: delegate to subprocess if SDK init recently failed
        global _sdk_init_failed_at
        sdk_cooldown_active = (
            _sdk_init_failed_at > 0
            and (time.monotonic() - _sdk_init_failed_at) < _SDK_RETRY_COOLDOWN
        )
        if sdk_cooldown_active:
            from bmad_assist.providers.opencode import OpenCodeProvider

            remaining = _SDK_RETRY_COOLDOWN - (time.monotonic() - _sdk_init_failed_at)
            logger.info(
                "SDK init cooldown active (retry in %.0fs), using subprocess",
                remaining,
            )
            return OpenCodeProvider().invoke(
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
                thinking=thinking,
                cancel_token=cancel_token,
                reasoning_effort=reasoning_effort,
            )

        # Ignored parameters
        _ = no_cache, thinking, reasoning_effort

        # Validate timeout
        if timeout is not None and timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")

        # Resolve model
        effective_model = model or self.default_model or "opencode/claude-sonnet-4"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        # Validate model format
        if not self.supports_model(effective_model):
            raise ProviderError(
                f"Invalid model format '{effective_model}' for OpenCode SDK provider. "
                "Expected 'provider/model' (e.g., 'opencode/claude-sonnet-4')"
            )

        # Validate settings (logged but not used)
        self._resolve_settings(settings_file, effective_model)

        shown_model = display_model or effective_model

        # Log SDK retry after cooldown expiry
        if _sdk_init_failed_at > 0:
            elapsed = time.monotonic() - _sdk_init_failed_at
            logger.info(
                "SDK retrying after %.0fs cooldown (failed %.0fs ago)",
                _SDK_RETRY_COOLDOWN,
                elapsed,
            )

        logger.debug(
            "Invoking OpenCode SDK: model=%s, display_model=%s, timeout=%ds, prompt_len=%d",
            effective_model,
            shown_model,
            effective_timeout,
            len(prompt),
        )

        start_time = time.perf_counter()
        command: tuple[str, ...] = ("opencode-sdk", "session.chat", effective_model)
        session_id: str | None = None

        try:
            from bmad_assist.core.async_utils import run_async_in_thread

            if cancel_token is not None:
                response_text, session_id = run_async_in_thread(
                    self._invoke_with_cancel(
                        prompt,
                        effective_model,
                        cwd,
                        allowed_tools,
                        cancel_token,
                        effective_timeout,
                        color_index,
                        display_model,
                    )
                )
            else:
                response_text, session_id = run_async_in_thread(
                    asyncio.wait_for(
                        self._invoke_async(
                            prompt,
                            effective_model,
                            cwd,
                            allowed_tools,
                            color_index,
                            display_model,
                            effective_timeout,
                        ),
                        timeout=effective_timeout,
                    )
                )

        except asyncio.CancelledError:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info("OpenCode SDK cancelled after %dms", duration_ms)
            return ProviderResult(
                stdout="",
                stderr="",
                exit_code=-15,
                duration_ms=duration_ms,
                model=shown_model,
                command=command,
            )

        except ImportError as e:
            raise ProviderError(
                "opencode-ai package not installed. Install with: "
                "pip install 'opencode-ai>=0.1.0a36,<0.2.0'"
            ) from e

        except ProviderTimeoutError:
            raise

        except ProviderError as e:
            # Check if this is a server startup failure (set cooldown)
            error_str = str(e)
            if "failed to start" in error_str.lower() or "not found" in error_str.lower():
                _sdk_init_failed_at = time.monotonic()
                logger.warning("SDK init failure, cooldown set: %s", error_str[:200])
            raise

        except FileNotFoundError as e:
            _sdk_init_failed_at = time.monotonic()
            raise ProviderError("OpenCode CLI not found. Is 'opencode' in PATH?") from e

        except ConnectionError as e:
            # Runtime connection error -- NO cooldown (F9)
            raise ProviderError(f"OpenCode SDK connection error: {e}") from e

        except TimeoutError as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            raise ProviderTimeoutError(f"OpenCode SDK timeout after {effective_timeout}s") from e

        except Exception as e:
            # Generic error -- NO cooldown for app-level errors
            logger.error("Unexpected OpenCode SDK error: %s", e)
            raise ProviderError(f"Unexpected OpenCode SDK error: {e}") from e

        duration_ms = int((time.perf_counter() - start_time) * 1000)

        # Clear cooldown on success
        if _sdk_init_failed_at > 0:
            logger.info("OpenCode SDK recovered, clearing cooldown")
            _sdk_init_failed_at = 0.0

        logger.info(
            "OpenCode SDK completed: duration=%dms, response_len=%d",
            duration_ms,
            len(response_text),
        )

        return ProviderResult(
            stdout=response_text,
            stderr="",
            exit_code=0,
            duration_ms=duration_ms,
            model=shown_model,
            command=command,
            provider_session_id=session_id,
        )

    def parse_output(self, result: ProviderResult) -> str:
        """Extract response text from SDK output.

        Args:
            result: ProviderResult from invoke().

        Returns:
            Stripped response text.

        """
        return result.stdout.strip()

    def cancel(self) -> None:
        """Cancel all active sessions via session.abort().

        Thread-safe: reads session IDs from _active_sessions under lock,
        then fires abort requests outside the lock.

        """
        with self._sessions_lock:
            active = dict(self._active_sessions)

        if not active:
            return

        port = _server_port
        token = _server_token
        if port is None:
            return

        for thread_id, session_id in active.items():
            try:
                import httpx

                cancel_headers: dict[str, str] = {}
                if token:
                    cancel_headers["Authorization"] = _basic_auth_header(token)
                httpx.post(
                    f"http://127.0.0.1:{port}/api/session/{session_id}/abort",
                    headers=cancel_headers,
                    timeout=2.0,
                )
                logger.info("Aborted session %s (thread %d)", session_id, thread_id)
            except Exception as e:
                logger.debug("Failed to abort session %s: %s", session_id, e)
