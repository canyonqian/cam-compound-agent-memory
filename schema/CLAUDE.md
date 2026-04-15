# CAM - AI 行为规范

> **这是整个知识库的核心规则文件。** AI Agent 在操作此知识库时，必须严格遵循以下所有规则。任何对 Wiki 目录的读写操作都应以此文件为准则。

---

## 一、系统概述

### 1.1 这是什么

**CAM（Compound Agent Memory）** 是一套基于本地 Markdown 文件的、由 AI Agent 驱动的个人/团队知识管理系统。核心理念是让 LLM 扮演全职知识管理员，通过"原始资料 → 结构化Wiki → 持续演化"的循环，实现知识的 **复利式积累与增长**。

### 1.2 核心原则

| 原则 | 说明 |
|------|------|
| **人类投喂，AI整理** | 人只负责把资料扔进 `raw/`，其余工作交给 AI |
| **原始资料不可篡改** | `raw/` 中的文件为只读源，保证信息可追溯 |
| **Wiki 全权归 AI** | `wiki/` 中的内容由 AI 维护，人类只读不编辑 |
| **关联产生价值** | 每个新知识点都必须与现有知识建立链接 |
| **持续迭代优化** | 通过 LINT 机制定期体检，消除错误和矛盾 |

---

## 二、目录结构与权限

```
cam/
├── raw/                    # 📥 原始资料层（人类写入，AI 只读）
│   └── *.*                 #    任意格式的原始素材
│
├── wiki/                   # 📝 知识层（AI 全权维护）
│   ├── index.md            #    全局索引页
│   ├── changelog.md        #    变更日志
│   ├── concept/            #    概念页面（理论、方法、定义）
│   ├── entity/             #    实体页面（人、组织、项目、工具）
│   └── synthesis/          #    综合页面（对比分析、综述、总结）
│
├── schema/                 # ⚙️ 规则层（人类定义，AI 遵循）
│   ├── CLAUDE.md           #    ← 本文件：AI 行为规范
│   ├── PERSPECTIVE.md      #    用户视角定义（可选）
│   └── templates/          #    页面模板
│       ├── concept.md      #    概念页模板
│       ├── entity.md       #    实体页模板
│       └── synthesis.md    #    综合页模板
│
├── outputs/                # 📤 产出层（问答结果、分析报告）
│
└── scripts/                # 🔧 辅助工具脚本
```

### 权限矩阵

| 目录 | 读取权限 | 写入权限 | 谁负责 |
|------|---------|---------|--------|
| `raw/` | ✅ AI 可读 | ❌ AI 不可写 | 人类 |
| `wiki/` | ✅ 两者可读 | ✅ 仅 AI 可写 | AI |
| `schema/` | ✅ AI 可读 | ❌ AI 不可改 | 人类 |
| `outputs/` | ✅ 两者可读 | ✅ 两者可写 | 两者 |

---

## 三、Wiki 编写规范

### 3.1 通用格式要求

每个 Wiki 页面 **必须** 包含以下元数据头部：

```markdown
---
title: "页面标题"
type: concept | entity | synthesis
created: YYYY-MM-DD
updated: YYYY-MM-DD
status: draft | active | superseded | deprecated
source: [raw/中的来源文件, 可多个]
tags: [标签1, 标签2, ...]
related: [[相关主题1]], [[相关主题2]]
---

# 页面标题

## 摘要
（2-3 句话概括核心内容）

## 正文
...

## 关键要点
- 要点 1
- 要点 2

## 来源引用
- [[raw-source-1]] → 核心观点 A（第X段）
- [[raw-source-2]] → 数据支撑 B（第Y段）

## 关联知识
- 详见 [[相关概念]]
- 对比参见 [[对比页面]]
```

### 3.2 双链规范

- 使用 `[[页面名]]` 格式创建内部链接
- **每次新建或更新页面时，必须扫描并更新所有相关页面的链接**
- 新页面至少关联 1 个已有页面（首个页面除外）
- 不存在的页面用 `[[尚未创建的页面]]` 标记为待建

