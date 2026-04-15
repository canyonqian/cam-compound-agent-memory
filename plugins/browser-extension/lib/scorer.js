/**
 * CAM — Value Scoring Engine
 * =====================================
 * 
 * Multi-dimensional content value scoring system.
 * Used by content.js for real-time page evaluation.
 * 
 * This module can also be used standalone for testing/debugging.
 * 
 * Dimensions:
 *   1. Content Density  (25%) — How much of the page is actual content vs noise
 *   2. Reading Depth    (20%) — How far did the user scroll (engagement)
 *   3. Dwell Time       (20%) — How long user spent on page
 *   4. Source Trust     (15%) — Domain reputation / quality signal
 *   5. Interaction      (10%) — Highlights, copies, link clicks
 *   6. Content Quality  (10%) — Length, structure, metadata completeness
 */

class CompoundWikiScorer {
    constructor(config = {}) {
        this.weights = {
            density: config.densityWeight || 0.25,
            depth: config.depthWeight || 0.20,
            dwell: config.dwellWeight || 0.20,
            trust: config.trustWeight || 0.15,
            interaction: config.interactionWeight || 0.10,
            quality: config.qualityWeight || 0.10,
        };
        
        this.thresholds = {
            autoCapture: config.autoCaptureThreshold || 80,
            observe: config.observeThreshold || 60,
            ignore: config.ignoreThreshold || 40,
            minDwellMs: config.minDwellMs || 15000,
        };
    }

    /**
     * Full scoring pipeline — input all data, get result
     */
    score(pageAnalysis, behaviorData, options = {}) {
        const dimensions = this.scoreAllDimensions(pageAnalysis, behaviorData);
        const total = this.weightedTotal(dimensions);
        
        return {
            total: Math.round(total),
            dimensions,
            decision: this.makeDecision(total, dimensions),
            confidence: this.calculateConfidence(dimensions),
        };
    }

    /**
     * Score each dimension independently
     */
    scoreAllDimensions(pageAnalysis, behavior) {
        return {
            density: this.scoreDensity(pageAnalysis),
            depth: this.scoreDepth(behavior),
            dwell: this.scoreDwell(behavior, pageAnalysis),
            trust: this.scoreTrust(pageAnalysis),
            interaction: this.scoreInteraction(behavior),
            quality: this.scoreQuality(pageAnalysis),
        };
    }

    // ========== Dimension Scorers ==========

    scoreDensity(pa) {
        let score = 0;
        
        if (!pa || pa.contentDensity === undefined) return 30; // Unknown = moderate
        
        const d = pa.contentDensity;
        
        if (d > 75) score = 95;
        else if (d > 55) score = 82;
        else if (d > 40) score = 65;
        else if (d > 25) score = 38;
        else if (d > 15) score = 18;
        else score = 5;
        
        // Bonuses
        if (pa.hasMainContent) score += 10;
        if (pa.bodyTextLength > 3000) score += 3;
        if (pa.bodyTextLength < 200) score -= 20; // Too short
        
        return Math.max(0, Math.min(100, score));
    }

    scoreDepth(behavior) {
        if (!behavior) return 10;
        
        const scrollRatio = behavior.maxScrollRatio || 0;
        let score = 0;
        
        if (scrollRatio >= 0.95) score = 98;
        else if (scrollRatio >= 0.80) score = 88;
        else if (scrollRatio >= 0.60) score = 72;
        else if (scrollRatio >= 0.40) score = 50;
        else if (scrollRatio >= 0.20) score = 28;
        else if (scrollRatio >= 0.05) score = 12;
        else score = 3;
        
        // Meaningful scrolling bonus
        if ((behavior.totalScrollDistance || 0) > 3000) score += 7;
        if ((behavior.totalScrollDistance || 0) > 8000) score += 5;
        
        return Math.max(0, Math.min(100, score));
    }

    scoreDwell(behavior, pa) {
        if (!behavior) return 10;
        
        const dwellSec = (behavior.activeTimeMs || 0) / 1000;
        const readTimeMin = (pa?.estimatedReadTimeMinutes) || 1;
        const ratio = (dwellSec / 60) / Math.max(readTimeMin, 0.5);
        
        let score = 0;
        
        if (dwellSec < 3) score = 2;          // Bounce
        else if (dwellSec < 8) score = 8;     // Quick glance
        else if (dwellSec < 15) score = 18;   // Brief look
        else if (ratio >= 1.0) score = 95;    // Spent more than read time
        else if (ratio >= 0.7) score = 82;
        else if (ratio >= 0.4) score = 60;
        else if (ratio >= 0.2) score = 38;
        else if (dwellSec >= 30) score = 30;
        else if (dwellSec >= 15) score = 22;
        else score = 12;
        
        // Tab engagement bonus
        if ((behavior.focusGainedCount || 0) >= 3) score += 8;
        if ((behavior.focusGainedCount || 0) >= 2) score += 5;
        
        return Math.max(0, Math.min(100, score));
    }

