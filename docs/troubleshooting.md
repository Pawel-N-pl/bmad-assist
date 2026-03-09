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

## Claude SDK Init Timeout

**Symptoms:**
- `TimeoutError: SDK initialization exceeded timeout`
- Provider fails on first invocation but works after retry

**Cause:** Claude SDK initialization includes loading MCP servers and CLAUDE.md, which can exceed the init timeout on complex projects.

**Solution:** The init timeout is 30s by default (increased from 5s in v0.4.32). If your project has many MCP servers or a very large CLAUDE.md, the SDK will automatically fall back to subprocess mode on timeout. No configuration needed.

---

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

**Note:** Since v0.4.32, the evidence score parser accepts severity aliases (HIGH→CRITICAL, MEDIUM→IMPORTANT, LOW→MINOR) and section header fallback formats, so most LLM output variations are now handled automatically.

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

## Provider Quota Exhaustion

**Symptoms:**
- `QuotaExhaustedError` or rate limit errors from LLM provider
- Long runs failing mid-epic due to API limits

**Solution:** Configure provider fallback chains to automatically switch to an alternative provider:

```yaml
providers:
  master:
    provider: claude-subprocess
    model: opus
    fallbacks:
      - provider: gemini
        model: gemini-2.5-pro
```

See [Providers Reference](providers.md#provider-fallback-chains) for details.

---

## Synthesis Extraction Failures

**Symptoms:**
- Loop exits with `GUARDIAN_HALT` after a synthesis phase
- Logs show `extraction_quality=failed` or `extraction_quality=degraded`
- `state.yaml` shows `last_synthesis_failure_class: halt`

### Degraded extraction (extraction_quality: degraded)

The LLM omitted the HTML-comment resolution markers but the runner recovered via section-header or semantic keyword fallback. The loop continues normally. If this happens frequently, the synthesis workflow prompt may need adjustment.

### Failed extraction with ToolCallGuard termination (failure_class: retryable)

**Cause:** ToolCallGuard interrupted the synthesis LLM call before it could produce structured output.

**Runner behavior:** Retries the synthesis phase automatically, up to `max_synthesis_retries` (default 1). After exhausting retries, exits GUARDIAN_HALT.

**Solutions:**
1. Increase `max_synthesis_retries` in `bmad-assist.yaml` (range 0–3)
2. Check ToolCallGuard thresholds — a very large story file may legitimately require more tool calls
3. Resume the run: `bmad-assist run --project ./my-project` — the runner will retry the failed synthesis phase

### Failed extraction with contradictory evidence (failure_class: halt)

**Cause:** The LLM output could not be parsed AND there was insufficient pre-synthesis evidence to make a reliable rework/resolve decision, OR the LLM claimed resolved with zero reported fixes but the evidence score showed pre-existing critical issues.

**Solutions:**
1. Check `state.yaml` for `last_synthesis_resolution`, `last_synthesis_extraction_quality`, and `last_synthesis_failure_class`
2. Review the synthesis workflow output log for the affected story
3. Manually inspect the story file for the LLM's actual changes
4. Resume the run after confirming the story state is correct — the loop will re-run synthesis

### Inspecting synthesis state after halt

```bash
# Check synthesis fields in state.yaml
grep "last_synthesis" .bmad-assist/state.yaml

# Fields persisted after each synthesis:
#   last_synthesis_resolution:         resolved | rework | halt
#   last_synthesis_extraction_quality: strict | degraded | failed
#   last_synthesis_failure_class:      retryable | halt | (null for clean runs)
#   synthesis_retry_count:             number of retries attempted this story
```

## Debug Mode

For detailed troubleshooting:

```bash
# Enable verbose logging
bmad-assist run -v --project ./my-project

# Debug specific workflow compilation
bmad-assist compile -w dev-story -e 1 -s 1 --debug
```