### 3.3 三种页面类型

#### 概念页 (`wiki/concept/`)
用于记录：理论、方法论、定义、原理、模式等抽象知识。

```markdown
---
title: "概念名称"
type: concept
created: 2026-01-15
updated: 2026-01-15
status: active
source: ["raw/paper-xxx.md"]
tags: [分类标签]
related: [[前置概念]], [[应用场景]]
---

# 概念名称

## 定义
（一句话精确定义）

## 核心原理
（解释它为什么有效、如何运作）

## 关键特征
1. 特征一
2. 特征二

## 与其他概念的关系
| 对比维度 | 本概念 | [[类似概念A]] | [[对立概念B]] |
|----------|--------|-------------|-------------|

## 应用场景
- 场景一
- 场景二

## 局限性
（诚实地标注不足和边界）
```

#### 实体页 (`wiki/entity/`)
用于记录：人、组织、项目、产品、工具等具体对象。

```markdown
---
title: "实体名称"
type: entity
created: 2026-01-15
updated: 2026-01-15
status: active
source: ["raw/article-xxx.md"]
tags: [类型, 领域]
related: [[所属领域]], [[相关实体]]
---

# 实体名称

## 基本信息
| 属性 | 内容 |
|------|------|
| 类型 | 人物 / 组织 / 项目 / 工具 |
| 领域 | 所属领域 |

## 概述
（2-3段话全面介绍）

## 核心贡献/特点
1. ...
2. ...

## 时间线
- YYYY-MM-DD: 事件描述
- YYYY-MM-DD: 事件描述

## 关联关系
- 属于 [[上级组织]]
- 与 [[相关实体]] 有合作关系
```

#### 综合页 (`wiki/synthesis/`)
用于记录：对比分析、综合综述、总结归纳等高阶知识产物。

```markdown
---
title: "综合分析标题"
type: synthesis
created: 2026-01-15
updated: 2026-01-15
status: active
source: ["wiki/concept/a.md", "wiki/concept/b.md"]
tags: [对比, 综述]
related: [[概念A]], [[概念B]]
---

# 标题

## 分析目的
（为什么要做这个分析）

## 多维对比
| 维度 | 方案A [[A]] | 方案B [[B]] |
|------|------------|------------|
| 指标1 | ... | ... |
| 指标2 | ... | ... |

## 结论与建议
（基于对比得出的明确结论）

## 置信度说明
（哪些结论有强数据支撑，哪些是推断）
```

---

## 四、核心工作流

### 工作流 1：INGEST（资料摄入）

**触发条件**：用户将新资料放入 `raw/` 目录后发出指令。

**AI 执行步骤**：

1. **扫描** `raw/` 中未被处理的新文件（检查 `changelog.md` 确认已处理列表）
2. **阅读** 每个新文件，提取：
   - 🔤 核心概念/术语（→ 可能新建 `concept/` 页面）
   - 👤 涉及的实体（→ 可能新建 `entity/` 页面）
   - 📊 关键数据、论点、结论
   - 🔗 与现有 Wiki 页面的潜在关联
3. **创建/更新** Wiki 页面：
   - 为新概念创建 `wiki/concept/*.md`
   - 为新实体创建 `wiki/entity/*.md`
   - **批量更新**所有受影响的已有页面（添加引用、补充关联）
4. **维护索引**：
   - 更新 `wiki/index.md`（新增条目到对应分类）
   - 更新 `wiki/changelog.md`（记录本次操作）

**命名规范**：
- 概念页：`wiki/concept/<英文slug>.md`（如 `rag-system.md`, `compound-interest.md`）
- 实体页：`wiki/entity/<英文slug>.md`（如 `andrej-karpathy.md`, `openai.md`）
- 综合页：`wiki/synthesis/<英文slug>-<类型>.md`（如 `llm-vs-rag-compare.md`）

### 工作流 2：QUERY（知识查询）

**触发条件**：用户基于知识库提问。

**AI 执行步骤**：

