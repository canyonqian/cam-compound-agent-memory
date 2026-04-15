/**
 * Compound Wiki — OpenClaw Plugin v3 (Daemon Mode)
 *
 * v3 改动：不再自己调用 Python 子进程做提取/写入，
 * 而是把对话数据发给 cw-daemon HTTP API，让 daemon 统一处理。
 *
 * Hook 点：
 *   before_prompt_build → 查询 daemon 的 /query → 注入上下文
 *   message_received    → 缓存用户消息（给 llm_output 用）
 *   llm_output          → POST /hook 发给 daemon 自动提取
 *
 * 优势：
 *   - 插件从 ~270 行 → ~80 行
 *   - 不再依赖 Python 子进程调用
 *   - 去重/节流/写入全部由 daemon 处理，不会重复
 *   - 和 Hermes / Claude Code 共享同一套逻辑
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

// ============================================================
// 配置
// ============================================================

const DAEMON_URL = process.env.CW_DAEMON_URL || "http://127.0.0.1:9877";
const DAEMON_TIMEOUT_MS = 8000; // 8s timeout for daemon calls

function resolveConfig(cfg: Record<string, unknown>): {
  wikiPath: string;
  injectOnPrompt: boolean;
  extractOnOutput: boolean;
  daemonUrl: string;
} {
  return {
    wikiPath: ((cfg.wikiPath as string) || process.env.CW_PROJECT_DIR || process.cwd()).replace(/\/+$/, ""),
    injectOnPrompt: cfg.injectOnPrompt !== false,
    extractOnOutput: cfg.extractOnOutput !== false,
    daemonUrl: (cfg.daemonUrl as string) || DAEMON_URL,
  };
}

// ============================================================
// 用户消息缓存（供 llm_output 组装完整对话）
// ============================================================

let _cachedUserMsg = "";
let _cachedUserTs = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;

function getCachedUserMsg(): string {
  if (!_cachedUserMsg || Date.now() - _cachedUserTs > CACHE_TTL_MS) return "";
  return _cachedUserMsg;
}

function setCachedUserMsg(msg: string): void {
  if (msg && msg.length > 10) { // Skip very short messages
    _cachedUserMsg = msg;
    _cachedUserTs = Date.now();
  }
}

function clearCachedUserMsg(): string {
  const prev = _cachedUserMsg;
  _cachedUserMsg = "";
  _cachedUserTs = 0;
  return prev;
}

// ============================================================
// Daemon HTTP Client (pure HTTP, no Python subprocess)
// ============================================================

interface DaemonResponse {
  success?: boolean;
  status: string;
  facts_extracted?: number;
  facts_written?: number;
  message?: string;
  processing_time_ms?: number;
  throttled?: boolean;
  results_found?: number;
  matches?: Array<{
    page: string;
    name: string;
    preview: string;
    content_snippet: string;
  }>;
  question?: string;
  error?: string;
  [key: string]: unknown;
}

async function daemonPost(path: string, body: Record<string, unknown>, url: string): Promise<DaemonResponse | null> {
  try {
    const resp = await fetch(`${url}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(DAEMON_TIMEOUT_MS),
    });
    
    if (!resp.ok) {
      console.warn(`[compound-wiki] daemon ${path} returned ${resp.status}`);
      return null;
    }
    
    return await resp.json() as DaemonResponse;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(`[compound-wiki] daemon ${path} unreachable: ${msg}`);
    return null; // Graceful degradation — daemon offline is not an error
  }
}

async function daemonGet(path: string, params: Record<string, string>, url: string): Promise<DaemonResponse | null> {
  try {
    const qs = new URLSearchParams(params).toString();
    const resp = await fetch(`${url}${path}?${qs}`, {
      signal: AbortSignal.timeout(DAEMON_TIMEOUT_MS),
    });
    
    if (!resp.ok) return null;
    return await resp.json() as DaemonResponse;
  } catch (err) {
    return null; // Graceful degradation
  }
}

// ============================================================
// Hook 实现 — 全部委托给 daemon
// ============================================================

/** 从 daemon 查询相关记忆并注入到 system prompt */
export async function before_prompt_build(
  ctx: OpenClawPluginApi & { userMessage?: string },
): Promise<void> {
  try {
    if (!ctx.userMessage) return;

    const config = resolveConfig(ctx.config);
    if (!config.injectOnPrompt) return;

    const result = await daemonGet("/query", {
      q: ctx.userMessage.slice(0, 200),
      top_k: "5",
    }, config.daemonUrl);

    if (!result || !result.matches?.length) return;

    // Build context block from matches
    const contextLines: string[] = [
      `## 📚 Compound Wiki Memory`,
      "",
      `_The following knowledge was retrieved from your persistent memory:_`,
      "",
    ];

    for (const m of result.matches) {
      contextLines.push(`### ${m.name.replace(/-/g, " ")}`);
      contextLines.push("");
      contextLines.push(m.content_snippet);
      contextLines.push("");
    }

    contextLines.push("---");

    const contextBlock = contextLines.join("\n");

    if (typeof ctx.prependSystemContext === "function") {
      ctx.prependSystemContext(contextBlock);
    }

    console.log(
      `[compound-wiki] Injected ${result.matches.length} pages from daemon`,
    );
  } catch (_) {}
}

