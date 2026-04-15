/**
 * CAM — Background Service Worker
 * ===========================================
 * 
 * Manifest V3 background script. Handles:
 * 1. Receiving auto-capture data from content scripts
 * 2. Processing and enriching captured content
 * 3. Sending to CAM backend (auto-clip endpoint)
 * 4. Managing capture queue and retry logic
 * 5. Context menu integration ("Save to Wiki")
 * 6. Badge count showing captures today
 * 
 * No UI — runs silently in the background.
 */

// ============================================================
// CONFIGURATION
// ============================================================

const DEFAULT_SETTINGS = {
    // Backend server
    serverUrl: 'http://localhost:9877',   // Auto-capture endpoint
    
    // Capture behavior
    autoCaptureEnabled: true,
    showNotifications: true,
    
    // Queue management
    maxQueueSize: 50,
    retryAttempts: 3,
    retryDelayMs: 5000,
    
    // Rate limiting
    maxCapturesPerHour: 30,
};

// ============================================================
// STATE
// ============================================================

const state = {
    settings: { ...DEFAULT_SETTINGS },
    
    // Capture queue (for offline / retry)
    queue: [],
    
    // Stats
    todayCaptures: [],
    totalCaptures: 0,
    failedCaptures: 0,
    
    // Page status cache (for popup display)
    pageStatus: new Map(), // tabId → status info
    
    // Retry timers
    retryTimers: new Map(),
};

// ============================================================
// INITIALIZATION
// ============================================================

chrome.runtime.onInstalled.addListener(async () => {
    console.log('[CAM] Extension installed');
    
    // Load settings from storage
    await loadSettings();
    
    // Set up context menu
    setupContextMenu();
    
    // Initialize badge
    updateBadge();
    
    // Process any queued items from previous session
    processQueue();
});

chrome.runtime.onStartup.addListener(async () => {
    await loadSettings();
    setupContextMenu();
    updateBadge();
    processQueue();
});

async function loadSettings() {
    try {
        const stored = await chrome.storage.local.get('cw_settings');
        if (stored.cw_settings) {
            state.settings = { ...DEFAULT_SETTINGS, ...stored.cw_settings };
        }
    } catch(e) {}
}

function saveSettings() {
    return chrome.storage.local.set({ cw_settings: state.settings }).catch(() => {});
}

// ============================================================
// CONTEXT MENU: "Save to Wiki" (manual fallback)
// ============================================================

function setupContextMenu() {
    try {
        chrome.contextMenus.create({
            id: 'cw-save-page',
            title: '🧠 Save to CAM',
            contexts: ['page', 'selection'],
        });
        
        chrome.contextMenus.create({
            id: 'cw-save-link',
            title: '🧠 Save link to CAM',
            contexts: ['link'],
        });
        
        chrome.contextMenus.onClicked.addListener(handleContextMenu);
    } catch(e) {
        // Context menus may not be available in all environments
    }
}

async function handleContextMenu(info, tab) {
    if (info.menuItemId === 'cw-save-page' || info.menuItemId === 'cw-save-link') {
        const url = info.linkUrl || info.pageUrl || tab?.url;
        const selectedText = info.selectionText || '';
        
        // Send message to content script to force-capture
        if (tab && tab.id) {
            try {
                await chrome.tabs.sendMessage(tab.id, { type: 'forceCapture' });
            } catch(e) {
                // Content script might not be injected — use API instead
                await saveViaAPI(url, selectedText, tab?.title || '', 'context_menu');
            }
        } else {
            await saveViaAPI(url, selectedText, '', 'context_menu');
        }
    }
}

// ============================================================
// MESSAGE HANDLER: Receive from content script & popup
// ============================================================

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    handleAsyncMessage(msg, sender).then(sendResponse).catch(err => {
        sendResponse({ error: err.message });
    });
    return true; // Keep channel open for async response
});

