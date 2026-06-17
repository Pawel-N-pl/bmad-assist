"""Validation report persistence module.

Story 11.8: Validation Report Persistence

This module provides:
- ValidationReportMetadata: Dataclass for parsed report metadata
- extract_validation_report(): Extract report from LLM output using markers
- list_validations(): Query validation reports with filtering
- save_validation_report(): Save validation reports with YAML frontmatter
- save_synthesis_report(): Save synthesis reports with YAML frontmatter

Security:
- Uses YAML SafeLoader to prevent code injection
- Validates resolved paths are within validations directory

Extraction:
- Uses shared core/extraction.py for marker-based and fallback extraction
- Supports flexible header patterns (with/without emoji, various formats)

"""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import frontmatter
import yaml

from bmad_assist.core.extraction import (
    CODE_REVIEW_SYNTHESIS_MARKERS,
    SYNTHESIS_MARKERS,
    VALIDATION_MARKERS,
    extract_report,
)
from bmad_assist.core.io import atomic_write as _atomic_write
from bmad_assist.core.types import EpicId

if TYPE_CHECKING:
    from bmad_assist.validation.anonymizer import ValidationOutput

logger = logging.getLogger(__name__)

__all__ = [
    "ValidationReportMetadata",
    "extract_validation_report",
    "extract_synthesis_report",
    "list_validations",
    "save_validation_report",
    "save_synthesis_report",
]

# Metrics markers for synthesis deduplication and stop-at detection
_METRICS_START_MARKER = "<!-- METRICS_JSON_START -->"
_METRICS_END_MARKER = "<!-- METRICS_JSON_END -->"


def extract_validation_report(raw_output: str) -> str:
    r"""Extract validation report content from LLM output.

    Uses shared extraction logic from core/extraction.py:
    1. Primary: Extract content between <!-- VALIDATION_REPORT_START --> and
       <!-- VALIDATION_REPORT_END --> markers
    2. Fallback: Try flexible header patterns (with/without emoji, etc.)
    3. Last resort: Return entire output stripped

    Args:
        raw_output: Raw LLM output (stdout from provider).

    Returns:
        Extracted report content, stripped of markers and code block wrappers.
        Never returns empty string.

    Example:
        >>> output = '''Some thinking...
        ... <!-- VALIDATION_REPORT_START -->
        ... # Story Validation Report
        ... ...report content...
        ... <!-- VALIDATION_REPORT_END -->
        ... Some closing commentary...'''
        >>> extract_validation_report(output)
        '# Story Validation Report\\n...report content...'

    """
    return extract_report(raw_output, VALIDATION_MARKERS)


def extract_synthesis_report(
    raw_output: str,
    synthesis_type: str = "validation",
    termination_reason: str | None = None,
) -> str:
    r"""Extract synthesis report content from LLM output.

    Uses shared extraction logic from core/extraction.py:
    1. Primary: Extract between synthesis markers
    2. Fallback: Try "## Summary" header patterns
    3. Last resort: Return entire output stripped

    Args:
        raw_output: Raw LLM output (stdout from provider).
        synthesis_type: Type of synthesis ("validation" or "code_review").
            Determines which markers to look for.

    Returns:
        Extracted synthesis report content (preserves original formatting).

    Example:
        >>> output = '''Some tool calls...
        ... <!-- VALIDATION_SYNTHESIS_START -->
        ... ## Synthesis Summary
        ... ...synthesis content...
        ... <!-- VALIDATION_SYNTHESIS_END -->
        ... <!-- METRICS_JSON_START -->...'''
        >>> extract_synthesis_report(output, "validation")
        '## Synthesis Summary\\n...synthesis content...'

    """
    # Select markers based on synthesis type
    markers = (
        CODE_REVIEW_SYNTHESIS_MARKERS if synthesis_type == "code_review" else SYNTHESIS_MARKERS
    )

    # Use shared extraction with METRICS_JSON as stop marker
    return extract_report(
        raw_output,
        markers,
        stop_at_markers=[_METRICS_START_MARKER],
        termination_reason=termination_reason,
    )


