/**
 * CAM — OpenClaw Plugin v5 (Agent-Native Extraction)
 *
 * 核心架构转变：不再由 daemon 调 LLM 提取知识，
 * 而是让 Agent 用自带的 LLM 提取知识，通过 tool 回传给 daemon 存储。
 *
 * 原因：Agent 本身就有强大的 LLM（Claude/GPT），无需额外配置 API key。
 * LCM 也不在 ingest 中调 LLM——它只存原始消息，压缩时才调。
 *
 * 三层机制：
 *   1️⃣ ContextEngine (框架自动调用，不受 activateGlobalSideEffects 限制)
 *      - ingest()    → 存原始对话到 daemon（不调 LLM）
 *      - assemble()  → 召回相关记忆注入 prompt（不调 LLM）
 *
 *   2️⃣ Tool (Agent 主动调用 — 核心！Agent 用自身 LLM 提取后回传)
 *      - cam_extract      → Agent 提取的知识存入 wiki（最核心！）
 *      - cam_query        → 查询知识库
 *      - cam_stats        → 统计面板
 *      - cam_extract_file → 文件/图片/文档提取 → 存入 wiki
 *
 *   3️⃣ Hook (补充 — 注入提取指令)
 *      - before_prompt_build → 注入记忆召回 + 提取指令（告诉 Agent 何时该用 cam_extract）
 *      - message_received    → 缓存用户消息
 *      - llm_output          → 检测文件讨论 → 自动补充存储
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";
import type {
  ContextEngine,
  AssembleResult,
  IngestResult,
} from "openclaw/plugin-sdk";

// ============================================================
// 配置
// ============================================================

const DAEMON_URL = process.env.CAM_DAEMON_URL || "http://127.0.0.1:9877";
const DAEMON_TIMEOUT_MS = 10000;

function resolveConfig(cfg: Record<string, unknown>) {
  return {
    wikiPath: ((cfg.wikiPath as string) || process.env.CAM_PROJECT_DIR || process.cwd()).replace(/\/+$/, ""),
    injectOnPrompt: cfg.injectOnPrompt !== false,
    extractOnOutput: cfg.extractOnOutput !== false,
    daemonUrl: (cfg.daemonUrl as string) || DAEMON_URL,
  };
}

// ============================================================
// Daemon HTTP Client
// ============================================================

interface DaemonResponse {
  success?: boolean;
  status: string;
  facts_extracted?: number;
  facts_written?: number;
  results_found?: number;
  matches?: Array<{
    page: string;
    name: string;
    preview: string;
    content_snippet: string;
  }>;
  question?: string;
  error?: string;
  processing_time_ms?: number;
  throttled?: boolean;
  message?: string;
  [key: string]: unknown;
}

async function daemonPost(
  endpoint: string,
  body: Record<string, unknown>,
  baseUrl?: string,
): Promise<DaemonResponse | null> {
  const url = `${baseUrl || DAEMON_URL}${endpoint}`;
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), DAEMON_TIMEOUT_MS);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) {
      console.log(`[cam] ${endpoint}: daemon returned ${res.status}`);
      return null;
    }
    return (await res.json()) as DaemonResponse;
  } catch (_) {
    return null;
  }
}

async function daemonGet(endpoint: string, params: Record<string, string> = {}): Promise<DaemonResponse | null> {
  const url = new URL(`${DAEMON_URL}${endpoint}`);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), DAEMON_TIMEOUT_MS);
    const res = await fetch(url.toString(), { signal: controller.signal });
    clearTimeout(timer);
    if (!res.ok) return null;
    return (await res.json()) as DaemonResponse;
  } catch (_) {
    return null;
  }
}

// ============================================================
// ContextEngine 实现 — 存储层（框架自动调用，不调 LLM）
// ============================================================

class CamContextEngine implements ContextEngine {
  private config: ReturnType<typeof resolveConfig>;
  private lastQueryResult: string | null = null;

  constructor(cfg: ReturnType<typeof resolveConfig>) {
    this.config = cfg;
  }

  /**
   * ingest(): 框架在每条消息到达时自动调用
   * 只存原始对话，不做 LLM 提取（跟 LCM 一样）
   * 知识提取由 Agent 通过 cam_extract tool 主动完成
   */
  async ingest(params: {
    sessionId: string;
    sessionKey?: string;
    message: any;
  }): Promise<IngestResult> {
    try {
      const content = this.extractTextContent(params.message);
      if (!content || content.length < 5) return { ingested: false };

      const role = params.message?.role || "unknown";

      // 只存原始对话，不调 LLM
      const result = await daemonPost("/hook", {
        user_message: role === "user" ? content : "",
        ai_response: role === "assistant" ? content : "",
        conversation: [{ role, content }],
        agent_id: "openclaw",
        session_id: params.sessionKey || params.sessionId || "",
      }, this.config.daemonUrl);

      if (result?.facts_written && result.facts_written > 0) {
        console.log(`[cam-ingest] stored ${role} message (${content.length} chars)`);
      }

      return { ingested: !!result };
    } catch (e) {
      console.log("[cam-ingest] error:", (e as Error).message);
      return { ingested: false };
    }
  }

  /**
   * assemble(): 框架在构建 prompt 时自动调用 — 召回相关记忆
   * 不调 LLM，只做 wiki 查询
   */
  async assemble(params: {
    sessionId: string;
    sessionKey?: string;
    messages: any[];
    prompt?: string;
    tokenBudget?: number;
  }): Promise<AssembleResult> {
    try {
      const query = params.prompt || "";
      if (!query || query.length < 3 || !this.config.injectOnPrompt) {
        return { messages: [], estimatedTokens: 0 };
      }

      const result = await daemonGet("/query", { q: query, top_k: "5" });
      if (!result || !result.matches || result.matches.length === 0) {
        return { messages: [], estimatedTokens: 0 };
      }

      this.lastQueryResult = this.formatMatches(result.matches);
      const contextBlock = this.formatMatchesForPrompt(result.matches, query);

      return {
        messages: [],
        estimatedTokens: Math.ceil(contextBlock.length / 4),
        systemPromptAddition: contextBlock,
      };
    } catch (e) {
      console.log("[cam-assemble] error:", (e as Error).message);
      return { messages: [], estimatedTokens: 0 };
    }
  }

  async compact(): Promise<any> {
    return { ok: true, compacted: false, reason: "CAM does not manage compaction" };
  }

  private extractTextContent(message: any): string {
    if (!message) return "";
    if (typeof message.content === "string") return message.content;
    if (Array.isArray(message.content)) {
      return message.content
        .filter((p: any) => p.type === "text")
        .map((p: any) => p.text || "")
        .join("\n");
    }
    return String(message.content || "");
  }

  private formatMatches(matches: DaemonResponse["matches"]): string {
    if (!matches) return "";
    return matches!.map(m => `- **[${m.name}]** (${m.page}): ${m.preview || m.content_snippet?.slice(0, 150)}`).join("\n");
  }

  private formatMatchesForPrompt(matches: DaemonResponse["matches"], query: string): string {
    const parts: string[] = [
      "",
      "---",
      "<cam-memory>",
      `<!-- CAM memory recall for: "${query.slice(0, 80)}" -->`,
    ];
    for (const m of matches!.slice(0, 5)) {
      const preview = m.preview || m.content_snippet?.slice(0, 200) || "";
      parts.push(`**${m.name}**: ${preview}`);
    }
    parts.push("</cam-memory>", "");
    return parts.join("\n");
  }

  getLastRecall(): string | null {
    return this.lastQueryResult;
  }
}

