# 🧠 Compound Wiki

<p align="center">
  <strong>Universal AI-Driven Compound Memory System — Make Knowledge Grow in Value Over Time</strong>
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> ·
  <a href="./README.en.md">English</a> &nbsp;&nbsp;
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/version-2.0.0-blue" alt="Version">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Status-Ready-green" alt="Status"></a>
  <a href="https://github.com/canyonqian/compound-wiki/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs Welcome"></a>
</p>

---

## ✨ What is This?

**Compound Wiki** is an **open-source, universal AI Agent memory and knowledge management solution**. Inspired by Andrej Karpathy's [LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) concept, refined with best practices from the OpenClaw three-layer memory system.

> **In a nutshell**: You just feed materials into it, AI handles organizing everything into a structured Wiki. Knowledge auto-connects and continuously evolves — **it gets smarter the more you use it**.

### Core Features

| Feature | Description |
|---------|-------------|
| 🔁 **Compound Growth** | Each operation adds new content AND automatically enhances 10-15 related pages |
| 🤖 **AI-Managed** | Humans only feed materials; AI maintains and updates the entire Wiki |
| 🔗 **Knowledge Network** | Double-link mechanism forces AI to think about connections between concepts |
| 📝 **Pure Markdown** | No database needed, no proprietary software — still readable in 10 years |
| 🔍 **LINT Auditing** | Built-in health checks to prevent error amplification in loops |
| 🚀 **Daemon Process** | **NEW in v2.0!** One HTTP service handles memory for ALL Agents — integrate in 1 line |
| 🔌 **Agent-Agnostic** | OpenClaw / Hermes / Claude Code / Cursor / Copilot / Any HTTP-capable Agent |
| 📦 **pip Install** | `pip install compound-wiki` — one command, globally available |
| 🛡️ **Smart Dedup** | Similarity-based dedup engine — auto-merges duplicate facts, prevents knowledge bloat |

---

## 📐 Architecture (v2.0)

```
compound-wiki/
│
├── cw_daemon/               🚀 v2.0 Core — Daemon Process (NEW!)
│   ├── server.py            ⭐ FastAPI HTTP server + extract/dedup/write pipeline
│   ├── config.py            Config system (LLM / port / throttle params)
│   ├── client.py            Lightweight SDK (3-line integration for any Agent)
│   ├── daemon.py            Lifecycle management (PID / graceful shutdown)
│   ├── scheduler.py         Scheduled tasks (LINT / index rebuild / stats)
│   └── _run.py              Entry point
│
├── memory_core/             🧠 Memory Core v2.0
│   ├── deduplicator.py      ⭐ Smart dedup engine (similarity detection + merge)
│   ├── shared_wiki.py       ⭐ Concurrent-safe Wiki (file locks + atomic writes + merge mode)
│   ├── agent_sdk.py         ⭐ Agent SDK (decorator / MCP / HTTP multi-mode)
│   ├── mcp_server.py        MCP protocol server
│   └── examples/
│
├── compound_wiki/           ⭐ CLI entry point
│   ├── cli.py               Unified CLI interface
│   └── cli_daemon.py        🆕 Daemon management subcommands
│
├── plugins/                 🧩 Plugin System
│   ├── mcp_server.py        MCP Server (6 tools)
│   ├── openclaw/index.ts    OpenClaw plugin (→ HTTP mode)
│   └── sources/             9 data source plugins
│
├── auto/                    ⚡ Auto Engine (file watcher + scheduled ingest)
├── schema/                  ⚙️ Rules layer (CLAUDE.md AI behavior spec + templates)
├── raw/                     📥 Raw material drop zone
├── wiki/                    📝 Knowledge base (AI-maintained, double-linked)
├── outputs/                 📤 Output layer
├── scripts/cw_tool.py       🔧 Utility tools
├── examples/                📚 Examples
├── README.md / README.en.md
└── LICENSE                  MIT
```

### v2.0 Architecture Overview — Unified Daemon Memory Layer

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
              │    cw_daemon (v2.0)    │  ← One process, unified memory for ALL Agents
              │                       │
              │  ┌─────────────────┐  │
              │  │ ThrottleController│  │  ← 10s debounce + content hash dedup
              │  ├─────────────────┤  │
              │  │ CwEngine        │  │  ← LLM extract → dedup → write → update index
              │  ├─────────────────┤  │
              │  │ Deduplicator    │  │  ← Similarity >85% auto-merge
              │  └─────────────────┘  │
              │                       │
              │  GET /query  /stats   │  ← Query & Stats API
              └──────────┬────────────┘
                         │ Write
                         ▼
              ┌───────────────────────┐
              │       wiki/            │  ← Structured knowledge base
              │  concept/entity/synthesis
              └───────────────────────┘
