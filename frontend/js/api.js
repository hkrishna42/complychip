// Token management
const TOKEN_KEY = 'complychip_access_token';
const REFRESH_KEY = 'complychip_refresh_token';
const USER_KEY = 'complychip_user';

function getAccessToken() { return localStorage.getItem(TOKEN_KEY); }
function getRefreshToken() { return localStorage.getItem(REFRESH_KEY); }
function getUser() { try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; } }
function setTokens(access, refresh) { localStorage.setItem(TOKEN_KEY, access); if (refresh) localStorage.setItem(REFRESH_KEY, refresh); }
function setUser(user) { localStorage.setItem(USER_KEY, JSON.stringify(user)); }
function clearAuth() { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(REFRESH_KEY); localStorage.removeItem(USER_KEY); }
function isAuthenticated() { return !!getAccessToken(); }

// Auth guard - redirect to login if not authenticated
function requireAuth() {
    if (!isAuthenticated()) {
        window.location.href = '/';
        return false;
    }
    return true;
}

// API fetch wrapper with auth headers and token refresh
async function apiFetch(url, options = {}) {
    const token = getAccessToken();
    const headers = { 'Content-Type': 'application/json', ...options.headers };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    let res = await fetch(url, { ...options, headers });

    // Try token refresh on 401
    if (res.status === 401 && getRefreshToken()) {
        const refreshRes = await fetch('/auth/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: getRefreshToken() })
        });
        if (refreshRes.ok) {
            const data = await refreshRes.json();
            setTokens(data.access_token, data.refresh_token);
            headers['Authorization'] = `Bearer ${data.access_token}`;
            res = await fetch(url, { ...options, headers });
        } else {
            clearAuth();
            window.location.href = '/';
            return null;
        }
    }
    return res;
}

// Convenience methods
async function apiGet(url) { return apiFetch(url); }
async function apiPost(url, body) { return apiFetch(url, { method: 'POST', body: JSON.stringify(body) }); }
async function apiPut(url, body) { return apiFetch(url, { method: 'PUT', body: JSON.stringify(body) }); }
async function apiDelete(url) { return apiFetch(url, { method: 'DELETE' }); }

// Upload helper (no Content-Type header - let browser set multipart boundary)
async function apiUpload(url, formData) {
    const token = getAccessToken();
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return fetch(url, { method: 'POST', headers, body: formData });
}

// Track user activity (fire-and-forget)
function trackActivity(action, resourceType = '', resourceId = '', details = {}) {
    const token = getAccessToken();
    if (!token) return;
    fetch('/api/activity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
        body: JSON.stringify({ action, resource_type: resourceType, resource_id: resourceId, details })
    }).catch(() => {}); // silently ignore errors
}

// Auto-track page views
document.addEventListener('DOMContentLoaded', () => {
    if (isAuthenticated()) {
        const page = window.location.pathname.replace('.html', '').replace(/^\//, '') || 'login';
        trackActivity('page_view', 'page', page);
    }
});

// Session heartbeat — keeps session alive and detects revocations
let _heartbeatInterval = null;
function startSessionHeartbeat() {
    if (_heartbeatInterval) return;
    _heartbeatInterval = setInterval(async () => {
        if (!isAuthenticated()) return;
        try {
            const res = await apiFetch('/auth/heartbeat', { method: 'POST' });
            if (!res || res.status === 401) {
                clearInterval(_heartbeatInterval);
                _heartbeatInterval = null;
                clearAuth();
                showToast('Session expired. Please sign in again.', 'error', 5000);
                setTimeout(() => { window.location.href = '/'; }, 2000);
            }
        } catch (e) {
            // Network error — don't log out, just skip
        }
    }, 5 * 60 * 1000); // Every 5 minutes
}
// Start heartbeat on auth pages
document.addEventListener('DOMContentLoaded', () => {
    if (isAuthenticated()) startSessionHeartbeat();
});

// Logout with server-side session invalidation
async function logout() {
    try {
        await apiFetch('/auth/logout', { method: 'POST' });
    } catch (e) {} // continue even if server call fails
    trackActivity('logout', 'session');
    clearAuth();
    window.location.href = '/';
}

// Format helpers
function formatDate(dateStr) {
    if (!dateStr) return '\u2014';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function formatNumber(n) {
    if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n/1000).toFixed(1) + 'K';
    return n?.toString() || '0';
}

function daysFromNow(dateStr) {
    if (!dateStr) return null;
    const diff = new Date(dateStr) - new Date();
    return Math.ceil(diff / (1000 * 60 * 60 * 24));
}

function getScoreColor(score) {
    if (score >= 80) return 'var(--success)';
    if (score >= 60) return 'var(--warning)';
    return 'var(--danger)';
}

function getScoreLabel(score) {
    if (score >= 80) return 'Good';
    if (score >= 60) return 'Fair';
    return 'At Risk';
}

function getRiskPill(level) {
    const map = { low: 'pill-success', medium: 'pill-warning', high: 'pill-danger', critical: 'pill-danger' };
    return map[level] || 'pill-neutral';
}

function getStatusPill(status) {
    const map = { compliant: 'pill-success', active: 'pill-success', warning: 'pill-warning', pending: 'pill-warning', expired: 'pill-danger', 'non-compliant': 'pill-danger', archived: 'pill-neutral' };
    return map[status] || 'pill-neutral';
}

// Debounce utility
function debounce(fn, delay = 300) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

// Toast notifications (works with components.js toast container)
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container') || createToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            ${type === 'success' ? '<path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>' :
              type === 'error' ? '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>' :
              '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>'}
        </svg>
        <span>${message}</span>
    `;
    container.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transform = 'translateX(100%)'; setTimeout(() => toast.remove(), 300); }, duration);
}

function createToastContainer() {
    const c = document.createElement('div');
    c.id = 'toast-container';
    c.className = 'toast-container';
    document.body.appendChild(c);
    return c;
}