@dataclass(frozen=True)
class ValidationReportMetadata:
    """Metadata from a validation or synthesis report.

    NULL Semantics:
    - For report_type="validation": synthesis-only fields must be None
      (master_validator_id, session_id, validators_used)
    - For report_type="synthesis": validation-only fields must be None
      (validator_id, phase, token_count)

    Attributes:
        path: Absolute path to report file.
        report_type: "validation" or "synthesis".
        validator_id: Combined provider-model ID (e.g., "claude-opus_4"); None for synthesis.
        master_validator_id: Master validator ID (e.g., "master-opus_4"); None for validation.
        timestamp: UTC timestamp, timezone-aware.
        epic: Epic number.
        story: Story number.
        phase: Phase string (e.g., "VALIDATE_STORY"); None for synthesis.
        duration_ms: Execution duration in milliseconds.
        token_count: Token count; only for validation reports.
        session_id: Anonymization session ID; only for synthesis reports.
        validators_used: List of anonymized validator IDs; only for synthesis reports.

    """

    path: Path
    report_type: str
    validator_id: str | None
    master_validator_id: str | None
    timestamp: datetime
    epic: EpicId
    story: int
    phase: str | None
    duration_ms: int
    token_count: int | None
    session_id: str | None
    validators_used: list[str] | None


def list_validations(
    validations_dir: Path,
    epic: EpicId,
    story: int,
    validator_id: str | None = None,
    report_type: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
) -> list[ValidationReportMetadata]:
    """List validation reports for a given epic/story with optional filters.

    Args:
        validations_dir: Path to story-validations directory.
        epic: Epic number to filter by.
        story: Story number to filter by.
        validator_id: Optional validator ID filter (e.g., "claude-opus_4").
        report_type: Optional type filter ("validation" or "synthesis").
        start_date: Optional minimum timestamp (UTC).
        end_date: Optional maximum timestamp (UTC).

    Returns:
        List of ValidationReportMetadata sorted by timestamp descending (newest first).
        Returns empty list if directory doesn't exist or no matching reports.

    """
    if not validations_dir.exists():
        logger.debug("Validations directory does not exist: %s", validations_dir)
        return []

    results: list[ValidationReportMetadata] = []
    resolved_dir = validations_dir.resolve()

    # Find all markdown files in directory
    for file_path in validations_dir.glob("*.md"):
        # Path traversal prevention: ensure resolved path is within validations_dir
        # Use is_relative_to() instead of string prefix check (cross-platform safe)
        try:
            resolved_path = file_path.resolve()
            if not resolved_path.is_relative_to(resolved_dir):
                logger.warning("Path traversal detected, skipping file: %s", file_path)
                continue
        except (OSError, ValueError) as e:
            logger.warning("Cannot resolve path %s: %s", file_path, e)
            continue

        # Parse frontmatter
        metadata = _parse_report_file(resolved_path)
        if metadata is None:
            continue

        # Filter by epic/story
        if metadata.epic != epic or metadata.story != story:
            continue

        # Filter by validator_id
        if validator_id is not None and metadata.validator_id != validator_id:
            continue

        # Filter by report_type
        if report_type is not None and metadata.report_type != report_type:
            continue

        # Filter by date range
        if start_date is not None and metadata.timestamp < start_date:
            continue
        if end_date is not None and metadata.timestamp > end_date:
            continue

        results.append(metadata)

    # Sort by timestamp descending (newest first)
    results.sort(key=lambda r: r.timestamp, reverse=True)

    return results


def _parse_report_file(file_path: Path) -> ValidationReportMetadata | None:
    """Parse a report file and extract metadata.

    Uses SafeLoader to prevent YAML injection attacks.

    Args:
        file_path: Path to report file.

    Returns:
        ValidationReportMetadata if successfully parsed, None if malformed.

    """
    try:
        with open(file_path, encoding="utf-8") as f:
            # Use SafeLoader to prevent code injection
            post = frontmatter.load(f, handler=frontmatter.YAMLHandler())
    except yaml.YAMLError as e:
        logger.warning("Invalid YAML in %s: %s", file_path, e)
        return None
    except OSError as e:
        logger.warning("Cannot read file %s: %s", file_path, e)
        return None

    metadata = post.metadata

    # Validate required fields
    required_fields = ["type", "timestamp", "epic", "story", "duration_ms"]
    for field in required_fields:
        if field not in metadata:
            logger.warning("Missing required field '%s' in %s", field, file_path)
            return None

    # Parse timestamp
    try:
        timestamp = _parse_timestamp(metadata["timestamp"])
    except (ValueError, TypeError) as e:
        logger.warning("Invalid timestamp in %s: %s", file_path, e)
        return None

    # Extract type
    report_type = metadata.get("type")
    if report_type not in ("validation", "synthesis"):
        logger.warning("Invalid report type '%s' in %s", report_type, file_path)
        return None

    # Type-specific field extraction
    if report_type == "validation":
        return _parse_validation_metadata(file_path, metadata, timestamp)
    else:
        return _parse_synthesis_metadata(file_path, metadata, timestamp)


