# 🧠 CAM — Compound Agent Memory

<p align="center">
  AI Agent Autonomous Learning Knowledge Engine · Zero Extra LLM Calls · Markdown Wiki Storage
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> · <a href="./README.en.md">English</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/canyonqian/cam/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs"></a>
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT">
</p>

---

## What?

CAM gives **any AI Agent** the ability to autonomously learn knowledge.

1. User sends message → **CAM intercepts**
2. After Agent replies → **CAM auto-extracts knowledge** into Wiki (zero extra LLM calls)
3. Next conversation → **CAM auto-recalls** relevant context into prompt

> Inspired by [Karpathy's LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): LLMs don't get bored of bookkeeping, which is exactly why humans stop maintaining wikis.

## How It Works

```
User message ──→ Agent (reply)
   │             │
   │             ├── llm_output hook → Heuristic extraction → Wiki/ (auto store)
   │
   └── message_received hook → Cache user message
```

**Zero extra LLM calls**: CAM doesn't call a separate LLM to extract knowledge — it grabs from the Agent's existing reply. The Agent was going to answer anyway; CAM just learns along the way.

## Three-Layer Architecture

```
                    ┌──────────────────────────────────┐
                    │  Layer 3: Schema (Rules)          │
                    │  schema/CLAUDE.md                 │
                    │  Classification · Page format · What NOT to store │
                    └────────────────┬─────────────────┘
                                     ↑
                    ┌──────────────────────────────────┐
                    │  Layer 2: Wiki (Compiled knowledge)│
                    │  concept/  — Principles, mechanisms│
                    │  synthesis/— Comparisons, decisions│
                    │  entity/   — Specific projects, tools, people │
                    └────────────────┬─────────────────┘
                                     ↑
                    ┌──────────────────────────────────┐
                    │  Layer 1: Raw (Immutable sources) │
                    │  raw/ — Full conversation logs    │
                    └──────────────────────────────────┘
```

## Project Structure

```
cam/
├── plugins/
│   └── openclaw/index.ts  ⭐ Core — OpenClaw plugin (v11)
│                            • message_received → Cache user messages
│                            • llm_output → Heuristic knowledge extraction
│                            • before_prompt_build → Schema + Wiki recall
├── cam_daemon/            FastAPI daemon (optional, Python SDK)
├── cam_core/              LLM extraction / dedup / Wiki write (Python SDK)
├── cam/                   CLI (`cam init`, `cam daemon start/stop`)
├── schema/                ⭐ Layer 3: Knowledge organization rules
│   ├── CLAUDE.md          Classification + page format + what NOT to store
│   └── templates/         Wiki page templates
└── wiki/                  Output: Structured Markdown pages
    ├── raw/               Raw conversation logs (immutable)
    ├── entity/            Specific entities (projects, tools, people)
    ├── concept/           Technical concepts (principles, mechanisms, methods)
    └── synthesis/         Synthesized knowledge (comparisons, decisions, solutions)
```

## Quick Start

### 1. Install & Init

```bash
pip install cam
cam init --dir ~/my-wiki          # creates wiki/ + schema/ directories
```

### 2. Connect via OpenClaw (recommended)

Install the plugin — CAM auto-learns through hooks:

```bash
openclaw plugin install /path/to/plugins/openclaw
openclaw gateway restart            # done! zero configuration
```

### 3. Or from any code (3 lines)

```python
from cam_daemon.client import CamClient, AutoRemember
client = CamClient()                # connects to localhost:9877
auto = AutoRemember(agent_id="my-agent")

# After each conversation:
await auto(user_message, reply)     # extracts knowledge → writes to wiki
results = await client.query("project architecture")  # recalls relevant context
```

## Agent Available Tools

| Tool | What It Does |
|------|-------------|
| `cam_query` | Search CAM Wiki knowledge base |
| `cam_stats` | View stats (fact count, pages, health) |

## Config

Set environment variables or edit `wiki/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CAM_PROJECT_DIR` | `./wiki` | Wiki output directory |
| `CAM_DAEMON_PORT` | `9877` | Daemon listen port |

## FAQ

**Q: Need a database?**
No. Pure Markdown files — human-readable, git-friendly, works great with Obsidian.

**Q: RAG vs CAM?**
RAG = slice raw docs → retrieve → re-synthesize each time (throw away after use).
CAM = extract once → structure into Wiki → iterate and persist forever (compounding growth).
They complement each other: CAM manages core knowledge, RAG handles massive temporary reference docs.

**Q: Need extra LLM calls?**
No. In OpenClaw mode, CAM extracts knowledge from the Agent's existing replies — zero extra calls.

**Q: What about hallucinations?**
Four defenses: ① Source traceability (raw/ directory) ② Periodic LINT audits ③ Incremental imports for verification ④ Uncertain content clearly marked.

---

MIT © 2026 CAM Contributors · [Issues](https://github.com/canyonqian/cam/issues) · [PRs Welcome](https://github.com/canyonqian/cam/pulls)