/** 缓存用户消息 */
export async function message_received(
  ctx: OpenClawPluginApi & { userMessage?: string },
): Promise<void> {
  setCachedUserMsg(ctx.userMessage || "");
}

/**
 * 核心Hook：把完整对话发给 daemon，daemon 自动完成：
 *   提取 → 去重 → 写入 → 更新索引
 *
 * 这一行替代了原来整个 llm_output 函数的复杂逻辑。
 */
export async function llm_output(
  ctx: OpenClawPluginApi & { aiResponse?: string },
): Promise<void> {
  try {
    const config = resolveConfig(ctx.config);
    if (!config.extractOnOutput) return;

    const aiResponse = ctx.aiResponse;
    if (!aiResponse || aiResponse.length < 20) return;

    const userMsg = clearCachedUserMsg();

    // POST to daemon — it handles everything:
    // throttle, extract, dedup, write, index update
    const result = await daemonPost("/hook", {
      user_message: userMsg || "",
      ai_response: aiResponse,
      agent_id: "openclaw",
      session_id: process.env.OPENCLAW_SESSION_ID || "",
    }, config.daemonUrl);

    if (!result) {
      // Daemon is offline — silently skip (not an error)
      return;
    }

    if (result.throttled) {
      console.log(`[compound-wiki] throttled by daemon: ${result.message}`);
      return;
    }

    if (result.facts_written && result.facts_written > 0) {
      console.log(
        `[compound-wiki] 🧠 ${result.facts_written} new fact(s) stored via daemon (${result.processing_time_ms}ms)`,
      );
    } else if (result.status === "ok") {
      console.log(`[compound-wiki] processed: ${result.message}`);
    }
  } catch (_) {}
}

// ============================================================
// 注册
// ============================================================

export async function register(api: OpenClawPluginApi): Promise<void> {
  const config = resolveConfig(api.config);
  
  console.log(`[compound-wiki] Plugin v3 loaded (daemon mode)`);
  console.log(`[compound-wiki] daemon=${config.daemonUrl}`);

  api.registerHook("before_prompt_build", (ctx: unknown) =>
    before_prompt_build(ctx as Parameters<typeof before_prompt_build>[0]),
  );
  api.registerHook("message_received", (ctx: unknown) =>
    message_received(ctx as Parameters<typeof message_received>[0]),
  );
  api.registerHook("llm_output", (ctx: unknown) =>
    llm_output(ctx as Parameters<typeof llm_output>[0]),
  );
}
