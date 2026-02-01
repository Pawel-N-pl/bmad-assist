/**
 * SSE connection component for real-time event streaming
 * Handles Server-Sent Events connection, reconnection, and event processing
 */

window.sseConnectionComponent = function() {
    return {
        // Connection state
        connected: false,
        eventSource: null,

        // Story 22.9: Dashboard event processing
        dashboardEventState: {
            currentRunId: null,
            lastSequenceId: 0,
            processedEvents: new Set(),
            eventBuffer: {},
        },

        // Reconnect state
        _sseReconnectDelay: 1000,
        _wasConnected: false,

        // Self-reload timestamp for detecting external vs self-initiated config reloads (Story 17.9)
        SELF_RELOAD_WINDOW_MS: 2000,

        /**
         * Connect to SSE endpoint
         */
        connectSSE() {
            if (this.eventSource) {
                this.eventSource.close();
            }

            this.eventSource = new EventSource('/sse/output');

            this.eventSource.onopen = () => {
                this.connected = true;
                // Story 22.9: Reset reconnect delay on successful connection
                this._sseReconnectDelay = 1000;
                console.log('SSE connected');
                // Story 22.9: Resync state after reconnect (fetch fresh tree data)
                if (this._wasConnected) {
                    console.log('SSE reconnected, resyncing state...');
                    this.fetchStories();
                }
                this._wasConnected = true;
            };

            this.eventSource.onerror = () => {
                this.connected = false;
                // Story 22.11 Task 2: Check readyState to distinguish EOF from temporary errors
                // readyState: 0=connecting, 1=open, 2=closed
                if (this.eventSource.readyState === 2) {
                    // Normal EOF (subprocess exited)
                    console.debug('SSE EOF (normal subprocess exit)');
                    // Story 22.11 Task 3: Update terminal status on EOF
                    this.terminalStatus = 'complete';
                    // Don't reconnect on normal EOF - wait for user action or new workflow
                    return;
                }
                // Temporary error - reconnect with exponential backoff
                console.debug('SSE error (reconnecting)');
                // Story 22.11 Task 7.4: Mark terminal as stopped on error
                this.terminalStatus = 'stopped';
                if (!this._sseReconnectDelay) {
                    this._sseReconnectDelay = 1000; // Start with 1s
                } else {
                    this._sseReconnectDelay = Math.min(this._sseReconnectDelay * 2, 8000); // Max 8s
                }
                setTimeout(() => this.connectSSE(), this._sseReconnectDelay);
            };

            // Output event - terminal lines
            this.eventSource.addEventListener('output', (e) => {
                const data = JSON.parse(e.data);
                this.addOutput(data);
            });

            // Status event - connection status
            this.eventSource.addEventListener('status', (e) => {
                const data = JSON.parse(e.data);
                if (data.connected) {
                    this.connected = true;
                }
            });

            // Heartbeat event - keep-alive
            this.eventSource.addEventListener('heartbeat', (e) => {
                // Keep-alive received
            });

            // Story 17.4 AC8 + Story 17.9 AC2/AC3: Handle config_reloaded SSE event
            this.eventSource.addEventListener('config_reloaded', (e) => {
                // Story 17.9 AC3: Skip notification if this is a self-reload (within detection window)
                if (this._selfReloadTimestamp && (Date.now() - this._selfReloadTimestamp) < this.SELF_RELOAD_WINDOW_MS) {
                    return;
                }

                // Story 17.9 AC2: External reload detected - show toast notification
                this.showToast('Configuration was reloaded externally.');

                // Set staleData flag if settings panel is open (defensive check)
                if (this.settingsView && this.settingsView.open) {
                    this.settingsView.staleData = true;
                }
            });

            // Story 22.9: Handle workflow_status SSE event (phase transitions)
            this.eventSource.addEventListener('workflow_status', (e) => {
                this._handleDashboardEvent(e, 'workflow_status');
            });

            // Story 22.9: Handle story_status SSE event (story status changes)
            this.eventSource.addEventListener('story_status', (e) => {
                this._handleDashboardEvent(e, 'story_status');
            });

            // Story 22.9: Handle story_transition SSE event (story started/completed)
            this.eventSource.addEventListener('story_transition', (e) => {
                this._handleDashboardEvent(e, 'story_transition');
            });

            // Story 22.10: Handle LOOP_PAUSED event (emitted by subprocess)
            this.eventSource.addEventListener('LOOP_PAUSED', (e) => {
                const data = JSON.parse(e.data);
                this.isPaused = true;
                this.pauseRequested = true;
                console.log('Loop paused at phase:', data.data?.current_phase);
            });

            // Story 22.10: Handle LOOP_RESUMED event (emitted by subprocess)
            this.eventSource.addEventListener('LOOP_RESUMED', (e) => {
                this.isPaused = false;
                this.pauseRequested = false;
                console.log('Loop resumed');
            });

            // Story 22.9: Handle loop_status SSE event
            this.eventSource.addEventListener('loop_status', (e) => {
                const data = JSON.parse(e.data);
                this.loopRunning = data.running;
                if (data.status === 'paused') {
                    this.isPaused = true;
                    this.pauseRequested = true;
                } else if (data.status === 'running') {
                    this.isPaused = false;
                    this.terminalStatus = 'running';
                } else if (data.status === 'stopped') {
                    this.terminalStatus = 'stopped';
                    // Bug fix: Clear queue.current when loop stops
                    this.queue.current = null;
                }
            });

            // Story 22.11 Task 7: Handle validator_progress SSE event
            this.eventSource.addEventListener('validator_progress', (e) => {
                const data = JSON.parse(e.data);
                this._handleValidatorProgress(data);
            });

            // Story 22.11 Task 7: Handle phase_complete SSE event
            this.eventSource.addEventListener('phase_complete', (e) => {
                const data = JSON.parse(e.data);
                this._handlePhaseComplete(data);
            });
        },

        /**
         * Handle dashboard events with deduplication and ordering
         * Story 22.9: Process events with sequence IDs for ordering
         * @param {Event} e - SSE event
         * @param {string} eventType - Event type name
         */
        _handleDashboardEvent(e, eventType) {
            const data = JSON.parse(e.data);

            // Check for run_id to track current run
            if (data.run_id) {
                if (this.dashboardEventState.currentRunId !== data.run_id) {
                    // New run - reset state
                    this.dashboardEventState.currentRunId = data.run_id;
                    this.dashboardEventState.lastSequenceId = 0;
                    this.dashboardEventState.processedEvents.clear();
                    this.dashboardEventState.eventBuffer = {};
                }
            }

            // Create unique event ID for deduplication (use simpler key without full JSON)
            const eventId = `${eventType}-${data.sequence_id || Date.now()}-${data.run_id || ''}`;
            if (this.dashboardEventState.processedEvents.has(eventId)) {
                return; // Already processed
            }
            this.dashboardEventState.processedEvents.add(eventId);

            // Prevent unbounded growth - evict oldest entries when Set exceeds 1000
            if (this.dashboardEventState.processedEvents.size > 1000) {
                const entries = Array.from(this.dashboardEventState.processedEvents);
                this.dashboardEventState.processedEvents = new Set(entries.slice(-500));
            }

            // Process event based on type
            switch (eventType) {
                case 'workflow_status':
                    this._updateStoryPhase(data);
                    // Bug fix: Update queue.current with current phase info
                    this._updateQueueCurrent(data);
                    break;
                case 'story_status':
                    this._updateStoryStatus(data);
                    break;
                case 'story_transition':
                    this._updateStoryTransition(data);
                    // Bug fix: Update queue.current on story transitions
                    this._updateQueueCurrent(data);
                    break;
            }

            // Re-render icons after state change
            this.$nextTick(() => this.refreshIcons());
        },

        /**
         * Update queue.current from SSE event data
         * Bug fix: Populate queue.current to show current task in header
         * @param {Object} eventData - SSE event data with nested data field
         */
        _updateQueueCurrent(eventData) {
            const data = eventData.data || eventData;

            // Extract story info from event
            const storyId = data.current_story || data.story_id;
            if (!storyId) return;

            const parts = storyId.split('.');
            const epicNum = parts[0] || data.epic_num;
            const storyNum = parts[1] || data.story_num;
            const phase = data.current_phase || data.phase;

            if (!phase) return;

            // Convert phase from snake_case to display name
            const phaseDisplayNames = {
                'create_story': 'Create Story',
                'CREATE_STORY': 'Create Story',
                'validate_story': 'Validate Story',
                'VALIDATE_STORY': 'Validate Story',
                'validate_story_synthesis': 'Validate Synthesis',
                'VALIDATE_STORY_SYNTHESIS': 'Validate Synthesis',
                'dev_story': 'Develop Story',
                'DEV_STORY': 'Develop Story',
                'code_review': 'Code Review',
                'CODE_REVIEW': 'Code Review',
                'code_review_synthesis': 'Review Synthesis',
                'CODE_REVIEW_SYNTHESIS': 'Review Synthesis',
                'retrospective': 'Retrospective',
                'RETROSPECTIVE': 'Retrospective',
                'qa_plan_generate': 'QA Plan',
                'QA_PLAN_GENERATE': 'QA Plan',
                'qa_plan_execute': 'QA Execute',
                'QA_PLAN_EXECUTE': 'QA Execute'
            };
            const workflow = phaseDisplayNames[phase] || phase;

            // Update queue.current
            this.queue.current = {
                workflow: workflow,
                epic_num: epicNum,
                story_num: storyNum,
                progress: this.queue.current?.progress || 0
            };
        }
    };
};
