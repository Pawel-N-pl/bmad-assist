# bmad-assist

CLI tool for automating the [BMAD](https://github.com/bmad-code-org/BMAD-METHOD) development methodology with Multi-LLM orchestration.

## What is BMAD?

BMAD (Breakthrough Method of Agile AI Driven Development) is a structured approach to software development that leverages AI assistants throughout the entire lifecycle.

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
      └──────────────┼──────────────┘
                     ▼
            ┌─────────────────┐
            │    Synthesis    │ ──► Dev Story ──► Code Review ──► Retrospective
            │    (Master)     │
            └─────────────────┘
```

**Key insight:** Multiple LLMs validate/review in parallel, then Master synthesizes findings. Only Master modifies files.

## Features

- **Multi-LLM Orchestration** - Claude Code, Gemini CLI, Codex, OpenCode, Amp, Cursor Agent, GitHub Copilot, Kimi CLI working in parallel
- **Bundled Workflows** - BMAD workflows included and ready to use out of the box
- **Workflow Compiler** - Builds single comprehensive prompts with resolved variables and embedded context - minimizes tool usage and LLM turns
- **Python State Tracking** - Deterministic sequencing maintains sprint status internally instead of relying on LLM inference
- **Evidence Score System** - Mathematical validation scoring with anti-bias checks for reliable quality assessment
- **Antipatterns Module** - Learns from validation and code review findings, injects lessons into subsequent prompts to prevent recurring mistakes
- **Strategic Context Loading** - Config-driven loading of PRD/Architecture per workflow with intelligent truncation to token limits
- **Patch System** - Removes interactive elements from BMAD workflows for fully automated execution
- **AST-aware Truncation** - Intelligent file truncation based on code structure (classes, functions) to fit token budgets
- **Experiment Framework** - Benchmarking with fixture isolation and statistical comparisons (Mann-Whitney U, Cohen's d) for A/B testing

## Installation

```bash
git clone https://github.com/Pawel-N-pl/bmad-assist.git
cd bmad-assist
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Requirements:** Python 3.11+ and at least one LLM CLI tool ([Claude Code](https://claude.ai/code), [Gemini CLI](https://github.com/google-gemini/gemini-cli), or [Codex](https://github.com/openai/codex)).

## Quick Start

```bash
# Initialize project
bmad-assist init --project /path/to/your/project

# Run the development loop
bmad-assist run --project /path/to/your/project
```

**Recommended:** Customize `bmad-assist.yaml` for your provider and model configuration before running. See [Configuration Reference](docs/configuration.md) for available options.

Your project needs documentation in `docs/`:
- `prd.md` - Product Requirements
- `architecture.md` or `architecture/` - Technical decisions
- `epics.md` or `epics/` - Epic definitions with stories
- `project-context.md` - AI implementation rules

## CLI Commands

```bash
# Main loop
bmad-assist run -p ./project              # Run BMAD loop
bmad-assist run -e 5 -s 3                 # Start from epic 5, story 3
bmad-assist run --phase dev_story         # Override starting phase

# Dashboard UI
bmad-assist serve -p ./project            # Start web dashboard on port 9600
bmad-assist serve --port 8080             # Custom port

# Setup
bmad-assist init -p ./project             # Initialize project
bmad-assist init --reset-workflows        # Restore bundled workflows

# Configuration
bmad-assist config wizard                 # Interactive config wizard
bmad-assist config verify                 # Validate config file

# Compilation
bmad-assist compile -w dev-story -e 5 -s 3

# Patches
bmad-assist patch list
bmad-assist patch compile-all

# Sprint
bmad-assist sprint generate
bmad-assist sprint validate
bmad-assist sprint sync

# Benchmarking
bmad-assist benchmark compare             # Compare workflow variants
bmad-assist benchmark models              # Compare LLM models

# Experiments
bmad-assist test scorecard <fixture>      # Generate quality scorecard
```

## Configuration

See [docs/configuration.md](docs/configuration.md) for full reference.

**Basic example:**
```yaml
providers:
  master:
    provider: claude-subprocess
    model: opus
  multi:
    - provider: gemini
      model: gemini-2.5-flash

timeouts:
  default: 600
  dev_story: 3600
```

## Documentation

- [Configuration Reference](docs/configuration.md) - Providers, timeouts, paths, compiler settings
- [Strategic Context](docs/strategic-context.md) - Smart document loading optimization
- [Troubleshooting](docs/troubleshooting.md) - Common issues and solutions

## Workflow Architecture

bmad-assist extends [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) workflows for Multi-LLM automation.

### Modified from BMAD

| Workflow | Changes |
|----------|---------|
| `code-review` | Removed interactive steps, file discovery handled by compiler, outputs to stdout with extraction markers |
| `create-story` | Removed user menus, context injected by compiler |
| `dev-story` | Removed interactive confirmations |
| `retrospective` | Automated summary generation |

### Added by bmad-assist

| Workflow | Purpose |
|----------|---------|
| `validate-story` | Multi-LLM story validation with INVEST criteria and Evidence Score |
| `validate-story-synthesis` | Consolidates multiple validator reports into single verdict |
| `code-review-synthesis` | Consolidates code review findings from multiple reviewers |
| `qa-plan-generate` | Generates QA test plans from requirements |
| `qa-plan-execute` | Executes generated QA plans |

### Key Differences from Vanilla BMAD

- **No user interaction** - Workflows run non-interactively for automation
- **Context injection** - Compiler embeds all needed files (story, architecture, PRD) instead of runtime loading
- **Stdout output** - Reports written to stdout with markers (`<!-- VALIDATION_REPORT_START -->`) for orchestrator extraction
- **Read-only validators** - Multi-LLM validators cannot modify files; only Master LLM writes code

Patches are transparent - see `.bmad-assist/patches/` for implementation details.

## Multi-LLM Orchestration

bmad-assist uses different LLM patterns depending on the workflow phase:

| Phase | Pattern | Description |
|-------|---------|-------------|
| `create_story` | Master | Single LLM creates story for consistency |
| `validate_story` | **Multi (parallel)** | Multiple LLMs validate independently for diverse perspectives |
| `validate_story_synthesis` | Master | Single LLM consolidates validator reports |
| `dev_story` | Master | Single LLM implements code for consistency |
| `code_review` | **Multi (parallel)** | Multiple LLMs review independently as adversarial reviewers |
| `code_review_synthesis` | Master | Single LLM consolidates review findings |
| `retrospective` | Master | Single LLM generates retrospective |

**Why this pattern?**
- **Validation & Review** benefit from multiple perspectives - different models catch different issues
- **Creation & Implementation** need single source of truth - multiple writers cause conflicts
- **Synthesis** consolidates parallel outputs into actionable decisions

**Per-Phase Model Configuration:** You can specify different models for each phase - use powerful models for critical phases, faster models for synthesis. See [Configuration Reference](docs/configuration.md#per-phase-model-configuration) for details.

## Development

```bash
pytest -q --tb=line --no-header
mypy src/
ruff check src/
```

## Community

- **Discord:** [Join our server](https://discord.gg/GeptH9ManY) - Get help, share workflows, discuss AI-assisted development
- **Issues:** [GitHub Issues](https://github.com/Pawel-N-pl/bmad-assist/issues) - Bug reports and feature requests
- **BMAD Method Community:** [Original BMAD community](https://github.com/bmad-code-org/BMAD-METHOD#community) - For questions about the BMAD methodology itself (not bmad-assist tool specific)

## License

MIT

## Links

- [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) - The methodology behind this tool
- [Discord Community](https://discord.gg/GeptH9ManY) - Chat, support, and discussions
