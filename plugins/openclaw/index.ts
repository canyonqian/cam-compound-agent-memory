/**
 * CAM — Compound Agent Memory Plugin v11.0 (Autonomous Knowledge Brain)
 *
 * 核心理念：CAM 自主学习知识，不教 Agent 做事。
 *
 * 流程：
 *   1. message_received → 缓存用户消息
 *   2. llm_output → 拦截 agent 的 LLM 回答 → 启发式提取知识 → 写 wiki
 *   3. before_prompt_build → 召回 wiki 知识注入上下文
 *
 * 架构：
 *   L1 Hooks（独立于 ContextEngine slot）
 *     - message_received    → 缓存用户消息
 *     - llm_output          → 从 agent 回答中提取知识写 wiki
 *     - before_prompt_build → 召回 wiki 知识注入 prompt
 *   L2 Tool（Agent 可选调用）
 *     - cam_query  → 搜索 CAM wiki
 *     - cam_stats  → 显示 wiki 统计
 *
 * v11.0：用 OpenClaw 配置的大模型，不再调用 Ollama。
 *        通过 llm_output 钩子直接从 agent 回答中提取知识，零额外 LLM 调用。
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
} from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

// Module-level state — shared across all plugin instances in the same process
// Since Node.js is single-threaded, just track the most recent user message
let lastUserMessage = "";

function setPendingUserMsg(content: string) {
  if (content.trim().length > 5) {
    lastUserMessage = content;
  }
}

function getPendingUserMsg(): string {
  return lastUserMessage;
}

function clearPendingUserMsg() {
  lastUserMessage = "";
}

// ============================================================
// Config
// ============================================================

function resolveConfig(cfg: Record<string, unknown>) {
  let wikiPath = (cfg.wikiPath as string) || "";
  if (!wikiPath && typeof cfg.config === "object" && cfg.config !== null) {
    wikiPath = ((cfg.config as Record<string, unknown>).wikiPath as string) || "";
  }
  if (typeof cfg.plugins === "object" && cfg.plugins !== null) {
    const plugins = cfg.plugins as Record<string, unknown>;
    if (typeof plugins.cam === "object" && plugins.cam !== null) {
      const cam = plugins.cam as Record<string, unknown>;
      if (typeof cam.config === "object" && cam.config !== null) {
        wikiPath = ((cam.config as Record<string, unknown>).wikiPath as string) || "";
      }
    }
    if (!wikiPath && typeof plugins.entries === "object" && plugins.entries !== null) {
      const entries = plugins.entries as Record<string, unknown>;
      if (typeof entries.cam === "object" && entries.cam !== null) {
        const camEntry = entries.cam as Record<string, unknown>;
        if (typeof camEntry.config === "object" && camEntry.config !== null) {
          wikiPath = ((camEntry.config as Record<string, unknown>).wikiPath as string) || "";
        }
      }
    }
  }
  wikiPath = wikiPath || process.env.CAM_WIKI_PATH || process.env.CAM_PROJECT_DIR || "/root/cam/wiki";

  return {
    wikiPath,
    injectOnPrompt: cfg.injectOnPrompt !== false,
    maxRecallPages: Math.min(Math.max((cfg.maxRecallPages as number) || 5, 1), 20),
  };
}

// ============================================================
// CamMemoryStore
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
    for (const dir of ["entity", "concept", "synthesis"]) {
      const p = join(this.wikiPath, dir);
      if (!existsSync(p)) mkdirSync(p, { recursive: true });
    }
    if (!existsSync(join(this.wikiPath, "raw"))) {
      mkdirSync(join(this.wikiPath, "raw"), { recursive: true });
    }
    this.loadIndex();
  }

  private loadIndex(): void {
    try {
      if (existsSync(this.indexPath)) {
        const data = JSON.parse(readFileSync(this.indexPath, "utf-8"));
        if (data.facts && Array.isArray(data.facts)) {
          for (const f of data.facts) this.index.set(f.name, f);
        }
        console.log(`[cam-store] Loaded index: ${this.index.size} facts`);
      }
    } catch (e) {
      console.warn(`[cam-store] Failed to load index: ${e}`);
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

  private similarity(a: string, b: string): number {
    const wordsA = new Set(a.toLowerCase().split(/\s+/));
    const wordsB = new Set(b.toLowerCase().split(/\s+/));
    if (wordsA.size === 0 || wordsB.size === 0) return 0;
    let intersection = 0;
    for (const w of wordsA) { if (wordsB.has(w)) intersection++; }
    const union = wordsA.size + wordsB.size - intersection;
    return union > 0 ? intersection / union : 0;
  }

  storeFact(fact: StoredFact): boolean {
    // Dedup
    for (const [, other] of this.index) {
      if (other.category !== fact.category) continue;
      if (other.name === fact.name) return false;
      const sim = this.similarity(fact.content, other.content);
      if (sim >= 0.6) return false;
    }

    const pagePath = this.getWikiPagePath(fact.category, fact.name);
    const dir = join(this.wikiPath, fact.category);
    if (!existsSync(dir)) mkdirSync(dir, { recursive: true });

    writeFileSync(pagePath, this.renderWikiPage(fact), "utf-8");
    this.index.set(fact.name, fact);
    this.dirty = true;
    this.saveIndex();
    return true;
  }

  storeRawConversation(userMsg: string, aiResponse: string, agentId: string, sessionId: string): void {
    const rawDir = join(this.wikiPath, "raw");
    if (!existsSync(rawDir)) mkdirSync(rawDir, { recursive: true });
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    const filename = `${timestamp}-${agentId}-${sessionId.slice(0, 8)}.md`;
    const content = [
      `# Conversation Turn`,
      `- **Agent**: ${agentId}`,
      `- **Time**: ${new Date().toISOString()}`,
      `## User`,
      userMsg,
      `## Assistant`,
      aiResponse,
    ].join("\n");
    writeFileSync(join(rawDir, filename), content, "utf-8");
  }

  query(question: string, topK: number = 5): Array<{ name: string; category: FactCategory; content: string; relevance: number }> {
    const keywords = this.extractKeywords(question);
    if (keywords.length === 0) return [];
    const results: Array<{ name: string; category: FactCategory; content: string; relevance: number }> = [];
    for (const [name, fact] of this.index) {
      const searchText = `${name} ${fact.content} ${fact.tags.join(" ")}`.toLowerCase();
      let matchCount = 0;
      for (const kw of keywords) { if (searchText.includes(kw.toLowerCase())) matchCount++; }
      if (matchCount > 0) {
        const pagePath = this.getWikiPagePath(fact.category, fact.name);
        let pageContent = fact.content;
        try { if (existsSync(pagePath)) pageContent = readFileSync(pagePath, "utf-8").slice(0, 500); } catch {}
        results.push({ name, category: fact.category, content: pageContent, relevance: matchCount / keywords.length });
      }
    }
    results.sort((a, b) => b.relevance - a.relevance);
    return results.slice(0, topK);
  }

  getStats(): Record<string, unknown> {
    const byCategory: Record<string, number> = { entity: 0, concept: 0, synthesis: 0 };
    for (const [, fact] of this.index) byCategory[fact.category] = (byCategory[fact.category] || 0) + 1;
    let totalBytes = 0, totalPages = 0;
    for (const dir of ["entity", "concept", "synthesis"]) {
      const p = join(this.wikiPath, dir);
      try {
        const files = readdirSync(p).filter((f) => f.endsWith(".md"));
        totalPages += files.length;
        for (const f of files) try { totalBytes += statSync(join(p, f)).size; } catch {}
      } catch {}
    }
    return { totalFacts: this.index.size, totalPages, totalBytes, byCategory, wikiPath: this.wikiPath };
  }

  private getWikiPagePath(category: FactCategory, name: string): string {
    const safeName = name.replace(/[^a-zA-Z0-9\u4e00-\u9fff\s]/g, " ").replace(/\s+/g, "-").replace(/-+/g, "-").replace(/^-|-$/g, "");
    const hash = this.simpleHash(name).slice(0, 8);
    return join(this.wikiPath, category, `${safeName}-${hash}.md`);
  }

  private simpleHash(str: string): string {
    let h = 0;
    for (let i = 0; i < str.length; i++) { h = ((h << 5) - h) + str.charCodeAt(i); h |= 0; }
    return Math.abs(h).toString(16);
  }

  private renderWikiPage(fact: StoredFact): string {
    let emoji: string, typeLabel: string;
    const tags = fact.tags.join(" ");
    if (tags.includes("concept")) { emoji = "\u{1F4A1}"; typeLabel = "Concept"; }
    else if (tags.includes("entity")) { emoji = "\u{1F3AF}"; typeLabel = "Entity"; }
    else if (tags.includes("mechanism")) { emoji = "\u2699\uFE0F"; typeLabel = "Mechanism"; }
    else if (tags.includes("problem-solving")) { emoji = "\u{1F527}"; typeLabel = "Problem Solving"; }
    else if (tags.includes("comparison")) { emoji = "\u2696\uFE0F"; typeLabel = "Comparison"; }
    else if (tags.includes("actionable")) { emoji = "\u{1F680}"; typeLabel = "Actionable"; }
    else { emoji = "\u{1F4DD}"; typeLabel = "Knowledge"; }

    const confidence = 85;
    const filled = 8, empty = 2;
    const bar = "\u2588".repeat(filled) + "\u2591".repeat(empty);

    return [
      `# ${fact.category} \u2192 ${fact.name}`,
      "",
      "> Auto-learned by CAM Knowledge Brain",
      "",
      "---",
      "",
      `${emoji} **${typeLabel}** | Confidence: \`${bar}\` (${confidence}%)`,
      "",
      fact.content,
      "",
      `*Source*: ${fact.sourceSnippet || "*Autonomous extraction*"}`,
      `*Tags*: ${fact.tags.map((t) => `\`${t}\``).join(" ")}`,
      "",
      "---",
      "",
    ].join("\n");
  }

  private extractKeywords(text: string): string[] {
    const words = text.toLowerCase().split(/[\s,，。.!！?？:：;；\-\(\)（）\[\]【】{}]+/).filter((w) => w.length >= 2);
    const stopWords = new Set(["the","a","an","is","are","was","were","be","been","being","have","has","had","do","does","did","will","would","could","should","may","might","shall","can","need","to","of","in","for","on","with","at","by","from","as","into","through","during","before","after","above","below","between","out","off","over","under","again","further","then","once","and","but","or","nor","not","so","yet","both","either","neither","each","every","all","any","few","more","most","other","some","such","no","only","own","same","than","too","very","just","because","的","了","在","是","我","有","和","就","不","人","都","一","一个","上","也","很","到","说","要","去","你","会","着","没有","看","好","自己","这"]);
    return [...new Set(words.filter((w) => !stopWords.has(w)))];
  }
}

// ============================================================
// Heuristic knowledge extraction from agent responses
// ============================================================

/**
 * Strip agent's internal thinking/meta-commentary/cron logs from the response.
 * Removes: "Let me search...", "我来看一下", cron execution traces, system metadata, NO_REPLY.
 * Keeps: actual knowledge, explanations, comparisons, technical content.
 */