async function handleAsyncMessage(msg, sender) {
    switch(msg.type) {
        
        case 'autoCapture':
            // === MAIN PIPELINE: Content script detected valuable content ===
            return await handleAutoCapture(msg.data, sender.tab);
            
        case 'pageAnalyzed':
            // Content script finished initial analysis
            if (sender.tab) {
                state.pageStatus.set(sender.tab.id, {
                    ...msg.data,
                    updatedAt: Date.now(),
                });
            }
            return { ok: true };
            
        case 'scoreUpdate':
            // Periodic score updates for popup display
            if (sender.tab) {
                const existing = state.pageStatus.get(sender.tab.id) || {};
                state.pageStatus.set(sender.tab.id, {
                    ...existing,
                    score: msg.data.score,
                    dimensions: msg.data.dimensions,
                    scrollDepth: msg.data.scrollDepth,
                    dwellSeconds: msg.data.dwellSeconds,
                    updatedAt: Date.now(),
                });
            }
            return { ok: true };
            
        case 'getStatus':
            // Popup asking for current state
            return getExtensionStatus(sender.tab?.id);
            
        case 'getSettings':
            return { settings: state.settings };
            
        case 'updateSettings':
            state.settings = { ...state.settings, ...msg.settings };
            await saveSettings();
            return { ok: true, settings: state.settings };
            
        case 'forceCapture':
            // Manual force-capture from popup
            if (sender.tab) {
                try {
                    await chrome.tabs.sendMessage(sender.tab.id, msg);
                    return { ok: true };
                } catch(e) {
                    return { error: 'Cannot reach page' };
                }
            }
            return { error: 'No active tab' };
            
        case 'clearStats':
            state.todayCaptures = [];
            state.failedCaptures = 0;
            updateBadge();
            return { ok: true };
            
        default:
            return { error: 'Unknown message type' };
    }
}

// ============================================================
// CORE: Handle Auto-Captured Content
// ============================================================

/**
 * Main pipeline when content script auto-detects valuable content
 */
async function handleAutoCapture(captureData, tab) {
    if (!state.settings.autoCaptureEnabled) {
        return { skipped: true, reason: 'auto_capture_disabled' };
    }
    
    // Rate limit check
    const recentCount = state.todayCaptures.filter(
        t => Date.now() - t < 3600000 // Last hour
    ).length;
    
    if (recentCount >= state.settings.maxCapturesPerHour) {
        return { skipped: true, reason: 'rate_limited' };
    }
    
    // Enrich with additional metadata
    captureData = enrichCaptureData(captureData, tab);
    
    // Add to today's stats
    state.todayCaptures.push(Date.now());
    state.totalCaptures++;
    updateBadge();
    
    // Try to send immediately; queue on failure
    try {
        const result = await sendToBackend(captureData);
        return { ok: true, result };
    } catch(e) {
        console.error('[CAM] Backend unavailable, queuing:', e.message);
        addToQueue(captureData);
        scheduleRetry(captureData);
        return { queued: true, reason: 'backend_unavailable' };
    }
}

/**
 * Enrich capture data with additional context before sending to backend
 */
function enrichCaptureData(data, tab) {
    return {
        ...data,
        
        // Tab metadata
        tabId: tab?.id,
        tabTitle: tab?.title,
        
        // Browser metadata
        userAgent: navigator.userAgent,
        extensionVersion: chrome.runtime.getManifest().version,
        
        // Timestamp
        processedAt: new Date().toISOString(),
    };
}

// ============================================================
// BACKEND COMMUNICATION
// ============================================================

/**
 * Send captured content to CAM backend
 */
async function sendToBackend(captureData) {
    const url = `${state.settings.serverUrl}/auto-clip`;
    
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Source': 'cam-extension',
            'X-Version': chrome.runtime.getManifest().version,
        },
        body: JSON.stringify(captureData),
    });
    
    if (!response.ok) {
        throw new Error(`Backend returned ${response.status}: ${await response.text()}`);
    }
    
    const result = await response.json();
    
    // Show desktop notification on success
    if (state.settings.showNotifications) {
        showDesktopNotification(captureData, result);
    }
    
    return result;
}

/**
 * Fallback: save via simple URL-based API (no content extraction)
 */
async function saveViaAPI(url, selectedText, title, source) {
    const apiUrl = `${state.settings.serverUrl}/auto-clip`;
    
    try {
        await fetch(apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url,
                title: title || url,
                content: selectedText || '',
                trigger: source || 'api_fallback',
                capturedAt: new Date().toISOString(),
            }),
        });
        
        state.todayCaptures.push(Date.now());
        updateBadge();
    } catch(e) {
        console.error('[CAM] API fallback failed:', e.message);
    }
}

