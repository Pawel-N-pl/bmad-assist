"""Google Cloud Code Assist provider using OpenClaw OAuth credentials.

This provider uses the same authentication method as OpenClaw - reading
OAuth credentials from ~/.openclaw/agents/main/agent/auth-profiles.json
and making direct API calls to Google Cloud Code Assist API.

This avoids requiring separate gemini CLI authentication.
"""

import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from bmad_assist.core.exceptions import ProviderError, ProviderExitCodeError
from bmad_assist.providers.base import BaseProvider, ProviderResult

logger = logging.getLogger(__name__)

# API Configuration
CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# OAuth client credentials - read from environment variables
# These should be set to the Google Cloud Code Assist OAuth credentials
# (same as used by gcloud CLI / Cloud Shell Editor)
CLIENT_ID = os.environ.get("GEMINI_CLOUDCODE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GEMINI_CLOUDCODE_CLIENT_SECRET", "")

# Headers for Cloud Code Assist API
HEADERS = {
    "User-Agent": "google-cloud-sdk vscode_cloudshelleditor/0.1",
    "X-Goog-Api-Client": "gl-node/22.17.0",
    "Client-Metadata": json.dumps({
        "ideType": "IDE_UNSPECIFIED",
        "platform": "PLATFORM_UNSPECIFIED",
        "pluginType": "GEMINI",
    }),
}

# Default timeout in seconds
DEFAULT_TIMEOUT: int = 300

# Auth profiles path
AUTH_PROFILES_PATH = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"