function stripAgentThinking(text: string): string {
  const lines = text.split("\n");
  const kept: string[] = [];
  let pastThinking = false;

  for (const line of lines) {
    const trimmed = line.trim();

    // ── Skip system metadata blocks (JSON) ──
    if (trimmed.startsWith("```json") || (trimmed.startsWith("{") && trimmed.includes("message_id"))) continue;
    if (trimmed.includes("untrusted metadata")) continue;
    if (/^ou_[a-f0-9]{10,}$/.test(trimmed)) continue; // standalone Feishu user ID

    // ── Skip cron execution traces ──
    const cronPatterns = [
      /cron fired at/i,
      /quiet hours/i,
      /technically outside quiet hours/i,
      /in human terms/i,
      /user (is )?(definitely )?sleep/i,
      /I've been deferring/i,
      /deferred send/i,
      /Internal handling complete/i,
      /NO_REPLY/,
      /^Internal handling/i,
      /\.+ consecutive defer/i,
      /accumulated reports/i,
      /next cron will execute/i,
      /when (quiet hours end|user wakes)/i,
    ];
    if (cronPatterns.some((p) => p.test(trimmed))) continue;

    // ── Skip mem0/storage execution traces ──
    const storagePatterns = [
      /mem0 storage (completed|done)/i,
      /storing in mem0/i,
      /stored in mem0/i,
      /stored .*memory/i,
      /exit code 0.*just terminal/i,
      /JSON parsing error.*just terminal/i,
      /^Mem0/i,
      /^Good search results/i,
      /^Web search is working/i,
      /search for what's new/i,
      /Let me (search|execute|handle|compile|analyze|store|fetch)/i,
      /^(Executing|Search|Searching)/i,
    ];
    if (storagePatterns.some((p) => p.test(trimmed))) continue;

    // ── Skip leading thinking lines ──
    if (!pastThinking) {
      const thinkingPatterns = [
        /^(好的|好的，|好的!|好的！|明白|收到|没问题|让我|我来|我来查|我来搜索|我来看看|我来找|已学习完毕)/i,
        /^(let me|i'll|i will|sure|ok|of course)/i,
        /^(fetching|searching|looking up|checking|analyzing)/i,
        /^(搜索|查找|看看|分析一下|帮你|为你)/i,
        /^已存入.*memory/i,
        /^这个模式.*很有参考价值/i,
        /^(找到|找到了)/i,
        /^(Excellent|Great|Perfect|Done|完成)\b/i,
        /^(Note:|However, I should)/i,
      ];
      if (thinkingPatterns.some((p) => p.test(trimmed))) continue;
      if (trimmed === "" && !pastThinking) continue;
      pastThinking = true;
    }

    // ── Skip trailing meta-commentary ──
    const trailingPatterns = [
      /^这个模式对于.*很有参考价值/i,
      /^如果你需要/i,
      /^希望这个.*对你有/i,
      /^以上/i,
      /^总结[：:]/i,
      /^已存入.*memory/i,
      /^要我.*研究.*吗/i,
      /^要我帮你/i,
      /让我存到记忆里/i,
      /\.+ 要我.*吗？$/i,
      /^Let me (analyze|compile|search|store)/i,
    ];
    if (trailingPatterns.some((p) => p.test(trimmed))) continue;

    kept.push(line);
  }

  return kept.join("\n").trim();
}

/**
 * Clean markdown for wiki storage — preserve structure, remove noise.
 */
function cleanMarkdown(text: string): string {
  // Remove JSON code blocks (system metadata, config dumps)
  let out = text.replace(/```json[\s\S]*?```/g, "");

  // Collapse code blocks into readable form (truncate very long ones)
  out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => {
    const lines = code.trim().split("\n").slice(0, 15); // max 15 lines
    return code.length > 300 ? lines.join("\n") + "\n[...]" : code;
  });

  // Simplify tables: keep the data, remove the border syntax
  out = out.replace(/\n(\|.+\|\n\|[-| :]+\|\n((?:\|.+\|\n?)+))/g, (m, tableBlock) => {
    // Remove the header separator line (|---|---|)
    return tableBlock
      .split("\n")
      .filter((l) => !/^[\s|:-]+$/.test(l.trim()) && l.trim().length > 3)
      .join("\n");
  });

  // Remove horizontal rules
  out = out.replace(/^-{3,}$/gm, "");

  // Remove image links (keep alt text if present)
  out = out.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");

  // Simplify links: keep text, remove URLs
  out = out.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");

  // Remove orphan Feishu IDs (ou_xxx, om_xxx)
  out = out.replace(/ou_[a-f0-9]{20,}/g, "");
  out = out.replace(/om_[a-f0-9]{20,}/g, "");

  // Collapse excessive blank lines
  out = out.replace(/\n{3,}/g, "\n\n");

  return out.trim();
}

