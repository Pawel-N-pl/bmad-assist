"""Git commit automation for bmad-assist phases.

Handles automatic commits after successful phase execution.
"""

import logging
import os
import subprocess
from pathlib import Path

from bmad_assist.core.state import Phase

logger = logging.getLogger(__name__)

# Phases that trigger auto-commit
# CREATE_STORY: Creates story documentation (commit after creation)
# DEV_STORY: Modifies code (commit after implementation)
# CODE_REVIEW_SYNTHESIS: Final story completion (commit after review)
# RETROSPECTIVE: Epic retrospective report (commit after retrospective)
# Validation phases excluded - their reports are outputs, not code changes
COMMIT_PHASES: frozenset[Phase] = frozenset(
    {
        Phase.CREATE_STORY,
        Phase.DEV_STORY,
        Phase.CODE_REVIEW_SYNTHESIS,
        Phase.RETROSPECTIVE,
    }
)

# Phase to conventional commit type mapping
PHASE_COMMIT_TYPES: dict[Phase, str] = {
    Phase.CREATE_STORY: "docs",
    Phase.DEV_STORY: "feat",
    Phase.CODE_REVIEW_SYNTHESIS: "refactor",
    Phase.RETROSPECTIVE: "chore",
}


def is_git_enabled() -> bool:
    """Check if git auto-commit is enabled via environment variable."""
    return os.environ.get("BMAD_GIT_COMMIT") == "1"


# Default threshold for "large commit" warnings. Override via the
# ``BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD`` env var. Set to 0 to disable
# the warning entirely.
_DEFAULT_LARGE_COMMIT_THRESHOLD = 100


def _get_large_commit_threshold() -> int:
    """Resolve the large-commit warning threshold from env, fall back safely.

    Returns 0 when disabled (env var explicitly 0), the configured value
    otherwise, or the default on invalid input.
    """
    raw = os.environ.get("BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD")
    if raw is None:
        return _DEFAULT_LARGE_COMMIT_THRESHOLD
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD=%r (expected int), "
            "using default %d",
            raw,
            _DEFAULT_LARGE_COMMIT_THRESHOLD,
        )
        return _DEFAULT_LARGE_COMMIT_THRESHOLD
    return max(0, value)


def _should_force_stage_all() -> bool:
    """Escape hatch: force legacy ``git add -A`` behavior when set.

    Preserves the original unconditional-stage-all semantics for users
    who rely on it (e.g. workflows that create files outside the
    excluded-prefix filter and still want them auto-committed).
    """
    return os.environ.get("BMAD_GIT_STAGE_ALL") == "1"


def should_commit_phase(phase: Phase | None) -> bool:
    """Check if the given phase should trigger a commit."""
    return phase in COMMIT_PHASES


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git command and return exit code, stdout, stderr.

    Args:
        args: Git command arguments (without 'git' prefix).
        cwd: Working directory for git command.

    Returns:
        Tuple of (exit_code, stdout, stderr).

    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Git command timed out"
    except FileNotFoundError:
        return 1, "", "Git not found in PATH"


def _parse_porcelain_z(stdout: str) -> list[tuple[str, str]]:
    """Parse ``git status --porcelain=v1 -z`` output.

    We use ``-z`` because the default (text) porcelain format has a subtle
    inconsistency: for staged-only modifications with an empty worktree
    delta, some git versions emit ``M filename`` (2-char prefix: status
    letter + separator space) instead of the documented ``XY filename``
    (3-char prefix: 2-char status + separator space). That broke the
    previous ``line[3:]`` slice, chopping the first char off filenames
    (e.g. ``.bmad-assist/running.lock`` → ``bmad-assist/running.lock``),
    which in turn made ``git add -- <path>`` fail with
    ``pathspec did not match any files``.

    The ``-z`` format is explicitly "for scripts": XY is **always** 2
    chars, followed by a space, followed by the path, followed by NUL.
    Renames (``R...``) and copies (``C...``) emit two records separated
    by NUL: the new path first, then the old path.

    Args:
        stdout: Raw subprocess stdout (contains NUL separators).

    Returns:
        List of ``(status, path)`` tuples. ``status`` is the 2-char XY
        code. For renames/copies, ``path`` is the NEW path (consistent
        with legacy behavior of taking the post-rename name).

    """
    records = stdout.split("\x00")
    results: list[tuple[str, str]] = []
    i = 0
    while i < len(records):
        record = records[i]
        if not record:
            i += 1
            continue
        # Each record is "XY path" — XY is 2 chars, space separator.
        if len(record) < 4:
            # Malformed; skip defensively.
            i += 1
            continue
        status = record[:2]
        path = record[3:]
        # Renames/copies: R? or C? in X consumes the next record as the
        # OLD path. We keep the new path (already captured in ``path``).
        if status and status[0] in ("R", "C") and i + 1 < len(records):
            i += 2
        else:
            i += 1
        results.append((status, path))
    return results


