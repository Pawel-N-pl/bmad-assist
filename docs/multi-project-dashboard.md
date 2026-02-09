# Multi-Project Dashboard: Implementation Plan

> **Status:** Design Document (v3 - incorporates external review feedback)

This document outlines the proposed architecture for enabling a single `bmad-assist` dashboard to manage multiple concurrent `bmad-assist run` instances.

---

## 1. Requirements

| **Requirement**       | **Decision**                                                                 |
| :-------------------- | :--------------------------------------------------------------------------- |
| **Concurrent Runs**   | ✅ Yes. Multiple projects can run loops simultaneously.                      |
| **UI Pattern**        | Hybrid Grid + Slideover (overview + detail view).                            |
| **Scope**             | Local development only.                                                      |

---

## 2. Invariants and Constraints

### 2.1 Concurrency Rules

| Rule                        | Value        | Rationale                                           |
| :-------------------------- | :----------- | :-------------------------------------------------- |
| Max loops per project       | 1            | Prevent conflicting state in same project           |
| Max concurrent loops total  | 2 (default)  | Prevent API rate limiting, system resource exhaustion |
| Queue behavior              | FIFO queue   | When max reached, new starts are queued             |

### 2.2 Resource Policy

```yaml
# ~/.config/bmad-assist/server.yaml
server:
  max_concurrent_loops: 2
  queue_max_size: 10
  subprocess_timeout_seconds: 30
  log_buffer_size: 500
```

---

## 3. Selected UI Pattern: Hybrid Grid + Slideover

### 3.1 Wireframe

```
┌─────────────────────────────────────────────────────────────────────┐
│  [➕ Add]  [🔍 Scan]  [⏹ Stop All]           bmad-assist Dashboard  │
├─────────────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐            │
│  │  Project A    │  │  Project B    │  │  Project C    │            │
│  │  ● Running    │  │  ● Running ←  │  │  ○ Idle       │            │
│  │  Phase: ATDD  │  │  Phase: Dev   │  │               │            │
│  │  Story: 5.2   │  │  Story: 3.1   │  │  [▶ Start]    │            │
│  │  ⏱ 5m 23s     │  │  ⏱ 12m 07s   │  │  [View]       │            │
│  │  [View] [⏸]   │  │  [View] [⏸]   │  │               │            │
│  └───────────────┘  └───────────────┘  └───────────────┘            │
│  ┌───────────────┐                                                  │
│  │  Project D    │                     ┌────────────────────────────┤
│  │  ⏳ Queued    │                     │ Detail: Project B          │
│  │  Position: 1  │                     │                            │
│  │               │                     │ ┌──────────────────────┐   │
│  │  [Cancel]     │                     │ │ Live Logs            │   │
│  └───────────────┘                     │ │ [INFO] Building...   │   │
│                                        │ │ [INFO] Test passed   │   │
│                                        │ └──────────────────────┘   │
│                                        │ Sprint: 5 / Story: 3.1     │
│                                        │ Phase: dev_story           │
│                                        │ [⏸ Pause] [⏹ Stop]         │
│                                        │                    [✕]     │
│                                        └────────────────────────────┤
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Card Contents

Each project card displays:
- **Project Name** (display name or path basename)
- **Status**: ● Running (green), ⏸ Paused (yellow), ○ Idle (gray), ❌ Error (red), ⏳ Queued (blue)
- **Current Phase** and **Story** (if running)
- **Time in Phase** (helps identify stuck processes)
- **Quick Actions**: Start/Pause/Stop, View detail

### 3.3 Slideover Contents

- **Live Logs** (last 500 lines from ring buffer)
- **Sprint Status** (epic/story/phase)
- **Loop Controls** (Start, Pause, Resume, Stop)
- **Links to**: Config, Validation Reports
- **Close button**

---

## 4. Architecture

### 4.1 `ProjectContext` Class

Encapsulates state for one registered project.

```python
@dataclass
class ProjectContext:
    project_uuid: str              # Stable UUID, generated once
    project_root: Path             # Absolute canonical path
    display_name: str              # User-friendly name
    current_process: Process | None
    state: LoopState               # IDLE, STARTING, RUNNING, PAUSED, ERROR, QUEUED
    log_buffer: deque[str]         # Ring buffer, maxlen=500
    phase_start_time: datetime | None
    last_seen: datetime            # For registry health checks
