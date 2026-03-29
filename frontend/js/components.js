// Sidebar HTML generator
function renderSidebar(activePage) {
    const user = getUser() || { name: 'Admin', email: 'admin@complychip.ai', role: 'admin' };
    const initials = (user.name || 'A').split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2);

    const navItems = [
        { group: 'MAIN', items: [
            { id: 'dashboard', label: 'Dashboard', href: '/dashboard.html', icon: '<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>' },
            { id: 'documents', label: 'Documents', href: '/documents.html', icon: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>' },
            { id: 'entities', label: 'Entities', href: '/entities.html', icon: '<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/>' },
            { id: 'upload', label: 'Upload', href: '/upload.html', icon: '<path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>' },
        ]},
        { group: 'INTELLIGENCE', items: [
            { id: 'copilot', label: 'Copilot', href: '/copilot.html', icon: '<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/>' },
            { id: 'graph', label: 'Knowledge Graph', href: '/graph.html', icon: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>' },
            { id: 'analytics', label: 'Analytics', href: '/analytics.html', icon: '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>' },
        ]},
        { group: 'RISK', items: [
            { id: 'vendors', label: 'Vendors', href: '/vendors.html', icon: '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>' },
            { id: 'regulatory', label: 'Regulatory', href: '/regulatory.html', icon: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>' },
        ]},
        { group: 'ACCOUNT', items: [
            { id: 'settings', label: 'Settings', href: '/settings.html', icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>' },
        ]},
    ];

    let html = `
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-header">
            <a href="/dashboard.html" class="sidebar-logo">
                <div class="sidebar-logo-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                        <path d="M9 12l2 2 4-4"/>
                    </svg>
                </div>
                <span class="sidebar-logo-text">ComplyChip</span>
            </a>
        </div>
        <nav class="sidebar-nav">`;

    for (const group of navItems) {
        html += `<div class="sidebar-group"><div class="sidebar-group-label">${group.group}</div>`;
        for (const item of group.items) {
            const isActive = activePage === item.id;
            html += `<a href="${item.href}" class="sidebar-item${isActive ? ' active' : ''}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${item.icon}</svg>
                <span>${item.label}</span>
            </a>`;
        }
        html += `</div>`;
    }

    const avatarHtml = user.avatar_url
        ? `<div class="sidebar-avatar-wrap"><img src="${user.avatar_url}" alt="${user.name || 'User'}" style="width:36px;height:36px;border-radius:50%;object-fit:cover;"><span class="sidebar-online-dot"></span></div>`
        : `<div class="sidebar-avatar-wrap"><div class="sidebar-avatar">${initials}</div><span class="sidebar-online-dot"></span></div>`;

    html += `</nav>
        <div class="sidebar-footer">
            <div class="sidebar-user">
                ${avatarHtml}
                <div class="sidebar-user-info">
                    <div class="sidebar-user-name">${user.name || 'Admin'}</div>
                    <div class="sidebar-user-role">
                        ${user.role === 'admin'
                            ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" style="vertical-align:-1px;margin-right:3px"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>'
                            : '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" style="vertical-align:-1px;margin-right:3px"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'}
                        ${user.role || 'viewer'}
                    </div>
                </div>
                <button class="btn-icon sidebar-logout" onclick="logout()" title="Sign out">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16"><path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                </button>
            </div>
        </div>
    </aside>`;

    return html;
}

// Topbar HTML generator
function renderTopbar(title, subtitle) {
    return `
    <header class="topbar">
        <div class="topbar-left">
            <button class="btn-icon sidebar-toggle" onclick="toggleSidebar()" id="sidebarToggle">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                    <line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>
                </svg>
            </button>
            <div>
                <h1 class="topbar-title">${title}</h1>
                ${subtitle ? `<p class="topbar-subtitle">${subtitle}</p>` : ''}
            </div>
        </div>
        <div class="topbar-right">
            <div class="topbar-search">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                <input type="text" placeholder="Search..." class="topbar-search-input" />
            </div>
        </div>
    </header>`;
}

// Initialize page layout
function initLayout(activePage, title, subtitle) {
    if (!requireAuth()) return false;

    // Insert sidebar before main content
    const sidebarEl = document.getElementById('sidebar-container');
    if (sidebarEl) sidebarEl.innerHTML = renderSidebar(activePage);

    const topbarEl = document.getElementById('topbar-container');
    if (topbarEl) topbarEl.innerHTML = renderTopbar(title, subtitle);

    // Restore sidebar collapsed state from localStorage
    const isCollapsed = localStorage.getItem('sidebar-collapsed') === 'true';
    if (isCollapsed) {
        const sidebar = document.getElementById('sidebar');
        const mainContent = document.querySelector('.main-content');
        const appLayout = document.querySelector('.app-layout');
        if (sidebar) sidebar.classList.add('collapsed');
        if (mainContent) mainContent.classList.add('sidebar-collapsed');
        if (appLayout) appLayout.classList.add('sidebar-collapsed');
    }

    return true;
}

// Toggle sidebar collapsed state
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.querySelector('.main-content');
    const appLayout = document.querySelector('.app-layout');
    if (sidebar) {
        sidebar.classList.toggle('collapsed');
        if (mainContent) mainContent.classList.toggle('sidebar-collapsed');
        if (appLayout) appLayout.classList.toggle('sidebar-collapsed');
        localStorage.setItem('sidebar-collapsed', sidebar.classList.contains('collapsed'));
    }
}

// Modal helper
function showModal(id) {
    const el = document.getElementById(id);
    if (el) { el.style.display = 'flex'; document.body.style.overflow = 'hidden'; }
}

function hideModal(id) {
    const el = document.getElementById(id);
    if (el) { el.style.display = 'none'; document.body.style.overflow = ''; }
}

// Render score ring SVG
function renderScoreRing(score, size = 120, strokeWidth = 10) {
    const radius = (size - strokeWidth) / 2;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (score / 100) * circumference;
    const color = getScoreColor(score);

    return `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="var(--border)" stroke-width="${strokeWidth}"/>
        <circle cx="${size/2}" cy="${size/2}" r="${radius}" fill="none" stroke="${color}" stroke-width="${strokeWidth}"
            stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" stroke-linecap="round"
            transform="rotate(-90 ${size/2} ${size/2})" style="transition: stroke-dashoffset 1s ease"/>
        <text x="${size/2}" y="${size/2 - 8}" text-anchor="middle" fill="var(--text-primary)" font-size="${size*0.22}" font-weight="700">${score}</text>
        <text x="${size/2}" y="${size/2 + 12}" text-anchor="middle" fill="var(--text-muted)" font-size="${size*0.09}" font-weight="500">${getScoreLabel(score)}</text>
    </svg>`;
}

// Loading spinner
function renderSpinner(size = 24) {
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" class="spinner">
        <circle cx="12" cy="12" r="10" fill="none" stroke="var(--accent)" stroke-width="3" stroke-dasharray="30 70" stroke-linecap="round">
            <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="1s" repeatCount="indefinite"/>
        </circle>
    </svg>`;
}

// Empty state
function renderEmptyState(icon, title, description, actionLabel, actionFn) {
    return `<div class="empty-state">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">${icon}</svg>
        <h3>${title}</h3>
        <p>${description}</p>
        ${actionLabel ? `<button class="btn btn-primary mt-4" onclick="${actionFn}">${actionLabel}</button>` : ''}
    </div>`;
}

// Pagination
function renderPagination(page, totalPages, onPageChange) {
    if (totalPages <= 1) return '';
    let html = '<div class="pagination">';
    html += `<button class="btn btn-ghost btn-sm" ${page <= 1 ? 'disabled' : ''} onclick="${onPageChange}(${page-1})">Prev</button>`;
    for (let i = 1; i <= totalPages; i++) {
        if (i === page) html += `<button class="btn btn-primary btn-sm">${i}</button>`;
        else if (i <= 3 || i > totalPages - 2 || Math.abs(i - page) <= 1) {
            html += `<button class="btn btn-ghost btn-sm" onclick="${onPageChange}(${i})">${i}</button>`;
        } else if (i === 4 || i === totalPages - 2) {
            html += `<span class="pagination-dots">...</span>`;
        }
    }
    html += `<button class="btn btn-ghost btn-sm" ${page >= totalPages ? 'disabled' : ''} onclick="${onPageChange}(${page+1})">Next</button>`;
    html += '</div>';
    return html;
}

// Confirmation dialog
function confirmAction(message) {
    return new Promise(resolve => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = `<div class="modal" style="max-width:400px">
            <div class="modal-header"><h3>Confirm</h3></div>
            <div class="modal-body"><p>${message}</p></div>
            <div class="modal-footer">
                <button class="btn btn-secondary" id="confirm-no">Cancel</button>
                <button class="btn btn-danger" id="confirm-yes">Confirm</button>
            </div>
        </div>`;
        document.body.appendChild(overlay);
        overlay.querySelector('#confirm-yes').onclick = () => { overlay.remove(); resolve(true); };
        overlay.querySelector('#confirm-no').onclick = () => { overlay.remove(); resolve(false); };
    });
}
