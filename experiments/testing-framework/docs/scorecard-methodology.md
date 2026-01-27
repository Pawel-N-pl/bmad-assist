# Scorecard Methodology

## Purpose

The Quality Scorecard provides a standardized, reproducible evaluation of AI-generated fixtures. It combines automated metrics with targeted manual review to produce an overall quality score.

## Scoring Categories

| Category | Weight | Automation | Description |
|----------|--------|------------|-------------|
| Completeness | 25% | Full | Are all stories implemented? |
| Functionality | 25% | Full | Does it work correctly? |
| Code Quality | 20% | Full | Is the code well-structured? |
| Documentation | 15% | Partial | Is it documented? |
| UI/UX | 15% | Manual | Is the UI usable? (if applicable) |

---

## 1. Completeness (25%)

**Measures:** Did bmad-assist complete all requested work?

### Automated Checks

| Metric | Points | Measurement |
|--------|--------|-------------|
| Stories completed | 10 | `done / total` from sprint-status.yaml |
| No TODO/FIXME | 5 | `grep -r "TODO\|FIXME" src/` count |
| No placeholder code | 5 | Pattern match for `pass`, `NotImplemented`, `panic("not implemented")` |
| No empty files | 5 | Files with <10 bytes content |

### Scoring Formula

```python
def score_completeness(fixture_path):
    scores = {
        "stories_completed": (done_count / total_count) * 10,
        "no_todos": max(0, 5 - (todo_count * 0.5)),  # -0.5 per TODO
        "no_placeholders": max(0, 5 - (placeholder_count * 1)),
        "no_empty_files": 5 if empty_count == 0 else 0,
    }
    return sum(scores.values())  # Max: 25
```

---

## 2. Functionality (25%)

**Measures:** Does the generated code work?

### Automated Checks

| Metric | Points | Measurement |
|--------|--------|-------------|
| Build succeeds | 10 | `go build` / `npm build` / `pip install -e .` |
| Unit tests pass | 10 | `go test` / `pytest` / `npm test` |
| Behavioral tests pass | 5 | `pytest experiments/fixture-tests/{fixture}/` |

### Scoring Formula

```python
def score_functionality(fixture_path):
    build_ok = run_build(fixture_path)  # Boolean
    unit_tests = run_unit_tests(fixture_path)  # (passed, failed, skipped)
    behavior_tests = run_behavior_tests(fixture_path)  # (passed, failed)

    scores = {
        "build": 10 if build_ok else 0,
        "unit_tests": (unit_tests.passed / (unit_tests.passed + unit_tests.failed)) * 10,
        "behavior_tests": (behavior_tests.passed / max(1, behavior_tests.total)) * 5,
    }
    return sum(scores.values())  # Max: 25
```

### Build Detection

The framework auto-detects build systems:

| Indicator | Build Command |
|-----------|---------------|
| `go.mod` | `go build ./...` |
| `package.json` | `npm install && npm run build` |
| `pyproject.toml` | `pip install -e .` |
| `Cargo.toml` | `cargo build` |
| `docker-compose.yaml` | `docker-compose build` |

---

## 3. Code Quality (20%)

**Measures:** Is the code maintainable?

### Automated Checks

| Metric | Points | Tool | Threshold |
|--------|--------|------|-----------|
| Linting passes | 8 | ruff/golint/eslint | <5 errors |
| Low complexity | 6 | radon/gocyclo | Avg CC <10 |
| No security issues | 6 | bandit/gosec/npm audit | 0 high/critical |

### Scoring Formula

```python
def score_code_quality(fixture_path):
    lint_errors = run_linter(fixture_path)  # Error count
    avg_complexity = calculate_complexity(fixture_path)
    security_issues = run_security_scan(fixture_path)  # (high, medium, low)

    scores = {
        "linting": max(0, 8 - lint_errors),  # -1 per error, min 0
        "complexity": 6 if avg_complexity < 10 else (3 if avg_complexity < 15 else 0),
        "security": 6 if security_issues.high == 0 else (3 if security_issues.high < 3 else 0),
    }
    return sum(scores.values())  # Max: 20
```

### Language-Specific Tools

| Language | Linter | Complexity | Security |
|----------|--------|------------|----------|
| Go | golint / staticcheck | gocyclo | gosec |
| Python | ruff | radon | bandit |
| JavaScript | eslint | complexity-report | npm audit |
| Rust | clippy | -- | cargo audit |

---

## 4. Documentation (15%)

**Measures:** Is the project documented?

### Automated Checks

| Metric | Points | Measurement |
|--------|--------|-------------|
| README exists | 4 | File exists and >100 chars |
| README has sections | 3 | Contains: install, usage, config |
| API docs exist | 4 | OpenAPI/Swagger or docs/api.md |
| Inline comments | 4 | Comment ratio >5% in main files |

### Scoring Formula

