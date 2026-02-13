# Changelog

All notable changes to bmad-assist are documented in this file.

## [0.4.29] - 2026-02-13

### Added
- **Source Context Budgets** - Configurable token budgets per source context type with scoring-based file selection
- **Subprocess Fallback** - Automatic subprocess fallback in retry logic and multi-LLM orchestration when SDK fails
- **Outlier Filters** - Sigma-based outlier detection wired into validation/review handlers

### Fixed
- **SDK Provider Reliability** - Init timeout reduced to 10s, global flag for init fallback, early subprocess termination, bundled CLI for streaming protocol
- **Validation Resilience** - Truncate oversized validations instead of dropping; safety net to never reduce below synthesis minimum (2 reports)
- **Agent Teams Leak** - Prevent orphaned child processes, kill child process tree on Ctrl+C
- **Stream Termination** - Early stream termination for SDK provider and GLM-4.7 models with extended markers
- **Story Header Parsing** - Support French typographic convention (non-breaking space before colon) ([#15](https://github.com/Pawel-N-pl/bmad-assist/issues/15))
- **XML Sanitization** - Invalid XML control characters in CDATA sections now sanitized
- **Partial JSON Parsing** - Fallback parsing for incomplete JSON responses in assumption surfacing
- **Antipatterns Extraction** - Added "Minor" severity support to extraction regex
- **Crash/Resume** - Proper handling of empty `epic_stories` in crash/resume scenarios

### Changed
- **Sprint Reconciler** - Improved reconciliation logic and config updates
- **Display Model** - Use `display_model` (user-friendly name) in SDK logs instead of internal model ID

## [0.4.28] - 2026-02-10

### Added
- **Timeout Retry Configuration** - New `timeouts.retries` field (`None`=no retry, `0`=infinite, `N`=specific count) with shared `invoke_with_timeout_retry()` wrapper across all provider invocations (single-LLM phases, multi-LLM orchestrators, security agent). Security agent has independent `SecurityAgentConfig.retries` for separate control
- **Git Intelligence: Excluded Files** - Git status operations now properly filter excluded files from `DEFAULT_EXCLUDE_PATTERNS` and user config

### Changed
- **Timeout Retry Architecture** - Unified retry logic via shared wrapper: BaseHandler refactored, validation/code_review orchestrators integrated, security agent uses `functools.partial()`
- **Deep Verify & QA** - Batch boundary analysis (single LLM call per-finding), QA remediate enhancements (6-source aggregation, fix→retest loop, escalation reports)
- **Context Extraction** - Intelligent source file collection with configurable budgets and scoring

### Fixed
- **Security Review** - Output format enforcement with markdown fallback, synthesis variable deduplication
- **Provider Visibility** - Claude SDK progress logging for long-running tool invocations, robust file list parsing (any heading level, numbered lists, tables)
- **Git Intelligence** - Proper excluded file filtering in git status operations

### Docs
- **README** - Clarified `bmad-assist` as BMAD orchestration tool (not replacement)

## [0.4.27] - 2026-02-08

### Added
- **QA Remediate** - New `qa_remediate` epic_teardown phase: 6-source issue aggregation, master LLM fix→retest loop with regression detection, escalation reports. Externalized XML prompt (`qa/prompts/remediate.xml`) with proactive INVESTIGATE → FIX → ESCALATE workflow. Configurable via `QaConfig` (max iterations, age, safety cap)
- **Scorecard: Multi-Stack** - Python and Node/TS stack detection alongside Go; modular `stacks/` registry
- **A/B Testing** - QA artifacts snapshot support; loop config phase gating (phases filtered through variant's `loop:` config)

### Changed
- **Experiments** - Relocated evaluation/testing/scorecard from `experiments/` into `src/bmad_assist/experiments/`; monolithic `scorecard.py` split into `scorecard/` package

### Fixed
- **Sprint Sync** - Corrupted sprint-status log level downgraded from ERROR to WARNING

## [0.4.26] - 2026-02-08

### Added
- **A/B Analysis CLI** - Standalone `ab-analysis` command to re-run LLM analysis on existing A/B test results

### Changed
- **A/B Testing: Per-Story Refs** - Stories use `{id, ref}` objects; each pins to its own git commit. `analysis: true` enables LLM-powered variant comparison
- **Docs** - README rewrite with plain-language intro and new feature sections; experiments.md and ab-testing.md updated to match current code

### Fixed
- **Security: CodeQL Alerts** - Resolve 10 of 11 alerts: workflow permissions, socket binds hardened to localhost, URL assertion refactors
- **A/B: ConfigError on Analysis** - Fixed singleton reset crash in `generate_ab_analysis()`

## [0.4.25] - 2026-02-08

### Added
- **A/B Workflow Tester** - Comparative workflow testing with git worktree isolation, per-story ref checkouts, artifact snapshots, LLM analysis, workflow/template sets, and full config pass-through per variant
- **Deep Verify Synthesis: Grouped Findings** - Findings grouped by `file_path` with prioritization

### Performance
- **Providers: CPU/Memory Hotspots** - Replace busy-wait poll loop in `claude.py` with blocking `process.wait()` (10→2 wakeups/sec); reduce pause polling from 100ms to 2s; add `timeout=10` to `thread.join()` in all 8 subprocess providers

### Changed
- **Claude Provider: `claude` is now primary** - Use `provider: claude` (SDK-based) instead of `provider: claude-subprocess` (legacy). SDK provider now supports streaming input, cancel, display_model, and prefers system CLI. `claude-subprocess` is retained for benchmarking only. Upgrade `claude-agent-sdk` 0.1.20 → 0.1.33

### Fixed
- **A/B: Worktree Artifact Bleed** - Gitignored artifact dirs leaked between stories; now purged before each ref checkout
- **A/B: Hardcoded Provider** - Analysis used hardcoded `claude-sdk`/`opus` instead of master provider from config
- **Scorecard: Float Rounding** - Round scores to prevent IEEE 754 artifacts in YAML

## [0.4.24] - 2026-02-07

### Changed
- **Config: .example Convention** - Renamed `bmad-assist.yaml` to `bmad-assist.yaml.example` in published repo; user config (`bmad-assist.yaml`) is now gitignored. Standard copy-and-customize pattern

### Performance
- **Deep Verify: Batch Boundary Analysis** - Consolidate per-finding boundary analysis into single LLM call, reducing token usage and latency in code review phase

### Fixed
- **Security Review: 0% Detection Rate** - Security agent received empty diffs after artifact exclusions; fixed source code extraction and pattern matching
- **Deep Verify: File List Extraction** - Regex was extracting file descriptions instead of paths from DV output
- **Deep Verify: DV Report Aggregation** - Aggregate per-file DV results into single archival report during code review phase
- **Scorecard: Broken Metric** - Replaced non-functional `stories_completed` with `test_to_code_ratio` metric
- **Dashboard: Mixed ID Sorting** - Resolve `TypeError` when sorting stories with mixed numeric/string IDs (PR #11, thanks [@DevRGT](https://github.com/DevRGT))

## [0.4.23] - 2026-02-06

### Added
- **Scorecard v2.0** - Restructured `code_quality` (20 pts) into five sub-metrics: linting, complexity, security, test_pass_rate, code_maturity. KLOC-normalized gradient for gosec with FP filtering. Correctness proxy advisory checks for Go

### Fixed
- **Security Review: Zero Findings** - Diffs were dominated by `.bmad-assist/` and `_bmad-output/` metadata YAML; all source code was truncated away at `max_lines=500`. Added BMAD artifact exclusions to `DEFAULT_EXCLUDE_PATTERNS`, raised `max_lines` to 2000, and added diff section prioritization (source > test > config > other)
- **Security Review: Missing Metadata** - `detected_languages` and `patterns_loaded` were not propagated from `SecurityReviewCompiler` to `run_security_review()` via `CompiledWorkflow.variables`
- **Deep Verify: Domains Not Propagated** - Detected domains were never passed through the engine call chain (`_run_methods_with_errors` → `_run_single_method_with_result` → `_run_single_method`). Methods received `domains=None`, causing `_should_run_for_domains()` to return False and 6/8 methods to skip instantly with 0 findings
- **Loop: Epic Transition on Resume** - `advance_to_next_epic` failed when current epic was missing from filtered list after resume. Now jumps to first available epic (PR #2, thanks [@DevRGT](https://github.com/DevRGT))
- **Parser: Bracketed Statuses** - Support `[DONE]`/`[IN PROGRESS]` status format in story headers and mixed standard/fallback story formats in epic files (PR #1, thanks [@DevRGT](https://github.com/DevRGT))
- **Deep Verify: Helper Config** - Propagate helper provider config to `DomainDetector`; add pricing for `zai-coding-plan` models
- **Sharding: Empty Directory Precedence** - Single file now takes precedence over empty sharded directory
- **Anonymization: Provider Leak** - Removed provider/model fields from report YAML frontmatter that defeated reviewer anonymization; deanonymization mapping in `.bmad-assist/cache/` already stores this info
- **CI: Lint/Type Errors** - Fix 4 mypy errors in `epic_transitions.py`, 16 ruff issues in parser/sharding modules
- **Dependencies** - Remove `typer[all]` extra, bump typer to 0.21.1
- **Compiler** - Remove `__init__.py` from hyphenated `security-review` workflow directory (mypy fix)

## [0.4.22] - 2026-02-06

### Added
- **Security Review Agent** - Parallel security-focused reviewer in code review phase with CWE classification, confidence scoring, and severity-based handling in synthesis
- **Deep Verify: Phase Type** - `phase_type` field in DV reports distinguishes validation vs code review findings
- **Logging: Restructured Levels** - Verbose/debug/full-stream logging levels for granular output control

### Changed
- **Synthesis: Remove METRICS_JSON** - Removed LLM-generated quality/consensus metrics from both synthesis workflows. Fields like `follows_template` (always true), `missed_findings` (always 0), `internal_consistency` (self-assessment) provided no signal. Saves LLM context and time per synthesis run. Data recoverable from synthesis reports post-hoc if needed

### Fixed
- **Deep Verify: Line Number Coercion** - Coerce LLM `line_number` strings to int in all deep-verify methods
- **Security Reports: Zero Findings** - Always save archival security report even with zero findings
- **Loop: Resume After hard Kill** - Preserve resume position after hard kill via fsync + phase restore
- **Git: Empty Repo Branch Creation** - Use atomic `checkout -b` in `ensure_epic_branch` for empty repo support (no HEAD)
- **Providers: Reasoning Effort Param** - Add `reasoning_effort` parameter to all provider `invoke()` signatures

## [0.4.21] - 2026-02-06

### Added