1. 先读 `wiki/index.md` 定位可能相关的页面
2. 读取相关页面内容，追踪 `[[双链]]` 获取关联知识
3. 基于结构化 Wiki 内容生成答案
4. **每个关键论点必须标注来源**（如 `[来源：wiki/concept/xxx.md]`）

### 工作流 3：LINT（健康审计）

**触发条件**：用户发出审计指令，或定期自动执行。

**AI 检测项目**：

| 检测项 | 严重级别 | 说明 |
|--------|---------|------|
| 🔴 内容矛盾 | **严重** | 同一事实在不同页面中表述冲突 |
| 🟠 孤立页面 | **中等** | 有页面没有任何入链或出链 |
| 🟡 缺失引用 | **中等** | 关键结论没有 `raw/` 来源支撑 |
| 🔵 过时标记 | **低** | 长期未更新的内容需确认有效性 |
| 🟢 待建链接 | **提示** | `[[未创建页面]]` 可考虑补建 |

**输出格式**：

```markdown
# CAM LINT 报告

**执行时间**: YYYY-MM-DD HH:MM
**扫描范围**: wiki/ 下共 N 个文件

## 问题汇总
| 级别 | 数量 |
|------|------|
| 🔴 严重 | X |
| 🟠 中等 | X |
| 🟡 低 | X |
| 🔵 提示 | X |

## 详细问题

### 🔴 内容矛盾 (X)
1. **问题**: [描述矛盾点]
   - `wiki/concept/A.md` 第X行: "..."
   - `wiki/concept/B.md` 第Y行: "..."
   - **建议**: [修正建议]

### 🚀 改进建议
1. 建议新建页面: [页面名] （被引用N次但不存在）
2. 建议合并页面: [页面A] 和 [页面B] （内容高度重叠）
```

---

## 五、质量标准

### 5.1 内容质量

- ✅ 每个论断必须有来源引用（来自 `raw/` 或明确标注为推断）
- ✅ 推断性内容必须使用"可能""推测""似乎"等谨慎措辞
- ✅ 不同来源的观点差异要明确标注
- ❌ 严禁编造不存在的来源或数据
- ❌ 严禁删除原始资料中的关键信息

### 5.2 关联质量

- ✅ 新建页面必须 ≥ 1 个 `[[关联]]` 链接
- ✅ 更新已有页面时必须同步更新关联页面的反向链接
- ✅ 使用精确的页面名作为链接文本
- ❌ 禁止创建"孤岛页面"（无任何链接的页面）

### 5.3 维护质量

- ✅ 每次 INGEST 操作必须更新 `changelog.md`
- ✅ 每 10 次 INGEST 后建议执行一次完整 LINT
- ✅ 过时信息标记为 `status: deprecated` 而非直接删除

---

## 六、用户视角配置（可选但推荐）

如果存在 `schema/PERSPECTIVE.md` 文件，AI 应在处理信息时参考用户的视角偏好。

示例 `PERSPECTIVE.md`:

```markdown
# 用户视角定义

## 身份
我是 [角色]，从事 [领域] 工作。

## 兴趣方向
我关注以下方向的信息：
- 方向 1：[具体描述]
- 方向 2：[具体描述]

## 信息过滤偏好
- 优先保留：[什么类型的详细信息]
- 可以简化：[什么类型的细节]
- 忽略不计：[什么类型的内容]

## 语言风格
- 技术术语：保留原文 / 翻译为中文 / 双语对照
- 描述深度：高度概括 / 中等详细 / 尽量详尽
```

---

## 七、错误处理策略

### 7.1 AI 幻觉防护

当遇到不确定的信息时：

1. **明确标注不确定性**："此信息未能从原始资料中验证"
2. **追溯来源**：注明是基于哪个 `raw/` 文件的哪部分内容推断的
3. **不 silently 忽略**：将不确定项记录在页面底部 `## 待验证` 区域

### 7.2 冲突解决

当发现信息矛盾时：

