"""Storage layer for LLM evaluation records.

Provides YAML-based persistence with atomic writes, index management,
and query operations for benchmarking records.

Public API:
    save_evaluation_record: Save record with atomic write
    load_evaluation_record: Load and validate record
    list_evaluation_records: List records with filtering
    get_records_for_story: Get all records for a story
    StorageError: Storage operation exception
    RecordFilters: Filter criteria dataclass
    RecordSummary: Record metadata dataclass
"""

import fcntl
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from bmad_assist.benchmarking.schema import (
    BenchmarkingError,
    EvaluatorRole,
    LLMEvaluationRecord,
)

logger = logging.getLogger(__name__)


def get_benchmark_base_dir(project_path: Path) -> Path:
    """Get base directory for benchmark storage.

    Returns the implementation-artifacts directory (base for benchmarks/).
    Uses paths singleton when available.

    Args:
        project_path: Root path to project directory (kept for backward compatibility).

    Returns:
        Path to implementation-artifacts directory (caller appends "benchmarks/").

    """
    from bmad_assist.core.paths import get_paths

    try:
        return get_paths().implementation_artifacts
    except RuntimeError:
        # Fallback for standalone scripts not using CLI
        logger.debug("Paths singleton not initialized, using default")
        return project_path / "_bmad-output" / "implementation-artifacts"


__all__ = [
    "StorageError",
    "RecordFilters",
    "RecordSummary",
    "get_benchmark_base_dir",
    "save_evaluation_record",
    "load_evaluation_record",
    "list_evaluation_records",
    "get_records_for_story",
]


class StorageError(BenchmarkingError):
    """Storage operation failed.

    Raised when:
    - File not found during load
    - Invalid YAML syntax
    - Schema validation fails
    - Atomic write fails
    - base_dir is None or invalid
    """

    pass


@dataclass(frozen=True)
class RecordFilters:
    """Filters for listing evaluation records.

    All fields are optional. Records must match ALL specified filters.

    Story 13.10: Added workflow_id for cross-phase filtering
    (e.g., "validate-story" vs "code-review").
    """

    date_from: datetime | None = None
    date_to: datetime | None = None
    epic: int | None = None
    story: int | None = None
    provider: str | None = None
    role: EvaluatorRole | None = None
    workflow_id: str | None = None  # Filter by workflow.id (e.g., "code-review")


@dataclass(frozen=True)
class RecordSummary:
    """Summary of an evaluation record for listing.

    Contains enough metadata for filtering without loading full content.

    Story 13.10: Added workflow_id for cross-phase filtering.
    """

    path: Path
    record_id: str
    epic_num: int
    story_num: int
    role_id: str | None
    provider: str
    created_at: datetime
    workflow_id: str | None = None  # e.g., "code-review", "validate-story"