def _parse_timestamp(ts: str | datetime) -> datetime:
    """Parse timestamp from various formats to timezone-aware datetime.

    Args:
        ts: Timestamp string (ISO 8601) or datetime object.

    Returns:
        Timezone-aware datetime (UTC).

    Raises:
        ValueError: If timestamp format is invalid.

    """
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            return ts.replace(tzinfo=UTC)
        return ts

    # Handle Z suffix (ISO 8601)
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"

    return datetime.fromisoformat(ts)


def _parse_validation_metadata(
    file_path: Path,
    metadata: dict[str, Any],
    timestamp: datetime,
) -> ValidationReportMetadata | None:
    """Parse validation-specific metadata.

    Args:
        file_path: Path to report file.
        metadata: Parsed frontmatter metadata.
        timestamp: Parsed timestamp.

    Returns:
        ValidationReportMetadata or None if invalid.

    """
    # Validation-specific required fields
    if "validator_id" not in metadata:
        logger.warning("Missing validator_id in validation report %s", file_path)
        return None

    try:
        return ValidationReportMetadata(
            path=file_path,
            report_type="validation",
            validator_id=str(metadata["validator_id"]),
            master_validator_id=None,
            timestamp=timestamp,
            epic=int(metadata["epic"]),
            story=int(metadata["story"]),
            phase=metadata.get("phase"),
            duration_ms=int(metadata["duration_ms"]),
            token_count=int(metadata["token_count"]) if "token_count" in metadata else None,
            session_id=None,
            validators_used=None,
        )
    except (ValueError, TypeError) as e:
        logger.warning("Invalid field value in %s: %s", file_path, e)
        return None


def _parse_synthesis_metadata(
    file_path: Path,
    metadata: dict[str, Any],
    timestamp: datetime,
) -> ValidationReportMetadata | None:
    """Parse synthesis-specific metadata.

    Args:
        file_path: Path to report file.
        metadata: Parsed frontmatter metadata.
        timestamp: Parsed timestamp.

    Returns:
        ValidationReportMetadata or None if invalid.

    """
    # Synthesis-specific required fields
    if "master_validator_id" not in metadata:
        logger.warning("Missing master_validator_id in synthesis report %s", file_path)
        return None

    try:
        validators_used = metadata.get("validators_used")
        if validators_used is not None and not isinstance(validators_used, list):
            validators_used = [str(validators_used)]

        return ValidationReportMetadata(
            path=file_path,
            report_type="synthesis",
            validator_id=None,
            master_validator_id=str(metadata["master_validator_id"]),
            timestamp=timestamp,
            epic=int(metadata["epic"]),
            story=int(metadata["story"]),
            phase=None,
            duration_ms=int(metadata["duration_ms"]),
            token_count=None,
            session_id=metadata.get("session_id"),
            validators_used=validators_used,
        )
    except (ValueError, TypeError) as e:
        logger.warning("Invalid field value in %s: %s", file_path, e)
        return None


def _format_timestamp_filename(dt: datetime) -> str:
    """Format datetime for filename using unified format.

    Uses core.io.get_timestamp() for consistent timestamp formatting
    across the codebase (ISO 8601 basic format with UTC marker).

    Args:
        dt: Datetime to format.

    Returns:
        Compact timestamp string (e.g., "20250113T154530Z").

    """
    from bmad_assist.core.io import get_timestamp

    return get_timestamp(dt)


def _sanitize_provider_id(provider_id: str) -> str:
    """Sanitize provider ID for safe use in filenames.

    Replaces unsafe characters with hyphens.

    Args:
        provider_id: Original provider ID.

    Returns:
        Filesystem-safe provider ID.

    """
    # Replace slashes, backslashes, and other unsafe chars
    safe_id = re.sub(r'[/\\:*?"<>|]', "-", provider_id)
    return safe_id


