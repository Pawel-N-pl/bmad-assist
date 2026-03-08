# Sprint Management

Sprint management tracks development progress across epics and stories in bmad-assist. The system maintains a `sprint-status.yaml` file that serves as a human-readable view of project state, synchronized from the authoritative `state.yaml` runtime file.

## Problem

BMAD development workflows need to track story and epic progress across multiple phases (create, validate, develop, review, retrospective). Manual status tracking is error-prone and falls out of sync with actual project artifacts.

Key challenges:
- Story status must reflect actual work completed (code reviews, validations)
- Epic status must aggregate from individual story progress
- Crash recovery requires knowing where work stopped
- Human operators need readable status without parsing runtime state

## Solution

The sprint module provides:
- **Automatic synchronization** from runtime state to sprint-status
- **Evidence-based inference** from project artifacts (story files, code reviews, validations)
- **3-way reconciliation** merging existing status, generated entries, and artifact evidence
- **Atomic writes** with YAML comment preservation
- **CLI commands** for manual inspection and repair

## Architecture

**Source of Truth Hierarchy:**
```
state.yaml (runtime authority, crash recovery)
    ↓ one-way sync
sprint-status.yaml (human-readable view)
    ↑ evidence inference
artifacts (stories, code-reviews, validations, retrospectives)
```

Sync is strictly one-way: state → sprint-status. Sprint-status never modifies state.

## File Format

### Location

Sprint-status files are discovered in priority order:

1. **New projects:** `_bmad-output/implementation-artifacts/sprint-status.yaml`
2. **Legacy projects:** `docs/sprint-artifacts/sprint-status.yaml`

### Structure

```yaml
# Metadata (required: generated)
generated: '2026-01-20T12:00:00'
project: my-project
project_key: my-project
tracking_system: file-system
story_location: _bmad-output/implementation-artifacts

# Development status entries
development_status:
  # Epic entries (recalculated from stories)
  epic-1: done
  epic-2: in-progress

  # Story entries (main tracking)
  1-1-project-setup: done
  1-2-config-loading: in-progress
  2-1-parser-impl: backlog

  # Retrospective entries
  epic-1-retrospective: done
```

### Status Values

| Status | Description |
|--------|-------------|
| `backlog` | Not started (default) |
| `ready-for-dev` | Approved and ready for implementation |
| `in-progress` | Currently being worked on |
| `review` | Code review phase |
| `done` | Completed |
| `blocked` | Blocked by external factor |
| `deferred` | Intentionally deferred |
| `optional` | Optional/nice-to-have |

### Entry Key Patterns

| Pattern | Type | Example | Description |
|---------|------|---------|-------------|
| `{epic}-{story}-{slug}` | Story | `12-3-auth-flow` | Main story tracking |
| `epic-{id}` | Epic meta | `epic-12` | Epic-level status (auto-calculated) |
| `{module}-{story}-{slug}` | Module story | `testarch-1-config` | Stories from module epics |
| `standalone-{id}-{slug}` | Standalone | `standalone-01-refactor` | Manual entries (never deleted) |
| `epic-{id}-retrospective` | Retrospective | `epic-12-retrospective` | Epic retrospective status |

### Format Variants

The parser handles 5 format variants for backwards compatibility:

1. **FULL** - Production format with `development_status` dict (no `epics` key)
2. **HYBRID** - Epic metadata list plus development status
3. **ARRAY** - Simple epic ID list plus development status
4. **MINIMAL** - Bootstrap template with empty `epics: []`
5. **UNKNOWN** - Fallback for unrecognized structures

All variants are normalized to the canonical model during parsing.

## CLI Commands

### `sprint generate`

Generate sprint-status entries from epic files.

```bash
bmad-assist sprint generate --project ./my-project [--verbose] [--include-legacy]
```

**Options:**
- `--project, -p` - Project root directory (default: `.`)
- `--verbose, -v` - Show detailed output with change table
- `--include-legacy` - Include legacy epics (normally auto-excluded)

**Behavior:**
1. Scans epic files in `docs/epics/` and `_bmad-output/planning-artifacts/epics/`
2. Extracts story definitions from frontmatter
3. Merges generated entries with existing sprint-status
4. Writes to `_bmad-output/implementation-artifacts/sprint-status.yaml`

This is a merge-only operation without evidence-based inference.

### `sprint repair`

Repair sprint-status from artifact evidence.

