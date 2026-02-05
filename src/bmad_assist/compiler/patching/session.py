"""LLM session orchestrator for applying workflow patches.

This module handles orchestrating LLM calls to apply transforms
to a workflow, with retry logic and failure tracking.

Classes:
    PatchSession: Orchestrates LLM calls to apply transforms

Functions:
    extract_workflow_from_response: Extract workflow content from LLM response
"""

import logging
import re
from pathlib import Path

from bmad_assist.compiler.patching.config import get_patcher_config
from bmad_assist.compiler.patching.transforms import fix_xml_entities, format_transform_prompt
from bmad_assist.compiler.patching.types import TransformResult
from bmad_assist.core.exceptions import PatchError
from bmad_assist.providers.base import BaseProvider

logger = logging.getLogger(__name__)


def extract_workflow_from_response(response: str) -> str | None:
    """Extract workflow content from LLM response.

    Looks for content between <transformed-document> tags (primary)
    or <workflow> tags (legacy fallback).

    Args:
        response: LLM response text.

    Returns:
        Extracted workflow content (without tags), or None if not found.

    """
    # Primary: look for <transformed-document> tags
    pattern = r"<transformed-document>(.*?)</transformed-document>"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        return match.group(1).strip()

    # Fallback: look for <workflow> tags (legacy)
    pattern = r"<workflow>(.*?)</workflow>"
    match = re.search(pattern, response, re.DOTALL)

    if match:
        return match.group(1).strip()

    return None


class PatchSession:
    """Orchestrates LLM calls to apply transforms to a workflow.

    Sends all transform instructions in a single prompt to the LLM.
    Includes retry logic for failed attempts.

    Attributes:
        workflow_content: Current workflow content.
        instructions: List of transform instructions (strings).
        provider: LLM provider instance.
        model: Model name to use (CLI model identifier).
        display_model: Human-readable model name for logging.
        timeout: Timeout in seconds.
        settings_file: Path to provider settings JSON file.

    """

    def __init__(
        self,
        workflow_content: str,
        instructions: list[str],
        provider: BaseProvider,
        *,
        model: str | None = None,
        display_model: str | None = None,
        timeout: int | None = None,
        settings_file: Path | None = None,
    ) -> None:
        """Initialize patch session.

        Args:
            workflow_content: Initial workflow content.
            instructions: List of transform instructions to apply in order.
            provider: LLM provider instance for making calls.
            model: Model name to use (e.g., "opus", "sonnet"). If None, uses provider default.
            display_model: Human-readable model name for logging (e.g., "glm-4.7"). If None, uses model.
            timeout: Timeout in seconds. If None, uses config default.
            settings_file: Path to provider settings JSON file. If None, uses provider defaults.

        Raises:
            PatchError: If workflow_content is empty or instructions list is empty.

        """
        if not workflow_content or not workflow_content.strip():
            raise PatchError("Workflow content cannot be empty")

        if not instructions:
            raise PatchError("Instructions list cannot be empty")

        config = get_patcher_config()

        self.workflow_content = workflow_content
        self.instructions = instructions
        self.provider = provider
        self.model = model
        self.display_model = display_model
        self.timeout = timeout or config.timeout
        self.settings_file = settings_file
        self.max_retries = config.max_retries

    def run(self) -> tuple[str, list[TransformResult]]:
        """Run the patch session, applying all transforms in a single LLM call.

        Returns:
            Tuple of (final_workflow_content, list_of_transform_results).

        """
        session_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                # Format prompt with all instructions
                prompt = format_transform_prompt(
                    self.instructions,
                    self.workflow_content,
                )

                logger.debug(
                    "Sending prompt with %d instructions (attempt %d/%d)",
                    len(self.instructions),
                    attempt + 1,
                    self.max_retries,
                )

                # Single LLM call with tools disabled and no caching
                # (one-shot prompt, cache overhead is wasteful)
                result = self.provider.invoke(
                    prompt,
                    model=self.model,
                    display_model=self.display_model,
                    timeout=self.timeout,
                    settings_file=self.settings_file,
                    disable_tools=True,
                    no_cache=True,
                )

                # Parse response
                response = self.provider.parse_output(result)
                logger.debug("LLM response length: %d chars", len(response))

                # Extract transformed workflow
                new_workflow = extract_workflow_from_response(response)

                if new_workflow is None:
                    logger.warning(
                        "Transform failed: missing <transformed-document> tag, attempt %d/%d",
                        attempt + 1,
                        self.max_retries,
                    )
                    continue

                # Fix any XML entity issues (LLMs may convert &lt; to <)
                new_workflow = fix_xml_entities(new_workflow)

                # Check if content changed (no-op detection)
                if new_workflow.strip() == self.workflow_content.strip():
                    logger.warning(
                        "Transform failed: no transformation applied, attempt %d/%d",
                        attempt + 1,
                        self.max_retries,
                    )
                    continue

                # Success - all instructions applied
                results = [
                    TransformResult(
                        success=True,
                        transform_index=i,
                    )
                    for i in range(len(self.instructions))
                ]

                return new_workflow, results

            except Exception as e:
                session_error = e
                logger.warning(
                    "Session crashed: %s, attempt %d/%d",
                    str(e),
                    attempt + 1,
                    self.max_retries,
                )
                continue

        # All retries exhausted - return failure results
        if session_error:
            reason = f"Provider error after {self.max_retries} attempts: {session_error}"
        else:
            reason = "LLM response missing <transformed-document> tag after retries"

        results = [
            TransformResult(
                success=False,
                transform_index=i,
                reason=reason,
            )
            for i in range(len(self.instructions))
        ]

        return self.workflow_content, results
