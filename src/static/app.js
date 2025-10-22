class SignalManager {
    constructor() {
        this.selectedSignals = new Set();
        this.signals = [];
        this.currentPage = 1;
        this.pageSize = 20;
        this.totalPages = 1;
        this.totalCount = 0;
        this.countries = [];
        this.hazards = [];
        const params = new URLSearchParams(window.location.search);
        this.initialCountries = params.get('countries') ? params.get('countries').split(',').map(c => c.trim()).filter(Boolean) : [];
        this.initialHazards = params.get('hazards') ? params.get('hazards').split(',').map(h => h.trim()).filter(Boolean) : [];
        this.initialSearch = params.get('search') || '';
        this.initialStartDate = params.get('start_date') || '';
        this.initialEndDate = params.get('end_date') || '';
        this.initialIsSignal = params.get('is_signal') || 'all';

        if (!this.initialStartDate || !this.initialEndDate) {
            const end = new Date();
            const start = new Date();
            start.setDate(end.getDate() - 3);
            const format = d => d.toISOString().slice(0, 10);
            if (!this.initialStartDate) {
                this.initialStartDate = format(start);
            }
            if (!this.initialEndDate) {
                this.initialEndDate = format(end);
            }
        }

        this.init();
    }

    async init() {
    this.bindEvents();
    this._ensureRiskAssessmentStyles();
        await this.loadCountries();
        await this.loadHazards();
        this.applyInitialFilters();
        this.loadSignals();
        this.loadTags();
        this.loadConfig();
        this.checkSchedulerStatus();
    }

    _ensureRiskAssessmentStyles() {
        // Inject minimal CSS to animate risk assessment expansion/collapse
        if (document.getElementById('risk-assessment-styles')) return;
        const style = document.createElement('style');
        style.id = 'risk-assessment-styles';
        style.textContent = `
        .risk-assessment {
            max-height: 0px;
            overflow: hidden;
            opacity: 0;
            transition: max-height 240ms ease, opacity 200ms ease;
        }
        .risk-assessment.open {
            max-height: 320px; /* adjust as needed */
            overflow: auto;
            opacity: 1;
        }
        .risk-assessment .whitespace-pre-line { white-space: pre-wrap; }
        `;
        document.head.appendChild(style);
    }

    bindEvents() {
        // Fetch signals button
        document.getElementById("fetchBtn").addEventListener("click", () => this.fetchSignals());
        
        // Configuration button
        document.getElementById("configBtn").addEventListener("click", () => this.openConfigModal());
        
        // Scheduler toggle button
        document.getElementById("toggleSchedulerBtn").addEventListener("click", () => this.toggleScheduler());
        
        // Filter changes
        document.getElementById("statusFilter").addEventListener("change", () => this.resetAndLoadSignals(true));
        document.getElementById("isSignalFilter").addEventListener("change", () => this.resetAndLoadSignals(true));
        document.getElementById("pinnedFilter").addEventListener("change", () => this.resetAndLoadSignals(true));
        document.getElementById("pageSizeFilter").addEventListener("change", () => this.resetAndLoadSignals());

        // Search input with debounce
        const searchInput = document.getElementById("searchInput");
        if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener("input", () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => this.resetAndLoadSignals(true), 500);
            });
        }

        // Country filter events
        document.getElementById("countryFilter").addEventListener("change", () => {
            this.onFilterChange();
        });
        document.getElementById("selectAllCountries").addEventListener("click", () => this.selectAllCountries());
        document.getElementById("clearAllCountries").addEventListener("click", () => this.clearAllCountries());

        // Hazards filter events
        document.getElementById("hazardFilter").addEventListener("change", () => {
            this.onFilterChange();
        });
        document.getElementById("selectAllHazards").addEventListener("click", () => this.selectAllHazards());
        document.getElementById("clearAllHazards").addEventListener("click", () => this.clearAllHazards());

        // Date filter events
        document.getElementById("startDate").addEventListener("change", () => {
            this.onFilterChange();
        });
        document.getElementById("endDate").addEventListener("change", () => {
            this.onFilterChange();
        });
        document.getElementById("clearDateFilter").addEventListener("click", () => this.clearDateFilter());

        // Pagination events
        document.getElementById("prevPageBtn").addEventListener("click", () => this.goToPage(this.currentPage - 1));
        document.getElementById("nextPageBtn").addEventListener("click", () => this.goToPage(this.currentPage + 1));
        document.getElementById("prevPageBtnBottom").addEventListener("click", () => this.goToPage(this.currentPage - 1));
        document.getElementById("nextPageBtnBottom").addEventListener("click", () => this.goToPage(this.currentPage + 1));
        
        // Batch actions
        document.getElementById("flagSelectedBtn").addEventListener("click", () => this.batchAction("flag"));
        document.getElementById("discardSelectedBtn").addEventListener("click", () => this.batchAction("discard"));
        document.getElementById("discardNonFlaggedBtn").addEventListener("click", () => this.discardNonFlagged());
        
        // Selection controls
        document.getElementById("selectAllBtn").addEventListener("click", () => this.selectAllSignals());
        document.getElementById("unselectAllBtn").addEventListener("click", () => this.unselectAllSignals());
        
        // Export controls
        document.getElementById("exportSelectedBtn").addEventListener("click", () => this.exportSelected());
        document.getElementById("exportAllBtn").addEventListener("click", () => this.exportAll());
        
        // Configuration modal
        document.getElementById("closeConfigBtn").addEventListener("click", () => this.closeConfigModal());
        document.getElementById("cancelConfigBtn").addEventListener("click", () => this.closeConfigModal());
        document.getElementById("saveConfigBtn").addEventListener("click", () => this.saveConfig());

        // Provider selection change: toggle provider-specific config fields
        const providerSelect = document.getElementById("providerSelect");
        if (providerSelect) {
            providerSelect.addEventListener("change", () => this.updateProviderUI());
        }

        // Database cleanup events
        document.getElementById("previewCleanupBtn").addEventListener("click", () => this.previewCleanup());
        document.getElementById("executeCleanupBtn").addEventListener("click", () => this.executeCleanup());
        
        // Close modal on background click
        document.getElementById("configModal").addEventListener("click", (e) => {
            if (e.target.id === "configModal") {
                this.closeConfigModal();
            }
        });
    }

    async resetAndLoadSignals(refreshCountries = false) {
        this.currentPage = 1;
        if (refreshCountries) {
            await this.loadCountries();
        }
        this.loadSignals();
    }

    goToPage(page) {
        if (page >= 1 && page <= this.totalPages) {
            this.currentPage = page;
            this.loadSignals();
        }
    }

    async loadCountries() {
        try {
            const status = document.getElementById("statusFilter").value;
            const isSignalSelect = document.getElementById("isSignalFilter");
            let isSignal = isSignalSelect ? isSignalSelect.value : 'all';
            if (isSignal === 'all' && this.initialIsSignal !== 'all') {
                isSignal = this.initialIsSignal;
            }
            const searchInput = document.getElementById("searchInput");
            let search = searchInput ? searchInput.value.trim() : "";
            if (!search && this.initialSearch) {
                search = this.initialSearch;
            }
            const startDate = document.getElementById("startDate").value || this.initialStartDate;
            const endDate = document.getElementById("endDate").value || this.initialEndDate;

            // Get selected hazards for filtering
            const selectedHazards = this.getSelectedHazards();

            const params = new URLSearchParams();
            if (status && status !== "all") params.append("status", status);
            if (isSignal && isSignal !== "all") params.append("is_signal", isSignal);
            if (search) params.append("search", search);
            if (startDate) params.append("start_date", startDate);
            if (endDate) params.append("end_date", endDate);
            if (selectedHazards.length > 0) params.append("hazards", selectedHazards.join(','));

            const response = await fetch(`/api/signals/countries?${params.toString()}`);
            const result = await response.json();

            if (result.success) {
                this.countries = result.countries;
                this.renderCountryFilter();
            }
        } catch (error) {
            console.error("Error loading countries:", error);
        }
    }

    async loadHazards() {
        try {
            const status = document.getElementById("statusFilter").value;
            const isSignalSelect = document.getElementById("isSignalFilter");
            let isSignal = isSignalSelect ? isSignalSelect.value : 'all';
            if (isSignal === 'all' && this.initialIsSignal !== 'all') {
                isSignal = this.initialIsSignal;
            }
            const searchInput = document.getElementById("searchInput");
            let search = searchInput ? searchInput.value.trim() : "";
            if (!search && this.initialSearch) {
                search = this.initialSearch;
            }
            const startDate = document.getElementById("startDate").value || this.initialStartDate;
            const endDate = document.getElementById("endDate").value || this.initialEndDate;

            // Get selected countries for filtering
            const selectedCountries = this.getSelectedCountries();

            const params = new URLSearchParams();
            if (status && status !== "all") params.append("status", status);
            if (isSignal && isSignal !== "all") params.append("is_signal", isSignal);
            if (search) params.append("search", search);
            if (startDate) params.append("start_date", startDate);
            if (endDate) params.append("end_date", endDate);
            if (selectedCountries.length > 0) params.append("countries", selectedCountries.join(','));

            const response = await fetch(`/api/signals/hazards?${params.toString()}`);
            const result = await response.json();

            if (result.success) {
                this.hazards = result.hazards;
                this.renderHazardFilter();
            }
        } catch (error) {
            console.error("Error loading hazards:", error);
        }
    }

    getSelectedCountries() {
        const countryFilter = document.getElementById("countryFilter");
        if (!countryFilter) return [];
        const checkboxes = countryFilter.querySelectorAll('input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    getSelectedHazards() {
        const hazardFilter = document.getElementById("hazardFilter");
        if (!hazardFilter) return [];
        const checkboxes = hazardFilter.querySelectorAll('input[type="checkbox"]:checked');
        return Array.from(checkboxes).map(cb => cb.value);
    }

    // Interactive filter change handler
    async onFilterChange() {
        // Update both filter lists to show only available options based on current selections
        await Promise.all([this.loadCountries(), this.loadHazards()]);
        // Then reload signals
        this.resetAndLoadSignals(true);
    }

    renderCountryFilter() {
        const countryFilter = document.getElementById("countryFilter");
        const previouslySelected = new Set(
            Array.from(countryFilter.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value)
        );
        countryFilter.innerHTML = "";

        if (this.countries.length === 0) {
            countryFilter.innerHTML = '<div class="text-sm text-gray-500">No countries available</div>';
            return;
        }

        this.countries.forEach(country => {
            const checkboxContainer = document.createElement("div");
            checkboxContainer.className = "flex items-center space-x-2 mb-1";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.id = `country-${country}`;
            checkbox.value = country;
            checkbox.className = "rounded border-gray-300 text-blue-600 focus:ring-blue-500";
            if (previouslySelected.has(country) || this.initialCountries.includes(country)) {
                checkbox.checked = true;
            }

            const label = document.createElement("label");
            label.htmlFor = `country-${country}`;
            label.textContent = country;
            label.className = "text-sm text-gray-700 cursor-pointer";

            checkboxContainer.appendChild(checkbox);
            checkboxContainer.appendChild(label);
            countryFilter.appendChild(checkboxContainer);
        });
    }

    renderHazardFilter() {
        const hazardFilter = document.getElementById("hazardFilter");
        const previouslySelected = new Set(
            Array.from(hazardFilter.querySelectorAll('input[type="checkbox"]:checked')).map(cb => cb.value)
        );
        hazardFilter.innerHTML = "";

        if (this.hazards.length === 0) {
            hazardFilter.innerHTML = '<div class="text-sm text-gray-500">No hazards available</div>';
            return;
        }

        this.hazards.forEach(hazard => {
            const checkboxContainer = document.createElement("div");
            checkboxContainer.className = "flex items-center space-x-2 mb-1";

            const checkbox = document.createElement("input");
            checkbox.type = "checkbox";
            checkbox.id = `hazard-${hazard}`;
            checkbox.value = hazard;
            checkbox.className = "rounded border-gray-300 text-blue-600 focus:ring-blue-500";
            if (previouslySelected.has(hazard) || this.initialHazards.includes(hazard)) {
                checkbox.checked = true;
            }

            const label = document.createElement("label");
            label.htmlFor = `hazard-${hazard}`;
            label.textContent = hazard;
            label.className = "text-sm text-gray-700 cursor-pointer";

            checkboxContainer.appendChild(checkbox);
            checkboxContainer.appendChild(label);
            hazardFilter.appendChild(checkboxContainer);
        });
    }

    applyInitialFilters() {
        if (this.initialSearch) {
            const searchInput = document.getElementById("searchInput");
            if (searchInput) {
                searchInput.value = this.initialSearch;
            }
        }
        if (this.initialCountries.length > 0) {
            const countryFilter = document.getElementById("countryFilter");
            this.initialCountries.forEach(country => {
                const checkbox = countryFilter.querySelector(`input[value="${country}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                }
            });
        }
        if (this.initialHazards.length > 0) {
            const hazardFilter = document.getElementById("hazardFilter");
            this.initialHazards.forEach(hazard => {
                const checkbox = hazardFilter.querySelector(`input[value="${hazard}"]`);
                if (checkbox) {
                    checkbox.checked = true;
                }
            });
        }
        const startDateInput = document.getElementById("startDate");
        const endDateInput = document.getElementById("endDate");
        if (startDateInput) {
            startDateInput.value = this.initialStartDate;
        }
        if (endDateInput) {
            endDateInput.value = this.initialEndDate;
        }
        const isSignalSelect = document.getElementById("isSignalFilter");
        if (isSignalSelect) {
            isSignalSelect.value = this.initialIsSignal;
        }

        // Clear initial values after applying so user changes take precedence
        this.initialCountries = [];
        this.initialHazards = [];
        this.initialSearch = '';
        this.initialIsSignal = isSignalSelect ? isSignalSelect.value : 'all';
        this.initialStartDate = '';
        this.initialEndDate = '';
    }

    selectAllCountries() {
        const countryFilter = document.getElementById("countryFilter");
        const checkboxes = countryFilter.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => {
            checkbox.checked = true;
        });
        this.onFilterChange();
    }

    clearAllCountries() {
        const countryFilter = document.getElementById("countryFilter");
        const checkboxes = countryFilter.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });
        this.onFilterChange();
    }

    selectAllHazards() {
        const hazardFilter = document.getElementById("hazardFilter");
        const checkboxes = hazardFilter.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => {
            checkbox.checked = true;
        });
        this.onFilterChange();
    }

    clearAllHazards() {
        const hazardFilter = document.getElementById("hazardFilter");
        const checkboxes = hazardFilter.querySelectorAll('input[type="checkbox"]');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });
        this.onFilterChange();
    }

    clearDateFilter() {
        document.getElementById("startDate").value = "";
        document.getElementById("endDate").value = "";
        this.onFilterChange();
    }

    async fetchSignals() {
        this.showStatus("Fetching signals from EIOS...", true);
        
        try {
            const response = await fetch("/api/signals/fetch", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showStatus(`Successfully processed ${result.processed_count} signals (${result.true_signals_count} true signals)`, false);
                setTimeout(() => this.hideStatus(), 3000);
                this.resetAndLoadSignals(true);
            } else {
                this.showStatus(`Error: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Error fetching signals: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    async loadSignals() {
        const statusFilter = document.getElementById("statusFilter").value;
        const isSignalFilter = document.getElementById("isSignalFilter").value;
        const pinnedFilter = document.getElementById("pinnedFilter").value;
        const search = document.getElementById("searchInput") ? document.getElementById("searchInput").value.trim() : "";
        
        // Get page size from selector
        this.pageSize = parseInt(document.getElementById("pageSizeFilter").value);
        
        // Get country filter from checkboxes
        const selectedCountries = this.getSelectedCountries();
        
        // Get hazard filter from checkboxes
        const selectedHazards = this.getSelectedHazards();
        
        // Get date filters
        const startDate = document.getElementById("startDate").value;
        const endDate = document.getElementById("endDate").value;
        
        try {
            const params = new URLSearchParams({
                status: statusFilter,
                page: this.currentPage,
                page_size: this.pageSize
            });

            if (search) {
                params.append("search", search);
            }
            
            if (pinnedFilter && pinnedFilter !== "all") {
                params.append("pinned_filter", pinnedFilter);
            }
            
            if (selectedCountries.length > 0) {
                params.append("countries", selectedCountries.join(","));
            }
            
            if (selectedHazards.length > 0) {
                params.append("hazards", selectedHazards.join(","));
            }
            
            if (startDate) {
                params.append("start_date", startDate);
            }
            
            if (endDate) {
                params.append("end_date", endDate);
            }
            
            const response = await fetch(`/api/signals/processed?${params}`);
            const result = await response.json();
            
            if (result.success) {
                // Apply front-end filter for isSignal (Yes/No) if set
                let signals = result.signals;
                if (isSignalFilter && isSignalFilter !== "all") {
                    signals = signals.filter(s => (s.is_signal || "").toLowerCase() === isSignalFilter.toLowerCase());
                }
                this.signals = signals;
                
                // Update pagination info
                if (result.pagination) {
                    this.totalCount = result.pagination.total_count;
                    this.totalPages = result.pagination.total_pages;
                    this.currentPage = result.pagination.page;
                }
                
                this.renderSignals();
                this.renderPagination();
                // After rendering, update counts in the status dropdown
                this.loadCounts();
            } else {
                console.error("Error loading signals:", result.message);
            }
        } catch (error) {
            console.error("Error loading signals:", error);
        }
    }

    renderPagination() {
        const showPagination = this.totalPages > 1;
        
        // Show/hide pagination controls
        document.getElementById("paginationTop").classList.toggle("hidden", !showPagination);
        document.getElementById("paginationBottom").classList.toggle("hidden", !showPagination);
        
        if (!showPagination) return;
        
        // Update pagination info
        const start = (this.currentPage - 1) * this.pageSize + 1;
        const end = Math.min(this.currentPage * this.pageSize, this.totalCount);
        const infoText = `Showing ${start}-${end} of ${this.totalCount} signals`;
        
        document.getElementById("paginationInfo").textContent = infoText;
        document.getElementById("paginationInfoBottom").textContent = infoText;
        
        // Update navigation buttons
        const hasPrev = this.currentPage > 1;
        const hasNext = this.currentPage < this.totalPages;
        
        document.getElementById("prevPageBtn").disabled = !hasPrev;
        document.getElementById("nextPageBtn").disabled = !hasNext;
        document.getElementById("prevPageBtnBottom").disabled = !hasPrev;
        document.getElementById("nextPageBtnBottom").disabled = !hasNext;
        
        // Render page numbers
        this.renderPageNumbers("pageNumbers");
        this.renderPageNumbers("pageNumbersBottom");
    }
    
    renderPageNumbers(containerId) {
        const container = document.getElementById(containerId);
        container.innerHTML = "";
        
        const maxVisible = 5;
        let startPage = Math.max(1, this.currentPage - Math.floor(maxVisible / 2));
        let endPage = Math.min(this.totalPages, startPage + maxVisible - 1);
        
        // Adjust start if we\'re near the end
        if (endPage - startPage + 1 < maxVisible) {
            startPage = Math.max(1, endPage - maxVisible + 1);
        }
        
        // Add first page and ellipsis if needed
        if (startPage > 1) {
            this.addPageButton(container, 1);
            if (startPage > 2) {
                const ellipsis = document.createElement("span");
                ellipsis.textContent = "...";
                ellipsis.className = "px-2 py-1 text-gray-500";
                container.appendChild(ellipsis);
            }
        }
        
        // Add visible page numbers
        for (let i = startPage; i <= endPage; i++) {
            this.addPageButton(container, i);
        }
        
        // Add ellipsis and last page if needed
        if (endPage < this.totalPages) {
            if (endPage < this.totalPages - 1) {
                const ellipsis = document.createElement("span");
                ellipsis.textContent = "...";
                ellipsis.className = "px-2 py-1 text-gray-500";
                container.appendChild(ellipsis);
            }
            this.addPageButton(container, this.totalPages);
        }
    }
    
    addPageButton(container, pageNum) {
        const button = document.createElement("button");
        button.textContent = pageNum;
        button.className = `px-3 py-1 border rounded text-sm ${
            pageNum === this.currentPage 
                ? "bg-blue-600 text-white border-blue-600" 
                : "border-gray-300 hover:bg-gray-50"
        }`;
        button.addEventListener("click", () => this.goToPage(pageNum));
        container.appendChild(button);
    }
    /**
     * Fetch counts for each status (new/flagged/discarded/all) and update option labels
     * in the status filter dropdown.
     */
    async loadCounts() {
        try {
            const response = await fetch(`/api/signals/counts`);
            const result = await response.json();
            if (result.success) {
                const counts = result.counts || {};
                const statusFilter = document.getElementById("statusFilter");
                // Iterate through options and update text
                Array.from(statusFilter.options).forEach(opt => {
                    const val = opt.value;
                    if (val === "all") {
                        opt.textContent = `All Signals${counts["all"] !== undefined ? ` (${counts["all"]})` : ""}`;
                    } else if (["new","flagged","discarded"].includes(val)) {
                        opt.textContent = `${val.charAt(0).toUpperCase() + val.slice(1)} Signals${counts[val] !== undefined ? ` (${counts[val]})` : ""}`;
                    }
                });
            }
        } catch (error) {
            console.error("Error loading counts:", error);
        }
    }

    renderSignals() {
        const container = document.getElementById("signalsList");
        const emptyState = document.getElementById("emptyState");
        
        if (this.signals.length === 0) {
            container.innerHTML = "";
            emptyState.classList.remove("hidden");
            return;
        }
        
        emptyState.classList.add("hidden");
        
        container.innerHTML = this.signals.map(signal => this.renderSignalCard(signal)).join("");
        
        // Bind checkbox events
        container.querySelectorAll(".signal-checkbox").forEach(checkbox => {
            checkbox.addEventListener("change", (e) => {
                const signalId = parseInt(e.target.dataset.signalId);
                if (e.target.checked) {
                    this.selectedSignals.add(signalId);
                } else {
                    this.selectedSignals.delete(signalId);
                }
                this.updateBatchButtons();
            });
        });
        
        // Bind individual action buttons
        container.querySelectorAll(".flag-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const signalId = parseInt(e.target.dataset.signalId);
                this.flagSignal(signalId);
            });
        });
        
        container.querySelectorAll(".discard-btn").forEach(btn => {
            btn.addEventListener("click", (e) => {
                const signalId = parseInt(e.target.dataset.signalId);
                this.discardSignal(signalId);
            });
        });

        // Click on card to toggle risk assessment (but ignore clicks on controls)
        container.querySelectorAll('.signal-card').forEach(card => {
            card.addEventListener('click', (e) => {
                const tag = e.target.tagName.toLowerCase();
                // ignore clicks on buttons, links, inputs
                if (tag === 'button' || tag === 'a' || tag === 'input' || e.target.closest('button') || e.target.closest('a')) {
                    return;
                }
                const riskDiv = card.querySelector('.risk-assessment');
                if (riskDiv) {
                    // toggle with animation class
                    riskDiv.classList.toggle('open');
                }
            });
        });
    }

    renderSignalCard(signal) {
        const statusClass = `status-${signal.status.toLowerCase()}`;
        const isSignalText = signal.is_signal === "Yes" ? "True Signal" : "Not a Signal";
        const isSignalColor = signal.is_signal === "Yes" ? "text-green-600" : "text-red-600";
        const eiosUrl = `https://portal.who.int/eios/#/items/${signal.id}/title/full-article`;
    const riskText = signal.risk_signal_assessment || "";
    // Parsed values from processed signal
    const countriesVal = signal.extracted_countries || "N/A";
    const isSignalVal = signal.is_signal || "N/A";
    const justificationVal = signal.justification || "";
    const hazardsVal = signal.extracted_hazards || "N/A";
    // Basic escaping
    const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const safeRaw = esc(riskText).replace(/\n/g, '<br>');
    const safeCountries = esc(countriesVal);
    const safeIsSignal = esc(isSignalVal);
    const safeJustification = esc(justificationVal).replace(/\n/g, '<br>');
    const safeHazards = esc(hazardsVal);
        const title = signal.raw_signal ? signal.raw_signal.title : "N/A";
        const summary = signal.raw_signal ? (signal.raw_signal.translated_abstractive_summary || signal.raw_signal.abstractive_summary) : "N/A";
        const country = signal.extracted_countries || "N/A";
        const processDate = signal.processed_at ? new Date(signal.processed_at).toLocaleDateString() : "Invalid Date";

        return `
            <div class="bg-white rounded-lg shadow-sm p-6 flex items-start space-x-4 signal-card" title="${safeJustification}">
                <input type="checkbox" class="signal-checkbox mt-1" data-signal-id="${signal.id}" ${this.selectedSignals.has(signal.id) ? "checked" : ""}>
                <div class="flex-1">
                    <div class="flex items-center justify-between mb-2">
                        <h2 class="text-xl font-semibold text-gray-800">${title}</h2>
                        <span class="${statusClass} status-badge">${signal.status}</span>
                    </div>
                    <p class="text-gray-600 mb-3">${summary}</p>
                    <div class="flex flex-wrap items-center text-sm text-gray-500 mb-3">
                        <span class="mr-3"><i class="fas fa-globe"></i> ${country}</span>
                        <span class="mr-3"><i class="fas fa-calendar-alt"></i> ${processDate}</span>
                        <span class="mr-3 ${isSignalColor}"><i class="fas fa-check-circle"></i> ${isSignalText}</span>
                        ${signal.is_pinned ? '<span class="mr-3 text-orange-600"><i class="fas fa-thumbtack"></i> Pinned</span>' : '<span class="mr-3 text-gray-400"><i class="fas fa-thumbtack"></i> Unpinned</span>'}
                        <a href="${eiosUrl}" target="_blank" class="text-blue-500 hover:text-blue-700 flex items-center">
                            <i class="fas fa-external-link-alt mr-1"></i> EIOS Link
                        </a>
                    </div>
                    <div class="flex space-x-2">
                        <button class="flag-btn ${signal.status === 'flagged' ? 'bg-gray-400 hover:bg-gray-500' : 'bg-yellow-500 hover:bg-yellow-600'} text-white px-3 py-1 rounded-lg text-sm" data-signal-id="${signal.id}">
                            <i class="fas fa-flag"></i> ${signal.status === 'flagged' ? 'Unflag' : 'Flag'}
                        </button>
                        <button class="discard-btn ${signal.status === 'discarded' ? 'bg-gray-400 hover:bg-gray-500' : 'bg-red-500 hover:bg-red-600'} text-white px-3 py-1 rounded-lg text-sm" data-signal-id="${signal.id}">
                            <i class="fas fa-trash"></i> ${signal.status === 'discarded' ? 'Restore' : 'Discard'}
                        </button>
                    </div>
                    <!-- Risk assessment panel (collapsed by default) -->
                    <div class="risk-assessment mt-3 text-sm text-gray-800">
                        <div class="mb-2"><strong>Countries:</strong> ${safeCountries}</div>
                        <div class="mb-2"><strong>Is signal:</strong> ${safeIsSignal}</div>
                        <div class="mb-2"><strong>Justification:</strong> ${safeJustification}</div>
                        <div class="mb-2"><strong>Hazards:</strong> ${safeHazards}</div>
                        <hr class="my-2" />
                        <div class="text-xs text-gray-600"><strong>Raw assessment:</strong></div>
                        <div class="whitespace-pre-line text-xs text-gray-700">${safeRaw}</div>
                    </div>
                </div>
            </div>
        `;
    }

    updateBatchButtons() {
        const hasSelection = this.selectedSignals.size > 0;
        document.getElementById("flagSelectedBtn").disabled = !hasSelection;
        document.getElementById("discardSelectedBtn").disabled = !hasSelection;
        document.getElementById("exportSelectedBtn").disabled = !hasSelection;
    }

    async flagSignal(signalId) {
        try {
            const response = await fetch(`/api/signals/${signalId}/flag`, {
                method: "POST"
            });
            const result = await response.json();
            if (result.success) {
                this.loadSignals(); // Reload to show updated status
                const msg = result.message || "Signal flagged"
                this.showStatus(msg, false);
                setTimeout(() => this.hideStatus(), 2000);
            } else {
                this.showStatus(`Error flagging signal: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Error flagging signal: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    async discardSignal(signalId) {
        try {
            const response = await fetch(`/api/signals/${signalId}/discard`, {
                method: "POST"
            });
            const result = await response.json();
            if (result.success) {
                this.loadSignals(); // Reload to show updated status
                const msg = result.message || "Signal discarded"
                this.showStatus(msg, false);
                setTimeout(() => this.hideStatus(), 2000);
            } else {
                this.showStatus(`Error discarding signal: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Error discarding signal: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    showStatus(message, showSpinner = false, type = "info") {
        const statusBar = document.getElementById("statusBar");
        const statusText = document.getElementById("statusText");
        const loadingSpinner = statusBar.querySelector(".loading-spinner");

        statusBar.classList.remove("hidden", "bg-blue-50", "bg-red-50", "border-blue-200", "border-red-200");
        statusBar.classList.add(type === "error" ? "bg-red-50" : "bg-blue-50");
        statusBar.classList.add(type === "error" ? "border-red-200" : "border-blue-200");
        statusText.textContent = message;

        if (loadingSpinner) {
            loadingSpinner.classList.toggle("hidden", !showSpinner);
        }
    }

    hideStatus() {
        document.getElementById("statusBar").classList.add("hidden");
    }

    openConfigModal() {
        document.getElementById("configModal").classList.remove("hidden");
        this.loadConfig(); // Load config when modal opens
    }

    closeConfigModal() {
        document.getElementById("configModal").classList.add("hidden");
    }

    async checkSchedulerStatus() {
        try {
            const response = await fetch("/api/scheduler/status");
            const result = await response.json();
            if (result.success) {
                this.updateSchedulerUI(result.running);
            }
        } catch (error) {
            console.error("Error checking scheduler status:", error);
        }
    }

    updateSchedulerUI(isRunning) {
        const statusSpan = document.getElementById("schedulerStatus");
        const toggleBtn = document.getElementById("toggleSchedulerBtn");

        if (isRunning) {
            statusSpan.textContent = "Scheduler: Running";
            statusSpan.classList.remove("text-gray-600");
            statusSpan.classList.add("text-green-600");
            toggleBtn.textContent = "Stop";
            toggleBtn.classList.remove("bg-green-600", "hover:bg-green-700");
            toggleBtn.classList.add("bg-red-600", "hover:bg-red-700");
        } else {
            statusSpan.textContent = "Scheduler: Stopped";
            statusSpan.classList.remove("text-green-600");
            statusSpan.classList.add("text-gray-600");
            toggleBtn.textContent = "Start";
            toggleBtn.classList.remove("bg-red-600", "hover:bg-red-700");
            toggleBtn.classList.add("bg-green-600", "hover:bg-green-700");
        }
    }

    async toggleScheduler() {
        try {
            // First get current status
            const statusResponse = await fetch("/api/scheduler/status");
            const statusResult = await statusResponse.json();
            
            if (!statusResult.success) {
                this.showStatus(`Error getting scheduler status: ${statusResult.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
                return;
            }
            
            // Toggle based on current status
            const endpoint = statusResult.running ? "/api/scheduler/stop" : "/api/scheduler/start";
            const response = await fetch(endpoint, {
                method: "POST"
            });
            const result = await response.json();
            
            if (result.success) {
                this.updateSchedulerUI(!statusResult.running);
                this.showStatus(`Scheduler ${!statusResult.running ? "started" : "stopped"}`, false);
                setTimeout(() => this.hideStatus(), 2000);
            } else {
                this.showStatus(`Error toggling scheduler: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Error toggling scheduler: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    async batchAction(action) {
        if (this.selectedSignals.size === 0) {
            alert("Please select at least one signal.");
            return;
        }

        const confirmMessage = `Are you sure you want to ${action} ${this.selectedSignals.size} selected signals?`;
        if (!confirm(confirmMessage)) {
            return;
        }

        this.showStatus(`Performing batch ${action}...`, true);
        try {
            const response = await fetch(`/api/signals/batch-action`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    signal_ids: Array.from(this.selectedSignals),
                    action: action
                })
            });
            const result = await response.json();
            if (result.success) {
                this.selectedSignals.clear(); // Clear selection after action
                this.updateBatchButtons();
                this.loadSignals();
                this.showStatus(`Successfully ${action}ged ${result.updated_count} signals.`, false);
                setTimeout(() => this.hideStatus(), 2000);
            } else {
                this.showStatus(`Error performing batch ${action}: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Error performing batch ${action}: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    async previewCleanup() {
        const cleanupDate = document.getElementById("cleanupDate").value;
        if (!cleanupDate) {
            alert("Please select a date for cleanup preview.");
            return;
        }

        try {
            const response = await fetch("/api/signals/cleanup/preview", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ cutoff_date: cleanupDate })
            });
            const result = await response.json();
            const previewText = document.getElementById("cleanupPreviewText");
            const executeBtn = document.getElementById("executeCleanupBtn");

            if (result.success) {
                const counts = result.preview.counts_to_delete;
                previewText.textContent = `This will delete ${counts.processed_signals} processed signals, ${counts.raw_signals} raw signals, and ${counts.processed_signal_ids} processed signal IDs.`;
                executeBtn.disabled = counts.processed_signals === 0;
            } else {
                previewText.textContent = `Error: ${result.message}`;
                executeBtn.disabled = true;
            }
        } catch (error) {
            console.error("Error previewing cleanup:", error);
            alert(`Error previewing cleanup: ${error.message}`);
        }
    }

    async executeCleanup() {
        const cleanupDate = document.getElementById("cleanupDate").value;
        if (!cleanupDate) {
            alert("Please select a date for cleanup.");
            return;
        }

        if (!confirm("Are you sure you want to permanently delete these records? This action cannot be undone.")) {
            return;
        }

        try {
            const response = await fetch("/api/signals/cleanup", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ 
                    cutoff_date: cleanupDate,
                    confirm: true
                })
            });
            const result = await response.json();

            if (result.success) {
                const counts = result.deleted_counts;
                alert(`Cleanup completed successfully! Deleted ${counts.processed_signals} processed signals, ${counts.raw_signals} raw signals, and ${counts.processed_signal_ids} processed signal IDs.`);
                this.loadSignals(); // Refresh the signals list
                this.previewCleanup(); // Refresh the preview
            } else {
                alert(`Error executing cleanup: ${result.message}`);
            }
        } catch (error) {
            console.error("Error executing cleanup:", error);
            alert(`Error executing cleanup: ${error.message}`);
        }
    }

    async loadTags() {
        try {
            const response = await fetch("/api/signals/tags");
            const result = await response.json();
            if (result.success) {
                document.getElementById("tagsInput").value = result.tags.join(", ");
            }
        } catch (error) {
            console.error("Error loading tags:", error);
        }
    }

    async saveConfig() {
        const tags = document.getElementById("tagsInput").value.trim();
        const provider = document.getElementById("providerSelect").value;
        // Gather per-provider settings
        const configPayload = {
            provider,
            openai_api_key: document.getElementById("openaiKeyInput").value.trim(),
            openai_api_base: document.getElementById("openaiBaseInput").value.trim(),
            deepseek_api_key: document.getElementById("deepseekKeyInput").value.trim(),
            deepseek_api_base: document.getElementById("deepseekBaseInput").value.trim(),
            local_api_key: document.getElementById("localKeyInput").value.trim(),
            local_api_base: document.getElementById("localBaseInput").value.trim(),
            ai_model: document.getElementById("modelNameInput").value.trim(),
            risk_prompt: document.getElementById("riskEvaluationPrompt").value.trim()
        };

        if (!tags) {
            alert("Tags cannot be empty");
            return;
        }

        try {
            // Save tags
            const tagsRes = await fetch("/api/signals/tags", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ tags })
            });
            const tagsResult = await tagsRes.json();
            if (!tagsResult.success) {
                alert(`Error: ${tagsResult.message}`);
                return;
            }

            // Save configuration
            const configRes = await fetch("/api/signals/config", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(configPayload)
            });
            const configResult = await configRes.json();
            if (!configResult.success) {
                alert(`Error: ${configResult.message}`);
                return;
            }
            this.closeConfigModal();
            this.showStatus("Configuration saved successfully", false);
            setTimeout(() => this.hideStatus(), 2000);
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    /**
     * Update which provider configuration fields are visible based on the selected provider.
     */
    updateProviderUI() {
        const provider = document.getElementById("providerSelect") ? document.getElementById("providerSelect").value : "openai";
        const openaiSection = document.getElementById("openaiConfig");
        const deepseekSection = document.getElementById("deepseekConfig");
        const localSection = document.getElementById("localConfig");
        // Hide all
        [openaiSection, deepseekSection, localSection].forEach(el => {
            if (el) el.classList.add("hidden");
        });
        // Show selected
        if (provider === "openai" && openaiSection) {
            openaiSection.classList.remove("hidden");
        } else if (provider === "deepseek" && deepseekSection) {
            deepseekSection.classList.remove("hidden");
        } else if (provider === "local" && localSection) {
            localSection.classList.remove("hidden");
        }
    }

    /**
     * Load configuration values (API key, API base, risk prompt) from the server
     * and populate the corresponding input fields in the configuration modal.
     */
    async loadConfig() {
        try {
            const response = await fetch("/api/signals/config");
            const result = await response.json();
            if (result.success) {
                const cfg = result.config || {};
                // Populate provider and per-provider settings
                const provider = cfg.provider || "openai";
                const providerSelect = document.getElementById("providerSelect");
                if (providerSelect) providerSelect.value = provider;
                // Populate API keys and bases
                document.getElementById("openaiKeyInput").value = cfg.openai_api_key || "";
                document.getElementById("openaiBaseInput").value = cfg.openai_api_base || "";
                document.getElementById("deepseekKeyInput").value = cfg.deepseek_api_key || "";
                document.getElementById("deepseekBaseInput").value = cfg.deepseek_api_base || "";
                document.getElementById("localKeyInput").value = cfg.local_api_key || "";
                document.getElementById("localBaseInput").value = cfg.local_api_base || "";
                document.getElementById("modelNameInput").value = cfg.ai_model || "";
                document.getElementById("riskEvaluationPrompt").value = cfg.risk_prompt || "";
                // Update UI to show correct provider section
                this.updateProviderUI();
            }
        } catch (error) {
            console.error("Error loading configuration:", error);
        }
    }

    selectAllSignals() {
        // Select all signals on current page
        this.signals.forEach(signal => {
            this.selectedSignals.add(signal.id);
        });
        
        // Update checkboxes
        document.querySelectorAll(".signal-checkbox").forEach(checkbox => {
            checkbox.checked = true;
        });
        
        this.updateBatchButtons();
    }

    unselectAllSignals() {
        // Clear all selections
        this.selectedSignals.clear();
        
        // Update checkboxes
        document.querySelectorAll(".signal-checkbox").forEach(checkbox => {
            checkbox.checked = false;
        });
        
        this.updateBatchButtons();
    }

    getCurrentFilters() {
        // Get current filter state for export
        const statusFilter = document.getElementById("statusFilter").value;
        const isSignalFilter = document.getElementById("isSignalFilter").value;
        const pinnedFilter = document.getElementById("pinnedFilter").value;
        const search = document.getElementById("searchInput") ? document.getElementById("searchInput").value.trim() : "";
        
        // Get country filter from checkboxes
        const selectedCountries = this.getSelectedCountries();
        
        // Get hazard filter from checkboxes
        const selectedHazards = this.getSelectedHazards();
        
        // Get date filters
        const startDate = document.getElementById("startDate").value;
        const endDate = document.getElementById("endDate").value;
        
        return {
            status: statusFilter,
            pinned_filter: pinnedFilter,
            signals_only: isSignalFilter === "Yes",
            search: search || undefined,
            countries: selectedCountries.length > 0 ? selectedCountries.join(",") : undefined,
            hazards: selectedHazards.length > 0 ? selectedHazards.join(",") : undefined,
            start_date: startDate || undefined,
            end_date: endDate || undefined
        };
    }

    async exportSelected() {
        if (this.selectedSignals.size === 0) {
            this.showStatus("No signals selected for export", false, "error");
            setTimeout(() => this.hideStatus(), 3000);
            return;
        }

        try {
            this.showStatus("Exporting selected signals...", true);
            
            const response = await fetch("/api/signals/export-csv", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    signal_ids: Array.from(this.selectedSignals),
                    filters: this.getCurrentFilters()
                })
            });

            if (response.ok) {
                // Get filename from response headers
                const contentDisposition = response.headers.get('Content-Disposition');
                const filename = contentDisposition 
                    ? contentDisposition.split('filename=')[1].replace(/"/g, '')
                    : 'eios_signals_export.csv';
                
                // Create download
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                this.showStatus(`Exported ${this.selectedSignals.size} signals successfully`, false);
                setTimeout(() => this.hideStatus(), 3000);
            } else {
                const result = await response.json();
                this.showStatus(`Export failed: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Export failed: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }

    async exportAll() {
        try {
            this.showStatus("Exporting all signals with current filters...", true);
            
            const response = await fetch("/api/signals/export-csv", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    signal_ids: "all",
                    filters: this.getCurrentFilters()
                })
            });

            if (response.ok) {
                // Get filename from response headers
                const contentDisposition = response.headers.get('Content-Disposition');
                const filename = contentDisposition 
                    ? contentDisposition.split('filename=')[1].replace(/"/g, '')
                    : 'eios_signals_export.csv';
                
                // Create download
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                this.showStatus("All signals exported successfully", false);
                setTimeout(() => this.hideStatus(), 3000);
            } else {
                const result = await response.json();
                this.showStatus(`Export failed: ${result.message}`, false, "error");
                setTimeout(() => this.hideStatus(), 5000);
            }
        } catch (error) {
            this.showStatus(`Export failed: ${error.message}`, false, "error");
            setTimeout(() => this.hideStatus(), 5000);
        }
    }
}

document.addEventListener("DOMContentLoaded", () => {
    window.signalManager = new SignalManager();
});


