# Fixture Testing Framework

A behavioral testing framework for evaluating AI-generated projects (fixtures) produced by bmad-assist experiments.

## Quick Start

### 1. Run Tests for a Fixture

```bash
# Activate virtual environment
source .venv/bin/activate

# Run all tests for webhook-relay-001
pytest experiments/fixture-tests/webhook-relay-001/ -v

# Run only API tests
pytest experiments/fixture-tests/webhook-relay-001/test_api_behavior.py -v

# Run with coverage
pytest experiments/fixture-tests/webhook-relay-001/ --cov=experiments/fixtures/webhook-relay-001
```

### 2. Generate a Quality Scorecard

```bash
# Generate scorecard for a fixture
python -m experiments.testing_framework.common.scorecard webhook-relay-001

# Output saved to: experiments/analysis/scorecards/webhook-relay-001.yaml
```

### 3. Create Tests for a New Fixture

1. **Copy templates** to `experiments/fixture-tests/<fixture-name>/`:
   ```bash
   cp experiments/testing-framework/templates/requirements_map.yaml \
      experiments/fixture-tests/my-fixture/
   cp experiments/testing-framework/templates/test_api_template.py \
      experiments/fixture-tests/my-fixture/test_api_behavior.py
   ```

2. **Add fixture metadata**:
   ```bash
   cp experiments/testing-framework/templates/FIXTURE_META.yaml \
      experiments/fixtures/my-fixture/
   ```

3. **Follow the process checklist**: See `docs/process-checklist.md`

## Framework Structure

```
experiments/
├── testing-framework/
│   ├── README.md                 # This file
│   ├── docs/
│   │   ├── methodology.md        # Behavioral testing methodology
│   │   ├── scorecard-methodology.md  # Quality evaluation guide
│   │   └── process-checklist.md  # Step-by-step checklist
│   ├── templates/                # Copy-paste ready templates
│   │   ├── FIXTURE_META.yaml     # Fixture metadata
│   │   ├── requirements_map.yaml # PRD → test mapping
│   │   ├── contract.yaml         # API contract definition
│   │   ├── test_api_template.py  # API test template
│   │   ├── test_ui_template.py   # UI journey test template
│   │   └── scorecard_template.yaml
│   └── common/                   # Shared test infrastructure
│       ├── conftest.py           # Pytest fixtures
│       ├── strategies.py         # App discovery & startup
│       ├── assertions.py         # Reusable assertions
│       └── scorecard.py          # Automated scoring
│
├── fixtures/                     # Immutable after completion
│   ├── webhook-relay-001/        # Baseline run
│   └── webhook-relay-002/        # Strategic context run
│
├── fixture-tests/                # Per-fixture behavioral tests
│   └── webhook-relay-001/
│       ├── requirements_map.yaml
│       ├── contract.yaml
│       ├── test_api_behavior.py
│       └── test_user_journeys.py
│
└── analysis/
    ├── reports/                  # Comparison reports
    └── scorecards/               # Generated scorecards
```

## Key Concepts

### Behavioral Testing

Tests verify **what the application does**, not **how it's implemented**:
- API tests check endpoints return correct responses
- UI journey tests simulate user workflows
- Tests are implementation-agnostic (work across Go, Python, Node)

### Quality Scorecard

Automated evaluation across 5 categories:
1. **Completeness** (25%) - Stories completed, no TODOs/FIXMEs
2. **Functionality** (25%) - Tests pass, builds succeed
3. **Code Quality** (20%) - Linting, complexity metrics
4. **Documentation** (15%) - README, API docs, inline comments
5. **UI/UX** (15%) - Manual review (if applicable)

### Fixture Immutability

Once a fixture is tagged/archived:
- Code is frozen (checksums recorded)
- Tests can be added/modified independently
- Enables fair comparison across bmad-assist versions

## Documentation

- [Behavioral Testing Methodology](docs/methodology.md)
- [Scorecard Methodology](docs/scorecard-methodology.md)
- [Process Checklist](docs/process-checklist.md)

## Requirements

- Python 3.11+
- pytest 7.0+
- httpx (for API testing)
- playwright (for UI testing, optional)
- Go 1.21+ (for webhook-relay fixtures)
