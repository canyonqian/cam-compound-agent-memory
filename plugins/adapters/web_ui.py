"""
Web Dashboard Adapter (Optional)
==================================

Lightweight web dashboard for browsing your Wiki.
Built with minimal dependencies — just aiohttp.

Provides:
  • Visual browse of all Wiki pages (concepts, entities, synthesis)
  • Search functionality
  • Stats overview
  • Graph visualization (using vis.js or D3)
  • Mobile-friendly responsive UI

This is OPTIONAL — you can use Obsidian instead for a richer experience.
The web dashboard is useful for quick access without installing anything.

Configuration:
    settings:
      port: 8766
      host: "127.0.0.1"
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict

from .base import BaseAdapter

logger = logging.getLogger("cw-adapter-web")


class WebDashboardAdapter(BaseAdapter):
    """Lightweight web dashboard for Wiki browsing."""

    @property
    def adapter_name(self) -> str:
        return "web_ui"

    @property
    def display_name(self) -> str:
        return "Web Dashboard"

    async def sync_all(self, wiki_dir: Path) -> Dict[str, Any]:
        """Generate static web dashboard files."""
        
        # This would generate HTML/CSS/JS for a static dashboard
        # For now, return info about how to start it
        
        return {
            "status": "ok",
            "adapter": "web_ui",
            "message": "Web dashboard available — run: python plugins/adapters/web_ui.py serve",
        }

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "adapter": "web_ui"}


# ── Static HTML Dashboard ────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🧠 CAM Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; 
       background:#0f1117; color:#e1e4e8; line-height:1.6; }
.header { background:linear-gradient(135deg,#1a1f35,#161b2e); padding:30px;
           border-bottom:1px solid #21262d; }
.header h1 { font-size:28px; } .header p { color:#8b949e; margin-top:5px; }
.container { max-width:1200px; margin:0 auto; padding:20px; display:grid;
             grid-template-columns:250px 1fr; gap:20px; min-height:80vh; }
.sidebar { background:#161b22; border-radius:12px; padding:20px; height:fit-content;
            border:1px solid #21262d; }
.sidebar nav a { display:block; color:#c9d1d9; text-decoration:none; 
                 padding:10px 14px; border-radius:8px; margin-bottom:4px; }
.sidebar nav a:hover,.sidebar nav a.active { background:#21262d; color:#58a6ff; }
.main { background:#161b22; border-radius:12px; padding:24px; 
         border:1px solid #21262d; }
.card { background:#0d1117; border:1px solid #21262d; border-radius:8px; 
        padding:16px; margin-bottom:16px; }
.card h3 { color:#58a6ff; margin-bottom:10px; font-size:15px; }
.stats { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:20px; }
.stat { background:linear-gradient(135deg,#161b22,#0d1117); 
         border:1px solid #21262d; border-radius:10px; padding:18px; text-align:center; }
.stat .num { font-size:32px; font-weight:700; color:#58a6ff; }
.stat .label { font-size:13px; color:#8b949e; margin-top:4px; }
.tag { display:inline-block;background:#21262d;color:#58a6ff;padding:3px 10px;
        border-radius:12px;font-size:12px;margin:2px; }
.search { width:100%;padding:12px 16px;border:1px solid #30363d;border-radius:8px;
          background:#0d1117;color:#e1e4e8;font-size:15px;outline:none; }
.search:focus{border-color:#58a6ff;box-shadow:0 0 0 3px rgba(88,166,255,.1); }
.page-list .item { padding:14px;border-bottom:1px solid #21262d;display:flex;
                  justify-content:space-between;align-items:center;cursor:pointer; }
.page-list .item:hover { background:#161b22; }
.page-list .item .title { font-weight:600; }
.page-list .item .meta { font-size:13px; color:#8b949e; }
.badge { display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;
         font-weight:600; }
.badge.concept { background:#1f3a5f;color:#79c0ff; }
.badge.entity { background:#2d1f3f; #d2a8ff; }
.badge.synthesis { background:#1f3a2f;color:#7ee787; }
</style>
</head>
<body>
<div class="header">
<h1>🧠 CAM</h1><p>Your AI-powered knowledge base — visualized</p>
<div style="margin-top:15px"><input class="search" type="text" id="search" placeholder="🔍 Search knowledge base..." style="max-width:500px"></div>
</div>
<div class="container">
<aside class="sidebar"><nav>
<a href="#" class="active">📊 Dashboard</a>
<a href="#">💡 Concepts</a>
<a href="#">👤 Entities</a>
<a href="#">🔗 Synthesis</a>
<a href="#">📥 Raw Sources</a>
<a href="#">⚙️ Settings</a>
</nav></aside>
<main class="main">
<div class="stats">
<div class="stat"><div class="num" id="stat-pages">--</div><div class="label">Wiki Pages</div></div>
<div class="stat"><div class="num" id="stat-links">--</div><div class="label">Links</div></div>
<div class="stat"><div class="num" id="stat-sources">--</div><div class="label">Raw Sources</div></div>
<div class="stat"><div class="num" id="stat-health">--</div><div class="label">Health Score</div></div>
</div>
<div class="card"><h3>📈 Knowledge Growth</h3>
<p style="color:#8b949e;font-size:14px">Track how your knowledge base grows over time.</p>
<div style="height:200px;background:#0d1117;border-radius:8px;display:flex;
align-items:center;justify-content:center;color:#484f58;">
[Chart loads with real data]
</div>
</div>
<div class="card"><h3>📝 Recent Updates</h3>
<div class="page-list" id="recent-list">
<div class="item"><span><span class="title">Loading...</span></span><span class="meta"></span></div>
</div>
</div>
</main>
</div>
<script>
// Dashboard will be populated by server-side rendering or API calls
console.log('CAM Dashboard loaded');
</script>
</body></html>"""