def get_modified_files(project_path: Path) -> list[str]:
    """Get list of modified files in the repository.

    Returns both staged and unstaged changes, EXCLUDING output directories
    that contain generated artifacts (validation reports, benchmarks, etc.).

    Args:
        project_path: Path to git repository.

    Returns:
        List of modified file paths relative to repo root.

    """
    # Use -z for NUL-separated output with guaranteed 2-char XY status.
    exit_code, stdout, _ = _run_git(
        ["status", "--porcelain=v1", "-uall", "-z"],
        project_path,
    )

    if exit_code != 0:
        return []

    # Directories to exclude from auto-commit (generated artifacts).
    # ``.bmad-assist/runs/`` and ``.bmad-assist/running.lock`` are run-time
    # state owned by bmad-assist itself — they change every run and would
    # otherwise appear in every auto-commit as noise AND break ``git add``
    # when the lock file is deleted between status + stage.
    exclude_prefixes = (
        "_bmad-output/",
        ".bmad-assist/prompts/",
        ".bmad-assist/cache/",
        ".bmad-assist/debug/",
        ".bmad-assist/runs/",
    )
    exclude_exact = (".bmad-assist/running.lock",)

    files: list[str] = []
    for _status, filename in _parse_porcelain_z(stdout):
        # Skip files in excluded directories
        if any(filename.startswith(prefix) for prefix in exclude_prefixes):
            continue
        if filename in exclude_exact:
            continue
        files.append(filename)

    return files


def check_for_deleted_story_files(project_path: Path) -> list[str]:
    """Check if any story files are marked for deletion.

    Story files are critical artifacts that should never be auto-deleted.
    This function detects deleted story files before they get committed.

    Args:
        project_path: Path to git repository.

    Returns:
        List of deleted story file paths. Empty if none found.

    """
    # Use -z for deterministic parsing (see _parse_porcelain_z docstring).
    exit_code, stdout, _ = _run_git(
        ["status", "--porcelain=v1", "-uall", "-z"],
        project_path,
    )

    if exit_code != 0:
        return []

    import re

    # docs/sprint-artifacts/{epic}-{story}-{slug}.md or stories/{epic}-{story}-{slug}.md
    story_pattern = re.compile(
        r"^(docs/sprint-artifacts/|stories/)?\d+-\d+"
        r"(?:[a-z](?:-[ivx]{2,})*)?-[\w-]+\.md$"
    )

    deleted_files: list[str] = []

    for status, filename in _parse_porcelain_z(stdout):
        # Check if file is deleted (D in staged or unstaged status).
        if "D" not in status:
            continue
        if story_pattern.match(filename):
            deleted_files.append(filename)

    return deleted_files


def generate_commit_message(
    phase: Phase,
    story_id: str | None,
    modified_files: list[str],
) -> str:
    """Generate deterministic conventional commit message for the phase.

    Args:
        phase: The completed phase.
        story_id: Current story ID (e.g., "1.2").
        modified_files: List of files that were modified.

    Returns:
        Commit message string.

    """
    return _generate_conventional_message(phase, story_id, modified_files)


