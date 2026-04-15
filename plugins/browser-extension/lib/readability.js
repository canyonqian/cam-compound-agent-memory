/**
 * CAM — Simplified Readability
 * ========================================
 * 
 * A lightweight, dependency-free implementation inspired by Mozilla's Readability.
 * Extracts main article content from any web page.
 * 
 * This is a simplified version (~300 lines vs original's 2000+ lines)
 * optimized for speed and browser extension use.
 */

class Readability {
    constructor(doc) {
        this.doc = doc;
        this.iframe = null;
    }

    /**
     * Main entry point: parse the document and return an article object
     */
    parse() {
        const { title, excerpt, byline, dir } = this._getArticleMetadata();
        
        // Try to find the main content container
        const content = this._findMainContent();
        
        if (!content || content.textContent.trim().length < 200) {
            return null;
        }
        
        return {
            title,
            content,           // DOM element with cleaned HTML
            textContent: this._getTextContent(content),
            excerpt: excerpt || this._generateExcerpt(content),
            byline,
            dir: dir || 'ltr',
            length: content.textContent.length,
        };
    }

    // ========== Metadata Extraction ==========
    
    _getArticleMetadata() {
        const doc = this.doc;
        
        let title = '';
        let excerpt = '';
        let byline = '';
        let dir = '';
        
        // Title — try various sources in order of preference
        const titleSelectors = [
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            'meta[name="title"]',
            'title',
        ];
        
        for (const sel of titleSelectors) {
            const el = doc.querySelector(sel);
            if (el) {
                title = el.getAttribute('content') || el.textContent;
                if (title && title.trim()) break;
            }
        }
        
        // Description / excerpt
        const descSelectors = [
            'meta[name="description"]',
            'meta[property="og:description"]',
            'meta[name="twitter:description"]',
        ];
        
        for (const sel of descSelectors) {
            const el = doc.querySelector(sel);
            if (el) {
                excerpt = el.getAttribute('content') || '';
                if (excerpt.trim()) break;
            }
        }
        
        // Author / byline
        const authorSelectors = [
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[name="dc.creator"]',
            '[rel="author"]',
            '.author-name', '.byline', '.post-author'
        ];
        
        for (const sel of authorSelectors) {
            const el = doc.querySelector(sel);
            if (el) {
                byline = el.getAttribute('content') || el.getAttribute('href') || el.textContent;
                if (byline && byline.trim()) break;
            }
        }
        
        // Direction
        const htmlEl = doc.documentElement;
        dir = htmlEl.getAttribute('dir');
        
        return { title, excerpt, byline, dir };
    }

    // ========== Content Finding ==========
    
    _findMainContent() {
        const doc = this.doc;
        
        // Strategy 1: Known semantic elements
        const semanticSelectors = [
            'article',
            '[role="article"]',
            '[role="main"]',
            'main',
        ];
        
        for (const sel of semanticSelectors) {
            const el = doc.querySelector(sel);
            if (el && this._isLikelyContent(el)) {
                return this._cleanContent(el.cloneNode(true));
            }
        }
        
        // Strategy 2: Common class names used by major platforms
        const classSelectors = [
            '.post-content', '.article-content', '.entry-content',
            '.content-body', '#content-body', '.story-body',
            '.markdown-body', '.ProseMirror', '.ql-editor',
            '.rich_media_content', '#js_content', '.article-body',
            '.post-body', 'article .body', '.article__body',
            '[itemprop="articleBody"]',
            '.tocsafe-content-wrapper', '.post-text',
        ];
        
        for (const sel of classSelectors) {
            const el = doc.querySelector(sel);
            if (el && this._isLikelyContent(el)) {
                return this._cleanContent(el.cloneNode(true));
            }
        }
        
        // Strategy 3: Score-based approach (like original Readability)
        return this._scoreAndExtract();
    }

    _isLikelyContent(el) {
        if (!el) return false;
        const text = el.innerText || '';
        const len = text.trim().length;
        return len > 200 && len < 500000;
    }

    /**
     * Original Readability-style scoring algorithm:
     * Score each candidate element based on content density
     */
    _scoreAndExtract() {
        const doc = this.doc;
        const candidates = [];
        
        // Get all paragraph-level elements as potential candidates
        const potentialContainers = new Set();
        
        // Start from paragraphs and walk up
        const paragraphs = doc.querySelectorAll('p, pre, div, section');
        
        for (const p of Array.from(paragraphs).slice(0, 200)) {
            if (p.innerText?.trim().length < 25) continue;
            
            let parent = p.parentElement;
            for (let level = 0; level < 5 && parent; level++) {
                potentialContainers.add(parent);
                parent = parent.parentElement;
            }
        }
        
        // Score each candidate
        for (const candidate of potentialContainers) {
            const score = this._scoreElement(candidate);
            if (score > 0) {
                candidates.push({ el: candidate, score });
            }
        }
        
        // Sort by score descending
        candidates.sort((a, b) => b.score - a.score);
        
        if (candidates.length === 0) {
            return this._fallbackExtraction();
        }
        
        // Take the best candidate
        const best = candidates[0];
        
        // Verify it's not just a wrapper for something better
        if (candidates.length > 1 && best.score > candidates[1].score * 1.5) {
            return this._cleanContent(best.el.cloneNode(true));
        }
        
        return this._cleanContent(best.el.cloneNode(true));
    }

