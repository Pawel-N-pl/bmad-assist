/**
 * Alpine.js initialization for bmad-dashboard
 * Orchestrates all component factories into a single dashboard scope
 *
 * Story 23.1: Modular Architecture
 * This file combines state and methods from all component files:
 * - utils.js: Shared utility functions (window.dashboardUtils)
 * - tree-view.js: Epic/story navigation (window.treeViewComponent)
 * - terminal.js: Terminal output display (window.terminalComponent)
 * - settings.js: Configuration management (window.settingsComponent)
 * - experiments.js: Experiment management (window.experimentsComponent)
 * - context-menu.js: Right-click/kebab menus (window.contextMenuComponent)
 * - modals.js: Content/report modals (window.modalsComponent)
 * - content-browser.js: Shared browser utilities (window.contentBrowserComponent) [Story 24.1]
 * - epic-metrics.js: Epic metrics browser (window.epicMetricsComponent) [Story 24.7]
 * - sse-connection.js: SSE event streaming (window.sseConnectionComponent)
 * - loop-control.js: Loop start/pause/stop (window.loopControlComponent)
 */

function dashboard() {
    // Collect all component factories
    const utils = window.dashboardUtils || {};
    const treeView = window.treeViewComponent ? window.treeViewComponent() : {};
    const terminal = window.terminalComponent ? window.terminalComponent() : {};
    const settings = window.settingsComponent ? window.settingsComponent() : {};
    const experiments = window.experimentsComponent ? window.experimentsComponent() : {};
    const contextMenu = window.contextMenuComponent ? window.contextMenuComponent() : {};
    const modals = window.modalsComponent ? window.modalsComponent() : {};
    const promptBrowser = window.promptBrowserComponent ? window.promptBrowserComponent() : {};
    const contentBrowser = window.contentBrowserComponent ? window.contentBrowserComponent() : {};
    const epicMetrics = window.epicMetricsComponent ? window.epicMetricsComponent() : {};
    const sseConnection = window.sseConnectionComponent ? window.sseConnectionComponent() : {};
    const loopControl = window.loopControlComponent ? window.loopControlComponent() : {};
    const multiProject = window.multiProjectComponent ? window.multiProjectComponent() : {};

    // Merge all components into a single object
    // Later components override earlier ones if there are conflicts
    return {
        // Spread all component state and methods
        ...treeView,
        ...terminal,
        ...settings,
        ...experiments,
        ...contextMenu,
        ...modals,
        ...promptBrowser,
        ...contentBrowser,
        ...epicMetrics,
        ...sseConnection,
        ...loopControl,
        ...multiProject,

        // Legacy queue state (removed in refactor but templates still reference)
        // Provides default values to prevent Alpine errors
        queue: {
            current: null,
            queue: []
        },

        // Legacy busy modal state (removed in refactor but templates still reference)
        busyModal: {
            show: false,
            priority: 'last'
        },

        // Utility functions - delegate to utils.js (loaded first via window.dashboardUtils)
        refreshIcons: utils.refreshIcons,
        getStatusColor: utils.getStatusColor,
        getStatusTextColor: utils.getStatusTextColor,
        getStatusIcon: utils.getStatusIcon,
        getEpicStatusIcon: utils.getEpicStatusIcon,
        getActionIcon: utils.getActionIcon,

        // Elapsed time display tick counter (triggers Alpine reactivity)
        elapsedTimeTick: 0,

        // Phase helpers (not in utils.js, keep inline)
        getPhaseIcon(status) {
            const icons = {
                completed: 'check-circle',
                'in-progress': 'play-circle',
                error: 'x-circle',
                pending: 'circle-dashed'
            };
            return icons[status] || 'circle-dashed';
        },

        /**
         * Format elapsed time from phase_started_at ISO string
         * @param {string|null} phaseStartedAt - ISO timestamp of phase start
         * @returns {string} Formatted elapsed time (e.g., "1m 34s")
         */
        formatElapsedTime(phaseStartedAt) {
            // Trigger reactivity on tick
            void this.elapsedTimeTick;

            if (!phaseStartedAt) {
                return '--:--';
            }

            const startTime = new Date(phaseStartedAt).getTime();
            const now = Date.now();
            const elapsedMs = now - startTime;

            if (elapsedMs < 0) {
                return '0s';
            }

            const totalSeconds = Math.floor(elapsedMs / 1000);
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = totalSeconds % 60;

            if (minutes > 0) {
                return `${minutes}m ${seconds}s`;
            }
            return `${seconds}s`;
        },

        getPhaseTextColor(status) {
            // Returns CSS classes for phase status with colors and animations
            // Green for completed, red for error
            // Blue pulsing for in-progress when run is active
            // Yellow-orange for in-progress when run is stopped
            if (status === 'completed') return 'phase-completed';
            if (status === 'error') return 'phase-error';
            if (status === 'in-progress') {
                return this.loopRunning ? 'phase-in-progress phase-pulse' : 'phase-paused';
            }
            return 'phase-pending';
        },

        // Story status color - considers loopRunning state
        // Statuses: done, error, blocked, in-progress, review, ready-for-dev, backlog, deferred
        getStoryStatusColor(status) {
            if (status === 'done') return 'status-done';  // Green
            if (status === 'error' || status === 'blocked') return 'status-error';  // Red
            // Active states: in-progress, review, ready-for-dev
            if (status === 'in-progress' || status === 'review' || status === 'ready-for-dev') {
                return this.loopRunning ? 'status-active' : 'status-paused';  // Blue or yellow
            }
            return 'status-pending';  // Backlog/deferred → gray
        },

        // Epic status color - considers loopRunning state
        // Computes status from stories if epic.status is null
        getEpicStatusColor(epic) {
            // Handle both epic object and status string for backwards compatibility
            let status = epic;
            if (epic && typeof epic === 'object') {
                // Compute status from stories if not set
                if (!epic.status && epic.stories) {
                    const activeStatuses = ['in-progress', 'review', 'ready-for-dev'];
                    const allDone = epic.stories.every(s => s.status === 'done');
                    const anyActive = epic.stories.some(s => activeStatuses.includes(s.status));
                    const anyError = epic.stories.some(s => s.status === 'error' || s.status === 'blocked');
                    if (allDone) status = 'done';
                    else if (anyError) status = 'error';
                    else if (anyActive) status = 'in-progress';
                    else status = 'backlog';
                } else {
                    status = epic.status;
                }
            }

            if (status === 'done') return 'status-done';  // Green
            if (status === 'error' || status === 'blocked') return 'status-error';  // Red
            if (status === 'in-progress' || status === 'review' || status === 'ready-for-dev') {
                return this.loopRunning ? 'status-active' : 'status-paused';  // Blue or yellow
            }
            return 'status-pending';  // Backlog/deferred → gray
        },

        /**
         * Main initialization - called when Alpine component mounts
         */
        init() {
            // Initialize terminal (load persisted font size)
            if (this.initTerminal) {
                this.initTerminal();
            }

            // Initialize loop control (version fetch, status polling)
            if (this.initLoopControl) {
                this.initLoopControl();
            }

            // Connect to SSE
            this.connectSSE();

            // Initialize multi-project view
            if (this.initMultiProject) {
                this.initMultiProject();
            }

            // Fetch initial data
            this.fetchStories();

            // Initialize Lucide icons after Alpine mounts
            this.$nextTick(() => this.refreshIcons());

            // Start elapsed time timer (updates every second)
            setInterval(() => {
                this.elapsedTimeTick++;
            }, 1000);
        }
    };
}
