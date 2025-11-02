// dashboard.js
// Fetch statistics and populate the dashboard UI.

const topListData = {};

document.addEventListener('DOMContentLoaded', () => {
    bindEvents();
    displayDashboardTimezoneInfo();
    loadDashboard();
});

function displayDashboardTimezoneInfo() {
    // Display timezone information to user
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    const offset = new Date().getTimezoneOffset();
    const offsetHours = Math.abs(offset / 60);
    const offsetSign = offset <= 0 ? '+' : '-';
    const offsetString = `UTC${offsetSign}${offsetHours.toString().padStart(2, '0')}:${(Math.abs(offset) % 60).toString().padStart(2, '0')}`;
    
    const timezoneText = `(${timezone} - ${offsetString})`;
    
    // Update dashboard timezone indicator
    const dashboardTimezoneIndicator = document.getElementById("dashboardTimezoneIndicator");
    if (dashboardTimezoneIndicator) {
        dashboardTimezoneIndicator.textContent = timezoneText;
    }
}

function bindEvents() {
    document.getElementById('applyDateFilter').addEventListener('click', () => {
        loadDashboard();
    });

    document.getElementById('clearDateFilter').addEventListener('click', () => {
        document.getElementById('dashboardStartDate').value = '';
        document.getElementById('dashboardEndDate').value = '';
        loadDashboard();
    });

    const isSignalSelect = document.getElementById('dashboardIsSignal');
    if (isSignalSelect) {
        isSignalSelect.addEventListener('change', () => loadDashboard());
    }
}

async function loadDashboard() {
    try {
        const startDate = document.getElementById('dashboardStartDate').value;
        const endDate = document.getElementById('dashboardEndDate').value;
        const signalFilter = document.getElementById('dashboardIsSignal').value;

        const params = new URLSearchParams({ top_n: '0' });
        if (startDate) {
            params.append('start_date', startDate);
        }
        if (endDate) {
            params.append('end_date', endDate);
        }
        if (signalFilter && signalFilter !== 'all') {
            params.append('is_signal', signalFilter);
        }

        const url = `/api/signals/stats${params.toString() ? '?' + params.toString() : ''}`;
        const response = await fetch(url);
        const result = await response.json();

        if (!result.success) {
            console.error('Failed to load stats:', result.message);
            return;
        }
        const { counts = {}, is_signal_counts = {}, top_countries = [], top_hazards = [] } = result;
        renderSummaryCards(counts, is_signal_counts);
        renderTopList('topCountriesList', top_countries, 'country', signalFilter, startDate, endDate);
        renderTopList('topHazardsList', top_hazards, 'hazard', signalFilter, startDate, endDate);
    } catch (error) {
        console.error('Error loading dashboard:', error);
    }
}

function renderSummaryCards(counts, isSignalCounts) {
    const container = document.getElementById('summaryCards');
    if (!container) return;
    // Define card configurations
    const cards = [
        { title: 'New', count: counts.new || 0, color: 'blue', icon: 'fa-bell' },
        { title: 'Flagged', count: counts.flagged || 0, color: 'yellow', icon: 'fa-flag' },
        { title: 'Discarded', count: counts.discarded || 0, color: 'red', icon: 'fa-trash' },
        { title: 'Total', count: counts.all || 0, color: 'gray', icon: 'fa-layer-group' },
        { title: 'True Signals', count: isSignalCounts['Yes'] || 0, color: 'green', icon: 'fa-check-circle' },
        { title: 'Not Signals', count: isSignalCounts['No'] || 0, color: 'purple', icon: 'fa-times-circle' }
    ];
    container.innerHTML = cards.map(card => {
        const bgColor = {
            blue: 'bg-blue-100',
            yellow: 'bg-yellow-100',
            red: 'bg-red-100',
            gray: 'bg-gray-100',
            green: 'bg-green-100',
            purple: 'bg-purple-100'
        }[card.color] || 'bg-gray-100';
        const textColor = {
            blue: 'text-blue-600',
            yellow: 'text-yellow-600',
            red: 'text-red-600',
            gray: 'text-gray-600',
            green: 'text-green-600',
            purple: 'text-purple-600'
        }[card.color] || 'text-gray-600';
        return `
            <div class="bg-white rounded-lg shadow-sm p-4 flex items-center space-x-4">
                <div class="rounded-full ${bgColor} p-3">
                    <i class="fas ${card.icon} ${textColor}"></i>
                </div>
                <div>
                    <div class="text-sm font-medium text-gray-500">${card.title}</div>
                    <div class="text-xl font-bold text-gray-900">${card.count}</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderTopList(elementId, items, fieldName, signalFilter, startDate, endDate) {
    const listEl = document.getElementById(elementId);
    if (!listEl) return;
    if (!Array.isArray(items) || items.length === 0) {
        listEl.innerHTML = '<li class="text-gray-500">No data available</li>';
        return;
    }

    topListData[elementId] = { items, fieldName, signalFilter, startDate, endDate };

    const visibleItems = items.slice(0, 20);
    listEl.innerHTML = visibleItems.map(item => renderTopListItem(item, fieldName, signalFilter, startDate, endDate)).join('');

    if (items.length > 20) {
        listEl.innerHTML += `<li><button class="text-blue-600 hover:underline" data-list="${elementId}">More...</button></li>`;
        const moreBtn = listEl.querySelector(`button[data-list="${elementId}"]`);
        moreBtn.addEventListener('click', () => showMore(elementId));
    }
}

function renderTopListItem(item, fieldName, signalFilter, startDate, endDate) {
    const label = item[fieldName] || 'Unknown';
    const count = item.count || 0;
    const params = new URLSearchParams();
    if (fieldName === 'country') {
        params.append('countries', label);
    } else if (fieldName === 'hazard') {
        params.append('search', label);
    }
    if (signalFilter && signalFilter !== 'all') {
        params.append('is_signal', signalFilter);
    }
    if (startDate) {
        params.append('start_date', startDate);
    }
    if (endDate) {
        params.append('end_date', endDate);
    }
    const href = `index.html?${params.toString()}`;
    return `<li class="flex justify-between"><a href="${href}" class="text-blue-600 hover:underline">${label}</a><span class="font-semibold">${count}</span></li>`;
}

function showMore(elementId) {
    const data = topListData[elementId];
    if (!data) return;
    const { items, fieldName, signalFilter, startDate, endDate } = data;
    const listEl = document.getElementById(elementId);
    const remaining = items.slice(20).map(item => renderTopListItem(item, fieldName, signalFilter, startDate, endDate)).join('');
    const moreBtn = listEl.querySelector(`button[data-list="${elementId}"]`);
    if (moreBtn) {
        moreBtn.parentElement.remove();
    }
    listEl.insertAdjacentHTML('beforeend', remaining);
}