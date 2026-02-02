/**
 * Loop control component for bmad-assist run loop management
 * Handles start, pause, resume, and stop operations
 */

window.loopControlComponent = function() {
    return {
        // Loop state
        loopRunning: false,
        pauseRequested: false,  // Pause requested, waiting for current workflow to complete
        isPaused: false,        // Story 22.10: Actual pause state (paused vs running)
        _loopStatusInterval: null,

        // Version info
        version: null,

        /**
         * Initialize loop control (called from main init)
         */
        initLoopControl() {
            this.checkLoopStatus();
            this.fetchVersion();
            // Poll loop status every 2 seconds to detect external runs
            // (CLI, context menu actions, etc.)
            this._loopStatusInterval = setInterval(() => {
                this.checkLoopStatus();
            }, 2000);
        },

        /**
         * Fetch bmad-assist version
         */
        async fetchVersion() {
            try {
                const res = await fetch('/api/version');
                const data = await res.json();
                this.version = data.version;
            } catch (err) {
                console.error('Failed to fetch version:', err);
            }
        },

        /**
         * Start the bmad-assist loop
         */
        async startLoop() {
            try {
                const response = await fetch('/api/loop/start', { method: 'POST' });
                const data = await response.json();
                console.log('Start loop response:', data);
                if (data.status === 'started') {
                    this.loopRunning = true;
                    // Story 22.11 Task 7.4: Update terminal status on start
                    this.terminalStatus = 'running';
                }
            } catch (error) {
                console.error('Failed to start loop:', error);
            }
        },

        /**
         * Request pause of the loop (will complete current workflow first)
         */
        async pauseLoop() {
            if (this.pauseRequested) {
                this.showToast('Pause already requested');
                return;
            }
            try {
                const response = await fetch('/api/loop/pause', { method: 'POST' });
                const data = await response.json();
                console.log('Pause loop response:', data);
                if (data.status === 'pause_requested') {
                    this.pauseRequested = true;
                    this.showToast('Pause requested - will stop after current workflow completes');
                } else if (data.status === 'already_paused') {
                    this.pauseRequested = true;
                }
            } catch (error) {
                console.error('Failed to pause loop:', error);
                this.showToast('Failed to pause loop');
            }
        },

        /**
         * Resume paused loop
         * Story 22.10 - Task 4: Resume functionality
         */
        async resumeLoop() {
            if (!this.isPaused) {
                this.showToast('Loop is not paused');
                return;
            }
            try {
                const response = await fetch('/api/loop/resume', { method: 'POST' });
                const data = await response.json();
                console.log('Resume loop response:', data);
                if (data.status === 'resumed') {
                    this.isPaused = false;
                    this.pauseRequested = false;
                    this.showToast('Resuming loop...');
                } else if (data.status === 'not_paused') {
                    this.isPaused = false;
                    this.pauseRequested = false;
                    this.showToast('Loop was not paused');
                } else if (data.status === 'not_running') {
                    this.showToast('Loop is not running');
                }
            } catch (error) {
                console.error('Failed to resume loop:', error);
                this.showToast('Failed to resume loop');
            }
        },

        /**
         * Stop the loop immediately
         */
        async stopLoop() {
            try {
                const response = await fetch('/api/loop/stop', { method: 'POST' });
                const data = await response.json();
                console.log('Stop loop response:', data);
                if (data.status === 'stopped') {
                    this.loopRunning = false;
                    this.pauseRequested = false;
                    this.isPaused = false;  // Story 22.10: Clear paused state on stop
                    // Story 22.11 Task 7.4: Update terminal status on stop
                    this.terminalStatus = 'stopped';
                    this.showToast('Loop stopped');
                }
            } catch (error) {
                console.error('Failed to stop loop:', error);
                this.showToast('Failed to stop loop');
            }
        },

        /**
         * Check current loop status
         */
        async checkLoopStatus() {
            try {
                const response = await fetch('/api/loop/status');
                const data = await response.json();
                this.loopRunning = data.running;
                // Story 22.10: Update paused state from status endpoint
                if (data.status === 'paused') {
                    this.isPaused = true;
                    this.pauseRequested = true;
                } else if (data.status === 'running') {
                    this.isPaused = false;
                }
                // Bug fix: Fetch current position when running to populate queue.current
                if (data.running) {
                    await this.fetchCurrentPosition();
                } else {
                    // Clear queue when not running
                    this.queue.current = null;
                }
            } catch (error) {
                console.error('Failed to check loop status:', error);
            }
        },

        /**
         * Fetch current execution position from state.yaml
         * Bug fix: Populate queue.current to show "Current task" in header
         */
        async fetchCurrentPosition() {
            try {
                const response = await fetch('/api/state');
                const data = await response.json();
                if (data.has_position && data.current_phase) {
                    // Parse story ID (e.g., "4.6" -> epic_num=4, story_num=6)
                    const storyParts = data.current_story?.split('.') || [];
                    const epicNum = storyParts[0] || data.current_epic;
                    const storyNum = storyParts[1] || '?';

                    // Convert phase from snake_case to display name
                    const phaseDisplayNames = {
                        'create_story': 'Create Story',
                        'validate_story': 'Validate Story',
                        'validate_story_synthesis': 'Validate Synthesis',
                        'dev_story': 'Develop Story',
                        'code_review': 'Code Review',
                        'code_review_synthesis': 'Review Synthesis',
                        'retrospective': 'Retrospective',
                        'qa_plan_generate': 'QA Plan',
                        'qa_plan_execute': 'QA Execute'
                    };
                    const workflow = phaseDisplayNames[data.current_phase] || data.current_phase;

                    this.queue.current = {
                        workflow: workflow,
                        epic_num: epicNum,
                        story_num: storyNum,
                        progress: 0  // Progress is tracked separately via SSE
                    };
                } else {
                    this.queue.current = null;
                }
            } catch (error) {
                console.error('Failed to fetch current position:', error);
            }
        },

        /**
         * Run a specific workflow (called from context menu actions)
         * @param {string} workflow - Workflow name
         * @param {number} epicNum - Epic number
         * @param {number} storyNum - Story number
         */
        async runWorkflow(workflow, epicNum, storyNum) {
            // Start the bmad-assist loop - it reads sprint-status.yaml to find current position
            if (this.loopRunning) {
                this.showToast('Loop is already running');
                return;
            }

            try {
                const res = await fetch('/api/loop/start', { method: 'POST' });
                const data = await res.json();
                if (data.status === 'started') {
                    this.showToast('Starting bmad-assist run loop...');
                } else {
                    this.showToast(data.message || 'Failed to start loop');
                }
            } catch (err) {
                console.error('Failed to start loop:', err);
                this.showToast('Failed to start loop');
            }
        }
    };
};
