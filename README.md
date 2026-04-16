# 🧠 CAM — Compound Agent Memory

<p align="center">
  通用 AI Agent 记忆引擎 · 自动提取 · 存入 Wiki · 按需召回
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> · <a href="./README.en.md">English</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/canyonqian/cam/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs"></a>
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT">
</p>

---

## 是什么？

CAM 给**任何 AI Agent** 提供持久化长期记忆。

1. Agent 对话 → **CAM 自动提取**知识
2. 知识存入 **Markdown Wiki**（无需数据库）
3. 下次对话 → **CAM 自动召回**相关上下文注入 prompt

> 灵感来自 [Karpathy 的 LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)。越用越聪明。

## 工作原理

```
用户消息 ──→ Agent ──→ 回复
     │                    │
     ├── ContextEngine.ingest() ──→ Daemon HTTP /hook ──→ Wiki/ (自动存储)
     │
     ←── ContextEngine.assemble() ←─ Daemon GET /query ←── Wiki/ (自动召回)
```

**三层架构**（参考 LCM / OpenClaw）：

| 层级 | 机制 | 触发方式 |
|------|------|---------|
| **核心层** | `registerContextEngine("cam")` | 框架自动调用 `ingest()` + `assemble()`，每条消息触发 |
| **工具层** | `cam_query` / `cam_stats` / `cam_ingest` / `cam_extract_file` | Agent 按需调用 |
| **钩子层** | `before_prompt_build` / `llm_output` | 事件驱动（文件检测、prompt 注入） |

## 项目结构

```
cam/
├── cam_daemon/          ⭐ 核心 — FastAPI 守护进程（提取 / 去重 / 存储 / 召回）
│   ├── server.py        POST /hook, GET /query, /stats, /health, /ingest
│   ├── client.py        轻量 Python SDK + AutoRemember 装饰器
│   ├── config.py        LLM 提供商、端口、节流参数
│   └── daemon.py        PID 文件、优雅关闭、生命周期管理
├── plugins/
│   └── openclaw/index.ts  OpenClaw 插件（v4: ContextEngine + Tool + Hook）
├── memory_core/
│   ├── extractor.py      LLM 驱动的知识提取
│   ├── deduplicator.py   基于相似度的去重引擎
│   └── shared_wiki.py    原子化 Markdown 写入 + merge
├── cam/                  CLI（`cam init`, `cam daemon start/stop/status`）
└── wiki/                 输出：结构化 Markdown 页面
    ├── entity/           关于人、项目、决策的事实
    └── synthesis/        综合结论与对比分析
```

## 快速开始

### 1. 安装 & 初始化

```bash
pip install cam
cam init --dir ~/my-wiki          # 创建 wiki/ 目录
```

### 2. 启动 Daemon

```bash
cam daemon start                    # 启动 FastAPI :9877
cam daemon status                   # 查看运行状态
curl http://localhost:9877/health   # {"status":"healthy"}
```

### 3. 接入 OpenClaw（推荐）

安装插件后注册为 **ContextEngine**，每条消息自动捕获和召回：

```bash
openclaw plugin install /path/to/plugins/openclaw
openclaw gateway restart            # 完成！零配置
```

### 4. 或从任何代码接入（3 行）

```python
from cam_daemon.client import CamClient, AutoRemember
client = CamClient()                # 连接 localhost:9877
auto = AutoRemember(agent_id="my-agent")

# 每轮对话结束后：
await auto(user_message, reply)     # 提取事实 → 写入 wiki
results = await client.query("项目架构")  # 召回相关上下文
```

## Agent 可用工具

| 工具 | 功能 |
|------|------|
| `cam_query` | 搜索知识库 |
| `cam_stats` | 查看统计（fact 数量、页面数、健康状态） |
| `cam_ingest` | 手动存入内容 |
| `cam_extract_file` | **文件/图片/文档 → LLM 提取 → Wiki** |

## 配置

通过环境变量或编辑 `wiki/.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CAM_LLM_PROVIDER` | `openai` | 用于提取的 LLM 提供商 |
| `CAM_LLM_MODEL` | `gpt-4o-mini` | 提取用的模型 |
| `CAM_DAEMON_PORT` | `9877` | Daemon 监听端口 |
| `OPENAI_API_KEY` | *(空)* | LLM 提取所需（或配置你自己的 key）|
| `CAM_PROJECT_DIR` | `./wiki` | Wiki 输出目录 |

**没有 API Key？** CAM 会退回到启发式提取模式（模式匹配，不需要 LLM）。

## FAQ

**Q: 需要数据库吗？**
不需要。纯 Markdown 文件——人类可读、git 友好、配合 Obsidian 使用体验极佳。

**Q: 能离线使用吗？**
能。配合本地模型（Ollama/Qwen），设 `CAM_LLM_BASE_URL=http://localhost:11434` 即可。

**Q: 和 RAG 有什么区别？**
RAG = 切原始文档 → 每次重新检索 → 重新合成（用完即弃）。
CAM = 提取一次 → 结构化为 Wiki → 持续迭代永久保存（复利增长）。
两者互补：CAM 管核心知识体系，RAG 管海量临时参考文档。

**Q: AI 产生幻觉怎么办？**
四道防线：①原始资料可溯源 ②定期 LINT 审计 ③增量导入便于校验 ④不确定内容明确标记。

---

MIT © 2026 CAM Contributors · [Issues](https://github.com/canyonqian/cam/issues) · [PRs Welcome](https://github.com/canyonqian/cam/pulls)