```bash
bmad-assist sprint repair --project ./my-project [--dry-run] [--verbose] [--include-legacy]
```

**Options:**
- `--project, -p` - Project root directory (default: `.`)
- `--dry-run, -n` - Show changes without applying
- `--verbose, -v` - Show divergence percentage and change details
- `--include-legacy` - Include legacy epics

**Behavior:**
1. Loads existing sprint-status
2. Generates entries from epic files
3. Scans project artifacts for evidence
4. Applies evidence-based inference (see Evidence Hierarchy)
5. Performs 3-way reconciliation
6. In interactive mode, prompts if divergence exceeds 30%
7. Writes repaired sprint-status atomically

### `sprint validate`

Validate sprint-status against artifact evidence.

```bash
bmad-assist sprint validate --project ./my-project [--format plain|json] [--verbose]
```

**Options:**
- `--project, -p` - Project root directory (default: `.`)
- `--format, -f` - Output format: `plain` (default) or `json`
- `--verbose, -v` - Show evidence details for each discrepancy

**Exit Codes:**
- `0` - No ERROR discrepancies (WARN-only is acceptable)
- `1` - ERROR discrepancies found or file missing

**Severity Classification:**

| Condition | Severity |
|-----------|----------|
| Status "done" but no code review synthesis | ERROR |
| Status "backlog" but code review synthesis exists | ERROR |
| Status "in-progress" but code reviews exist | WARN |
| Status "review" but code review synthesis exists | WARN |

**JSON Output Format:**
```json
{
  "success": true,
  "exit_code": 0,
  "summary": {"total": 10, "error_count": 0, "warn_count": 2},
  "discrepancies": [
    {
      "key": "1-2-story",
      "sprint_status": "in-progress",
      "inferred_status": "review",
      "severity": "warn",
      "reason": "Code reviews exist"
    }
  ]
}
```

### `sprint sync`

Sync sprint-status from state.yaml (one-way).

```bash
bmad-assist sprint sync --project ./my-project [--verbose]
```

**Options:**
- `--project, -p` - Project root directory (default: `.`)
- `--verbose, -v` - Show skipped keys

**Behavior:**
1. Loads state.yaml from project
2. Maps current phase to sprint-status value
3. Updates matching entries in sprint-status
4. Marks completed stories and epics as done

**Phase to Status Mapping:**

| Phases | Sprint Status |
|--------|---------------|
| CREATE_STORY, VALIDATE_STORY, VALIDATE_STORY_SYNTHESIS | in-progress |
| ATDD, DEV_STORY | in-progress |
| TEA_FRAMEWORK, TEA_CI, TEA_TEST_DESIGN, TEA_AUTOMATE | in-progress |
| CODE_REVIEW, CODE_REVIEW_SYNTHESIS | review |
| TEST_REVIEW, TRACE, TEA_NFR_ASSESS | review |
| RETROSPECTIVE, QA_PLAN_GENERATE, QA_PLAN_EXECUTE | done |

## Evidence Hierarchy

When inferring status from artifacts, evidence is evaluated in priority order:

| Priority | Evidence | Confidence | Inferred Status |
|----------|----------|------------|-----------------|
| 1 | Story file `Status:` field | EXPLICIT | Field value |
| 2 | Code review synthesis exists | STRONG | done |
| 3 | Any code review exists | MEDIUM | review |
| 4 | Validation report exists | MEDIUM | ready-for-dev |
| 5 | Story file exists (no Status) | WEAK | in-progress |
| 6 | No evidence | NONE | backlog |

Higher priority evidence overrides lower priority.

## Loop Integration

Sprint synchronization is integrated into the development loop:

**Synchronization Points:**
1. **Loop initialization** - Resume validation checks if current story/epic is done
2. **After each phase** - Current story status updated based on phase
3. **Story completion** - Story marked done at retrospective
4. **Epic completion** - Epic marked done, retrospective tracked

**Callback System:**
```python
from bmad_assist.sprint.sync import register_sync_callback

def my_callback(state, project_path):
    # Custom sync logic
    pass

register_sync_callback(my_callback)
```

Callbacks are fire-and-forget - they never block the main loop.

## Reconciliation Engine

The 3-way reconciliation merges:
1. **Existing** - Current sprint-status.yaml
2. **Generated** - Entries from epic files
3. **Evidence** - Inferred status from artifacts

**Merge Rules by Entry Type:**

