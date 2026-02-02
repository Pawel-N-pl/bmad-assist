# Workflow Patches

Workflow patches customize BMAD workflow prompts for bmad-assist automation. They transform interactive workflows into automated versions by removing user prompts, embedding compile-time data, and applying deterministic text transformations.

## Problem

BMAD workflows are designed for interactive use with human operators. They include:
- User prompts and choice menus
- References to files the LLM must load at runtime
- Sprint status operations that should be managed programmatically
- Interactive flow control (goto, anchors, HALT conditions)

bmad-assist needs these workflows adapted for autonomous execution where:
- No human is present to answer prompts
- Context is pre-compiled and embedded
- Sprint status is managed by the loop handler
- Execution is linear without user intervention

## Solution

Patches define transformations applied at compile time to produce optimized workflow prompts. Each patch targets a specific workflow and specifies:
- **Transforms**: Natural language instructions for LLM-based modifications
- **Post-process rules**: Deterministic regex find/replace operations
- **Git intelligence**: Git commands run at compile time, results embedded
- **Validation**: Rules to verify patch output correctness

## Patch File Location

Patches are discovered in this order (first found wins):

1. **Project**: `.bmad-assist/patches/{workflow}.patch.yaml`
2. **CWD**: `./bmad-assist/patches/{workflow}.patch.yaml`
3. **Global**: `~/.bmad-assist/patches/{workflow}.patch.yaml`

Example structure:
```
.bmad-assist/
├── patches/
│   ├── defaults.yaml              # Shared post-process rules
│   ├── create-story.patch.yaml
│   ├── dev-story.patch.yaml
│   ├── validate-story.patch.yaml
│   ├── code-review.patch.yaml
│   └── retrospective.patch.yaml
└── cache/                         # Compiled templates (auto-generated)
    ├── create-story.tpl.xml
    └── dev-story.tpl.xml
```

## Patch File Structure

```yaml
# Metadata
patch:
  name: "create-story-optimizer"
  version: "3.0.0"
  author: "Your Name"
  description: "Optimizes create-story for bmad-assist automation"

# Version requirements
compatibility:
  bmad_version: "6.0.0-alpha.22"
  workflow: "create-story"

# Compile-time git data (optional)
git_intelligence:
  enabled: true
  embed_marker: "git-intelligence"
  no_git_message: |
    This project is not under git version control.
  commands:
    - name: "Recent Commits"
      command: "git log --oneline -5"

# LLM-based transformations
transforms:
  - "Remove step 1 (file discovery) - handled by compiler"
  - "Remove all sprint status operations"
  - "Renumber remaining steps sequentially"

# Deterministic regex replacements
post_process:
  - pattern: '<ask>.*?</ask>'
    replacement: ""
    flags: "DOTALL"

# Output validation
validation:
  must_contain:
    - "<step"
    - "<critical"
  must_not_contain:
    - "{installed_path}"
    - "<ask>"
```

## Section Reference

### `patch`

Metadata about the patch.

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique identifier for the patch |
| `version` | Yes | Semantic version string |
| `author` | No | Patch author |
| `description` | No | Human-readable description |

### `compatibility`

Version requirements for the patch.

| Field | Required | Description |
|-------|----------|-------------|
| `bmad_version` | Yes | Required bmad-assist version (exact match) |
| `workflow` | Yes | Target workflow name (e.g., `create-story`, `dev-story`) |

### `git_intelligence`

Runs git commands at compile time and embeds results in the prompt. This prevents LLMs from running expensive git archaeology at runtime.

| Field | Default | Description |
|-------|---------|-------------|
| `enabled` | `true` | Enable/disable git intelligence |
| `embed_marker` | `git-intelligence` | XML tag name for embedded results |
| `no_git_message` | (see below) | Message when project has no git |
| `commands` | `[]` | List of git commands to run |

Each command in `commands`:

| Field | Description |
|-------|-------------|
| `name` | Label for this command's output |
| `command` | Shell command to execute (supports `{{variable}}` placeholders) |

Example:
```yaml
git_intelligence:
  enabled: true
  embed_marker: "git-intelligence"
  commands:
    - name: "Recent Commits (last 5)"
      command: "git log --oneline -5"
    - name: "Related Story Commits"
      command: "git log --grep='{{epic_num}}\\.' --oneline -5 2>/dev/null || echo '(none)'"
    - name: "Recently Modified Files"
      command: "git diff --name-only HEAD~5 -- ':!docs/*.md' | head -10"
```

