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
  if (agentResponse.trim().length < 50) return facts;

  // 1. Extract code-heavy sections as technical knowledge
  const codeBlocks = agentResponse.match(/```(\w+)?\n([\s\S]*?)```/g);
  if (codeBlocks && codeBlocks.length > 0) {
    const techNames = agentResponse.match(/\b(SQLite|Docker|PostgreSQL|Redis|MongoDB|MySQL|GraphQL|REST|gRPC|WebSocket|Nginx|Kafka|RabbitMQ|React|Vue|Angular|Next\.?js|Nuxt|Django|Flask|FastAPI|Express|Spring|TensorFlow|PyTorch|Ollama|Kubernetes|Terraform|Ansible|Git)\b/g);
    for (const tech of [...new Set(techNames || [])]) {
      facts.push({
        type: "concept",
        content: `${tech}: ${userMessage}`,
      });
    }
  }

  // 2. Extract explanations (contains "因为", "原理", "机制", "作用是", "通过")
  const explanationPatterns = [
    /(?:原理|机制|作用是|工作原理|运行方式|如何实现|底层)/,
    /(?:because|principle|mechanism|works by|through|under the hood)/,
  ];
  if (explanationPatterns.some((p) => p.test(agentResponse))) {
    const sentences = agentResponse.split(/[。.!！]/);
    for (const s of sentences) {
      const trimmed = s.trim();
      if (trimmed.length > 20 && trimmed.length < 300) {
        facts.push({ type: "concept", content: trimmed });
        break;
      }
    }
  }

  // 3. Extract comparisons (contains "vs", "对比", "区别")
  const comparisonPatterns = [
    /(?:vs\.?|对比|区别|相比|不同于|与...不同)/,
  ];
  if (comparisonPatterns.some((p) => p.test(agentResponse))) {
    facts.push({
      type: "synthesis",
      content: `Comparison: ${userMessage}`,
    });
  }

  // 4. Extract problem-solving steps
  const solutionPatterns = [
    /(?:解决方案|解决方法|修复方法|步骤[一二三四1234]|第一步|首先|然后|最后)/,
    /(?:to fix|solution|step 1|first|then|finally|workaround)/,
  ];
  if (solutionPatterns.some((p) => p.test(agentResponse))) {
    facts.push({
      type: "synthesis",
      content: `Solution: ${agentResponse.slice(0, 300)}`,
    });
  }

  // 5. Extract entity mentions (specific tools, projects, services)
  const entityPatterns = [
    /\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b/g,
  ];
  // Only extract entities from technical context
  if (agentResponse.length > 100 && codeBlocks) {
    const mentions = agentResponse.match(/\b([A-Z][a-zA-Z]{2,})\b/g);
    if (mentions) {
      const filtered = mentions.filter((m) => !["The", "This", "That", "These", "Those", "There", "What", "When", "Where", "Which", "While", "With", "Without", "Would", "Could", "Should"].includes(m));
      for (const m of [...new Set(filtered)].slice(0, 3)) {
        facts.push({
          type: "entity",
          content: `${m}: mentioned in technical discussion`,
        });
      }
    }
  }

  // Dedup
  const seen = new Set<string>();
  return facts.filter((f) => {
    if (seen.has(f.content)) return false;
    seen.add(f.content);
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
// Hook — just recall, no instructions
// ============================================================

function handleBeforePromptBuild(
  config: ReturnType<typeof resolveConfig>,
  engine: CamContextEngine,
): (event: any, ctx: any) => Promise<{ prependSystemContext?: string; prependContext?: string }> {
  return async (event, ctx) => {
    if (!config.injectOnPrompt) return {};
    try {
      const store = engine.getStore();
      const stats = store.getStats();
      const totalPages = stats.totalPages as number;
      if (totalPages === 0) return {};

      const parts: string[] = [];
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
            parts.push(`**[${fact.category}] ${fact.name}**\n${preview}`);
          }
        }
      } catch {}

      if (parts.length === 0) return {};
      return {
        prependSystemContext: [
          "## CAM Knowledge Recall",
          `Learned knowledge (${totalPages} pages):`,
          "",
          ...parts,
          "",
        ].join("\n"),
      };
    } catch (e) {
      return {};
    }
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

    // ── Hook 1: cache user message ──
    api.on("message_received", (event: any) => {
      if (typeof event.content === "string" && event.content.trim().length > 5) {
        engine.pendingUserMsg = event.content;
      }
    });

    // ── Hook 2: extract knowledge from agent's LLM response ──
    api.on("llm_output", (event: any) => {
      const userMsg = engine.pendingUserMsg || "";

      // Get agent response text from assistantTexts
      let agentText = "";
      if (event.assistantTexts && Array.isArray(event.assistantTexts)) {
        agentText = event.assistantTexts.filter((t: string) => typeof t === "string").join("\n");
      }

      if (!agentText || agentText.length < 50) return;

      console.log(`[cam-extract] llm_output: agent response ${agentText.length} chars, model=${event.model || "?"}`);

      // Store raw conversation
      engine.storeRawConversation(
        userMsg || "(unknown)",
        agentText.slice(0, 2000),
        engine.getAgentId(),
        event.sessionId || "llm-output",
      );

      // Heuristic extraction
      const facts = heuristicExtract(userMsg, agentText);
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

      engine.pendingUserMsg = "";
    });

    // ── Hook 3: recall wiki knowledge before prompt build ──
    api.on("before_prompt_build", handleBeforePromptBuild(config, engine));

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