def _generate_conventional_message(
    phase: Phase,
    story_id: str | None,
    modified_files: list[str],
) -> str:
    """Generate conventional commit message.

    Format: <type>(story-X.Y): <description>

    Args:
        phase: The completed phase.
        story_id: Current story ID.
        modified_files: List of modified files.

    Returns:
        Conventional commit message.

    """
    commit_type = PHASE_COMMIT_TYPES.get(phase, "chore")

    # RETROSPECTIVE uses epic-based scope; other phases use story-based scope
    if phase == Phase.RETROSPECTIVE:
        # Extract epic from story_id (e.g., "22.11" -> "22", "testarch.1" -> "testarch")
        epic_id = (
            story_id.split(".")[0] if story_id and "." in story_id else (story_id or "unknown")
        )  # noqa: E501
        scope = f"epic-{epic_id}"
        description = f"archive epic {epic_id} retrospective"
    else:
        scope = f"story-{story_id}" if story_id else "bmad"
        if phase == Phase.CREATE_STORY:
            description = "create story file"
        elif phase == Phase.DEV_STORY:
            description = "implement story"
        elif phase == Phase.CODE_REVIEW_SYNTHESIS:
            description = "apply code review changes"
        else:
            description = f"complete {phase.value.replace('_', ' ')}"

    message = f"{commit_type}({scope}): {description}"

    # Add file count in body if many files changed
    if len(modified_files) > 3:
        message += f"\n\nModified {len(modified_files)} files"

    return message


def stage_all_changes(
    project_path: Path,
    paths: list[str] | None = None,
) -> bool:
    """Stage modified files for commit.

    Args:
        project_path: Path to git repository.
        paths: Optional explicit list of repo-relative paths to stage.
            When provided (and ``BMAD_GIT_STAGE_ALL`` is NOT set), runs
            ``git add -- <paths>`` to stage only those files — aligning
            with whatever filter the caller applied (typically
            :func:`get_modified_files`' exclusion list). When ``paths``
            is None OR the escape hatch is set, falls back to
            ``git add -A`` (legacy "stage everything" behavior).
            Empty list is treated as "nothing to stage" — returns True.

    Returns:
        True if staging succeeded or was a no-op (empty path list).

    """
    force_all = _should_force_stage_all()

    if paths is not None and not force_all:
        if not paths:
            # Nothing to stage — not an error. commit_changes() below
            # will no-op via its "nothing to commit" path.
            return True
        # ``--`` separator protects against paths that start with ``-``.
        exit_code, _, stderr = _run_git(["add", "--", *paths], project_path)
    else:
        exit_code, _, stderr = _run_git(["add", "-A"], project_path)

    if exit_code != 0:
        logger.error("Failed to stage changes: %s", stderr)
        return False
    return True


def commit_changes(project_path: Path, message: str) -> bool:
    """Create a git commit with the given message.

    Args:
        project_path: Path to git repository.
        message: Commit message.

    Returns:
        True if commit succeeded.

    """
    exit_code, stdout, stderr = _run_git(
        ["commit", "-m", message],
        project_path,
    )

    if exit_code != 0:
        # "nothing to commit" is not an error
        if "nothing to commit" in stdout or "nothing to commit" in stderr:
            logger.info("Nothing to commit")
            return True
        logger.error("Failed to commit: %s", stderr)
        return False

    logger.info("Created commit: %s", message.split("\n")[0])
    return True


def _run_precommit_fix(project_path: Path) -> None:
    """Fix lint and typecheck errors that would fail the pre-commit hook.

    Detects which checks the pre-commit hook runs (ESLint, typecheck)
    and fixes errors for each. Uses eslint --fix for auto-fixable issues,
    then invokes an LLM for remaining errors in both categories.

    Best-effort: logs warnings on failure but never blocks the commit flow.

    Args:
        project_path: Path to project root.

    """
    package_json = project_path / "package.json"
    if not package_json.exists():
        return

    # Detect pre-commit checks from .husky/pre-commit
    checks = _detect_precommit_checks(project_path)

    # Fix ESLint errors
    if "eslint" in checks:
        # Layer 1: eslint --fix for auto-fixable issues
        eslint_output = _run_eslint_fix(project_path)

        # Layer 2: If errors remain, invoke LLM to fix them
        if eslint_output:
            _run_llm_lint_fix(project_path, eslint_output)

            # Layer 3: Second eslint --fix pass to clean up import ordering
            remaining = _run_eslint_fix(project_path)
            if remaining:
                error_lines = [
                    line for line in remaining.split("\n") if "error" in line.lower()
                ]
                logger.warning(
                    "Lint fix: %d errors remain after all fix layers",
                    len(error_lines),
                )

    # Fix TypeScript errors
    if "typecheck" in checks:
        tsc_output = _run_typecheck(project_path)
        if tsc_output:
            _run_llm_typecheck_fix(project_path, tsc_output)


