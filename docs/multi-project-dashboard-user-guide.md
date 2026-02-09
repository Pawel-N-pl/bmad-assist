# Multi-Project Dashboard User Guide

The multi-project dashboard allows you to manage and monitor multiple bmad-assist projects from a single interface. This guide covers all features and controls.

## Accessing the Dashboard

1. Start the bmad-assist dashboard server: `bmad-assist serve`
2. Open your browser to `http://localhost:8899`
3. Click the **Projects** button in the main dashboard header

Or navigate directly to `http://localhost:8899/projects.html`

## Dashboard Overview

The multi-project dashboard displays:
- **Header** - Logo, title, running count badge, and global controls
- **Project Grid** - Card-based view of all registered projects
- **Slideover Panel** - Detailed view of the selected project with live logs

## Global Controls

| Button | Description |
|--------|-------------|
| **Running Count** | Badge showing `X/Y running` (current vs max concurrent) |
| **Add Project** | Opens modal to register a new project |
| **Scan Directory** | Discovers bmad-assist projects in a directory |
| **Stop All** | Stops all running and paused projects |
| **Dashboard** | Returns to the main single-project dashboard |

## Project Cards

Each project card displays:
- **Project name** and path
- **State badge** with color-coded status
- **Phase info** (when running) - current phase, story, duration
- **Queue position** (when queued)
- **Error message** (when in error state)
- **Control buttons** - Start, Pause, Resume, Stop, View, Remove

### Project States

| State | Color | Description |
|-------|-------|-------------|
| **Idle** | Gray | Not running |
| **Starting** | Blue | Subprocess spawning |
| **Running** | Green | Loop actively executing |
| **Pause Requested** | Yellow | Will pause after current step |
| **Paused** | Yellow | Paused, waiting for resume |
| **Queued** | Orange | Waiting for slot (max concurrent reached) |
| **Error** | Red | Crashed or failed |

## Adding Projects

1. Click **Add Project** in the header
2. Enter the absolute path to your bmad-assist project directory
3. Optionally provide a display name
4. Click **Add Project**

The project must contain a `.bmad-assist/` configuration directory.

## Scanning for Projects

1. Click **Scan Directory** in the header
2. Enter the path to a parent directory containing multiple projects
3. Click **Scan Directory**

The scanner finds all subdirectories containing `.bmad-assist/` folders.

## Controlling Project Loops

| Action | When Available | Effect |
|--------|----------------|--------|
| **Start** | Idle or Error | Starts the automation loop (or queues if at max) |
| **Pause** | Running | Pauses after current step completes |
| **Resume** | Paused | Continues from where it paused |
| **Stop** | Running/Paused/Queued | Immediately stops the loop |
| **Remove** | Idle or Error | Unregisters the project from the dashboard |

## Viewing Project Details

Click any project card (or the **View** button) to open the slideover panel:

- **Project Info** - Path, state, current phase, story, duration
- **Controls** - Start, Pause, Resume, Stop buttons
- **Live Output** - Real-time streaming logs from the project

Close the panel by clicking the **X** button.

## Concurrent Execution

The dashboard limits how many projects can run simultaneously (default: 2).

- When you start a project and the limit is reached, it enters **Queued** state
- Queue position is displayed on the card
- When a running project completes or stops, the next queued project starts automatically

## Real-time Streaming

Each project has its own SSE (Server-Sent Events) connection for:
- Live terminal output
- State change notifications
- Workflow status updates (phase/story changes)
- Error events

Log buffers are preserved when switching between projects.

## Tips

- **Refresh projects** - The project list auto-refreshes every 5 seconds
- **Toast notifications** - Success/error messages appear briefly in bottom-right
- **Keyboard shortcuts** - Press `Escape` to close modals
- **Log scrolling** - The live output panel auto-scrolls to the bottom

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Project not appearing | Verify the path contains `.bmad-assist/` directory |
| Can't start project | Check if max concurrent limit is reached |
| SSE not connecting | Refresh the page and ensure the project is running |
| Remove button disabled | Stop the project first before removing |
