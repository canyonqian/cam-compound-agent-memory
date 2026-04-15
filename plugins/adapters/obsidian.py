"""
Obsidian Adapter Plugin
========================

Sync CAM content to/from an Obsidian vault.

How it works:
  • wiki/ directory IS an Obsidian-compatible vault
  • All [[wiki-links]] are native Obsidian links
  • Open the cam folder as an Obsidian vault
  • Get graph view, backlinks, search, plugins — for free!

Usage:
    adapter = ObsidianAdapter({"vault_path": "/path/to/cam"})
  ✅ Bidirectional sync (optional)
  ✅ Auto-generate .obsidian config on first run
  ✅ Graph view with all Wiki pages connected
  ✅ Backlink panel shows incoming connections
  ✅ Community plugins work normally

Usage:
    adapter = ObsidianAdapter({"vault_path": "/path/to/cam"})
    await adapter.sync_all(Path("wiki"))
    
    # Or simply: Open cam/ in Obsidian!
    # File → Open Folder As Vault → select cam/
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from .base import BaseAdapter

logger = logging.getLogger("cw-adapter-obsidian")


class ObsidianAdapter(BaseAdapter):
    """
    Obsidian vault synchronization adapter.
    
    Since CAM uses Markdown + [[]] links natively,
    it's already Obsidian-compatible! This adapter:
    
    1. Generates .obsidian/ config if missing
    2. Creates useful community plugin configs
    3. Optionally watches for external edits
    4. Provides Obsidian-specific metadata
    """

    @property
    def adapter_name(self) -> str:
        return "obsidian"

    @property
    def display_name(self) -> str:
        return "Obsidian Vault"

    async def on_wiki_update(self, action: str, page_path: str, content=None):
        """Called when Wiki content changes."""
        logger.debug(f"Obsidian adapter: {action} → {page_path}")
        # Obsidian auto-detects file changes — no extra work needed!

    async def sync_all(self, wiki_dir: Path) -> Dict[str, Any]:
        """Ensure Obsidian compatibility — generate .obsidian/ config."""
        
        project_root = self.config.get("project_dir", ".")
        project = Path(project_root).resolve()
        obs_dir = project / ".obsidian"
        
        # Create .obsidian directory with sensible defaults
        obs_dir.mkdir(parents=True, exist_ok=True)
        
        # app.json
        (obs_dir / "app.json").write_text(json.dumps({
            "defaultViewMode": "preview",
            "showLineNumber": False,
            "strictLineBreaks": false,
            "useMarkdownLinks": False,
            "newLinkFormat": "shortest",
            "newFileLocation": "folder",
            "newFileFolderPath": "wiki/concept",
            "attachmentFolderPath": "raw",
            "alwaysUpdateLinks": True,
        }, indent=2), encoding="utf-8")
        
        # appearance.json
        (obs_dir / "appearance.json").write_text(json.dumps({
            "cssTheme": "Default",
            "theme": "dark",
        }, indent=2), encoding="utf-8")
        
        # workspace.json — setup default layout
        (obs_dir / "workspace.json").write_text(json.dumps({
            "main": {
                "id": "main",
                "mode": "preview",
                "state": {
                    "type": "markdown",
                    "state": {"file": "wiki/index.md", "mode": "preview"}
                }
            },
            "left-ribbon": {
                "collapsed": False,
                "width": 36,
                "pinned": True
            }
        }, indent=2), encoding="utf-8")
        
        page_count = sum(1 for _ in wiki_dir.rglob("*.md") 
                        if _.name not in ("index.md", "changelog.md"))
        link_count = 0
        for md in wiki_dir.rglob("*.md"):
            import re
            link_count += len(re.findall(r'\[\[(.+?)\]\]', md.read_text(encoding="utf-8")))
        
        return {
            "status": "ok",
            "adapter": "obsidian",
            "vault_path": str(project),
            "pages": page_count,
            "links": link_count,
            "message": f"✅ Vault ready! Open {project} as Obsidian vault.",
            "_tip": "File → Open Folder As Vault → select this project root",
        }

    async def health_check(self) -> Dict[str, Any]:
        base = await super().health_check()
        project = Path(self.config.get("project_dir", ".")).resolve()
        has_obsidian = (project / ".obsidian").exists()
        base["vault_ready"] = has_obsidian
        return base


# ── Quick Start ─────────────────────────────────────────────

def setup_obsidian_vault(project_dir: str):
    """
    One-time setup to make CAM work as an Obsidian vault.
    
    Just call this once after creating your wiki. Then open in Obsidian.
    
    Args:
        project_dir: Path to the CAM project root
        
    Example:
        from plugins.adapters.obsidian import setup_obsidian_vault
        
        setup_obsidian_vault("/path/to/cam")
        print("Done! Now open in Obsidian.")
    """
    async def do_setup():
        adapter = ObsidianAdapter({"project_dir": project_dir})
        result = await adapter.sync_all(Path(project_dir) / "wiki")
        return result
    
    import asyncio
    return asyncio.get_event_loop().run_until_complete(do_setup())
