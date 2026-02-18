# bmad-assist

CLI tool that reads your project documentation (PRD, architecture, epics) and implements it story by story using multiple LLMs. Built on the [BMAD](https://github.com/bmad-code-org/BMAD-METHOD) methodology.

## What does it do?

[BMAD](https://github.com/bmad-code-org/BMAD-METHOD) (Breakthrough Method of Agile AI Driven Development) structures AI-driven projects into docs: PRD, architecture, epics, and stories. bmad-assist uses BMAD workflows to produce code, adding multi-LLM orchestration, automated quality loops, and hands-free execution on top.

You write the docs (or have AI help you write them with BMAD). bmad-assist reads them and runs an automated loop:

1. **Creates** the next story from your epics
2. **Validates** the story using multiple LLMs in parallel (catches issues a single LLM would miss)
3. **Implements** the story - writes code, tests, updates files
4. **Reviews** the code with multiple LLMs as adversarial reviewers
5. **Pauses** between stories and epics to let you quit gracefully - or skip prompts with `--skip-story-prompts` / `-n`
6. **Repeats** for every story in the epic, then runs a retrospective and moves to the next epic

One LLM (Master) writes all code. The others only validate and review - they never touch your files.

```
  Create Story ──► Validate (multi-LLM) ──► Synthesis ──► Dev Story ──► Code Review (multi-LLM) ──► Synthesis
       │                                                                                                │
       └────────────────────────────────── next story ◄─────────────────────────────────────────────────┘
```

## Features

- **Multi-LLM Orchestration** - Claude Code, Gemini CLI, Codex, OpenCode, Amp, Cursor Agent, GitHub Copilot, Kimi CLI working in parallel
- **A/B Testing** - Compare workflow configs, prompts, or model fleets side-by-side with git worktree isolation and LLM-powered analysis reports
- **TEA Enterprise** - Test Architect with 8 workflows: framework setup, CI scaffolding, test design, ATDD, automation, NFR assessment, traceability, test review
- **Bundled Workflows** - BMAD workflows included and ready to use out of the box
- **Git Auto-commit** - Automatic commits after create-story, dev-story, and code-review-synthesis phases (`-g` flag)
- **Deep Verify** *(WIP)* - Multi-method artifact verification (pattern matching, boundary analysis, cross-reference checks)
- **Security Agent** *(WIP)* - Parallel CWE pattern analysis with tech stack detection, integrated into code review phase

### Under the Hood

- **Workflow Compiler** - Builds single comprehensive prompts with resolved variables and embedded context - minimizes tool usage and LLM turns
- **AST-aware Truncation** - Intelligent file truncation based on code structure (classes, functions) to fit token budgets
- **Evidence Score System** - Mathematical validation scoring with anti-bias checks for reliable quality assessment
- **Antipatterns Module** - Learns from validation and code review findings, injects lessons into subsequent prompts to prevent recurring mistakes
- **Strategic Context Loading** - Config-driven loading of PRD/Architecture per workflow with intelligent truncation to token limits
- **Patch System** - Removes interactive elements from BMAD workflows for fully automated execution
- **Python State Tracking** - Deterministic sequencing maintains sprint status internally instead of relying on LLM inference

## Installation

```bash
git clone https://github.com/Pawel-N-pl/bmad-assist.git
cd bmad-assist
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

**Requirements:** Python 3.11+ and at least one LLM CLI tool ([Claude Code](https://claude.ai/code), [Gemini CLI](https://github.com/google-gemini/gemini-cli), or [Codex](https://github.com/openai/codex)).

> **Platform:** Linux and macOS only. Windows is not supported — the subprocess management layer depends on POSIX APIs (`os.killpg`, `signal.SIGKILL`, process groups, `start_new_session`) throughout the codebase. On Windows, use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install).

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

# Useful flags
bmad-assist run -g                        # Auto-commit after create/dev/synthesis phases
bmad-assist run -n                        # Non-interactive (no prompts, fail if config missing)
bmad-assist run --skip-story-prompts      # Skip prompts between stories (still prompt at epic boundaries)
bmad-assist run -v                        # Verbose - show INFO-level logs (phase progress, providers)
bmad-assist run --debug --full-stream     # Debug JSONL logging + full untruncated LLM output

# Typical production run (-n implies --skip-story-prompts)
bmad-assist run -g -n -v

# Setup
bmad-assist init -p ./project             # Initialize project
bmad-assist init --reset-workflows        # Restore bundled workflows

# Sprint
bmad-assist sprint generate
bmad-assist sprint validate
bmad-assist sprint sync

# A/B testing
bmad-assist experiment ab experiments/ab-tests/prompt-v2-test.yaml        # Run A/B test from definition
bmad-assist experiment ab-analysis experiments/ab-results/my-test-20260208  # Re-run LLM analysis on existing results
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
    - provider: codex
      model: gpt-5.3-codex
      reasoning_effort: high
    - provider: opencode-sdk
      model: opencode/glm-5-free

timeouts:
  default: 600
  dev_story: 3600
```

## Documentation

- [Configuration Reference](docs/configuration.md) - Providers, timeouts, paths, compiler settings
- [Providers Guide](docs/providers.md) - Setting up Claude Code, Gemini CLI, Codex, and other LLM tools
- [TEA Configuration](docs/tea-configuration.md) - Test Architect Enterprise switch hierarchy and modes
- [A/B Testing](docs/ab-testing.md) - Running controlled experiments comparing workflow configurations
- [Strategic Context](docs/strategic-context.md) - Smart document loading optimization
- [Sprint Management](docs/sprint-management.md) - Sprint status tracking and story lifecycle
- [Experiment Framework](docs/experiments.md) - Benchmarking with fixture isolation
- [Workflow Patches](docs/workflow-patches.md) - Customizing BMAD workflows for automation
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