| Entry Type | Behavior |
|------------|----------|
| EPIC_STORY | Merge with generated, apply evidence inference |
| EPIC_META | Recalculate from story statuses |
| MODULE_STORY | Preserve from existing (different source) |
| STANDALONE | Never delete (no regeneration source) |
| RETROSPECTIVE | Preserve existing status |

**Status Advancement:**

Status changes are forward-only to prevent accidental downgrades:

```
backlog < ready-for-dev < in-progress < review < done
```

A status will not change from "done" to "in-progress" unless explicitly set in the story file's `Status:` field.

## Writer

Sprint-status files are written atomically with YAML comment preservation:

1. Write to temporary file
2. Preserve inline comments using ruamel.yaml
3. Add epic separator comments (`# Epic X`)
4. Atomic rename to target path

This prevents corruption from crashes during write operations.

## Resume Validation

When resuming after a crash, the system validates state against sprint-status:

1. Check if current story is marked "done" in sprint-status
2. If done, advance to next incomplete story
3. Check if current epic is complete
4. If complete, advance to next incomplete epic
5. Detect project completion (all epics done)

This handles cases where work completed but state wasn't updated before crash.

## Dashboard Integration

The dashboard server integrates with sprint management:

- **Auto-generation** - Creates sprint-status from epics if missing
- **Status API** - `GET /api/status` returns current sprint state
- **Legacy fallback** - Checks legacy location before auto-generating

## Troubleshooting

### Sprint-status not updating

1. Verify state.yaml exists and is valid
2. Check sync callbacks are registered
3. Run manual sync: `bmad-assist sprint sync --project .`

### High divergence warning

This warning only appears when starting the development loop fresh (not resuming) if >30% of entries would change. The CLI `sprint repair` command does not show this warning - it always proceeds silently.

When the loop shows high divergence dialog:
1. Review the summary of proposed changes
2. Choose "Update" to apply changes or "Cancel" to skip repair
3. Use `bmad-assist sprint repair --dry-run` beforehand to preview changes

### Validation errors

When validate reports ERROR severity:
1. Check if story files have explicit `Status:` field
2. Verify code review artifacts exist for "done" stories
3. Run repair to fix discrepancies

### Legacy location conflicts

If both new and legacy locations exist:
1. Legacy is only used if new location is missing
2. To migrate: move file to new location
3. Auto-exclude prevents regenerating legacy epics

### Comment preservation issues

If comments are lost during writes:
1. Ensure ruamel.yaml is installed (required dependency)
2. Inline comments are preserved, header comments regenerated
3. Epic separator comments are auto-added

## Configuration

Sprint behavior is controlled via bmad-assist.yaml:

```yaml
# No dedicated sprint section - uses paths and loop config
paths:
  implementation_artifacts: _bmad-output/implementation-artifacts
  planning_artifacts: _bmad-output/planning-artifacts
  project_knowledge: docs

loop:
  story:
    - create_story
    - validate_story
    - dev_story
    - code_review
    - code_review_synthesis
  epic_teardown:
    - retrospective
```

## Synthesis Extraction Quality

When `code_review_synthesis` or `validate_story_synthesis` runs, the runner records how reliably the LLM output was parsed. This metadata is stored in `state.yaml` — it is not reflected in `sprint-status.yaml`, which only tracks the four BMAD-facing statuses (`backlog`, `in-progress`, `review`, `done`).

### Extraction quality levels

| extraction_quality | meaning |
|---|---|
| `strict` | Exact HTML-comment markers found; all fields valid |
| `degraded` | Fell back to section-header or semantic keyword scan |
| `failed` | No usable structure found; decision based on evidence or manual review |

### What happens on synthesis halt

When the runner cannot derive a trusted resolution (contradictory evidence, fully failed extraction with no pre-synthesis evidence, or repeated ToolCallGuard terminations), it exits with `GUARDIAN_HALT`. The story's visible sprint status stays at its last recorded value — it is **not** rolled back to `backlog`. The runner's `state.yaml` records `last_synthesis_resolution`, `last_synthesis_extraction_quality`, and `last_synthesis_failure_class` for diagnosis.

After resolving the root cause (see [Troubleshooting](troubleshooting.md)), resume the run normally; the loop will retry from the halted phase using the persisted state.

## See Also

- [Configuration Reference](configuration.md) - Main configuration options
- [Workflow Patches](workflow-patches.md) - Workflow customization
- [Troubleshooting](troubleshooting.md) - Common issues