1. 不要自行选择"正确"的一方
2. 在两个页面分别标注矛盾点
3. 在 LINT 报告中列为 🔴 严重问题
4. 等待人工裁决

### 7.3 资料缺失

当 Wiki 引用的 `raw/` 文件不存在时：

1. 标记该引用为断裂状态
2. 不删除对应的 Wiki 内容（标记为 `source-missing`）
3. 在 LINT 报告中提醒用户补充原始资料

---

## 八、自动化引擎行为规范（Auto Engine）

当通过 `auto/agent.py` 自动运行时，AI 需遵循额外的自动化行为规则。

### 8.1 自动摄取（Auto INGEST）

文件监听器检测到 `raw/` 有新文件后，自动触发摄取流程：

```
raw/ 新文件 → Watcher 检测 → Pipeline.run() 
→ LLM 读取 + 规则解析 → Wiki 页面生成 + 链接建立
→ Index 更新 + Changelog 记录 → State 持久化
```

**自动化规则：**
- ✅ 批量处理：等待 `batch_wait_seconds`（默认30s）安静窗口后批量处理所有新文件
- ✅ 增量处理：只处理状态为 `pending` 的文件，跳过已处理的（通过 SHA256 判断）
- ✅ 大于 2MB 的文件自动跳过并记录警告
- ✅ 每处理完一个批次自动更新全局索引
- ✅ 每 N 次 INGEST（默认10次）自动触发一次 LINT 检查

### 8.2 自动查询归档（Auto Query Archive）

用户提问后，高质量回答自动归档为 synthesis 页面：

- ✅ 回答长度 > 200 字符时自动归档
- ✅ 归档文件名格式: `wiki/synthesis/q-{timestamp}-{question-slug}.md`
- ✅ 归档页面包含完整的问题和回答内容

### 8.3 定时任务（Scheduled Tasks）

| 任务 | 默认时间 | 行为 |
|------|----------|------|
| **每日 LINT** | 每天 08:00 | 全库健康检查，报告写入 `outputs/` |
| **每周摘要** | 每周日 20:00 | 知识增长统计，写入 `outputs/weekly-summary-*.md` |
| **月度报告** | 每月1日 09:00 | 复利效应分析，写入 `outputs/monthly-report-*.md` |

### 8.4 网页采集器（Web Collector）

自动采集网页内容存入 `raw/collected/`：

- ✅ 自动提取正文（去除导航、广告、脚本等噪音）
- ✅ 转换为 Markdown 格式保存
- ✅ 在文件头部添加来源 URL 和采集时间元数据
- ✅ 文件名包含时间戳 + 域名 + 内容哈希，避免冲突
- ✅ 支持速率限制（默认每分钟10次请求）
- ✅ 支持多种输入方式：单URL / URL列表 / RSS订阅 / 书签文件

### 8.5 状态持久化（State Management）

每次操作后持久化以下状态：

```json
{
  "files": { "path": {"sha256": "...", "status": "done", ...} },
  "ingests": [...],   // 摄取历史
  "lints": [...],     // LINT 历史  
  "queries": [...]    // 查询历史
}
```

**关键机制：**
- **SHA256 内容哈希** — 即使文件时间戳变化，内容不变则不重复处理
- **原子操作** — 状态文件使用写-替换模式，防止损坏
- **错误恢复** — 中断后重新运行可从上次中断处继续（跳过已完成项）

### 8.6 多模型策略

不同任务使用不同模型以优化成本和质量：

| 任务 | 推荐模型 | 原因 |
|------|----------|------|
| **INGEST** (资料提取) | Claude Sonnet | 需要强理解和结构化能力 |
| **QUERY** (问答) | Claude Haiku | 快速响应，成本低 |
| **LINT** (体检) | Claude Sonnet | 需要细致的推理能力 |
| **COLLECT** (采集) | Claude Hauku | 仅用于简单元数据处理 |

---

## 九、插件系统（Plugin System）

### 9.1 MCP Server 插件（核心插件）

本项目提供 **MCP (Model Context Protocol) Server** 作为标准 AI 插件接口。