```

**Project ID Strategy:** Use a stable UUID generated on first registration. Store mapping of UUID → canonical path. Hashing paths is fragile (symlinks, renames).

### 4.2 `ProjectRegistry` Class

Manages lifecycle of all `ProjectContext` instances.

```python
class ProjectRegistry:
    def register(self, path: Path) -> str:
        """Add project, return project_uuid. Validates path exists."""

    def unregister(self, project_uuid: str) -> None:
        """Remove project. Fails if loop is running."""

    def get(self, project_uuid: str) -> ProjectContext:
        """Return context or raise KeyError."""

    def list_all(self) -> list[ProjectSummary]:
        """Return all projects with health status."""

    def reconcile(self) -> list[str]:
        """Check for broken paths, return list of invalid UUIDs."""

    def can_start_loop(self) -> bool:
        """Check if under max_concurrent_loops limit."""
```

### 4.3 Registry Persistence

**Location:** `~/.config/bmad-assist/projects.yaml` (XDG-compliant)

```yaml
projects:
  - uuid: "a1b2c3d4-..."
    path: "/Users/dev/project-alpha"
    display_name: "Project Alpha"
    last_seen: "2024-01-15T10:30:00Z"
    last_status: "SUCCESS"  # or FAILED, IDLE

  - uuid: "e5f6g7h8-..."
    path: "/Users/dev/project-beta"
    display_name: "Project Beta"
    last_seen: "2024-01-14T08:00:00Z"
    last_status: "IDLE"
```

**Reconciliation on startup:**
- Check each path exists
- Mark missing projects as `BROKEN` (don't auto-remove)
- UI shows warning for broken projects

---

## 5. Process Lifecycle

### 5.1 Start Flow

```
User clicks Start
       │
       ▼
┌──────────────────┐
│ can_start_loop()? │
└────────┬─────────┘
         │
    ┌────┴────┐
    │ NO      │ YES
    ▼         ▼
┌────────┐  ┌────────────────┐
│ QUEUED │  │ Spawn subprocess│
└────────┘  └───────┬────────┘
                    │
                    ▼
              ┌───────────┐
              │ STARTING  │
              └─────┬─────┘
                    │
         ┌──────────┴──────────┐
         │                     │
    PID alive              PID dead
         │                     │
         ▼                     ▼
    ┌─────────┐           ┌───────┐
    │ RUNNING │           │ ERROR │
    └─────────┘           └───────┘
```

### 5.2 Stop Flow (Graceful + Force)

1. Write `stop.flag` to project directory
2. Wait up to `subprocess_timeout_seconds` for exit
3. If still running: send `SIGTERM`
4. Wait 5 seconds
5. If still running: send `SIGKILL`
6. Clean up flags, set state to `IDLE`

### 5.3 Crash Detection

- **Watchdog:** Check PID every 5 seconds
- **If PID dead:** Set state to `ERROR`, broadcast error event
- **Heartbeat (optional future):** Subprocess emits `DASHBOARD_EVENT:{"type":"heartbeat"}` every 10s

---

## 6. SSE Architecture

### 6.1 Routing Strategy

**Option A: Single stream, client-side filtering**
- `GET /sse/events` → All events, each tagged with `project_id`
- Frontend filters by active project

**Option B: Per-project streams** (Recommended)
- `GET /api/projects/{id}/sse/output` → Events for one project
- Simpler auth, easier debugging, no frontend filtering

### 6.2 Backpressure Policy

```python
class SSEChannel:
    max_queue_size: int = 1000
    drop_policy: str = "oldest"  # drop oldest when full
    heartbeat_interval: int = 15  # seconds
