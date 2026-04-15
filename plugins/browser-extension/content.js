/**
 * CAM — Content Script
 * =================================
 * 
 * Injected into every page. Runs silently in background:
 * 1. Analyzes page content quality (density, readability)
 * 2. Tracks user reading behavior (scroll depth, dwell time)
 * 3. Computes value score using multi-dimensional scoring engine
 * 4. Auto-captures when score exceeds threshold — NO user action needed
 * 
 * Communication with background.js via chrome.runtime.sendMessage()
 */

(function() {
    'use strict';

    // ============================================================
    // CONFIGURATION
    // ============================================================
    
    const DEFAULT_CONFIG = {
        autoCapture: true,
        minScoreThreshold: 60,
        observeIntervalMs: 30000,     // Re-evaluate every 30s
        minDwellTimeMs: 15000,         // Must stay at least 15s
        minContentLength: 500,         // Skip very short pages
        maxContentLength: 200000,      // Skip absurdly long pages
        notificationDurationMs: 4000,  // Toast duration
        enableNotifications: true,
        
        // Domain trust scores (-100 to +100)
        domainTrustBoosts: {
            'arxiv.org': 30,
            'paperswithcode.com': 25,
            'github.com': 20,
            'medium.com': 10,
            'substack.com': 10,
            'dev.to': 15,
            'hashnode.com': 12,
            'towardsdatascience.com': 18,
            'distill.pub': 35,
            'lesswrong.com': 25,
            'bbc.com': 20,
            'economist.com': 22,
            'nytimes.com': 18,
            'wikipedia.org': 15,
            'zhuanlan.zhihu.com': 15,
            'sspai.com': 12,
            'juejin.cn': 8,
            'csdn.net': 5,
            'segmentfault.com': 8,
            'developer.aliyun.com': 12,
            'woshipm.com': 8,
        },
        
        // Domain penalties (likely not worth saving)
        domainPenalties: {
            'google.com': -50,
            'google.co.jp': -50,
            'bing.com': -50,
            'baidu.com': -40,
            'facebook.com': -45,
            'twitter.com': -30,
            'x.com': -30,
            'instagram.com': -45,
            'tiktok.com': -45,
            'youtube.com': -35,
            'amazon.com': -40,
            'taobao.com': -40,
            'jd.com': -35,
            'pinterest.com': -30,
            'reddit.com': -10,  // Reddit can have good content, mild penalty
        },
        
        // URL patterns to skip (regex)
        skipPatterns: [
            /^https?:\/\/(www\.)?google\.(com|co|jp|cn)/i,
            /^https?:\/\/(www\.)?bing\.com/i,
            /^https?:\/\/(www\.)?baidu\.com/i,
            /^https?:\/\/(mail\.|inbox|outlook)/i,
            /^https?:\/\/.*\/(login|signin|signup|register)/i,
            /^data:/i,
            /^chrome-extension:/i,
            /\/(api\/|feed\/|rss\/|sitemap\.xml)/i,
        ],
    };

    // ============================================================
    // STATE
    // ============================================================
    
    const state = {
        config: { ...DEFAULT_CONFIG },
        isActive: false,
        isAnalyzing: false,
        hasCaptured: false,
        
        // Reading behavior tracking
        scrollData: {
            maxScrollRatio: 0,
            scrollTimestamps: [],       // [{ratio, time}]
            totalScrollDistance: 0,
            lastScrollY: 0,
        },
        dwellData: {
            startTime: Date.now(),
            activeTimeMs: 0,           // Time tab was actually visible
            lastActiveTime: Date.now(),
            focusGainedCount: 0,
            blurEvents: [],
        },
        interactionData: {
            selections: [],             // Text selection events
            copyEvents: 0,
            linkClicks: 0,
            highlights: 0,
        },
        
        // Analysis results
        pageAnalysis: null,
        currentScore: 0,
        scoreHistory: [],
        observerTimer: null,
        
        // Notification element
        toastElement: null,
    };

    // ============================================================
    // INITIALIZATION
    // ============================================================
    
    async function init() {
        // Load config from storage
        try {
            const stored = await chrome.storage.local.get('cw_config');
            if (stored.cw_config) {
                state.config = { ...DEFAULT_CONFIG, ...stored.cw_config };
            }
        } catch(e) {}
        
        // Quick check: should we even analyze this page?
        if (shouldSkipPage()) {
            return;
        }
        
        // Start analysis
        state.isActive = true;
        state.dwellData.startTime = Date.now();
        state.dwellData.lastActiveTime = Date.now();
        
        // Initial content analysis (async, non-blocking)
        requestIdleCallback(() => analyzePage(), { timeout: 3000 });
        
        // Start tracking reading behavior
        startBehaviorTracking();
        
        // Start periodic re-evaluation
        state.observerTimer = setInterval(
            () => evaluateAndMaybeCapture(), 
            state.config.observeIntervalMs
        );
        
        // Also evaluate on key events
        document.addEventListener('visibilitychange', onVisibilityChange);
        window.addEventListener('beforeunload', onPageLeave);
        
        // Listen for messages from popup/background
        chrome.runtime.onMessage.addListener(onMessage);
        
        console.log('[CAM] Smart capture activated for:', window.location.href);
    }

    function shouldSkipPage() {
        const url = window.location.href;
        
        // Check skip patterns
        for (const pattern of state.config.skipPatterns) {
            if (pattern.test(url)) return true;
        }
        
        // Check if it's a special page
        if (document.documentElement.childElementCount < 3) return true;
        
        return false;
    }

    // ============================================================
    // CONTENT ANALYSIS ENGINE
    // ============================================================
    
    /**
     * Full page analysis — runs once on load, then incrementally updates
     */
    function analyzePage() {
        if (state.isAnalyzing) return;
        state.isAnalyzing = true;
        
        try {
            const result = {
                url: window.location.href,
                title: document.title,
                
                // Basic metrics
                totalTextLength: 0,
                bodyTextLength: 0,
                wordCount: 0,
                paragraphCount: 0,
                linkCount: 0,
                imageCount: 0,
                codeBlockCount: 0,
                headingCount: 0,
                listCount: 0,
                
                // Quality indicators
                contentDensity: 0,          // bodyText / totalText
                readabilityScore: 0,         // 0-100
                hasMainContent: false,
                estimatedReadTimeMinutes: 0,
                
                // Metadata extraction
                author: extractAuthor(),
                publishDate: extractPublishDate(),
                domain: window.location.hostname,
                contentType: detectContentType(),
                
                // Readability article (if applicable)
                article: null,
                
                // Timestamp
                analyzedAt: Date.now(),
            };
            
            // === Extract basic metrics ===
            const bodyText = getBodyText();
            const allText = document.body ? document.body.innerText : '';
            
            result.totalTextLength = allText.length;
            result.bodyTextLength = bodyText.length;
            result.wordCount = countWords(bodyText);
            result.paragraphCount = countParagraphs();
            result.linkCount = document.querySelectorAll('a').length;
            result.imageCount = document.querySelectorAll('img').length;
            result.codeBlockCount = document.querySelectorAll('pre, code').length;
            result.headingCount = document.querySelectorAll('h1, h2, h3, h4, h5, h6').length;
            result.listCount = document.querySelectorAll('ol, ul').length;
            
            // === Content density ===
            result.contentDensity = result.totalTextLength > 0 
                ? Math.round((result.bodyTextLength / result.totalTextLength) * 100) 
                : 0;
            
            // === Estimated read time ===
            result.estimatedReadTimeMinutes = Math.ceil(result.wordCount / 200); // 200 wpm avg
            
            // === Try Readability extraction ===
            try {
                if (typeof Readability !== 'undefined') {
                    const documentClone = document.cloneNode(true);
                    const reader = new Readability(documentClone);
                    const article = reader.parse();
                    
                    if (article && article.textContent && article.textContent.length > 200) {
                        result.article = article;
                        result.hasMainContent = true;
                        
                        // Use Readability's text as the "body" for scoring
                        result.readabilityScore = calculateReadabilityQuality(article);
                    }
                }
            } catch(e) {
                // Readability failed, fall back to simple heuristics
            }
            
            // If no Readability article, use fallback detection
            if (!result.hasMainContent) {
                result.hasMainContent = result.contentDensity > 30 
                    && result.bodyTextLength > state.config.minContentLength;
            }
            
            state.pageAnalysis = result;
            
            // Send initial analysis to background
            sendMessageToBackground({
                type: 'pageAnalyzed',
                data: result
            });
            
        } catch(e) {
            console.error('[CAM] Analysis error:', e);
        } finally {
            state.isAnalyzing = false;
        }
    }

    /**
     * Get the main body text, excluding nav/sidebar/footer noise
     */
    function getBodyText() {
        // Try common content selectors first
        const selectors = [
            'article', '[role="main"]', 'main', '.post-content', '.article-content',
            '.entry-content', '.content-body', '#content', '.markdown-body',
            '.ProseMirror', '.ql-editor', '.rich_media_content', '#js_content',
            '[itemprop="articleBody"]', '.article-body', '.story-body'
        ];
        
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el && el.innerText.length > 300) {
                return cleanText(el.innerText);
            }
        }
        
        // Fallback: remove known-noise elements and get remaining text
        const clone = document.body.cloneNode(true);
        const noiseSelectors = [
            'nav', 'header', 'footer', 'aside', '.sidebar', '.navigation',
            '.menu', '.navbar', '.footer', '.comments', '.comment-section',
            '.related-posts', '.recommendations', '.share-buttons',
            '.social-share', '.ads', '.ad-', '[class*="advertisement"]',
            'script', 'style', 'noscript', 'svg', 'canvas'
        ];
        
        noiseSelectors.forEach(sel => {
            clone.querySelectorAll(sel).forEach(el => el.remove());
        });
        
        return cleanText(clone.innerText || '');
    }

    function cleanText(text) {
        return text
            .replace(/\s+/g, ' ')
            .replace(/^\s+|\s+$/g, '')
            .trim();
    }

    function countWords(text) {
        // Handle both CJK and Latin text
        const cjkChars = (text.match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;
        const latinWords = text.split(/\s+/).filter(w => /[a-zA-Z]/.test(w)).length;
        return cjkChars + latinWords;
    }

    function countParagraphs() {
        return document.querySelectorAll('p').length;
    }

    /**
     * Calculate quality score for a Readability article
     */
    function calculateReadabilityQuality(article) {
        if (!article) return 0;
        
        let score = 50; // Base score
        
        // Length bonus (longer articles tend to be higher quality)
        const len = article.textContent.length;
        if (len > 3000) score += 20;
        else if (len > 1500) score += 15;
        else if (len > 800) score += 10;
        else if (len > 400) score += 5;
        
        // Structure bonus
        if (article.textContent.includes('\n\n')) score += 5; // Has paragraphs
        
        return Math.min(100, Math.max(0, score));
    }

    // ============================================================
    // METADATA EXTRACTION
    // ============================================================
    
    function extractAuthor() {
        // Try meta tags
        const metaSelectors = [
            'meta[name="author"]', 'meta[property="article:author"]',
            'meta[name="dc.creator"]', '[rel="author"]',
            '.author-name', '.byline', '.post-author', '.writer'
        ];
        
        for (const sel of metaSelectors) {
            const el = document.querySelector(sel);
            if (el) {
                const val = el.getAttribute('content') || el.getAttribute('href') || el.innerText;
                if (val && val.trim()) return val.trim().substring(0, 100);
            }
        }
        
        return '';
    }

    function extractPublishDate() {
        const dateSelectors = [
            'meta[property="article:published_time"]',
            'meta[name="date"]', 'meta[name="DC.date"]',
            'time[datetime]', '.publish-date', '.date', '.post-date',
            'time.published'
        ];
        
        for (const sel of dateSelectors) {
            const el = document.querySelector(sel);
            if (el) {
                let val = el.getAttribute('content') || el.getAttribute('datetime') || el.innerText;
                if (val) {
                    const parsed = new Date(val);
                    if (!isNaN(parsed.getTime())) return parsed.toISOString();
                    return val.trim().substring(0, 50);
                }
            }
        }
        
        return '';
    }

    function detectContentType() {
        const url = window.location.href.toLowerCase();
        const title = document.title.toLowerCase();
        const html = document.documentElement.innerHTML.toLowerCase();
        
        // Check for known patterns
        if (/arxiv\.org/.test(url)) return 'paper';
        if (/github\.com.*\/(readme|wiki|issues|discussions)/.test(url)) return 'code';
        if (/youtube\.com|youtu.be/.test(url)) return 'video';
        
        // HTML hints
        if (html.includes('article') || html.includes('post-content')) return 'article';
        if (html.includes('book') || html.includes('isbn')) return 'book';
        
        // Title keywords
        const typeKeywords = {
            'paper': ['paper', 'research', 'study', 'arxiv', '论文', '研究'],
            'tutorial': ['tutorial', 'how-to', 'how to', 'guide', '教程', '指南'],
            'news': ['news', 'breaking', '报道', '新闻'],
            'blog': ['blog', 'post', '日记', '博客'],
            'doc': ['docs', 'documentation', '文档', 'manual', 'api'],
        };
        
        for (const [type, keywords] of Object.entries(typeKeywords)) {
            if (keywords.some(k => title.includes(k) || url.includes(k))) return type;
        }
        
        return 'general';
    }

    // ============================================================
    // READING BEHAVIOR TRACKING
    // ============================================================
    
    function startBehaviorTracking() {
        // Scroll tracking (throttled)
        let scrollThrottle = 0;
        window.addEventListener('scroll', () => {
            const now = Date.now();
            if (now - scrollThrottle < 200) return; // Throttle to 5Hz
            scrollThrottle = now;
            
            recordScrollPosition();
        }, { passive: true });
        
        // Selection tracking (text highlight)
        document.addEventListener('mouseup', () => {
            const sel = window.getSelection();
            if (sel && sel.toString().trim().length > 10) {
                state.interactionData.selections.push({
                    text: sel.toString().trim().substring(0, 500),
                    time: Date.now()
                });
                state.interactionData.highlights++;
            }
        });
        
        // Copy detection
        document.addEventListener('copy', () => {
            state.interactionData.copyEvents++;
        });
        
        // Visibility tracking (tab switch)
        document.addEventListener('visibilitychange', updateDwellTime);
        
        // Focus tracking
        window.addEventListener('focus', () => {
            state.dwellData.focusGainedCount++;
            state.dwellData.lastActiveTime = Date.now();
        });
        window.addEventListener('blur', () => {
            updateDwellTime();
            state.dwellData.blurEvents.push(Date.now());
        });
        
        // Link click tracking
        document.addEventListener('click', (e) => {
            if (e.target.tagName === 'A' || e.target.closest('a')) {
                state.interactionData.linkClicks++;
            }
        });
    }

    function recordScrollPosition() {
        const scrollTop = window.scrollY || document.documentElement.scrollTop;
        const scrollHeight = document.documentElement.scrollHeight - window.innerHeight;
        const ratio = scrollHeight > 0 ? Math.min(1, scrollTop / scrollHeight) : 0;
        
        state.scrollData.maxScrollRatio = Math.max(state.scrollData.maxScrollRatio, ratio);
        state.scrollData.totalScrollDistance += Math.abs(scrollTop - state.scrollData.lastScrollY);
        state.scrollData.lastScrollY = scrollTop;
        
        state.scrollData.scrollTimestamps.push({ ratio, time: Date.now() });
        
        // Keep only recent timestamps (last 200 entries ≈ ~40s at 5Hz)
        if (state.scrollData.scrollTimestamps.length > 200) {
            state.scrollData.scrollTimestamps = state.scrollData.scrollTimestamps.slice(-200);
        }
    }

    function updateDwellTime() {
        if (document.visibilityState === 'visible' && !document.hidden) {
            const now = Date.now();
            state.dwellData.activeTimeMs += (now - state.dwellData.lastActiveTime);
            state.dwellData.lastActiveTime = now;
        }
    }

    // ============================================================
    // VALUE SCORING ENGINE
    // ============================================================
    
    /**
     * Multi-dimensional value scoring
     * Returns 0-100 score representing how likely this page should be saved
     */
    function computeValueScore() {
        if (!state.pageAnalysis) return 0;
        
        const pa = state.pageAnalysis;
        const cfg = state.config;
        const scores = {};
        
        // --- Dimension 1: Content Density (weight: 25%) ---
        scores.density = 0;
        if (pa.contentDensity > 70) scores.density = 95;
        else if (pa.contentDensity > 50) scores.density = 80;
        else if (pa.contentDensity > 35) scores.density = 60;
        else if (pa.contentDensity > 20) scores.density = 35;
        else scores.density = 10;
        
        // Bonus for having main content detected
        if (pa.hasMainContent) scores.density += 10;
        
        // --- Dimension 2: Reading Depth (weight: 20%) ---
        const scrollRatio = state.scrollData.maxScrollRatio;
        scores.depth = 0;
        if (scrollRatio >= 0.9) scores.depth = 95;   // Scrolled to bottom
        else if (scrollRatio >= 0.7) scores.depth = 80;
        else if (scrollRatio >= 0.5) scores.depth = 60; // At least halfway
        else if (scrollRatio >= 0.3) scores.depth = 35;
        else if (scrollRatio >= 0.1) scores.depth = 15;
        else scores.depth = 5;
        
        // Bonus for meaningful scrolling (not just bouncing around)
        if (state.scrollData.totalScrollDistance > 2000) scores.depth += 5;
        
        // --- Dimension 3: Dwell Time (weight: 20%) ---
        updateDwellTime();
        const dwellSec = state.dwellData.activeTimeMs / 1000;
        const readTimeMin = pa.estimatedReadTimeMinutes || 1;
        const dwellRatio = (dwellSec / 60) / Math.max(readTimeMin, 0.5); // How much of read time spent
        
        scores.dwell = 0;
        if (dwellSec < 5) scores.dwell = 5;          // Less than 5 seconds = probably accidental
        else if (dwellRatio >= 1.0) scores.dwell = 95;  // Spent more than estimated read time
        else if (dwellRatio >= 0.6) scores.dwell = 80;
        else if (dwellRatio >= 0.3) scores.dwell = 55;
        else if (dwellSec >= 15) scores.dwell = 35;
        else if (dwellSec >= cfg.minDwellTimeMs / 1000) scores.dwell = 25;
        else scores.dwell = 10;
        
        // --- Dimension 4: Source Trust (weight: 15%) ---
        scores.trust = 50; // Neutral default
        const domain = pa.domain.replace(/^www\./, '');
        
        // Check boosts
        for (const [pattern, boost] of Object.entries(cfg.domainTrustBoosts)) {
            if (domain.includes(pattern) || domain === pattern) {
                scores.trust = Math.min(100, scores.trust + boost);
                break;
            }
        }
        
        // Check penalties
        for (const [pattern, penalty] of Object.entries(cfg.domainPenalties)) {
            if (domain.includes(pattern) || domain === pattern) {
                scores.trust = Math.max(0, scores.trust + penalty);
                break;
            }
        }
        
        // --- Dimension 5: Interaction Signals (weight: 10%) ---
        scores.interaction = 0;
        const interactions = (
            state.interactionData.highlights * 25 +
            state.interactionData.copyEvents * 20 +
            state.interactionData.linkClicks * 5 +
            Math.min(state.interactionData.selections.length * 15, 40)
        );
        scores.interaction = Math.min(100, interactions);
        if (state.dwellData.focusGainedCount > 2) scores.interaction += 15; // Came back to this tab
        
        // --- Dimension 6: Content Quality Signals (weight: 10%) ---
        scores.quality = 0;
        if (pa.wordCount > 2000) scores.quality += 30;
        else if (pa.wordCount > 800) scores.quality += 20;
        else if (pa.wordCount > 300) scores.quality += 10;
        
        if (pa.headingCount > 3) scores.quality += 15;
        if (pa.codeBlockCount > 0) scores.quality += 10; // Code blocks = technical content
        if (pa.author) scores.quality += 10;              // Has author attribution
        if (pa.publishDate) scores.quality += 5;
        if (pa.contentType === 'paper') scores.quality += 20;
        if (pa.contentType === 'tutorial') scores.quality += 15;
        if (pa.hasMainContent) scores.quality += 10;
        
        // Penalize extremely short content
        if (pa.bodyTextLength < cfg.minContentLength) scores.quality -= 30;
        
        scores.quality = Math.max(0, Math.min(100, scores.quality));
        
        // --- WEIGHTED TOTAL ---
        const totalScore = Math.round(
            scores.density * 0.25 +
            scores.depth * 0.20 +
            scores.dwell * 0.20 +
            scores.trust * 0.15 +
            scores.interaction * 0.10 +
            scores.quality * 0.10
        );
        
        state.currentScore = totalScore;
        state.scoreHistory.push({
            score: totalScore,
            dimensions: { ...scores },
            timestamp: Date.now()
        });
        
        // Keep last 20 scores
        if (state.scoreHistory.length > 20) {
            state.scoreHistory = state.scoreHistory.slice(-20);
        }
        
        return { totalScore, dimensions: scores };
    }

    // ============================================================
    // CAPTURE DECISION & EXECUTION
    // ============================================================
    
    /**
     * Periodic evaluation — called every N seconds
     */
    function evaluateAndMaybeCapture() {
        if (!state.isActive || state.hasCaptured) return;
        if (!state.pageAnalysis) {
            analyzePage();
            return;
        }
        
        const result = computeValueScore();
        
        // Report current status to background (for popup display)
        sendMessageToBackground({
            type: 'scoreUpdate',
            data: {
                url: window.location.href,
                title: document.title,
                score: result.totalScore,
                dimensions: result.dimensions,
                scrollDepth: Math.round(state.scrollData.maxScrollRatio * 100),
                dwellSeconds: Math.round(state.dwellData.activeTimeMs / 1000),
            }
        });
        
        // Decision logic
        if (result.totalScore >= 80) {
            // High confidence → immediate capture
            performAutoCapture(result, 'high_confidence');
        } else if (result.totalScore >= cfg.minScoreThreshold && result.totalScore >= 60) {
            // Medium score → check if user seems done with page
            const dwellOk = state.dwellData.activeTimeMs > cfg.minDwellTimeMs * 2;
            const scrollOk = state.scrollData.maxScrollRatio > 0.5;
            
            if (dwellOk && scrollOk) {
                performAutoCapture(result, 'behavioral_trigger');
            }
            // Otherwise keep observing...
        }
    }

    /**
     * Called when page loses visibility or unloads
     */
    function onVisibilityChange() {
        if (document.visibilityState === 'hidden' && !state.hasCaptured) {
            // Final evaluation before leaving page
            updateDwellTime();
            const result = computeValueScore();
            
            if (result.totalScore >= cfg.minScoreThreshold) {
                performAutoCapture(result, 'page_leave');
            }
        }
    }

    function onPageLeave() {
        if (!state.hasCaptured && state.currentScore >= cfg.minScoreThreshold * 0.8) {
            // One final attempt — slightly lower threshold since user is leaving
            const result = computeValueScore();
            if (result.totalScore >= cfg.minScoreThreshold * 0.8) {
                performAutoCapture(result, 'page_unload');
            }
        }
    }

    /**
     * Execute the actual capture — extract content and send to backend
     */
    async function performAutoCapture(scoreResult, trigger) {
        if (state.hasCaptured) return;
        state.hasCaptured = true;
        
        clearInterval(state.observerTimer);
        
        try {
            // Build capture payload
            const payload = buildCapturePayload(scoreResult, trigger);
            
            // Send to backend
            sendMessageToBackground({
                type: 'autoCapture',
                data: payload
            });
            
            // Show notification
            if (cfg.enableNotifications) {
                showNotification(payload.title, scoreResult.totalScore, trigger);
            }
            
            console.log(`[CAM] ✅ Auto-captured (${trigger}, score=${scoreResult.totalScore}):`, payload.title);
            
        } catch(e) {
            console.error('[CAM] Capture failed:', e);
            state.hasCaptured = false; // Allow retry
        }
    }

    /**
     * Build the full capture payload to send to backend
     */
    function buildCapturePayload(scoreResult, trigger) {
        const pa = state.pageAnalysis || {};
        
        // Get best available text content
        let content = '';
        let excerpt = '';
        
        if (pa.article && pa.article.textContent) {
            content = pa.article.textContent;
            excerpt = pa.article.excerpt || content.substring(0, 500);
        } else {
            content = getBodyText();
            excerpt = content.substring(0, 500);
        }
        
        // Clean up HTML if we have the article DOM
        let contentHtml = '';
        if (pa.article && pa.article.content) {
            contentHtml = sanitizeHtml(pa.article.content.innerHTML);
        }
        
        // Generate tags from content type + analysis
        const tags = generateTags(pa, scoreResult);
        
        return {
            title: pa.title || document.title,
            url: window.location.href,
            author: pa.author || '',
            publishDate: pa.publishDate || '',
            contentType: pa.contentType || 'general',
            
            // Content
            content: content,
            contentHtml: contentHtml || undefined,
            excerpt: excerpt,
            wordCount: pa.wordCount || countWords(content),
            estimatedReadTime: pa.estimatedReadTimeMinutes || 0,
            
            // Classification
            tags: tags,
            
            // Scoring metadata
            score: scoreResult.totalScore,
            dimensions: scoreResult.dimensions,
            trigger: trigger,
            
            // Reading behavior (useful for training/analysis)
            behavior: {
                scrollDepthPercent: Math.round(state.scrollData.maxScrollRatio * 100),
                dwellSeconds: Math.round(state.dwellData.activeTimeMs / 1000),
                highlights: state.interactionData.highlights,
                copies: state.interactionData.copyEvents,
                tabReturns: state.dwellData.focusGainedCount,
            },
            
            // Timestamp
            capturedAt: new Date().toISOString(),
        };
    }

    function generateTags(pa, scoreResult) {
        const tags = [];
        
        // Content type tag
        if (pa.contentType && pa.contentType !== 'general') {
            tags.push(pa.contentType);
        }
        
        // Language detection (simple heuristic)
        const sample = (pa.article?.textContent || '').substring(0, 500) || '';
        if (/[\u4e00-\u9fff]/.test(sample)) {
            tags.push('chinese');
        } else if (sample.length > 0) {
            tags.push('english');
        }
        
        // Domain-based tags
        const domain = pa.domain || '';
        if (domain.includes('github')) tags.push('code');
        if (domain.includes('arxiv')) tags.push('academic');
        if (domain.includes('medium') || domain.includes('substack')) tags.push('blog');
        if (domain.includes('zhihu')) tags.push('zhihu');
        
        // Score-based quality tag
        if (scoreResult.totalScore >= 85) tags.push('high-quality');
        
        // Length-based tag
        const wc = pa.wordCount || 0;
        if (wc > 3000) tags.push('long-read');
        else if (wc > 1000) tags.push('article');
        else if (wc > 300) tags.push('short-article');
        
        // Technical indicators
        if (pa.codeBlockCount > 0) tags.push('technical');
        if (pa.author) tags.push('has-author');
        
        return tags.slice(0, 10); // Max 10 tags
    }

    function sanitizeHtml(html) {
        // Remove script, style, dangerous elements
        const div = document.createElement('div');
        div.innerHTML = html;
        
        const remove = div.querySelectorAll('script, style, iframe, object, embed, form, input');
        remove.forEach(el => el.remove());
        
        return div.innerHTML.substring(0, 100000); // Cap size
    }

    // ============================================================
    // NOTIFICATION SYSTEM
    // ============================================================
    
    function showNotification(title, score, trigger) {
        // Remove existing toast
        if (state.toastElement) {
            state.toastElement.remove();
        }
        
        const toast = document.createElement('div');
        toast.style.cssText = `
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 2147483647;
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            color: #f1f5f9;
            padding: 14px 20px;
            border-radius: 12px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            font-size: 13px;
            line-height: 1.5;
            max-width: 380px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3), 0 0 0 1px rgba(255,255,255,0.05);
            backdrop-filter: blur(12px);
            animation: cw-slideIn 0.3s ease-out;
            cursor: pointer;
        `;
        
        const triggerLabels = {
            high_confidence: '⚡ 高质量自动捕获',
            behavioral_trigger: '📖 阅读行为触发',
            page_leave: '👋 离页自动保存',
            page_unload: '🔄 离开前最后捕获',
            manual_force: '✋ 手动强制保存',
        };
        
        const triggerLabel = triggerLabels[trigger] || '🧠 自动捕获';
        
        toast.innerHTML = `
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
                <span style="font-size:18px">🧠</span>
                <span style="font-weight:600;font-size:14px">已存入 CAM</span>
                <span style="margin-left:auto;background:#22c55e;color:white;font-size:11px;
                       font-weight:700;padding:2px 8px;border-radius:99px">${score}分</span>
            </div>
            <div style="color:#94a3b8;font-size:12px;margin-bottom:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                ${escapeHtml(title)}
            </div>
            <div style="color:#64748b;font-size:11px;display:flex;align-items:center;gap:6px">
                <span>${triggerLabel}</span>
                <span>·</span>
                <span>${new Date().toLocaleTimeString()}</span>
            </div>
        `;
        
        // Add animation keyframes
        if (!document.getElementById('cw-toast-styles')) {
            const style = document.createElement('style');
            style.id = 'cw-toast-styles';
            style.textContent = `
                @keyframes cw-slideIn {
                    from { transform: translateY(20px); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
                @keyframes cw-fadeOut {
                    from { opacity: 1; }
                    to { opacity: 0; transform: translateY(10px); }
                }
            `;
            document.head.appendChild(style);
        }
        
        document.body.appendChild(toast);
        state.toastElement = toast;
        
        // Click to dismiss
        toast.addEventListener('click', () => {
            toast.style.animation = 'cw-fadeOut 0.2s ease-in forwards';
            setTimeout(() => toast.remove(), 200);
        });
        
        // Auto-dismiss after duration
        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.animation = 'cw-fadeOut 0.3s ease-in forwards';
                setTimeout(() => toast.remove(), 300);
            }
        }, cfg.notificationDurationMs);
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // ============================================================
    // MESSAGE HANDLING
    // ============================================================
    
    function sendMessageToBackground(msg) {
        try {
            chrome.runtime.sendMessage(msg).catch(() => {});
        } catch(e) {}
    }

    function onMessage(msg, sender, sendResponse) {
        switch(msg.type) {
            case 'getStatus':
                sendResponse({
                    isActive: state.isActive,
                    hasCaptured: state.hasCaptured,
                    currentScore: state.currentScore,
                    pageAnalysis: state.pageAnalysis ? {
                        title: state.pageAnalysis.title,
                        wordCount: state.pageAnalysis.wordCount,
                        contentType: state.pageAnalysis.contentType,
                    } : null,
                    behavior: {
                        scrollDepth: Math.round(state.scrollData.maxScrollRatio * 100),
                        dwellSeconds: Math.round(state.dwellData.activeTimeMs / 1000),
                        highlights: state.interactionData.highlights,
                    },
                    scoreHistory: state.scoreHistory.slice(-5),
                });
                return true;
                
            case 'forceCapture':
                // Manual force-capture from popup
                if (!state.pageAnalysis) analyzePage();
                const result = computeValueScore();
                performAutoCapture({ ...result, totalScore: 100 }, 'manual_force');
                sendResponse({ ok: true });
                return true;
                
            case 'updateConfig':
                state.config = { ...DEFAULT_CONFIG, ...msg.config };
                sendResponse({ ok: true });
                return true;
        }
    }

    // ============================================================
    // BOOT
    // ============================================================
    
    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
