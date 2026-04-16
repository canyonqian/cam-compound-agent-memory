/**
 * CAM — Compound Agent Memory Plugin v6.0 (Self-Contained)
 *
 * 核心架构：完全自包含，不依赖外部 Python daemon。
 * 像 LCM 一样，所有逻辑都在插件内部完成。
 *
 * 存储：直接读写 wiki/ 目录（Markdown 文件 + JSON 索引）
 *   - wiki/entity/     — 实体页（人、项目、工具）
 *   - wiki/concept/    — 概念页（技术、方法、模式）
 *   - wiki/synthesis/  — 综合页（决策、偏好、经验）
 *
 * 三层机制：
 *   L1 ContextEngine（框架自动调用）
 *     - ingest()   → 直接存消息到 wiki（entity/concept/synthesis）
 *     - assemble() → 从 wiki 检索相关记忆注入 prompt
 *
 *   L2 Tool（Agent 主动调用）
 *     - cam_extract      → Agent 提取的知识直接写 wiki（最核心！）
 *     - cam_query        → 搜索知识库
 *     - cam_extract_file → 文件/图片提取 → 写 wiki
 *
 *   L3 Hook（补充增强）
 *     - before_prompt_build → 注入记忆召回指令 + 文件处理提醒
 *     - message_received    → 检测文件/图片附件
 *
 * Agent 兼容性：
 *   - 任何支持 OpenClaw 插件的 Agent 都能用
 *   - 不需要 Python daemon、不需要外部 LLM
 *   - Agent 用自己的 LLM 提取知识 → cam_extract 存储
 *   - ingest 自动用启发式规则存储明显的事实
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import type {
  ContextEngine,
  AssembleResult,
  IngestResult,
} from "openclaw/plugin-sdk";
import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  statSync,
  appendFileSync,
  unlinkSync,
} from "node:fs";
import { join, basename } from "node:path";
import { createHash } from "node:crypto";

// ============================================================
// 配置
// ============================================================

function resolveConfig(cfg: Record<string, unknown>) {
  return {
    wikiPath: ((cfg.wikiPath as string) ||
      process.env.CAM_WIKI_PATH ||
      process.env.CAM_PROJECT_DIR ||
      process.cwd()) as string,
    injectOnPrompt: cfg.injectOnPrompt !== false,
    maxRecallPages: Math.min(Math.max((cfg.maxRecallPages as number) || 5, 1), 20),
  };
}

// ============================================================
// CamMemoryStore — 直接读写 wiki 目录
// ============================================================

type FactCategory = "entity" | "concept" | "synthesis";

interface StoredFact {
  name: string;
  category: FactCategory;
  content: string;
  tags: string[];
  agentId: string;
  timestamp: string;
  sourceSnippet: string;
}

class CamMemoryStore {
  private wikiPath: string;
  private indexPath: string;
  private index: Map<string, StoredFact> = new Map();
  private dirty = false;

  constructor(wikiPath: string) {
    this.wikiPath = wikiPath.replace(/\/+$/, "");
    this.indexPath = join(this.wikiPath, ".cam-index.json");

    // Ensure directory structure
    for (const dir of ["entity", "concept", "synthesis"]) {
      const p = join(this.wikiPath, dir);
      if (!existsSync(p)) mkdirSync(p, { recursive: true });
    }
    if (!existsSync(join(this.wikiPath, "raw"))) {
      mkdirSync(join(this.wikiPath, "raw"), { recursive: true });
    }

    this.loadIndex();
  }

  // ── Index Management ──

  private loadIndex(): void {
    try {
      if (existsSync(this.indexPath)) {
        const data = JSON.parse(readFileSync(this.indexPath, "utf-8"));
        if (data.facts && Array.isArray(data.facts)) {
          for (const f of data.facts) {
            this.index.set(f.name, f);
          }
        }
        console.log(`[cam-store] Loaded index: ${this.index.size} facts`);
      }
    } catch (e) {
      console.warn(`[cam-store] Failed to load index, starting fresh: ${e}`);
      this.index = new Map();
    }
  }

  private saveIndex(): void {
    if (!this.dirty) return;
    try {
      const data = {
        version: 1,
        updatedAt: new Date().toISOString(),
        facts: Array.from(this.index.values()),
      };
      writeFileSync(this.indexPath, JSON.stringify(data, null, 2), "utf-8");
      this.dirty = false;
    } catch (e) {
      console.error(`[cam-store] Failed to save index: ${e}`);
    }
  }

  // ── Core Operations ──

  /**
   * Store a fact into the wiki directory.
   * Returns true if a new page was written, false if deduplicated.
   */
  storeFact(fact: StoredFact): boolean {
    // Dedup check by name
    const existing = this.index.get(fact.name);
    if (existing) {
      // Update existing: append new info if content differs
      const existingPath = this.getWikiPagePath(existing.category, existing.name);
      if (existsSync(existingPath)) {
        const existingContent = readFileSync(existingPath, "utf-8");
        if (existingContent.includes(fact.content)) {
          // Already contains this info
          return false;
        }
        // Append new info to existing page
        const appendSection = `\n\n## ${fact.timestamp}\n\n${fact.content}`;
        appendFileSync(existingPath, appendSection, "utf-8");
        this.dirty = true;
        this.saveIndex();
        return true;
      }
    }

    // Write new wiki page
    const pagePath = this.getWikiPagePath(fact.category, fact.name);
    const dir = join(this.wikiPath, fact.category);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });

    const pageContent = this.renderWikiPage(fact);
    writeFileSync(pagePath, pageContent, "utf-8");

    // Update index
    this.index.set(fact.name, fact);
    this.dirty = true;
    this.saveIndex();
    return true;
  }

  /**
   * Store raw conversation turn (ingest).
   */
  storeRawConversation(
    userMsg: string,
    aiResponse: string,
    agentId: string,
    sessionId: string,
  ): void {
    const rawDir = join(this.wikiPath, "raw");
    if (!existsSync(rawDir)) mkdirSync(rawDir, { recursive: true });

    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filename = `${timestamp}-${agentId}-${sessionId.slice(0, 8)}.md`;

    const content = [
      `# Conversation Turn`,
      ``,
      `- **Agent**: ${agentId}`,
      `- **Session**: ${sessionId}`,
      `- **Time**: ${new Date().toISOString()}`,
      ``,
      `## User`,
      ``,
      userMsg,
      ``,
      `## Assistant`,
      ``,
      aiResponse,
    ].join("\n");

    writeFileSync(join(rawDir, filename), content, "utf-8");
  }

  /**
   * Query the wiki for relevant memories.
   * Simple keyword-based search (no LLM needed).
   */
  query(question: string, topK: number = 5): Array<{
    name: string;
    category: FactCategory;
    content: string;
    relevance: number;
  }> {
    const keywords = this.extractKeywords(question);
    if (keywords.length === 0) return [];

    const results: Array<{
      name: string;
      category: FactCategory;
      content: string;
      relevance: number;
    }> = [];

    for (const [name, fact] of this.index) {
      const searchText = `${name} ${fact.content} ${fact.tags.join(" ")}`.toLowerCase();
      let matchCount = 0;
      for (const kw of keywords) {
        if (searchText.includes(kw.toLowerCase())) matchCount++;
      }
      if (matchCount > 0) {
        // Read actual page content for preview
        const pagePath = this.getWikiPagePath(fact.category, fact.name);
        let pageContent = fact.content;
        try {
          if (existsSync(pagePath)) {
            pageContent = readFileSync(pagePath, "utf-8").slice(0, 500);
          }
        } catch {}

        results.push({
          name,
          category: fact.category,
          content: pageContent,
          relevance: matchCount / keywords.length,
        });
      }
    }

    // Sort by relevance, take top K
    results.sort((a, b) => b.relevance - a.relevance);
    return results.slice(0, topK);
  }

  /**
   * Get statistics.
   */
  getStats(): Record<string, unknown> {
    const byCategory: Record<string, number> = { entity: 0, concept: 0, synthesis: 0 };
    for (const [, fact] of this.index) {
      byCategory[fact.category] = (byCategory[fact.category] || 0) + 1;
    }

    let totalBytes = 0;
    let totalPages = 0;
    for (const dir of ["entity", "concept", "synthesis"]) {
      const p = join(this.wikiPath, dir);
      try {
        const files = readdirSync(p).filter((f) => f.endsWith(".md"));
        totalPages += files.length;
        for (const f of files) {
          try {
            totalBytes += statSync(join(p, f)).size;
          } catch {}
        }
      } catch {}
    }

    return {
      totalFacts: this.index.size,
      totalPages,
      totalBytes,
      byCategory,
      wikiPath: this.wikiPath,
    };
  }

  // ── Helpers ──

  private getWikiPagePath(category: FactCategory, name: string): string {
    // Sanitize + add hash suffix (matches Python daemon format)
    const safeName = name
      .replace(/[^a-zA-Z0-9\u4e00-\u9fff\s]/g, ' ')
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-')
      .replace(/^-|-$/g, '');
    const hash = this.simpleHash(name).slice(0, 8);
    return join(this.wikiPath, category, `${safeName}-${hash}.md`);
  }

  private simpleHash(str: string): string {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
      h = ((h << 5) - h) + str.charCodeAt(i);
      h |= 0; // Convert to 32bit integer
    }
    return Math.abs(h).toString(16);
  }

  private renderWikiPage(fact: StoredFact): string {
    // Format matches Python daemon's SharedWiki output exactly
    const catLabel = fact.category === 'entity' ? 'entity' : fact.category === 'concept' ? 'concept' : 'synthesis';
    
    // Pick emoji + label based on tags/content
    let emoji = '';
    let typeLabel = fact.category.charAt(0).toUpperCase() + fact.category.slice(1);
    
    if (fact.tags.includes('preference') || fact.tags.includes('auto-extracted-preference')) {
      emoji = '\u{1F3AF}'; // 🎯
      typeLabel = 'Preference';
    } else if (fact.tags.includes('decision') || fact.tags.includes('auto-extracted-decision')) {
      emoji = '\u2705'; // ✅
      typeLabel = 'Decision';
    } else if (fact.tags.includes('concept') || fact.category === 'concept') {
      emoji = '\u{1F4A1}'; // 💡
      typeLabel = 'Concept';
    } else if (fact.category === 'entity') {
      emoji = '\u{1F3AF}'; // 🎯
      typeLabel = 'Preference';
    } else if (fact.category === 'synthesis') {
      emoji = '\u2705'; // ✅
      typeLabel = 'Decision';
    }

    // Confidence bar (heuristic based on source length)
    const confidence = fact.sourceSnippet && fact.sourceSnippet.length > 20 ? 90 : 75;
    const filled = Math.round(confidence / 10);
    const empty = 10 - filled;

    return [
      `# ${catLabel} → ${fact.name}`,
      ``,
      `> Auto-generated by CAM Memory Core`,
      ``,
      `---`,
      ``,
      `${emoji} **${typeLabel}** | Confidence: \`\`${'█'.repeat(filled)}${'░'.repeat(empty)}\` (${confidence}%)`,
      ``,
      ${fact.content},
      ``,
      `*Source*: ${fact.sourceSnippet || '> *Extracted by agent*'}`,
      ...fact.tags.length > 0 ? [`*Tags*: ${fact.tags.map(t => \``\`${t}\`\``).join(' ')}`] : [],
      ``,
      `---`,
      ``,
    ].join('\n');
  }`,
  private extractKeywords(text: string): string[] {
    // Split on whitespace/punctuation, filter short words
    const words = text
      .toLowerCase()
      .split(/[\s,，。.!！?？:：;；\-\(\)（）\[\]【】{}]+/)
      .filter((w) => w.length >= 2);

    // Remove common stop words (English + Chinese)
    const stopWords = new Set([
      "the", "a", "an", "is", "are", "was", "were", "be", "been",
      "being", "have", "has", "had", "do", "does", "did", "will",
      "would", "could", "should", "may", "might", "shall", "can",
      "need", "dare", "ought", "used", "to", "of", "in", "for",
      "on", "with", "at", "by", "from", "as", "into", "through",
      "during", "before", "after", "above", "below", "between",
      "out", "off", "over", "under", "again", "further", "then",
      "once", "and", "but", "or", "nor", "not", "so", "yet",
      "both", "either", "neither", "each", "every", "all", "any",
      "few", "more", "most", "other", "some", "such", "no", "only",
      "own", "same", "than", "too", "very", "just", "because",
      "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
      "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
      "你", "会", "着", "没有", "看", "好", "自己", "这",
    ]);

    return [...new Set(words.filter((w) => !stopWords.has(w)))];
  }

  /**
   * Heuristic: auto-classify a fact based on content.
   */
  classifyFact(content: string, nameHint?: string): FactCategory {
    const text = (content + " " + (nameHint || "")).toLowerCase();

    // Entity indicators: proper nouns, specific names, tools, projects
    const entityPatterns = [
      /\b(project|tool|framework|library|app|service|server|agent|model|company|team|person)\b/i,
      /^[A-Z][a-z]+/,  // Starts with capital (proper noun)
    ];

    // Synthesis indicators: decisions, preferences, conclusions
    const synthesisPatterns = [
      /\b(decided|prefer|chose|selected|recommend|conclusion|should|must|always|never)\b/i,
      /\b(决定|偏好|选择|建议|应该|必须|总是|从不)\b/,
    ];

    // Check synthesis first (more specific)
    for (const pat of synthesisPatterns) {
      if (pat.test(text)) return "synthesis";
    }

    // Then entity
    for (const pat of entityPatterns) {
      if (pat.test(text)) return "entity";
    }

    // Default: concept
    return "concept";
  }

  /**
   * Heuristic: extract notable facts from a conversation turn.
   * Used by ingest() when Agent doesn't explicitly call cam_extract.
   */
  /**
   * Heuristic: extract notable facts from a conversation turn.
   * Used by ingest() when Agent doesn't explicitly call cam_extract.
   */
  private heuristicExtract(
    userMsg: string,
    aiResponse: string,
  ): Array<Omit<StoredFact, "timestamp">> {
    const facts: Array<Omit<StoredFact, "timestamp">> = [];
    const text = `${userMsg} ${aiResponse}`;

    // Decision patterns — extract clean decision phrase
    const decisions = [
      { re: /(?:decided|chose|selected|will\s+use|going to use|should use)\s+(PostgreSQL|MySQL|MongoDB|Redis|SQLite|Docker|Kubernetes|TDD|Drizzle|Prisma|TypeORM|FastAPI|Express|NextJS|React|Vue|Svelte|LangChain|CrewAI|AutoGen)(?:\s|$)/i, type: "synthesis" as FactCategory, tag: "decision" },
      { re: /(?:决定|选择|采用|使用|选用)(?:了|要)?\s*(.+?)(?:。|，|因为|用于|作为|$)/, type: "synthesis" as FactCategory, tag: "decision" },
      { re: /(?:use|using)\s+(PostgreSQL|MySQL|MongoDB|Redis|Docker|Kubernetes|TDD|Drizzle|Prisma|FastAPI|Express|NextJS|React|Vue)/i, type: "synthesis" as FactCategory, tag: "tool-decision" },
    ];

    for (const { re, type, tag } of decisions) {
      const match = text.match(re);
      if (match && match[1] && match[1].trim().length >= 2) {
        const extracted = match[1].trim();
        facts.push({
          name: this.sanitizeName(extracted),
          category: type,
          content: extracted,
          tags: ["auto-extracted", tag],
          agentId: "heuristic",
          sourceSnippet: "> " + userMsg + "\n" + match[0].trim(),
        });
      }
    }

    // Preference patterns — extract clean preference phrase
    const prefs = [
      { re: /(?:prefer|prefers|like using|always uses?)\s+(.+?)(?:\.\s|for |when |because|$)/i, type: "entity" as FactCategory, tag: "preference" },
      { re: /(?:VS Code with Cursor AI|Cursor AI extension|Claude Code best|Copilot Workspace|Docker|GitHub Actions|TDD|Drizzle ORM|PostgreSQL)/i, type: "entity" as FactCategory, tag: "tool" },
      { re: /(?:using|running|with)\s+(VS Code|Cursor|Claude Code|Copilot|Docker|PostgreSQL|GitHub Actions|TDD|Drizzle|Postgres)(?:\s|$|\b)/i, type: "entity" as FactCategory, tag: "tool" },
    ];

    for (const { re, type, tag } of prefs) {
      const match = text.match(re);
      if (match && match[1] && match[1].trim().length >= 2) {
        let extracted = match[1].trim();
        // Clean up common prefixes/suffixes
        extracted = extracted.replace(/^(the |a |an )/i, '').replace(/( for it| for this|, which.*)$/i, '').trim();
        if (extracted.length >= 2 && extracted.length <= 80) {
          facts.push({
            name: this.sanitizeName(extracted),
            category: type,
            content: extracted,
            tags: ["auto-extracted", tag],
            agentId: "heuristic",
            sourceSnippet: "> " + userMsg + "\n" + match[0].trim(),
          });
        }
      } else if (!match[1] && match[0] && match[0].length >= 5) {
        // Match on full pattern (e.g., tool names)
        const extracted = match[0].trim();
        facts.push({
          name: this.sanitizeName(extracted),
          category: type,
          content: extracted,
          tags: ["auto-extracted", tag],
          agentId: "heuristic",
          sourceSnippet: "> " + userMsg,
        });
      }
    }

    return facts;
  }
  private sanitizeName(name: string): string {
    return name
      .replace(/[^a-zA-Z0-9\u4e00-\u9fff\s-_]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 80);
  }
}

