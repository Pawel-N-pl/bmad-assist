# Prompt: Build Multi-Project Dashboard Frontend UI

I need to implement the **frontend UI for the multi-project dashboard** in the `bmad-assist` project. The backend API is already implemented and tested.

## Context

The backend implementation includes:

### New API Endpoints (already implemented)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects` | List all registered projects with state, running count, and queue info |
| `POST` | `/api/projects` | Register a new project `{path: string, name?: string}` |
| `POST` | `/api/projects/scan` | Scan directory for projects `{directory: string}` |
| `POST` | `/api/projects/control/stop-all` | Stop all running loops |
| `GET` | `/api/projects/{id}` | Get project details with logs |
| `DELETE` | `/api/projects/{id}` | Unregister a project |
| `POST` | `/api/projects/{id}/loop/start` | Start loop (may queue if at max concurrent) |
| `POST` | `/api/projects/{id}/loop/pause` | Pause loop |
| `POST` | `/api/projects/{id}/loop/resume` | Resume loop |
| `POST` | `/api/projects/{id}/loop/stop` | Stop loop |
| `GET` | `/api/projects/{id}/status` | Get sprint status |
| `GET` | `/api/projects/{id}/sse/output` | Per-project SSE stream |

### Project State Machine (`LoopState`)

| State | Description |
|-------|-------------|
| `idle` | Not running |
| `starting` | Subprocess spawning |
| `running` | Loop executing |
| `pause_requested` | Will pause after current step |
| `paused` | Paused, awaiting resume |
| `queued` | Waiting for slot (max concurrent reached) |
| `error` | Crashed or failed |

### Design Document

Review `docs/multi-project-dashboard.md` Section 9 (Frontend State Management) for the design spec.

## Requirements

### 1. Project List/Sidebar

- Display all registered projects with their current state (color-coded badges)
- Show running/queued/paused indicators
- Allow selecting a project to view its details
- "Add Project" button to register new projects
- "Scan Directory" button to discover projects

### 2. Per-Project Controls

- Start/Pause/Resume/Stop buttons based on current state
- Show queue position when queued
- Display current epic/story/phase

### 3. Per-Project SSE Output

- Each project has its own output stream via `/api/projects/{id}/sse/output`
- Log replay on connect (the SSE sends a `log_replay` event on connect)
- Real-time output streaming
- Show subprocess output with proper formatting

### 4. Global Controls

- "Stop All" button to stop all running/paused projects
- Show running count vs max concurrent (e.g., "2/3 running")

### 5. State Indicators

- Use color-coded badges: green=running, yellow=paused, orange=queued, red=error, gray=idle
- Show phase duration when running

### 6. Error Handling

- Display error messages from the `error` SSE event
- Show error state in project list

## Technical Notes

- The existing frontend is in `src/bmad_assist/dashboard/static/`
- The frontend uses vanilla HTML/CSS/JS (no framework)
- The existing SSE integration is in the current dashboard - study it for patterns
- The dashboard currently shows a single-project view - this needs to become a multi-project view
- Maintain the existing aesthetic and design patterns

## Starting Point

1. First, review the existing frontend code in `src/bmad_assist/dashboard/static/`
2. Review `docs/multi-project-dashboard.md` Section 9 for the frontend design spec
3. Study the existing SSE integration patterns
4. Implement the multi-project UI incrementally

## Testing Requirements

### Unit Tests

- Write unit tests for all new JavaScript modules and functions
- Test state management logic for multi-project handling
- Test UI component rendering and state updates
- Test API client functions for all new endpoints
- All unit tests must pass before completion

### E2E Tests

- Create E2E tests using Playwright (existing test framework in the project)
- Test project registration flow (add project, verify it appears in list)
- Test project loop control (start, pause, resume, stop)
- Test SSE connection and output streaming
- Test "Stop All" functionality
- Test error state handling and display
- Test queue behavior when max concurrent is reached
- All E2E tests must pass before completion

### Test Location

- Unit tests: `tests/dashboard/test_frontend_*.py` or `tests/dashboard/frontend/`
- E2E tests: `tests/e2e/test_multi_project_dashboard.py`

## Documentation Requirements

### User Documentation

- Create comprehensive documentation in `docs/multi-project-dashboard-user-guide.md`
- Include step-by-step usage instructions
- Document all UI features and controls

### Screenshots

- Capture screenshots of the completed UI for documentation
- Include screenshots showing:
  - Project list/sidebar with multiple projects in different states
  - Adding a new project
  - Project running with SSE output streaming
  - Paused project state
  - Queued project with queue position
  - Error state display
  - "Stop All" functionality
- Save screenshots to `docs/images/multi-project-dashboard/`

### Technical Documentation

- Update `docs/multi-project-dashboard.md` with frontend implementation details
- Document the JavaScript architecture and module structure
- Document any new CSS classes and design patterns used

## Task

Please implement the frontend UI for the multi-project dashboard, ensuring:

1. It integrates with the existing backend API
2. Follows the existing code style and design patterns
3. All unit tests pass
4. All E2E tests pass
5. Full documentation is provided with screenshots