/**
 * Extract a meaningful topic name from agent response headers.
 */
function extractTopic(response: string): string {
  // Try to find the first meaningful header
  const headerMatch = response.match(/^#{1,3}\s+(.+)$/m);
  if (headerMatch) {
    const topic = headerMatch[1].trim();
    // Reject system metadata or cron noise as topics
    if (topic.length > 3 && topic.length < 80 &&
        !topic.includes("untrusted metadata") &&
        !topic.includes("Conversation info") &&
        !topic.toLowerCase().includes("cron fired") &&
        !topic.toLowerCase().includes("this is the daily") &&
        !topic.startsWith("```")) {
      return topic;
    }
  }
  // Try to find a key term from the first non-empty substantive line
  const lines = response.split("\n");
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.length < 5) continue;
    // Skip thinking, metadata, and cron lines
    if (/^(let me|好的|让我|找到|找到了|搜索|Executing|Search|The AI frontier|This is the daily|Mem0|Good search|Quiet hours|cron fired|Internal|NO_REPLY|Done|完成|Source Question)/i.test(trimmed)) continue;
    if (trimmed.startsWith("```")) continue;
    if (trimmed.startsWith("{") || trimmed.includes("untrusted metadata")) continue;
    return trimmed.slice(0, 60);
  }
  return "unknown";
}