def save_validation_report(
    output: "ValidationOutput",
    epic: EpicId,
    story: int | str,
    phase: str,
    validations_dir: Path,
    anonymized_id: str | None = None,
    role_id: str | None = None,
    session_id: str | None = None,
) -> Path:
    """Save a validation report with YAML frontmatter.

    File path pattern:
    {validations_dir}/validation-{epic}-{story}-{role_id}-{timestamp}.md

    Args:
        output: ValidationOutput from validator.
        epic: Epic number.
        story: Story number (supports string IDs like "6a").
        phase: Phase string (e.g., "VALIDATE_STORY").
        validations_dir: Path to story-validations directory.
        anonymized_id: Anonymous validator ID (e.g., "Validator A") for
            frontmatter display. Preserved for synthesis context.
        role_id: Single letter identifier (a, b, c...) for filename.
            If not provided, falls back to extracting from anonymized_id
            or using sanitized provider name.
        session_id: Anonymization session ID for traceability (Story 22.8).
            Links this report to the validation mapping file.

    Returns:
        Path to saved report file.

    """
    # Use timestamp from ValidationOutput for consistency with other artifacts
    timestamp = output.timestamp
    timestamp_filename = _format_timestamp_filename(timestamp)

    # Determine role_id for filename (a, b, c...)
    if role_id:
        file_role_id = role_id
    elif anonymized_id and anonymized_id.startswith("Validator "):
        # Extract from "Validator A" -> "a"
        file_role_id = anonymized_id[-1].lower()
    else:
        # Fallback to sanitized provider name
        file_role_id = _sanitize_provider_id(output.provider.lower())

    filename = f"validation-{epic}-{story}-{file_role_id}-{timestamp_filename}.md"
    file_path = validations_dir / filename

    # Build YAML frontmatter with both role_id and anonymized_id
    validator_label = anonymized_id or output.provider
    frontmatter_data: dict[str, Any] = {
        "type": "validation",
        "role_id": file_role_id,
        "validator_id": validator_label,
        "timestamp": timestamp.isoformat(),
        "epic": epic,
        "story": story,
        "phase": phase,
        "duration_ms": output.duration_ms,
        "token_count": output.token_count,
    }

    # Story 22.8 AC#3: Add session_id for linking reports to synthesis mapping
    if session_id:
        frontmatter_data["session_id"] = session_id

    # Build content with frontmatter
    post = frontmatter.Post(output.content, **frontmatter_data)
    content = frontmatter.dumps(post)

    _atomic_write(file_path, content)

    logger.info("Saved validation report: %s", file_path)
    return file_path


def _deduplicate_synthesis_content(content: str) -> str:
    """Remove duplicate sections from synthesis LLM output.

    LLMs sometimes repeat sections (e.g., "## Changes Applied" multiple times)
    or output METRICS_JSON blocks more than once. This function keeps only the
    first occurrence of each major section and the first METRICS_JSON block.

    Deduplication strategy:
    1. Find first complete METRICS_JSON block (with both markers)
    2. Split content into sections by ## headings
    3. Keep only first occurrence of each heading
    4. Remove filler text between sections
    5. Add METRICS_JSON block at end

    Args:
        content: Raw synthesis LLM output.

    Returns:
        Deduplicated content with single occurrences of each section.

    """
    # Step 1: Extract first METRICS_JSON block
    first_metrics_start = content.find(_METRICS_START_MARKER)
    first_metrics_end = content.find(_METRICS_END_MARKER)

    metrics_block = ""
    if first_metrics_start != -1 and first_metrics_end != -1:
        # Extract full block including markers
        metrics_block = content[first_metrics_start : first_metrics_end + len(_METRICS_END_MARKER)]

        # Remove ALL METRICS_JSON blocks from content (we'll add first one back at end)
        while True:
            start = content.find(_METRICS_START_MARKER)
            end = content.find(_METRICS_END_MARKER)
            if start == -1 or end == -1:
                break
            # Remove the block and any trailing whitespace/newlines up to next content
            block_end = end + len(_METRICS_END_MARKER)
            # Skip trailing whitespace but preserve structure
            while block_end < len(content) and content[block_end] in "\n\r\t ":
                block_end += 1
            content = content[:start] + content[block_end:]

    # Step 2: Only deduplicate KNOWN problematic headings (safe whitelist)
    # LLMs tend to repeat these specific sections when "thinking out loud"
    dedup_headings = {
        "## Changes Applied",
        "## Synthesis Summary",
        "## Summary",
    }

    # Find all ## headings
    heading_pattern = re.compile(r"^(## .+)$", re.MULTILINE)
    matches = list(heading_pattern.finditer(content))

    if not matches:
        # No headings - just clean filler and return
        if metrics_block:
            return content.rstrip() + "\n\n" + metrics_block + "\n"
        return content

    # Build sections: (heading_text, full_section_content)
    sections: list[tuple[str, str]] = []

    # Content before first heading
    preamble = content[: matches[0].start()]
    if preamble.strip() and not _is_duplicate_filler(preamble):
        sections.append(("__preamble__", preamble))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        section_start = match.start()

        # Section ends at next heading or end of content
        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)

        section_content = content[section_start:section_end]
        sections.append((heading, section_content))

    # Step 3: For WHITELISTED headings, keep the LONGEST version
    # For all other headings, keep ALL occurrences (they're legitimate)
    best_sections: dict[str, str] = {}
    heading_counts: dict[str, int] = {}

    for heading, section_content in sections:
        # Clean filler from section content
        if heading == "__preamble__":
            cleaned = section_content
        else:
            lines = section_content.split("\n")
            clean_lines = [line for line in lines if not _is_duplicate_filler(line)]
            cleaned = "\n".join(clean_lines)

        # Only deduplicate whitelisted headings
        if heading in dedup_headings:
            # Keep the longest version
            if heading not in best_sections or len(cleaned) > len(best_sections[heading]):
                best_sections[heading] = cleaned
        else:
            # Non-whitelisted: keep all occurrences with unique keys
            count = heading_counts.get(heading, 0)
            unique_key = f"{heading}___{count}" if count > 0 else heading
            best_sections[unique_key] = cleaned
            heading_counts[heading] = count + 1

    # Rebuild in original order (first occurrence order for deduped, all for others)
    seen_headings: set[str] = set()
    unique_sections: list[str] = []
    heading_indices: dict[str, int] = {}

    for heading, _ in sections:
        if heading in dedup_headings:
            # Whitelisted: only include first occurrence (with best content)
            if heading in seen_headings:
                continue
            seen_headings.add(heading)
            unique_sections.append(best_sections[heading])
        else:
            # Non-whitelisted: include all with unique keys
            idx = heading_indices.get(heading, 0)
            unique_key = f"{heading}___{idx}" if idx > 0 else heading
            heading_indices[heading] = idx + 1
            unique_sections.append(best_sections[unique_key])

    # Rebuild content
    result = "".join(unique_sections)

    # Step 4: Add METRICS_JSON block at the end (if we extracted one)
    if metrics_block:
        result = result.rstrip() + "\n\n" + metrics_block + "\n"

    return result