def _load_gemini_credentials() -> dict[str, Any] | None:
    """Load Google Gemini CLI credentials from OpenClaw auth-profiles.json.

    Returns:
        Dict with access, refresh, expires, projectId, email or None if not found.
    """
    if not AUTH_PROFILES_PATH.exists():
        logger.warning("OpenClaw auth-profiles.json not found at %s", AUTH_PROFILES_PATH)
        return None

    try:
        with open(AUTH_PROFILES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to read auth-profiles.json: %s", e)
        return None

    profiles = data.get("profiles", {})

    # Find google-gemini-cli profile
    for profile_id, profile in profiles.items():
        if profile.get("provider") == "google-gemini-cli" and profile.get("type") == "oauth":
            return {
                "access": profile.get("access"),
                "refresh": profile.get("refresh"),
                "expires": profile.get("expires"),
                "projectId": profile.get("projectId"),
                "email": profile.get("email"),
                "profile_id": profile_id,
            }

    logger.warning("No google-gemini-cli profile found in auth-profiles.json")
    return None


def _refresh_token(refresh_token: str, project_id: str) -> dict[str, Any]:
    """Refresh the OAuth access token.

    Args:
        refresh_token: The refresh token.
        project_id: Google Cloud project ID.

    Returns:
        Dict with new access token, refresh token, and expiry.

    Raises:
        ProviderError: If refresh fails.
    """
    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            raise ProviderError(f"Token refresh failed: {response.text}")

        data = response.json()

        # Calculate expiry (expires_in seconds - 5 min buffer)
        expires = int(time.time() * 1000) + (data["expires_in"] * 1000) - (5 * 60 * 1000)

        return {
            "access": data["access_token"],
            "refresh": data.get("refresh_token", refresh_token),
            "expires": expires,
            "projectId": project_id,
        }


def _save_refreshed_credentials(profile_id: str, new_creds: dict[str, Any]) -> None:
    """Save refreshed credentials back to auth-profiles.json.

    Args:
        profile_id: The profile ID to update.
        new_creds: New credentials dict with access, refresh, expires.
    """
    try:
        with open(AUTH_PROFILES_PATH, encoding="utf-8") as f:
            data = json.load(f)

        if profile_id in data.get("profiles", {}):
            data["profiles"][profile_id]["access"] = new_creds["access"]
            data["profiles"][profile_id]["refresh"] = new_creds["refresh"]
            data["profiles"][profile_id]["expires"] = new_creds["expires"]

            with open(AUTH_PROFILES_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            logger.debug("Saved refreshed credentials for %s", profile_id)
    except Exception as e:
        logger.warning("Failed to save refreshed credentials: %s", e)


def _get_valid_credentials() -> tuple[str, str]:
    """Get valid access token and project ID, refreshing if needed.

    Returns:
        Tuple of (access_token, project_id).

    Raises:
        ProviderError: If credentials not available or refresh fails.
    """
    creds = _load_gemini_credentials()
    if not creds:
        raise ProviderError(
            "Google Gemini credentials not found. "
            "Please authenticate with OpenClaw first: openclaw login google-gemini-cli"
        )

    access_token = creds.get("access")
    refresh_token = creds.get("refresh")
    expires = creds.get("expires", 0)
    project_id = creds.get("projectId")
    profile_id = creds.get("profile_id")

    if not access_token or not project_id:
        raise ProviderError("Invalid Google Gemini credentials - missing access token or projectId")

    # Check if token needs refresh (expired or within 5 min of expiry)
    now_ms = int(time.time() * 1000)
    if expires and now_ms >= expires - (5 * 60 * 1000):
        if not refresh_token:
            raise ProviderError("Token expired and no refresh token available")

        logger.info("Refreshing expired Google Cloud token")
        new_creds = _refresh_token(refresh_token, project_id)
        access_token = new_creds["access"]

        # Save back to auth-profiles.json
        if profile_id:
            _save_refreshed_credentials(profile_id, new_creds)

    return access_token, project_id


class GeminiCloudCodeProvider(BaseProvider):
    """Google Cloud Code Assist provider using OpenClaw OAuth credentials.

    This provider makes direct API calls to Google's Cloud Code Assist API,
    using OAuth credentials stored by OpenClaw. This avoids requiring
    separate gemini CLI authentication.

    Supported models:
        - gemini-3-pro-preview: Gemini 3 Pro (preview)
        - gemini-3-flash-preview: Gemini 3 Flash (preview)
        - gemini-2.5-pro: Gemini 2.5 Pro
        - gemini-2.5-flash: Gemini 2.5 Flash

    Example:
        >>> provider = GeminiCloudCodeProvider()
        >>> result = provider.invoke("Review this code", model="gemini-3-pro-preview")
    """

    @property
    def provider_name(self) -> str:
        """Return unique identifier for this provider."""
        return "gemini-cloudcode"

    @property
    def default_model(self) -> str | None:
        """Return default model when none specified."""
        return "gemini-3-pro-preview"

    def supports_model(self, model: str) -> bool:
        """Check if this provider supports the given model."""
        # Accept any gemini model - let API validate
        return True

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
    ) -> ProviderResult:
        """Execute Cloud Code Assist API call with the given prompt.

        Args:
            prompt: The prompt text to send.
            model: Model to use (gemini-3-pro-preview, gemini-2.5-flash, etc).
            timeout: Timeout in seconds.
            settings_file: Ignored (uses OpenClaw credentials).
            cwd: Ignored (API doesn't have workspace concept).
            disable_tools: Ignored (no tool support in simple mode).
            allowed_tools: Ignored.
            no_cache: Ignored.
            color_index: Color index for terminal output.
            display_model: Display name for the model.

        Returns:
            ProviderResult containing response text, exit code, and timing.

        Raises:
            ProviderError: If API call fails.
        """
        # Ignored parameters
        _ = settings_file, cwd, disable_tools, allowed_tools, no_cache, color_index

        effective_model = model or self.default_model or "gemini-2.5-flash"
        effective_timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

        logger.debug(
            "Invoking Cloud Code Assist: model=%s, timeout=%ds, prompt_len=%d",
            effective_model,
            effective_timeout,
            len(prompt),
        )

        start_time = time.perf_counter()

        try:
            # Get valid credentials (refreshing if needed)
            access_token, project_id = _get_valid_credentials()

            # Build request
            request_body = {
                "project": project_id,
                "model": effective_model,
                "request": {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": prompt}],
                        }
                    ],
                },
                "userAgent": "bmad-assist",
                "requestId": f"bmad-{int(time.time() * 1000)}",
            }

            # Make API call
            url = f"{CODE_ASSIST_ENDPOINT}/v1internal:streamGenerateContent?alt=sse"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                **HEADERS,
            }

            response_text_parts: list[str] = []

            with httpx.Client(timeout=effective_timeout) as client:
                with client.stream(
                    "POST",
                    url,
                    json=request_body,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = response.read().decode("utf-8", errors="replace")
                        raise ProviderExitCodeError(
                            f"Cloud Code Assist API error ({response.status_code}): {error_text}",
                            exit_code=1,
                        )

                    # Parse SSE stream
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue

                        json_str = line[5:].strip()
                        if not json_str:
                            continue

                        try:
                            chunk = json.loads(json_str)
                            response_data = chunk.get("response", {})
                            candidate = response_data.get("candidates", [{}])[0]
                            parts = candidate.get("content", {}).get("parts", [])

                            for part in parts:
                                if "text" in part:
                                    response_text_parts.append(part["text"])
                        except json.JSONDecodeError:
                            continue

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            response_text = "".join(response_text_parts)

            logger.info(
                "Cloud Code Assist completed: model=%s, duration=%dms, response_len=%d",
                effective_model,
                duration_ms,
                len(response_text),
            )

            return ProviderResult(
                stdout=response_text,
                stderr="",
                exit_code=0,
                duration_ms=duration_ms,
                model=display_model or effective_model,
                command=("cloudcode-api", effective_model),
            )

        except ProviderExitCodeError:
            raise
        except httpx.TimeoutException as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            raise ProviderError(f"Cloud Code Assist timeout after {duration_ms}ms: {e}") from e
        except Exception as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error("Cloud Code Assist failed: %s", e, exc_info=True)
            raise ProviderError(f"Cloud Code Assist failed: {e}") from e

    def parse_output(self, result: ProviderResult) -> str:
        """Extract response text from Cloud Code Assist output.

        The API response is already processed and stored in stdout.

        Args:
            result: The ProviderResult from invoke().

        Returns:
            The response text.
        """
        return result.stdout