```

**v1.x → v2.0 Key Changes:**

| | v1.x (Plugin Mode) | v2.0 (Daemon Mode) |
|---|---|---|
| Each Agent needs | Write custom plugin (~200 lines) | **1 HTTP call** |
| Dedup logic | Per-agent (buggy) | **Unified in Daemon** |
| Write paths | MCP / MC dual-track (inconsistent) | **Single write pipeline** |
| Index update | Never auto-updated | **Auto-updated after every write** |
| New Agent onboarding | ~200 lines of code | **3 lines of code** |

### Responsibility Boundary

```
┌─────────────────────────────────────────────┐
│               You (Human)                   │
│                                             │
│  ✅ Drop materials into raw/                │
│  ✅ Define schema/CLAUDE.md rules           │
│  ✅ Read contents from wiki/                │
│  ✅ Review LINT reports periodically        │
│                                             │
│  ❌ Do NOT edit wiki/ content directly      │
│  ❌ Do NOT modify core CLAUDE.md rules     │
│                                             │
├─────────────────────────────────────────────┤
│               AI (Agent)                    │
│                                             │
│  ✅ Read raw materials from raw/            │
│  ✅ Create/update all pages in wiki/        │
│  ✅ Build [[double-link]] connections       │
│  ✅ Maintain index.md and changelog.md     │
│  ✅ Execute LINT health audits             │
│  ✅ Answer questions based on Wiki         │
│                                             │
│  ❌ Do NOT modify any files in raw/        │
│  ❌ Do NOT modify schema/ rule files       │
│                                             │
└─────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

> ⚡ **v2.0 — Zero-config integration for any AI Agent, no API key needed!**

### Method A: Daemon Mode (Recommended — NEW in v2.0)

The most powerful approach. Start one daemon, all Agents connect via HTTP:

```bash
# 1. Install
pip install compound-wiki

# 2. Start the daemon
cw daemon start --wiki ./wiki --port 9877

# 3. Any Agent just sends conversations (1 line!)
curl -X POST http://localhost:9877/hook \
  -H "Content-Type: application/json" \
  -d '{"user_message": "We use PostgreSQL", "ai_response": "Noted", "agent_id": "openclaw"}'

# Python Agent (3-line integration)
from cw_daemon.client import CwClient, AutoRemember

client = CwClient()                              # Default: localhost:9877
auto = AutoRemember(agent_id="my-bot")           # Or use decorator pattern

reply = await my_llm.chat(user_msg)
await auto(user_msg, reply)                      # ← That's it! Auto-extract + dedup + write

# Query knowledge base
result = await client.query("database selection") # Returns relevant Wiki pages

# Management
cw daemon status    # Check daemon status
cw daemon stop      # Stop gracefully
cw daemon ping      # Quick health check
```

**Full Daemon CLI:**

```bash
cw daemon start [--wiki PATH] [--port PORT] [--host HOST]  # Start daemon
cw daemon stop                                            # Graceful stop
cw daemon restart                                         # Restart
cw daemon status                                          # View status
cw daemon ping                                            # Quick health check
```

### Method B: MCP Plugin (For MCP-compatible Agents)

```bash
pip install 'compound-wiki[mcp]'
# Add MCP Server config in your AI tool (see INSTALL.md)
# Supports: Claude Desktop · Claude Code · Cursor · Copilot · Windsurf
```

**Why no API key?** Compound Wiki uses **Agent-Native mode**: the Daemon handles orchestration and storage; calling AI Agents use their own LLM for knowledge extraction. Zero extra cost.

### Method C: CLI (Standalone)

```bash
pip install compound-wiki
cw init my-knowledge-base
cd my-knowledge-base
# Drop files into raw/
cw ingest          # Process materials → AI compiles Wiki
cw stats           # View statistics
cw lint            # Health check
cw query "What is X?" # Query knowledge base
```

### Method D: From Source (Developers)

```bash
git clone https://github.com/canyonqian/compound-wiki.git
cd compound-wiki
pip install -e .          # Editable mode for development
cw init .
```

**Prerequisites**: Python 3.8+

**Optional dependencies:**
```bash
pip install 'compound-wiki[auto]'      # Auto engine (file watcher + scheduler)
pip install 'compound-wiki[anthropic]' # Anthropic Claude support
pip install 'compound-wiki[openai]'    # OpenAI GPT support
pip install 'compound-wiki[mcp]'       # MCP protocol support
pip install 'compound-wiki[all]'       # Everything
```

