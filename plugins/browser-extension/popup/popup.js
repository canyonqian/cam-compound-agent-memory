/**
 * CAM — Popup Script
 * ==============================
 * 
 * Popup UI logic. Shows:
 * - Current page analysis status & score
 * - Real-time reading behavior stats
 * - Force-capture button
 * - Auto-capture toggle
 * - Recent captures list
 */

document.addEventListener('DOMContentLoaded', init);

// DOM Elements
const els = {
    statusDot: document.getElementById('statusDot'),
    statusText: document.getElementById('statusText'),
    todayCount: document.getElementById('todayCount'),
    pageTitle: document.getElementById('pageTitle'),
    scoreFg: document.getElementById('scoreFg'),
    scoreValue: document.getElementById('scoreValue'),
    scoreDecision: document.getElementById('scoreDecision'),
    scoreHint: document.getElementById('scoreHint'),
    dimBars: document.getElementById('dimBars'),
    statScroll: document.getElementById('statScroll'),
    statDwell: document.getElementById('statDwell'),
    statHighlights: document.getElementById('statHighlights'),
    btnForceCapture: document.getElementById('btnForceCapture'),
    btnSettings: document.getElementById('btnSettings'),
    autoCaptureToggle: document.getElementById('autoCaptureToggle'),
    recentList: document.getElementById('recentList'),
    versionNum: document.getElementById('versionNum'),
};

const CIRCLE_CIRCUMFERENCE = 2 * Math.PI * 22; // r=22

async function init() {
    bindEvents();
    await loadStatus();
    
    // Refresh every 2 seconds while popup is open
    setInterval(loadStatus, 2000);
}

function bindEvents() {
    els.btnForceCapture.addEventListener('click', handleForceCapture);
    els.btnSettings.addEventListener('click', () => chrome.runtime.openOptionsPage?.());
    els.autoCaptureToggle.addEventListener('change', handleAutoCaptureToggle);
}

// ========== Data Loading ==========

async function loadStatus() {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        
        if (!tab || !tab.id) {
            showNoTab();
            return;
        }
        
        // Get extension-wide status from background
        let bgStatus = {};
        try {
            bgStatus = await sendMessage({ type: 'getStatus' });
        } catch(e) {}
        
        updateStatusBar(bgStatus);
        updateTodayCount(bgStatus);
        updateVersion(bgStatus);
        
        // Get page-specific status from content script
        let pageStatus = null;
        try {
            pageStatus = await chrome.tabs.sendMessage(tab.id, { type: 'getStatus' });
        } catch(e) {
            // Content script not available for this page (e.g., chrome:// pages)
            showUnsupported(tab);
            return;
        }
        
        updatePageCard(pageStatus, tab);
        
    } catch(e) {
        console.error('[CW Popup] Load error:', e);
    }
}

function sendMessage(msg) {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage(msg, resolve);
    });
}

// ========== UI Updaters ==========

function updateStatusBar(status) {
    const connected = checkConnection(status);
    
    els.statusDot.className = 'status-dot ' + (connected ? 'connected' : 'disconnected');
    els.statusText.textContent = connected 
        ? 'Wiki Server Connected' 
        : 'Server Offline (queued)';
}

function checkConnection(status) {
    return !status || status.queueSize === 0; // Simplified — could ping server
}

function updateTodayCount(status) {
    const count = status?.todayCount || 0;
    els.todayCount.textContent = `${count} today`;
}

function updateVersion(status) {
    if (status?.version) {
        els.versionNum.textContent = status.version;
    }
}

function updatePageCard(pageStatus, tab) {
    if (!pageStatus) {
        els.pageTitle.textContent = tab.title || 'Unknown Page';
        els.scoreValue.textContent = '--';
        els.scoreDecision.textContent = 'Not analyzing';
        els.scoreDecision.className = 'score-decision ignore';
        return;
    }
    
    // Title
    els.pageTitle.textContent = pageStatus.pageAnalysis?.title || tab.title || '';
    
    // Score
    const score = pageStatus.currentScore || 0;
    updateScoreRing(score);
    updateScoreDecision(score);
    updateDimensionBars(pageStatus.scoreHistory);
    
    // Behavior
    const behavior = pageStatus.behavior || {};
    els.statScroll.textContent = `${behavior.scrollDepth || 0}%`;
    els.statDwell.textContent = formatTime(behavior.dwellSeconds || 0);
    els.statHighlights.textContent = behavior.highlights || 0;
}

/**
 * Update the circular score ring with animated fill
 */
