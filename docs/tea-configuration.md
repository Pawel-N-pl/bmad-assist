# TEA Configuration Guide

TEA (Test Engineer Architect) is bmad-assist's test automation module. This guide explains the configuration switches and how `auto` mode works.

## Configuration Hierarchy

TEA uses a three-level switch hierarchy:

```
testarch:
  enabled: true/false          ← MASTER SWITCH (highest priority)
  │
  └─ engagement_model: auto    ← ENGAGEMENT MODEL (medium priority)
     │
     └─ atdd_mode: auto        ← WORKFLOW MODES (lowest priority)
         framework_mode: auto
         ci_mode: auto
         ...
```

**Priority rule:** Higher-level switches override lower-level ones.

---

## Master Switch: `enabled`

Completely enables or disables all TEA functionality.

```yaml
testarch:
  enabled: false  # All TEA workflows disabled, no TEA code runs
```

| Value | Effect |
|-------|--------|
| `true` | TEA enabled (default) |
| `false` | TEA completely disabled |

---

## Engagement Model

Controls **which groups of workflows** are available.

```yaml
testarch:
  engagement_model: auto  # off | lite | solo | integrated | auto
```

| Value | Enabled Workflows |
|-------|-------------------|
| `off` | None (same as `enabled: false`) |
| `lite` | Only `automate` (standalone test generation) |
| `solo` | Standalone: `framework`, `ci`, `test-design`, `automate`, `nfr-assess` |
| `integrated` | All workflows (full loop integration) |
| `auto` | **Delegates to individual `*_mode` settings** |

### When to use each model

- **`off`** - Disable TEA without removing config
- **`lite`** - Generate tests without ATDD ceremony
- **`solo`** - Run TEA workflows standalone (via `bmad-assist tea` commands)
- **`integrated`** - Full TEA integration in development loop
- **`auto`** - Fine-grained control via individual workflow modes (default)

---

## Workflow Modes

Each TEA workflow has its own mode setting. These only take effect when `engagement_model: auto`.

```yaml
testarch:
  engagement_model: auto
  atdd_mode: auto                    # off | auto | on
  framework_mode: auto               # off | auto | on
  ci_mode: auto                      # off | auto | on
  test_design_mode: auto             # off | auto | on
  automate_mode: off                 # off | auto | on
  nfr_assess_mode: off               # off | auto | on
  test_review_on_code_complete: auto # off | auto | on
  trace_on_epic_complete: auto       # off | auto | on
```

| Value | Effect |
|-------|--------|
| `off` | Workflow never runs |
| `on` | Workflow always runs |
| `auto` | Workflow runs conditionally (see below) |

---

## What Does `auto` Mean?

Each workflow interprets `auto` differently based on project state:

| Workflow | `auto` condition |
|----------|------------------|
| `atdd_mode` | Run if story is "ATDD-eligible" (hybrid keyword+LLM scoring) |
| `framework_mode` | Run if no test framework detected (Playwright/Cypress config missing) |
| `ci_mode` | Run if no CI config detected (`.github/workflows/`, `.gitlab-ci.yml`, etc.) |
| `test_design_mode` | Run if no test-design document exists for current level |
| `automate_mode` | Run if test framework exists (opposite of `framework_mode`) |
| `nfr_assess_mode` | Run if trace gate decision is PASS |
| `test_review_on_code_complete` | Run if ATDD was used for current story |
| `trace_on_epic_complete` | Run if ATDD was used anywhere in current epic |

### ATDD Eligibility Scoring

When `atdd_mode: auto`, stories are scored for ATDD eligibility using:

1. **Keyword detection** (weight: 0.5) - Looks for UI/test-related terms
2. **LLM assessment** (weight: 0.5) - Uses helper provider to evaluate story

Stories scoring above threshold (default: 0.5) trigger ATDD workflow.

Configure scoring weights:
```yaml
testarch:
  eligibility:
    keyword_weight: 0.5
    llm_weight: 0.5
    threshold: 0.5
```

---

## Decision Flow

When a TEA workflow is about to run, bmad-assist evaluates:

```
should_run_workflow("atdd") →

1. enabled=false?           → BLOCKED
2. engagement_model=off?    → BLOCKED
3. engagement_model=lite?   → Only "automate" passes
4. engagement_model=solo?   → Only standalone workflows pass
5. engagement_model=integrated? → ALLOWED
6. engagement_model=auto?   → Check atdd_mode:
   - off  → BLOCKED
   - on   → ALLOWED
   - auto → Check eligibility score
```

---

## Common Configurations

### Full TEA Integration (default)
```yaml
testarch:
  enabled: true
  engagement_model: auto
  atdd_mode: auto
```
Runs ATDD for eligible stories, other workflows as needed.

### Force ATDD for Every Story
```yaml
testarch:
  engagement_model: auto
  atdd_mode: on
```
Generates ATDD checklist for every story regardless of eligibility.

### Test Generation Only (No ATDD Loop)
```yaml
testarch:
  engagement_model: lite
```
Only `bmad-assist tea automate` works. No loop integration.

### Standalone Workflows Only
```yaml
testarch:
  engagement_model: solo
```
All standalone workflows enabled (`framework`, `ci`, `test-design`, `automate`, `nfr-assess`).
No loop-integrated workflows (`atdd`, `test-review`, `trace`).

### Disable TEA Completely
```yaml
testarch:
  enabled: false
```
No TEA code runs. Equivalent to not having `testarch:` section.

---

## Standalone vs Loop-Integrated Workflows

| Standalone | Loop-Integrated |
|------------|-----------------|
| `framework` | `atdd` |
| `ci` | `test-review` |
| `test-design` | `trace` |
| `automate` | |
| `nfr-assess` | |

**Standalone** workflows run via `bmad-assist tea <workflow>` commands.
**Loop-integrated** workflows run automatically during `bmad-assist run` phases.

---

## Related Documentation

- [Configuration Reference](configuration.md) - Provider and general settings
- [Strategic Context](strategic-context.md) - Document injection into prompts