// ============================================================
// CamContextEngine — 框架自动调用的核心接口
// ============================================================

class CamContextEngine implements ContextEngine {
  private store: CamMemoryStore;
  private config: ReturnType<typeof resolveConfig>;
  private recentAttachments: Array<{
    type: string;
    name: string;
    detected: number;
  }> = [];
  private agentId = "unknown";
  private sessionId = "unknown";

  constructor(config: ReturnType<typeof resolveConfig>) {
    this.config = config;
    this.store = new CamMemoryStore(config.wikiPath);
    console.log(`[cam-engine] Initialized, wikiPath=${config.wikiPath}`);
  }

  async ingest(params: {
    sessionId: string;
    sessionKey?: string;
    message: {
      role: string;
      content?: string | Array<{ type: string; text?: string; image_url?: { url: string }; file_url?: { url: string } }>;
    };
    isHeartbeat?: boolean;
  }): Promise<IngestResult> {
    if (params.isHeartbeat) return { ingested: false };

    const { sessionId, message } = params;
    this.sessionId = sessionId;

    // Extract agent ID from session key if available
    const sk = params.sessionKey || "";
    if (sk.startsWith("agent:")) {
      this.agentId = sk.split(":")[1] || "unknown";
    }

    // Extract text content
    let userText = "";
    let aiText = "";

    if (message.role === "user") {
      userText = this.extractText(message.content);
    } else if (message.role === "assistant") {
      aiText = this.extractText(message.content);
    }

    // Detect attachments
    const attachments = this.detectAttachments(message);
    if (attachments.length > 0) {
      this.recentAttachments = attachments.map((a) => ({
        ...a,
        detected: Date.now(),
      }));
    }

    // Skip if no meaningful content
    if (!userText.trim() && !aiText.trim() && attachments.length === 0) {
      return { ingested: false };
    }

    // Store raw conversation
    this.store.storeRawConversation(
      userText || "(file/image attachment)",
      aiText || "(processing)",
      this.agentId,
      sessionId,
    );

    // Heuristic: auto-extract obvious facts
    if (userText.trim() && aiText.trim()) {
      const heuristicFacts = this.store.heuristicExtract(userText, aiText);
      for (const fact of heuristicFacts) {
        this.store.storeFact({
          ...fact,
          timestamp: new Date().toISOString(),
        });
      }
      if (heuristicFacts.length > 0) {
        console.log(
          `[cam-ingest] Auto-extracted ${heuristicFacts.length} facts (heuristic)`,
        );
      }
    }

    return { ingested: true };
  }

