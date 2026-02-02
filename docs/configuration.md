# Configuration Reference

bmad-assist uses a YAML configuration file (`bmad-assist.yaml`) in your project root.

## Configuration Hierarchy

Settings are loaded in this order (later overrides earlier):

1. **Global** (`~/.bmad-assist/config.yaml`)
2. **CWD** (`./bmad-assist.yaml` in current directory)
3. **Project** (`bmad-assist.yaml` in `--project` path)

## Providers

Configure LLM providers for the Master/Multi architecture:

```yaml
providers:
  # Master LLM - creates stories, implements code, synthesizes reviews
  master:
    provider: claude-subprocess
    model: opus

  # Helper LLM - used for metrics extraction, lightweight tasks
  helper:
    provider: claude-subprocess
    model: haiku

  # Multi LLMs - parallel validation and code review
  multi:
    - provider: gemini
      model: gemini-2.5-flash
    - provider: codex
      model: o3-mini
    - provider: claude-subprocess
      model: sonnet
      model_name: glm-4.7           # Display name in logs/reports
      settings: ~/.claude/glm.json  # Custom model settings file
```

### Available Providers

| Provider | Command | Notes |
|----------|---------|-------|
| `claude-subprocess` | `claude --model <model>` | Claude Code CLI |
| `gemini` | `gemini -m <model>` | Gemini CLI |
| `codex` | `codex --model <model>` | OpenAI Codex |
| `opencode` | `opencode chat` | OpenCode CLI |
| `amp` | `amp` | Sourcegraph Amp (smart mode only) |
| `cursor-agent` | `cursor-agent` | Cursor IDE agent |
| `copilot` | `copilot` | GitHub Copilot |

### Provider Options

| Option | Required | Description |
|--------|----------|-------------|
| `provider` | Yes | Provider identifier |
| `model` | Yes | Model name passed to CLI |
| `model_name` | No | Display name in logs/benchmarks |
| `settings` | No | Path to settings file (claude-subprocess) |

## Per-Phase Model Configuration

Override providers for specific workflow phases using `phase_models`. This enables cost/quality optimization - use powerful models for critical phases, faster models for synthesis.

```yaml
phase_models:
  # Single-LLM phases - object format
  create_story:
    provider: claude-subprocess
    model: opus
  dev_story:
    provider: claude-subprocess
    model: opus
  validate_story_synthesis:
    provider: claude-subprocess
    model: sonnet
    model_name: glm-4.7
    settings: ~/.claude/glm.json
  code_review_synthesis:
    provider: claude-subprocess
    model: haiku

  # Multi-LLM phases - array format
  # Lists ALL validators/reviewers - master is NOT auto-added
  validate_story:
    - provider: gemini
      model: gemini-2.5-flash
    - provider: gemini
      model: gemini-3-flash-preview
    - provider: claude-subprocess
      model: sonnet
  code_review:
    - provider: gemini
      model: gemini-2.5-flash
    - provider: claude-subprocess
      model: sonnet
```

### Phase Types

**Single-LLM phases** (object format):
- `create_story` - Story creation from epic
- `validate_story_synthesis` - Consolidate validation reports
- `dev_story` - Implementation
- `code_review_synthesis` - Consolidate review findings
- `retrospective` - Epic completion review
- `atdd` - Acceptance test generation (testarch)
- `test_review` - Test quality review (testarch)
- `qa_plan_generate` - QA plan generation
- `qa_plan_execute` - QA plan execution

**Multi-LLM phases** (array format):
- `validate_story` - Parallel story validation
- `code_review` - Parallel code review

### Fallback Behavior

Phases not listed in `phase_models` use global `providers`:
- Single-LLM phases → `providers.master`
- Multi-LLM phases → `providers.multi` (with master auto-added)

When `phase_models` defines a multi-LLM phase, you have **full control** over the validator/reviewer list - master is NOT automatically added.

## Timeouts

Per-phase timeout configuration (in seconds):