**支持平台：** Claude Desktop / Claude Code / Cursor / GitHub Copilot / 任何 MCP 兼容工具

**提供的工具：**

| 工具名 | 功能 |
|--------|------|
| `cam_ingest` | 向知识库添加内容（文本/URL/文章/笔记） |
| `cam_query` | 查询 knowledge base获取结构化答案 |
| `cam_lint` | 执行 LINT 健康检查 |
| `cam_stats` | 获取统计和增长指标 |
| `cam_list_sources` | 查看所有数据源插件状态 |
| `cam_ingest_from_source` | 触发特定数据源摄取 |

**安装方式：**

```json
// Claude Code / Cursor 配置文件
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["plugins/mcp_server.py"],
      "env": { "CAM_PROJECT_DIR": "${workspaceFolder}" }
    }
  }
}
```

### 9.2 数据源插件（多种投喂方式）

**你不必手动往 raw/ 扔文件！** 以下任一方式都可以自动投喂：

| 数据源 | 投喂方式 | 典型场景 |
|--------|---------|----------|
| 📁 **File Watcher** | 往 `raw/` 放文件即自动检测（默认开启） | 本地文件拖放 |
| 🌐 **Browser Clipper** | 浏览器按钮一键保存网页 | 网页文章保存 |
| 📋 **Clipboard Monitor** | 复制文本自动捕获 | 随手复制的内容 |
| 📧 **Email Watcher** | 监控邮箱自动提取邮件内容 | Newsletter/论文通知 |
| 📡 **RSS Reader** | 订阅 RSS/Atom 自动入库 | 博客/新闻/arXiv |
| 🤖 **Telegram Bot** | 转发消息给 Bot 自动保存 | 手机端随手存 |
| 💬 **Discord Bot** | 监控频道消息 | Discord 讨论记录 |
| 🔌 **REST API** | POST JSON 到本地接口 | 程序化批量导入 |
| 🪝 **Webhook** | 接收 Zapier/IFTTT/n8n 推送 | 自动化工作流 |

**配置方式：** 编辑 `plugins/config.json` → 在 `sources` 下设置 `"enabled": true`

### 9.3 输出适配器

| 适配器 | 功能 |
|--------|------|
| **Obsidian** | 直接用 Obsidian 打开项目文件夹即可获得图谱视图、反向链接、全文搜索 |
| **Logseq** | 导出为 Logseq 图谱格式 |
| **Web Dashboard** | 轻量级 Web 浏览界面（可选） |

### 9.4 插件架构

```
plugins/
├── mcp_server.py           # MCP 协议服务端
├── base.py                 # 抽象基类（BaseSource/BaseAdapter）
├── config.json             # 插件统一配置
├── sources/                # 数据源插件
│   ├── api_source.py       # REST API 端点
│   ├── browser.py          # 浏览器剪藏（Bookmarklet）
│   ├── clipboard.py        # 剪贴板监控
│   ├── email_source.py     # IMAP 邮箱监听
│   ├── rss_source.py       # RSS/Atom 订阅
│   ├── bot_telegram.py     # Telegram Bot
│   ├── bot_discord.py      # Discord Bot
│   ├── webhook_source.py   # Webhook 接收
│   └── file_watch.py       # 增强型文件监听
└── adapters/               # 输出适配器
    ├── obsidian.py         # Obsidian Vault 同步
    ├── logseq.py           # Logseq 导出
    └── web_ui.py           # Web 仪表盘
```

---

---

## 十、Memory Core — 对话自动记忆系统（v2.0）

> **这是 CAM 的核心创新。** 从"人喂资料 → AI整理"进化为 **"AI 对话自动产生记忆"**。

### 10.1 核心理念

```
传统模式:  你跟AI聊天 → 聊完就没了 → 下次从头再来
          ↓
Memory Core: 你跟AI聊天 → AI后台自动提取知识 → 存入Wiki → 
             下次对话自动参考已有知识 → 回答更精准 → 又产生新知识
             ↓
             复利循环 🔄
```