  async assemble(params: {
    sessionId: string;
    sessionKey?: string;
    budget?: number;
  }): Promise<AssembleResult> {
    // Read recent conversation context from wiki
    // We don't have a specific query here, so we load recent facts
    const stats = this.store.getStats();
    const totalPages = stats.totalPages as number;

    if (totalPages === 0) {
      return { content: "", tokenCount: 0 };
    }

    // Load a summary of recent wiki entries
    const indexPath = join(this.config.wikiPath, ".cam-index.json");
    let contextParts: string[] = [];

    try {
      if (existsSync(indexPath)) {
        const data = JSON.parse(readFileSync(indexPath, "utf-8"));
        const facts = data.facts || [];
        // Take the most recent N facts
        const recent = facts.slice(-this.config.maxRecallPages);
        for (const fact of recent) {
          const pagePath = this.store["getWikiPagePath"](
            fact.category,
            fact.name,
          );
          let preview = fact.content || "";
          try {
            if (existsSync(pagePath)) {
              preview = readFileSync(pagePath, "utf-8").slice(0, 300);
            }
          } catch {}
          contextParts.push(
            `**[${fact.category}] ${fact.name}**\n${preview}`,
          );
        }
      }
    } catch {}

    if (contextParts.length === 0) {
      return { content: "", tokenCount: 0 };
    }

    const content = [
      "## 🧠 CAM Memory Recall",
      "",
      `The following knowledge was recalled from your memory wiki (${totalPages} pages total):`,
      "",
      ...contextParts,
      "",
    ].join("\n");

    return {
      content,
      tokenCount: Math.ceil(content.length / 4),
    };
  }

