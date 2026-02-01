# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**bmad-assist** is a Python CLI tool that automates the BMAD development loop: create story → validate → develop → code review → retrospective. It orchestrates multiple LLM CLI tools (Claude Code, Gemini CLI, Codex, OpenCode, Amp, Copilot, Cursor, Kimi) with a Master/Multi/Guardian architecture.

**🚫 NEVER run `git push` without explicit user command!** Do not push to any remote repository unless the user explicitly tells you to push. This applies to both repos (bmad-assist-22 and bmad-assist). Commits are fine, push is forbidden without direct instruction.

**Development Workflow:** See `WORKTREE.md` for git worktree-based isolated development.

## Publishing to bmad-assist (GitHub)

This repo (bmad-assist-22) is the development environment. The publication repo is `../bmad-assist/`.

**Directory mapping:**
- `docs/` → Internal BMAD docs (PRD, architecture, epics) - NOT published
- `docs-public/` → User-facing docs → synced to `bmad-assist/docs/`
- `README.md` → Same in both repos, links to `docs/` work in publication

**Sync workflow (ALWAYS use this pattern):**
```bash
# 1. Sync code
rsync -av --delete --exclude='__pycache__' src/ ../bmad-assist/src/
rsync -av --delete --exclude='__pycache__' tests/ ../bmad-assist/tests/

# 2. Sync public docs
rsync -av --delete docs-public/ ../bmad-assist/docs/

# 3. Copy root files
cp README.md CHANGELOG.md bmad-assist.yaml pyproject.toml ../bmad-assist/

# 4. Verify tests pass in bmad-assist
cd ../bmad-assist && ../.venv/bin/pytest -q --tb=line --no-header

# 5. Commit and push (ASK USER FIRST!)
```

**IMPORTANT:** Always run tests in bmad-assist before committing there.

## Current Status (2026-01-31)

- **Completed:** Epics 1-4, 6, 7, 10-16, 18, 22-25 (TEA Enterprise Full Integration, 140+ stories)
- **In Progress:** Test refactoring, CI/CD setup
- **Recent:** Epic 25 - TEA Enterprise v7.0.0+ integration with 8 workflows, evidence collection, engagement models
- **Recent Refactors:** Config package modularization, Loop handler architecture, Notifications system, Strategic context optimization
- **Phase 2 Backlog:** Epics 5, 8, 9 (Power-Prompts, Guardian, Static Reports)

## Project Structure

Single repo architecture using **BMAD v6.0.0-alpha.22**:

### CLI Development (bmad-assist-22/):

```
bmad-assist-22/
├── src/bmad_assist/           # CLI source code (EDIT HERE)
│   ├── cli.py                 # Typer CLI entry point
│   ├── commands/              # CLI command groups (modularized)
│   ├── core/                  # Core: config/, loop/, state, paths
│   ├── providers/             # LLM provider adapters (12 providers)
│   ├── compiler/              # BMAD workflow compiler + patching
│   ├── validation/            # Multi-LLM validation orchestration
│   ├── code_review/           # Code review orchestration
│   ├── benchmarking/          # LLM performance tracking + reports
│   ├── testarch/              # Test Architect module
│   ├── dashboard/             # Real-time dashboard UI + API
│   ├── experiments/           # Experiment framework
│   ├── notifications/         # Discord/Telegram notifications
│   ├── sprint/                # Sprint status management
│   ├── git/                   # Git operations (diff, branch, commit)
│   ├── antipatterns/          # Antipattern extraction from reviews
│   ├── qa/                    # QA plan generation & execution
│   ├── retrospective/         # Epic retrospective reports
│   └── bmad/                  # BMAD file parsing + sharding
├── docs/                      # Internal BMAD docs (PRD, architecture, epics)
├── docs-public/               # User docs → synced to bmad-assist/docs/
├── experiments/               # Benchmark fixtures, analysis, runs
├── .venv/                     # Single venv (Python 3.11 + pip)
├── tests/                     # Test suite (~7000 tests)
├── CLAUDE.md                  # This file
└── WORKTREE.md                # Git worktree workflow guide
```

### For Target Projects (where BMAD generates code):