```python
def score_documentation(fixture_path):
    readme = analyze_readme(fixture_path)
    api_docs = find_api_docs(fixture_path)
    comment_ratio = calculate_comment_ratio(fixture_path)

    scores = {
        "readme_exists": 4 if readme.exists and readme.length > 100 else 0,
        "readme_sections": sum(1 for s in ["install", "usage", "config"] if s in readme.text.lower()),
        "api_docs": 4 if api_docs else 0,
        "comments": min(4, int(comment_ratio / 5 * 4)),  # 5% = 1pt, 20% = 4pt
    }
    return sum(scores.values())  # Max: 15
```

### Required README Sections

For full points, README should contain:
- **Installation** - How to set up the project
- **Usage** - How to run/use the application
- **Configuration** - Environment variables, config files

---

## 5. UI/UX (15%)

**Measures:** Is the interface usable? (Manual review only)

### When Applicable

This category applies when the fixture has a web UI. If no UI exists, redistribute points:
- Completeness: 30% (+5)
- Functionality: 30% (+5)
- Code Quality: 25% (+5)
- Documentation: 15% (unchanged)

### Manual Checklist

| Aspect | Points | Criteria |
|--------|--------|----------|
| Responsive layout | 3 | Works on mobile, tablet, desktop |
| Navigation clarity | 3 | User can find key features |
| Error feedback | 3 | Clear error messages, no silent failures |
| Loading states | 3 | Spinners, disabled buttons during async |
| Visual consistency | 3 | Consistent colors, spacing, fonts |

### Evaluation Process

1. **Launch the application** in a browser
2. **Walk through primary journeys** (create, read, update, delete)
3. **Test responsive design** (resize browser, mobile emulation)
4. **Trigger error states** (invalid input, network errors)
5. **Score each aspect** (0-3 points)

---

## Generating a Scorecard

### Command Line

```bash
python -m experiments.testing_framework.common.scorecard webhook-relay-001
```

### Output Format

```yaml
# experiments/analysis/scorecards/webhook-relay-001.yaml
fixture: webhook-relay-001
generated_at: "2026-01-26T12:00:00Z"
version: "1.0"

scores:
  completeness:
    weight: 25
    score: 23
    details:
      stories_completed: 10  # 24/24
      no_todos: 3            # 4 TODOs found
      no_placeholders: 5     # None found
      no_empty_files: 5      # None found

  functionality:
    weight: 25
    score: 25
    details:
      build: 10
      unit_tests: 10         # 48/48 passed
      behavior_tests: 5      # 12/12 passed

  code_quality:
    weight: 20
    score: 17
    details:
      linting: 6             # 2 warnings
      complexity: 6          # Avg CC: 8.2
      security: 5            # 1 medium issue

  documentation:
    weight: 15
    score: 12
    details:
      readme_exists: 4
      readme_sections: 2     # Missing "config" section
      api_docs: 4
      comments: 2            # 8% ratio

  ui_ux:
    weight: 15
    score: null              # No UI in this fixture
    details: "Fixture has no UI - points redistributed"

totals:
  raw_score: 77
  weighted_score: 77         # Adjusted for missing UI category
  grade: "B"                 # A: 90+, B: 80+, C: 70+, D: 60+, F: <60
```

---

## Interpreting Results

### Grade Thresholds

| Grade | Score | Interpretation |
|-------|-------|----------------|
| A | 90-100 | Production-ready, minimal issues |
| B | 80-89 | Good quality, minor improvements needed |
| C | 70-79 | Acceptable, several improvements needed |
| D | 60-69 | Below expectations, significant issues |
| F | <60 | Major problems, may need regeneration |

### Common Issues by Category

**Low Completeness:**
- Incomplete stories in sprint-status.yaml
- Abandoned TODOs suggesting incomplete features
- Placeholder code that was never replaced

**Low Functionality:**
- Build failures (missing dependencies, syntax errors)
- Test failures (regression, incomplete implementation)
- Behavior tests failing (API contract violation)

**Low Code Quality:**
- High cyclomatic complexity (refactoring needed)
- Linting violations (style inconsistency)
- Security vulnerabilities (input validation, injection)

**Low Documentation:**
- Missing or minimal README
- No API documentation
- Sparse inline comments

---

## Comparison Between Fixtures

When comparing fixtures (e.g., baseline vs optimized):

```bash
python -m experiments.testing_framework.common.scorecard --compare \
    webhook-relay-001 webhook-relay-002
```

Output includes delta analysis:

```yaml
comparison:
  fixtures: [webhook-relay-001, webhook-relay-002]
  deltas:
    completeness: +2      # 002 scored 2 points higher
    functionality: 0      # Same score
    code_quality: -3      # 002 scored 3 points lower
    documentation: +1
  net_change: 0
  recommendation: "webhook-relay-001 has better code quality, 002 has better completeness"
```