def _is_duplicate_filler(text: str) -> bool:
    """Check if text is duplicate filler content (thinking out loud, confirmations).

    Args:
        text: Text to check.

    Returns:
        True if text appears to be filler/duplicate content.

    """
    stripped = text.strip()

    # Empty lines are NOT filler - they're important for markdown formatting
    if not stripped:
        return False

    # Common filler patterns from LLM "thinking out loud"
    filler_patterns = [
        "Let me now apply",
        "Now I'll apply",
        "All 4 changes have been applied",
        "All changes have been applied",
        "Here's the complete summary",
        "I'll apply the verified changes",
    ]

    return any(pattern in stripped for pattern in filler_patterns)


def save_synthesis_report(
    content: str,
    master_validator_id: str,
    session_id: str,
    validators_used: list[str],
    epic: EpicId,
    story: int | str,
    duration_ms: int,
    validations_dir: Path,
    run_timestamp: datetime | None = None,
    failed_validators: list[str] | None = None,
) -> Path:
    """Save a synthesis report with YAML frontmatter.

    File path pattern:
    {validations_dir}/synthesis-{epic}-{story}-{timestamp}.md

    Args:
        content: Synthesis output content.
        master_validator_id: Master validator ID (e.g., "master-opus_4").
        session_id: Anonymization session ID for traceability.
        validators_used: List of anonymized validator IDs.
        epic: Epic number.
        story: Story number.
        duration_ms: Execution duration in milliseconds.
        validations_dir: Path to story-validations directory.
        run_timestamp: Unified timestamp for this validation run. If None, uses now().
        failed_validators: List of validators that failed/timed out (Story 22.8 AC#4).

    Returns:
        Path to saved report file.

    """
    # Use unified run timestamp for consistency with other artifacts
    timestamp = run_timestamp or datetime.now(UTC)
    timestamp_filename = _format_timestamp_filename(timestamp)

    filename = f"synthesis-{epic}-{story}-{timestamp_filename}.md"
    file_path = validations_dir / filename

    # Deduplicate content (LLMs sometimes repeat sections)
    content = _deduplicate_synthesis_content(content)

    # Build YAML frontmatter
    frontmatter_data: dict[str, Any] = {
        "type": "synthesis",
        "master_validator_id": master_validator_id,
        "timestamp": timestamp.isoformat(),
        "epic": epic,
        "story": story,
        "validators_used": validators_used,
        "duration_ms": duration_ms,
        "session_id": session_id,
    }

    # Story 22.8 AC#4: Add failed_validators for traceability
    if failed_validators:
        frontmatter_data["failed_validators"] = failed_validators

    # Build content with frontmatter
    post = frontmatter.Post(content, **frontmatter_data)
    output_content = frontmatter.dumps(post)

    _atomic_write(file_path, output_content)

    logger.info("Saved synthesis report: %s", file_path)
    return file_path