  async compact(): Promise<void> {
    // CAM doesn't compact — that's LCM's job
  }

  // ── Public API for hooks/tools ──

  getStore(): CamMemoryStore {
    return this.store;
  }

  getRecentAttachments(): Array<{ type: string; name: string; detected: number }> {
    const now = Date.now();
    this.recentAttachments = this.recentAttachments.filter(
      (a) => now - a.detected < 60000,
    );
    return this.recentAttachments;
  }

  getAgentId(): string {
    return this.agentId;
  }

  // ── Helpers ──

  private extractText(
    content?: string | Array<{ type: string; text?: string }>,
  ): string {
    if (!content) return "";
    if (typeof content === "string") return content;
    if (Array.isArray(content)) {
      return content
        .filter((c) => c.type === "text" && c.text)
        .map((c) => c.text || "")
        .join("\n");
    }
    return String(content);
  }

  private detectAttachments(
    message: { role: string; content?: unknown },
  ): Array<{ type: string; name: string }> {
    const attachments: Array<{ type: string; name: string }> = [];
    const content = message.content;
    if (!content) return attachments;

    // Structured content blocks
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block && typeof block === "object") {
          if (block.type === "image" || block.type === "image_url") {
            attachments.push({
              type: "image",
              name: block.text || "image",
            });
          } else if (block.type === "file" || block.type === "file_url") {
            attachments.push({
              type: "file",
              name: block.text || block.filename || "file",
            });
          }
        }
      }
    }

    return attachments;
  }
}