/**
 * Extract knowledge from agent's LLM response using heuristics.
 * No extra LLM call needed — uses what the agent already generated.
 */
function heuristicExtract(
  userMessage: string,
  agentResponse: string,
): Array<{ type: "concept" | "entity" | "synthesis"; content: string }> {
  const facts: Array<{ type: "concept" | "entity" | "synthesis"; content: string }> = [];

  // Skip greetings, short replies
  const greetingPatterns = [/^(好的|好的，|好的!|好的！|明白|收到|没问题|可以|当然|ok|yes|sure|hi|hello|hey)/i];
  if (greetingPatterns.some((p) => p.test(agentResponse.trim()))) return facts;
  if (agentResponse.trim().length < 100) return facts;

  // Early rejection: cron execution logs, internal status reports, pure NO_REPLY
  const cronRejection = [
    /cron fired at/i,
    /Internal handling complete/i,
    /NO_REPLY/i,
    /Mem0 storage completed/i,
    /Quiet hours.*UTC/i,
    /I've been deferring since/i,
    /This is the daily/i,
    /the user is definitely sleeping/i,
    /accumulated reports when user wakes/i,
  ];
  // Only reject if the majority of the response is cron/internal stuff
  const hasCronContent = cronRejection.some((p) => p.test(agentResponse));
  const hasSubstantiveContent = /原理|机制|架构|对比|区别|vs\.?|技术|实现|配置|建议|分析|principle|mechanism|architecture|comparison|solution|configuration/i.test(agentResponse);
  if (hasCronContent && !hasSubstantiveContent) return facts;

  // Step 1: Strip agent thinking/meta-commentary
  const knowledgeText = stripAgentThinking(agentResponse);

  // Step 2: Clean markdown for wiki storage
  const cleanText = cleanMarkdown(knowledgeText);

  if (cleanText.length < 50) return facts;

  // After cleaning, check if anything substantive remains
  if (cleanText.toLowerCase().includes("untrusted metadata") || cleanText.toLowerCase().includes("conversation info")) return facts;

  const topic = extractTopic(agentResponse);
  if (topic === "unknown" || topic.length < 3) return facts;

  // 1. Technical explanation → concept
  const explanationSignals = [
    /原理|机制|工作方式|运行方式|如何实现|底层|工作流|架构|核心|关键|技术|算法/,
    /because|principle|mechanism|how it works|architecture|workflow|core|key technique/,
  ];
  const hasExplanation = explanationSignals.some((p) => p.test(agentResponse));

  // 2. Comparison/contrast → synthesis
  const comparisonSignals = [
    /vs\.?|对比|区别|相比|不同于|与.*不同|差异|优劣|权衡|trade.?off|比较/i,
  ];

  // 3. Solution/steps → synthesis
  const solutionSignals = [
    /解决方案|解决方法|修复方法|步骤|第一步|首先.*然后|最佳实践|配置建议/,
    /to fix|solution|step 1|first.*then|finally|workaround|best practice|configuration/i,
  ];

  const isComparison = comparisonSignals.some((p) => p.test(agentResponse));
  const isSolution = solutionSignals.some((p) => p.test(agentResponse));

  // Prioritize: if explanation + comparison, make synthesis (dedup)
  if (hasExplanation && cleanText.length > 80) {
    const content = `Topic: ${topic}\n\nSource Question: ${userMessage || "(technical discussion)"}\n\n${cleanText.slice(0, 2000)}`;
    facts.push({ type: "concept", content });
  }

  // Only create synthesis if it's distinctly comparison or solution AND concept wasn't already created
  if ((isComparison || isSolution) && cleanText.length > 100) {
    const label = isComparison ? "(comparison)" : "(solution)";
    const solutionContent = `Topic: ${topic}\n\nSource Question: ${userMessage || label}\n\n${cleanText.slice(0, 2000)}`;
    // Dedup: skip if concept already covers this topic
    if (!facts.some((f) => f.type === "concept" && f.content.includes(topic))) {
      facts.push({ type: "synthesis", content: solutionContent });
    }
  }

  // 4. Tech entities mentioned in technical context
  const codeBlocks = agentResponse.match(/```(\w+)?\n[\s\S]*?```/g);
  if (codeBlocks && codeBlocks.length > 0) {
    const techNames = agentResponse.match(/\b(SQLite|PostgreSQL|Redis|MongoDB|MySQL|GraphQL|REST|gRPC|WebSocket|Nginx|Kafka|RabbitMQ|React|Vue|Next\.?js|Django|Flask|FastAPI|Express|TensorFlow|PyTorch|Ollama|Kubernetes|Terraform|Docker|Git|WAL|JDBC|ORM|ACID|RAG|MinerU|PaddleOCR|LightRAG|Docling)\b/g);
    for (const tech of [...new Set(techNames || [])]) {
      if (!facts.some((f) => f.content.includes(tech))) {
        facts.push({
          type: "entity",
          content: `${tech}: mentioned in technical context — ${userMessage.slice(0, 100)}`,
        });
      }
    }
  }

  // Dedup — use first 80 chars as fingerprint
  const seen = new Set<string>();
  return facts.filter((f) => {
    const key = f.content.slice(0, 80);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ============================================================
// CamContextEngine
// ============================================================

class CamContextEngine implements ContextEngine {
  private store: CamMemoryStore;
  private config: ReturnType<typeof resolveConfig>;
  private recentAttachments: Array<{ type: string; name: string; detected: number }> = [];
  private agentId = "unknown";
  private sessionId = "unknown";
  pendingUserMsg = "";

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
    if (!message || typeof message !== "object") return { ingested: false };

    this.sessionId = sessionId;
    const sk = params.sessionKey || "";
    if (sk.startsWith("agent:")) this.agentId = sk.split(":")[1] || "unknown";

    if (message.role === "user") {
      this.pendingUserMsg = this.extractText(message.content);
    }

    const attachments = this.detectAttachments(message);
    if (attachments.length > 0) {
      this.recentAttachments = attachments.map((a) => ({ ...a, detected: Date.now() }));
    }

    return { ingested: true };
  }

  async assemble(params: { sessionId: string; sessionKey?: string; budget?: number }): Promise<AssembleResult> {
    const stats = this.store.getStats();
    const totalPages = stats.totalPages as number;
    if (totalPages === 0) return { content: "", tokenCount: 0 };

    const indexPath = join(this.config.wikiPath, ".cam-index.json");
    const contextParts: string[] = [];
    try {
      if (existsSync(indexPath)) {
        const data = JSON.parse(readFileSync(indexPath, "utf-8"));
        const facts = data.facts || [];
        const recent = facts.slice(-this.config.maxRecallPages);
        for (const fact of recent) {
          const pagePath = this.store["getWikiPagePath"](fact.category, fact.name);
          let preview = fact.content || "";
          try { if (existsSync(pagePath)) preview = readFileSync(pagePath, "utf-8").slice(0, 300); } catch {}
          contextParts.push(`**[${fact.category}] ${fact.name}**\n${preview}`);
        }
      }
    } catch {}

    if (contextParts.length === 0) return { content: "", tokenCount: 0 };

    const content = [
      "## CAM Knowledge Recall",
      "",
      `The following knowledge has been learned and stored in CAM (${totalPages} pages):`,
      "",
      ...contextParts,
      "",
      "Use this knowledge to inform your answers.",
    ].join("\n");

    return { content, tokenCount: Math.ceil(content.length / 4) };
  }

  async compact(): Promise<void> {}

  getStore(): CamMemoryStore { return this.store; }
  getRecentAttachments(): Array<{ type: string; name: string; detected: number }> {
    const now = Date.now();
    this.recentAttachments = this.recentAttachments.filter((a) => now - a.detected < 60000);
    return this.recentAttachments;
  }
  getAgentId(): string { return this.agentId; }

  private extractText(content?: string | Array<{ type: string; text?: string }>): string {
    if (!content) return "";
    if (typeof content === "string") return content;
    if (Array.isArray(content)) return content.filter((c) => c.type === "text" && c.text).map((c) => c.text || "").join("\n");
    return String(content);
  }

  private detectAttachments(message: { role: string; content?: unknown }): Array<{ type: string; name: string }> {
    const attachments: Array<{ type: string; name: string }> = [];
    const content = message.content;
    if (!content) return attachments;
    if (Array.isArray(content)) {
      for (const block of content) {
        if (block && typeof block === "object") {
          if (block.type === "image" || block.type === "image_url") attachments.push({ type: "image", name: block.text || "image" });
          else if (block.type === "file" || block.type === "file_url") attachments.push({ type: "file", name: block.text || (block as any).filename || "file" });
        }
      }
    }
    return attachments;
  }
}

// ============================================================
// Tools
// ============================================================

function createCamQueryTool(store: CamMemoryStore): any {
  return {
    name: "cam_query",
    description: "Search the CAM knowledge wiki for relevant facts and concepts.",
    parameters: {
      type: "object",
      properties: {
        question: { type: "string", description: "What to search for" },
        top_k: { type: "number", description: "Max results (default: 5)" },
      },
      required: ["question"],
    },
    async execute(args: { question: string; top_k?: number }): Promise<string> {
      const results = store.query(args.question, args.top_k || 5);
      if (results.length === 0) return "No matching knowledge in CAM wiki.";
      const lines = results.map((r, i) => `${i + 1}. **[${r.category}] ${r.name}**\n   ${r.content.slice(0, 200)}`);
      return `CAM Query Results:\n\n${lines.join("\n\n")}`;
    },
  };
}

function createCamStatsTool(store: CamMemoryStore): any {
  return {
    name: "cam_stats",
    description: "Show CAM knowledge wiki statistics.",
    parameters: { type: "object", properties: {} },
    async execute(): Promise<string> {
      const stats = store.getStats();
      return [`CAM Knowledge Wiki:`, ``, `- Total: ${stats.totalFacts} facts, ${stats.totalPages} pages`, `- Concepts: ${stats.byCategory.concept}`, `- Entities: ${stats.byCategory.entity}`, `- Wiki: ${stats.wikiPath}`].join("\n");
    },
  };
}

// ============================================================
// Hook — cache user message + recall wiki knowledge
// ============================================================

function handleBeforePromptBuild(
  config: ReturnType<typeof resolveConfig>,
  engine: CamContextEngine,
  store: CamMemoryStore,
): (event: any, ctx: any) => Promise<{ prependSystemContext?: string; prependContext?: string }> {
  return async (event, ctx) => {
    // Cache latest user message from session messages
    if (event.messages && Array.isArray(event.messages)) {
      for (let i = event.messages.length - 1; i >= 0; i--) {
        const msg = event.messages[i];
        if (msg && msg.role === "user" && msg.content) {
          const text = typeof msg.content === "string" ? msg.content : "";
          if (text.trim().length > 5) {
            engine.pendingUserMsg = text;
            break;
          }
        }
      }
    }

    if (!config.injectOnPrompt) return {};

    const contextParts: string[] = [];

    // Inject Layer 3: Schema rules (always, so agent knows how to organize)
    const schemaPath = join(config.wikiPath, "..", "schema", "CLAUDE.md");
    try {
      if (existsSync(schemaPath)) {
        const schemaContent = readFileSync(schemaPath, "utf-8");
        contextParts.push("### CAM Knowledge Schema (Layer 3 — Rules)\n" + schemaContent.slice(0, 2000));
      }
    } catch {}

    // Inject Layer 2: Wiki knowledge recall
    const stats = store.getStats();
    const totalPages = stats.totalPages as number;
    if (totalPages > 0) {
      const indexPath = join(config.wikiPath, ".cam-index.json");
      try {
        if (existsSync(indexPath)) {
          const data = JSON.parse(readFileSync(indexPath, "utf-8"));
          const facts = data.facts || [];
          const recent = facts.slice(-config.maxRecallPages);
          for (const fact of recent) {
            const pagePath = join(config.wikiPath, fact.category, `${fact.name.replace(/[^a-zA-Z0-9\u4e00-\u9fff\s]/g, " ").replace(/\s+/g, "-").slice(0, 60)}-${Math.abs([...fact.name].reduce((h, c) => ((h << 5) - h) + c.charCodeAt(0) | 0, 0)).toString(16).slice(0, 8)}.md`);
            let preview = fact.content || "";
            try { if (existsSync(pagePath)) preview = readFileSync(pagePath, "utf-8").slice(0, 300); } catch {}
            contextParts.push(`**[${fact.category}] ${fact.name}**\n${preview}`);
          }
        }
      } catch {}
    }

    if (contextParts.length === 0) return {};

    return {
      prependSystemContext: [
        "## CAM Knowledge Recall",
        `Learned knowledge (${totalPages} pages) + CAM Schema rules:`,
        "",
        ...contextParts,
        "",
      ].join("\n"),
    };
  };
}

// ============================================================
// Plugin Registration
// ============================================================

const camPlugin = {
  id: "cam",
  version: "11.0.0",

  configSchema: {
    parse(value: unknown) {
      const raw = value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
      return resolveConfig(raw);
    },
  },

  register(api: OpenClawPluginApi): void {
    const config = resolveConfig(api.config || {});
    const engine = new CamContextEngine(config);
    const store = engine.getStore();

    // ── Hook 1: message_received → cache user message (fires early for all channels) ──
    api.on("message_received", (event: any) => {
      if (typeof event.content === "string" && event.content.trim().length > 5) {
        setPendingUserMsg(event.content);
        console.log(`[cam-hook] message_received: "${event.content.slice(0, 80)}..."`);
      }
    });

    // ── Hook 2: before_prompt_build → recall wiki knowledge ──
    api.on("before_prompt_build", handleBeforePromptBuild(config, engine, store));

    // ── Hook 3: llm_output → extract knowledge from agent response ──
    api.on("llm_output", (event: any, ctx: any) => {
      const userMsg = getPendingUserMsg();

      // Get agent response text from assistantTexts
      let agentText = "";
      if (event.assistantTexts && Array.isArray(event.assistantTexts)) {
        agentText = event.assistantTexts.filter((t: string) => typeof t === "string").join("\n");
      }

      if (!agentText || agentText.length < 50) return;

      const agentId = ctx?.agentId || engine.getAgentId() || "unknown";

      console.log(`[cam-extract] llm_output: agent response ${agentText.length} chars, model=${event.model || "?"}, agent=${agentId}`);
      console.log(`[cam-extract] user message: "${userMsg.slice(0, 100)}${userMsg.length > 100 ? "..." : ""}"`);

      // Store raw conversation
      store.storeRawConversation(
        userMsg || "(unknown)",
        agentText.slice(0, 2000),
        agentId,
        ctx?.sessionId || event.sessionId || "llm-output",
      );

      // Heuristic extraction — skip if user message looks like system metadata
      const looksLikeSystemMsg = userMsg.includes("untrusted metadata") ||
        userMsg.includes("Conversation info") ||
        userMsg.startsWith("Conversation");

      // Also skip if agent response is purely internal execution log (cron, NO_REPLY, etc.)
      const looksLikeCronLog = /cron fired at/i.test(agentText) &&
        /Internal handling complete/i.test(agentText);
      const looksLikeNoReply = agentText.includes("NO_REPLY") &&
        !/原理|机制|架构|技术|principle|mechanism|architecture/i.test(agentText);

      let facts: Array<{ type: "concept" | "entity" | "synthesis"; content: string }> = [];
      if (looksLikeCronLog || looksLikeNoReply) {
        console.log(`[cam-extract] Skipping: response is cron/NO_REPLY log, no substantive knowledge`);
      } else {
        if (!looksLikeSystemMsg && userMsg.length > 5) {
          facts = heuristicExtract(userMsg, agentText);
        } else {
          facts = heuristicExtract("(technical discussion)", agentText);
        }
      }

      for (const fact of facts) {
        const saved = store.storeFact({
          name: fact.content.slice(0, 80),
          category: fact.type,
          content: fact.content,
          tags: ["heuristic", fact.type],
          agentId: "cam-autonomous",
          timestamp: new Date().toISOString(),
          sourceSnippet: `> User: ${userMsg.slice(0, 150)}`,
        });
        if (saved) {
          console.log(`[cam-extract] Stored ${fact.type}: ${fact.content.slice(0, 60)}...`);
        }
      }
      if (facts.length > 0) {
        console.log(`[cam-extract] Extracted ${facts.length} facts from agent response`);
      }

      // Clear after use
      clearPendingUserMsg();
    });

    // ── ContextEngine (registered but not active unless slot = "cam") ──
    api.registerContextEngine("cam", () => engine);

    // ── Tools ──
    api.registerTool(() => createCamQueryTool(store));
    api.registerTool(() => createCamStatsTool(store));

    console.log(`[cam] Plugin v11.0 loaded (Autonomous Knowledge Brain)`);
    console.log(`[cam] wikiPath=${config.wikiPath}`);
    console.log(`[cam] Knowledge extraction via llm_output hook (uses OpenClaw's model)`);
    console.log(`[cam] Tools: cam_query, cam_stats`);
  },
};

export default camPlugin;
