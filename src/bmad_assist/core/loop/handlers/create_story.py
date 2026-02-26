"""CREATE_STORY phase handler.

Creates a new story file based on epic requirements using the Master LLM.

Includes story file rescue: if the LLM fails to save the story file,
extracts the story content from stdout and writes it to disk.

"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from bmad_assist.core.loop.handlers.base import BaseHandler
from bmad_assist.core.loop.types import PhaseResult
from bmad_assist.core.paths import get_paths
from bmad_assist.core.state import State

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
MIN_STORY_CONTENT_LENGTH = 400
REQUIRED_SECTION_PATTERNS = (
    re.compile(r"^#{2,}\s+Story\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^#{2,}\s+Acceptance\s+Criteria\b", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^#{2,}\s+Tasks?\b", re.MULTILINE | re.IGNORECASE),
)
# Keep for backward compat (exported in tests)
REQUIRED_SECTIONS = ("## Story", "## Acceptance Criteria", "## Tasks")

_STORY_HEADER_PATTERN = re.compile(r"^# Story\s+[\w.-]+\s*:\s*(.+)$", re.MULTILINE)

_STORY_END_PATTERNS = (
    "I've created the story",
    "I've written the story",
    "I have created the story",
    "I have written the story",
    "The story has been created",
    "The story has been written",
    "The story file has been",
    "Let me now",
    "Let me create",
    "Let me save",
    "Now let me",
    "Now I'll",
    "Now I will",
    "<tool_call>",
    "<invoke",
    "</result>",
)


def _find_story_file(state: State) -> Path | None:
    """Find the story file on disk after LLM execution.

    Globs for {epic}-{story_num}-*.md in the stories directory.

    Args:
        state: Current loop state with epic/story info.

    Returns:
        Path to story file if found, None otherwise.

    """
    if state.current_epic is None or state.current_story is None:
        return None

    import re
    hardening_pattern = re.compile(r"^epic-(.+)-hardening$")
    match = hardening_pattern.match(state.current_story)

    if match:
        story_num = "hardening"
    elif "." in state.current_story:
        story_num = state.current_story.split(".")[-1]
    else:
        return None

    paths = get_paths()
    stories_dir = paths.stories_dir

    if not stories_dir.exists():
        return None

    pattern = f"{state.current_epic}-{story_num}-*.md"
    # also handle 'epic-X-hardening.md' which is exact
    if match:
        pattern = f"epic-{state.current_epic}-hardening.md"

    matches = sorted(stories_dir.glob(pattern))
    return matches[0] if matches else None


def _extract_story_content(output: str) -> tuple[str | None, str | None]:
    """Extract story content from LLM stdout.

    Looks for a story header pattern (``# Story X.Y: Title``) and extracts
    from that point. Strips markdown code block wrappers if present,
    and trims trailing LLM commentary.

    Args:
        output: Raw LLM stdout.

    Returns:
        Tuple of (content, title) or (None, None) if not found.

    """
    if not output:
        return None, None

    from bmad_assist.core.io import strip_code_block

    text = strip_code_block(output)

    match = _STORY_HEADER_PATTERN.search(text)
    if not match:
        return None, None

    title = match.group(1).strip()
    content = text[match.start():]

    # Trim trailing LLM commentary
    for end_pattern in _STORY_END_PATTERNS:
        idx = content.find(end_pattern)
        if idx > 0:
            content = content[:idx].rstrip()

    return content.strip() if content.strip() else None, title


def _validate_story_content(content: str) -> bool:
    """Validate that extracted content looks like a real story.

    Checks minimum length and presence of required sections.

    Args:
        content: Extracted story content.

    Returns:
        True if content passes validation.

    """
    if len(content) < MIN_STORY_CONTENT_LENGTH:
        return False

    return all(pat.search(content) for pat in REQUIRED_SECTION_PATTERNS)


def _write_rescued_story(state: State, content: str, title: str | None) -> Path:
    """Write rescued story content to disk.

    Uses generate_story_slug for the filename and atomic_write for
    crash-safe persistence.

    Args:
        state: Current loop state with epic/story info.
        content: Validated story content.
        title: Story title extracted from header, or None.

    Returns:
        Path to the written story file.

    """
    import re

    from bmad_assist.core.io import atomic_write
    from bmad_assist.sprint.generator import generate_story_slug

    paths = get_paths()
    stories_dir = paths.stories_dir

    hardening_pattern = re.compile(r"^epic-(.+)-hardening$")
    match = hardening_pattern.match(state.current_story or "")

    if match:
        filename = f"{state.current_story}.md"
    else:
        slug = generate_story_slug(title) if title else "untitled"
        story_num = (
            state.current_story.split(".")[-1]
            if state.current_story and "." in state.current_story
            else "1"
        )
        filename = f"{state.current_epic}-{story_num}-{slug}.md"

    story_path = stories_dir / filename

    atomic_write(story_path, content)
    logger.info("Rescued story file written: %s", story_path)

    return story_path


class CreateStoryHandler(BaseHandler):
    """Handler for CREATE_STORY phase.

    Invokes Master LLM to generate a new story file from epic context.
    Includes post-execution verification and rescue: if the LLM fails
    to save the story file, extracts content from stdout and writes it.

    """

    @property
    def phase_name(self) -> str:
        """Returns the name of the phase."""
        return "create_story"

    @property
    def track_timing(self) -> bool:
        """Enable timing tracking for this handler."""
        return True

    @property
    def timing_workflow_id(self) -> str:
        """Workflow ID for timing records."""
        return "create-story"

    def build_context(self, state: State) -> dict[str, Any]:
        """Build context for create_story prompt template.

        Available variables: epic_num, story_num, story_id, project_path

        """
        return self._build_common_context(state)

    def execute(self, state: State) -> PhaseResult:
        """Execute create_story with file verification and rescue.

        After each LLM invocation, checks if the story file was created.
        If not, attempts to extract story content from stdout and write it.
        Retries up to MAX_RETRIES times on rescue failure.

        Args:
            state: Current loop state.

        Returns:
            PhaseResult from story creation.

        """
        for attempt in range(MAX_RETRIES + 1):
            result = super().execute(state)

            if not result.success:
                return result

            if _find_story_file(state):
                return result

            # Story file missing — attempt rescue from stdout
            raw_output = result.outputs.get("response", "")
            content, title = _extract_story_content(raw_output)

            if content and _validate_story_content(content):
                rescued_path = _write_rescued_story(state, content, title)
                result.outputs["rescued_file"] = str(rescued_path)
                logger.info(
                    "Story rescued from LLM output on attempt %d", attempt + 1
                )
                return result

            if attempt < MAX_RETRIES:
                logger.warning(
                    "Story file not found and rescue failed (attempt %d/%d), retrying...",
                    attempt + 1,
                    MAX_RETRIES + 1,
                )

        return PhaseResult.fail(
            f"Story file not created after {MAX_RETRIES + 1} attempts and rescue extraction failed"
        )