The output is embedded as:
```xml
<git-intelligence>
## Recent Commits (last 5)
abc1234 Fix authentication bug
def5678 Add user profile page
...

## Related Story Commits
(none)
</git-intelligence>
```

### `transforms`

Natural language instructions for an LLM to modify the workflow content. Each transform is a string describing what change to make.

```yaml
transforms:
  - "Remove step 1 (Determine target story) - story discovery is handled by compiler"
  - "Remove ALL sprint status related content: references to sprint-status.yaml, any operations that read/write sprint status"
  - "Renumber remaining steps sequentially starting from 1"
  - "Add instruction in <critical>: Git Intelligence is EMBEDDED - do NOT run git commands"
  - "Transform HALT instructions to FAILURE CONDITIONS"
```

Guidelines for writing transforms:
- Be specific about what to remove, modify, or add
- Reference step numbers or content patterns when removing
- Explain why changes are needed (helps LLM understand intent)
- Use CRITICAL prefix for instructions that must be preserved exactly

### `post_process`

Deterministic regex find/replace rules applied after LLM transforms. Use these for:
- Cleanup that LLMs often miss
- Exact pattern matching (step numbers, XML tags)
- Consistent formatting

```yaml
post_process:
  - pattern: '<ask>.*?</ask>'
    replacement: ""
    flags: "DOTALL"

  - pattern: '<step n="3"'
    replacement: '<step n="1"'
    flags: ""

  - pattern: 'sprint-status\.yaml'
    replacement: ""
    flags: "IGNORECASE"
```

| Field | Required | Description |
|-------|----------|-------------|
| `pattern` | Yes | Python regex pattern |
| `replacement` | Yes | Replacement string (can use `\1`, `\2` for groups) |
| `flags` | No | Space-separated regex flags |

Available flags:
- `IGNORECASE` or `I` - Case-insensitive matching
- `MULTILINE` or `M` - `^` and `$` match line boundaries
- `DOTALL` or `S` - `.` matches newlines
- Combine with spaces: `"MULTILINE DOTALL IGNORECASE"`

### `validation`

Rules to verify the patched output is correct.

```yaml
validation:
  must_contain:
    - "<step"                    # Substring match
    - "<critical"
    - "/[Ii]mplement/"          # Regex (enclosed in /.../)
    - "/red-green-refactor/"
  must_not_contain:
    - "{installed_path}"
    - "<ask>"
    - "sprint-status"
```

| Field | Description |
|-------|-------------|
| `must_contain` | Patterns that must exist in output |
| `must_not_contain` | Patterns that must NOT exist in output |

Pattern format:
- Plain string: Substring match (case-sensitive)
- `/pattern/`: Regex match

## Defaults File

The `defaults.yaml` file contains shared post-process rules automatically applied to all patches. Create workflow-specific defaults with `defaults-{category}.yaml`.

```yaml
# defaults.yaml - shared rules for all patches
post_process:
  # Remove template variable references
  - pattern: '^\s*<var\s+name="template"[^>]*>.*?</var>\s*$'
    replacement: ""
    flags: "MULTILINE DOTALL"

  # Remove sprint-status references
  - pattern: 'sprint-status\.yaml'
    replacement: ""
    flags: "IGNORECASE"

  # Remove steps tagged for sprint-status
  - pattern: '<step[^>]*tag="sprint-status"[^>]*>.*?</step>'
    replacement: "<!-- step removed: sprint-status managed by loop handler -->"
    flags: "DOTALL IGNORECASE"
```

Rules from defaults are applied first, then workflow-specific `post_process` rules extend them.

## Cache System

Compiled patches are cached to avoid recompilation:

```
.bmad-assist/cache/
├── create-story.tpl.xml
├── dev-story.tpl.xml
└── validate-story.tpl.xml
```

Cache invalidation occurs when:
- Patch file is modified (mtime check)
- Defaults file is modified
- bmad-assist version changes

To manually clear the cache:
```bash
rm -rf .bmad-assist/cache/
```

## CLI Commands

```bash
# Compile a specific patch
bmad-assist patch compile create-story

# Compile all patches in project
bmad-assist patch compile-all

# List available patches
bmad-assist patch list

# Show patch details
bmad-assist patch show create-story

# Debug compilation (verbose output)
bmad-assist compile -w create-story -e 1 -s 1 --debug
```