```
<target-project>/
├── _bmad/                     # BMAD installation
│   └── bmm/
│       └── config.yaml        # Module configuration
├── _bmad-output/              # Generated artifacts (gitignored)
│   ├── planning-artifacts/    # PRD, architecture, epics
│   └── implementation-artifacts/
│       ├── sprint-status.yaml # Sprint tracking
│       ├── stories/           # Story files
│       ├── code-reviews/      # Code review reports
│       ├── story-validations/ # Validation reports
│       ├── retrospectives/    # Epic retrospectives
│       └── benchmarks/        # LLM performance metrics
├── docs/                      # Project knowledge
│   ├── prd.md                 # Product Requirements
│   ├── architecture.md        # Architectural decisions
│   ├── project-context.md     # AI agent rules
│   ├── epics/                 # Epic definitions (sharded)
│   └── modules/               # Module documentation
└── .bmad-assist/              # Project-specific patches
    ├── patches/               # Workflow patches
    └── cache/                 # Template cache
```

**Key Paths from Config:**
- `planning_artifacts`: `_bmad-output/planning-artifacts/`
- `implementation_artifacts`: `_bmad-output/implementation-artifacts/`
- `project_knowledge`: `docs/`

## Build & Development Commands

**IMPORTANT: Always run Python commands through the virtual environment (`.venv`).** Activate it first with `source .venv/bin/activate` or prefix commands with `.venv/bin/` (e.g., `.venv/bin/pytest`, `.venv/bin/python`).

```bash
# Install in development mode
pip install -e .

# Run CLI
bmad-assist run --project ./my-project

# Compile workflow to standalone prompt
bmad-assist compile -w create-story -e 11 -s 1

# Experiment framework commands
bmad-assist experiment run -f minimal -c opus-solo -P baseline -l standard
bmad-assist experiment batch --fixtures minimal,complex --configs opus-solo,haiku-solo -P baseline -l standard
bmad-assist experiment list [--status completed] [--fixture minimal]
bmad-assist experiment show run-2026-01-09-001
bmad-assist experiment compare run-001 run-002 --output comparison.md
bmad-assist experiment templates [--type config|loop|patch-set|fixture]

# Dashboard
bmad-assist serve --project ./my-project --port 8080

# TEA Standalone Workflows
bmad-assist tea framework [-r PROJECT] [-m create|validate|edit] [-d]
bmad-assist tea ci [-r PROJECT] [--ci-platform github|gitlab|circleci] [-d]
bmad-assist tea test-design [-r PROJECT] [--level system|epic] [-d]
bmad-assist tea automate [-r PROJECT] [--component COMPONENT] [-d]
bmad-assist tea nfr-assess [-r PROJECT] [--category CATEGORY] [-d]

# Quality scorecard (experiment fixtures)
bmad-assist test scorecard <fixture-name>

# Run tests (token-optimized - ALWAYS use these flags)
pytest -q --tb=line --no-header
pytest -q --tb=line --no-header tests/core/test_state.py   # Single file
pytest -q --tb=line --no-header -k "test_atomic_write"     # By pattern
```

**⚠️ TEST STRATEGY - IMPORTANT:**
- **DO NOT run full test suite (`pytest tests/`)** unless absolutely necessary
- Full suite takes ~90-120 seconds - too slow for iterative development
- **During development**: Run only relevant test files or patterns
- **Before commit**: Run `mypy src/` and `ruff check src/` (fast)
- **Only at the END of implementation** (before PR/push): Run full test suite once to verify

```bash
# Type checking
mypy src/

# Linting
ruff check src/
ruff format src/
```

### Frontend Development

Dashboard UI uses a modular build system - **NEVER edit `static/index.html` directly!**

**Build System Structure:**
```
src/bmad_assist/dashboard/
├── static-src/              # SOURCE files (edit here!)
│   ├── 01-head.html        # DOCTYPE, meta, CDN links (Tailwind, Basecoat, Alpine, HTMX)
│   ├── 02-sidebar.html     # Project tree navigation
│   ├── 03-main-header.html # Top bar controls
│   ├── 04-terminal.html    # Terminal output section
│   ├── 05-settings-panel.html   # Settings configuration
│   ├── 06-experiments-panel.html # Experiment list
│   ├── 07-experiment-details.html # Experiment detail modal
│   ├── 08-comparison-panel.html   # Run comparison
│   ├── 09-footer.html      # Bottom controls
│   ├── 10-modals.html      # Context menu, toasts, busy modal
│   └── 11-tail.html        # Alpine.js dashboard() component, scripts
├── static/
│   └── index.html          # GENERATED output (DO NOT EDIT!)
├── build_static.py         # Concat partials → index.html
└── split_index.py          # Split index.html → partials (one-time setup)
```