    scoreTrust(pa) {
        let score = 50; // Neutral default
        if (!pa || !pa.domain) return score;
        
        const domain = pa.domain.replace(/^www\./, '');
        
        // Known high-quality domains (boosts)
        const boosts = {
            'arxiv.org': 35, 'paperswithcode.com': 30, 'distill.pub': 38,
            'lesswrong.com': 28, 'nature.com': 32, 'science.org': 32,
            'ieee.org': 28, 'acm.org': 26, 'github.com': 22,
            'developer.mozilla.org': 30, 'wikipedia.org': 18,
            'towardsdatascience.com': 18, 'medium.com': 12,
            'substack.com': 12, 'dev.to': 16, 'hashnode.com': 14,
            'zhuanlan.zhihu.com': 16, 'sspai.com': 14,
            'segmentfault.com': 10, 'juejin.cn': 8, 'csdn.net': 5,
            'developer.aliyun.com': 14, 'woshipm.com': 10,
        };
        
        for (const [pattern, boost] of Object.entries(boosts)) {
            if (domain.includes(pattern)) {
                score = Math.min(100, score + boost);
                break;
            }
        }
        
        // Known low-value domains (penalties)
        const penalties = {
            'google.com': -55, 'baidu.com': -45, 'bing.com': -50,
            'facebook.com': -48, 'instagram.com': -48, 'twitter.com': -32,
            'x.com': -32, 'tiktok.com': -45, 'youtube.com': -35,
            'amazon.com': -42, 'taobao.com': -42, 'jd.com': -36,
            'pinterest.com': -32,
        };
        
        for (const [pattern, penalty] of Object.entries(penalties)) {
            if (domain.includes(pattern)) {
                score = Math.max(0, score + penalty);
                break;
            }
        }
        
        return Math.max(0, Math.min(100, score));
    }

    scoreInteraction(behavior) {
        if (!behavior) return 0;
        
        let rawScore = 0;
        
        rawScore += (behavior.highlights || 0) * 25;     // Highlighting is strong signal
        rawScore += (behavior.copyEvents || 0) * 20;     // Copying text = interest
        rawScore += Math.min((behavior.selections?.length || 0) * 15, 45); // Selections
        rawScore += (behavior.linkClicks || 0) * 5;
        
        if ((behavior.focusGainedCount || 0) > 2) rawScore += 15; // Returned to tab
        
        return Math.max(0, Math.min(100, rawScore));
    }

    scoreQuality(pa) {
        if (!pa) return 20;
        
        let score = 0;
        
        // Content length
        const wc = pa.wordCount || 0;
        if (wc > 5000) score += 32;
        else if (wc > 2500) score += 24;
        else if (wc > 1000) score += 18;
        else if (wc > 400) score += 10;
        else if (wc > 150) score += 4;
        
        // Structure indicators
        if ((pa.headingCount || 0) > 5) score += 14;
        else if ((pa.headingCount || 0) > 2) score += 8;
        if ((pa.listCount || 0) > 3) score += 6;
        
        // Technical content signals
        if ((pa.codeBlockCount || 0) > 0) score += 12;
        if ((pa.imageCount || 0) > 3) score += 4; // Has figures/images
        
        // Metadata completeness
        if (pa.author) score += 10;
        if (pa.publishDate) score += 6;
        
        // Content type bonuses
        if (pa.contentType === 'paper') score += 20;
        if (pa.contentType === 'tutorial') score += 16;
        if (pa.contentType === 'docs') score += 12;
        
        // Main content detection
        if (pa.hasMainContent) score += 10;
        
        // Penalties
        if ((pa.wordCount || 0) < 150) score -= 25; // Very short
        if (!pa.hasMainContent && (pa.contentDensity || 0) < 20) score -= 15;
        
        return Math.max(0, Math.min(100, score));
    }

    // ========== Aggregation ==========

    weightedTotal(dimensions) {
        return (
            dimensions.density * this.weights.density +
            dimensions.depth * this.weights.depth +
            dimensions.dwell * this.weights.dwell +
            dimensions.trust * this.weights.trust +
            dimensions.interaction * this.weights.interaction +
            dimensions.quality * this.weights.quality
        );
    }

    makeDecision(total, dimensions) {
        if (total >= this.thresholds.autoCapture) {
            return { action: 'capture', reason: 'high_confidence' };
        }
        
        if (total >= this.thresholds.observe) {
            // Check secondary signals
            const engaged = (
                dimensions.dwell >= 60 &&
                dimensions.depth >= 50
            );
            
            if (engaged) {
                return { action: 'capture_if_done', reason: 'engaged_reading' };
            }
            return { action: 'observe', reason: 'moderate_score_keep_watching' };
        }
        
        if (total < this.thresholds.ignore) {
            return { action: 'ignore', reason: 'low_quality_or_no_engagement' };
        }
        
        return { action: 'observe', reason: 'borderline' };
    }

    calculateConfidence(dimensions) {
        // How much do all dimensions agree?
        const values = Object.values(dimensions);
        const mean = values.reduce((a, b) => a + b, 0) / values.length;
        const variance = values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length;
        const stdDev = Math.sqrt(variance);
        
        // Low stdDev = high agreement = high confidence
        const agreement = Math.max(0, 100 - stdDev * 1.5);
        
        // Also factor in how many dimensions have meaningful data
        const dataCompleteness = values.filter(v => v > 0).length / values.length;
        
        return Math.round(agreement * 0.6 + dataCompleteness * 40);
    }

    // ========== Utility ==========

    explain(scoreResult) {
        const { total, dimensions, decision } = scoreResult;
        const lines = [
            `Total Score: ${total}/100`,
            `Decision: ${decision.action} (${decision.reason})`,
            ``,
            `Dimension Breakdown:`,
            `  📊 Density (×${this.weights.density}): ${dimensions.density} — Content purity`,
            `  📏 Depth   (×${this.weights.depth}): ${dimensions.depth} — Scroll engagement`,
            `  ⏱️ Dwell   (×${this.weights.dwell}): ${dimensions.dwell} — Time on page`,
            `  🔒 Trust   (×${this.weights.trust}): ${dimensions.trust} — Domain reputation`,
            `  👆 Interact(×${this.weights.interaction}): ${dimensions.interaction} — User actions`,
            `  ⭐ Quality (×${this.weights.quality}): ${dimensions.quality} — Content signals`,
            ``,
            `Confidence: ${scoreResult.confidence}%`,
        ];
        return lines.join('\n');
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.CompoundWikiScorer = CompoundWikiScorer;
}
