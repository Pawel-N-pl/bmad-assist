# bmad-assist

CLI tool for automating the [BMAD](https://github.com/bmad-method) development methodology with Multi-LLM orchestration.

## What is BMAD?

BMAD (Brian's Methodology for AI-Driven Development) is a structured approach to software development that leverages AI assistants throughout the entire lifecycle.

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

- **Multi-LLM Orchestration** - Claude Code, Gemini CLI, Codex, OpenCode, Amp, Cursor Agent, GitHub Copilot
- **Evidence Score System** - Mathematical validation scoring with anti-bias checks
- **Workflow Compiler** - Transform BMAD workflows into optimized prompts
- **Strategic Context Optimization** - Smart loading of PRD/Architecture per workflow
- **Patch System** - Customize workflows per-project without forking
- **Bundled Workflows** - All BMAD workflows included, no extra setup

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

# Configure providers in bmad-assist.yaml (see docs/configuration.md)

# Run the development loop
bmad-assist run --project /path/to/your/project
```

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

# Setup
bmad-assist init -p ./project             # Initialize project
bmad-assist init --reset-workflows        # Restore bundled workflows

# Compilation
bmad-assist compile -w dev-story -e 5 -s 3

# Patches
bmad-assist patch list
bmad-assist patch compile-all

# Sprint
bmad-assist sprint generate
bmad-assist sprint validate
bmad-assist sprint sync
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

## Development

```bash
pytest -q --tb=line --no-header
mypy src/
ruff check src/
```

## License

MIT

## Links

- [BMAD Method](https://github.com/bmad-method) - The methodology behind this tool