// ============================================================
// Tool Definitions
// ============================================================

function createCamExtractTool(
  store: CamMemoryStore,
): ReturnType<OpenClawPluginApi["registerTool"]> extends (fn: (ctx: any) => infer R) => void ? R : never {
  return {
    name: "cam_extract",
    description:
      "Store extracted knowledge into the CAM memory wiki. " +
      "Use this when you identify important facts, decisions, preferences, or concepts " +
      "from the conversation that should be remembered for future sessions. " +
      "Each fact should have: name, content, category (entity/concept/synthesis), and optional tags.",
    parameters: {
      type: "object",
      properties: {
        facts: {
          type: "array",
          description:
            "Array of extracted facts to store. Each fact: {name, content, category?, tags?}",
          items: {
            type: "object",
            properties: {
              name: {
                type: "string",
                description: "Short name/title for this fact (e.g., 'React Framework', 'Deploy Decision')",
              },
              content: {
                type: "string",
                description: "The fact content in detail",
              },
              category: {
                type: "string",
                enum: ["entity", "concept", "synthesis"],
                description:
                  "entity=specific thing (tool/project/person), concept=abstract idea, synthesis=decision/preference/conclusion",
              },
              tags: {
                type: "array",
                items: { type: "string" },
                description: "Tags for categorization",
              },
            },
            required: ["name", "content"],
          },
        },
      },
      required: ["facts"],
    },
    async execute(args: {
      facts: Array<{
        name: string;
        content: string;
        category?: string;
        tags?: string[];
      }>;
    }): Promise<string> {
      const results: string[] = [];

      for (const fact of args.facts) {
        const category = (fact.category as FactCategory) || store.classifyFact(fact.content, fact.name);
        const stored = store.storeFact({
          name: fact.name,
          category,
          content: fact.content,
          tags: fact.tags || [],
          agentId: "agent-extracted",
          timestamp: new Date().toISOString(),
          sourceSnippet: "Agent-extracted via cam_extract tool",
        });

        results.push(
          stored
            ? `✅ Stored: [${category}] ${fact.name}`
            : `⏭️ Skipped (duplicate): ${fact.name}`,
        );
      }

      return `CAM Extract Results:\n${results.join("\n")}`;
    },
  } as any;
}

