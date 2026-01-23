"""Antipatterns extraction from synthesis reports.

This module extracts verified issues from synthesis reports using the helper
LLM model, then appends them to epic-scoped antipatterns files for use by
subsequent workflows.

Public API:
    extract_antipatterns: Extract issues list from synthesis content
    append_to_antipatterns_file: Append issues to antipatterns file
    extract_and_append_antipatterns: Combined convenience function
"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml

from bmad_assist.antipatterns.prompts import EXTRACTION_PROMPT
from bmad_assist.core.io import atomic_write, strip_code_block
from bmad_assist.core.paths import get_paths

if TYPE_CHECKING:
    from bmad_assist.core.config import Config
    from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Warning header for antipatterns files
STORY_ANTIPATTERNS_HEADER = '''# Epic {epic_id} - Story Antipatterns

> **WARNING: ANTI-PATTERNS**
> The issues below were MISTAKES found during validation of previous stories.
> DO NOT repeat these patterns. Learn from them and avoid similar errors.
> These represent story-writing mistakes (unclear AC, missing Notes, unrealistic scope).

'''

CODE_ANTIPATTERNS_HEADER = '''# Epic {epic_id} - Code Antipatterns

> **WARNING: ANTI-PATTERNS**
> The issues below were MISTAKES found during code review of previous stories.
> DO NOT repeat these patterns. Learn from them and avoid similar errors.
> These represent implementation mistakes (race conditions, missing tests, weak assertions, etc.)

'''


def extract_antipatterns(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    config: "Config",
) -> list[dict[str, str]]:
    """Extract verified issues from synthesis content using helper model.

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier (numeric or string like "testarch").
        story_id: Story identifier (e.g., "24-11").
        config: Application configuration with helper provider settings.

    Returns:
        List of issue dictionaries with keys: severity, issue, file, fix.
        Returns empty list on any failure (best-effort, non-blocking).

    """
    # Input validation - early exit
    if not synthesis_content or not synthesis_content.strip():
        logger.debug("Empty synthesis content, skipping antipatterns extraction")
        return []

    if "Issues Verified" not in synthesis_content:
        logger.debug("No 'Issues Verified' section found, skipping extraction")
        return []

    # Check helper provider is configured
    helper_config = config.providers.helper
    if not helper_config.provider or not helper_config.model:
        logger.warning("Helper provider not configured, skipping antipatterns extraction")
        return []

    try:
        from bmad_assist.providers import get_provider

        # Get helper provider
        provider = get_provider(helper_config.provider)

        # Build prompt
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        prompt = EXTRACTION_PROMPT.format(
            story_id=story_id,
            date=date_str,
            synthesis_content=synthesis_content,
        )

        # Invoke helper (SYNC) with no file modification allowed
        result = provider.invoke(
            prompt,
            model=helper_config.model,
            timeout=60,
            settings_file=helper_config.settings_path,
            allowed_tools=[],  # Extraction is read-only
        )

        if result.exit_code != 0:
            logger.warning(
                "Helper model extraction failed: exit_code=%d, stderr=%s",
                result.exit_code,
                result.stderr[:200] if result.stderr else "(empty)",
            )
            return []

        # Strip code fences and parse YAML
        cleaned = strip_code_block(result.stdout)

        try:
            data = yaml.safe_load(cleaned)
        except yaml.YAMLError as e:
            logger.warning("Failed to parse extraction YAML: %s", e)
            return []

        # Validate structure
        if not isinstance(data, dict) or "issues" not in data:
            logger.warning("Invalid extraction response structure: missing 'issues' key")
            return []

        issues = data.get("issues", [])
        if not isinstance(issues, list):
            logger.warning("Invalid extraction response: 'issues' is not a list")
            return []

        logger.info(
            "Extracted %d antipatterns from story %s (epic %s)",
            len(issues),
            story_id,
            epic_id,
        )
        return issues

    except Exception as e:
        logger.warning("Antipatterns extraction failed: %s", e)
        return []


def append_to_antipatterns_file(
    issues: list[dict[str, str]],
    epic_id: "EpicId",
    story_id: str,
    antipattern_type: Literal["story", "code"],
    project_path: Path,
) -> None:
    """Append extracted issues to antipatterns file.

    Creates file with warning header if it doesn't exist.
    Appends story section with issues table in markdown format.

    Args:
        issues: List of issue dictionaries to append.
        epic_id: Epic identifier (numeric or string).
        story_id: Story identifier (e.g., "24-11").
        antipattern_type: Either "story" (for validation) or "code" (for code review).
        project_path: Project root path for path resolution.

    """
    if not issues:
        logger.debug("No issues to append, skipping file write")
        return

    try:
        paths = get_paths()
    except RuntimeError:
        # Paths not initialized - use fallback
        impl_artifacts = project_path / "_bmad-output" / "implementation-artifacts"
        impl_artifacts.mkdir(parents=True, exist_ok=True)
        antipatterns_path = impl_artifacts / f"epic-{epic_id}-{antipattern_type}-antipatterns.md"
    else:
        antipatterns_path = (
            paths.implementation_artifacts / f"epic-{epic_id}-{antipattern_type}-antipatterns.md"
        )

    # Determine header based on type
    if antipattern_type == "story":
        header = STORY_ANTIPATTERNS_HEADER.format(epic_id=epic_id)
    else:
        header = CODE_ANTIPATTERNS_HEADER.format(epic_id=epic_id)

    # Read existing content or start with header
    if antipatterns_path.exists():
        existing_content = antipatterns_path.read_text(encoding="utf-8")
    else:
        existing_content = header

    # Build story section
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    story_section = f"\n## Story {story_id} ({date_str})\n\n"
    story_section += "| Severity | Issue | File | Fix |\n"
    story_section += "|----------|-------|------|-----|\n"

    for issue in issues:
        severity = issue.get("severity", "unknown")
        issue_desc = issue.get("issue", "").replace("|", "\\|").replace("\n", " ")
        file_ref = issue.get("file", "-").replace("|", "\\|")
        fix_desc = issue.get("fix", "-").replace("|", "\\|").replace("\n", " ")
        story_section += f"| {severity} | {issue_desc} | {file_ref} | {fix_desc} |\n"

    # Append to content
    full_content = existing_content.rstrip() + "\n" + story_section

    # Atomic write
    atomic_write(antipatterns_path, full_content)
    logger.info("Appended %d antipatterns to %s", len(issues), antipatterns_path)


def extract_and_append_antipatterns(
    synthesis_content: str,
    epic_id: "EpicId",
    story_id: str,
    antipattern_type: Literal["story", "code"],
    project_path: Path,
    config: "Config",
) -> None:
    """Extract antipatterns and append to file (convenience function).

    Combines extract_antipatterns() and append_to_antipatterns_file() into
    a single call. Handles all errors gracefully (best-effort, non-blocking).

    Args:
        synthesis_content: Raw synthesis report content.
        epic_id: Epic identifier (numeric or string).
        story_id: Story identifier (e.g., "24-11").
        antipattern_type: Either "story" (for validation) or "code" (for code review).
        project_path: Project root path for path resolution.
        config: Application configuration with helper provider settings.

    """
    issues = extract_antipatterns(synthesis_content, epic_id, story_id, config)
    if issues:
        append_to_antipatterns_file(issues, epic_id, story_id, antipattern_type, project_path)
