/**
 * Compound Wiki — OpenClaw Plugin v2
 *
 * 替代 memory-guard 的下一代 AI 记忆引擎
 *
 * Hook 点：
 *   before_prompt_build → 查询 Compound Wiki 相关记忆 → prependSystemContext 注入
 *   message_received    → 缓存最近用户消息
 *   llm_output          → 调用 Compound Wiki 提取知识 → 存入 Wiki
 *
 * 架构优势（vs 旧版 memory-guard）：
 *   - 零 API Key：用 Host Agent 自身的 LLM 能力做提取
 *   - 结构化存储：Markdown Wiki + 索引，人类可读
 *   - 规则引擎：内置提取规则 + Agent 自由发挥
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

// ============================================================
// 配置
// ============================================================

const DEFAULT_WIKI_PATH = process.env.CW_PROJECT_DIR || process.cwd();
const CACHE_TTL_MS = 5 * 60 * 1000; // 5分钟

function resolveConfig(cfg: Record<string, unknown>): {
  wikiPath: string;
  injectOnPrompt: boolean;
  extractOnOutput: boolean;
} {
  return {
    wikiPath: ((cfg.wikiPath as string) || DEFAULT_WIKI_PATH).replace(/\/+$/, ""),
    injectOnPrompt: cfg.injectOnPrompt !== false,
    extractOnOutput: cfg.extractOnOutput !== false,
  };
}

// ============================================================
// 用户消息缓存（模块级单例）
// ============================================================

let _cachedUserMsg = "";
let _cachedUserTs = 0;

function getCachedUserMsg(): string {
  if (!_cachedUserMsg || Date.now() - _cachedUserTs > CACHE_TTL_MS) return "";
  return _cachedUserMsg;
}

function setCachedUserMsg(msg: string): void {
  _cachedUserMsg = msg;
  _cachedUserTs = Date.now();
}

function clearCachedUserMsg(): string {
  const prev = _cachedUserMsg;
  _cachedUserMsg = "";
  _cachedUserTs = 0;
  return prev;
}

// ============================================================
// Compound Wiki MCP Client（通过子进程调用）
// ============================================================

interface CwResult {
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}

/**
 * 通过 Python 子进程调用 Compound Wiki MCP 工具
 */
async function callCwTool(
  wikiPath: string,
  toolName: string,
  args: Record<string, unknown>,
): Promise<CwResult> {
  try {
    const { execFileSync } = await import("child_process");

    // 写临时 JSON 文件传递参数（避免命令行参数转义问题）
    const fs = await import("fs");
    const os = await import("os");
    const tmpFile = os.tmpdir() + `/cw_call_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.json`;
    fs.writeFileSync(tmpFile, JSON.stringify({ tool: toolName, args }));

    const result = execFileSync(
      "python3",
      [
        "-c",
        `import json, sys
sys.path.insert(0, "${wikiPath}")
from plugins.mcp_server import call_tool as _call
import asyncio

async def main():
    with open("${tmpFile}") as f:
        req = json.load(f)
    result = await _call(req["tool"], req["args"])
    out = []
    for c in result.content:
        out.append({"type": c.type, "text": c.text})
    print(json.dumps({"content": out, "isError": getattr(result, "isError", False)}))

asyncio.run(main())
`,
      ],
      {
        timeout: 30000,
        env: process.env,
        cwd: wikiPath,
        encoding: "utf-8",
        maxBuffer: 1024 * 1024,
      },
    );

    // 清理临时文件
    try { fs.unlinkSync(tmpFile); } catch (_) {}

    return JSON.parse(result) as CwResult;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[compound-wiki] ${toolName} error: ${msg}`);
    return {
      content: [{ type: "text", text: "" }],
      isError: true,
    };
  }
}

// ============================================================
// Hook 实现
// ============================================================

/** 从 Wiki 中检索相关记忆并注入到 system prompt */
export async function before_prompt_build(
  ctx: OpenClawPluginApi & { userMessage?: string },
): Promise<void> {
  try {
    if (!ctx.userMessage) return;

    const config = resolveConfig(ctx.config);
    if (!config.injectOnPrompt) return;

    // 用用户消息的前 200 字符作为查询关键词
    const query = ctx.userMessage.slice(0, 200);

    const result = await callCwTool(config.wikiPath, "cw_query", {
      query,
      scope: "all",
      max_results: 5,
      format: "context",
    });

    if (result.isError || !result.content?.[0]?.text) return;

    const memoriesText = result.content[0].text.trim();
    if (!memoriesText || memoriesText === "_No matching pages found._") return;

    // 注入到 system prompt 前面
    const contextBlock = [
      `## 📚 Compound Wiki Memory`,
      "",
      `_The following knowledge was retrieved from your persistent memory:_`,
      "",
      memoriesText,
      "",
      "---",
    ].join("\n");

    if (typeof ctx.prependSystemContext === "function") {
      ctx.prependSystemContext(contextBlock);
    }

    console.log(
      `[compound-wiki] Injected ${(memoriesText.match(/\n/g) || []).length} lines of context`,
    );
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[compound-wiki] before_prompt_build error: ${msg}`);
  }
}

/** 缓存用户消息，供 llm_output 提取使用 */
export async function message_received(
  ctx: OpenClawPluginApi & { userMessage?: string },
): Promise<void> {
  try {
    if (ctx.userMessage && ctx.userMessage.length > 10) {
      setCachedUserMsg(ctx.userMessage);
    }
  } catch (_) {}
}

/** 从 AI 回复中自动摄入内容 + 提取知识 */
export async function llm_output(
  ctx: OpenClawPluginApi & { aiResponse?: string },
): Promise<void> {
  try {
    const config = resolveConfig(ctx.config);
    if (!config.extractOnOutput) return;

    const userMsg = clearCachedUserMsg();
    const aiResponse = ctx.aiResponse;
    if (!aiResponse || aiResponse.length < 20) return;

    // Step 1: 先把完整对话存为 raw 记录
    const rawContent = [
      `# Conversation Record — ${new Date().toISOString()}`,
      "",
      `## User`,
      userMsg || "(unknown)",
      "",
      `## Assistant`,
      aiResponse,
    ].join("\n");

    await callCwTool(config.wikiPath, "cw_ingest", {
      content: rawContent,
      source: "openclaw-conversation",
      title: `chat-${Date.now()}`,
    });

    // Step 2: 同时把 AI 回复单独作为知识源摄入
    await callCwTool(config.wikiPath, "cw_ingest", {
      content: aiResponse,
      source: "openclaw-response",
      title: `response-${Date.now()}`,
    });

    console.log(`[compound-wiki] Ingested conversation (${rawContent.length} chars)`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    console.error(`[compound-wiki] llm_output error: ${msg}`);
  }
}

// ============================================================
// 注册函数
// ============================================================

export async function register(api: OpenClawPluginApi): Promise<void> {
  const config = resolveConfig(api.config);
  console.log(`[compound-wiki] Plugin loaded | wiki=${config.wikiPath}`);

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