def _detect_precommit_checks(project_path: Path) -> set[str]:
    """Detect which checks the pre-commit hook runs.

    Returns:
        Set of check identifiers: "eslint", "typecheck".

    """
    checks: set[str] = set()
    husky_file = project_path / ".husky" / "pre-commit"

    if not husky_file.exists():
        checks.add("eslint")  # Default: always try eslint
        return checks

    try:
        content = husky_file.read_text(encoding="utf-8")
        if "lint" in content:
            checks.add("eslint")
        if "typecheck" in content or "tsc" in content:
            checks.add("typecheck")
    except OSError:
        checks.add("eslint")  # Safe default

    return checks


def _run_typecheck(project_path: Path) -> str | None:
    """Run typecheck and return error output, or None if clean."""
    try:
        result = subprocess.run(
            ["npx", "turbo", "run", "typecheck"],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            logger.info("Typecheck passed (zero errors)")
            return None

        output = result.stdout or result.stderr or ""
        error_lines = [line for line in output.split("\n") if "error TS" in line]
        if not error_lines:
            logger.info("Typecheck failed but no TS errors found in output")
            return None

        logger.info("Typecheck: %d TypeScript errors found, invoking LLM", len(error_lines))
        return output

    except subprocess.TimeoutExpired:
        logger.warning("Typecheck timed out after 180s, skipping")
        return None
    except FileNotFoundError:
        logger.debug("npx not found, skipping typecheck")
        return None
    except Exception as e:
        logger.warning("Typecheck failed (non-blocking): %s", e)
        return None


def _run_llm_typecheck_fix(project_path: Path, tsc_output: str) -> None:
    """Invoke a lightweight LLM to fix TypeScript errors. Best-effort."""
    try:
        from bmad_assist.providers.claude_sdk import ClaudeSDKProvider
    except ImportError:
        logger.debug("Claude SDK not available, skipping LLM typecheck fix")
        return

    error_lines = [line.strip() for line in tsc_output.split("\n") if "error TS" in line]
    errors_text = "\n".join(error_lines)

    prompt = (
        "Fix ALL TypeScript errors shown below. For each error:\n"
        "- `TS4111`: Change `obj.prop` to `obj['prop']`\n"
        "- `TS2322`: Fix the type assignment\n"
        "- `TS2339`: Add the missing property or use bracket notation\n"
        "- `TS7006`: Add explicit type annotations\n\n"
        "Use the Read tool to examine each file, then Edit tool to fix. "
        "Do NOT modify any logic — only fix type errors.\n\n"
        "TypeScript errors:\n```\n" + errors_text + "\n```"
    )

    try:
        provider = ClaudeSDKProvider()
        result = provider.invoke(
            prompt,
            model="sonnet",
            timeout=180,
            cwd=project_path,
            allowed_tools=["Read", "Edit", "Glob", "Grep"],
        )
        if result.exit_code == 0:
            logger.info("LLM typecheck fix completed successfully")
        else:
            logger.warning("LLM typecheck fix returned exit_code=%d", result.exit_code)
    except Exception as e:
        logger.warning("LLM typecheck fix failed (non-blocking): %s", e)


def _run_eslint_fix(project_path: Path) -> str | None:
    """Run eslint --fix and return remaining error output, or None if clean."""
    try:
        result = subprocess.run(
            ["npx", "eslint", "--fix", "."],
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            logger.info("Lint auto-fix completed successfully (zero errors)")
            return None

        output = result.stdout or result.stderr or ""
        error_lines = [line for line in output.split("\n") if "error" in line.lower()]
        logger.info("Lint auto-fix: %d errors remain after --fix, invoking LLM", len(error_lines))
        return output

    except subprocess.TimeoutExpired:
        logger.warning("Lint auto-fix timed out after 120s, skipping")
        return None
    except FileNotFoundError:
        logger.debug("npx not found, skipping lint auto-fix")
        return None
    except Exception as e:
        logger.warning("Lint auto-fix failed (non-blocking): %s", e)
        return None


def _run_llm_lint_fix(project_path: Path, eslint_output: str) -> None:
    """Invoke a lightweight LLM to fix remaining lint errors. Best-effort."""
    try:
        from bmad_assist.providers.claude_sdk import ClaudeSDKProvider
    except ImportError:
        logger.debug("Claude SDK not available, skipping LLM lint fix")
        return

    prompt = (
        "Fix ALL ESLint errors shown below. For each error:\n"
        "- `no-undef` for React: Add `import React from 'react'`\n"
        "- `@typescript-eslint/no-unused-vars`: Remove unused import/variable or prefix with `_`\n"
        "- `@typescript-eslint/no-explicit-any`: Replace `any` with correct type or `unknown`\n"
        "- `import/order`: Move the import to the correct position\n\n"
        "Use the Edit tool to fix each file. Do NOT modify any logic — only fix lint errors.\n\n"
        "ESLint output:\n```\n" + eslint_output + "\n```"
    )

    try:
        provider = ClaudeSDKProvider()
        result = provider.invoke(
            prompt,
            model="sonnet",
            timeout=180,
            cwd=project_path,
            allowed_tools=["Read", "Edit", "Glob", "Grep"],
        )
        if result.exit_code == 0:
            logger.info("LLM lint fix completed successfully")
        else:
            logger.warning("LLM lint fix returned exit_code=%d", result.exit_code)
    except Exception as e:
        logger.warning("LLM lint fix failed (non-blocking): %s", e)


def auto_commit_phase(
    phase: Phase | None,
    story_id: str | None,
    project_path: Path,
) -> bool:
    """Automatically commit changes after a successful phase.

    This is the main entry point called from runner.py.

    Args:
        phase: The completed phase.
        story_id: Current story ID.
        project_path: Path to project root.

    Returns:
        True if commit was successful or not needed, False on error.

    """
    if not is_git_enabled():
        return True

    if not should_commit_phase(phase):
        return True

    # Check for modified files
    modified_files = get_modified_files(project_path)
    if not modified_files:
        logger.debug("No changes to commit for phase %s", phase)
        return True

    logger.info(
        "Auto-committing %d files after %s",
        len(modified_files),
        phase.value if phase else "unknown",
    )

    # Approach A (safety net): warn when the number of files to commit
    # crosses a threshold. Catches the symptom of "branch created from
    # a dirty working tree captured 1000+ unrelated files" without
    # changing staging behavior. Users see the warning and can decide
    # whether to investigate before the commit goes through.
    threshold = _get_large_commit_threshold()
    if threshold > 0 and len(modified_files) > threshold:
        preview = modified_files[:5]
        logger.warning(
            "Large auto-commit detected: %d files exceed threshold %d "
            "(phase=%s). Sample: %s%s. If this is unexpected, check for "
            "unrelated changes staged on this branch (e.g. leftover work "
            "from main before branch creation). Set "
            "BMAD_GIT_WARN_LARGE_COMMITS_THRESHOLD=0 to disable this warning.",
            len(modified_files),
            threshold,
            phase.value if phase else "unknown",
            preview,
            ", ..." if len(modified_files) > len(preview) else "",
        )

    # CRITICAL: Check if any story files are marked for deletion
    # This prevents accidental permanent deletion of story artifacts
    deleted_story_files = check_for_deleted_story_files(project_path)
    if deleted_story_files:
        logger.error(
            "CRITICAL: Detected story file deletion(s): %s. "
            "Story files should NEVER be auto-deleted. "
            "Aborting commit to prevent data loss. "
            "Please investigate what caused these deletions.",
            deleted_story_files,
        )
        # Return False to halt the workflow - this is a critical error
        return False

    # Approach B: scope staging to the exclusion-filtered list from
    # get_modified_files(). Previously ``git add -A`` unconditionally
    # staged everything the working tree had modified — including files
    # that the exclusion filter already decided should NOT be part of
    # the auto-commit (e.g. generated artifacts in _bmad-output/). The
    # filter was only applied to the LOG message. Now it's also applied
    # to the actual staging. Honors ``BMAD_GIT_STAGE_ALL=1`` escape
    # hatch for users who need the legacy behavior.
    if not stage_all_changes(project_path, paths=modified_files):
        return False

    # Auto-fix pre-commit hook issues (ESLint + typecheck)
    _run_precommit_fix(project_path)

    # Re-stage after lint fixes. lint may have modified files in ways
    # that also modify files outside our original filter — re-query the
    # filtered list and stage THOSE. This keeps the staging scope
    # consistent with the filter across both stage passes.
    refreshed_files = get_modified_files(project_path)
    stage_all_changes(project_path, paths=refreshed_files)

    # Generate commit message
    message = generate_commit_message(
        phase,  # type: ignore[arg-type]
        story_id,
        modified_files,
    )

    # Commit
    return commit_changes(project_path, message)
