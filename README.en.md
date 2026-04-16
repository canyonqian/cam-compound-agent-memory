# 🧠 CAM — Compound Agent Memory

<p align="center">
  AI-driven memory engine for any Agent · Auto-extract · Store in Wiki · Recall on demand
</p>

<p align="center">
  <a href="./README.md">🇨🇳 中文</a> · <a href="./README.en.md">English</a>
  &nbsp;·&nbsp;
  <a href="https://github.com/canyonqian/cam/issues"><img src="https://img.shields.io/badge/PRs-Welcome-blue" alt="PRs"></a>
  <img src="https://img.shields.io/badge/License-MIT-yellow" alt="MIT">
</p>

---

## What?

CAM gives **any AI Agent** persistent long-term memory.

1. Agent talks → **CAM auto-extracts** knowledge from conversations
2. Knowledge goes into a **Markdown Wiki** (no database needed)
3. Next conversation → **CAM auto-recalls** relevant context into the prompt

> Inspired by [Karpathy's LLM-Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f). The more you use it, the smarter it gets.

## How It Works

```
User message ──→ Agent ──→ Reply
     │                    │
     ├── ContextEngine.ingest() ──→ Daemon HTTP /hook ──→ Wiki/ (auto store)
     │
     ←── ContextEngine.assemble() ←─ Daemon GET /query ←── Wiki/ (auto recall)
```

**Three layers** (inspired by LCM / OpenClaw):

| Layer | Mechanism | Trigger |
|-------|-----------|---------|
| **Core** | `registerContextEngine("cam")` | Framework auto-calls `ingest()` + `assemble()` per message |
| **Tool** | `cam_query` / `cam_stats` / `cam_ingest` / `cam_extract_file` | Agent calls on demand |
| **Hook** | `before_prompt_build` / `llm_output` | Event-driven (file detection, prompt injection) |

## Project Structure

```
cam/
├── cam_daemon/          ⭐ Core — FastAPI daemon (extract / dedupe / store / recall)
│   ├── server.py        POST /hook, GET /query, /stats, /health, /ingest
│   ├── client.py        Lightweight Python SDK + AutoRemember decorator
│   ├── config.py        LLM provider, port, throttle settings
│   └── daemon.py        PID file, graceful shutdown, lifecycle
├── plugins/
│   └── openclaw/index.ts  OpenClaw plugin (v4: ContextEngine + Tool + Hook)
├── memory_core/
│   ├── extractor.py      LLM-powered fact extraction
│   ├── deduplicator.py   Similarity-based dedup
│   └── shared_wiki.py    Atomic Markdown write with merge
├── cam/                  CLI (`cam init`, `cam daemon start/stop/status`)
└── wiki/                 Output: structured Markdown pages
    ├── entity/           Facts about people, projects, decisions
    └── synthesis/        Synthesized conclusions & comparisons
```

## Quick Start

### 1. Install & Init

```bash
pip install cam
cam init --dir ~/my-wiki          # creates wiki/ directory
```

### 2. Start Daemon

```bash
cam daemon start                    # starts FastAPI on :9877
cam daemon status                   # check if running
curl http://localhost:9877/health   # {"status":"healthy"}
```

### 3. Use with OpenClaw (recommended)

Install the plugin — it registers as a **ContextEngine**, so every message is automatically captured and recalled:

```bash
openclaw plugin install /path/to/plugins/openclaw
openclaw gateway restart            # done! zero config needed
```

### 4. Or use from any code (3 lines)

```python
from cam_daemon.client import CamClient, AutoRemember
client = CamClient()                # connects to localhost:9877
auto = AutoRemember(agent_id="my-agent")

# After every message exchange:
await auto(user_message, reply)     # extracts facts → stores in wiki
results = await client.query("project architecture")  # recalls relevant context
```

## Tools Available to Agents

| Tool | What It Does |
|------|-------------|
| `cam_query` | Search the knowledge base |
| `cam_stats` | View stats (facts, pages, health) |
| `cam_ingest` | Manually store content |
| `cam_extract_file` | **File/image/doc → LLM extract → Wiki** |

## Config

Set environment variables or edit `wiki/.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `CAM_LLM_PROVIDER` | `openai` | LLM provider for extraction |
| `CAM_LLM_MODEL` | `gpt-4o-mini` | Model used for fact extraction |
| `CAM_DAEMON_PORT` | `9877` | Daemon listen port |
| `OPENAI_API_KEY` | *(none)* | Required for LLM extraction (or set your own) |
| `CAM_PROJECT_DIR` | `./wiki` | Wiki output directory |

**No API key?** CAM falls back to heuristic extraction (pattern matching, no LLM needed).

## FAQ

**Q: Database?**
No. Pure Markdown files — human-readable, git-friendly, works with Obsidian.

**Q: Offline?**
Yes. Use local models via Ollama/Qwen + `CAM_LLM_BASE_URL=http://localhost:11434`.

**Q: RAG vs CAM?**
RAG = slice raw docs → retrieve → re-synthesize each time (ephemeral).
CAM = extract once → structure into Wiki → keep improving forever (compounding).

**Q: Hallucinations?**
Four guards: source traceability, periodic LINT audit, incremental imports, uncertainty markers.

---

MIT © 2026 CAM Contributors · [Issues](https://github.com/canyonqian/cam/issues) · [PRs Welcome](https://github.com/canyonqian/cam/pulls)