    _scoreElement(el) {
        let score = 0;
        
        const textLen = (el.innerText || '').trim().length;
        if (textLen < 100) return 0;
        
        // Base score from text length
        if (textLen > 200) score += Math.min(textLen / 10, 50);
        
        // Count content-rich children
        const pCount = el.querySelectorAll('p').length;
        score += pCount * 3;
        
        // Bonus for semantically rich content
        score += el.querySelectorAll('h2, h3').length * 5;
        score += el.querySelectorAll('pre, code').length * 3;
        score += el.querySelectorAll('blockquote').length * 3;
        score += el.querySelectorAll('img[src], figure').length * 2;
        score += el.querySelectorAll('li').length * 1;
        
        // Class name bonuses
        const className = (el.className || '').toLowerCase();
        const idName = (el.id || '').toLowerCase();
        
        const positivePatterns = [
            /post|article|content|body|story|entry|text|main|blog|news/,
            /markdown|prosemirror|editor|rich.?media|article.?body/
        ];
        
        const negativePatterns = [
            /comment|sidebar|nav|footer|header|menu|widget|ad|sponsor|
             related|recommend|share|social|subscribe|newsletter|promo/
        ];
        
        for (const pat of positivePatterns) {
            if (pat.test(className) || pat.test(idName)) score += 25;
        }
        
        for (const pat of negativePatterns) {
            if (pat.test(className) || pat.test(idName)) score -= 50;
        }
        
        // Content density: ratio of text to total innerHTML
        const htmlLen = (el.innerHTML || '').length;
        if (htmlLen > 0) {
            const density = textLen / htmlLen;
            if (density > 0.4) score += 20;     // High density = good
            else if (density > 0.25) score += 10;
            else if (density < 0.1) score -= 20;  // Low density = likely navigation
        }
        
        // Link density penalty (too many links = nav/menu)
        const links = el.querySelectorAll('a[href]').length;
        const linkRatio = links / Math.max(pCount, 1);
        if (linkRatio > 5) score -= 30;
        else if (linkRatio > 3) score -= 15;
        
        return Math.max(0, score);
    }

    /**
     * Fallback: clean the body itself
     */
    _fallbackExtraction() {
        const body = this.doc.body;
        if (!body) return null;
        
        const clone = body.cloneNode(true);
        this._removeNoise(clone);
        
        if ((clone.innerText || '').trim().length > 100) {
            return clone;
        }
        
        return null;
    }

    // ========== Content Cleaning ==========
    
    _cleanContent(container) {
        this._removeNoise(container);
        this._fixFormatting(container);
        return container;
    }

    _removeNoise(container) {
        // Elements to completely remove
        const removeSelectors = [
            'script', 'style', 'noscript', 'svg', 'canvas',
            'iframe', 'object', 'embed', 'applet',
            'nav', 'header', 'footer', 'aside',
            
            // Common noise classes/ids
            '.sidebar', '.navigation', '.navbar', '.menu',
            '.footer', '.comment', '.comments', '.related',
            '.share', '.social', '.ad-', '.advertisement',
            '.promo', '.subscription', '.newsletter',
            '.cookie', '.banner', '.popup', '.modal',
            '.breadcrumbs', '.pagination',
            
            '[role="navigation"]', '[role="complementary"]',
            '[role="banner"]', '[role="contentinfo"]',
        ];
        
        removeSelectors.forEach(selector => {
            try {
                container.querySelectorAll(selector).forEach(el => el.remove());
            } catch(e) {}
        });
        
        // Remove elements with common ad patterns in their attributes
        container.querySelectorAll('*').forEach(el => {
            const cls = el.className || '';
            const id = el.id || '';
            const combined = (cls + ' ' + id).toLowerCase();
            
            if (/ad[s-]? |sponsor|promo|widget|sidebar|comment|share-btn/.test(combined)) {
                // Be more careful here — only remove if clearly noise
                if (/^(ad|sponsor|promo)/.test(combined.replace(/[\s_-]/g, ''))) {
                    el.remove();
                }
            }
        });
    }

    _fixFormatting(container) {
        // Convert excessive line breaks
        container.querySelectorAll('br').forEach(br => {
            const next = br.nextElementSibling;
            if (next && next.tagName === 'BR') {
                br.remove(); // Remove consecutive BRs
            }
        });
        
        // Ensure images have alt text or remove decorative ones
        container.querySelectorAll('img').forEach(img => {
            if (!img.alt) img.alt = '';
            // Skip tiny tracking pixels
            if (parseInt(img.width) < 5 || parseInt(img.height) < 5) {
                img.remove();
            }
        });
        
        // Clean up empty elements
        container.querySelectorAll('*').forEach(el => {
            if (el.children.length === 0 && 
                !(el.innerText || '').trim() &&
                !['IMG', 'BR', 'HR'].includes(el.tagName)) {
                el.remove();
            }
        });
    }

    // ========== Utilities ==========
    
    _getTextContent(element) {
        if (!element) return '';
        
        let text = (element.innerText || '') || 
                   (element.textContent || '');
        
        // Normalize whitespace
        return text
            .replace(/[\r\n\t]+/g, '\n')
            .replace(/[ ]{2,}/g, ' ')
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    _generateExcerpt(content) {
        const text = this._getTextContent(content);
        if (text.length <= 280) return text;
        
        // Try to cut at sentence boundary
        const truncated = text.substring(0, 280);
        const lastSentenceEnd = Math.max(
            truncated.lastIndexOf('.'),
            truncated.lastIndexOf('!'),
            truncated.lastIndexOf('？'),
            truncated.lastIndexOf('。')
        );
        
        if (lastSentenceEnd > 150) {
            return truncated.substring(0, lastSentenceEnd + 1) + '...';
        }
        
        return truncated + '...';
    }
}

// Export
if (typeof window !== 'undefined') {
    window.Readability = Readability;
}