// ============================================================
// QUEUE & RETRY SYSTEM
// ============================================================

function addToQueue(item) {
    if (state.queue.length >= state.settings.maxQueueSize) {
        state.queue.shift(); // Remove oldest
    }
    state.queue.push({ item, attempts: 0, addedAt: Date.now() });
}

async function processQueue() {
    while(state.queue.length > 0) {
        const entry = state.queue[0];
        
        try {
            await sendToBackend(entry.item);
            state.queue.shift(); // Success, remove
        } catch(e) {
            entry.attempts++;
            if (entry.attempts >= state.settings.retryAttempts) {
                state.queue.shift();
                state.failedCaptures++;
                console.error('[CAM] Gave up after retries:', entry.item.title);
            } else {
                break; // Wait for retry timer
            }
        }
    }
}

function scheduleRetry(item) {
    // Avoid duplicate retries for same URL
    const key = item.url || item.title;
    if (state.retryTimers.has(key)) return;
    
    const timer = setTimeout(async () => {
        state.retryTimers.delete(key);
        
        const entry = state.queue.find(e => 
            e.item.url === item.url || e.item.title === item.title
        );
        
        if (entry) {
            try {
                await sendToBackend(entry.item);
                state.queue = state.queue.filter(e => e !== entry);
            } catch(e) {
                entry.attempts++;
                if (entry.attempts < state.settings.retryAttempts) {
                    scheduleRetry(item); // Exponential backoff
                }
            }
        }
    }, state.settings.retryDelayMs * (item.attempts + 1)); // Linear backoff
    
    state.retryTimers.set(key, timer);
}

// ============================================================
// DESKTOP NOTIFICATIONS
// ============================================================

function showDesktopNotification(captureData, backendResult) {
    try {
        chrome.notifications.create(`cw-${Date.now()}`, {
            type: 'basic',
            iconUrl: 'icons/icon128.png',
            title: '🧠 Saved to CAM',
            message: captureData.title || captureData.url,
            contextMessage: `Score: ${captureData.score} · Triggered by: ${captureData.trigger}`,
            priority: 1,
        });
    } catch(e) {
        // Notifications may not be available in all browsers
    }
}

// ============================================================
// BADGE: Show capture count on icon
// ============================================================

function updateBadge() {
    const count = state.todayCaptures.length;
    
    if (count > 0) {
        chrome.action.setBadgeText({ text: count.toString() });
        chrome.action.setBadgeBackgroundColor({ color: '#22c55e' });
        chrome.action.setBadgeTextColor({ color: '#ffffff' });
    } else {
        chrome.action.setBadgeText({ text: '' });
    }
}

// Reset daily badge count at midnight
chrome.alarms?.create('dailyReset', { periodInMinutes: 24 * 60 });
chrome.alarms?.onAlarm.addListener((alarm) => {
    if (alarm.name === 'dailyReset') {
        state.todayCaptures = [];
        updateBadge();
    }
});

// ============================================================
// STATUS FOR POPUP
// ============================================================

async function getExtensionStatus(tabId) {
    const pageState = state.pageStatus.get(tabId);
    
    return {
        version: chrome.runtime.getManifest().version,
        autoCaptureEnabled: state.settings.autoCaptureEnabled,
        serverUrl: state.settings.serverUrl,
        isConnected: false, // Will be checked separately
        
        // Today's stats
        todayCount: state.todayCaptures.length,
        totalCount: state.totalCaptures,
        failedCount: state.failedCaptures,
        queueSize: state.queue.length,
        
        // Current page (if available)
        currentPage: pageState || null,
    };
}

// ============================================================
// TAB CLEANUP: Remove stale entries from pageStatus
// ============================================================

chrome.tabs.onRemoved.addListener((tabId) => {
    state.pageStatus.delete(tabId);
});

// Clean up old entries every 5 minutes
setInterval(() => {
    const cutoff = Date.now() - 10 * 60 * 1000; // 10 minutes
    for (const [tabId, data] of state.pageStatus.entries()) {
        if (data.updatedAt < cutoff) {
            state.pageStatus.delete(tabId);
        }
    }
}, 5 * 60 * 1000);

console.log('[CAM] Background service worker loaded');
