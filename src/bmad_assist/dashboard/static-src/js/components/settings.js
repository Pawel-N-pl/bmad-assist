/**
 * Settings component for configuration management
 * Handles settings panel, config editing, validation, backups, Playwright status, and import/export
 */

window.settingsComponent = function() {
    return {
        // Settings view state (Story 17.4)
        settingsView: {
            open: false,           // Panel visibility
            scope: 'project',      // 'global' | 'project'
            activeTab: 'testing',  // 'testing' | 'benchmarking' | 'providers'
            loading: false,
            error: null,
            hasChanges: false,     // Enable/disable Apply button
            applying: false,       // Loading state for Apply button
            staleData: false       // Set true when SSE config_reloaded received while open
        },

        // Backups view state (Story 17.10)
        backupsView: {
            expanded: false,       // Collapsible section toggle
            loading: false,        // Loading state for backup list
            globalBackups: [],     // Global config backups
            projectBackups: [],    // Project config backups
            restoring: false,      // Restore operation in progress
            viewing: null          // Backup being viewed (null or {scope, version})
        },

        configData: {},            // Current config values with provenance
        globalConfigData: {},      // Global config for "Reset to global" functionality in project scope (Story 17.8)
        configSchema: null,        // Schema from /api/config/schema (fetched once, cached)
        pendingUpdates: [],        // Track changes before Apply (populated by Stories 17.5-17.7)
        validationErrors: {},      // Keyed by path, e.g., { 'testarch.playwright.timeout': 'Must be between...' }

        // Playwright status state (Story 17.11)
        playwrightStatus: {
            loading: false,
            data: null,      // Response from /api/playwright/status
            error: null,     // Error message if fetch failed
            lastFetch: 0,    // Timestamp of last successful fetch
            showCommands: false,  // Toggle for install commands section
        },
        // Debounce threshold (30 seconds)
        PLAYWRIGHT_STATUS_CACHE_MS: 30000,

        // Config Export/Import state (Story 17.12)
        exportView: {
            loading: false,
            dropdownOpen: false,
        },
        importView: {
            loading: false,
            modalOpen: false,
            filename: '',
            scope: 'project',   // Target scope for import
            diff: null,         // {added: {}, modified: {}, removed: []}
            riskyFields: [],    // Fields requiring confirmation
            errors: null,       // Validation errors or error string
            content: '',        // Raw YAML content (stored for scope switching)
        },

        // Self-reload timestamp for detecting external vs self-initiated config reloads (Story 17.9)
        _selfReloadTimestamp: 0,

        // ==========================================
        // Settings Panel Methods (Story 17.4)
        // ==========================================

        /**
         * Open settings panel and load config data
         * Story 17.11 AC6: Fetch Playwright status if testing tab is active
         */
        openSettings() {
            this.settingsView.open = true;
            this.settingsView.loading = true;
            this.settingsView.error = null;
            this.settingsView.staleData = false;

            Promise.all([
                this.fetchSchema(),
                this.fetchConfig()
            ]).finally(() => {
                this.settingsView.loading = false;
                // Story 17.11 AC6: Fetch Playwright status if testing tab is active
                if (this.settingsView.activeTab === 'testing') {
                    this.fetchPlaywrightStatus();
                }
                this.$nextTick(() => {
                    this.refreshIcons();
                    // Focus close button on open (AC1)
                    if (this.$refs.settingsCloseBtn) {
                        this.$refs.settingsCloseBtn.focus();
                    }
                });
            });
        },

        /**
         * Close settings panel with unsaved changes warning
         */
        closeSettings() {
            if (this.settingsView.hasChanges) {
                if (!confirm('You have unsaved changes. Discard and close?')) {
                    return;
                }
            }
            this.settingsView.open = false;
            this.settingsView.staleData = false;
            this.pendingUpdates = [];
            this.validationErrors = {};
            this.settingsView.hasChanges = false;
            // Return focus to Settings button (AC1)
            this.$nextTick(() => {
                if (this.$refs.settingsBtn) {
                    this.$refs.settingsBtn.focus();
                }
            });
        },

        /**
         * Toggle scope between global and project
         */
        toggleScope(newScope) {
            if (newScope === this.settingsView.scope) return;

            if (this.settingsView.hasChanges) {
                if (!confirm('You have unsaved changes. Switching scope will discard them. Continue?')) {
                    return;
                }
            }

            this.settingsView.scope = newScope;
            this.pendingUpdates = [];
            this.validationErrors = {};
            this.settingsView.hasChanges = false;
            this.settingsView.staleData = false;
            this.settingsView.loading = true;
            this.settingsView.error = null;

            this.fetchConfig().finally(() => {
                this.settingsView.loading = false;
                this.$nextTick(() => this.refreshIcons());
            });
        },

        /**
         * Switch active settings tab
         * Story 17.11 AC6: Fetch Playwright status when switching to testing tab
         */
        setSettingsTab(tab) {
            this.settingsView.activeTab = tab;
            // Fetch Playwright status when switching to testing tab
            if (tab === 'testing') {
                this.fetchPlaywrightStatus();
            }
            this.$nextTick(() => this.refreshIcons());
        },

        /**
         * Fetch config schema (once, cached)
         */
        async fetchSchema() {
            // Skip if already cached
            if (this.configSchema) return;

            try {
                const res = await fetch('/api/config/schema');
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                this.configSchema = await res.json();
            } catch (err) {
                console.error('Failed to fetch config schema:', err);
                // Schema fetch failure is non-critical, just log it
            }
        },

        /**
         * Fetch config data based on current scope (AC2)
         * Story 17.8: Also fetch global config when in project scope for "Reset to global" functionality
         */
        async fetchConfig() {
            try {
                this.settingsView.error = null;
                const scope = this.settingsView.scope;

                if (scope === 'project') {
                    // Story 17.8 AC7: Fetch both project and global configs in parallel
                    // Global config needed for "Reset to global" functionality
                    const [projectRes, globalRes] = await Promise.all([
                        fetch('/api/config/project'),
                        fetch('/api/config/global')
                    ]);
                    if (!projectRes.ok) {
                        throw new Error(`HTTP ${projectRes.status}`);
                    }
                    if (!globalRes.ok) {
                        throw new Error(`HTTP ${globalRes.status}`);
                    }
                    this.configData = await projectRes.json();
                    this.globalConfigData = await globalRes.json();
                } else {
                    // Global scope - only need global config
                    const res = await fetch('/api/config/global');
                    if (!res.ok) {
                        throw new Error(`HTTP ${res.status}`);
                    }
                    this.configData = await res.json();
                    this.globalConfigData = {};  // Not needed in global scope
                }
            } catch (err) {
                console.error('Failed to fetch config:', err);
                this.settingsView.error = 'Failed to load configuration';
            }
        },

        /**
         * Retry fetching config after error
         */
        retryFetchConfig() {
            this.settingsView.loading = true;
            this.settingsView.error = null;
            Promise.all([
                this.fetchSchema(),
                this.fetchConfig()
            ]).finally(() => {
                this.settingsView.loading = false;
                this.$nextTick(() => this.refreshIcons());
            });
        },

        /**
         * Reload config data (for stale data warning)
         */
        reloadConfigData() {
            if (this.settingsView.hasChanges) {
                if (!confirm('Reloading will discard your unsaved changes.')) {
                    return;
                }
            }
            this.pendingUpdates = [];
            this.validationErrors = {};
            this.settingsView.hasChanges = false;
            this.settingsView.staleData = false;
            this.settingsView.loading = true;
            this.fetchConfig().finally(() => {
                this.settingsView.loading = false;
                this.$nextTick(() => this.refreshIcons());
            });
        },

        /**
         * Apply config changes: save then reload
         * Handles 428 Precondition Required for RISKY fields (AC5)
         */
        async applyConfig() {
            if (!this.settingsView.hasChanges || this.settingsView.applying) {
                return;
            }

            this.settingsView.applying = true;

            try {
                // Step 1: Save changes to appropriate scope
                const scope = this.settingsView.scope;
                const endpoint = scope === 'global' ? '/api/config/global' : '/api/config/project';

                const saveRes = await fetch(endpoint, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ updates: this.pendingUpdates })
                });

                // Handle 428 Precondition Required (RISKY fields) - Story 17.6 AC5
                if (saveRes.status === 428) {
                    const data = await saveRes.json().catch(() => ({}));
                    const riskyFields = data.risky_fields || [];
                    console.log('RISKY fields requiring confirmation:', riskyFields);

                    // Show confirmation dialog
                    const confirmed = confirm(
                        `The following settings require confirmation:\n\n` +
                        `• ${riskyFields.join('\n• ')}\n\n` +
                        `Modifying these could affect workflow behavior. Continue?`
                    );

                    if (!confirmed) {
                        // User cancelled - keep pendingUpdates, reset applying state
                        this.settingsView.applying = false;
                        return;
                    }

                    // Retry with confirmed: true
                    const retryRes = await fetch(endpoint, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ updates: this.pendingUpdates, confirmed: true })
                    });

                    if (retryRes.status === 428) {
                        // Unexpected second 428
                        this.showToast('Unexpected error - please try again');
                        this.settingsView.applying = false;
                        return;
                    }

                    if (!retryRes.ok) {
                        const errData = await retryRes.json().catch(() => ({}));
                        throw new Error(errData.error || `Save failed after confirmation: HTTP ${retryRes.status}`);
                    }
                } else if (saveRes.status === 422) {
                    // Story 17.10 AC1/AC2: Handle Pydantic validation errors
                    const data = await saveRes.json().catch(() => ({}));
                    this.parseValidationErrors(data);
                    // Show toast with error count
                    const errorCount = Object.keys(this.validationErrors).length;
                    const errorWord = errorCount === 1 ? 'error' : 'errors';
                    this.showToast(`Validation failed: ${errorCount} field ${errorWord}`);
                    this.settingsView.applying = false;
                    return;
                } else if (!saveRes.ok) {
                    const errData = await saveRes.json().catch(() => ({}));
                    throw new Error(errData.message || errData.error || `Save failed: HTTP ${saveRes.status}`);
                }

                // Step 2: Reload config singleton
                // Story 17.9 AC3: Set timestamp immediately before reload to minimize race window
                this._selfReloadTimestamp = Date.now();
                const reloadRes = await fetch('/api/config/reload', {
                    method: 'POST'
                });

                if (!reloadRes.ok) {
                    // Config saved but reload failed - still show success but warn
                    this.showToast('Configuration saved but reload failed. Restart may be required.');
                } else {
                    this.showToast('Config reloaded.');
                }

                // Clear pending changes and validation errors
                this.pendingUpdates = [];
                this.validationErrors = {};
                this.settingsView.hasChanges = false;
                this.settingsView.staleData = false;

                // Refresh config data
                await this.fetchConfig();

            } catch (err) {
                console.error('Failed to apply config:', err);
                // Story 17.10 AC3: Differentiate error types for better user feedback
                let errorMessage;
                if (err.name === 'TypeError' && err.message.includes('fetch')) {
                    // Network error (no connectivity, DNS failure, etc.)
                    errorMessage = 'Network error. Check your connection and try again.';
                } else if (err.name === 'AbortError') {
                    // Request was aborted (timeout)
                    errorMessage = 'Request timed out. Server may be busy.';
                } else if (err.message.includes('500')) {
                    // Server error
                    errorMessage = 'Server error. Please try again later.';
                } else {
                    // Other errors (validation, config, etc.)
                    errorMessage = err.message || 'Failed to save configuration';
                }
                this.showToast(errorMessage);
            } finally {
                this.settingsView.applying = false;
            }
        },

        /**
         * Handle Escape key to close settings
         */
        handleSettingsEscape(event) {
            if (this.settingsView.open && event.key === 'Escape') {
                // Don't close if a modal is open
                if (this.contentModal.show || this.reportModal.show) {
                    return;
                }
                event.preventDefault();
                this.closeSettings();
            }
        },

        // ==========================================
        // Settings Helper Methods (Story 17.5)
        // ==========================================

        /**
         * Safe nested property access for config data
         * @param {object} obj - Object to access
         * @param {string} path - Dot-separated path (e.g., 'testarch.playwright.browsers')
         * @returns {any} Value at path or undefined
         */
        getNestedValue(obj, path) {
            return path.split('.').reduce((o, k) => o?.[k], obj);
        },

        /**
         * Get field value (pending or from config)
         * @param {string} path - Config path (e.g., 'testarch.playwright.browsers')
         * @returns {any} Pending value if exists, otherwise config value
         */
        getFieldValue(path) {
            const pending = this.pendingUpdates.find(u => u.path === path);
            if (pending !== undefined) return pending.value;
            return this.getNestedValue(this.configData, path + '.value');
        },

        /**
         * Get field provenance source
         * @param {string} path - Config path
         * @returns {string} Source: 'default', 'global', or 'project'
         */
        getFieldSource(path) {
            return this.getNestedValue(this.configData, path + '.source') || 'default';
        },

        /**
         * Array equality helper for browser selection comparison
         * @param {array} a - First array
         * @param {array} b - Second array
         * @returns {boolean} True if arrays contain same elements (order-independent)
         */
        arraysEqual(a, b) {
            if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
            const sortedA = [...a].sort();
            const sortedB = [...b].sort();
            return sortedA.every((val, i) => val === sortedB[i]);
        },

        /**
         * Add or update pending change with reversion detection
         * @param {string} path - Config path
         * @param {any} value - New value
         */
        addPendingUpdate(path, value) {
            const originalValue = this.getNestedValue(this.configData, path + '.value');
            const isEqual = Array.isArray(value)
                ? this.arraysEqual(value, originalValue)
                : value === originalValue;

            const idx = this.pendingUpdates.findIndex(u => u.path === path);

            if (isEqual) {
                // Value reverted to original - remove from pending
                if (idx >= 0) this.pendingUpdates.splice(idx, 1);
            } else {
                // Value changed - add/update pending
                if (idx >= 0) {
                    this.pendingUpdates[idx].value = value;
                } else {
                    this.pendingUpdates.push({ path, value });
                }
            }
            this.settingsView.hasChanges = this.pendingUpdates.length > 0;
        },

        /**
         * Check if Apply should be disabled due to validation errors
         * @returns {boolean} True if any validation errors exist
         */
        hasValidationErrors() {
            return Object.keys(this.validationErrors).length > 0;
        },

        /**
         * Validate and update a numeric field
         * @param {string} path - Config path
         * @param {string|number} value - Input value
         * @param {number} min - Minimum allowed value
         * @param {number} max - Maximum allowed value
         */
        validateAndUpdateNumber(path, value, min, max) {
            // Handle empty input - clear error and don't add to pending
            if (value === '' || value === null || value === undefined) {
                delete this.validationErrors[path];
                return;
            }

            const num = parseInt(value, 10);

            // Handle non-numeric input
            if (isNaN(num)) {
                this.validationErrors[path] = 'Must be a valid number';
                return;
            }

            // Store validation error in validationErrors object
            if (num < min || num > max) {
                this.validationErrors[path] = `Must be between ${min.toLocaleString()} and ${max.toLocaleString()}`;
            } else {
                delete this.validationErrors[path];
                this.addPendingUpdate(path, num);
            }
        },

        /**
         * Toggle a browser in the browsers array
         * @param {string} browser - Browser name ('chromium', 'firefox', 'webkit')
         */
        toggleBrowser(browser) {
            const path = 'testarch.playwright.browsers';
            const current = this.getFieldValue(path) || [];
            const browsers = Array.isArray(current) ? [...current] : [];
            const idx = browsers.indexOf(browser);
            if (idx >= 0) {
                browsers.splice(idx, 1);
            } else {
                browsers.push(browser);
            }
            this.addPendingUpdate(path, browsers);
        },

        /**
         * Check if a browser is selected
         * @param {string} browser - Browser name
         * @returns {boolean} True if browser is in the browsers array
         */
        isBrowserSelected(browser) {
            const browsers = this.getFieldValue('testarch.playwright.browsers') || ['chromium'];
            return Array.isArray(browsers) && browsers.includes(browser);
        },

        /**
         * Check if playwright config exists in configData
         * @returns {boolean} True if testarch.playwright exists
         */
        hasPlaywrightConfig() {
            return this.getNestedValue(this.configData, 'testarch.playwright') != null;
        },

        /**
         * Check if benchmarking config exists in configData
         * @returns {boolean} True if benchmarking exists
         */
        hasBenchmarkingConfig() {
            return this.getNestedValue(this.configData, 'benchmarking') != null;
        },

        // ==========================================
        // Providers Settings Helper Methods (Story 17.7)
        // ==========================================

        /**
         * Check if providers config exists in configData
         * @returns {boolean} True if providers.master exists
         */
        hasProvidersConfig() {
            return this.getNestedValue(this.configData, 'providers.master') != null;
        },

        /**
         * Get master provider field value using established getFieldValue() helper
         * @param {string} field - Field name (e.g., 'provider', 'model', 'model_name')
         * @returns {any} Pending value if exists, otherwise config value
         */
        getMasterField(field) {
            return this.getFieldValue(`providers.master.${field}`);
        },

        /**
         * Get master provider field source using established getFieldSource() helper
         * @param {string} field - Field name
         * @returns {string} Source: 'default', 'global', or 'project'
         */
        getMasterFieldSource(field) {
            return this.getFieldSource(`providers.master.${field}`);
        },

        /**
         * Get multi validators array (handles null/undefined/empty gracefully)
         * The API returns multi as {"value": [...], "source": "..."} so we access .value
         * @returns {Array} Array of raw multi validator objects (no provenance wrapper per field)
         */
        getMultiValidators() {
            const multiWrapper = this.getNestedValue(this.configData, 'providers.multi');
            // Multi is wrapped: {"value": [...], "source": "..."}
            const items = multiWrapper?.value;
            return Array.isArray(items) ? items : [];
        },

        /**
         * Get provenance source for the entire multi validators array
         * @returns {string} Source: 'default', 'global', or 'project'
         */
        getMultiValidatorsSource() {
            const multiWrapper = this.getNestedValue(this.configData, 'providers.multi');
            return multiWrapper?.source || 'default';
        },

        /**
         * Get multi validator display name: model_name if set, else model, else 'Unknown'
         * Note: Multi validators are raw objects (not wrapped in provenance per field)
         * @param {object} validator - Validator object (raw, e.g., {provider: "claude", model: "sonnet", ...})
         * @returns {string} Display name for the validator
         */
        getMultiDisplayName(validator) {
            // Raw validator objects, not wrapped in provenance per field
            // Use explicit null/undefined/empty-string check to distinguish unset from cleared
            const modelName = validator?.model_name;
            if (modelName !== null && modelName !== undefined && modelName !== '') {
                return modelName;
            }
            return validator?.model || 'Unknown';
        },

        // Phase Models helpers
        getPhaseModels() {
            return this.getNestedValue(this.configData, 'phase_models') || {};
        },

        getPhaseModelNames() {
            return Object.keys(this.getPhaseModels());
        },

        isMultiLLMPhase(phaseName) {
            const phase = this.getPhaseModels()[phaseName];
            // Multi-LLM phases are wrapped: {value: [...], source: "..."}
            return Array.isArray(phase?.value);
        },

        getPhaseMultiProviders(phaseName) {
            const phase = this.getPhaseModels()[phaseName];
            return Array.isArray(phase?.value) ? phase.value : [];
        },

        getPhaseSingleProvider(phaseName) {
            const phase = this.getPhaseModels()[phaseName];
            // Single-LLM: {provider: {value: "...", source: "..."}, model: {value: "...", source: "..."}}
            if (phase && !Array.isArray(phase?.value)) {
                return {
                    provider: phase?.provider?.value || 'Unknown',
                    model: phase?.model?.value || 'Unknown',
                    model_name: phase?.model_name?.value || null
                };
            }
            return null;
        },

        getPhaseSource(phaseName) {
            const phase = this.getPhaseModels()[phaseName];
            if (Array.isArray(phase?.value)) {
                return phase.source || 'default';
            }
            // Single-LLM: check provider field source
            return phase?.provider?.source || 'default';
        },

        formatPhaseName(name) {
            // "validate_story" → "Validate Story"
            return name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        },

        /**
         * Validate dropdown/text field (required non-empty)
         * Consolidated method for both benchmarking and provider fields
         * @param {string} path - Config path
         * @param {string} value - Input value
         */
        validateDropdownField(path, value) {
            const trimmed = value?.trim() || '';
            if (!trimmed) {
                // Map paths to exact AC-required labels
                const labelMap = {
                    'benchmarking.extraction_provider': 'Provider',
                    'benchmarking.extraction_model': 'Model',
                    'providers.master.provider': 'Provider',
                    'providers.master.model': 'Model'
                };
                const fieldName = labelMap[path] || path.split('.').pop().replace(/_/g, ' ');
                const label = fieldName.charAt(0).toUpperCase() + fieldName.slice(1);
                this.validationErrors[path] = `${label} is required`;
            } else {
                delete this.validationErrors[path];
            }
        },

        // ==========================================
        // Inheritance Indicator Methods (Story 17.8)
        // ==========================================

        /**
         * Hardcoded default values for config fields (fallback when schema doesn't include defaults)
         * Story 17.8 AC6: Complete list of all config paths with reset buttons
         */
        CONFIG_DEFAULTS: {
            // Testing tab (4 fields)
            'testarch.playwright.browsers': ['chromium'],
            'testarch.playwright.headless': true,
            'testarch.playwright.timeout': 30000,
            'testarch.playwright.workers': 1,
            // Benchmarking tab (3 fields)
            'benchmarking.enabled': true,
            'benchmarking.extraction_provider': 'claude',
            'benchmarking.extraction_model': 'haiku',
            // Providers tab - Master (3 fields)
            'providers.master.provider': 'claude',
            'providers.master.model': 'opus',
            'providers.master.model_name': null  // null is valid default (optional field)
        },

        /**
         * Get default value for a config path from schema or hardcoded fallback
         * Story 17.8 AC6
         * @param {string} path - Config path (e.g., 'testarch.playwright.timeout')
         * @returns {any} Default value or undefined if not found
         */
        getDefaultValue(path) {
            // Try schema first
            if (this.configSchema) {
                const parts = path.split('.');
                let schema = this.configSchema;
                for (const part of parts) {
                    schema = schema?.properties?.[part];
                    if (!schema) break;
                }
                if (schema?.default !== undefined) {
                    return schema.default;
                }
            }
            // Fallback to hardcoded defaults
            if (this.CONFIG_DEFAULTS[path] !== undefined) {
                return this.CONFIG_DEFAULTS[path];
            }
            // No default available - log warning
            console.warn('No default value found for:', path);
            return undefined;
        },

        /**
         * Get global value for a config path (for "Reset to global" in project scope)
         * Story 17.8 AC7
         * @param {string} path - Config path
         * @returns {any} Global config value or undefined
         */
        getGlobalValue(path) {
            return this.getNestedValue(this.globalConfigData, path + '.value');
        },

        /**
         * Check if field can be reset to default (has non-default value AND default is known)
         * Story 17.8 AC2
         * @param {string} path - Config path
         * @returns {boolean} True if reset to default is available
         */
        canResetToDefault(path) {
            const source = this.getFieldSource(path);
            const defaultVal = this.getDefaultValue(path);
            // Can reset if source is not 'default' and we know what the default is
            return source !== 'default' && defaultVal !== undefined;
        },

        /**
         * Check if field can be reset to global (project scope with project override)
         * Story 17.8 AC3
         * @param {string} path - Config path
         * @returns {boolean} True if reset to global is available
         */
        canResetToGlobal(path) {
            // Only available in project scope when the field has a project-level override
            return this.settingsView.scope === 'project' &&
                   this.getFieldSource(path) === 'project';
        },

        /**
         * Check if field has a project-level override (for visual indicator)
         * Story 17.8 AC1
         * @param {string} path - Config path
         * @returns {boolean} True if field has project override in project scope
         */
        hasProjectOverride(path) {
            return this.settingsView.scope === 'project' &&
                   this.getFieldSource(path) === 'project';
        },

        /**
         * Format a value for display in confirmation dialogs
         * @param {any} val - Value to format
         * @returns {string} Formatted display string
         */
        formatValueForDisplay(val) {
            if (val === null || val === undefined) {
                return 'none';
            }
            if (Array.isArray(val)) {
                return val.length > 0 ? val.join(', ') : 'empty';
            }
            if (typeof val === 'boolean') {
                return val ? 'enabled' : 'disabled';
            }
            return String(val);
        },

        /**
         * Reset field to default value
         * Story 17.8 AC2
         * @param {string} path - Config path
         * @param {string} fieldName - Human-readable field name for confirmation dialog
         */
        resetToDefault(path, fieldName) {
            const defaultVal = this.getDefaultValue(path);
            if (defaultVal === undefined) {
                console.error('Cannot reset - no default value for:', path);
                return;
            }

            const displayVal = this.formatValueForDisplay(defaultVal);
            if (!confirm(`Reset ${fieldName} to default value (${displayVal})?`)) {
                return;
            }

            // null signals "delete this field from config" to backend
            // This causes the field to inherit from the next level (global or Pydantic default)
            this.addPendingUpdate(path, null);
        },

        /**
         * Reset field to global value (removes project override)
         * Story 17.8 AC3
         * @param {string} path - Config path
         * @param {string} fieldName - Human-readable field name for confirmation dialog
         */
        resetToGlobal(path, fieldName) {
            const globalVal = this.getGlobalValue(path);
            const defaultVal = this.getDefaultValue(path);
            const targetVal = globalVal !== undefined ? globalVal : defaultVal;
            const displayVal = this.formatValueForDisplay(targetVal);

            const targetSource = globalVal !== undefined ? 'global' : 'default';
            if (!confirm(`Reset ${fieldName} to ${targetSource} value (${displayVal})?`)) {
                return;
            }

            // null signals "delete this field from project config"
            // Field will then inherit from global (or default if no global)
            this.addPendingUpdate(path, null);
        },

        // ==========================================
        // Validation Error Handling Methods (Story 17.10)
        // ==========================================

        /**
         * Parse validation errors from 422 response into field-level errors
         * Story 17.10 AC1/AC2: Converts backend validation error format to per-field display format
         *
         * Backend format:
         * {
         *   "error": "validation_failed",
         *   "details": [
         *     {"loc": ["testarch", "playwright", "timeout"], "msg": "Input should be...", "type": "..."}
         *   ]
         * }
         *
         * Output format (stored in this.validationErrors):
         * {
         *   "testarch.playwright.timeout": "Input should be..."
         * }
         *
         * @param {object} responseData - Parsed JSON from 422 response
         */
        parseValidationErrors(responseData) {
            // Clear any existing validation errors
            this.validationErrors = {};

            const details = responseData?.details;
            if (!Array.isArray(details) || details.length === 0) {
                return;
            }

            for (const err of details) {
                // Convert loc array to dot-notation path
                // e.g., ["testarch", "playwright", "timeout"] -> "testarch.playwright.timeout"
                const loc = err.loc;
                if (!Array.isArray(loc) || loc.length === 0) {
                    continue;
                }
                const path = loc.map(String).join('.');
                const msg = err.msg || 'Validation error';

                // Store in validationErrors keyed by path
                this.validationErrors[path] = msg;
            }
        },

        /**
         * Clear all validation errors (used when successfully saving or resetting form)
         * Story 17.10 AC2
         */
        clearValidationErrors() {
            this.validationErrors = {};
        },

        /**
         * Get validation error message for a specific field path
         * Story 17.10 AC2: Returns error message if field has validation error
         * @param {string} path - Config path (e.g., 'testarch.playwright.timeout')
         * @returns {string|null} Error message or null if no error
         */
        getValidationError(path) {
            return this.validationErrors[path] || null;
        },

        /**
         * Check if a specific field has a validation error
         * Story 17.10 AC2: For conditional styling of input fields
         * @param {string} path - Config path
         * @returns {boolean} True if field has validation error
         */
        hasFieldError(path) {
            return !!this.validationErrors[path];
        },

        // ==========================================
        // Backup Management Methods (Story 17.10)
        // ==========================================

        /**
         * Toggle backups section expansion
         * Story 17.10 AC4/AC7: Collapsible section for backups
         */
        toggleBackupsSection() {
            this.backupsView.expanded = !this.backupsView.expanded;
            if (this.backupsView.expanded) {
                // Fetch backups when expanding
                this.fetchBackups();
            }
        },

        /**
         * Fetch backups for both global and project scopes
         * Story 17.10 AC4: Loads backup list from API
         */
        async fetchBackups() {
            this.backupsView.loading = true;
            try {
                // Fetch both global and project backups in parallel
                const [globalRes, projectRes] = await Promise.all([
                    fetch('/api/config/backups?scope=global'),
                    fetch('/api/config/backups?scope=project')
                ]);

                if (!globalRes.ok) {
                    throw new Error(`Failed to fetch global backups: HTTP ${globalRes.status}`);
                }
                if (!projectRes.ok) {
                    throw new Error(`Failed to fetch project backups: HTTP ${projectRes.status}`);
                }

                const globalData = await globalRes.json();
                const projectData = await projectRes.json();

                this.backupsView.globalBackups = globalData.backups || [];
                this.backupsView.projectBackups = projectData.backups || [];
            } catch (err) {
                console.error('Failed to fetch backups:', err);
                this.showToast('Failed to load backups');
            } finally {
                this.backupsView.loading = false;
            }
        },

        /**
         * Format backup timestamp for display
         * @param {string} isoTimestamp - ISO timestamp string
         * @returns {string} Formatted date/time string
         */
        formatBackupTime(isoTimestamp) {
            if (!isoTimestamp || isoTimestamp === 'unknown') {
                return 'Unknown';
            }
            try {
                const date = new Date(isoTimestamp);
                return date.toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                });
            } catch {
                return isoTimestamp;
            }
        },

        /**
         * Restore config from backup
         * Story 17.10 AC5: Restore backup with confirmation
         * @param {string} scope - 'global' or 'project'
         * @param {number} version - Backup version (1 = newest)
         */
        async restoreBackup(scope, version) {
            // Story 17.10 AC5: Confirmation dialog with unsaved changes warning
            let message = `Restore ${scope} config from backup version ${version}?\n\n` +
                `This will replace the current ${scope} configuration and cannot be undone.`;

            // Add warning if there are pending updates
            if (this.pendingUpdates.length > 0) {
                message += `\n\n⚠️ WARNING: You have ${this.pendingUpdates.length} unsaved change(s) that will be discarded.`;
            }

            const confirmed = confirm(message);
            if (!confirmed) return;

            this.backupsView.restoring = true;
            try {
                const res = await fetch('/api/config/restore', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scope, version })
                });

                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    if (res.status === 404) {
                        throw new Error(data.message || 'Backup not found');
                    } else if (res.status === 400) {
                        throw new Error(data.message || 'Invalid backup content');
                    } else {
                        throw new Error(data.message || `Restore failed: HTTP ${res.status}`);
                    }
                }

                this.showToast(`Restored ${scope} config from backup v${version}`);

                // Refresh backups list and config data
                await Promise.all([
                    this.fetchBackups(),
                    this.fetchConfig()
                ]);

                // Clear pending changes since we just restored
                this.pendingUpdates = [];
                this.validationErrors = {};
                this.settingsView.hasChanges = false;
                this.settingsView.staleData = false;

            } catch (err) {
                console.error('Failed to restore backup:', err);
                this.showToast(`Restore failed: ${err.message}`);
            } finally {
                this.backupsView.restoring = false;
            }
        },

        /**
         * View backup content in modal
         * Story 17.10 AC6: Display backup content for inspection
         * @param {string} scope - 'global' or 'project'
         * @param {object} backup - Backup object with path, version, modified
         */
        async viewBackup(scope, backup) {
            try {
                // Story 17.10 AC6: Use dedicated backup content endpoint (supports global backups)
                const res = await fetch(`/api/config/backup/content?scope=${scope}&version=${backup.version}`);

                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.error || `Failed to load backup: HTTP ${res.status}`);
                }

                const content = await res.text();

                // Display in content modal
                this.contentModal.title = `${scope.charAt(0).toUpperCase() + scope.slice(1)} Backup v${backup.version}`;
                this.contentModal.content = content;
                this.contentModal.type = 'text';  // YAML as plain text
                this.contentModal.show = true;

            } catch (err) {
                console.error('Failed to view backup:', err);
                this.showToast(`Failed to load backup: ${err.message}`);
            }
        },

        /**
         * Check if any backups exist
         * @returns {boolean} True if there are any backups
         */
        hasBackups() {
            return this.backupsView.globalBackups.length > 0 ||
                   this.backupsView.projectBackups.length > 0;
        },

        // ==========================================
        // Playwright Status Methods (Story 17.11)
        // ==========================================

        /**
         * Fetch Playwright status with 30s debounce
         * Story 17.11 AC6: Auto-fetch with caching
         */
        async fetchPlaywrightStatus() {
            // Prevent concurrent fetches
            if (this.playwrightStatus.loading) return;

            const now = Date.now();
            if (now - this.playwrightStatus.lastFetch < this.PLAYWRIGHT_STATUS_CACHE_MS) {
                return;  // Use cached data
            }
            await this.refreshPlaywrightStatus();
        },

        /**
         * Force refresh Playwright status (no debounce)
         * Story 17.11 AC5: Manual refresh button
         */
        async refreshPlaywrightStatus() {
            this.playwrightStatus.loading = true;
            this.playwrightStatus.error = null;

            try {
                const res = await fetch('/api/playwright/status');
                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.error || `HTTP ${res.status}`);
                }

                const data = await res.json();
                this.playwrightStatus.data = data;
                this.playwrightStatus.lastFetch = Date.now();
            } catch (err) {
                console.error('Failed to fetch Playwright status:', err);
                this.playwrightStatus.error = err.message || 'Failed to check status';
            } finally {
                this.playwrightStatus.loading = false;
                this.$nextTick(() => this.refreshIcons());
            }
        },

        /**
         * Get status badge config for display
         * Story 17.11 AC2: Badge shows Ready/Not Installed/Missing Deps/No Browsers
         */
        getPlaywrightStatusBadge() {
            const s = this.playwrightStatus;

            if (s.loading) {
                return { text: 'Checking...', class: 'badge-secondary', icon: 'loader-2' };
            }

            if (s.error) {
                return { text: 'Error', class: 'bg-destructive/20 text-destructive', icon: 'alert-circle' };
            }

            if (!s.data) {
                return { text: 'Unknown', class: 'badge-secondary', icon: 'help-circle' };
            }

            if (s.data.ready) {
                return { text: 'Ready', class: 'bg-accent/20 text-accent', icon: 'check-circle' };
            }

            if (!s.data.package_installed) {
                return { text: 'Not Installed', class: 'bg-destructive/20 text-destructive', icon: 'x-circle' };
            }

            // Check for browsers BEFORE deps_ok (deps_ok is false when no browsers installed)
            const hasAnyBrowser = s.data.browsers.chromium || s.data.browsers.firefox || s.data.browsers.webkit;
            if (!hasAnyBrowser) {
                return { text: 'No Browsers', class: 'bg-bp-warning/20 text-bp-warning', icon: 'alert-triangle' };
            }

            if (!s.data.deps_ok) {
                return { text: 'Missing Deps', class: 'bg-bp-warning/20 text-bp-warning', icon: 'alert-triangle' };
            }

            // Fallback for any other unexpected state
            return { text: 'Unknown', class: 'badge-secondary', icon: 'help-circle' };
        },

        /**
         * Get formatted browsers list from status
         * Story 17.11 AC3: Show installed browsers
         */
        getInstalledBrowsersList() {
            const browsers = this.playwrightStatus.data?.browsers;
            if (!browsers) return '';

            const installed = [];
            if (browsers.chromium) installed.push('chromium');
            if (browsers.firefox) installed.push('firefox');
            if (browsers.webkit) installed.push('webkit');

            return installed.length > 0 ? installed.join(', ') : 'none';
        },

        /**
         * Copy install commands to clipboard
         * Story 17.11 AC4: Copy All button
         */
        async copyInstallCommands() {
            const commands = this.playwrightStatus.data?.install_commands || [];
            if (commands.length === 0) {
                this.showToast('No commands to copy');
                return;
            }

            const text = commands.join('\n');
            await this.copyToClipboard(text);
        },

        // ==========================================
        // Config Export/Import Methods (Story 17.12)
        // ==========================================

        /**
         * Export configuration as YAML download
         * Story 17.12 AC2: Export button with dropdown
         * @param {string} scope - 'merged' | 'global' | 'project'
         */
        async exportConfig(scope = 'merged') {
            this.exportView.loading = true;
            this.exportView.dropdownOpen = false;

            try {
                const res = await fetch(`/api/config/export?scope=${scope}`);

                if (!res.ok) {
                    const data = await res.json().catch(() => ({}));
                    throw new Error(data.message || `Export failed: HTTP ${res.status}`);
                }

                // Get filename from Content-Disposition header or generate
                const disposition = res.headers.get('Content-Disposition');
                let filename = `bmad-config-${scope}.yaml`;
                if (disposition) {
                    const match = disposition.match(/filename="(.+)"/);
                    if (match) filename = match[1];
                }

                // Create download with delayed cleanup for browser compatibility
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                // Delay cleanup to ensure download completes on slower devices
                setTimeout(() => URL.revokeObjectURL(url), 5000);

                this.showToast(`Exported ${scope} config`);

            } catch (err) {
                console.error('Export failed:', err);
                this.showToast(`Export failed: ${err.message}`);
            } finally {
                this.exportView.loading = false;
            }
        },

        /**
         * Trigger file picker for import
         * Story 17.12 AC5: Import button opens file picker
         */
        openImportFilePicker() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.yaml,.yml';
            input.onchange = (e) => {
                const file = e.target.files?.[0];
                if (file) this.startImport(file);
            };
            input.click();
        },

        /**
         * Read file and request import preview
         * Story 17.12 AC5/AC6: Read file, POST preview, show modal
         */
        async startImport(file) {
            // Check file size client-side (100KB limit)
            if (file.size > 100 * 1024) {
                this.showToast('Import file too large. Maximum size: 100KB');
                return;
            }

            this.importView.loading = true;
            this.importView.filename = file.name;
            this.importView.errors = null;
            this.importView.diff = null;

            try {
                const content = await file.text();
                this.importView.content = content;  // Store for scope switching
                await this._fetchImportPreview();
            } catch (err) {
                console.error('Import failed:', err);
                this.showToast(`Import failed: ${err.message}`);
                this.importView.loading = false;
            }
        },

        /**
         * Re-fetch diff preview when scope changes (uses stored content)
         * Story 17.12 AC6: Scope selector triggers re-fetch
         */
        async refreshImportPreview() {
            if (!this.importView.content) return;
            this.importView.loading = true;
            this.importView.errors = null;
            this.importView.diff = null;
            await this._fetchImportPreview();
        },

        /**
         * Internal: Fetch import preview from backend
         * Story 17.12 AC3/AC4/AC8: Preview mode returns diff or errors
         */
        async _fetchImportPreview() {
            try {
                const res = await fetch('/api/config/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scope: this.importView.scope,
                        content: this.importView.content,
                        confirmed: false,
                    }),
                });

                const data = await res.json();

                if (res.status === 422) {
                    // Pydantic validation errors
                    this.parseValidationErrors(data);
                    this.importView.errors = 'validation';
                    this.importView.modalOpen = true;
                } else if (res.status === 403) {
                    // DANGEROUS fields present
                    this.importView.errors = `Import contains restricted fields: ${data.dangerous_fields.join(', ')}`;
                    this.importView.modalOpen = true;
                } else if (!res.ok) {
                    throw new Error(data.message || `Import failed: HTTP ${res.status}`);
                } else {
                    // Success - show diff preview
                    this.importView.diff = data.diff;
                    this.importView.riskyFields = data.risky_fields || [];
                    this.importView.modalOpen = true;
                }
            } finally {
                this.importView.loading = false;
                this.$nextTick(() => this.refreshIcons());
            }
        },

        /**
         * Check if import has any changes to apply
         * Story 17.12 AC6: Disable Apply button when no changes
         * @returns {boolean} True if diff contains any changes
         */
        hasImportChanges() {
            const d = this.importView.diff;
            if (!d) return false;
            return Object.keys(d.added || {}).length > 0 ||
                   Object.keys(d.modified || {}).length > 0 ||
                   (d.removed || []).length > 0;
        },

        /**
         * Apply the imported configuration
         * Story 17.12 AC7: Apply import with risky field confirmation
         */
        async applyImport() {
            // Handle risky fields confirmation
            if (this.importView.riskyFields.length > 0) {
                const confirmed = confirm(
                    `The following settings require confirmation:\n\n` +
                    `• ${this.importView.riskyFields.join('\n• ')}\n\n` +
                    `Modifying these could affect workflow behavior. Continue?`
                );
                if (!confirmed) return;
            }

            this.importView.loading = true;

            try {
                const res = await fetch('/api/config/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        scope: this.importView.scope,
                        content: this.importView.content,
                        confirmed: true,
                    }),
                });

                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.message || `Apply failed: HTTP ${res.status}`);
                }

                // Success
                this.importView.modalOpen = false;
                const count = data.updated_paths?.length || 0;
                this.showToast(`Configuration imported successfully. ${count} fields updated.`);

                // Suppress duplicate toast from SSE (Story 17.9 pattern)
                this._selfReloadTimestamp = Date.now();

                // Reload config in settings panel if open
                // Note: Backend already reloads config singleton and broadcasts SSE
                if (this.settingsView.open) {
                    await this.fetchConfig();
                }

            } catch (err) {
                console.error('Apply import failed:', err);
                this.importView.errors = err.message;
            } finally {
                this.importView.loading = false;
            }
        },

        /**
         * Close import modal and reset state
         * Story 17.12 AC6: Cancel button
         */
        closeImportModal() {
            this.importView.modalOpen = false;
            this.importView.diff = null;
            this.importView.errors = null;
            this.importView.content = '';
            this.importView.filename = '';
            this.importView.riskyFields = [];
        }
    };
};