**Build Commands:**
```bash
# One-time build (generates static/index.html from static-src/*.html)
python src/bmad_assist/dashboard/build_static.py

# Watch mode (auto-rebuild on static-src/ changes)
python src/bmad_assist/dashboard/build_static.py --watch
```

**Key Rules:**
- Edit files in `static-src/`, NEVER `static/index.html`
- Partials are concatenated in numeric order (01-11)
- Build process overwrites `static/index.html` completely
- Use watch mode during active frontend development

## Architecture

### Core Components

```
src/bmad_assist/
├── cli.py                 # Typer CLI entry point (core commands only)
├── cli_utils.py           # Shared CLI utilities (EXIT_*, console, helpers)
├── commands/              # CLI command groups (modularized)
│   ├── benchmark.py       # bmad-assist benchmark compare/models
│   ├── compile.py         # bmad-assist compile workflow
│   ├── experiment.py      # bmad-assist experiment run/batch/list/show/compare
│   ├── init.py            # bmad-assist init project setup
│   ├── patch.py           # bmad-assist patch compile/list
│   ├── qa.py              # bmad-assist qa generate/execute
│   ├── serve.py           # bmad-assist serve dashboard
│   ├── sprint.py          # bmad-assist sprint generate/repair/validate/sync
│   └── test.py            # bmad-assist test scorecard
│
├── core/                  # Core package (refactored 2026-01)
│   ├── config/            # Configuration subsystem
│   │   ├── loaders.py     # Config file loading + merging
│   │   ├── env.py         # Environment variable handling
│   │   ├── constants.py   # Config constants and defaults
│   │   ├── loop_config.py # LoopConfig loader
│   │   ├── schema.py      # Config validation schema
│   │   └── models/        # Pydantic config models
│   │       ├── main.py    # BmadAssistConfig root model
│   │       ├── providers.py   # Provider configs (Master, Multi)
│   │       ├── paths.py       # PathsConfig model
│   │       ├── loop.py        # LoopConfig model
│   │       ├── features.py    # FeatureFlags model
│   │       ├── strategic_context.py  # Strategic context config
│   │       └── source_context.py     # Source context config
│   ├── loop/              # Development loop orchestration
│   │   ├── runner.py      # Main loop runner
│   │   ├── dispatch.py    # Phase dispatcher
│   │   ├── handlers/      # Phase handlers (one per workflow)
│   │   │   ├── base.py              # BaseHandler ABC
│   │   │   ├── create_story.py      # Story creation
│   │   │   ├── validate_story.py    # Multi-LLM validation
│   │   │   ├── validate_story_synthesis.py
│   │   │   ├── dev_story.py         # Implementation
│   │   │   ├── code_review.py       # Multi-LLM review
│   │   │   ├── code_review_synthesis.py
│   │   │   ├── retrospective.py     # Epic retrospective
│   │   │   ├── qa_plan_generate.py  # QA planning
│   │   │   └── qa_plan_execute.py   # QA execution
│   │   ├── epic_phases.py     # Epic-level phase logic
│   │   ├── epic_transitions.py # Epic state transitions
│   │   ├── story_transitions.py # Story state transitions
│   │   ├── sprint_sync.py     # Sprint status sync
│   │   ├── locking.py         # Process locking
│   │   ├── pause.py           # Pause/resume logic
│   │   ├── signals.py         # Signal handling
│   │   ├── notifications.py   # Event notifications
│   │   ├── dashboard_events.py # Dashboard SSE events
│   │   └── types.py           # Loop type definitions
│   ├── state.py           # YAML state persistence (atomic writes)
│   ├── paths.py           # Project paths singleton
│   ├── types.py           # EpicId type (int | str)
│   ├── exceptions.py      # Custom exception hierarchy
│   ├── timing.py          # Execution timing utilities
│   ├── debug_logger.py    # JSON debug logging
│   ├── extraction.py      # Output extraction helpers
│   ├── config_editor.py   # Runtime config editing
│   └── config_generator.py # Config file generation
│
├── providers/             # LLM Provider Adapters
│   ├── base.py            # BaseProvider ABC
│   ├── registry.py        # Dynamic provider loading
│   ├── claude.py          # Claude subprocess (--print)
│   ├── claude_sdk.py      # Claude SDK (primary)
│   ├── gemini.py          # Gemini CLI
│   ├── codex.py           # OpenAI Codex
│   ├── opencode.py        # OpenCode CLI
│   ├── amp.py             # Amp CLI
│   ├── copilot.py         # GitHub Copilot
│   ├── cursor_agent.py    # Cursor Agent
│   └── kimi.py            # Kimi CLI (MoonshotAI)
│
├── compiler/              # BMAD Workflow Compiler
│   ├── core.py            # compile_workflow() entry point
│   ├── output.py          # XML output generator
│   ├── variables/         # Variable resolution
│   ├── patching/          # Patch system
│   │   ├── compiler.py    # Patch compilation
│   │   ├── discovery.py   # Patch discovery (project → CWD → global)
│   │   └── cache.py       # Template cache
│   └── workflows/         # Workflow-specific compilers
│
├── validation/            # Multi-LLM Validation
│   ├── orchestrator.py    # Parallel validation
│   ├── anonymizer.py      # Output anonymization
│   └── reports.py         # Report extraction
│
├── code_review/           # Code Review
│   └── orchestrator.py    # Parallel review orchestration
│
├── benchmarking/          # LLM Performance Tracking
│   ├── schema.py          # Metrics models
│   ├── collector.py       # Deterministic metrics
│   ├── extraction.py      # LLM-based extraction
│   ├── storage.py         # YAML persistence
│   ├── reports.py         # Comparison reports
│   └── prompts/           # Extraction prompts
│
├── dashboard/             # Real-time Dashboard
│   ├── server.py          # Starlette + Uvicorn
│   ├── routes/            # REST API (modularized)
│   │   ├── loop.py, status.py, content.py, sse.py
│   │   ├── config/        # Config CRUD
│   │   └── experiments/   # Experiment API
│   ├── sse.py             # SSE broadcaster
│   ├── queue.py           # Task queue
│   ├── static/            # Generated frontend
│   └── static-src/        # Source partials (01-11)
│
├── experiments/           # Experiment Framework
│   ├── runner.py          # Experiment orchestration
│   ├── fixture.py         # Fixture registry
│   ├── config.py, loop.py, patchset.py  # Templates
│   ├── isolation.py       # Fixture isolation
│   ├── comparison.py      # Run comparison
│   └── scorecard.py       # Quality scorecard
│
├── notifications/         # Notification System (NEW)
│   ├── dispatcher.py      # Event dispatcher
│   ├── events.py          # Event definitions
│   ├── formatter.py       # Message formatting
│   ├── discord.py         # Discord webhook
│   └── telegram.py        # Telegram bot
│
├── sprint/                # Sprint Management (NEW)
│   ├── generator.py       # Sprint status generation
│   ├── parser.py          # Status file parsing
│   ├── sync.py            # Story sync with sprint
│   ├── repair.py          # Status repair
│   └── models.py          # Sprint models
│
├── git/                   # Git Operations (NEW)
│   ├── diff.py            # Git diff generation
│   ├── branch.py          # Branch management
│   ├── committer.py       # Auto-commit logic
│   └── gitignore.py       # Gitignore handling
│
├── antipatterns/          # Antipattern Extraction (NEW)
│   ├── extractor.py       # Extract from code reviews
│   └── prompts.py         # Extraction prompts
│
├── qa/                    # QA System
│   ├── generator.py       # Test plan generation
│   ├── executor.py        # Plan execution
│   ├── playwright_executor.py  # Playwright tests
│   └── summary.py         # Results summary
│
├── retrospective/         # Epic Retrospectives
│   └── reports.py         # Retrospective generation
│
├── testarch/              # Test Architect Module (TEA Enterprise v7.0.0+)
│   ├── config.py          # TestarchConfig model
│   ├── eligibility.py     # ATDD eligibility detection
│   ├── preflight.py       # Preflight infrastructure checks
│   ├── engagement.py      # Engagement model logic (off/lite/solo/integrated/auto)
│   ├── core/              # Core TEA infrastructure
│   │   ├── extraction.py  # Output extraction patterns
│   │   ├── types.py       # CIPlatform, ReviewScope enums
│   │   └── variables.py   # TEAVariableResolver
│   ├── handlers/          # TEA phase handlers (9 total: 1 base + 8 workflows)
│   │   ├── base.py        # TestarchBaseHandler ABC
│   │   ├── atdd.py, automate.py, ci.py, framework.py
│   │   ├── nfr_assess.py, test_design.py, test_review.py, trace.py
│   ├── evidence/          # Evidence collection
│   │   ├── collector.py   # EvidenceContextCollector
│   │   └── sources/       # coverage, test_results, security, performance
│   ├── knowledge/         # Knowledge base loading
│   │   ├── loader.py      # KnowledgeBaseLoader
│   │   └── index.py       # tea-index.csv parser
│   └── standalone/        # Standalone runner & CLI
│       ├── runner.py      # StandaloneRunner
│       └── cli.py         # CLI commands (tea_app)
│
├── bmad/                  # BMAD File Parsing
│   ├── parser.py          # Frontmatter + markdown
│   ├── sharding/          # Sharded docs support
│   └── state_reader.py    # Project state reading
│
├── guardian/              # Anomaly Detection (Phase 2)
├── prompts/               # Power-prompts (Phase 2)
└── reporting/             # Static Reports (Phase 2)
```