// ============================================================
// Tool 定义 — Agent 主动调用（核心！）
// ============================================================

/** Helper: format tool output */
function jsonToolResult(data: Record<string, unknown>) {
  return {
    content: data.content
      ? [{ type: "text" as const, text: String(data.content) }]
      : [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
    details: data,
  };
}

/**
 * cam_extract: 最核心的 tool！
 *
 * Agent 用自身 LLM 分析对话后，把提取到的知识通过此 tool 存入 wiki。
 * 这样 daemon 就走 Agent-Native 模式——直接存储，不需要额外 LLM。
 *
 * Agent 应该在以下情况调用此 tool：
 * - 用户表达了明确的偏好或决策
 * - 讨论中产生了重要的技术选型或架构决定
 * - 用户纠正了之前的错误信息
 * - 获取了值得跨会话记住的事实知识
 */
function createCamExtractTool(daemonUrl: string) {
  return {
    name: "cam_extract",
    label: "CAM Extract",
    description:
      "Store extracted knowledge into the CAM Wiki knowledge base. " +
      "Use this tool when you identify important information in the conversation that should be remembered " +
      "across sessions — such as user preferences, decisions, technical choices, corrections, " +
      "architecture decisions, or any factual knowledge worth preserving. " +
      "YOU (the Agent) do the extraction using your own LLM capabilities, then pass the structured facts here.",
    parameters: {
      type: "object" as const,
      properties: {
        facts: {
          type: "array",
          description: "Array of facts to store. Each fact should have content and optionally a type.",
          items: {
            type: "object",
            properties: {
              content: {
                type: "string",
                description: "The fact/knowledge to store (clear, concise, self-contained)",
              },
              fact_type: {
                type: "string",
                description: "Type: 'entity' (person/project/tool), 'concept' (idea/pattern), 'synthesis' (decision/summary), or 'fact' (general)",
                enum: ["entity", "concept", "synthesis", "fact"],
              },
              tags: {
                type: "array",
                items: { type: "string" },
                description: "Tags for categorization",
              },
            },
            required: ["content"],
          },
        },
        context: {
          type: "string",
          description: "Brief context about what was being discussed when these facts were extracted",
        },
      },
      required: ["facts"],
    },
    async execute(_toolCallId: string, params: Record<string, unknown>) {
      const facts = params.facts as Array<Record<string, unknown>>;
      if (!facts || !Array.isArray(facts) || facts.length === 0) {
        return jsonToolResult({ error: "facts array is required and must not be empty" });
      }

      const context = String(params.context || "");

      // 发送给 daemon，走 Agent-Native 模式（extracted_facts 已提供）
      const result = await daemonPost("/hook", {
        user_message: context || "Agent extracted knowledge",
        ai_response: "",
        agent_id: "openclaw-agent",
        session_id: process.env.OPENCLAW_SESSION_ID || "",
        extracted_facts: facts,  // ← 这是关键！daemon 会走 Agent-Native 模式直接存储
      }, daemonUrl);

      if (!result) {
        return jsonToolResult({
          content: `[CAM] ${facts.length} fact(s) queued (daemon offline)`,
          queued: true,
        });
      }

      return jsonToolResult({
        content: [
          `## CAM Knowledge Stored`,
          `**Facts:** ${facts.length} submitted, ${result.facts_written || 0} written`,
          `**Status:** ${result.status}`,
          result.throttled ? `*(Throttled: ${result.message})*` : "",
        ].filter(Boolean).join("\n"),
        factsSubmitted: facts.length,
        factsWritten: result.facts_written || 0,
      });
    },
  };
}

/** cam_query: 搜索 Wiki 知识库 */
function createCamQueryTool(daemonUrl: string) {
  return {
    name: "cam_query",
    label: "CAM Query",
    description:
      "Search the CAM knowledge base (Wiki) for relevant facts, decisions, preferences, or knowledge. " +
      "Use this when you need to recall something from past conversations.",
    parameters: {
      type: "object" as const,
      properties: {
        query: {
          type: "string",
          description: "Search query for the knowledge base",
        },
        top_k: {
          type: "number",
          description: "Number of results to return (default: 5)",
          minimum: 1,
          maximum: 20,
        },
      },
      required: ["query"],
    },
    async execute(_toolCallId: string, params: Record<string, unknown>) {
      const q = String(params.query || "").trim();
      if (!q) return jsonToolResult({ error: "query is required" });
      const k = typeof params.top_k === "number" ? params.top_k : 5;

      const result = await daemonGet("/query", { q, top_k: String(k) });
      if (!result) return jsonToolResult({ error: "CAM daemon is offline" });

      const lines: string[] = [
        "## CAM Knowledge Base Results",
        `**Query:** \`${q}\``,
        `**Found:** ${result.results_found || result.matches?.length || 0} match(es)`,
        "",
      ];

      if (result.matches?.length) {
        for (const m of result.matches) {
          lines.push(`### ${m.name}`);
          lines.push(`**Page:** ${m.page}`);
          lines.push(m.content_snippet || m.preview || "(no preview)");
          lines.push("");
        }
      } else {
        lines.push("No matching facts found.");
      }

      return jsonToolResult({ content: lines.join("\n"), count: result.matches?.length || 0 });
    },
  };
}

/** cam_stats: 获取统计面板 */
function createCamStatsTool() {
  return {
    name: "cam_stats",
    label: "CAM Stats",
    description: "Get CAM memory engine statistics.",
    parameters: {
      type: "object" as const,
      properties: {},
    },
    async execute() {
      const result = await daemonGet("/stats");
      if (!result) return jsonToolResult({ error: "CAM daemon is offline" });
      return jsonToolResult({
        content: [
          "## CAM Memory Stats",
          `**Status:** ${result.status || "unknown"}`,
          `**Facts:** ${(result as any).total_facts || 0}`,
          `**Pages:** ${(result as any).total_pages || 0}`,
        ].join("\n"),
        raw: result,
      });
    },
  };
}

/**
 * cam_extract_file: 文件/图片/文档 → Agent LLM 提取 → 存入 wiki
 *
 * Agent 读取文件后，用自身 LLM 分析，然后调用此 tool 存储
 */
function createCamExtractFileTool(daemonUrl: string) {
  return {
    name: "cam_extract_file",
    label: "CAM Extract File",
    description:
      "Extract key information from a file, image, or document that you have already read/analyzed, " +
      "then store the extracted knowledge into the CAM Wiki. " +
      "Use this when the user shares a project file, image, or document containing " +
      "valuable information worth remembering (design decisions, requirements, architecture, preferences, specs). " +
      "YOU analyze the file with your LLM, then pass the extracted facts here.",
    parameters: {
      type: "object" as const,
      properties: {
        file_path: {
          type: "string",
          description: "Path of the file that was analyzed",
        },
        facts: {
          type: "array",
          description: "Extracted facts from the file",
          items: {
            type: "object",
            properties: {
              content: {
                type: "string",
                description: "The extracted fact/knowledge",
              },
              fact_type: {
                type: "string",
                description: "Type: 'entity', 'concept', 'synthesis', or 'fact'",
                enum: ["entity", "concept", "synthesis", "fact"],
              },
              tags: {
                type: "array",
                items: { type: "string" },
                description: "Tags for categorization",
              },
            },
            required: ["content"],
          },
        },
        summary: {
          type: "string",
          description: "Brief summary of what the file contains and why it matters",
        },
      },
      required: ["file_path", "facts"],
    },
    async execute(_toolCallId: string, params: Record<string, unknown>) {
      const filePath = String(params.file_path || "").trim();
      const facts = params.facts as Array<Record<string, unknown>>;
      const summary = String(params.summary || "");

      if (!filePath) return jsonToolResult({ error: "file_path is required" });
      if (!facts || !Array.isArray(facts) || facts.length === 0) {
        return jsonToolResult({ error: "facts array is required and must not be empty" });
      }

      // 走 Agent-Native 模式
      const result = await daemonPost("/hook", {
        user_message: `File: ${filePath}${summary ? `\nSummary: ${summary}` : ""}`,
        ai_response: "",
        agent_id: "openclaw-file-extract",
        session_id: "file-extraction",
        extracted_facts: facts,
        metadata: {
          source_type: "file_extraction",
          file_path: filePath,
        },
      }, daemonUrl);

      if (!result) {
        return jsonToolResult({
          content: `[CAM] ${facts.length} fact(s) from ${filePath} queued (daemon offline)`,
          queued: true,
        });
      }

      return jsonToolResult({
        content: [
          `## CAM File Extraction: ${filePath}`,
          `**Facts:** ${facts.length} submitted, ${result.facts_written || 0} written`,
          `**Status:** ${result.status}`,
        ].join("\n"),
        factsSubmitted: facts.length,
        factsWritten: result.facts_written || 0,
      });
    },
  };
}

// ============================================================
// Hook 处理器 — 补充层
// ============================================================

let _cachedUserMsg = "";
let _cachedUserTs = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * before_prompt_build: 注入提取指令 + 文件处理提示
 *
 * 这是让 Agent "知道"它应该用 cam_extract 的关键！
 * 告诉 Agent：你在对话中识别到重要知识时，应该主动调用 cam_extract
 */
export function handleBeforePromptBuild(
  ctx: any & { config?: Record<string, unknown> },
): { prependSystemContext?: string } {
  const config = ctx.config ? resolveConfig(ctx.config) : resolveConfig({});
  if (!config.injectOnPrompt) return {};

  return {
    prependSystemContext: [
      "",
      "<cam-instructions>",
      "CAM (Compound Agent Memory) is active. You have access to long-term knowledge storage:",
      "",
      "## When to use cam_extract:",
      "- The user expresses a clear **preference** (e.g., 'I prefer...', 'Always use...')",
      "- A **decision** is made (e.g., 'We'll use React', 'Switched to PostgreSQL')",
      "- The user **corrects** previous information",
      "- Important **technical choices** or **architecture decisions** are discussed",
      "- The user shares **personal context** they'd want remembered (name, role, project details)",
      "- Any **factual knowledge** worth preserving across conversations",
      "",
      "## When to use cam_extract_file:",
      "- The user shares a file, image, or document with important information",
      "- Read it first, extract key facts, then call cam_extract_file to store them",
      "",
      "## When to use cam_query:",
      "- You need to recall something from past conversations",
      "- The user asks about previous decisions, preferences, or context",
      "",
      "IMPORTANT: Do NOT call cam_extract for every message — only when genuinely valuable knowledge is identified.",
      "</cam-instructions>",
      "",
    ].join("\n"),
  };
}

/** message_received: 缓存用户消息 */
export function handleMessageReceived(ctx: any): void {
  const msg =
    ctx.userMessage ||
    ctx.bodyForAgent ||
    ctx.event?.content ||
    (ctx.event && typeof ctx.event === "object" && "content" in ctx.event ? ctx.event.content : "") ||
    "";
  if (msg && typeof msg === "string" && msg.length > 10) {
    _cachedUserMsg = msg;
    _cachedUserTs = Date.now();
  }
}

/** llm_output: 检测文件讨论 → 提醒 Agent 使用 cam_extract_file */
export async function handleLlmOutput(
  ctx: any & { config?: Record<string, unknown>; aiResponse?: string },
): Promise<void> {
  // v5 中不再自动存储——由 Agent 主动通过 tool 完成
  // 这里只做日志记录
  try {
    const config = ctx.config ? resolveConfig(ctx.config) : resolveConfig({});
    if (!config.extractOnOutput) return;

    const aiResponse = ctx.aiResponse || ctx.lastAssistant || "";
    if (!aiResponse || aiResponse.length < 20) return;

    // 检测是否涉及文件，只打日志
    const fileIndicators = /\.(ts|js|py|json|yaml|yml|md|txt|pdf|png|jpg|jpeg)[`'\"\s]/i;
    if (fileIndicators.test(aiResponse)) {
      console.log("[cam-output] File discussion detected — Agent should use cam_extract_file");
    }
  } catch (_) {}
}

function getCachedUserMsg(): string {
  if (!_cachedUserMsg || Date.now() - _cachedUserTs > CACHE_TTL_MS) return "";
  return _cachedUserMsg;
}

// ============================================================
// 插件注册入口
// ============================================================

const camPlugin = {
  id: "cam",
  version: "5.0.0",

  resolveConfig(env: Record<string, string>, value: Record<string, unknown>): Record<string, unknown> {
    const raw = value && typeof value === "object" && !Array.isArray(value) ? value : {};
    return {
      ...raw,
      daemonUrl: (raw.daemonUrl as string) || env.CAM_DAEMON_URL || DAEMON_URL,
    };
  },

  register(api: OpenClawPluginApi): void {
    const config = resolveConfig(api.config);
    const engine = new CamContextEngine(config);

    // ── Layer 1: ContextEngine (框架自动调用，不调 LLM) ──
    api.registerContextEngine("cam", () => engine);

    // ── Layer 2: Tools (Agent 主动调用 — 知识提取核心) ──
    api.registerTool(() => createCamExtractTool(config.daemonUrl));     // 最核心！
    api.registerTool(() => createCamQueryTool(config.daemonUrl));
    api.registerTool(() => createCamStatsTool());
    api.registerTool(() => createCamExtractFileTool(config.daemonUrl));

    // ── Layer 3: Hooks (补充 — 注入提取指令) ──
    api.on("before_prompt_build", () =>
      handleBeforePromptBuild(config as any),
    );
    api.on("message_received", (event: any) => {
      handleMessageReceived(event);
    });
    api.on("llm_output", (event: any) => {
      handleLlmOutput(event);
    });

    console.log(`[cam] Plugin v5 loaded (Agent-Native Extraction)`);
    console.log(`[cam] daemon=${config.daemonUrl}`);
    console.log(`[cam] Agent extracts knowledge → cam_extract stores it (no external LLM needed)`);
  },
};

export default camPlugin;