---

## 🧬 Memory Core — AI Conversation Auto-Memory (v2.0)

> **This is Compound Wiki's core capability.** From "human feeds materials → AI organizes" to **"AI conversation automatically produces memories, fully transparent"**.

### The Problem It Solves

```
❌ Traditional:
   You chat with AI → Context lost after chat → Re-explain background next time
   100th conversation = 1st experience (AI remembers nothing)

✅ Memory Core (v2.0):
   You chat with AI → Daemon auto-extracts knowledge → Deduplicates → Stores in Wiki
   Next conversation auto-references existing knowledge → Better answers
   100th conversation = AI knows your project/preferences/history better than you
```

### 3-Line Integration

```python
from cw_daemon.client import CwClient, AutoRemember

# Pattern A: Decorator style (recommended)
auto = AutoRemember(agent_id="my-bot")

reply = await my_llm.chat(user_msg)
await auto(user_msg, reply)   # ← Auto extract → dedup → write → update index

# Pattern B: Manual call
client = CwClient()
await client.remember(user_msg, ai_response)

# Pattern C: Any language that can send HTTP
POST http://localhost:9877/hook
{"user_message": "...", "ai_response": "..."}
```

### What Gets Auto-Extracted?

| Type | Example | Value |
|------|---------|-------|
| ✅ **Decision** | "Chose Redis over Memcached" | Record decision rationale |
| 🎯 **Preference** | "User likes concise comments" | AI learns your style over time |
| 📌 **Fact** | "Project uses Python 3.11+" | Build context foundation |
| 💡 **Concept** | "CQRS separates read/write" | Accumulate technical knowledge |
| 🏷️ **Entity** | "Team Alpha, Project Beta" | Build relationship network |

### Smart Deduplication (v2.0 Fix)

v2.0 rewrote the entire deduplication pipeline:

```
v1.x issue: Same fact "Using TDD" was written 4 times
v2.0 solution:
  ① ThrottleController — Don't reprocess identical content within 10s window
  ② Deduplicator — Similarity >85% auto-merge
  ③ _add_fact_to_page — Scan existing content before writing, skip duplicates
  ④ Merge mode — Both MCP and MC write paths unified as incremental merge
```

---

## 🔄 How The Compound Engine Works

### Why "Compound"?

Traditional KM is **linear** — input equals output.
Compound Wiki is **exponential** — every operation creates cascading value:

```
Round 1: Import material A → Create page A → +1 page

Round 2: Import material B → Create page B → Update page A (A↔B link) → +2 ops

Round 3: Q&A query X → Generate answer → Archive as synthesis S → Update citation chain → +N ops

Round 4: LINT audit → Fix contradictions → Overall quality improves → All future queries benefit
```

### Value Multiplication Per Operation

| Operation | Direct Output | Indirect Value Add |
|-----------|--------------|-------------------|
| Import 1 material | 1 new Wiki page | Auto-update 10~15 related pages |
| 1 Q&A session | Get answer | Archive as synthesis/comparison page |
| 1 LINT check | Fix issues | Overall accuracy improves |
| Time passes | - | Network density keeps increasing |

---

## 🧩 Plugin System & Data Sources

### 9 Data Source Plugins

| Plugin | How to Feed | Config |
|--------|-------------|--------|
| **📁 File Watcher** | Drop files into `raw/` | Enabled by default |
| **🌐 Browser Clipper** | One-click save from browser | Visit bookmarklet.js |
| **📋 Clipboard Monitor** | Auto-capture copied text | Set `min_length` filter |
| **📧 Email Watcher** | Auto-extract from IMAP inbox | Gmail/Outlook/any IMAP |
| **📡 RSS Reader** | Subscribe blogs/arXiv auto-import | Multi-feed + tags |
| **🤖 Telegram Bot** | Forward messages to bot | Create via @BotFather |
| **💬 Discord Bot** | Monitor channel messages | Multi-channel support |
| **🔌 REST API** | POST JSON to local endpoint | Programmatic batch import |
| **🪝 Webhook** | Receive Zapier/IFTTT/n8n pushes | Workflow automation |

### Output Adapters

| Adapter | Usage |
|---------|-------|
| **Obsidian** | Open `wiki/` directory → graph view, backlinks, full-text search |
| **Logseq** | One-click export to Logseq graph format |
| **Web Dashboard** | Lightweight web UI (optional) |

---

## 🛠️ CLI Commands

