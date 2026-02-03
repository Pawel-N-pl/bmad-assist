# Benchmarking

The benchmarking module collects, stores, and analyzes LLM evaluation metrics from multi-LLM validation and code review workflows. It enables comparison of workflow variants, model performance, and validation accuracy measurement through ground truth correlation.

## Problem

When running multi-LLM validation or code review with bmad-assist, you need answers to:
- Which LLM models produce the most actionable findings?
- How do different workflow variants compare in quality metrics?
- Are validation findings accurate (confirmed by code review)?
- Which models tend to over-report or under-report issues?

Without metrics collection, these questions require manual analysis of individual reports.

## Solution

The benchmarking module provides:
- **Automatic metrics collection** during validation and code review phases
- **Deterministic metrics** (55%) calculated from output text: structure, linguistics, reasoning
- **LLM-extracted metrics** (45%) using a lightweight model: findings classification, quality signals
- **YAML storage** with atomic writes and query-optimized indexes
- **Comparison reports** for workflow variants and models
- **Ground truth** correlation with code review for precision/recall

## Configuration

Add to your `bmad-assist.yaml`:

```yaml
benchmarking:
  enabled: true                    # Enable metrics collection (default: true)
  extraction_provider: claude      # Provider for LLM extraction (default: claude)
  extraction_model: haiku          # Model for extraction (default: haiku)
```

When `providers.helper` is configured, it overrides `extraction_provider` and `extraction_model`:

```yaml
providers:
  helper:
    provider: claude-subprocess
    model: haiku

benchmarking:
  enabled: true
  # extraction_provider/extraction_model ignored when helper is configured
```

The helper provider is recommended as it consolidates configuration for all lightweight LLM tasks.

Metrics are automatically collected during `validate_story` and `code_review` phases.

## Storage Location

Evaluation records are stored in:

```
_bmad-output/implementation-artifacts/benchmarks/
├── 2026-01/
│   ├── index.yaml                              # Month index for fast queries
│   ├── eval-12-3-a-20260115-143022.yaml       # Validator A record
│   ├── eval-12-3-b-20260115-143024.yaml       # Validator B record
│   ├── eval-12-3-synthesizer-20260115-143030.yaml
│   └── eval-12-3-master-20260115-150000.yaml  # Master timing record
└── 2026-02/
    └── ...
```

**File naming pattern**: `eval-{epic}-{story}-{role}-{timestamp}.yaml`

Role segments:
- `a-z`: Validator letters
- `synthesizer`: Synthesis phase
- `master`: Master LLM timing (create-story, dev-story)

## CLI Commands

### Compare Workflow Variants

Compare metrics between two workflow variants (e.g., different prompt patches):

```bash
# Compare variants with markdown report to stdout
bmad-assist benchmark compare -a default -b multi-llm

# Save to file with date filtering
bmad-assist benchmark compare -a default -b optimized \
    --from 2026-01-01 --to 2026-01-31 \
    -o comparison-report.md

# Project in different directory
bmad-assist benchmark compare -a v1 -b v2 --project /path/to/project
```

**Output**: Markdown report with sample sizes, per-metric comparison table, statistical significance testing (requires scipy), and interpretation.

### Compare Models

Compare all LLM models used in evaluations:

```bash
# Markdown report to stdout
bmad-assist benchmark models

# JSON output for programmatic use
bmad-assist benchmark models --format json -o models.json

# Filter by date range
bmad-assist benchmark models --from 2026-01-01 --to 2026-01-31
```

**Output**: Summary table with evaluation counts, findings averages, severity focus, false positive rates (when ground truth available), severity distribution breakdown, and model tendencies analysis.

## Evaluation Record Schema

Each evaluation record contains nested models tracking different metric categories:

### Core Identity

| Field | Source | Description |
|-------|--------|-------------|
| `record_id` | Deterministic | UUID4 identifier |
| `created_at` | Deterministic | UTC timestamp |
| `workflow.id` | Deterministic | Workflow identifier (e.g., `validate-story`) |
| `workflow.variant` | Deterministic | Variant name (e.g., `default`, `multi-llm`) |
| `story.epic_num` | Deterministic | Epic number |
| `story.story_num` | Deterministic | Story number |
| `evaluator.provider` | Deterministic | Provider name (e.g., `claude`, `gemini`) |
| `evaluator.model` | Deterministic | Model identifier |
| `evaluator.role` | Deterministic | `VALIDATOR`, `SYNTHESIZER`, or `MASTER` |

### Execution Telemetry

