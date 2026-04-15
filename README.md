# 🧠 Compound Wiki

<p align="center">
  <strong>AI 驱动的通用复利记忆系统 — 让知识越积累越值钱</strong>
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> ·
  <a href="./README.en.md">English</a> &nbsp;&nbsp;
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/version-2.0.0-blue" alt="Version">
  <a href="#快速开始"><img src="https://img.shields.io/badge/状态-可用-green" alt="Status"></a>
  <a href="https://github.com/canyonqian/compound-wiki/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs Welcome"></a>
</p>

---

## ✨ 这是什么？

**Compound Wiki（复利维基）** 是一套 **开源的、通用的 AI Agent 记忆与知识管理方案**。灵感来自 Andrej Karpathy 的 [LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 思想，结合了 OpenClaw 三层记忆系统的最佳实践。

> **一句话概括**: 你只管往里塞资料，AI 负责整理成结构化 Wiki，知识自动关联、持续演化，**越用越聪明**。

### 核心特性

| 特性 | 说明 |
|------|------|
| 🔁 **复利增长** | 每次操作不仅新增内容，还自动增强 10-15 个关联页面 |
| 🤖 **AI 全托管** | 人只负责投喂资料，Wiki 由 AI 自动维护和更新 |
| 🔗 **知识网络** | 双链机制强制 AI 思考知识点之间的关联 |
| 📝 **纯 Markdown** | 无需数据库、无需专用软件、十年后依然可读 |
| 🔍 **LINT 审计** | 内置健康检查机制，防止错误在循环中被放大 |
| 🚀 **Daemon 守护进程** | **v2.0 新增！** 一个 HTTP 服务统一处理所有 Agent 的记忆，一行代码接入 |
| 🔌 **Agent 通用** | OpenClaw / Hermes / Claude Code / Cursor / Copilot / 任何能发 HTTP 的 Agent |
| 📦 **pip 安装** | `pip install compound-wiki` 一行命令全局注册 |
| 🛡️ **智能去重** | 基于相似度的去重引擎，自动合并重复事实，杜绝知识膨胀 |

---

## 📐 架构设计（v2.0）

```
compound-wiki/
│
├── cw_daemon/               🚀 v2.0 核心 — 守护进程（NEW!）
│   ├── server.py            ⭐ FastAPI HTTP 服务 + 提取/去重/写入管线
│   ├── config.py            配置系统（LLM/端口/节流参数）
│   ├── client.py            轻量 SDK（3行接入任何 Agent）
│   ├── daemon.py            生命周期管理（PID/graceful shutdown）
│   ├── scheduler.py         定时任务（LINT/索引重建/统计日志）
│   └── _run.py              启动入口
│
├── memory_core/             🧠 Memory Core v2.0 核心
│   ├── config.py / hook_engine.py / extractor.py
│   ├── deduplicator.py      ⭐ 智能去重引擎（相似度检测+合并）
│   ├── shared_wiki.py       ⭐ 并发安全 Wiki（文件锁+原子写入+merge模式）
│   ├── agent_sdk.py         ⭐ Agent SDK（装饰器/MCP/HTTP多模式适配）
│   ├── memory_graph.py      知识图谱构建器
│   ├── mcp_server.py        MCP 协议服务端
│   └── examples/
│
├── compound_wiki/           ⭐ CLI 命令入口
│   ├── cli.py               统一命令行接口
│   └── cli_daemon.py        🆕 Daemon 管理子命令
│
├── plugins/                 🧩 插件系统
│   ├── mcp_server.py        MCP Server（6个工具）
│   ├── openclaw/index.ts    OpenClaw 插件（→ HTTP 模式）
│   └── sources/             9种数据源插件
│
├── auto/                    ⚡ 自动化引擎（文件监听+定时摄取）
├── schema/                  ⚙️ 规则层（CLAUDE.md AI行为规范 + 模板）
├── raw/                     📥 原始资料投喂区
├── wiki/                    📝 知识库（AI维护，双链网络）
├── outputs/                 📤 产出层
├── scripts/cw_tool.py       🔧 辅助工具
├── examples/                📚 示例
├── README.md / README.en.md
└── LICENSE                  MIT
```

### v2.0 架构总览 — Daemon 统一记忆层

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  OpenClaw   │  │   Hermes    │  │ Claude Code │  │  Cursor     │
│  (TypeScript)│  │  (Python)  │  │  (MCP)      │  │  (MCP)      │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │ POST /hook       │ POST /hook       │ MCP tools       │ MCP tools
       │                  │                  │                 │
       └──────────────────┼──────────────────┼─────────────────┘
                          ▼
              ┌───────────────────────┐
              │    cw_daemon (v2.0)    │  ← 一个进程，统一所有 Agent 记忆
              │                       │
              │  ┌─────────────────┐  │
              │  │ ThrottleController│  │  ← 10秒防抖 + 内容hash去重
              │  ├─────────────────┤  │
              │  │ CwEngine        │  │  ← LLM提取 → 去重 → 写入 → 更新索引
              │  ├─────────────────┤  │
              │  │ Deduplicator    │  │  ← 相似度>85%自动合并
              │  └─────────────────┘  │
              │                       │
              │  GET /query  /stats   │  ← 查询 & 统计 API
              └──────────┬────────────┘
                         │ 写入
                         ▼
              ┌───────────────────────┐
              │       wiki/            │  ← 结构化知识库
              │  concept/entity/synthesis
              └───────────────────────┘
```

**v1.x → v2.0 的核心变化：**

| | v1.x（插件模式）| v2.0（Daemon 模式）|
|---|---|---|
| 每个 Agent 需要 | 写专属插件代码 | **1行 HTTP 调用** |
| 去重逻辑 | 各自实现（有bug） | **Daemon 统一处理** |
| 写入路径 | MCP / MC 双轨不一致 | **唯一写入管线** |
| 索引更新 | 从未自动更新 | **每次写入后自动更新** |
| 接入新 Agent | ~200行代码 | **3行代码** |

### 权责边界

```
┌─────────────────────────────────────────────┐
│              你 (人类)                       │
│                                             │
│  ✅ 往 raw/ 扔资料                           │
│  ✅ 定义 schema/CLAUDE.md 规则               │
│  ✅ 定义 schema/PERSPECTIVE.md 视角          │
│  ✅ 读 wiki/ 中的内容                        │
│  ✅ 定期审查 LINT 报告                       │
│                                             │
│  ❌ 不编辑 wiki/ 中的内容                    │
│  ❌ 不修改 schema/CLAUDE.md 中的核心规则     │
│                                             │
├─────────────────────────────────────────────┤
│              AI (Agent)                     │
│                                             │
│  ✅ 读取 raw/ 中的原始资料                   │
│  ✅ 创建/更新 wiki/ 中的所有页面             │
│  ✅ 建立 [[双链]] 关联                       │
│  ✅ 维护 index.md 和 changelog.md           │
│  ✅ 执行 LINT 健康审计                      │
│  ✅ 基于 Wiki 回答问题                       │
│                                             │
│  ❌ 不修改 raw/ 中的任何文件                 │
│  ❌ 不修改 schema/ 中的规则文件              │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 🚀 快速开始

> ⚡ **v2.0 零配置接入任何 AI Agent，无需单独配 API Key！**

### 方式一：Daemon 模式（推荐 — v2.0 新功能）

这是最强大的使用方式。启动一个守护进程，所有 Agent 通过 HTTP 对接：

```bash
# 1. 安装
pip install compound-wiki

# 2. 启动守护进程
cw daemon start --wiki ./wiki --port 9877

# 3. 任何 Agent 只需发送对话（1行搞定！）
curl -X POST http://localhost:9877/hook \
  -H "Content-Type: application/json" \
  -d '{"user_message": "我们用PostgreSQL做主库", "ai_response": "好的，已记录", "agent_id": "openclaw"}'

# Python Agent（3行接入）
from cw_daemon.client import CwClient, AutoRemember

client = CwClient()                              # 默认连接 localhost:9877
auto = AutoRemember(agent_id="my-bot")           # 或用装饰器模式

reply = await my_llm.chat(user_msg)
await auto(user_msg, reply)                      # ← 就这一行！自动提取+去重+写入

# 查询知识库
result = await client.query("数据库选型")         # 返回相关 Wiki 页面

# 管理
cw daemon status    # 查看 daemon 状态
cw daemon stop      # 停止
cw daemon ping      # 快速检查在线
```

**Daemon CLI 完整命令：**

```bash
cw daemon start [--wiki PATH] [--port PORT] [--host HOST]  # 启动守护进程
cw daemon stop                                            # 优雅停止
cw daemon restart                                         # 重启
cw daemon status                                          # 查看状态
cw daemon ping                                            # 快速健康检查
```

### 方式二：MCP 插件（适用于支持 MCP 的 Agent）

```bash
# 1. 安装
pip install 'compound-wiki[mcp]'

# 2. 在你的 AI 工具中添加 MCP Server（见 [INSTALL.md](./INSTALL.md)）
#    支持: Claude Desktop · Claude Code · Cursor · Copilot · Windsurf

# 3. 完成！在对话中直接使用：
#    "帮我记住这篇文章的内容" → Agent 自动调用 cw_ingest
#    "我之前学过什么关于 X 的？" → Agent 自动调用 cw_query
```

**为什么不需要 API Key？**
Compound Wiki 使用 **Agent-Native 模式**：Daemon 只负责编排和存储，调用它的 AI Agent 用自己的大脑做知识提取。零额外成本。

### 方式三：CLI 命令行（独立使用）

```bash
# 1. 一行安装
pip install compound-wiki

# 2. 初始化你的知识库
cw init my-knowledge-base

# 3. 进入项目目录
cd my-knowledge-base

# 4. 把资料扔进 raw/

# 5. 开始使用！
cw ingest          # 处理资料 → AI 编译 Wiki
cw stats           # 查看知识库统计
cw lint            # Wiki 健康检查
cw query "什么是X?" # 基于知识库提问
```

### 方式四：从源码安装（开发者）

```bash
git clone https://github.com/canyonqian/compound-wiki.git
cd compound-wiki
pip install -e .          # 可编辑模式开发
cw init .
```

**前置条件**：Python 3.8+

**可选依赖**：
```bash
pip install 'compound-wiki[auto]'      # 自动化引擎
pip install 'compound-wiki[anthropic]' # Anthropic Claude 支持
pip install 'compound-wiki[openai]'    # OpenAI GPT 支持
pip install 'compound-wiki[mcp]'       # MCP 协议支持
pip install 'compound-wiki[all]'       # 全部功能
```

---

## 🧬 Memory Core — AI 对话自动记忆（v2.0）

> **这是 Compound Wiki 最核心的能力。** 从"人喂资料 → AI整理"进化为 **"AI 对话自动产生记忆，全程无感"**。

### 解决的问题

```
❌ 传统模式：
   你跟AI聊天 → 聊完就没了 → 下次从头交代背景
   第100次对话 = 第1次的体验（AI完全不记得你）

✅ Memory Core (v2.0)：
   你跟AI聊天 → Daemon后台自动提取知识 → 去重 → 存入Wiki
   下次对话AI自动参考已有知识 → 回答更精准
   第100次对话 = AI比你还懂你的项目/偏好/历史决策
```

### 3 行代码集成

```python
from cw_daemon.client import CwClient, AutoRemember

# 方式 A：装饰器模式（推荐）
auto = AutoRemember(agent_id="my-bot")

reply = await my_llm.chat(user_msg)
await auto(user_msg, reply)   # ← 自动提取 → 去重 → 写入 → 更新索引

# 方式 B：手动调用
client = CwClient()
await client.remember(user_msg, ai_response)

# 方式 C：任何语言，只要能发 HTTP
POST http://localhost:9877/hook
{"user_message": "...", "ai_response": "..."}
```

### 自动提取什么？

| 类型 | 示例 | 价值 |
|------|------|------|
| ✅ **决策** | "选择了 Redis 而非 Memcached" | 记录决策脉络 |
| 🎯 **偏好** | "用户喜欢简洁注释风格" | 让 AI 越来越懂你 |
| 📌 **事实** | "项目使用 Python 3.11+" | 建立上下文基础 |
| 💡 **概念** | "CQRS 分离读写模型" | 积累技术知识库 |
| 🏷️ **实体** | "Team Alpha, 项目 Beta" | 构建关系网络 |

### 智能去重（v2.0 修复）

v2.0 重写了整个去重管线：

```
v1.x 问题：同一条 "Using TDD" 被写入了 4 次
v2.0 解决：
  ① ThrottleController — 10秒内相同内容不重复处理
  ② Deduplicator — 相似度 >85% 自动合并
  ③ _add_fact_to_page — 写入前扫描已有内容，重复即跳过
  ④ Merge 模式 — MCP 和 MC 两条写入路径统一为增量合并
```

---

## 🔄 复利引擎工作原理

### 为什么叫"复利"?

传统知识管理是**线性的**——你存多少就是多少。
Compound Wiki 是**指数的**——每次操作都会产生连锁增值：

```
第1轮: 导入资料A → 新建页面 A → +1 个页面

第2轮: 导入资料B → 新建页面 B → 更新页面 A（建立 A↔B 关联）→ +2 个操作

第3轮: 问答查询X → 生成答案 → 可归档为综述页 S → 更新引用链 → +N 个操作

第4轮: LINT审计 → 发现矛盾并修正 → 整体质量提升 → 所有后续查询受益
```

### 单次操作的增值效应

| 操作类型 | 直接产出 | 间接增值 |
|---------|---------|---------|
| 导入1篇资料 | 1个新Wiki页面 | 自动更新10~15个关联页面 |
| 1次查询问答 | 得到答案 | 可沉淀为综述/对比页面 |
| 1次LINT检查 | 修复问题 | 整体知识库准确性提升 |
| 时间推移 | - | 知识网络密度持续增加 |

---

## 🧩 插件系统 & 数据源

### 9 种数据源输入

| 插件 | 投喂方式 | 配置 |
|------|---------|------|
| **📁 File Watcher** | 往 raw/ 放文件即自动检测 | 默认开启 |
| **🌐 Browser Clipper** | 浏览器按钮一键保存 | 启动后访问 bookmarklet.js |
| **📋 Clipboard Monitor** | 复制文本自动捕获 | 设置 min_length 过滤短文本 |
| **📧 Email Watcher** | IMAP邮箱自动提取 | 支持 Gmail/Outlook/任意IMAP |
| **📡 RSS Reader** | 订阅博客/arXiv自动入库 | 支持多Feed + 标签分类 |
| **🤖 Telegram Bot** | 转发消息给Bot | 通过 @BotFather 创建 |
| **💬 Discord Bot** | 监控频道消息 | 支持多频道 |
| **🔌 REST API** | POST JSON到本地接口 | 适合程序化批量导入 |
| **🪝 Webhook** | 接收Zapier/IFTTT/n8n推送 | 自动化工作流集成 |

### 输出适配器

| 适配器 | 用法 |
|--------|------|
| **Obsidian** | 直接打开 wiki/ 目录 → 图谱视图、反向链接、全文搜索 |
| **Logseq** | 一键导出为 Logseq 图谱格式 |
| **Web Dashboard** | 轻量级 Web 浏览界面（可选） |

---

## 🛠️ CLI 命令一览

```bash
# === 知识库管理 ===
cw init my-wiki              # 初始化新知识库
cw ingest                    # 处理 raw/ 资料 → Wiki
cw query "什么是RAG?"        # 基于知识库提问
cw stats                     # 统计面板
cw lint                      # LINT 健康检查
cw check-raw                 # 查看 raw/ 未处理文件
cw status                    # 运行状态总览

# === Daemon 管理（v2.0）===
cw daemon start [--wiki ./wiki] [--port 9877]   # 启动守护进程
cw daemon stop                                      # 停止
cw daemon restart                                   # 重启
cw daemon status                                    # 查看状态
cw daemon ping                                      # 快速健康检查

# === 其他 ===
cw version                  # 显示版本
```

---

## 📖 使用场景

### 场景 1：个人学习 & 学术研究
论文/教程扔进 raw/ → AI 提取概念方法 → 形成领域知识图谱 → 新资料自动关联旧知识

### 场景 2：内容创作 & 行业研究
竞品素材持续摄入 → AI 生成对比分析页 → 新竞品自动加入对比矩阵 → 写作时快速检索

### 场景 3：团队知识管理
团队共享仓库 → 每人投喂各自领域资料 → AI 编译为统一团队 Wiki → 新人入职快速上手

### 场景 4：AI Agent 长期记忆 ⭐
**这是 v2.0 的杀手场景。** 启动 Daemon 后，任何 Agent 的每轮对话都会自动提取有价值的知识：

```python
# 在你的 Agent 主循环里加 3 行
from cw_daemon.client import AutoRemember
auto = AutoRemember(agent_id="my-agent")

# 每轮对话结束后：
reply = await agent.respond(user_message)
await auto(user_message, reply)  # ✅ 自动记忆
```

支持的 Agent：OpenClaw / Hermes / 任何 Python Agent / curl / ...

---

## ❓ FAQ

### Q: 这是软件还是方法论？
**两者皆是。** 我们提供了一套完整的方案：Daemon 守护进程 + 方法论规范（`schema/CLAUDE.md`）+ 项目模板 + SDK。核心提取工作由 AI 完成，不依赖特定模型。

### Q: 和 Obsidian 冲突吗？
**完全不冲突，高度互补。** Obsidian 负责 Markdown 可视化和图形展示；Compound Wiki 负责 AI 如何自动整理和维护这些文件。用 Obsidian 打开 `wiki/` 即可获得最佳体验。

### Q: AI 产生幻觉怎么办？
四重防护：①原始资料可溯源 ②LINT 定期审计 ③增量导入便于校验 ④不确定内容明确标记

### Q: 能离线使用吗？
**可以。** 本地模型（Ollama/Qwen 等）+ 本地文件 = 完全离线的私有知识库。

### Q: 和 RAG 有什么区别？

| | RAG | Compound Wiki |
|--|-----|---------------|
| 知识形态 | 原始文档切片 + 向量索引 | 结构化 Wiki 页面 + 双链网络 |
| 查询方式 | 每次重新检索 + 重新合成 | 直接读取已整理好的结构化内容 |
| 知识沉淀 | 无，用完即弃 | 有，持续迭代永久保存 |
| 长期价值 | 低 | **复利增长** |

两者也可互补：Compound Wiki 处理核心知识体系，RAG 处理海量临时参考文档。

---

## 🤝 贡献指南

欢迎贡献！

1. **Fork** 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交改动 (`git commit -m 'Add amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

### 特别欢迎

- 🌐 多语言 CLAUDE.md
- 🎨 更专业的模板
- 🔌 更多 Agent 适配器
- 📖 示例知识库
- 🐛 Bug 修复

---

## 📄 开源许可

MIT License © 2026 Compound Wiki Contributors

---

## 🙏 致谢与灵感来源

| 来源 | 贡献 | 链接 |
|------|------|------|
| **Andrej Karpathy — LLM-Wiki** | **核心架构灵感**。"三个文件夹 + 一个规则文件"范式是本项目的基石 | [Gist 原文](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) |
| **OpenClaw / ClawdBot** | **记忆分层设计**。三层记忆模型和 Hooks 机制深刻影响了本项目的架构 | [GitHub](https://github.com/openclaw/clawdbot) |
| **老金（阿里云）** | **工程实践参考**。落地实现路径 | [阿里云文章](https://developer.aliyun.com/article/1710321) |
| **一泽（53AI）** | **理念启发**。AI 记忆资产与复利价值 | [原文](https://www.53ai.com/news/gerentixiao/2025120317865.html) |

> ⚠️ **声明**: 本项目是开源通用 Agent 记忆系统框架，整合了上述思想并进行了通用化改造。所有原始思想归其原作者所有。

---

<p align="center">
  <strong>⭐ 如果这个项目对你有帮助，请给一个 Star 支持一下！⭐</strong>
</p>

<p align="center">
  让知识产生复利 · Build knowledge that compounds 🧠
</p>