function createCamQueryTool(
  store: CamMemoryStore,
): any {
  return {
    name: "cam_query",
    description:
      "Search the CAM memory wiki for relevant knowledge. " +
      "Use this when you need to recall previously stored facts, decisions, or concepts.",
    parameters: {
      type: "object",
      properties: {
        question: {
          type: "string",
          description: "What to search for in the memory wiki",
        },
        top_k: {
          type: "number",
          description: "Max results to return (default: 5)",
        },
      },
      required: ["question"],
    },
    async execute(args: { question: string; top_k?: number }): Promise<string> {
      const results = store.query(args.question, args.top_k || 5);

      if (results.length === 0) {
        return "No matching memories found in the CAM wiki.";
      }

      const lines = results.map(
        (r, i) =>
          `${i + 1}. **[${r.category}] ${r.name}** (relevance: ${(r.relevance * 100).toFixed(0)}%)\n   ${r.content.slice(0, 200)}`,
      );

      return `CAM Query Results for "${args.question}":\n\n${lines.join("\n\n")}`;
    },
  };
}

function createCamStatsTool(store: CamMemoryStore): any {
  return {
    name: "cam_stats",
    description: "Show CAM memory wiki statistics.",
    parameters: { type: "object", properties: {} },
    async execute(): Promise<string> {
      const stats = store.getStats();
      return [
        `📊 **CAM Memory Wiki Stats**`,
        ``,
        `- **Total Facts**: ${stats.totalFacts}`,
        `- **Total Pages**: ${stats.totalPages}`,
        `- **Total Size**: ${(stats.totalBytes as number / 1024).toFixed(1)} KB`,
        `- **Entity Pages**: ${stats.byCategory.entity}`,
        `- **Concept Pages**: ${stats.byCategory.concept}`,
        `- **Synthesis Pages**: ${stats.byCategory.synthesis}`,
        `- **Wiki Path**: ${stats.wikiPath}`,
      ].join("\n");
    },
  };
}

