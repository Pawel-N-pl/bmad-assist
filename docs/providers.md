# LLM Providers Reference

bmad-assist supports multiple LLM providers through CLI tool adapters. This document covers installation, configuration, and usage for each provider.

## Provider Architecture

All providers implement a common interface:
- **invoke()** - Execute prompt and return result
- **parse_output()** - Extract response text from CLI output
- **supports_model()** - Check model compatibility

Providers run CLI tools via subprocess, capturing stdout/stderr for processing. The `opencode-sdk` provider is an exception - it uses the official Python SDK with a persistent HTTP server instead of per-call subprocesses.

---

## claude-subprocess (Recommended)

**CLI Tool:** [Claude Code](https://github.com/anthropics/claude-code) (`claude`)

The primary provider for bmad-assist. Uses Claude Code CLI which provides file access, tool use, and agentic capabilities.

> **Note:** There is also a `claude-sdk` provider that uses the Anthropic Agent SDK directly. It is the internal primary but is not recommended for external use as it requires the `claude-agent-sdk` package. Use `claude-subprocess` for the simplest setup.

### Installation

```bash
npm install -g @anthropics/claude-code
```

### Configuration

```yaml
providers:
  master:
    provider: claude-subprocess
    model: opus                      # opus, sonnet, or haiku

  # With custom settings file (for alternate API endpoints)
  helper:
    provider: claude-subprocess
    model: sonnet
    model_name: glm-4.7              # Display name in logs/benchmarks
    settings: ~/.claude/glm.json    # Custom Claude settings
```

### Models

| Model | Description | Best For |
|-------|-------------|----------|
| `opus` | Most capable, slower | Complex reasoning, implementation |
| `sonnet` | Balanced | General use, code review |
| `haiku` | Fastest, cheapest | Synthesis, simple tasks |

### Custom Settings File

To use alternate API providers (like GLM-4.7 via compatible endpoint), create a settings JSON:

```json
{
  "apiProvider": "openai-compatible",
  "openaiBaseUrl": "https://your-api-endpoint.com/v1",
  "openaiApiKey": "your-api-key"
}
```

Then reference it in config:

```yaml
providers:
  master:
    provider: claude-subprocess
    model: sonnet
    model_name: glm-4.7           # Shows "glm-4.7" in logs instead of "sonnet"
    settings: ~/.claude/glm.json
```

### Command Generated

```bash
claude --print --output-format stream-json --model <model> [--settings <path>]
```

---

## gemini

**CLI Tool:** [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`)

Google's Gemini models via official CLI.

### Installation

```bash
npm install -g @anthropics/gemini-cli
# or
pip install gemini-cli
```

### Configuration

```yaml
providers:
  multi:
    - provider: gemini
      model: gemini-2.5-flash
    - provider: gemini
      model: gemini-3-pro-preview
```

### Models

| Model | Description |
|-------|-------------|
| `gemini-2.5-flash` | Fast, cost-effective |
| `gemini-2.5-flash-lite` | Lighter version |
| `gemini-2.5-pro` | More capable |
| `gemini-3-pro-preview` | Latest preview |
| `gemini-3-flash-preview` | Latest fast preview |

### Command Generated

```bash
gemini -m <model> --output-format stream-json
```

---

## kimi

**CLI Tool:** [Kimi CLI](https://github.com/MoonshotAI/kimi-cli) (`kimi`)

MoonshotAI's Kimi Code assistant with 256K context window.

### Installation

```bash
npm install -g @anthropics/kimi-cli
# or via cargo
cargo install kimi-cli
```

### Setup (Required)

Kimi uses OAuth authentication. Run login before first use:

```bash
kimi login
```

This opens a browser for authentication. Tokens are stored in kimi's config directory.

### Configuration

```yaml
providers:
  multi:
    - provider: kimi
      model: kimi-code/kimi-for-coding  # Full model name required
      thinking: true                     # Enable thinking mode (extended reasoning)
```

### Models

| Model | Description |
|-------|-------------|
| `kimi-code/kimi-for-coding` | Default coding-optimized model (256K context) |

> **Important:** Use the full model name `kimi-code/kimi-for-coding`, not just `kimi-for-coding`.

### Thinking Mode

When `thinking: true` is set, Kimi outputs reasoning in separate blocks before the response. The provider extracts only the final text response.

### Command Generated

```bash
kimi --print --output-format stream-json -m <model> [--thinking] [--work-dir <path>]
```

### Troubleshooting

**"LLM not set" error:**
- Run `kimi login` to authenticate
- Verify login completed successfully in browser

**Empty responses:**
- Verify OAuth token is valid (re-run `kimi login`)
- Check model name is exactly `kimi-for-coding`

---

## codex

**CLI Tool:** OpenAI Codex CLI (`codex`)

OpenAI's code-specialized models.

### Configuration

```yaml
providers:
  multi:
    - provider: codex
      model: o3-mini
```

### Models

| Model | Description |
|-------|-------------|
| `o3-mini` | Fast reasoning model |
| `gpt-5.1-codex-max` | Default, most capable |

### Command Generated

```bash
codex --print --model <model> --output-format stream-json
```

---

## opencode

**CLI Tool:** [OpenCode](https://github.com/opencode-ai/opencode) (`opencode`)

Multi-backend CLI supporting various providers.

### Configuration

```yaml
providers:
  multi:
    - provider: opencode
      model: opencode/claude-sonnet-4
    - provider: opencode
      model: zai-coding-plan/glm-4.7
    - provider: opencode
      model: xai/grok-4
```

### Model Format

Models use `provider/model` format:
- `opencode/claude-sonnet-4` - Claude via OpenCode
- `opencode/claude-opus-4-5` - Opus via OpenCode
- `zai-coding-plan/glm-4.7` - GLM via Z.ai
- `xai/grok-4` - Grok via xAI
- `opencode/gemini-3-flash` - Gemini via OpenCode

### Command Generated

```bash
opencode chat --print --model <model>
```

---

## opencode-sdk

**SDK:** [opencode-ai](https://pypi.org/project/opencode-ai/) Python SDK (`opencode-ai`)

SDK-based provider that replaces per-call subprocess overhead with a persistent `opencode serve` HTTP server. Provides live SSE event streaming for real-time progress visibility, automatic server lifecycle management, and cancel support.

### How It Works

1. On first invocation, the provider auto-starts an `opencode serve` process on a random port with a random password
2. All subsequent invocations reuse the same server (one-shot sessions: create → chat → delete)
3. Live SSE events stream text deltas, tool calls, and cost/token usage in real time
4. If the server fails to start, the provider falls back to the subprocess `opencode` provider with a 2-minute cooldown before retrying the SDK

### Installation

The `opencode-ai` SDK is bundled as a dependency of bmad-assist. You also need the `opencode` CLI installed:

```bash
# OpenCode CLI (required for the managed server)
go install github.com/opencode-ai/opencode@latest
# or via npm/brew - see OpenCode docs
```

### Configuration

```yaml
providers:
  master:
    provider: opencode-sdk
    model: opencode/claude-sonnet-4

  multi:
    - provider: opencode-sdk
      model: zai-coding-plan/glm-4.7
    - provider: opencode-sdk
      model: xai/grok-4
```

### Model Format

Same as `opencode` - models use `provider/model` format:
- `opencode/claude-sonnet-4` - Claude via OpenCode
- `opencode/claude-opus-4-5` - Opus via OpenCode
- `zai-coding-plan/glm-4.7` - GLM via Z.ai
- `xai/grok-4` - Grok via xAI

### Features

| Feature | Description |
|---------|-------------|
| **Persistent server** | Single `opencode serve` process shared across all invocations |
| **SSE streaming** | Real-time text deltas, tool call progress, cost/token tracking |
| **Auto lifecycle** | Server starts on demand, cleans up on process exit |
| **Subprocess fallback** | Automatic fallback to `opencode` CLI if server fails |
| **Cancel support** | In-flight requests can be aborted via `session.abort()` |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENCODE_SERVER_PORT` | Override default server port (default: auto-selected) |
| `OPENCODE_SERVER_PASSWORD` | Override auto-generated server password |

### When to Use opencode-sdk vs opencode

| | `opencode` | `opencode-sdk` |
|---|---|---|
| **Startup** | New subprocess per call | Persistent server (faster) |
| **Progress** | No live output | SSE streaming with text/tool/cost events |
| **Overhead** | Process spawn + teardown | HTTP request to running server |
| **Reliability** | Simple, always works | Falls back to subprocess on failure |
| **Best for** | Single-use, simple setups | Multi-LLM orchestration, long sessions |

Use `opencode-sdk` when you want lower latency and live streaming. Use `opencode` for simplicity or if the SDK server has issues with your setup.

---

## amp

**CLI Tool:** [Amp](https://sourcegraph.com/amp) (`amp`)

Sourcegraph's agentic coding assistant.

### Configuration

```yaml
providers:
  multi:
    - provider: amp
      model: smart                   # Only "smart" mode works with bmad-assist
```

### Modes

| Mode | Model | Works with bmad-assist |
|------|-------|------------------------|
| `smart` | Claude Opus 4.5 | Yes |
| `rush` | Faster model | No (lacks tool use) |
| `free` | Free tier | No (lacks tool use) |

> **Warning:** Only `smart` mode has the tool use capabilities required for validation/review tasks.

### Command Generated

```bash
amp --print --mode <mode>
```

---

## copilot

**CLI Tool:** GitHub Copilot CLI (`copilot`)

GitHub Copilot's CLI interface.

### Configuration

```yaml
providers:
  multi:
    - provider: copilot
      model: claude-haiku-4.5
```

### Models

Depends on your Copilot subscription. Common options:
- `claude-haiku-4.5`
- `gpt-4o`

### Command Generated

```bash
copilot -p "<prompt>" --allow-all-tools --yolo --model <model>
```

---

## cursor-agent

**CLI Tool:** Cursor Agent (`cursor-agent`)

Cursor IDE's agent mode via CLI.

### Configuration

```yaml
providers:
  multi:
    - provider: cursor-agent
      model: auto
```

### Models

| Model | Description |
|-------|-------------|
| `auto` | Automatic model selection |
| `composer-1` | Composer model |

### Command Generated

```bash
cursor-agent --print --model <model> --force "<prompt>"
```

---

## Provider Options Reference

All providers support these configuration options:

| Option | Required | Description |
|--------|----------|-------------|
| `provider` | Yes | Provider identifier (e.g., `claude-subprocess`, `opencode-sdk`) |
| `model` | Yes | Model name passed to CLI |
| `model_name` | No | Display name in logs/benchmarks (overrides model) |
| `settings` | No | Path to settings file (claude-subprocess only) |
| `thinking` | No | Enable thinking mode (kimi only) |

---

## Adding New Providers

To add support for a new CLI tool:

1. Create `src/bmad_assist/providers/<name>.py`
2. Implement `BaseProvider` interface
3. Register in `src/bmad_assist/providers/registry.py`

See existing providers for implementation patterns.