```bash
# === Knowledge Base ===
cw init my-wiki              # Initialize new KB
cw ingest                    # Process raw/ materials → Wiki
cw query "What is RAG?"     # Query knowledge base
cw stats                     # Statistics dashboard
cw lint                      # LINT health check
cw check-raw                 # View unprocessed raw/ files
cw status                    # Runtime overview

# === Daemon Management (v2.0) ===
cw daemon start [--wiki ./wiki] [--port 9877]   # Start daemon
cw daemon stop                                      # Stop gracefully
cw daemon restart                                   # Restart
cw daemon status                                    # View status
cw daemon ping                                      # Quick health check

# === Other ===
cw version                  # Show version
```

---

## 📖 Use Cases

### Use Case 1: Personal Learning & Research
Papers/tutorials → `raw/` → AI extracts concepts → Domain graph forms → New material auto-links to existing

### Use Case 2: Content Creation & Industry Research
Competitor materials → AI generates comparison pages → New entrants join matrix → Quick retrieval when writing

### Use Case 3: Team Knowledge Management
Shared repo → Each member feeds domain material → AI compiles unified team Wiki → New hires onboard fast

### Use Case 4: AI Agent Long-Term Memory ⭐
**This is v2.0's killer feature.** After starting the Daemon, every conversation turn from any Agent gets auto-extracted:

```python
# Add 3 lines to your Agent's main loop
from cw_daemon.client import AutoRemember
auto = AutoRemember(agent_id="my-agent")

# After each conversation turn:
reply = await agent.respond(user_message)
await auto(user_message, reply)  # ✅ Auto-memory
```

Supported Agents: OpenClaw / Hermes / Any Python Agent / curl / anything that speaks HTTP

---

## ❓ FAQ

### Q: Is this software or methodology?
**Both.** We provide a complete solution: Daemon + methodology spec (`schema/CLAUDE.md`) + project template + SDK. Core extraction work is done by AI — no model lock-in.

### Q: Does it conflict with Obsidian?
**Not at all — highly complementary.** Obsidian handles Markdown visualization; Compound Wiki defines how AI auto-organizes those files. Open `wiki/` in Obsidian for the best experience.

### Q: What about AI hallucinations?
Four layers of protection: ① Raw materials are traceable ② LINT periodic audits ③ Incremental imports for verification ④ Uncertain content explicitly marked

### Q: Can I use it offline?
**Yes.** Local model (Ollama/Qwen/etc.) + local files = fully offline private knowledge base.

### Q: How does this compare with RAG?

| | RAG | Compound Wiki |
|--|-----|---------------|
| Knowledge form | Doc chunks + vector index | Structured Wiki pages + double-link network |
| Query method | Re-retrieve + re-synthesize each time | Read already-structured content directly |
| Knowledge persistence | None, use-and-discard | Yes, iterates and persists forever |
| Long-term value | Low | **Compound growth** |

They complement each other: Compound Wiki for core knowledge, RAG for massive temporary reference docs.

---

## 🤝 Contributing

Contributions are welcome!

1. **Fork** this repo
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit (`git commit -m 'Add amazing feature'`)
4. Push (`git push origin feature/amazing-feature`)
5. Submit a Pull Request

### Especially Welcome

- 🌐 Multilingual CLAUDE.md
- 🎨 Better templates
- 🔌 More Agent adapters
- 📖 Example knowledge bases
- 🐛 Bug fixes

---

## 📄 License

MIT License © 2026 Compound Wiki Contributors

---

## 🙏 Acknowledgments & Inspiration

| Source | Contribution | Link |
|--------|-------------|------|
| **Andrej Karpathy — LLM-Wiki** | **Core architectural inspiration**. The "three folders + one rule file" paradigm is this project's foundation | [Original Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) |
| **OpenClaw / ClawdBot** | **Memory layering design**. Three-layer model and Hooks mechanism deeply influenced our architecture | [GitHub](https://github.com/openclaw/clawdbot) |
| **老金 (Alibaba Cloud)** | **Engineering practice reference** | [Article (CN)](https://developer.aliyun.com/article/1710321) |
| **一泽 (53AI)** | **Philosophical inspiration**. AI memory assets & compound value | [Article (CN)](https://www.53ai.com/news/gerentixiao/2025120317865.html) |

> ⚠️ **Disclaimer**: This project is an open-source universal Agent memory system framework integrating ideas from the above sources with general-purpose adaptations. All original concepts belong to their respective authors.

---

<p align="center">
  <strong>⭐ If this project helps you, please give it a Star! ⭐</strong>
</p>

<p align="center">
  Make knowledge compound · Build knowledge that compounds 🧠
</p>