### Project Patches

Workflow patches live in `.bmad-assist/patches/`:
- `defaults.yaml` - shared post_process rules
- `create-story.patch.yaml` - create-story transforms
- `validate-create-story.patch.yaml` - validation transforms
- `dev-story.patch.yaml` - dev-story transforms
- `code-review.patch.yaml` - code review transforms

**Centralized Patch Discovery** (in `compiler/core.py` via `compiler/patching/compiler.py`):
1. Before compiling, check for cached template: project → CWD → global
2. If no valid cache, look for patch: project → CWD → global
3. If patch exists, auto-compile it to cache
4. Load `workflow_ir` from cache or original files
5. Set `context.workflow_ir` and `context.patch_path` before calling compiler

### Key Design Patterns

**Provider Pattern**: All CLI tools implement `BaseProvider` ABC with `invoke()`, `parse_output()`, `supports_model()`.

**Config Package**: Configuration is now a package (`core/config/`) with:
- `loaders.py` - file loading and merging (global → project)
- `models/` - Pydantic models for type-safe config
- Use `get_config()` singleton, never load config directly

**Handler Pattern**: Loop phases use handler classes (`core/loop/handlers/`):
- Each workflow has a dedicated handler (e.g., `CreateStoryHandler`)
- Handlers inherit from `BaseHandler` ABC
- Dispatch via `core/loop/dispatch.py`

