# bmad-assist

CLI tool for automating the [BMAD](https://github.com/bmad-method) development methodology with Multi-LLM orchestration.

## What is BMAD?

BMAD (Brian's Methodology for AI-Driven Development) is a structured approach to software development that leverages AI assistants throughout the entire lifecycle: from product brief to retrospective.

**bmad-assist** automates the BMAD loop with Multi-LLM orchestration:

```
            ┌─────────────────┐
            │  Create Story   │
            │    (Master)     │
            └────────┬────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│  Validate  │ │  Validate  │ │  Validate  │
│  (Master)  │ │  (Gemini)  │ │  (Codex)   │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
      └──────────────┼──────────────┘
                     ▼
            ┌─────────────────┐
            │    Synthesis    │
            │    (Master)     │
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │    Dev Story    │
            │    (Master)     │
            └────────┬────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│   Review   │ │   Review   │ │   Review   │
│  (Master)  │ │  (Gemini)  │ │  (Codex)   │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
      └──────────────┼──────────────┘
                     ▼
            ┌─────────────────┐
            │    Synthesis    │
            │    (Master)     │
            └────────┬────────┘
                     │
            ┌────────▼────────┐
            │  Retrospective  │
            │    (Master)     │
            └─────────────────┘
```

**Key insight:** Multiple LLMs validate/review in parallel, then Master synthesizes their findings. Only Master modifies files.

## Features

- **Multi-LLM Orchestration** - Run parallel validations/reviews with Claude Code, Gemini CLI, Codex, OpenCode, Amp
- **Evidence Score System** - Mathematical validation scoring (CRITICAL/IMPORTANT/MINOR) with anti-bias checks
- **Workflow Compiler** - Transform BMAD workflows into optimized standalone prompts
- **Patch System** - Customize workflows per-project without forking
- **Bundled Workflows** - All BMAD workflows included, no extra setup needed
- **Per-phase Timeouts** - Configurable timeout per workflow phase

**TODO (not fully working yet):**
- Real-time Dashboard
- Experiment Framework
- Test Architect Integration

## Installation

```bash
# Clone the repository
git clone https://github.com/Pawel-N-pl/bmad-assist.git
cd bmad-assist

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or: .venv\Scripts\activate  # Windows

# Install in development mode
pip install -e .
```

## Requirements

- Python 3.11+
- At least one LLM CLI tool:
  - [Claude Code](https://claude.ai/code) (recommended)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli)
  - [Codex CLI](https://github.com/openai/codex)

## Quick Start

```bash
# 1. Initialize your project
bmad-assist init --project /path/to/your/project

# 2. Create configuration file (see Project Configuration below)
# Edit bmad-assist.yaml in your project root

# 3. Run the development loop
bmad-assist run --project /path/to/your/project

# CLI options:
#   -n, --no-interactive   Disable prompts (for CI/automation)
#                          WARNING: Burns tokens fast, no human oversight!
#   -v, --verbose          Enable debug output
#   -q, --quiet            Suppress non-error output
```

**Your project needs documentation in `docs/`:**
- `prd.md` - Product Requirements Document
- `architecture/` or `architecture.md` - Technical architecture decisions
- `epics/` or `epics.md` - Epic definitions with stories
- `project-context.md` - AI agent implementation rules
- `ux-spec.md` (optional) - UX specifications

**Note:** Workflows are bundled with bmad-assist. No need to copy `_bmad/` directory anymore.

## The `init` Command (Recommended)

The `bmad-assist init` command prepares your project for bmad-assist with full configuration.

```bash
bmad-assist init                    # Initialize current directory
bmad-assist init -p ./my-project    # Initialize specific project
bmad-assist init --dry-run          # Preview changes
bmad-assist init --reset-workflows  # Restore bundled workflow versions
```

**What it does:**
- Creates `.bmad-assist/` directory (state, cache, patches)
- Copies bundled BMAD workflows to `_bmad/bmm/workflows/`
- Updates `.gitignore` with required patterns
- Creates minimal BMAD config if missing

### `init` vs `run`

| Action | `run` | `init` |
|--------|-------|--------|
| Create directories | ✓ | ✓ |
| Copy bundled workflows | ✓ | ✓ |
| Create BMAD config | ✓ | ✓ |
| Update `.gitignore` | ✗ | ✓ |
| Prompt on file differences | ✓ | ✓ |

**TL;DR:** `run` works out-of-the-box. Use `init` once for proper git setup.

### File Conflict Handling

When local workflows differ from bundled versions, you'll see:

```
3 workflow file(s) differ from bundled version:
  - create-story/workflow.yaml
  - dev-story/instructions.md
  - ...

What would you like to do? [a/s/i/d/?] (s): ?

Options:
  [a] Overwrite ALL - replace all differing files
  [s] Skip all     - keep your local versions (default)
  [i] Interactive  - prompt for each file
  [d] Show diff    - display differences
  [?] Help         - show this message
```

### Configuration Options

Suppress gitignore warnings in `bmad-assist.yaml`:

```yaml
warnings:
  suppress_gitignore: true
```

### Exit Codes

- `0` - Success
- `1` - Error
- `2` - Success with warnings (workflows skipped due to local modifications)

### Try It Out

To quickly test bmad-assist, use the included `simple-portfolio` fixture:

```bash
# Unpack the fixture
./scripts/fixture-reset.sh simple-portfolio

# Run bmad-assist on the fixture project
bmad-assist run --project experiments/fixtures/simple-portfolio
```

## Project Configuration

Create `bmad-assist.yaml` in your project root:

```yaml
providers:
  master:
    provider: claude-subprocess
    model: opus
  multi:
    - provider: gemini
      model: gemini-2.5-flash
    - provider: codex
      model: o3-mini
    - provider: claude-subprocess
      model: opus
      model_name: glm-4.7           # display name in logs/reports
      settings: ~/.claude/glm.json  # custom model settings

notifications:
  enabled: true
  events:
    - story_started
    - story_completed
    - phase_completed
    - error_occurred
  providers:
    - type: telegram
      bot_token: ${TELEGRAM_BOT_TOKEN}
      chat_id: ${TELEGRAM_CHAT_ID}
    - type: discord
      webhook_url: ${DISCORD_WEBHOOK_URL}

# Per-phase timeout configuration (seconds)
timeouts:
  default: 600
  create_story: 900
  dev_story: 3600       # Longer for implementation
  code_review: 900
  validate_story: 600
```

## External Documentation

By default, bmad-assist expects documentation in `docs/` and outputs artifacts to `_bmad-output/` within your project. However, you can configure **external paths** to store documentation or artifacts outside your project directory.

This is useful when:
- Multiple projects share the same documentation (monorepo, shared specs)
- You want to keep generated artifacts on a separate drive
- Documentation lives in a different repository

### Configuration

Add a `paths` section to your `bmad-assist.yaml`:

```yaml
paths:
  # Documentation source (PRD, architecture, epics, project-context)
  project_knowledge: /shared/docs/my-project

  # Generated artifacts (stories, validations, code reviews)
  output_folder: /data/bmad-output/my-project

  # Or use relative paths (resolved from project root)
  # project_knowledge: ../shared-docs
```

### Available Path Options

| Option | Default | Description |
|--------|---------|-------------|
| `project_knowledge` | `{project-root}/docs` | Source documentation (read-only) |
| `output_folder` | `{project-root}/_bmad-output` | Base folder for all generated artifacts |
| `planning_artifacts` | `{output_folder}/planning-artifacts` | PRD, architecture copies |
| `implementation_artifacts` | `{output_folder}/implementation-artifacts` | Stories, validations, reviews |

### Path Resolution

Paths are resolved in this order:
1. **Absolute paths** (`/external/docs`) - used as-is
2. **Placeholder paths** (`{project-root}/custom`) - placeholder replaced with project root
3. **Relative paths** (`../shared-docs`) - resolved relative to project root

### Example: Shared Documentation

```yaml
# Project A: /projects/frontend
paths:
  project_knowledge: /shared/product-docs

# Project B: /projects/backend
paths:
  project_knowledge: /shared/product-docs

# Both projects read from the same documentation source
```

### Example: Separate Output Drive

```yaml
paths:
  output_folder: /mnt/fast-ssd/bmad-output/my-project
  # All artifacts (stories, validations, reviews) go to the SSD
```

### Important Notes

- **External `project_knowledge` must exist** - bmad-assist won't create it
- **External `output_folder` is created automatically** - with appropriate subdirectories
- **Permission errors show helpful messages** - if external paths are inaccessible
- **Legacy locations are still checked** - for backwards compatibility with older projects

## Project Structure

```
bmad-assist/
├── src/bmad_assist/      # CLI source code
│   ├── cli.py            # Typer entry point
│   ├── core/             # Config, state, loop
│   ├── compiler/         # Workflow compiler
│   ├── workflows/        # Bundled BMAD workflows
│   ├── validation/       # Multi-LLM validation
│   └── code_review/      # Code review orchestration
├── .bmad-assist/         # Project patches
└── tests/                # Test suite
```

## CLI Commands

```bash
# Main development loop
bmad-assist run -p ./project         # Run BMAD loop
bmad-assist run -e 5 -s 3            # Start from epic 5, story 3
bmad-assist run --phase dev_story    # Override starting phase

# Project setup
bmad-assist init -p ./project        # Initialize project
bmad-assist init --reset-workflows   # Restore bundled workflows

# Workflow compilation
bmad-assist compile -w dev-story -e 5 -s 3    # Compile to standalone prompt
bmad-assist compile -w retrospective -e 5     # Epic-level workflow

# Patch management
bmad-assist patch list               # Show patches and cache status
bmad-assist patch compile -w dev-story        # Compile single patch
bmad-assist patch compile-all        # Compile all patches without cache

# Sprint management
bmad-assist sprint generate          # Generate sprint-status from epics
bmad-assist sprint validate          # Validate sprint-status.yaml
bmad-assist sprint sync              # Sync with story file statuses
```

## Development

```bash
# Run tests
pytest -q --tb=line --no-header

# Type checking
mypy src/

# Linting
ruff check src/
ruff format src/
```

## Troubleshooting

### "Workflow not found" Error

**Symptoms:**
- `CompilerError: Workflow 'dev-story' not found!`
- `Bundled workflow 'code-review' not found!`

**Solution:**
```bash
# Reinstall bmad-assist to ensure workflows are bundled
pip install -e .

# Verify workflows are available
bmad-assist init  # Shows workflow validation
```

### "Handler config not found" Error

**Symptoms:**
- `ConfigError: Handler config not found: ~/.bmad-assist/handlers/...`

**Cause:** Handler YAML files are deprecated. The compiler should handle prompts automatically.

**Solution:**
1. Ensure bmad-assist is properly installed: `pip install -e .`
2. Check if workflow discovery is working: `bmad-assist compile -w dev-story --debug`
3. If using custom workflows, place them in `.bmad-assist/workflows/{workflow-name}/`

### Custom Workflow Overrides

To customize a workflow for your project:

1. Create `.bmad-assist/workflows/{workflow-name}/` directory
2. Copy the workflow files (`workflow.yaml`, `instructions.md`, etc.)
3. Modify as needed

Project overrides take priority over bundled workflows.

## License

MIT

## Links

- [BMAD Method](https://github.com/bmad-method) - The methodology behind this tool