function updateScoreRing(score) {
    const clampedScore = Math.max(0, Math.min(100, score));
    const offset = CIRCLE_CIRCUMFERENCE * (1 - clampedScore / 100);
    
    els.scoreFg.style.strokeDashoffset = offset;
    els.scoreValue.textContent = clampedScore;
    
    // Color based on score
    let color = '#64748b'; // gray
    if (clampedScore >= 80) color = '#22c55e';      // green
    else if (clampedScore >= 60) color = '#facc15';  // yellow
    else if (clampedScore >= 40) color = '#f97316';  // orange
    else color = '#64748b';                           // gray
    
    els.scoreFg.style.stroke = color;
    els.scoreValue.style.color = color;
}

function updateScoreDecision(score) {
    let text, cls, hint;
    
    if (score >= 80) {
        text = '⚡ Will Auto-Capture';
        cls = 'capture';
        hint = 'High quality + engaged reading';
    } else if (score >= 60) {
        text = '🔍 Observing...';
        cls = 'observe';
        hint = 'May auto-capture when you leave';
    } else if (score >= 40) {
        text = '💤 Low Engagement';
        cls = 'ignore';
        hint = 'Use Force Save to capture anyway';
    } else {
        text = '❌ Unlikely Worth Saving';
        cls = 'ignore';
        hint = 'Looks like navigation or short content';
    }
    
    els.scoreDecision.textContent = text;
    els.scoreDecision.className = `score-decision ${cls}`;
    els.scoreHint.textContent = hint;
}

/**
 * Render dimension bars showing the 6 scoring dimensions
 */
function updateDimensionBars(scoreHistory) {
    // Get latest scores
    const latest = scoreHistory && scoreHistory.length > 0 
        ? scoreHistory[scoreHistory.length - 1]?.dimensions 
        : null;
    
    if (!latest) {
        els.dimBars.innerHTML = '<span style="font-size:10px;color:#475569">Waiting for data...</span>';
        return;
    }
    
    const dims = [
        { key: 'density', icon: '📊', label: 'Density', weight: 25 },
        { key: 'depth',   icon: '📏', label: 'Depth',   weight: 20 },
        { key: 'dwell',   icon: '⏱️', label: 'Dwell',   weight: 20 },
        { key: 'trust',   icon: '🔒', label: 'Trust',   weight: 15 },
        { key: 'interaction', icon: '👆', label: 'Action',  weight: 10 },
        { key: 'quality', icon: '⭐', label: 'Quality', weight: 10 },
    ];
    
    els.dimBars.innerHTML = dims.map(d => `
        <div class="dim-bar">
            <span>${d.icon}</span>
            <div class="track">
                <div class="fill" style="width:${latest[d.key]}%;background:${barColor(latest[d.key])}"></div>
            </div>
            <span>${latest[d.key]}</span>
        </div>
    `).join('');
}

function barColor(value) {
    if (value >= 70) return '#22c55e';
    if (value >= 45) return '#facc15';
    if (value >= 20) return '#f97316';
    return '#475569';
}

// ========== Event Handlers ==========

async function handleForceCapture() {
    els.btnForceCapture.disabled = true;
    els.btnForceCapture.textContent = '⏳ Saving...';
    
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (tab?.id) {
            await chrome.tabs.sendMessage(tab.id, { type: 'forceCapture' });
        }
        
        // Visual feedback
        els.btnForceCapture.textContent = '✅ Saved!';
        setTimeout(() => {
            els.btnForceCapture.disabled = false;
            els.btnForceCapture.textContent = '💾 Force Save Now';
        }, 1500);
    } catch(e) {
        els.btnForceCapture.textContent = '❌ Failed';
        setTimeout(() => {
            els.btnForceCapture.disabled = false;
            els.btnForceCapture.textContent = '💾 Force Save Now';
        }, 1500);
    }
}

async function handleAutoCaptureToggle() {
    const enabled = els.autoCaptureToggle.checked;
    await sendMessage({
        type: 'updateSettings',
        settings: { autoCaptureEnabled: enabled }
    });
}

// ========== Special States ==========

function showNoTab() {
    els.pageTitle.textContent = 'No active tab';
    els.scoreValue.textContent = '--';
    els.scoreDecision.textContent = 'N/A';
    els.scoreDecision.className = 'score-decision ignore';
}

function showUnsupported(tab) {
    els.pageTitle.textContent = tab?.title || 'Unsupported page';
    els.scoreValue.textContent = '—';
    els.scoreDecision.textContent = 'Cannot analyze this page type';
    els.scoreDecision.className = 'score-decision ignore';
    els.scoreHint.textContent = 'Try on a regular webpage';
}

// ========== Utilities ==========

function formatTime(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const min = Math.floor(seconds / 60);
    const sec = seconds % 60;
    return `${min}m${sec}s`;
}