**Atomic Writes**: State persistence uses temp file + `os.rename()` for crash resilience.

**EpicId Type**: Supports both numeric (1, 2, 3) and string ("testarch", "standalone") epic identifiers.

**Strategic Context**: Configurable document loading per workflow via `strategic_context:` in config.

### Workflow Phases (Configurable via LoopConfig)

Default sequence: CREATE_STORY → VALIDATE_STORY → VALIDATE_STORY_SYNTHESIS → DEV_STORY → CODE_REVIEW → CODE_REVIEW_SYNTHESIS (→ RETROSPECTIVE)

Phase sequence is defined in `bmad-assist.yaml` under `loop:` key:
```yaml
loop:
  epic_setup: []                    # Before first story
  story:                            # Per-story phases
    - create_story
    - validate_story
    - validate_story_synthesis
    - dev_story
    - code_review
    - code_review_synthesis
  epic_teardown:                    # After last story
    - retrospective
```

Epic retrospective runs only after last story in epic completes.
Multi-LLM runs in parallel; only Master LLM can modify files.

### Validation Report Extraction (Multi-LLM)

Multi-LLM validators output reports to stdout (no file writes). The orchestrator extracts report content using markers:

```
<!-- VALIDATION_REPORT_START -->
# Story Context Validation Report
...report content...
<!-- VALIDATION_REPORT_END -->
```

**Extraction strategy** (`validation/reports.py:extract_validation_report()`):
1. **Primary**: Extract between markers
2. **Fallback**: Find report header and extract to end
3. **Last resort**: Use raw output

## Code Style

- Python 3.11+, PEP8 naming (snake_case functions, PascalCase classes)
- All functions require type hints
- Google-style docstrings for public APIs
- Custom exceptions inherit from `BmadAssistError`
- Each module uses `logger = logging.getLogger(__name__)`

## Configuration

- Global config: `~/.bmad-assist/config.yaml`
- Project config: `./bmad-assist.yaml` (overrides global)
- BMAD module config: `_bmad/bmm/config.yaml`

**Provider Config Fields:**
```yaml
providers:
  master:
    provider: claude-subprocess   # Provider identifier
    model: opus                   # Model for CLI invocation
    model_name: glm-4.7           # (optional) Display name in logs/reports
    settings: ~/.claude/glm.json  # (optional) --settings flag path
  multi:
    - provider: gemini
      model: gemini-2.5-flash
```

