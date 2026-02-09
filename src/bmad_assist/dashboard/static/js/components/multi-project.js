/**
 * Multi-project dashboard component for bmad-assist
 * Manages multiple projects, their states, and SSE connections
 * 
 * Based on design document: docs/multi-project-dashboard.md Section 8
 */

window.multiProjectComponent = function () {
    return {
        // ==========================================
        // State
        // ==========================================

        // Project map: UUID -> ProjectSummary
        projects: new Map(),

        // Currently selected project UUID (for detail view)
        activeProjectId: null,

        // SSE connection per project: UUID -> EventSource
        projectSSEConnections: new Map(),

        // Server info
        serverInfo: {
            runningCount: 0,
            maxConcurrent: 2,
            queueSize: 0,
        },

        // UI state
        multiProjectView: {
            loading: false,
            error: null,
            addProjectModal: false,
            scanModal: false,
            addProjectPath: '',
            addProjectName: '',
            scanDirectory: '',
        },

        // Log buffers per project: UUID -> string[]
        projectLogs: new Map(),

        // ==========================================
        // Initialization
        // ==========================================

        /**
         * Initialize multi-project component
         * Called from alpine-init.js on dashboard mount
         */
        async initMultiProject() {
            await this.fetchProjects();
            // Set up polling for project list updates
            setInterval(() => this.fetchProjects(), 5000);
        },

        // ==========================================
        // API Methods - Project Management
        // ==========================================

        /**
         * Fetch all registered projects from the server
         */
        async fetchProjects() {
            try {
                const response = await fetch('/api/projects');
                const data = await response.json();

                // Update server info
                this.serverInfo.runningCount = data.running_count || 0;
                this.serverInfo.maxConcurrent = data.max_concurrent || 2;
                this.serverInfo.queueSize = data.queue_size || 0;

                // Update projects map
                const newProjects = new Map();
                for (const project of (data.projects || [])) {
                    newProjects.set(project.uuid, project);
                }
                this.projects = newProjects;

                // Refresh icons after updating project list
                this.$nextTick(() => this.refreshIcons());

                return data;
            } catch (error) {
                console.error('Failed to fetch projects:', error);
                this.multiProjectView.error = 'Failed to load projects';
                return null;
            }
        },

        /**
         * Register a new project
         * @param {string} path - Path to project directory
         * @param {string} name - Optional display name
         */
        async addProject(path, name) {
            try {
                this.multiProjectView.loading = true;
                const response = await fetch('/api/projects', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path, name: name || undefined }),
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to add project');
                    return null;
                }

                await this.fetchProjects();
                this.showToast(`Project "${data.display_name}" added`);
                return data;
            } catch (error) {
                console.error('Failed to add project:', error);
                this.showToast('Failed to add project');
                return null;
            } finally {
                this.multiProjectView.loading = false;
            }
        },

        /**
         * Scan a directory for bmad-assist projects
         * @param {string} directory - Directory to scan
         */
        async scanForProjects(directory) {
            try {
                this.multiProjectView.loading = true;
                const response = await fetch('/api/projects/scan', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ directory }),
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to scan directory');
                    return null;
                }

                await this.fetchProjects();
                this.showToast(`Found ${data.count} project(s)`);
                return data;
            } catch (error) {
                console.error('Failed to scan directory:', error);
                this.showToast('Failed to scan directory');
                return null;
            } finally {
                this.multiProjectView.loading = false;
            }
        },

        /**
         * Remove a project from the registry
         * @param {string} projectId - Project UUID
         */
        async removeProject(projectId) {
            const project = this.projects.get(projectId);
            if (!project) return;

            if (project.state !== 'idle' && project.state !== 'error') {
                this.showToast('Stop the project before removing');
                return;
            }

            try {
                const response = await fetch(`/api/projects/${projectId}`, {
                    method: 'DELETE',
                });

                if (!response.ok) {
                    const data = await response.json();
                    this.showToast(data.error || 'Failed to remove project');
                    return;
                }

                // Disconnect SSE if connected
                this.disconnectProjectSSE(projectId);

                // Clear active selection if this was the active project
                if (this.activeProjectId === projectId) {
                    this.activeProjectId = null;
                }

                await this.fetchProjects();
                this.showToast(`Project removed`);
            } catch (error) {
                console.error('Failed to remove project:', error);
                this.showToast('Failed to remove project');
            }
        },

        // ==========================================
        // API Methods - Loop Control
        // ==========================================

        /**
         * Start loop for a specific project
         * @param {string} projectId - Project UUID
         */
        async startProjectLoop(projectId) {
            try {
                const response = await fetch(`/api/projects/${projectId}/loop/start`, {
                    method: 'POST',
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to start loop');
                    return;
                }

                // Connect to SSE for this project if not already connected
                this.connectProjectSSE(projectId);

                if (data.status === 'queued') {
                    this.showToast(`Queued at position ${data.queue_position}`);
                } else {
                    this.showToast('Loop started');
                }

                await this.fetchProjects();
            } catch (error) {
                console.error('Failed to start project loop:', error);
                this.showToast('Failed to start loop');
            }
        },

        /**
         * Pause loop for a specific project
         * @param {string} projectId - Project UUID
         */
        async pauseProjectLoop(projectId) {
            try {
                const response = await fetch(`/api/projects/${projectId}/loop/pause`, {
                    method: 'POST',
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to pause loop');
                    return;
                }

                this.showToast('Pause requested');
                await this.fetchProjects();
            } catch (error) {
                console.error('Failed to pause project loop:', error);
                this.showToast('Failed to pause loop');
            }
        },

        /**
         * Resume loop for a specific project
         * @param {string} projectId - Project UUID
         */
        async resumeProjectLoop(projectId) {
            try {
                const response = await fetch(`/api/projects/${projectId}/loop/resume`, {
                    method: 'POST',
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to resume loop');
                    return;
                }

                this.showToast('Loop resumed');
                await this.fetchProjects();
            } catch (error) {
                console.error('Failed to resume project loop:', error);
                this.showToast('Failed to resume loop');
            }
        },

        /**
         * Stop loop for a specific project
         * @param {string} projectId - Project UUID
         */
        async stopProjectLoop(projectId) {
            try {
                const response = await fetch(`/api/projects/${projectId}/loop/stop`, {
                    method: 'POST',
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to stop loop');
                    return;
                }

                this.showToast('Loop stopped');
                await this.fetchProjects();
            } catch (error) {
                console.error('Failed to stop project loop:', error);
                this.showToast('Failed to stop loop');
            }
        },

        /**
         * Stop all running projects
         */
        async stopAllProjects() {
            try {
                const response = await fetch('/api/projects/control/stop-all', {
                    method: 'POST',
                });

                const data = await response.json();

                if (!response.ok) {
                    this.showToast(data.error || 'Failed to stop all');
                    return;
                }

                this.showToast(`Stopped ${data.count} project(s)`);
                await this.fetchProjects();
            } catch (error) {
                console.error('Failed to stop all projects:', error);
                this.showToast('Failed to stop all');
            }
        },

        // ==========================================
        // SSE Connection Management
        // ==========================================

        /**
         * Connect to SSE for a specific project
         * @param {string} projectId - Project UUID
         */
        connectProjectSSE(projectId) {
            // Skip if already connected
            if (this.projectSSEConnections.has(projectId)) {
                return;
            }

            const eventSource = new EventSource(`/api/projects/${projectId}/sse/output`);
            this.projectSSEConnections.set(projectId, eventSource);

            // Initialize log buffer for this project
            if (!this.projectLogs.has(projectId)) {
                this.projectLogs.set(projectId, []);
            }

            eventSource.onopen = () => {
                console.log(`SSE connected for project ${projectId.substring(0, 8)}`);
            };

            eventSource.onerror = (error) => {
                console.error(`SSE error for project ${projectId.substring(0, 8)}:`, error);
                // Only reconnect if still active
                const project = this.projects.get(projectId);
                if (project && project.state !== 'idle' && project.state !== 'error') {
                    setTimeout(() => {
                        this.disconnectProjectSSE(projectId);
                        this.connectProjectSSE(projectId);
                    }, 2000);
                }
            };

            // Handle log_replay event (initial logs on connect)
            eventSource.addEventListener('log_replay', (event) => {
                const data = JSON.parse(event.data);
                if (data.logs) {
                    this.projectLogs.set(projectId, data.logs);
                    this.updateProjectTerminal(projectId);
                }
            });

            // Handle output event
            eventSource.addEventListener('output', (event) => {
                const data = JSON.parse(event.data);
                const logs = this.projectLogs.get(projectId) || [];
                logs.push(data.line || data.text || JSON.stringify(data));
                // Keep only last 500 lines
                if (logs.length > 500) {
                    logs.shift();
                }
                this.projectLogs.set(projectId, logs);
                this.updateProjectTerminal(projectId);
            });

            // Handle loop_status event
            eventSource.addEventListener('loop_status', (event) => {
                const data = JSON.parse(event.data);
                const project = this.projects.get(projectId);
                if (project) {
                    project.state = data.status || data.state;
                    this.projects.set(projectId, project);
                }
            });

            // Handle error event
            eventSource.addEventListener('error_event', (event) => {
                const data = JSON.parse(event.data);
                this.showToast(`Error: ${data.message || data.error}`, 'error');
            });

            // Handle workflow_status event
            eventSource.addEventListener('workflow_status', (event) => {
                const data = JSON.parse(event.data);
                const project = this.projects.get(projectId);
                if (project && data.data) {
                    project.current_phase = data.data.current_phase;
                    project.current_story = data.data.current_story;
                    this.projects.set(projectId, project);
                }
            });
        },

        /**
         * Disconnect SSE for a specific project
         * @param {string} projectId - Project UUID
         */
        disconnectProjectSSE(projectId) {
            const eventSource = this.projectSSEConnections.get(projectId);
            if (eventSource) {
                eventSource.close();
                this.projectSSEConnections.delete(projectId);
                console.log(`SSE disconnected for project ${projectId.substring(0, 8)}`);
            }
        },

        /**
         * Update terminal display for a project (if active)
         * @param {string} projectId - Project UUID
         */
        updateProjectTerminal(projectId) {
            // Only update if this is the active project
            if (this.activeProjectId !== projectId) {
                return;
            }

            const logs = this.projectLogs.get(projectId) || [];

            // Update xterm if available
            if (this.xterm && this.xtermInitialized) {
                // Clear and rewrite all logs
                this.xterm.clear();
                for (const line of logs) {
                    this.xterm.writeln(line);
                }
            }
        },

        // ==========================================
        // UI Helper Methods
        // ==========================================

        /**
         * Select a project for detail view
         * @param {string} projectId - Project UUID
         */
        selectProject(projectId) {
            this.activeProjectId = projectId;

            // Connect to SSE for this project if it's active
            const project = this.projects.get(projectId);
            if (project && project.state !== 'idle' && project.state !== 'error') {
                this.connectProjectSSE(projectId);
            }

            // Update terminal with this project's logs
            this.updateProjectTerminal(projectId);

            this.$nextTick(() => this.refreshIcons());
        },

        /**
         * Close the project detail view
         */
        closeProjectDetail() {
            this.activeProjectId = null;
        },

        /**
         * Get projects as array for Alpine iteration
         * @returns {Array} Array of project objects
         */
        getProjectsArray() {
            return Array.from(this.projects.values());
        },

        /**
         * Get the active project object
         * @returns {Object|null} Active project or null
         */
        getActiveProject() {
            if (!this.activeProjectId) return null;
            return this.projects.get(this.activeProjectId) || null;
        },

        /**
         * Get color-coded badge class for project state
         * @param {string} state - Project state
         * @returns {string} CSS classes for badge
         */
        getProjectStateBadge(state) {
            const badges = {
                idle: 'bg-muted text-muted-foreground',
                starting: 'bg-blue-500/20 text-blue-400',
                running: 'bg-green-500/20 text-green-400',
                pause_requested: 'bg-yellow-500/20 text-yellow-400',
                paused: 'bg-yellow-500/20 text-yellow-400',
                queued: 'bg-orange-500/20 text-orange-400',
                error: 'bg-red-500/20 text-red-400',
            };
            return badges[state] || badges.idle;
        },

        /**
         * Get icon name for project state
         * @param {string} state - Project state
         * @returns {string} Lucide icon name
         */
        getProjectStateIcon(state) {
            const icons = {
                idle: 'circle',
                starting: 'loader',
                running: 'play-circle',
                pause_requested: 'loader',
                paused: 'pause-circle',
                queued: 'clock',
                error: 'x-circle',
            };
            return icons[state] || icons.idle;
        },

        /**
         * Get state display text
         * @param {string} state - Project state
         * @returns {string} Human-readable state
         */
        getProjectStateText(state) {
            const texts = {
                idle: 'Idle',
                starting: 'Starting',
                running: 'Running',
                pause_requested: 'Pausing...',
                paused: 'Paused',
                queued: 'Queued',
                error: 'Error',
            };
            return texts[state] || state;
        },

        /**
         * Check if project can be started
         * @param {Object} project - Project object
         * @returns {boolean}
         */
        canStartProject(project) {
            return project.state === 'idle' || project.state === 'error';
        },

        /**
         * Check if project can be paused
         * @param {Object} project - Project object
         * @returns {boolean}
         */
        canPauseProject(project) {
            return project.state === 'running';
        },

        /**
         * Check if project can be resumed
         * @param {Object} project - Project object
         * @returns {boolean}
         */
        canResumeProject(project) {
            return project.state === 'paused';
        },

        /**
         * Check if project can be stopped
         * @param {Object} project - Project object
         * @returns {boolean}
         */
        canStopProject(project) {
            return ['running', 'paused', 'pause_requested', 'starting', 'queued'].includes(project.state);
        },

        /**
         * Format phase duration for display
         * @param {number|null} seconds - Duration in seconds
         * @returns {string} Formatted duration
         */
        formatPhaseDuration(seconds) {
            if (seconds === null || seconds === undefined) {
                return '--:--';
            }

            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);

            if (mins > 0) {
                return `${mins}m ${secs}s`;
            }
            return `${secs}s`;
        },

        /**
         * Get display name for phase
         * @param {string} phase - Phase identifier
         * @returns {string} Human-readable phase name
         */
        getPhaseDisplayName(phase) {
            const names = {
                'create_story': 'Create Story',
                'validate_story': 'Validate Story',
                'validate_story_synthesis': 'Validate Synthesis',
                'dev_story': 'Develop Story',
                'code_review': 'Code Review',
                'code_review_synthesis': 'Review Synthesis',
                'retrospective': 'Retrospective',
                'qa_plan_generate': 'QA Plan',
                'qa_plan_execute': 'QA Execute',
            };
            return names[phase] || phase || 'Unknown';
        },

        // ==========================================
        // Modal Handlers
        // ==========================================

        /**
         * Open the add project modal
         */
        openAddProjectModal() {
            this.multiProjectView.addProjectPath = '';
            this.multiProjectView.addProjectName = '';
            this.multiProjectView.addProjectModal = true;
        },

        /**
         * Close the add project modal
         */
        closeAddProjectModal() {
            this.multiProjectView.addProjectModal = false;
        },

        /**
         * Submit the add project form
         */
        async submitAddProject() {
            const path = this.multiProjectView.addProjectPath.trim();
            const name = this.multiProjectView.addProjectName.trim();

            if (!path) {
                this.showToast('Please enter a project path');
                return;
            }

            const result = await this.addProject(path, name);
            if (result) {
                this.closeAddProjectModal();
            }
        },

        /**
         * Open the scan directory modal
         */
        openScanModal() {
            this.multiProjectView.scanDirectory = '';
            this.multiProjectView.scanModal = true;
        },

        /**
         * Close the scan directory modal
         */
        closeScanModal() {
            this.multiProjectView.scanModal = false;
        },

        /**
         * Submit the scan directory form
         */
        async submitScanDirectory() {
            const directory = this.multiProjectView.scanDirectory.trim();

            if (!directory) {
                this.showToast('Please enter a directory path');
                return;
            }

            const result = await this.scanForProjects(directory);
            if (result) {
                this.closeScanModal();
            }
        },
    };
};
