"""Logseq graph adapter (optional)."""

import logging
from pathlib import Path
from typing import Any, Dict

from .base import BaseAdapter

logger = logging.getLogger("cw-adapter-logseq")


class LogseqAdapter(BaseAdapter):
    """Export Wiki content to Logseq journal/graph format."""

    @property
    def adapter_name(self) -> str:
        return "logseq"

    @property
    def display_name(self) -> str:
        return "Logseq Graph"

    async def sync_all(self, wiki_dir: Path) -> Dict[str, Any]:
        """Generate Logseq-compatible pages in a logseq/ subdirectory."""
        logseq_dir = wiki_dir.parent / "logseq"
        logseq_dir.mkdir(parents=True, exist_ok=True)
        
        count = 0
        for md_file in sorted(wiki_dir.rglob("*.md")):
            if md_file.name in ("index.md", "changelog.md"):
                continue
            
            content = md_file.read_text(encoding="utf-8")
            
            # Convert [[]] to Logseq [[page]] format (already compatible)
            # Add Logseq frontmatter
            logseq_content = f"- CAM page\n- tags: [[wiki]]\n\n{content}"
            
            out_path = logseq_dir / md_file.relative_to(wiki_dir)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(logseq_content, encoding="utf-8")
            count += 1
        
        return {"status": "ok", "adapter": "logseq", "pages_exported": count}

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok", "adapter": "logseq"}
