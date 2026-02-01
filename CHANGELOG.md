# Changelog

All notable changes to bmad-assist are documented in this file.

## [0.4.15] - 2026-02-01

### Added
- **Bundled TEA Knowledge Base** - All 34 knowledge fragments now ship with bmad-assist package, enabling TEA workflows to run without `_bmad/tea/testarch/` in target projects
- **TEA Master Switch** - `testarch.enabled` config option to completely disable all TEA functionality
- **Interactive Config Wizard** - `bmad-assist init --wizard` for guided configuration setup
- **Config Verify Command** - `bmad-assist verify` to validate configuration files
- **TEA Standalone Banners** - Visual phase banners and notifications for TEA standalone workflows
- **TEA Prompt Saving** - Unit tests for context enhancement and prompt saving

### Documentation
- **TEA Configuration Guide** - New `docs-public/tea-configuration.md` explaining switch hierarchy, `auto` mode behavior, and common configurations

### Fixed
- **Provider Signatures** - Add `display_model` and `thinking` params to BaseProvider.invoke() - fixes validation orchestrator errors with multi-LLM configs
- **Kimi Thinking Config** - Pass thinking configuration correctly to kimi provider
- **Phase Banners** - Add banners to epic setup/teardown phases for better visibility
- **TEA Patch Resolution** - Resolve `{installed_path}` placeholder in TEA workflow compilation
- **Knowledge Fragment IDs** - Fix incorrect IDs in defaults.py (`test-levels`, `test-priorities`)

### Changed
- **Bundled Workflows** - All 8 TEA workflows now bundled for fallback when BMAD not installed
- **Knowledge Fallback** - Loader now falls back to bundled knowledge base when project has none

## [0.4.14] - 2026-01-31

### Added
- **Epic 25: TEA Enterprise Full Integration** - Complete Test Architect module with 8 workflows:
  - `testarch-atdd` - ATDD checklist generation
  - `testarch-trace` - Traceability matrix
  - `testarch-test-review` - Test code review
  - `testarch-framework` - Test framework setup
  - `testarch-ci` - CI/CD test integration
  - `testarch-test-design` - Test design documents
  - `testarch-automate` - Test automation discovery
  - `testarch-nfr-assess` - NFR assessment
- **KimiProvider** - New provider for kimi-cli (MoonshotAI) integration
- **TEA Context Loader** - Artifact injection from previous TEA runs (ATDD checklists, test-design docs) into workflow prompts
- **Context services for TEA workflows** - StrategicContextService, TEAContextService, SourceContextService integration with per-workflow configuration
- **Prompt saving for TEA workflows** - All TEA handlers now save compiled prompts to `.bmad-assist/prompts/` for debugging
- **CLI observability** - Run tracking with timestamps and staggered parallel execution
- **`--tea` flag** - Enable full TEA loop configuration (all 8 TEA phases)
- **TEA workflow configs** - Per-workflow strategic context settings (project-context, prd, architecture)
- **TEA source budgets** - 10000 tokens for automate/nfr-assess, disabled for other TEA workflows
- **Notifications:** Credential masking and phase completion events
- **Sprint repair logging** - Loud logging when new entries added during repair

### Fixed
- **Notifications:** Eliminate duplicate `phase_completed` events, add TEA phase support with proper labels
- **Workflow paths:** Two bugs in workflow path resolution
- **Placeholders:** Standardize format to `{project-root}` across codebase
- **Patch compiler:** Add testarch workflow name mapping (testarch-atdd → tea-atdd)
- **Loop messages:** Remove misleading "guardian halt" message on normal phase failure
- **Parser:** Support non-standard story formats with Priority anchor
- **Kimi:** Handle array content format in kimi-cli responses
- **Kimi:** Use full model name `kimi-code/kimi-for-coding`
- **Benchmarking:** Use actual provider names in evaluation records
- **Patches:** Update code-review patch for 6-step workflow

