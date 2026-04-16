# 🧠 CAM — Compound Agent Memory

<p align="center">
  AI Agent 自主学习知识引擎 · 零额外 LLM 调用 · Markdown Wiki 存储
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> · <a href="./README.en.md">English</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/canyonqian/cam/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs"></a>
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT">
</p>

---

## 是什么？

CAM 给**任何 AI Agent** 提供自主学习知识的能力。

1. 用户发消息 → **CAM 自动拦截**
2. Agent 回答后 → **CAM 自动提取知识**写入 Wiki（零额外 LLM 调用）
3. 下次对话 → **CAM 自动召回**相关上下文注入 prompt

> 灵感来自 [Karpathy 的 LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：LLM 不厌倦重复性工作（bookkeeping），而这正是人类放弃维护 Wiki 的原因。

## 工作原理

```
用户消息 ──→ Agent (回答)
   │             │
   │             ├── llm_output 钩子 → 启发式提取知识 → Wiki/ (自动存储)
   │
   └── message_received 钩子 → 缓存用户消息
```

**零额外 LLM 调用**：CAM 不单独调 LLM 提取知识，而是从 Agent 已有的回答中抓取——Agent 本来就要回答，CAM 只是顺便学习。

## 三层架构

```
                    ┌──────────────────────────────────┐
                    │  Layer 3: Schema (规则)           │
                    │  schema/CLAUDE.md                 │
                    │  知识分类标准 · 页面格式 · 不存什么  │
                    └────────────────┬─────────────────┘
                                     ↑
                    ┌──────────────────────────────────┐
                    │  Layer 2: Wiki (编译后的知识)      │
                    │  concept/  — 技术原理、工作机制     │
                    │  synthesis/— 对比分析、决策建议     │
                    │  entity/   — 具体项目、工具、人     │
                    └────────────────┬─────────────────┘
                                     ↑
                    ┌──────────────────────────────────┐
                    │  Layer 1: Raw (不可变原始源)      │
                    │  raw/ — 每次对话的完整记录         │
                    └──────────────────────────────────┘
```

## 项目结构

```
cam/
├── plugins/
│   └── openclaw/index.ts  ⭐ 核心 — OpenClaw 插件 (v11)
│                            • message_received → 缓存用户消息
│                            • llm_output → 启发式提取知识
│                            • before_prompt_build → Schema + Wiki 召回
├── cam_daemon/            FastAPI 守护进程（可选，Python SDK 接入）
├── memory_core/           LLM 提取 / 去重 / Wiki 写入（Python SDK）
├── cam/                   CLI（`cam init`, `cam daemon start/stop`）
├── schema/                ⭐ Layer 3: 知识组织规则
│   ├── CLAUDE.md          分类标准 + 页面格式 + 不存什么
│   └── templates/         Wiki 页面模板
└── wiki/                  输出：结构化 Markdown 页面
    ├── raw/               原始对话记录（不可变）
    ├── entity/            具体实体（项目、工具、人）
    ├── concept/           技术概念（原理、机制、方法）
    └── synthesis/         综合知识（对比、决策、方案）
```

## 快速开始

### 1. 安装 & 初始化

```bash
pip install cam
cam init --dir ~/my-wiki          # 创建 wiki/ + schema/ 目录
```

### 2. 接入 OpenClaw（推荐）

安装插件，CAM 通过钩子自动学习：

```bash
openclaw plugin install /path/to/plugins/openclaw
openclaw gateway restart            # 完成！零配置
```

### 3. 或从任何代码接入（3 行）

```python
from cam_daemon.client import CamClient, AutoRemember
client = CamClient()                # 连接 localhost:9877
auto = AutoRemember(agent_id="my-agent")

# 每轮对话结束后：
await auto(user_message, reply)     # 提取知识 → 写入 wiki
results = await client.query("项目架构")  # 召回相关上下文
```

## Agent 可用工具

| 工具 | 功能 |
|------|------|
| `cam_query` | 搜索 CAM Wiki 知识库 |
| `cam_stats` | 查看统计（fact 数量、页面数、健康状态） |

## 配置

通过环境变量或编辑 `wiki/.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CAM_PROJECT_DIR` | `./wiki` | Wiki 输出目录 |
| `CAM_DAEMON_PORT` | `9877` | Daemon 监听端口 |

## FAQ

**Q: 需要数据库吗？**
不需要。纯 Markdown 文件——人类可读、git 友好、配合 Obsidian 使用体验极佳。

**Q: 和 RAG 有什么区别？**
RAG = 切原始文档 → 每次重新检索 → 重新合成（用完即弃）。
CAM = 提取一次 → 结构化为 Wiki → 持续迭代永久保存（复利增长）。
两者互补：CAM 管核心知识体系，RAG 管海量临时参考文档。

**Q: 需要额外的 LLM 调用吗？**
不需要。OpenClaw 模式下，CAM 从 Agent 已有的回答中提取知识，零额外调用。

**Q: AI 产生幻觉怎么办？**
四道防线：①原始资料可溯源（raw/ 目录） ②定期 LINT 审计 ③增量导入便于校验 ④不确定内容明确标记。

---

MIT © 2026 CAM Contributors · [Issues](https://github.com/canyonqian/cam/issues) · [PRs Welcome](https://github.com/canyonqian/cam/pulls)
