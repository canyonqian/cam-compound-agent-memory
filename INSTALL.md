# CAM — Installation Guide

Zero-config. Uses Host Agent's LLM. No separate API key needed.

---

## 1. Prerequisites

```bash
# Python 3.10+ required
pip install mcp[cli]
pip install -r requirements.txt
```

Or install as a package (once published):

```bash
pip install cam
```

---

## 2. Platform-Specific Setup

### Claude Desktop / Claude Code

Add to your MCP config:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**Linux:** `~/.claude.json` (Claude Code)

```json
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "plugins.mcp_server"],
      "env": { "CAM_PROJECT_DIR": "/path/to/your/wiki" }
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "plugins.mcp_server"],
      "env": { "CAM_PROJECT_DIR": "${workspaceFolder}" }
    }
  }
}
```

### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json` or VS Code settings:

```json
{
  "github.copilot.mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "plugins.mcp_server"],
      "env": { "CAM_PROJECT_DIR": "${workspaceFolder}" }
    }
  }
}
```

### Windsurf

Add to `.windsurf/mcp.json`:

```json
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "plugins.mcp_server"],
      "env": { "CAM_PROJECT_DIR": "${workspaceFolder}" }
    }
  }
}
```

### OpenClaw

OpenClaw uses a **native plugin system** (not MCP). Installation is a two-step process:

#### Step 1: Clone the repo and install dependencies

```bash
# Clone to a permanent location
git clone https://github.com/canyonqian/cam-compound-agent-memory.git ~/cam
cd ~/cam
pip install mcp[cli] -r requirements.txt
```

#### Step 2: Register the plugin with OpenClaw

```bash
# Enable the plugin (OpenClaw CLI handles config registration)
openclaw plugins enable cam --source path --source-path ~/cam/plugins/openclaw

# Restart the gateway to apply
openclaw gateway restart
```

#### Verify

```bash
openclaw plugins list | grep cam
# Should show: │ CAM │ cam │ loaded │ ... │ 3.0.0 │
```

#### Plugin Configuration (optional)

The plugin works out of the box with defaults. To customize, edit `~/.openclaw/openclaw.json`:

```json
{
  "plugins": {
    "entries": {
      "cam": {
        "enabled": true,
        "config": {
          "wikiPath": "/path/to/your/wiki",
          "injectOnPrompt": true,
          "extractOnOutput": true
        }
      }
    }
  }
}
```

| Config Key | Default | Description |
|------------|---------|-------------|
| `wikiPath` | `~/cam` | Path to CAM project root |
| `injectOnPrompt` | `true` | Auto-inject wiki context into system prompt |
| `extractOnOutput` | `true` | Auto-extract knowledge from AI responses |

### Cody / JetBrains

Add to `.cody/mcp.json` or JetBrains MCP settings:

```json
{
  "mcpServers": {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "plugins.mcp_server"],
      "env": { "CAM_PROJECT_DIR": "${projectRoot}" }
    }
  }
}
```

### Generic MCP Client (any tool)

```bash
# Start as stdio server (default)
python -m plugins.mcp_server

# Start as SSE server (for remote connections)
python -m plugins.mcp_server sse
# → Connect to http://localhost:8765/sse
```

---

## 3. How It Works (No API Key Needed!)

```
┌─────────────────────────────────────────────────────┐
│                   Your AI Agent                      │
│            (Claude/GPT/Any LLM)                     │
│                                                      │
│  User: "Read this article about RAG"                │
│       ↓                                             │
│  Agent calls: cam_ingest(content="...")             │
│       ↓                                             │
│  ┌─────────────────────────────────┐               │
│  │   CAM MCP Server               │               │
│  │                                 │               │
│  │  1. Saves content → raw/        │               │
│  │  2. Returns EXTRACTION PROMPT   │ ← No API call! │
│  │  ─────────────────────────────  │               │
│  │  3. Agent uses ITS OWN brain     │               │
│  │     to extract knowledge         │               │
│  │  4. Agent calls cam_write_pages()│              │
│  │  5. Wiki updated! ✅             │               │
│  └─────────────────────────────────┘               │
│                                                      │
└─────────────────────────────────────────────────────┘
```

**The plugin is pure orchestration + storage.**
**The Agent provides ALL intelligence. Zero extra cost.**

---

## 4. Available Tools

| Tool | What It Does |
|------|-------------|
| `cam_ingest` | Learn from any content (articles, notes, code, conversations) |
| `cam_write_pages` | Save extracted wiki pages to the knowledge base |
| `cam_update_index` | Refresh the global wiki index |
| `cam_query` | Search and retrieve stored knowledge |
| `cam_stats` | View wiki statistics and health score |
| `cam_lint` | Run quality check on the entire wiki |

---

## 5. Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: mcp` | Run `pip install mcp[cli]` |
| `CAM_PROJECT_DIR` not set | Set env var or use default (plugin parent dir) |
| Wiki directory empty after ingest | The Agent needs to follow the extraction prompt and call `cam_write_pages` |
| Pages not linking correctly | Make sure Agent uses `[[]]` format for internal links |
| **OpenClaw:** `source: Invalid input` | Must use `openclaw plugins enable` CLI, not manual config edit. Allowed sources: `npm`, `archive`, `path`, `clawhub`, `marketplace` |
| **OpenClaw:** `plugin disabled (not in allowlist)` | Run `openclaw plugins enable cam --source path --source-path <path>` to register |

---

*CAM v3 — Universal AI Memory Plugin*