### 10.2 工作原理

Memory Core 通过 **Hook 引擎** 嵌入到 Agent 的对话生命周期中：

```
┌─────────────────────────────────────────────────────────────┐
│                    用户与 AI 的对话                           │
│                                                             │
│   用户: "我觉得这个项目应该用微服务架构"                      │
│   AI: "好主意，微服务可以..."                                │
│         ↓                                                   │
│   ┌──── HookEngine.on_turn_end() 自动触发 ────┐            │
│   │                                              │           │
│   │  ① 智能判断：这次对话值得提取吗？              │           │
│   │     ✓ 提到了架构决策 → 触发提取              │           │
│   │     ✗ "你好"/"谢谢" → 跳过                  │           │
│   │                                              │           │
│   │  ② LLM 提取：从对话中抽取结构化事实           │           │
│   │     → DECISION: "用户选择微服务架构"          │           │
│   │     → PREFERENCE: "关注架构设计"              │           │
│   │     → ENTITY: "当前项目"                      │           │
│   │                                              │           │
│   │  ③ 去重：和已有 Wiki 内容比对                 │           │
│   │     → 无重复 → 写入 Wiki                     │           │
│   │     → 近似重复 → 合并/替代                   │           │
│   │     → 矛盾 → 标记冲突                        │           │
│   │                                              │           │
│   │  ④ 写入：原子操作，并发安全                   │           │
│   │     → wiki/entity/current-project.md 更新    │           │
│   │     → 知识图谱更新                            │           │
│   │     → 索引 + 变更日志更新                     │           │
│   │                                              │           │
│   └──────────────────────────────────────────────┘           │
│         ↓                                                   │
│   （用户完全无感知，继续正常聊天）                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.3 自动提取的 6 种事实类型

| 类型 | Emoji | 示例 | 为什么重要 |
|------|-------|------|-----------|
| **FACT** (事实) | 📌 | "用户在 AcmeCorp 工作" | 建立用户画像基础 |
| **CONCEPT** (概念) | 💡 | "CQRS 模式分离读写模型" | 积累技术知识库 |
| **DECISION** (决策) | ✅ | "选择 Redis 而非 Memcached 作为缓存" | ⭐ 高价值：记录决策过程 |
| **PREFERENCE** (偏好) | 🎯 | "用户喜欢简洁的代码注释风格" | ⭐ 高价值：让 AI 越来越懂你 |
| **TASK** (任务) | 📋 | "需要实现认证中间件" | 追踪待办事项 |
| **ENTITY** (实体) | 🏷️ | "CAM, Andrej Karpathy" | 构建实体关系网 |

### 10.4 智能触发策略（不是每次都提取！）

Memory Core **不会**对每句话都调用 LLM 提取——那样既慢又贵。它有多层智能判断：

```
第1层：显式命令 → 立即提取
  "记住这个"、"note this"、"不要忘了"
  → bypass 所有检查，强制提取

第2层：内容质量判断 → 有价值就提取  
  ✅ 长消息（>500 tokens）
  ✅ 包含决策词汇（choose/decided/prefer/because/因为/决定/选择/偏好）
  ✅ 用户提问 + AI 长回答
  ❌ "hi" / "谢谢" / "ok"

第3层：频率控制 → 不超限
  - 最少间隔 15 秒（防止连续短对话刷 API）
  - 每小时最多 120 次提取
  - 每会话最多 500 次

第4层：批量队列 → 高效处理
  - 多个事实排队后一次性写入
  - 减少文件 I/O 和锁竞争
```

### 10.5 多 Agent 并发安全

当多个 Agent 同时写同一个 Wiki 时：

```
Agent A: "用户选择了方案X" ──→ 申请写入锁 ──→ 获取锁 → 写入 → 释放锁
Agent B: "项目使用Python"  ──→ 申请写入锁 ──→ 等待... → 获取锁 → 写入 → 释放锁
Agent C: "团队共5人"      ──→ 申请写入锁 ──→ 等待... → 等待... → 获取锁 → 写入 → 释放锁

