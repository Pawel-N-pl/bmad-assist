# Troubleshooting

Common issues and their solutions.

## "Workflow not found" Error

**Symptoms:**
- `CompilerError: Workflow 'dev-story' not found!`
- `Bundled workflow 'code-review' not found!`

**Solution:**
```bash
# Reinstall bmad-assist to ensure workflows are bundled
pip install -e .

# Verify workflows are available
bmad-assist init  # Shows workflow validation
```

## "Handler config not found" Error

**Symptoms:**
- `ConfigError: Handler config not found: ~/.bmad-assist/handlers/...`

**Cause:** Handler YAML files are deprecated. The compiler handles prompts automatically.

**Solution:**
1. Ensure bmad-assist is properly installed: `pip install -e .`
2. Check workflow discovery: `bmad-assist compile -w dev-story --debug`
3. For custom workflows, place them in `.bmad-assist/workflows/{workflow-name}/`

## Custom Workflow Overrides

To customize a workflow for your project:

1. Create `.bmad-assist/workflows/{workflow-name}/` directory
2. Copy the workflow files (`workflow.yaml`, `instructions.md`, etc.)
3. Modify as needed

Project overrides take priority over bundled workflows.

## Provider Connection Issues

**Symptoms:**
- `ProviderError: Failed to invoke claude-subprocess`
- Timeouts during LLM invocation

**Solutions:**

1. **Verify CLI tool is installed:**
   ```bash
   claude --version
   gemini --version
   codex --version
   ```

2. **Check authentication:**
   ```bash
   claude "test"  # Should respond without auth errors
   ```

3. **Increase timeout:**
   ```yaml
   timeouts:
     dev_story: 7200  # 2 hours for large implementations
   ```

## Missing Documentation Error

**Symptoms:**
- `FileNotFoundError: docs/prd.md not found`
- `No epic files found`

**Solution:**

Ensure your project has the required documentation structure:
```
docs/
├── prd.md              # Product Requirements
├── architecture.md     # Or architecture/ directory
├── project-context.md  # AI implementation rules
└── epics/              # Epic definitions
    ├── index.md
    └── epic-1-*.md
```

## Cache/Patch Conflicts

**Symptoms:**
- Unexpected workflow behavior after updates
- Stale prompts being used

**Solution:**
```bash
# Clear patch cache
rm -rf .bmad-assist/cache/

# Recompile patches
bmad-assist patch compile-all

# Or reset to bundled workflows
bmad-assist init --reset-workflows
```

See [Workflow Patches](workflow-patches.md) for detailed patch configuration.

## Sprint Status Sync Issues

**Symptoms:**
- Story status not updating
- Duplicate entries in sprint-status.yaml

**Solution:**
```bash
# Validate sprint status
bmad-assist sprint validate

# Repair and sync
bmad-assist sprint sync
```

## Multi-LLM Validation Failures

**Symptoms:**
- Some validators fail while others succeed
- Inconsistent validation results

**Possible causes:**
1. **Rate limiting** - Reduce parallel validators or add delays
2. **Model availability** - Check if model is accessible
3. **Timeout** - Increase validation timeout

**Solution:**
```yaml
# Use fewer multi providers
multi:
  - provider: gemini
    model: gemini-2.5-flash
  # Comment out others to reduce load
```

## Evidence Score Extraction Errors

**Symptoms:**
- `Failed to extract evidence score`
- Missing metrics in benchmark reports

**Cause:** Validator output doesn't match expected format.

**Solution:**
1. Check validator output contains Evidence Score section
2. Verify report markers are present:
   ```
   <!-- VALIDATION_REPORT_START -->
   ...
   <!-- VALIDATION_REPORT_END -->
   ```

## Dashboard Not Loading

**Symptoms:**
- Empty dashboard
- SSE connection errors

**Solution:**
```bash
# Check if server is running
bmad-assist serve --port 8080

# Verify state file exists
ls .bmad-assist/state.yaml
```

## Permission Errors with External Paths

**Symptoms:**
- `PermissionError: Cannot write to /external/path`
- `FileNotFoundError: External path does not exist`

**Solution:**
1. Ensure external paths exist and are writable
2. Check path configuration in `bmad-assist.yaml`:
   ```yaml
   paths:
     project_knowledge: /path/that/exists
     output_folder: /writable/path
   ```

## Debug Mode

For detailed troubleshooting:

```bash
# Enable verbose logging
bmad-assist run -v --project ./my-project

# Debug specific workflow compilation
bmad-assist compile -w dev-story -e 1 -s 1 --debug
```