function createCamExtractFileTool(
  store: CamMemoryStore,
): any {
  return {
    name: "cam_extract_file",
    description:
      "Extract knowledge from a file, image, or document and store it in the CAM wiki. " +
      "Use this when the user shares a file and you want to learn from its contents. " +
      "First read/analyze the file, then call this tool with the extracted facts.",
    parameters: {
      type: "object",
      properties: {
        filename: {
          type: "string",
          description: "Name of the file being processed",
        },
        facts: {
          type: "array",
          description: "Extracted facts from the file",
          items: {
            type: "object",
            properties: {
              name: { type: "string" },
              content: { type: "string" },
              category: {
                type: "string",
                enum: ["entity", "concept", "synthesis"],
              },
              tags: { type: "array", items: { type: "string" } },
            },
            required: ["name", "content"],
          },
        },
      },
      required: ["filename", "facts"],
    },
    async execute(args: {
      filename: string;
      facts: Array<{
        name: string;
        content: string;
        category?: string;
        tags?: string[];
      }>;
    }): Promise<string> {
      const results: string[] = [];

      for (const fact of args.facts) {
        const category = (fact.category as FactCategory) || store.classifyFact(fact.content, fact.name);
        const stored = store.storeFact({
          name: fact.name,
          category,
          content: fact.content,
          tags: [...(fact.tags || []), `file:${args.filename}`],
          agentId: "agent-extracted",
          timestamp: new Date().toISOString(),
          sourceSnippet: `Extracted from file: ${args.filename}`,
        });

        results.push(
          stored
            ? `✅ Stored: [${category}] ${fact.name} (from ${args.filename})`
            : `⏭️ Skipped: ${fact.name}`,
        );
      }

      return `CAM File Extraction Results (${args.filename}):\n${results.join("\n")}`;
    },
  };
}