```

- Bounded queue per subscriber
- Drop oldest messages when full (not newest—user sees most recent)
- Heartbeat every 15s to detect dead connections

### 6.3 Log Buffer (Ring Buffer)

Each `ProjectContext` maintains a `deque(maxlen=500)`.

When client connects:
1. Flush buffer contents as initial batch
2. Then stream live events

---

## 7. API Changes

### 7.1 New Endpoints

| Endpoint                              | Method | Description                           |
| :------------------------------------ | :----- | :------------------------------------ |
| `/api/projects`                       | GET    | List all registered projects          |
| `/api/projects`                       | POST   | Register new project `{path, name?}`  |
| `/api/projects/scan`                  | POST   | Scan directory for `.bmad-assist/`    |
| `/api/projects/control/stop-all`      | POST   | Stop all running loops                |
| `/api/projects/{id}`                  | GET    | Get project details                   |
| `/api/projects/{id}`                  | DELETE | Unregister project                    |
| `/api/projects/{id}/loop/start`       | POST   | Start loop for project                |
| `/api/projects/{id}/loop/pause`       | POST   | Pause loop for project                |
| `/api/projects/{id}/loop/resume`      | POST   | Resume loop for project               |
| `/api/projects/{id}/loop/stop`        | POST   | Stop loop for project                 |
| `/api/projects/{id}/status`           | GET    | Sprint status for project             |
| `/api/projects/{id}/sse/output`       | GET    | SSE stream for project                |
| `/api/projects/{id}/config`           | GET    | Get project config                    |
| `/api/projects/{id}/config`           | PUT    | Update project config                 |

### 7.2 SSE Event Format

```json
{
  "event": "output",
  "data": {
    "project_id": "a1b2c3d4-...",
    "line": "[INFO] Story 5.2 started",
    "level": "info",
    "ts": "2024-01-15T10:30:00Z"
  }
}
```

---

## 8. Frontend State Management

Recommended: Lightweight state manager (Zustand for React, Pinia for Vue).

```typescript
interface DashboardState {
  projects: Map<string, ProjectSummary>;
  activeProjectId: string | null;
  sseConnection: EventSource | null;

  // Actions
  selectProject(id: string): void;
  startLoop(id: string): Promise<void>;
  stopAllLoops(): Promise<void>;
}
```

---

## 9. File Structure

```
src/bmad_assist/dashboard/
├── manager/
│   ├── project_context.py   # State for one project
│   ├── registry.py          # Collection + persistence
│   └── process_supervisor.py # PID monitoring, cleanup
├── routes/
│   ├── projects.py          # /api/projects/...
│   └── project_loop.py      # /api/projects/{id}/loop/...
├── sse/
│   ├── broadcaster.py       # Multi-channel SSE
│   ├── channel.py           # Per-project channel with buffer
│   └── event_parser.py      # DASHBOARD_EVENT parsing
└── server.py                # Entry point
```

---

## 10. Impact Summary

| Area             | Impact  | Key Changes                                                    |
| :--------------- | :------ | :------------------------------------------------------------- |
| Backend          | High    | New `ProjectRegistry`, `ProjectContext`, process supervisor    |
| API              | High    | All routes scoped by `project_id`, new management endpoints    |
| SSE              | Medium  | Per-project channels, backpressure, log buffer                 |
| Frontend         | High    | Grid UI, slideover, state management                           |
| Config           | Low     | New `server.yaml` for global settings                          |
| CLI              | Low     | `serve` no longer requires `--project` flag                    |

---

## 11. Implementation Phases

### Phase 1: Backend Foundation
1. Create `ProjectContext` and `ProjectRegistry`
2. Implement registry persistence
3. Add process supervisor with PID monitoring
4. Add log ring buffer

### Phase 2: API Migration
1. Add new `/api/projects/...` endpoints
2. Migrate existing endpoints to project-scoped versions
3. Add multi-project SSE channels

### Phase 3: Frontend
1. Build Grid overview component
2. Build Slideover detail panel
3. Implement state management
4. Wire up SSE routing

### Phase 4: Polish
1. Add "Scan" feature for project discovery
2. Add "Stop All" functionality
3. Add concurrency queue UI
4. Performance testing with 5+ concurrent projects