**Benchmarking Config:**
```yaml
benchmarking:
  enabled: true                    # Enable metrics collection (default: true)
  extraction_provider: claude      # Provider for LLM extraction
  extraction_model: haiku          # Model for LLM extraction
```

**Timeouts Config:**
```yaml
# Per-phase timeout configuration (optional, overrides legacy 'timeout' field)
timeouts:
  default: 3600                    # Default timeout for all phases (seconds)
  validate_story: 600              # Shorter timeout for validation
  code_review: 900                 # Shorter timeout for code review
  # Other phases: create_story, validate_story_synthesis, dev_story,
  #               code_review_synthesis, retrospective
```

If `timeouts` section is not present, falls back to legacy `timeout` field (default: 300s).

**Notifications Config:**
```yaml
notifications:
  discord:
    webhook_url: "https://discord.com/api/webhooks/..."
    enabled: true
  telegram:
    bot_token: "..."
    chat_id: "..."
    enabled: false
```

**Strategic Context Config:**
```yaml
strategic_context:
  project_context: true    # Always include project-context.md
  prd: auto               # Include for create_story, dev_story
  architecture: auto      # Include for dev_story, code_review
  ux: false               # Include UX docs
```

### Master LLM Timing Tracking

Timing is automatically tracked for `create-story` and `dev-story` workflows when `benchmarking.enabled: true`.

**File pattern:**
```
_bmad-output/implementation-artifacts/benchmarks/YYYY-MM/eval-{epic}-{story}-master-{timestamp}.yaml
```

**Enabled handlers:**
- `CreateStoryHandler` → `timing_workflow_id = "create-story"`
- `DevStoryHandler` → `timing_workflow_id = "dev-story"`

## Project Documentation

- `docs/prd.md` - 62 functional + 13 non-functional requirements
- `docs/architecture.md` - Full architectural decisions and patterns
- `docs/project-context.md` - AI agent implementation rules
- `docs/epics/` - 19 epics (sharded), 120+ stories completed
- `docs/modules/testarch/` - Test Architect module documentation
- `docs/modules/dashboard/` - Dashboard module (PRD, architecture, wireframes)
- `docs/experiments/` - Experiment framework documentation (Quick start, templates, comparison)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` - Current sprint tracking (testarch+)
- `docs/sprint-artifacts/sprint-status.yaml` - Legacy tracking (Epics 1-14, frozen)

## BMAD Workflow Commands

The project uses BMAD v6 for its own development:

```bash
/bmad:bmm:workflows:sprint-status      # Check current sprint
/bmad:bmm:workflows:create-story       # Create next story
/bmad:bmm:workflows:dev-story          # Implement story
/bmad:bmm:workflows:code-review        # Review implementation
```

Story lifecycle: `backlog → ready-for-dev → in-progress → review → done`

## CRITICAL: Claude Code Token Limits

**Claude Code has a hard limit of 25,000 tokens per file read.** Exceeding this crashes the session and loses all work.

### Rules to Avoid Crashes

1. **DO NOT use background shells** (`run_in_background`) for long-running processes
   - Server logs (uvicorn, etc.) can grow quickly beyond 25K tokens
   - Use foreground execution with `timeout` instead: `timeout 30 command &`

2. **DO NOT read entire outputs** from TaskOutput or large files
   - If output might be large, use `tail -100` or `head -100` via Bash
   - Never use Read tool on files > 20K tokens without offset/limit

3. **Chunking large files:**
   - Use `offset` and `limit` parameters for Read tool
   - Example: `Read file_path=X offset=0 limit=500` then `offset=500 limit=500`

4. **Safe patterns for E2E tests:**
   ```bash
   # GOOD: Foreground with timeout, capture limited output
   timeout 30 .venv/bin/bmad-assist serve --port $PORT > /tmp/server.log 2>&1 &
   SERVE_PID=$!
   sleep 3
   # ... run tests ...
   kill $SERVE_PID 2>/dev/null
   tail -50 /tmp/server.log  # Only read last 50 lines if needed

   # BAD: Background shell (output file can overflow 25K tokens)
   # Bash with run_in_background=true → AVOID
   ```

5. **Output truncation:**
   - Truncate stdout/stderr in results to 8000 chars max (enough for full stack traces)
   - Don't try to read entire log files - extract only what you need