安全保障:
✅ 文件级互斥锁（Windows msvcrt / Unix fcntl）
✅ 原子写入（先写临时文件 → rename，永不会损坏）
✅ 写前备份（保留最近 N 个版本）
✅ 冲突检测（Agent A 说 X, Agent B 说 not-X → 标记矛盾）
✅ 每条记录追踪来源 Agent ID
```

### 10.6 集成方式

#### 方式 A：Python Decorator（推荐，零代码侵入）

```python
from memory_core import MemoryCore

mc = MemoryCore(wiki_path="./wiki")
await mc.initialize()

# 只需加一个装饰器，所有对话自动记忆！
@mc.hook
async def chat(user_message: str) -> str:
    response = await my_llm.generate(user_message)
    return response

# 使用：
answer = await chat("我决定用 PostgreSQL 做主数据库")
# ← 自动提取：DECISION + PREFERENCE，存入 Wiki
# ← 用户完全不需要做任何额外操作
```

#### 方式 B：手动 Hook（适用于非 Python Agent）

```python
from memory_core import MemoryCore

mc = MemoryCore(wiki_path="./wiki")
await mc.initialize()

# 在你的对话循环中加入这一行：
while True:
    user_msg = get_user_input()
    ai_response = generate(user_msg)
    
    # ← 就这一行！
    await mc.remember(user_msg, ai_response)
    
    print(ai_response)
```

#### 方式 C：MCP Server（Claude Desktop / Cursor）

在 MCP 配置中添加：

```json
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "memory_core.mcp_server"],
      "env": { "WIKI_PATH": "./wiki" }
    }
  }
}
```

然后在任何 AI 对话中使用 `remember` 工具。

#### 方式 D：HTTP API（任何语言/平台）

```bash
# POST 到 Memory Core 的 HTTP 接口
curl -X POST http://localhost:9877/memory/hook \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "我更喜欢函数式编程风格",
    "assistant_response": "好的，我会记住这个偏好..."
  }'
# → 返回：{"facts_extracted": 2, "facts_written": 2}
```

### 10.7 复利效应时间线

```
第1天:
  对话 50 轮 → 自动提取 ~15 个事实 → Wiki 初具雏形
  
第1周:
  累计 300+ 轮对话 → ~100 个事实 → 开始出现关联链接
  AI 能回忆起："你上周说过喜欢 TypeScript..."
  
第1月:
  累计 1500+ 轮 → ~500 个事实 + 200+ 个实体节点
  知识图谱形成 → AI 主动建议关联信息
  
第3月:
  AI 比你还了解你的项目历史、偏好、决策脉络
  新成员入职 → 读 Wiki → 快速对齐上下文
  ⚡ 效率翻倍点
```

### 10.8 配置选项

通过编辑 `memory_core/config.json` 或环境变量调整行为：

```json
{
  "extraction": {
    "extract_facts": true,
    "extract_concepts": true,
    "extract_decisions": true,
    "extract_preferences": true,
    "min_confidence": 0.6,
    "max_extractions_per_turn": 10
  },
  "deduplication": {
    "similarity_method": "keyword",
    "auto_supersede": true
  },
  "concurrency": {
    "enable_locking": true,
    "agent_id": "my-agent",
    "track_agent_contributions": true
  },
  "llm_provider": "auto",
  "llm_model": "auto"
}
```

---

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| **v2.0** | 2026-04-14 | **核心升级**: Memory Core — AI对话自动记忆系统。Hook引擎 + LLM提取器 + 去重器 + 并发安全SharedWiki + 知识图谱 + Agent SDK + MCP Server |
| v1.2 | 2026-04-14 | 新增插件系统：MCP Server + 9种数据源插件 + 3种输出适配器 |
| v1.1 | 2026-04-14 | 新增自动化引擎：文件监听、自动摄取、定时任务、网页采集、状态持久化 |
| v1.0 | 2026-04-14 | 初始版本，定义完整的 CAM 规范 |
