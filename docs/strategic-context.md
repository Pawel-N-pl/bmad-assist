# Strategic Context Optimization

Strategic Context Optimization controls which planning documents (PRD, Architecture, UX, project-context) are included in compiled workflow prompts.

## Problem

Workflow compilers previously loaded all strategic documents unconditionally. Benchmark analysis of 311 files revealed significant waste:

| Workflow | PRD Citation Rate | Observation |
|----------|-------------------|-------------|
| code-review | 0% (105 files) | PRD never referenced |
| validate-story | 26% (35/134 files) | PRD rarely needed |

Loading unused documents wastes context tokens that could be used for source code or story details.

## Solution

The `strategic_context` configuration section controls document loading per workflow:

```yaml
compiler:
  strategic_context:
    budget: 8000                 # Total token cap for strategic docs (0 = disabled)

    defaults:
      include: [project-context] # Doc types to include
      main_only: true            # For sharded docs: load only index.md

    # Per-workflow overrides
    create_story:
      include: [project-context, prd, architecture, ux]
    validate_story:
      include: [project-context, architecture]
    validate_story_synthesis:
      include: [project-context]
    # dev_story, code_review, code_review_synthesis use defaults
```

## Configuration Options

### `budget`
Total token cap for all strategic documents combined. Set to `0` to disable strategic context loading entirely.

### `defaults`
Default settings applied to all workflows unless overridden:

| Option | Type | Description |
|--------|------|-------------|
| `include` | list | Doc types to load: `project-context`, `prd`, `architecture`, `ux` |
| `main_only` | bool | If `true`, load only index.md for sharded documents |

### Per-Workflow Overrides

Each workflow can override defaults by specifying its own `include` and/or `main_only`:

```yaml
create_story:
  include: [project-context, prd, architecture, ux]  # Full context for story creation
  # main_only not specified → inherits true from defaults
```

If a workflow section only specifies `include`, it inherits `main_only` from defaults.

## Default Workflow Settings

Based on benchmark analysis, these defaults optimize token usage:

| Workflow | Documents | Rationale |
|----------|-----------|-----------|
| `create_story` | project-context, prd, architecture, ux | Needs full context to create stories |
| `validate_story` | project-context, architecture | Story alignment checks |
| `validate_story_synthesis` | project-context | Aggregates validator outputs |
| `dev_story` | project-context | Implementation focus |
| `code_review` | project-context | Code quality focus |
| `code_review_synthesis` | project-context | Aggregates reviewer outputs |

## Sharded Documents

Some documents (architecture, PRD) can be sharded into multiple files:

```
docs/
└── architecture/
    ├── index.md          # Main overview
    ├── api-design.md     # API decisions
    ├── data-model.md     # Database schema
    └── security.md       # Security patterns
```

The `main_only` flag controls loading behavior:
- `true` (default): Load only `index.md` (saves tokens)
- `false`: Load all shards (full context)

## Token Budget

The `budget` setting caps total strategic context size. If documents exceed the budget:
1. Documents are loaded in order specified by `include`
2. Loading stops when budget would be exceeded
3. A warning is logged if budget is tight

Recommended budgets:
- Small projects: 4000-6000 tokens
- Medium projects: 8000-12000 tokens
- Large projects with detailed architecture: 15000-20000 tokens

## Disabling Strategic Context

To disable strategic context for a specific workflow:

```yaml
code_review:
  include: []  # Empty list = no strategic docs
```

To disable globally:
```yaml
compiler:
  strategic_context:
    budget: 0  # Disables strategic context loading
```

## Fallback Behavior

When configuration is not available (e.g., standalone tests), hardcoded defaults are used matching the optimized settings above.

## See Also

- [Configuration Reference](configuration.md) - Main configuration options
- [Workflow Patches](workflow-patches.md) - Customize workflow prompts