def _compute_role_segment(record: LLMEvaluationRecord) -> str:
    """Compute role segment for filename from record.

    Args:
        record: The evaluation record.

    Returns:
        Role segment string: letter (a-z) for validators,
        "synthesizer" for SYNTHESIZER, "master" for MASTER.

    Raises:
        StorageError: If VALIDATOR role has no role_id.

    """
    if record.evaluator.role == EvaluatorRole.VALIDATOR:
        if record.evaluator.role_id is None:
            raise StorageError("VALIDATOR role requires role_id (a-z)")
        return record.evaluator.role_id
    elif record.evaluator.role == EvaluatorRole.SYNTHESIZER:
        return "synthesizer"
    else:  # MASTER
        return "master"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML file atomically using temp file + rename.

    Args:
        path: Target file path.
        data: Data dictionary to serialize.

    Raises:
        StorageError: If write operation fails.

    """
    temp_path = path.with_suffix(".yaml.tmp")

    try:
        # Create parent directories
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file
        with open(temp_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
            )

        # Atomic replace
        os.replace(temp_path, path)

    except OSError as e:
        # Clean up temp file on failure
        if temp_path.exists():
            temp_path.unlink()
        raise StorageError(f"Failed to write {path}: {e}") from e


def _update_index(
    month_dir: Path,
    record: LLMEvaluationRecord,
    filename: str,
    role_segment: str,
) -> None:
    """Update index.yaml with new record entry.

    Uses file locking to prevent race conditions during concurrent updates
    from parallel validators/reviewers (Story 22.6 AC #1, #3, #4).

    Args:
        month_dir: Directory containing the record file.
        record: The evaluation record that was saved.
        filename: Filename of the saved record.
        role_segment: Computed role segment for the record.

    """
    index_path = month_dir / "index.yaml"

    # Ensure parent directory exists
    index_path.parent.mkdir(parents=True, exist_ok=True)

    # Open file for reading and writing (create if doesn't exist)
    # Use 'a+' mode to allow both reading and writing, create if doesn't exist
    with open(index_path, "a+", encoding="utf-8") as f:
        # Acquire exclusive lock on file descriptor (blocking)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

        try:
            # Read existing content
            f.seek(0)
            content = f.read()

            # Parse existing index or create new
            index_data: dict[str, Any] = {"records": [], "updated_at": None}
            if content:
                try:
                    loaded = yaml.safe_load(content)
                    if isinstance(loaded, dict) and "records" in loaded:
                        index_data = dict(loaded)
                except (yaml.YAMLError, OSError):
                    # Corrupted index, start fresh
                    logger.warning("Index file corrupted, rebuilding: %s", index_path)

            # Check for duplicate record_id
            existing_ids = {r["record_id"] for r in index_data["records"]}
            if record.record_id in existing_ids:
                logger.debug("Record %s already in index, skipping", record.record_id)
                return

            # Create new entry
            # Story 13.10: Include workflow_id for cross-phase filtering
            entry = {
                "record_id": record.record_id,
                "path": filename,
                "epic": record.story.epic_num,
                "story": record.story.story_num,
                "role": record.evaluator.role.value,
                "role_id": role_segment
                if record.evaluator.role == EvaluatorRole.VALIDATOR
                else None,
                "provider": record.evaluator.provider,
                "created_at": record.created_at.isoformat(),
                "workflow_id": record.workflow.id,  # e.g., "code-review"
            }
            index_data["records"].append(entry)
            index_data["updated_at"] = datetime.now(UTC).isoformat()

            # Write back: truncate and rewrite
            f.seek(0)
            f.truncate()
            yaml.dump(index_data, f, default_flow_style=False, sort_keys=False)

        finally:
            # Lock is automatically released when file is closed
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_evaluation_record(
    record: LLMEvaluationRecord,
    base_dir: Path | None,
) -> Path:
    """Save evaluation record to YAML file.

    Args:
        record: Complete evaluation record to persist.
        base_dir: Base directory for storage (REQUIRED, passed by orchestrator).

    Returns:
        Path to the saved file.

    Raises:
        StorageError: If save operation fails or base_dir is None.

    """
    if base_dir is None:
        raise StorageError("base_dir required")

    # Compute path components
    month_str = record.created_at.strftime("%Y-%m")
    from bmad_assist.core.io import get_timestamp

    timestamp_str = get_timestamp(record.created_at)
    role_segment = _compute_role_segment(record)

    filename = (
        f"eval-{record.story.epic_num}-{record.story.story_num}-{role_segment}-{timestamp_str}.yaml"
    )

    file_path = base_dir / "benchmarks" / month_str / filename

    # Serialize to dict using model_dump(mode="json") for proper serialization
    data = record.model_dump(mode="json")

    # Atomic write
    _atomic_write_yaml(file_path, data)

    # Update index
    _update_index(file_path.parent, record, filename, role_segment)

    logger.info("Saved evaluation record: %s", file_path)
    return file_path


def load_evaluation_record(path: Path) -> LLMEvaluationRecord:
    """Load evaluation record from YAML file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated LLMEvaluationRecord instance.

    Raises:
        StorageError: If file not found, invalid YAML, or schema validation fails.

    """
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise StorageError(f"Record file not found: {path}") from e
    except yaml.YAMLError as e:
        raise StorageError(f"Invalid YAML in {path}: {e}") from e
    except OSError as e:
        raise StorageError(f"Failed to read {path}: {e}") from e

    try:
        return LLMEvaluationRecord.model_validate(data)
    except ValidationError as e:
        raise StorageError(f"Schema validation failed for {path}: {e}") from e


def _parse_datetime(dt_value: str | datetime) -> datetime:
    """Parse datetime from string or return existing datetime object.

    PyYAML can deserialize ISO 8601 timestamps directly to datetime objects,
    so we handle both string and datetime inputs.

    Args:
        dt_value: ISO 8601 string or datetime object.

    Returns:
        datetime object.

    Raises:
        ValueError: If string cannot be parsed as ISO 8601.

    """
    # Handle datetime objects (PyYAML auto-deserialization)
    if isinstance(dt_value, datetime):
        return dt_value

    # Handle string format
    dt_str = dt_value
    # Handle both Z suffix and +00:00 format
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def _load_index_entries(month_dir: Path) -> list[dict[str, Any]]:
    """Load entries from index.yaml if valid.

    Args:
        month_dir: Directory containing index.yaml.

    Returns:
        List of index entries, empty if index missing or corrupted.

    """
    index_path = month_dir / "index.yaml"
    if not index_path.exists():
        return []

    try:
        with open(index_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return list(data["records"])
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Index file corrupted, falling back to glob: %s (%s)", index_path, e)

    return []


def _load_minimal_from_file(file_path: Path) -> dict[str, Any] | None:
    """Load minimal metadata from record file.

    Args:
        file_path: Path to evaluation record YAML.

    Returns:
        Dict with minimal fields, or None if load fails.

    """
    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return None

        # Extract minimal fields
        # Story 13.10: Include workflow_id for cross-phase filtering
        return {
            "record_id": data.get("record_id"),
            "epic": data.get("story", {}).get("epic_num"),
            "story": data.get("story", {}).get("story_num"),
            "role_id": data.get("evaluator", {}).get("role_id"),
            "provider": data.get("evaluator", {}).get("provider"),
            "created_at": data.get("created_at"),
            "role": data.get("evaluator", {}).get("role"),
            "workflow_id": data.get("workflow", {}).get("id"),
        }
    except (yaml.YAMLError, OSError) as e:
        logger.warning("Failed to load minimal metadata from %s: %s", file_path, e)
        return None


def _matches_filters(entry: dict[str, Any], filters: RecordFilters | None) -> bool:
    """Check if index entry matches filters.

    Args:
        entry: Index entry dict.
        filters: Filter criteria (None means no filtering).

    Returns:
        True if entry matches all specified filters.

    """
    if filters is None:
        return True

    # Epic filter
    if filters.epic is not None and entry.get("epic") != filters.epic:
        return False

    # Story filter
    if filters.story is not None and entry.get("story") != filters.story:
        return False

    # Provider filter
    if filters.provider is not None and entry.get("provider") != filters.provider:
        return False

    # Role filter
    if filters.role is not None:
        entry_role = entry.get("role")
        # Handle legacy index entries without role field (backwards compatibility)
        if entry_role is None:
            # Infer VALIDATOR from role_id pattern (single lowercase letter)
            role_id = entry.get("role_id")
            if role_id is not None and len(role_id) == 1 and role_id.islower():
                entry_role = EvaluatorRole.VALIDATOR.value
            # For legacy entries without role field, SYNTHESIZER/MASTER cannot be
            # distinguished. Filter will exclude these entries - caller should use
            # glob fallback if role field is missing from index.
        if entry_role != filters.role.value:
            return False

    # Date range filter
    if filters.date_from is not None or filters.date_to is not None:
        created_at_str = entry.get("created_at")
        if created_at_str:
            try:
                created_at = _parse_datetime(created_at_str)
                if filters.date_from is not None and created_at < filters.date_from:
                    return False
                if filters.date_to is not None and created_at > filters.date_to:
                    return False
            except (ValueError, TypeError):
                return False
        else:
            return False

    # Workflow ID filter (Story 13.10)
    return filters.workflow_id is None or entry.get("workflow_id") == filters.workflow_id


def list_evaluation_records(
    base_dir: Path | None,
    filters: RecordFilters | None = None,
) -> list[RecordSummary]:
    """List evaluation records with optional filtering.

    Uses index.yaml for fast lookup when available, falls back to
    glob + minimal parse when index is missing or corrupted.

    Args:
        base_dir: Base directory for storage (REQUIRED).
        filters: Optional filter criteria.

    Returns:
        List of RecordSummary matching filters, empty if no matches.

    Raises:
        StorageError: If base_dir is None.

    """
    if base_dir is None:
        raise StorageError("base_dir required")

    benchmarks_dir = base_dir / "benchmarks"
    if not benchmarks_dir.exists():
        return []

    results: list[RecordSummary] = []

    # Iterate through month directories
    for month_dir in sorted(benchmarks_dir.iterdir()):
        if not month_dir.is_dir():
            continue

        # Try to load from index first
        index_entries = _load_index_entries(month_dir)

        if index_entries:
            # Use index (fast path)
            for entry in index_entries:
                if _matches_filters(entry, filters):
                    try:
                        # Story 13.10: Include workflow_id in RecordSummary
                        results.append(
                            RecordSummary(
                                path=month_dir / entry["path"],
                                record_id=entry["record_id"],
                                epic_num=entry["epic"],
                                story_num=entry["story"],
                                role_id=entry.get("role_id"),
                                provider=entry["provider"],
                                created_at=_parse_datetime(entry["created_at"]),
                                workflow_id=entry.get("workflow_id"),
                            )
                        )
                    except (KeyError, ValueError, TypeError) as e:
                        logger.warning("Invalid index entry: %s (%s)", entry, e)
        else:
            # Fallback to glob + minimal parse
            for file_path in month_dir.glob("eval-*.yaml"):
                loaded_entry = _load_minimal_from_file(file_path)
                if loaded_entry is not None and _matches_filters(loaded_entry, filters):
                    entry = loaded_entry
                    try:
                        # Story 13.10: Include workflow_id in RecordSummary
                        results.append(
                            RecordSummary(
                                path=file_path,
                                record_id=entry["record_id"],
                                epic_num=entry["epic"],
                                story_num=entry["story"],
                                role_id=entry.get("role_id"),
                                provider=entry["provider"],
                                created_at=_parse_datetime(entry["created_at"]),
                                workflow_id=entry.get("workflow_id"),
                            )
                        )
                    except (KeyError, ValueError, TypeError) as e:
                        logger.warning("Invalid record file: %s (%s)", file_path, e)

    return results


def get_records_for_story(
    epic_id: int,
    story_id: int,
    base_dir: Path | None,
) -> list[LLMEvaluationRecord]:
    """Get all evaluation records for a story.

    Args:
        epic_id: Epic number.
        story_id: Story number within epic.
        base_dir: Base directory for storage (REQUIRED).

    Returns:
        List of LLMEvaluationRecord sorted by created_at ascending,
        empty if no records exist.

    Raises:
        StorageError: If base_dir is None.

    """
    if base_dir is None:
        raise StorageError("base_dir required")

    # List records with epic+story filter
    summaries = list_evaluation_records(
        base_dir,
        RecordFilters(epic=epic_id, story=story_id),
    )

    # Load full content for each
    records: list[LLMEvaluationRecord] = []
    for summary in summaries:
        try:
            record = load_evaluation_record(summary.path)
            records.append(record)
        except StorageError as e:
            logger.warning("Failed to load record %s: %s", summary.path, e)

    # Sort by created_at ascending
    records.sort(key=lambda r: r.created_at)

    return records
