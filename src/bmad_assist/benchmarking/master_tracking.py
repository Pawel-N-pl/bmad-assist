"""Timing tracking for Master LLM workflows (create-story, dev-story).

Phase 1: Basic timing tracking without LLM-extracted metrics.
"""

import logging
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from bmad_assist.benchmarking.schema import (
    EnvironmentInfo,
    EvaluatorInfo,
    EvaluatorRole,
    ExecutionTelemetry,
    LLMEvaluationRecord,
    OutputAnalysis,
    PatchInfo,
    StoryInfo,
    WorkflowInfo,
)
from bmad_assist.benchmarking.storage import save_evaluation_record
from bmad_assist.core.paths import get_paths
from bmad_assist.core.types import EpicId

logger = logging.getLogger(__name__)

# Package version from single source of truth (pyproject.toml via __init__.py)
from bmad_assist import __version__ as _bmad_assist_version


def _get_git_commit(project_path: Path) -> str | None:
    """Get current git commit hash."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=project_path,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:12]
    except Exception:
        pass
    return None


def _analyze_output(output: str) -> OutputAnalysis:
    """Analyze output without LLM extraction."""
    lines = output.split("\n")

    # Count headings (lines starting with #)
    heading_count = sum(1 for line in lines if re.match(r"^#{1,6}\s", line))

    # Count code blocks
    code_block_count = len(re.findall(r"```", output)) // 2

    # Detect max list depth (simple heuristic)
    max_depth = 0
    for line in lines:
        match = re.match(r"^(\s*)[-*]\s", line)
        if match:
            depth = len(match.group(1)) // 2 + 1
            max_depth = max(max_depth, depth)

    # Detect sections (level 2 headings)
    sections = [line.lstrip("#").strip() for line in lines if re.match(r"^##\s", line)]

    return OutputAnalysis(
        char_count=len(output),
        heading_count=heading_count,
        list_depth_max=max_depth,
        code_block_count=code_block_count,
        sections_detected=sections[:10],  # Limit to 10
        anomalies=[],
    )


def create_master_record(
    workflow_id: str,
    epic_num: EpicId,
    story_num: int,
    story_title: str,
    provider: str,
    model: str,
    start_time: datetime,
    end_time: datetime,
    output: str,
    project_path: Path,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> LLMEvaluationRecord:
    """Create evaluation record for Master LLM workflow.

    Args:
        workflow_id: Workflow identifier (e.g., 'create-story', 'dev-story')
        epic_num: Epic number
        story_num: Story number
        story_title: Story title
        provider: Provider name
        model: Model identifier
        start_time: UTC start timestamp
        end_time: UTC end timestamp
        output: Raw LLM output
        project_path: Project root path
        input_tokens: Input token count (if available)
        output_tokens: Output token count (if available)

    Returns:
        Complete LLMEvaluationRecord ready for storage.

    """
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    return LLMEvaluationRecord(
        workflow=WorkflowInfo(
            id=workflow_id,
            version="1.0.0",
            variant="default",
            patch=PatchInfo(applied=False),
        ),
        story=StoryInfo(
            epic_num=epic_num,
            story_num=story_num,
            title=story_title,
            complexity_flags={},
        ),
        evaluator=EvaluatorInfo(
            provider=provider,
            model=model,
            role=EvaluatorRole.MASTER,
            role_id=None,
            session_id=str(uuid4()),
        ),
        execution=ExecutionTelemetry(
            start_time=start_time,
            end_time=end_time,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            retries=0,
            sequence_position=0,
        ),
        output=_analyze_output(output),
        environment=EnvironmentInfo(
            bmad_assist_version=_bmad_assist_version,
            python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            platform=platform.system(),
            git_commit_hash=_get_git_commit(project_path),
        ),
    )


def save_master_timing(
    workflow_id: str,
    epic_num: EpicId,
    story_num: int,
    story_title: str,
    provider: str,
    model: str,
    start_time: datetime,
    end_time: datetime,
    output: str,
    project_path: Path,
    benchmarks_base: Path | None = None,
) -> Path | None:
    """Create and save timing record for Master LLM workflow.

    Args:
        workflow_id: Workflow identifier
        epic_num: Epic number
        story_num: Story number
        story_title: Story title
        provider: Provider name
        model: Model identifier
        start_time: UTC start timestamp
        end_time: UTC end timestamp
        output: Raw LLM output
        project_path: Project root path
        benchmarks_base: Base dir for benchmarks (default: paths.implementation_artifacts)

    Returns:
        Path to saved file, or None if save failed.

    """
    if benchmarks_base is None:
        paths = get_paths()
        benchmarks_base = paths.implementation_artifacts

    try:
        record = create_master_record(
            workflow_id=workflow_id,
            epic_num=epic_num,
            story_num=story_num,
            story_title=story_title,
            provider=provider,
            model=model,
            start_time=start_time,
            end_time=end_time,
            output=output,
            project_path=project_path,
        )
        return save_evaluation_record(record, benchmarks_base)
    except Exception as e:
        logger.warning("Failed to save master timing: %s", e)
        return None
