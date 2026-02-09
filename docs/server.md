# bmad-assist Server Documentation

> **Verified against:** Current `main` branch implementation in `src/bmad_assist/dashboard/`

This document provides a detailed analysis of the `bmad-assist` server functionality, which powers the web-based dashboard and orchestrates the development loop.

---

## 1. Overview

The `bmad-assist` server is a local web server that provides a real-time user interface for the BMAD development methodology. It allows users to:
- Visualize the current sprint status and story progress.
- Control the development loop (Start, Pause, Resume, Stop).
- View live logs and events via Server-Sent Events (SSE).
- Manage configuration (Global and Project-level).
- Run and monitor experiments.
- View validation reports and prompts.

The server is launched via the CLI command:
```bash
bmad-assist serve [--project PATH] [--port PORT]
```

---

## 2. Architecture

The server is built using **Python** with the following core technologies:
- **[Starlette](https://www.starlette.io/)**: Lightweight ASGI web framework.
- **[Uvicorn](https://www.uvicorn.org/)**: ASGI web server implementation.
- **[asyncio](https://docs.python.org/3/library/asyncio.html)**: Concurrent execution of server and subprocess.

### 2.1 Process Model

```
┌─────────────────────────────────────────────────────────────┐
│                     Main Process                            │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐  │
│  │  Starlette  │  │ SSEBroadcaster│  │  Subprocess Mgr   │  │
│  │  (HTTP/API) │  │  (Push logs) │  │  (spawn, monitor) │  │
│  └─────────────┘  └──────────────┘  └────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ stdout (DASHBOARD_EVENT markers)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Subprocess                              │
│                  bmad-assist run --no-interactive           │
│             (LLM orchestration, code generation)            │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. State Machine

The development loop follows this state machine:

```
                    ┌─────────────────────────────────────┐
                    │                                     │
                    ▼                                     │
    ┌───────┐   POST /start   ┌──────────┐   success   ┌─────────┐
    │ IDLE  │ ───────────────►│ STARTING │────────────►│ RUNNING │
    └───────┘                 └──────────┘             └─────────┘
        ▲                          │                       │ │
        │                          │ failure               │ │
        │                          ▼                       │ │
        │                     ┌─────────┐                  │ │
        │◄────────────────────│  ERROR  │◄─────────────────┘ │
        │     POST /stop      └─────────┘   crash/error      │
        │                                                    │
        │                                          POST /pause
        │                                                    │
        │  POST /stop    ┌──────────────────┐                │
        │◄───────────────│ PAUSE_REQUESTED  │◄───────────────┘
        │                └──────────────────┘
        │                          │
        │                          │ step completes
        │                          ▼
        │                     ┌──────────┐
        │◄────────────────────│  PAUSED  │
        │     POST /stop      └──────────┘
        │                          │
        │                          │ POST /resume
        │                          ▼
        └──────────────────────── RUNNING
```

### State Transition Rules

| Current State      | Action          | Next State        | Notes                                    |
| :----------------- | :-------------- | :---------------- | :--------------------------------------- |
| `IDLE`             | `POST /start`   | `STARTING`        | Subprocess spawned                       |
| `STARTING`         | (success)       | `RUNNING`         | Subprocess confirmed alive               |
| `STARTING`         | (failure)       | `ERROR`           | Subprocess failed to start               |
| `RUNNING`          | `POST /pause`   | `PAUSE_REQUESTED` | Flag written, waits for step completion  |
| `RUNNING`          | `POST /stop`    | `IDLE`            | SIGTERM sent, then SIGKILL after timeout |
| `RUNNING`          | (crash)         | `ERROR`           | Subprocess exited unexpectedly           |
| `PAUSE_REQUESTED`  | (step done)     | `PAUSED`          | Subprocess paused at safe point          |
| `PAUSED`           | `POST /resume`  | `RUNNING`         | Flag removed, subprocess continues       |
| `PAUSED`           | `POST /stop`    | `IDLE`            | Subprocess terminated                    |
| `ERROR`            | `POST /stop`    | `IDLE`            | Clears error state                       |

**Idempotency:** Calling `/start` while already `RUNNING` returns `409 Conflict`.

---

## 4. Filesystem Contract

| File                           | Producer  | Consumer    | Lifecycle                     |
| :----------------------------- | :-------- | :---------- | :---------------------------- |
| `sprint-status.yaml`           | CLI       | Server, UI  | Persistent, auto-generated    |
| `state.yaml`                   | CLI       | Server      | Persistent                    |
| `.bmad-assist/pause.flag`      | Server    | CLI         | Ephemeral, deleted on resume  |
| `.bmad-assist/stop.flag`       | Server    | CLI         | Ephemeral, deleted on stop    |
| `.bmad-assist/lock.flag`       | CLI       | Server      | Ephemeral, indicates running  |
| Validation reports (`_bmad-output/`) | CLI | Server, UI  | Persistent, read-only by server |

**Startup cleanup:** Server removes stale flag files (`pause.flag`, `stop.flag`) on startup.

---

## 5. Event Types and Schemas

### 5.1 SSE Message Format

All SSE messages follow this structure:
```json
{
  "event": "<event_type>",
  "data": { ... },
  "ts": "2024-01-15T10:30:00Z"
}
```

### 5.2 Event Type Reference

| Event Type        | Required Fields                      | Description                         |
| :---------------- | :----------------------------------- | :---------------------------------- |
| `output`          | `line`, `level` (info/warn/error)    | Raw log line from subprocess        |
| `phase_changed`   | `from`, `to`, `story_id`             | Workflow phase transition           |
| `story_started`   | `epic_id`, `story_id`, `title`       | New story execution began           |
| `story_completed` | `epic_id`, `story_id`, `result`      | Story finished (success/fail)       |
| `loop_status`     | `status`, `reason`                   | Loop state change (running/paused)  |
| `error`           | `message`, `code`                    | Error occurred                      |

### 5.3 Example: stdout marker to SSE event

**Subprocess stdout:**
```
[INFO] Starting validation...
DASHBOARD_EVENT:{"type":"phase_changed","from":"dev_story","to":"atdd_validation","story_id":"5-2"}
```

**SSE broadcast:**
```json
{"event":"output","data":{"line":"[INFO] Starting validation...","level":"info"},"ts":"..."}
{"event":"phase_changed","data":{"from":"dev_story","to":"atdd_validation","story_id":"5-2"},"ts":"..."}
```

---

## 6. API Reference

### 6.1 Loop Control (`/api/loop`)

| Endpoint        | Method | Description                              | Response Codes       |
| :-------------- | :----- | :--------------------------------------- | :------------------- |
| `/start`        | POST   | Start the development loop               | 200, 409 (already running) |
| `/pause`        | POST   | Request pause after current step         | 200, 409 (not running) |
| `/resume`       | POST   | Resume paused loop                       | 200, 409 (not paused) |
| `/stop`         | POST   | Immediately terminate subprocess         | 200                  |
| `/status`       | GET    | Return current state                     | 200                  |

### 6.2 Status & Content

| Endpoint             | Method | Description                              |
| :------------------- | :----- | :--------------------------------------- |
| `/api/status`        | GET    | Sprint status from `sprint-status.yaml`  |
| `/api/stories`       | GET    | Hierarchical list of epics/stories       |
| `/api/state`         | GET    | Execution position from `state.yaml`     |
| `/api/epics/{id}`    | GET    | Detailed epic content                    |
| `/api/report/content`| GET    | Secure file reader (path traversal protected) |

### 6.3 Configuration (`/api/config`)

| Endpoint             | Method | Description                              |
| :------------------- | :----- | :--------------------------------------- |
| `/api/config`        | GET    | Merged config with provenance            |
| `/api/config/{scope}`| PUT    | Update Global or Project config          |
| `/api/config/reload` | POST   | Hot-reload configuration                 |

**Field Safety Levels:**
- **Dangerous:** Read-only via API (e.g., `llm.api_key`)
- **Risky:** Require explicit confirmation (e.g., `paths.output_dir`)

### 6.4 SSE (`/sse/output`)

Single endpoint for real-time event streaming. Client connects and receives all events.

---

## 7. Failure Modes and Recovery

| Failure                        | Detection                    | Server Response                          |
| :----------------------------- | :--------------------------- | :--------------------------------------- |
| Subprocess crashes             | PID check, exit code         | Set state to `ERROR`, broadcast error event |
| Subprocess hangs (no output)   | Watchdog timeout (30s)       | Log warning, optional force-kill         |
| JSON marker parse error        | Exception in parser          | Broadcast raw line as `output`, log warning |
| SSE client disconnect          | Connection closed            | Remove from subscriber list, no retry    |
| Stale flag files after crash   | Startup check                | Delete orphan flags, reset to `IDLE`     |
| Report file outside project    | Path validation              | Return 403 Forbidden                     |

---

## 8. Security Model

### 8.1 Network Binding
- **Default:** `127.0.0.1` (localhost only)
- **Override:** `--host 0.0.0.0` (explicitly opt-in, shows warning)

### 8.2 CORS Policy
- Allows `localhost` and `127.0.0.1` origins only
- No credentials allowed for cross-origin requests

### 8.3 Path Traversal Protection
- All file access validated against project root
- Symlinks rejected
- Absolute paths rejected

### 8.4 Config Safety
- "Dangerous" fields cannot be modified via HTTP API
- "Risky" fields require `confirm: true` in request body

---

## 9. Performance Considerations

| Aspect             | Current Behavior                    | Limit                     |
| :----------------- | :---------------------------------- | :------------------------ |
| SSE buffer         | Unbounded queue per subscriber      | Memory growth risk        |
| Log retention      | Broadcast and discard               | No history on refresh     |
| Subprocess stdout  | Line-buffered read                  | High-volume may lag       |

**Recommended improvements:** Ring buffer for log history, bounded SSE queues.