| Field | Source | Description |
|-------|--------|-------------|
| `execution.start_time` | Deterministic | UTC start timestamp |
| `execution.end_time` | Deterministic | UTC end timestamp |
| `execution.duration_ms` | Deterministic | Duration in milliseconds |
| `execution.input_tokens` | Deterministic | Input token count |
| `execution.output_tokens` | Deterministic | Output token count |

### Output Analysis (Deterministic)

| Field | Source | Description |
|-------|--------|-------------|
| `output.char_count` | Deterministic | Total character count |
| `output.heading_count` | Deterministic | Number of markdown headings |
| `output.list_depth_max` | Deterministic | Maximum nested list depth |
| `output.code_block_count` | Deterministic | Number of code blocks |
| `output.sections_detected` | Deterministic | List of heading texts |

### Linguistic Fingerprint

| Field | Source | Description |
|-------|--------|-------------|
| `linguistic.avg_sentence_length` | Deterministic | Average words per sentence |
| `linguistic.vocabulary_richness` | Deterministic | Type-token ratio |
| `linguistic.flesch_reading_ease` | Deterministic | Flesch readability score |
| `linguistic.vague_terms_count` | Deterministic | Count of vague terms |
| `linguistic.formality_score` | LLM Assessed | Formality (0.0-1.0) |
| `linguistic.sentiment` | LLM Assessed | `positive`, `neutral`, `negative`, `mixed` |

### Reasoning Patterns

| Field | Source | Description |
|-------|--------|-------------|
| `reasoning.cites_prd` | Deterministic | Regex detection of PRD references |
| `reasoning.cites_architecture` | Deterministic | Regex detection of architecture refs |
| `reasoning.cites_story_sections` | Deterministic | Regex detection of AC/Task patterns |
| `reasoning.uses_conditionals` | Deterministic | Regex detection of if/when/unless |
| `reasoning.uncertainty_phrases_count` | Deterministic | Count of uncertainty phrases |
| `reasoning.confidence_phrases_count` | Deterministic | Count of confidence phrases |

Note: Reasoning pattern detection uses regex matching, not semantic analysis. A false positive may occur if the pattern appears in unrelated context.

### Findings Extracted (Validator Records)

| Field | Source | Description |
|-------|--------|-------------|
| `findings.total_count` | LLM Extracted | Total number of findings |
| `findings.by_severity` | LLM Extracted | Counts by severity level |
| `findings.by_category` | LLM Extracted | Counts by category |
| `findings.has_fix_count` | LLM Extracted | Findings with suggested fixes |
| `findings.has_location_count` | LLM Extracted | Findings with file/line refs |
| `findings.has_evidence_count` | LLM Extracted | Findings citing sources |

**Severity levels**: `critical`, `major`, `minor`, `nit`

**Categories**: `security`, `performance`, `correctness`, `completeness`, `clarity`, `testability`

### Quality Signals (Synthesizer Records)

| Field | Source | Description |
|-------|--------|-------------|
| `quality.actionable_ratio` | LLM Assessed | Ratio of actionable findings (0-1) |
| `quality.specificity_score` | LLM Assessed | Specificity assessment (0-1) |
| `quality.evidence_quality` | LLM Assessed | Evidence quality score (0-1) |
| `quality.internal_consistency` | LLM Assessed | Consistency score (0-1) |
| `quality.follows_template` | Deterministic | Output follows expected format |

### Consensus Data (Synthesizer Records)

| Field | Source | Description |
|-------|--------|-------------|
| `consensus.agreed_findings` | Synthesizer | Findings agreed by 2+ validators |
| `consensus.unique_findings` | Synthesizer | Single-validator findings |
| `consensus.disputed_findings` | Synthesizer | Conflicting assessments |
| `consensus.agreement_score` | Synthesizer | Overall agreement (0-1) |
| `consensus.missed_findings` | Post-hoc | From ground truth |
| `consensus.false_positive_count` | Post-hoc | From ground truth |

### Ground Truth (Post-hoc)

| Field | Source | Description |
|-------|--------|-------------|
| `ground_truth.populated` | Post-hoc | Whether populated from code review |
| `ground_truth.populated_at` | Post-hoc | UTC timestamp |
| `ground_truth.findings_confirmed` | Post-hoc | Validated findings confirmed |
| `ground_truth.findings_false_alarm` | Post-hoc | False positive count |
| `ground_truth.issues_missed` | Post-hoc | Issues missed by validation |
| `ground_truth.precision` | Post-hoc | confirmed / (confirmed + false_alarm) |
| `ground_truth.recall` | Post-hoc | confirmed / (confirmed + missed) |

## Metric Source Types