// ============================================================
// Hook Handlers
// ============================================================

const CAM_RECALL_INSTRUCTION = `[CAM Memory System]
You have access to a Compound Agent Memory (CAM) system. Here's how to use it:

1. **cam_extract** — When you identify important knowledge (decisions, preferences, facts, concepts), use this tool to store it in the memory wiki. This ensures the knowledge persists across sessions.

2. **cam_query** — When you need to recall previously stored knowledge, use this tool to search the memory wiki.

3. **cam_extract_file** — When the user shares a file/image/document, analyze it and use this tool to store extracted knowledge.

Guidelines:
- Extract facts proactively — don't wait to be asked
- Categories: entity (specific things), concept (abstract ideas), synthesis (decisions/preferences)
- Store decisions, user preferences, project conventions, technical choices
- Do NOT store trivial or obvious information`;

function handleBeforePromptBuild(
  config: ReturnType<typeof resolveConfig>,
  engine: CamContextEngine,
): { prependSystemContext?: string } {
  if (!config.injectOnPrompt) return {};

  const parts: string[] = [CAM_RECALL_INSTRUCTION];

  // Check for recent attachments
  const attachments = engine.getRecentAttachments();
  if (attachments.length > 0) {
    const fileList = attachments
      .map((a) => `- 📄 ${a.type}: ${a.name}`)
      .join("\n");
    parts.push("");
    parts.push(
      `⚠️ FILE/IMAGE DETECTED — You received the following attachments:\n${fileList}\n\nYou MUST analyze the file/image content and use cam_extract_file to store key knowledge from it.`,
    );
  }

  return { prependSystemContext: parts.join("\n") };
}

// ============================================================
// Plugin Registration
// ============================================================

const camPlugin = {
  id: "cam",
  version: "6.0.0",

  configSchema: {
    parse(value: unknown) {
      const raw =
        value && typeof value === "object" && !Array.isArray(value)
          ? (value as Record<string, unknown>)
          : {};
      return resolveConfig(raw);
    },
  },

  register(api: OpenClawPluginApi): void {
    const config = resolveConfig(api.config || {});
    const engine = new CamContextEngine(config);
    const store = engine.getStore();

    // ── L1: ContextEngine (框架自动调用) ──
    api.registerContextEngine("cam", () => engine);

    // ── L2: Tools (Agent 主动调用) ──
    api.registerTool(() => createCamExtractTool(store));
    api.registerTool(() => createCamQueryTool(store));
    api.registerTool(() => createCamStatsTool(store));
    api.registerTool(() => createCamExtractFileTool(store));

    // ── L3: Hooks (补充增强) ──
    api.on("before_prompt_build", () =>
      handleBeforePromptBuild(config, engine),
    );

    console.log(`[cam] Plugin v6.0 loaded (Self-Contained)`);
    console.log(`[cam] wikiPath=${config.wikiPath}`);
    console.log(`[cam] No external daemon needed — all logic is self-contained`);
    console.log(`[cam] Tools: cam_extract, cam_query, cam_stats, cam_extract_file`);
  },
};

export default camPlugin;