## Example: Minimal Patch

A minimal patch that removes user interaction:

```yaml
patch:
  name: "minimal-automation"
  version: "1.0.0"

compatibility:
  bmad_version: "6.0.0-alpha.22"
  workflow: "create-story"

transforms:
  - "Remove all <ask> elements - no interactive user"
  - "Remove step 1 (file discovery) - handled by compiler"

post_process:
  - pattern: '<ask>.*?</ask>'
    replacement: ""
    flags: "DOTALL"

validation:
  must_not_contain:
    - "<ask>"
```

## Example: Full Patch with Git Intelligence

```yaml
patch:
  name: "dev-story-automation"
  version: "2.0.0"
  author: "BMad"
  description: "Full automation patch for dev-story workflow"

compatibility:
  bmad_version: "6.0.0-alpha.22"
  workflow: "dev-story"

git_intelligence:
  enabled: true
  embed_marker: "git-intelligence"
  no_git_message: |
    This project is not under git version control.
    Do NOT attempt to run git commands - they will fail.
  commands:
    - name: "Recent Implementation Commits"
      command: "git log --oneline -10"
    - name: "Current Branch Status"
      command: "git status --short"
    - name: "Uncommitted Changes"
      command: "git diff --stat -- ':!docs/*.md'"

transforms:
  - "Add CRITICAL instruction: 'SCOPE: You are the MASTER agent with READ+WRITE permission'"
  - "CRITICAL: Preserve the EXACT phrase 'red-green-refactor' wherever it appears"
  - "Remove step 1 (file discovery) - handled by compiler"
  - "Remove step 4 (sprint-status) - managed by loop handler"
  - "Remove ALL <goto> and <anchor> elements - workflow executes linearly"
  - "Transform HALT instructions to FAILURE CONDITIONS"
  - "Renumber remaining steps sequentially"

post_process:
  # Remove user interaction
  - pattern: '\s*<ask>.*?</ask>\s*'
    replacement: ""
    flags: "DOTALL"

  # Remove goto/anchor
  - pattern: '<anchor[^/]*/?>\s*'
    replacement: ""
    flags: ""
  - pattern: '<goto[^>]*>.*?</goto>'
    replacement: ""
    flags: "DOTALL"

  # Step removal by number
  - pattern: '<step n="1"[^>]*>.*?</step>'
    replacement: "<!-- step 1 removed: file discovery -->"
    flags: "DOTALL"
  - pattern: '<step n="4"[^>]*>.*?</step>'
    replacement: "<!-- step 4 removed: sprint-status -->"
    flags: "DOTALL"

  # Renumber remaining steps
  - pattern: '<step n="2"'
    replacement: '<step n="1"'
    flags: ""
  - pattern: '<step n="3"'
    replacement: '<step n="2"'
    flags: ""

validation:
  must_contain:
    - "<step"
    - "<critical"
    - "/red-green-refactor/"
  must_not_contain:
    - "{installed_path}"
    - "<ask>"
    - "<anchor"
    - "<goto"
```

## Troubleshooting

### Patch not being applied

1. Verify patch file location matches discovery order
2. Check `compatibility.workflow` matches the target workflow name
3. Clear cache and recompile: `rm -rf .bmad-assist/cache/`

### Validation failures

```
ValidationError: must_contain failed: /red-green-refactor/
```

The patched output is missing required content. Either:
- Transform instruction didn't preserve the content
- Post-process rule accidentally removed it

Debug by examining the compiled template in `.bmad-assist/cache/`.

### Post-process regex not matching

1. Test regex separately: `python -c "import re; print(re.search(r'pattern', text))"`
2. Check flags - `DOTALL` needed for patterns spanning lines
3. Escape special characters: `\.` for literal dot, `\{` for literal brace

### Cache conflicts after updates

```bash
# Clear all cached templates
rm -rf .bmad-assist/cache/

# Recompile
bmad-assist patch compile-all
```

### Transform not applied by LLM

Transforms are natural language instructions - LLMs may interpret them differently. If a transform isn't working:
1. Make the instruction more specific
2. Add a post-process rule as backup
3. Use validation rules to catch failures

## See Also

- [Configuration Reference](configuration.md) - Main configuration options
- [Strategic Context](strategic-context.md) - Document injection settings
- [Troubleshooting](troubleshooting.md) - Common issues