### Changed
- **Performance:** Lazy loading for heavy imports (providers, core, handlers) - faster CLI startup
- **Loop config:** `DEFAULT_LOOP_CONFIG` now minimal (standard phases only), use `--tea` for full TEA integration
- **README:** Improved feature descriptions and added community section

## [0.4.13] - 2026-01-29

### Added
- **Interactive element detection** - CRITICAL warning when workflow contains `<ask>` elements without patch (prevents hangs in non-interactive/subprocess mode)
- **Auto-discover epics directory** in `project_knowledge` path

### Fixed
- **Compiler:** Escaped XML comment placeholders in CDATA - fixes METRICS_JSON markers appearing as `<__xml_comment__>` in compiled prompts
- **Compiler:** Downgrade missing patch log from CRITICAL to DEBUG (not an error for custom workflows without bundled patches)
- **Config:** Missing workflow fields in `StrategicContextConfig`
- **CLI:** Use config paths for epic loading instead of hardcoded `docs/`
- **CLI:** Pass `bmad_paths.epics` to `init_paths` in all commands

### Changed
- Example `bmad-assist.yaml` marked as optimized reference configuration

## [0.4.12] - 2026-01-28

### Added
- **Flexible Epic Story Parser** with fallback for non-standard formats (thanks @Richard)
  - Parses `PRSP-5-1`, `REFACTOR-2-1` style story headers when standard `## Story X.Y:` not found
  - Status-anchored detection: finds stories by `**Status:**` field presence
  - Sequential numbering (1.1, 1.2, 1.3...) regardless of original IDs
  - New `code` field on `EpicStory` preserves original story codes
  - Mixed heading levels supported (###, ####, #####)
  - Non-standard dependency extraction (`**Dependencies:** PRSP-5-1, PRSP-5-2`)
- **Default patches fallback** for pip-installed users without local BMAD installation (thanks [@mattbrun](https://github.com/mattbrun))
- **GitHub Actions CI** workflow for tests, mypy, and ruff
- **Test health initiative** completed - mutation testing analysis, 73% mutation score achieved

### Fixed
- **Scorecard:** gosec reliability and error handling, eliminate false positives when tools not installed
- **Config validation:** identify specific config file causing errors, include actual validation error in messages
- **Strategic context:** truncate docs instead of skipping when over token budget (thanks [@mattbrun](https://github.com/mattbrun))
- **Mypy:** resolve all type errors, enable strict CI checks
- **CI tests:** Rich/Typer help tests now skip properly in Docker/root environments

### Changed
- `_extract_status()` now cleans trailing asterisks (handles typos like `done**`)
- `_parse_story_sections()` accepts optional `epic_num` and `path` parameters

## [0.4.11] - 2026-01-27

### Added
- **Per-phase model configuration** (`phase_models`) - specify different LLM providers/models for each workflow phase
  - Single-LLM phases: object format with `provider`, `model`, `model_name`, `settings`
  - Multi-LLM phases: array format with full control over validator/reviewer list
  - Phases not in `phase_models` fall back to global `providers` config
  - Settings path validation with tilde expansion
- **23 unit tests** for phase_models validation, resolution, and fallback behavior
- **Documentation** for per-phase configuration in `docs/configuration.md`

### Changed
- **Breaking:** When `phase_models` defines a multi-LLM phase (`validate_story`, `code_review`), master is NOT auto-added - user has full control over the list
- When falling back to global `providers.multi` (no phase_models override), master IS still auto-added (existing behavior preserved)

## [0.4.10] - 2026-01-27

### Added
- **`bmad-assist test scorecard <fixture>`** command for automated quality scoring of experiment fixtures
  - Completeness: TODOs, placeholders, empty files detection
  - Functionality: build verification, unit tests, behavior tests
  - Code Quality: linting (go vet), complexity (gocyclo), security (gosec)
  - Documentation: README, API docs, inline comments ratio
- **Experiment prerequisites documentation** (`docs/experiments/prerequisites.md`)
- **Benchmark fixtures release** with webhook-relay-001, 002, 003 (available in GitHub Releases)

### Fixed
- **Scorecard false positives** when Go tools not installed - now correctly reports `skipped: true` with reason instead of giving max scores
- Graceful degradation for missing `gocyclo` and `gosec` tools

### Changed
- Scorecard defaults changed from max to 0 for code_quality when tools unavailable

### Benchmark Results
First empirical validation of Antipatterns module effectiveness:

| Fixture | Config | Score | Build | Tests |
|---------|--------|-------|-------|-------|
| webhook-relay-001 | baseline | 40.0% | FAIL | 252 |
| webhook-relay-002 | strategic context | 28.2% | FAIL | 0 |
| webhook-relay-003 | strategic + antipatterns | **55.3%** | **PASS** | **1254** |

Key findings:
- Strategic context alone caused regression (-11.8pp)
- Antipatterns module improved quality significantly (+15.3pp vs baseline, +27.1pp vs strategic-only)
- 5x more unit tests generated with antipatterns guidance

## [0.4.9] - 2026-01-25

### Changed
- **refactor(config):** Split `config.py` into modular `core/config/` package
- **refactor(providers):** Extract shared helpers, add cross-platform `platform_command.py` (thanks [@mattbrun](https://github.com/mattbrun))
- **refactor(loop):** Split `runner.py` into 5 helper modules
- **refactor(antipatterns):** Replace LLM extraction with deterministic regex

### Fixed
- Full mypy/ruff compliance across 102 files

## [0.4.8] - 2026-01-25

### Added
- **Strategic Context Optimization** for workflow compilers - configurable loading of strategic docs (PRD, Architecture, UX, project-context)
  - New `strategic_context` section in bmad-assist.yaml with per-workflow overrides
  - `StrategicContextService` replaces hardcoded document loading
  - Token budget enforcement and `main_only` flag for sharded docs
  - Benchmark analysis showed 0% PRD usage in code-review → excluded by default
  - `create_story`: all docs (prd, architecture, ux, project-context), indexes only
  - `validate_story`: project-context + architecture only
  - `dev_story`, `code_review`, synthesis workflows: project-context only

## [0.4.7] - 2026-01-23

### Added
- **Cursor Agent provider** for Multi-LLM orchestration (subprocess-based)
  (thanks [@mattbrun](https://github.com/mattbrun))
- **GitHub Copilot provider** for Multi-LLM orchestration (subprocess-based)
  (thanks [@mattbrun](https://github.com/mattbrun))

## [0.4.6] - 2026-01-23

### Added
- **Evidence Score System** for validation and code review workflows - replaces 1-10 scoring with mathematical model
  - CRITICAL (+3), IMPORTANT (+1), MINOR (+0.3), CLEAN PASS (-0.5)
  - Deterministic verdict thresholds: ≥6 REJECT, 4-6 REWORK, ≤3 READY/APPROVE, ≤-3 EXCELLENT/EXEMPLARY
  - Mandatory evidence enforcement ("no quote, no finding" for stories; "no code snippet, no finding" for code review)
  - Anti-Bias Battery with 5 self-checks (Devil's Advocate, Ego Check, Context Check, Best Intent, Pattern Recognition)
  - Based on Deep Verify methodology by [@LKrysik](https://github.com/LKrysik/BMAD-METHOD) 🎯
- Evidence Score extraction in `validation_metrics.py` with backward compatibility
- New regex patterns for Evidence Score report parsing
- `bmad-assist patch compile-all` command for batch compilation of all patches without valid cache
- Per-phase timeout configuration via `timeouts:` section in bmad-assist.yaml
- Antipatterns extraction from synthesis reports for organizational learning
- Source context support for validation workflows (story file, epic context)
- Auto-generate sprint-status.yaml from epic files when missing

### Fixed
- Python 3.14+ compatibility: `Traversable` import moved to `importlib.resources.abc` (thanks [@mattbrun](https://github.com/mattbrun))
- Clearer error messages for outdated/incompatible cache files
- Evidence Score calculation deduplication in code review reports
- `webhook-relay` experiment fixture repaired (other fixtures still broken)

### Changed
- `validate-story` workflow now uses Evidence Score instead of 1-10 severity
- `validate-story-synthesis` workflow updated for CRITICAL/IMPORTANT/MINOR terminology
- `code-review` workflow now uses Evidence Score with mandatory code snippet enforcement
- `code-review-synthesis` workflow updated for CRITICAL/IMPORTANT/MINOR terminology
- `ValidatorMetrics` dataclass extended with Evidence Score fields
- `AggregateMetrics` with auto-detection of report format (legacy vs Evidence Score)
- `format_deterministic_metrics_header()` dynamically switches output format
- Providers now accept any model format without hardcoded restrictions

## [0.4.5] - 2026-01-21

### Added
- Project setup consolidation - `init` and `run` now copy bundled workflows
- Batch overwrite prompt `[a/s/i/d/?]` when local workflows differ from bundled
- `--reset-workflows` flag for `init` command to restore bundled versions
- `warnings.suppress_gitignore` config option to silence gitignore warnings
- Exit code 2 for "success with warnings" (workflows skipped in CI)

### Changed
- `init` command refactored to use shared `ensure_project_setup()` logic
- `run` command now performs implicit project setup (without gitignore changes)
- File copy uses atomic write with rollback on partial failure

### Security
- Path traversal protection in workflow copying
- Symlinks not followed during file operations
- Temp files created with 0o644 permissions

## [0.4.4] - 2026-01-21

### Added
- OpenCode provider for Multi-LLM validation (subprocess-based, JSON streaming)
- Amp provider for Sourcegraph's Claude wrapper (smart mode only)
- Three-tier config hierarchy: Global → CWD → Project

### Fixed
- Config loading now respects CWD when using `--project` flag
- OpenCode provider accepts any `provider/model` format (no hardcoded list)

## [0.4.3] - 2026-01-21

### Added
- CLI `--phase` flag to override starting phase in development loop

### Changed
- Sprint reconciler with forward-only protection and improved entry ordering
- Retrospective entries now tracked in sprint-status.yaml

## [0.4.2] - 2026-01-20

### Added
- Bundled workflow templates for standalone package distribution
- External docs support - planning artifacts can live outside project root
- Configurable loop phases via `loop:` key in bmad-assist.yaml

### Changed
- Paths singleton pattern for consistent path resolution
- Project knowledge path added to CompilerContext

### Fixed
- Patch/cache discovery in subprocess and experiment contexts
- Sprint-status sync before project completion
- ruamel.yaml now a required dependency

## [0.4.1] - 2026-01-15

### Changed
- Modularized CLI commands (patch, benchmark, sprint, experiment, qa)
- Modularized dashboard routes into package structure

### Fixed
- Test suite async isolation and E2E skip handling
- Story counting in sync and QA result parsing

## [0.4.0] - 2026-01-10

### Added
- Sprint-status auto-repair and reconciliation
- Human-readable notification formatting with story titles
- Descriptive prompt filenames (epic/story/phase identifiers)
- Auto-archive artifacts after code review synthesis

### Changed
- Unified phase naming convention across all components
- Report extraction with flexible fallbacks for Multi-LLM outputs

### Fixed
- Validator tools restricted to read-only operations
- Code review anonymization and report extraction

## [0.3.0] - 2025-12-28

### Added
- Workflow compiler with variable resolution and patch system
- Multi-LLM validation with output anonymization
- Benchmarking module for LLM performance metrics
- Code review orchestration with Multi-LLM synthesis
- Telegram and Discord notification providers
- Context menu system for story/phase actions

### Changed
- Provider pattern with BaseProvider ABC for CLI adapters
- Atomic state persistence with temp file + rename

## [0.1.1] - 2025-12-15

### Added
- Typer CLI with Pydantic configuration models
- BMAD file parsing (markdown frontmatter, epic files)
- YAML state persistence with atomic writes
- LLM providers: Claude, Codex, Gemini CLI
- Development loop with phase execution and transitions
- Multi-LLM parallel orchestration with Master synthesis

### Notes
- Initial release with core development loop functionality