```yaml
timeouts:
  default: 600              # Fallback for phases not listed
  create_story: 900
  validate_story: 600
  validate_story_synthesis: 300
  dev_story: 3600           # Longer for implementation
  code_review: 900
  code_review_synthesis: 300
  retrospective: 900
```

## External Paths

Store documentation or artifacts outside your project:

```yaml
paths:
  # Documentation source (PRD, architecture, epics)
  project_knowledge: /shared/docs/my-project

  # Generated artifacts
  output_folder: /data/bmad-output/my-project
```

### Path Options

| Option | Default | Description |
|--------|---------|-------------|
| `project_knowledge` | `{project}/docs` | Source documentation (read-only) |
| `output_folder` | `{project}/_bmad-output` | Generated artifacts root |
| `planning_artifacts` | `{output_folder}/planning-artifacts` | PRD, architecture copies |
| `implementation_artifacts` | `{output_folder}/implementation-artifacts` | Stories, validations, reviews |

### Path Resolution

1. **Absolute** (`/external/docs`) - used as-is
2. **Placeholder** (`{project-root}/custom`) - placeholder replaced
3. **Relative** (`../shared-docs`) - resolved from project root

## Compiler Settings

### Source Context

Controls which source files are included in workflow prompts:

```yaml
compiler:
  source_context:
    budgets:
      create_story: 20000
      validate_story: 10000
      dev_story: 15000
      code_review: 15000
      default: 20000

    scoring:
      in_file_list: 50       # Bonus for files in story's File List
      in_git_diff: 50        # Bonus for files in git diff
      is_test_file: -10      # Penalty for test files
      is_config_file: -5     # Penalty for config files

    extraction:
      adaptive_threshold: 0.25
      hunk_context_lines: 20
      max_files: 15
```

### Strategic Context

Controls which planning documents (PRD, Architecture, UX) are included:

```yaml
compiler:
  strategic_context:
    budget: 8000

    defaults:
      include: [project-context]
      main_only: true

    create_story:
      include: [project-context, prd, architecture, ux]
    validate_story:
      include: [project-context, architecture]
```

See [Strategic Context Optimization](strategic-context.md) for details.

## Notifications

Send notifications on workflow events:

```yaml
notifications:
  enabled: true
  events:
    - story_started
    - story_completed
    - phase_completed
    - error_occurred
    - anomaly_detected
  providers:
    - type: telegram
      bot_token: ${TELEGRAM_BOT_TOKEN}
      chat_id: ${TELEGRAM_CHAT_ID}
    - type: discord
      webhook_url: ${DISCORD_WEBHOOK_URL}
```

### Notification Events

| Event | Description |
|-------|-------------|
| `story_started` | Story processing begins |
| `story_completed` | Story fully processed |
| `phase_completed` | Individual phase finished |
| `error_occurred` | Error during processing |
| `anomaly_detected` | Guardian detected issue |

## Benchmarking

Track LLM performance metrics:

```yaml
benchmarking:
  enabled: true
```

Metrics are saved to `_bmad-output/implementation-artifacts/benchmarks/`.

## Loop Configuration

Customize the phase sequence:

```yaml
loop:
  epic_setup: []              # Before first story
  story:                      # Per-story phases
    - create_story
    - validate_story
    - validate_story_synthesis
    - dev_story
    - code_review
    - code_review_synthesis
  epic_teardown:              # After last story
    - retrospective
```

## Warnings

Suppress specific warnings:

```yaml
warnings:
  suppress_gitignore: true    # Don't warn about .gitignore patterns
```

## Environment Variables

Use `${VAR_NAME}` syntax for sensitive values:

```yaml
notifications:
  providers:
    - type: telegram
      bot_token: ${TELEGRAM_BOT_TOKEN}  # Loaded from environment
```

Variables are resolved at runtime from the environment or `.env` file.

## See Also

- [TEA Configuration](tea-configuration.md) - Test Engineer Architect module settings
- [Providers Reference](providers.md) - Detailed provider configuration
- [Strategic Context](strategic-context.md) - Document injection settings
- [Workflow Patches](workflow-patches.md) - Customize workflow prompts