Each field is annotated with its source:

| Source | Description |
|--------|-------------|
| `DETERMINISTIC` | Calculated by Python code, 100% reproducible |
| `LLM_EXTRACTED` | LLM parses structured data from output |
| `LLM_ASSESSED` | LLM makes qualitative judgment |
| `SYNTHESIZER` | Filled by synthesis phase |
| `POST_HOC` | Filled after later phases (code review) |

## Master LLM Timing

For `create-story` and `dev-story` workflows, timing records track execution duration without full metrics extraction:

```yaml
# eval-12-3-master-20260115-150000.yaml
workflow:
  id: create-story
  variant: default
evaluator:
  role: master
  provider: claude
  model: opus
execution:
  start_time: "2026-01-15T15:00:00+00:00"
  end_time: "2026-01-15T15:02:30+00:00"
  duration_ms: 150000
```

This enables tracking Master LLM performance across stories without the overhead of full metrics extraction.

## Workflow Variant Comparison

The `compare_workflow_variants` function aggregates metrics by role:

- **Validator records**: `mean_findings_count`, findings distribution
- **Synthesizer records**: `agreement_score`, `actionable_ratio`, `specificity_score`

Statistical significance testing uses two-tailed t-test (requires scipy):
- Minimum 10 samples per variant per metric
- p < 0.05 threshold for significance

## Model Comparison

The `compare_models` function analyzes behavioral tendencies:

- **Verbosity detection**: char_count > 1.4x median = "Verbose reports"
- **Terseness detection**: char_count < 0.6x median = "Concise reports"
- **Category bias**: severity % > 1.5x average = "Over-reports {severity}"
- **Low confidence**: < 5 evaluations flagged with warning

## Ground Truth Population

After code review completes, ground truth correlates validation findings with actual issues:

1. Parse code review output for findings (issues, problems sections)
2. Parse validation report for findings
3. Match using fuzzy string similarity (SequenceMatcher, threshold 0.6)
4. Category and severity matches boost score (+0.1, +0.05)
5. Calculate precision and recall

```python
# Precision: How many validation findings were correct?
precision = confirmed / (confirmed + false_alarm)

# Recall: How many real issues did validation catch?
recall = confirmed / (confirmed + missed)
```

## Querying Records

Use the storage API for programmatic access:

```python
from bmad_assist.benchmarking import (
    list_evaluation_records,
    load_evaluation_record,
    get_records_for_story,
    RecordFilters,
    EvaluatorRole,
)

# List all records with filters
summaries = list_evaluation_records(
    base_dir=project_path / "_bmad-output/implementation-artifacts",
    filters=RecordFilters(
        epic=12,
        story=3,
        role=EvaluatorRole.VALIDATOR,
        workflow_id="validate-story",
    ),
)

# Load full record
for summary in summaries:
    record = load_evaluation_record(summary.path)
    print(f"{record.evaluator.provider}: {record.findings.total_count} findings")

# Get all records for a story
records = get_records_for_story(epic_id=12, story_id=3, base_dir=base_dir)
```

## Integration with Development Loop

When `benchmarking.enabled: true`:

1. **validate_story phase**: Each validator's output is analyzed
   - Deterministic metrics collected immediately
   - LLM extraction runs in parallel with synthesis

2. **validate_story_synthesis phase**: Synthesizer record created
   - Consensus data populated
   - Quality signals assessed

3. **code_review phase**: Triggers ground truth population
   - Matches validation findings to code review issues
   - Updates precision/recall metrics

4. **create_story / dev_story phases**: Master timing recorded
   - Duration, tokens, output analysis

## Troubleshooting

### No records found

Check that benchmarking is enabled and the correct base directory:
```bash
ls -la _bmad-output/implementation-artifacts/benchmarks/
```

### Missing LLM-extracted metrics

Verify extraction provider is configured. Either use helper provider:
```yaml
providers:
  helper:
    provider: claude-subprocess
    model: haiku
```

Or configure explicitly:
```yaml
benchmarking:
  enabled: true
  extraction_provider: claude
  extraction_model: haiku
```

### Index corruption

If queries return unexpected results, rebuild the index:
```bash
rm _bmad-output/implementation-artifacts/benchmarks/*/index.yaml
# Records will be re-indexed on next query
```

### Statistical significance unavailable

Install scipy for significance testing:
```bash
pip install scipy
```

## See Also

- [Configuration Reference](configuration.md) - Enable benchmarking in config
- [Providers Reference](providers.md) - Configure helper provider for extraction
- [Experiments](experiments.md) - Run controlled benchmarking experiments (planned)
