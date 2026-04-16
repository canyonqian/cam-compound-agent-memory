# CAM Schema — 知识组织规则

> 本文件定义 CAM (Compound Agent Memory) 的知识分类和页面格式标准。
> LLM Agent 在提取和组织知识时应遵循这些规则。

## 核心原则

1. **存知识，不存元数据** — 存技术原理、机制、方法，不存项目决策、用户偏好、会议记录
2. **结构化优先** — 知识应组织清晰，便于未来检索和理解
3. **去重** — 同一知识点只存一次，更新而非重复
4. **可追溯** — 每个知识点标注来源（原始对话时间/问题）

## 三层架构

### Layer 1: Raw（原始源）

- 路径：`wiki/raw/`
- 内容：不可变的对话记录
- 格式：`wiki/raw/YYYY-MM-DD-HH-MM-SS-{agentId}-{sessionId}.md`
- 规则：
  - 写入后**不再修改**
  - 包含用户消息 + agent 回答 + 时间戳
  - 用于知识追溯和重新提取

### Layer 2: Wiki（编译后的知识）

- 路径：`wiki/entity/`, `wiki/concept/`, `wiki/synthesis/`
- 内容：结构化的知识页面
- 规则见下方"页面格式"

#### 分类标准

| 分类 | 目录 | 存什么 | 例子 |
|------|------|--------|------|
| **Entity** | `wiki/entity/` | 具体的命名对象（项目、工具、服务、人名） | `RAG-Anything.md`, `Redis.md`, `OpenClaw.md` |
| **Concept** | `wiki/concept/` | 技术原理、工作机制、算法、方法、模式 | `WAL机制.md`, `多模态知识图谱.md`, `COW机制.md` |
| **Synthesis** | `wiki/synthesis/` | 对比分析、决策建议、经验教训、问题解决方案 | `RDB vs AOF对比.md`, `高并发数据库选型.md` |

#### 判断规则

- 问：**这是一个具体的东西吗？** → `entity`（工具名、项目名）
- 问：**这是关于"怎么工作"的吗？** → `concept`（原理、机制、方法）
- 问：**这是关于"选哪个/哪个好/怎么解决"的吗？** → `synthesis`（对比、决策、方案）

### Layer 3: Schema（规则）

- 路径：`schema/CLAUDE.md`（本文件）
- 内容：知识组织规则和模板
- 用途：告诉 LLM Agent 如何正确分类和组织知识

## 页面格式

### Entity 页面

```markdown
# entity → {实体名称}

> Auto-learned by CAM Knowledge Brain

---

🎯 **Entity** | Confidence: `████████░░` (85%)

**类型**: 工具/项目/服务/人
**描述**: 一句话简要说明

**关键信息**:
- 核心功能/用途
- 技术栈
- 相关链接/仓库

*Source*: {来源问题}
*Tags*: `heuristic` `entity`

---
```

### Concept 页面

```markdown
# concept → {概念名称}

> Auto-learned by CAM Knowledge Brain

---

💡 **Concept** | Confidence: `████████░░` (85%)

Topic: {主题}

Source Question: {用户的原始问题}

{技术原理/工作机制的详细说明}

*Source*: {来源问题}
*Tags*: `heuristic` `concept`

---
```

### Synthesis 页面

```markdown
# synthesis → {主题}

> Auto-learned by CAM Knowledge Brain

---

🔧 **Synthesis** | Confidence: `████████░░` (85%)

Topic: {主题}

Source Question: {用户的原始问题}

{对比分析/决策建议/解决方案}

*Source*: {来源问题}
*Tags*: `heuristic` `synthesis`

---
```

## 不存什么

以下内容**不应**存入 CAM wiki：

- ❌ 项目决策（"我们选了 SQLite"）
- ❌ 用户偏好（"我喜欢 pytest"）
- ❌ 项目约定（"所有 API 测试用 pytest"）
- ❌ 问候、确认、闲聊
- ❌ 会议记录
- ❌ agent 的思考过程（"Let me search..."）
- ❌ 纯日志输出

## 交叉引用

使用 `[[双括号]]` 格式引用其他 wiki 页面：

```
RAG-Anything 使用 [[多模态知识图谱]] 作为核心架构，
底层依赖 [[LightRAG]] 进行检索。
```
