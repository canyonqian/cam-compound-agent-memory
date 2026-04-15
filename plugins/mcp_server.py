"""
Compound Wiki MCP Server v2
============================

Zero-config, universal AI memory plugin for ANY Agent.

KEY DESIGN PRINCIPLE: NO SEPARATE API KEY NEEDED.
The Hosting Agent provides ALL intelligence via its own LLM capability.
This plugin is pure orchestration + storage.

Works with:
  - Claude Desktop / Claude Code  (native MCP)
  - Cursor                        (native MCP)
  - GitHub Copilot                (native MCP)
  - Windsurf / Cody               (native MCP)
  - OpenClaw                      (via webhook bridge)
  - Any MCP-compatible tool

INSTALLATION (one line per platform):
  See INSTALL.md or README.md for platform-specific instructions

HOW IT WORKS:
  1. Agent calls cw_ingest("some content")
  2. Plugin saves content to raw/ (immutable source record)  
  3. Plugin returns a STRUCTURED EXTRACTION PROMPT to the Agent
  4. The Agent uses its OWN brain to extract knowledge (no extra API call!)
  5. Agent writes extracted knowledge back via cw_write_pages()
  6. Plugin updates index, links, and state
  
This is the "Agent-Native" pattern — zero cost, zero config, maximum quality.
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# ── Resolve paths ──────────────────────────────────────────────
PLUGIN_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = PLUGIN_DIR.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from mcp.server import Server
    from mcp.types import (
        Tool, TextContent,
        CallToolResult, ListToolsResult,
    )
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("cw-mcp")

server = Server("compound-wiki")


# ══════════════════════════════════════════════════════════════
# PATH RESOLUTION
# ══════════════════════════════════════════════════════════════

def _resolve_paths() -> Dict[str, Path]:
    """Resolve all critical directory paths from env or defaults."""
    project_dir = Path(os.environ.get(
        "CW_PROJECT_DIR", str(PROJECT_ROOT)
    )).resolve()

    dirs = {
        "project": project_dir,
        "raw": project_dir / "raw",
        "wiki": project_dir / "wiki",
        "schema": project_dir / "schema",
        "outputs": project_dir / "outputs",
        "state": project_dir / "auto" / "state",
    }
    
    # Auto-detect compound_wiki package location (pip installed)
    pkg_candidates = [
        PROJECT_ROOT / "compound_wiki",
        project_dir / "compound_wiki",
    ]
    for candidate in pkg_candidates:
        if candidate.exists():
            dirs["package"] = candidate
            break
    
    # Fallback: try site-packages
    if "package" not in dirs:
        try:
            import compound_wiki as pkg_module
            dirs["package"] = Path(pkg_module.__file__).parent
        except ImportError:
            pass
    
    return dirs


def _ensure_dirs(paths: Dict[str, Path]) -> None:
    """Create all required directories."""
    for key in ["raw", "wiki", "schema", "outputs", "state"]:
        p = paths.get(key)
        if p and not p.exists():
            p.mkdir(parents=True, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# SCHEMA & RULES LOADER
# ══════════════════════════════════════════════════════════════

def _load_rules() -> str:
    """Load CLAUDE.md rules file."""
    paths = _resolve_paths()
    candidates = [
        paths["schema"] / "CLAUDE.md",
        paths["project"] / "schema" / "CLAUDE.md",
        paths["schema"] / "AGENTS.md",
    ]
    for c in candidates:
        if c.exists():
            text = c.read_text(encoding="utf-8")
            logger.info(f"📋 Loaded rules from {c.name} ({len(text)} chars)")
            return text
    
    # Built-in default rules (no external file needed)
    return _DEFAULT_RULES


_DEFAULT_RULES = """You are Compound Wiki's Knowledge Engineer. Your job is to convert raw content into structured, linked Markdown wiki pages that COMPOUND over time.

## CORE RULES
1. Each DISTINCT topic/concept/entity gets its own .md file
2. Use [[double-bracket]] format for ALL internal wiki links (bidirectional!)
3. Start each page with a clear summary paragraph
4. Include source citations for every factual claim
5. Mark confidence levels for uncertain information
6. Think about how new content CONNECTS to existing pages

## PAGE TYPES & LOCATIONS
- **Concepts**: Technical concepts, patterns, methodologies → `wiki/concept/name.md`
- **Entities**: People, projects, organizations, tools → `wiki/entity/name.md`
- **Synthesis**: Q&A summaries, cross-topic analysis → `wiki/synthesis/name.md`

## OUTPUT FORMAT
For each page you create, output:
### FILENAME: wiki/<type>/<slug>.md
# Title

> **Source**: <source_file>
> **Confidence**: ★★★★☆ (1-5 stars)
> **Last Updated**: <date>

Summary paragraph (2-3 sentences).

## Key Points
- Point 1
- Point 2

## Related Concepts
- [[related-topic]]
- [[another-topic]]

---
*Auto-generated by Compound Wiki*

## QUALITY STANDARDS
- Minimum 100 characters of actual content per page
- At least 2 outgoing [[links]] per page
- Every claim needs a source or confidence marker
- No orphaned pages — always link TO and FROM existing content"""


# ══════════════════════════════════════════════════════════════
# STORAGE OPERATIONS (pure filesystem, no LLM needed)
# ══════════════════════════════════════════════════════════════

def _save_raw(content: str, title: str, url: str, 
              tags: List[str], content_type: str, paths: Dict[str, Path]) -> str:
    """
    Save raw content to raw/ directory.
    
    Returns the relative path of saved file.
    """
    raw_dir = paths["raw"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate filename
    safe_title = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '-', title or 'untitled')[:60]
    timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    hash_suffix = hashlib.md5(content.encode()[:500].strip()).hexdigest()[:8]
    filename = f"{timestamp}-{safe_title.rstrip('-')}-{hash_suffix}.md"
    filepath = raw_dir / filename
    
    # Build raw file with metadata header
    meta_lines = [
        "---",
        f"title: {title or 'Untitled'}",
        f"source: mcp_agent",
        f"source_type: {content_type}",
        f"url: {url or 'N/A'}",
        f"tags: {', '.join(tags) if tags else 'none'}",
        f"ingested_at: {datetime.now().isoformat()}",
        f"chars: {len(content)}",
        "---",
        "",
        f"# {title or 'Untitled'}",
        "",
        content,
    ]
    filepath.write_text("\n".join(meta_lines), encoding="utf-8")
    
    logger.info(f"💾 Saved raw: {filename} ({len(content)} chars)")
    return str(filepath.relative_to(paths["project"]))


def _save_page(filename: str, content: str, paths: Dict[str, Path]) -> Dict[str, Any]:
    """
    Save a wiki page with merge semantics (dedup before write).
    
    If the page already exists and new content contains fact blocks,
    only append blocks that don't already exist (similarity < 0.85).
    For non-fact content or completely new files, use normal behavior.
    """
    import difflib
    
    wiki_dir = paths["wiki"]
    filepath = wiki_dir / filename
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    is_new = not filepath.exists()
    
    if not is_new:
        # --- Merge mode: deduplicate fact blocks ---
        existing = filepath.read_text(encoding="utf-8")
        
        # Check if both old and new content look like fact-based wiki pages
        if "---" in existing and "---" in content:
            existing_blocks = [b.strip() for b in existing.split("---") if b.strip() and len(b.strip()) > 20]
            new_blocks = [b.strip() for b in content.split("---") if b.strip() and len(b.strip()) > 20]
            
            # Extract core content lines for comparison
            def _core_line(block: str) -> str:
                for line in block.split("\n"):
                    l = line.strip()
                    if l and not any(l.startswith(p) for p in [
                        "🎯", "📌", "💡", "✅", "📋", "🏷️",
                        "*Source*", "*Tags*", "*Entities*",
                        "Confidence", "# "
                    ]):
                        return l
                return ""
            
            deduped_new_blocks = []
            for nb in new_blocks:
                nb_core = _core_line(nb)
                if not nb_core:
                    deduped_new_blocks.append(nb)
                    continue
                    
                is_dup = False
                for eb in existing_blocks:
                    eb_core = _core_line(eb)
                    if not eb_core:
                        continue
                    if nb_core == eb_core:
                        is_dup = True
                        break
                    ratio = difflib.SequenceMatcher(None, nb_core, eb_core).ratio()
                    if ratio >= 0.85:
                        logger.debug(f"  _save_page: skipping duplicate block "
                                   f"(ratio={ratio:.2f})")
                        is_dup = True
                        break
                
                if not is_dup:
                    deduped_new_blocks.append(nb)
            
            if len(deduped_new_blocks) < len(new_blocks):
                logger.info(f"  📄 MERGE: {filename} — "
                           f"deduplicated {len(new_blocks) - len(deduped_new_blocks)} blocks")
            
            # Rebuild content with deduplicated new blocks appended
            if deduped_new_blocks:
                merged_content = existing.rstrip().rstrip("---").rstrip() + "\n"
                for block in deduped_new_blocks:
                    merged_content += f"\n{block}\n---\n"
                content = merged_content
    
    filepath.write_text(content, encoding="utf-8")
    
    rel_path = str(filepath.relative_to(wiki_dir))
    action = "CREATED" if is_new else ("MERGED" if not is_new and "---" in content else "UPDATED")
    
    # Auto-update index when a page is written
    try:
        _update_index(paths)
        logger.debug(f"  📋 Index updated after writing {rel_path}")
    except Exception as e:
        logger.debug(f"  ⚠️ Failed to update index: {e}")
    
    logger.info(f"  📄 {action}: {rel_path}")
    
    return {
        "path": rel_path,
        "action": action.lower(),
        "size_bytes": len(content),
    }


def _update_index(paths: Dict[str, Path]) -> str:
    """
    Update global INDEX.md with current state of wiki/.
    Returns index content summary.
    """
    wiki_dir = paths["wiki"]
    index_path = wiki_dir / "index.md"
    
    all_pages = sorted(wiki_dir.rglob("*.md"))
    all_pages = [p for p in all_pages if p.name not in ("index.md", "changelog.md")]
    
    lines = ["# Compound Wiki — Global Index\n"]
    lines.append(f"> Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"> Total pages: {len(all_pages)}\n")
    
    by_dir: Dict[str, List[Path]] = {}
    for p in all_pages:
        parent = p.parent.name
        if parent not in ("concept", "entity", "synthesis"):
            parent = "other"
        by_dir.setdefault(parent, []).append(p)
    
    dir_emoji = {"concept": "💡", "entity": "🏷️", "synthesis": "🔗", "other": "📁"}
    dir_label = {"concept": "Concepts", "entity": "Entities", "synthesis": "Synthesis", "other": "Other"}
    
    for dir_name in ("concept", "entity", "synthesis", "other"):
        if dir_name not in by_dir:
            continue
        lines.append(f"\n### {dir_emoji.get(dir_name,'')} {dir_label.get(dir_name,dir_name)} ({len(by_dir[dir_name])})\n")
        lines.append("| Page | Path |")
        lines.append("|------|------|")
        for p in sorted(by_dir[dir_name], key=lambda x: x.stem):
            rel_path = str(p.relative_to(wiki_dir))
            title = p.stem.replace("-", " ").title()
            lines.append(f"| [[{title}]] | `{rel_path}` |")
    
    index_path.write_text("\n".join(lines), encoding="utf-8")
    
    return f"Index updated: {len(all_pages)} pages across {len(by_dir)} sections"


def _count_files(directory: Path, pattern: str = "*.md") -> int:
    if not directory.exists():
        return 0
    return len(list(directory.rglob(pattern)))


# ══════════════════════════════════════════════════════════════
# SEARCH / QUERY ENGINE (keyword-based, no external dependency)
# ══════════════════════════════════════════════════════════════

def _search_wiki(query: str, scope: str = "all", max_results: int = 10,
                 include_content: bool = True, paths: Dict[str, Path] = None) -> Dict:
    """Search wiki for relevant pages. Returns structured results."""
    if paths is None:
        paths = _resolve_paths()
    
    wiki_dir = paths["wiki"]
    if not wiki_dir.exists():
        return {"results": [], "total": 0, "scanned": 0}
    
    query_lower = query.lower()
    query_words = set(re.findall(r'\b\w{2,}\b', query_lower))
    
    search_dirs = []
    if scope in ("all", "concepts"):
        search_dirs.append(("Concepts", wiki_dir / "concept"))
    if scope in ("all", "entities"):
        search_dirs.append(("Entities", wiki_dir / "entity"))
    if scope in ("all", "synthesis"):
        search_dirs.append(("Synthesis", wiki_dir / "synthesis"))
    
    results = []
    scanned = 0
    
    for dir_name, dir_path in search_dirs:
        if not dir_path.exists():
            continue
        
        for md_file in sorted(dir_path.rglob("*.md"), 
                               key=lambda p: p.stat().st_mtime, reverse=True):
            if scanned >= max_results * 5:
                break
            
            try:
                text = md_file.read_text(encoding="utf-8")
                
                score = 0
                if query_lower in md_file.stem.lower():
                    score += 10
                score += text.lower().count(query_lower) * 1
                content_words = set(text.lower().split())
                score += len(query_words & content_words) * 3
                
                if score > 0:
                    rel_path = str(md_file.relative_to(wiki_dir))
                    results.append({
                        "page": rel_path,
                        "section": dir_name,
                        "score": round(score, 1),
                        "preview": text[:400].replace("\n", " ").strip(),
                        "full_content": text if include_content else "[hidden]",
                        "modified": datetime.fromtimestamp(
                            md_file.stat().st_mtime
                        ).isoformat(),
                    })
                
                scanned += 1
            except Exception:
                continue
    
    results.sort(key=lambda r: r["score"], reverse=True)
    return {
        "results": results[:max_results],
        "total": len(results),
        "scanned": scanned,
    }


def _get_stats(paths: Dict[str, Path] = None) -> Dict:
    """Get comprehensive wiki statistics."""
    if paths is None:
        paths = _resolve_paths()
    
    wiki_dir = paths["wiki"]
    raw_dir = paths["raw"]
    
    stats = {
        "raw_files": _count_files(raw_dir),
        "concepts": _count_files(wiki_dir / "concept"),
        "entities": _count_files(wiki_dir / "entity"),
        "synthesis": _count_files(wiki_dir / "synthesis"),
        "wiki_total": _count_files(wiki_dir),
    }
    stats["total"] = (
        stats["concepts"] + stats["entities"] + stats["synthesis"]
    )
    
    # Link density
    total_links = 0
    total_size = 0
    for md in wiki_dir.rglob("*.md"):
        if md.name in ("index.md", "changelog.md"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
            total_links += len(re.findall(r'\[\[(.+?)\]\]', text))
            total_size += len(text)
        except Exception:
            pass
    
    valid_pages = max(stats["total"] - 2, 1)
    stats["avg_links"] = round(total_links / valid_pages, 1)
    stats["total_chars"] = total_size
    
    # Health score calculation
    issues = 0
    if stats["avg_links"] < 2: issues += 1
    if stats["concepts"] == 0 and stats["raw_files"] > 0: issues += 1
    if stats["total_chars"] < 1000 and stats["total"] > 0: issues += 1
    stats["health_score"] = max(0, 100 - issues * 15)
    
    return stats


# ══════════════════════════════════════════════════════════════
# THE EXTRACTION PROMPT GENERATOR
# ══════════════════════════════════════════════════════════════
# This is the MAGIC — we tell the Host Agent what to extract.
# The Agent uses its own LLM brain. Zero extra API call.

def _build_extraction_prompt(raw_filename: str, content: str,
                            title: str, rules_text: str,
                            paths: Dict[str, Path]) -> str:
    """
    Build the Agent-Native extraction prompt.
    
    This prompt is returned to the calling Agent.
    The Agent will execute it using its OWN LLM capability.
    No separate API key needed!
    """
    
    # Get context about existing wiki pages
    existing_context = ""
    wiki_dir = paths["wiki"]
    if wiki_dir.exists():
        existing_pages = list(wiki_dir.rglob("*.md"))
        existing_pages = [p for p in existing_pages 
                         if p.name not in ("index.md", "changelog.md")]
        
        if existing_pages:
            # Show up to 20 existing page titles for link reference
            titles = []
            for p in sorted(existing_pages)[:20]:
                rel = str(p.relative_to(wiki_dir))
                stem = p.stem.replace("-", " ").title()
                titles.append(f"  - [[{stem}]] ({rel})")
            
            existing_context = f"""
## EXISTING WIKI KNOWLEDGE ({len(existing_pages)} pages)
These pages already exist. LINK to them when relevant:

{chr(10).join(titles)}
"""
    
    # Truncate very long content
    max_input = 60000
    display_content = content
    if len(content) > max_input:
        display_content = content[:max_input] + (
            f"\n\n... [TRUNCATED — original was {len(content):,} chars]"
        )
    
    prompt = f"""## 🧠 COMPOUND WIKI — EXTRACTION TASK

You are the **Knowledge Extraction Engine** for this Wiki. Your task is to analyze the following raw content and produce structured wiki pages.

---

### SOURCE MATERIAL
**File:** `{raw_filename}`
**Title:** {title}
**Size:** {len(content):,} characters

{display_content}

---

### YOUR RULES
{rules_text}
{existing_context}

---

### 🔧 WHAT YOU MUST DO NOW

**Step 1: Analyze**
Read the source material above. Identify:
- Core concepts worth remembering long-term
- Named entities (people, projects, tools, orgs)
- Key decisions or preferences stated
- Relationships between topics
- Facts that should be cited

**Step 2: Create/Update Wiki Pages**
For EACH distinct topic you found, create a wiki page. Use cw_write_pages tool to save them.

Format each page according to the RULES above. Make sure to include:
- FILENAME header (wiki/concept/, wiki/entity/, or wiki/synthesis/)
- Summary paragraph
- ## Key Points section
- ## Related Concepts with [[]] links to BOTH new AND existing pages
- Source citation
- Confidence rating

**Step 3: Update Index**
After writing all pages, call the cw_update_index tool.

---

### ✅ QUALITY CHECKLIST
- [ ] Each topic has its OWN page (not crammed together)
- [ ] All internal links use [[]] format
- [ ] Links are BIDIRECTIONAL (if A links to B, B links to A)
- [ ] Source citations included
- [ ] Connected to EXISTING wiki pages where relevant
- [ ] Minimum ~150 useful characters per page

Start extracting now! 🚀"""

    return prompt


# ══════════════════════════════════════════════════════════════
# TOOL DEFINITIONS
# ══════════════════════════════════════════════════════════════

TOOLS = [
    Tool(
        name="cw_ingest",
        description="""⭐ PRIMARY TOOL: Ingest content into Compound Wiki — FULLY AUTOMATIC, no API key needed!

HOW IT WORKS:
  1. Content is saved to raw/ (immutable source record)
  2. You receive an EXTRACTION PROMPT — follow it using your OWN intelligence
  3. Extract knowledge → create wiki pages → update index
  4. Done! Knowledge is permanently stored and linked

WHAT TO INGEST:
  • Articles, papers, research findings
  • Notes, thoughts, ideas
  • Code documentation
  • Conversation transcripts
  • Web page content (paste the text)
  • ANYTHING worth remembering long-term

EXAMPLES:
  • User shares an article about RAG → ingest it
  • User explains their project architecture → ingest it
  • User makes a decision about tech stack → ingest it
  • User lists their preferences → ingest it

NO CONFIGURATION NEEDED — just call this tool with any content.""",
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content to learn from (required). Can be article text, notes, code, conversation transcript, anything."
                },
                "title": {
                    "type": "string", 
                    "description": "Title/description (auto-generated if empty)"
                },
                "url": {
                    "type": "string",
                    "description": "Source URL (optional, for attribution)"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for categorization (optional)"
                },
                "content_type": {
                    "type": "string",
                    "enum": ["article", "paper", "note", "bookmark", "code",
                             "pdf", "conversation", "tweet", "video", "unknown"],
                    "default": "unknown"
                }
            },
            "required": ["content"],
        }
    ),
    Tool(
        name="cw_write_pages",
        description="""Write one or more wiki pages created during extraction.

Call this AFTER analyzing content from cw_ingest. Each page becomes a permanent part of the knowledge base.

FORMAT: Pass page data as JSON array. Each page needs 'filename' and 'content'.
Filename must start with 'wiki/concept/', 'wiki/entity/', or 'wiki/synthesis/'.""",
        inputSchema={
            "type": "object",
            "properties": {
                "pages": {
                    "type": "array",
                    "description": "Array of pages to write",
                    "items": {
                        "type": "object",
                        "properties": {
                            "filename": {
                                "type": "string",
                                "description": "Path like wiki/concept/topic-name.md"
                            },
                            "content": {
                                "type": "string",
                                "description": "Full markdown content of the page"
                            }
                        },
                        "required": ["filename", "content"]
                    }
                }
            },
            "required": ["pages"],
        }
    ),
    Tool(
        name="cw_update_index",
        description="""Update the global wiki index after writing pages.

Call this ONCE after finishing all cw_write_pages calls in a batch.
Regenerates wiki/index.md with all current pages organized by type.""",
        inputSchema={
            "type": "object",
            "properties": {},
        }
    ),
    Tool(
        name="cw_query",
        description="""Search the Compound Wiki knowledge base for information.

Use when:
  • User asks about something they might have told you before
  • You need context about user's past decisions/preferences/projects
  • Building context before generating reports, code, plans
  • User says "what do I know about X" or "check my notes"

Returns relevant wiki pages with content previews.""",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query or question (required)"
                },
                "scope": {
                    "type": "string",
                    "enum": ["all", "concepts", "entities", "synthesis"],
                    "default": "all"
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50
                }
            },
            "required": ["query"],
        }
    ),
    Tool(
        name="cw_stats",
        description="""Get statistics about the Compound Wiki knowledge base.

Shows: page counts, health score, link density, activity timestamps.""",
        inputSchema={
            "type": "object",
            "properties": {},
        }
    ),
    Tool(
        name="cw_lint",
        description="""Run health check on the entire Wiki.

Checks: broken links, orphaned pages, short pages, missing citations.
Returns actionable report with fix suggestions.""",
        inputSchema={
            "type": "object",
            "properties": {
                "fix_auto": {
                    "type": "boolean",
                    "default": False,
                    "description": "Auto-fix minor issues (orphan links, stale markers)"
                }
            }
        }
    ),
]


# ══════════════════════════════════════════════════════════════
# TOOL HANDLERS
# ══════════════════════════════════════════════════════════════

async def _handle_ingest(arguments: Dict[str, Any]) -> List[TextContent]:
    """
    Handle cw_ingest — the main entry point.
    
    STRATEGY: Save raw content → Return extraction prompt to the Agent.
    The Agent uses its OWN LLM to do the extraction. Zero extra cost.
    """
    try:
        content = arguments.get("content", "")
        if not content or len(content.strip()) < 10:
            return [TextContent(type="text", text=
                "❌ Content too short (need at least 10 characters). "
                "Please provide actual content to learn from."
            )]
        
        title = arguments.get("title") or ""
        url = arguments.get("url") or ""
        tags = arguments.get("tags") or []
        ct_str = arguments.get("content_type", "unknown")
        
        # Resolve paths and ensure directories exist
        paths = _resolve_paths()
        _ensure_dirs(paths)
        
        # Step 1: Save raw content (immutable record)
        raw_rel_path = _save_raw(
            content=content,
            title=title,
            url=url,
            tags=tags,
            content_type=ct_str,
            paths=paths,
        )
        
        # Step 2: Load extraction rules
        rules_text = _load_rules()
        
        # Step 3: Build and return the EXTRACTION PROMPT
        # This is where the magic happens — the HOST AGENT executes this!
        extraction_prompt = _build_extraction_prompt(
            raw_filename=raw_rel_path,
            content=content,
            title=title or "Untitled",
            rules_text=rules_text,
            paths=paths,
        )
        
        # Get current stats for context
        stats = _get_stats(paths)
        
        response = f"""✅ **Content Saved — Ready for Analysis**

**Source:** `{raw_rel_path}`  
**Size:** {len(content):,} characters  
**Type:** {ct_str}  
**Wiki Status:** {stats['total']} existing pages ({stats['concepts']} concepts, {stats['entities']} entities)

---

{extraction_prompt}"""

        return [TextContent(type="text", text=response)]
    
    except Exception as e:
        logger.error(f"Ingest error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ Ingestion error: {e}")]


async def _handle_write_pages(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cw_write_pages — save wiki pages generated by the Agent."""
    try:
        pages = arguments.get("pages", [])
        if not pages:
            return [TextContent(type="text", text="❌ No pages provided.")]
        
        paths = _resolve_paths()
        _ensure_dirs(paths)
        
        results = []
        created_count = 0
        updated_count = 0
        
        for page_data in pages:
            filename = page_data.get("filename", "")
            content = page_data.get("content", "")
            
            if not filename or not content:
                continue
            
            # Validate path (security: only allow wiki/ subdirectory)
            if not filename.startswith("wiki/") or ".." in filename:
                results.append(f"⚠️ SKIPPED (invalid path): {filename}")
                continue
            
            result = _save_page(filename, content, paths)
            if result["action"] == "created":
                created_count += 1
            else:
                updated_count += 1
            results.append(
                f"✅ {result['action'].upper()}: {result['path']} "
                f"({result['size_bytes']} chars)"
            )
        
        response = f"""📝 **Pages Written Successfully**

**Created:** {created_count} | **Updated:** {updated_count} | **Total:** {len(pages)}

### Details
{chr(10).join(f'- {r}' for r in results)}

### Next Step
Run `cw_update_index` to refresh the global index."""

        return [TextContent(type="text", text=response)]
    
    except Exception as e:
        logger.error(f"Write error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ Write error: {e}")]


async def _handle_update_index(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cw_update_index — regenerate global index."""
    try:
        paths = _resolve_paths()
        index_summary = _update_index(paths)
        stats = _get_stats(paths)
        
        response = f"""📑 **Index Updated**

{index_summary}

### Current Stats
- 💡 Concepts: {stats['concepts']}
- 🏷️ Entities: {stats['entities']}
- 🔗 Synthesis: {stats['synthesis']}
- ❤️ Health Score: {'🟢' if stats['health_score'] > 80 else '🟡' if stats['health_score'] > 50 else '🔴'} {stats['health_score']}/100
- 🔗 Avg Links/Page: {stats['avg_links']}"""

        return [TextContent(type="text", text=response)]
    
    except Exception as e:
        logger.error(f"Index error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ Index error: {e}")]


async def _handle_query(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cw_query — search wiki knowledge base."""
    try:
        query = arguments.get("query", "").strip()
        if not query:
            return [TextContent(type="text", text="❌ Query cannot be empty.")]
        
        scope = arguments.get("scope", "all")
        max_results = min(max(int(arguments.get("max_results", 10)), 1), 50)
        
        paths = _resolve_paths()
        result = _search_wiki(query, scope, max_results, True, paths)
        
        if not result["results"]:
            stats = _get_stats(paths)
            return [TextContent(type="text", text=f"""🔍 **No matches found for:** "{query}"

**Suggestions:**
- Try different keywords
- Use `cw_ingest` to add content about this topic first

**Wiki Status:** {stats['total']} pages available""")]
        
        # Build rich response
        lines = [
            f'🔍 **Results for:** "{query}"',
            f"Found **{len(result['results'])}** relevant page(s)\n",
        ]
        
        for i, r in enumerate(result["results"], 1):
            lines.append(f"### {i}. `{r['page']}` *(relevance: {r['score']})*")
            lines.append(f"- **Section:** {r['section']}")
            full = r.get("full_content", "")
            if len(full) > 1200:
                lines.append(f"\n<details>\n<summary>📖 Full content ({len(full)} chars)</summary>\n\n{full}\n\n</details>")
            elif len(full) > 50:
                lines.append(f"\n**Content:**\n{full}")
            lines.append("")
        
        lines.extend([
            "---\n**💡 Tips:**",
            "- Need more detail? Ask me to read a specific page.",
            "- Want to add info? Use `cw_ingest`.",
            "- Check quality? Run `cw_lint`.",
        ])
        
        return [TextContent(type="text", text="\n".join(l for l in lines if l))]
    
    except Exception as e:
        logger.error(f"Query error: {e}", exc_info=True)
        return [TextContent(type="text", text=f"❌ Query error: {e}")]


async def _handle_stats(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cw_stats — show wiki statistics."""
    try:
        paths = _resolve_paths()
        stats = _get_stats(paths)
        
        health_emoji = '🟢' if stats['health_score'] > 80 else '🟡' if stats['health_score'] > 50 else '🔴'
        link_quality = 'High' if stats['avg_links'] > 5 else 'Medium' if stats['avg_links'] > 2 else 'Low'
        
        response = [
            "## 📊 Compound Wiki Statistics\n",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| 📥 Raw Sources | {stats['raw_files']} files |",
            f"| 💡 Concepts | {stats['concepts']} |",
            f"| 👤 Entities | {stats['entities']} |",
            f"| 🔗 Synthesis | {stats['synthesis']} |",
            f"| 📝 Total Pages | {stats['total']} |",
            f"| 🔗 Avg Links/Page | {stats['avg_links']} ({link_quality}) |",
            f"| ❤️ Health Score | {health_emoji} **{stats['health_score']}/100** |",
            f"| 📊 Total Content | {stats['total_chars']:,} chars |",
            "\n---\n*Stats by Compound Wiki v2 (Zero-Config Mode)*",
        ]
        
        return [TextContent(type="text", text="\n".join(response))]
    
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Stats error: {e}")]


async def _handle_lint(arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle cw_lint — run wiki health check."""
    try:
        paths = _resolve_paths()
        wiki_dir = paths["wiki"]
        
        if not wiki_dir.exists():
            return [TextContent(type="text", text="📭 Wiki is empty. Nothing to check.")]
        
        issues = {"broken_links": [], "orphans": [], "short_pages": [], "no_citation": []}
        total_pages = 0
        total_links = 0
        linked_targets = set()
        all_stems = set()
        
        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name in ("index.md", "changelog.md"):
                continue
            
            total_pages += 1
            all_stems.add(md_file.stem.lower())
            
            try:
                content = md_file.read_text(encoding="utf-8")
                size = md_file.stat().st_size
                
                # Check links
                links = re.findall(r'\[\[(.+?)\]\]', content)
                total_links += len(links)
                for link in links:
                    target = link.split("|")[0].strip().lower().rstrip("]")
                    linked_targets.add(target)
                    # Check if target exists
                    target_files = list(wiki_dir.rglob(f"{target}.md"))
                    if not target_files:
                        issues["broken_links"].append({
                            "page": str(md_file.relative_to(wiki_dir)),
                            "target": link,
                        })
                
                # Short pages
                if size < 100:
                    issues["short_pages"].append(str(md_file.relative_to(wiki_dir)))
                
                # Missing citations
                has_citations = bool(re.search(r'>\s*(Source|来源)', content))
                has_claims = bool(re.search(r'\*\*[^*]+\*\*', content))
                if has_claims and not has_citations:
                    issues["no_citation"].append(str(md_file.relative_to(wiki_dir)))
                    
            except Exception:
                continue
        
        # Orphaned pages (nothing links to them)
        for md_file in wiki_dir.rglob("*.md"):
            if md_file.name in ("index.md", "changelog.md"):
                continue
            if md_file.stem.lower() not in linked_targets and total_pages > 1:
                issues["orphans"].append(str(md_file.relative_to(wiki_dir)))
        
        # Calculate scores
        total_issues = sum(len(v) for v in issues.values())
        health = max(0, 100 - total_issues * 5)
        
        icons = {"broken_links": "🔴", "orphans": "🔗", "short_pages": "⚠️", "no_citation": "📎"}
        
        lines = [
            "## 🔬 Wiki Health Report\n",
            f"**Health:** {'🟢' if health > 80 else '🟡' if health > 50 else '🔴'} **{health}/100**",
            f"**Pages:** {total_pages} | **Links:** {total_links}\n",
        ]
        
        for issue_type, items in issues.items():
            icon = icons.get(issue_type, "•")
            label = issue_type.replace("_", " ").title()
            count = len(items)
            if count == 0:
                lines.append(f"| {icon} **{label}** | ✅ Clean |")
            else:
                lines.append(f"| {icon} **{label}** | ⚠️ {count} |")
                for item in items[:5]:
                    if isinstance(item, dict):
                        detail = " | ".join(f"`{v}`" for v in item.values())
                        lines.append(f"| | → {detail} |")
                    else:
                        lines.append(f"| | → `{item}` |")
                if count > 5:
                    lines.append(f"| | ... +{count - 5} more |")
            lines.append("")
        
        lines.extend(["---\n", f"_Checked at {datetime.now().isoformat()}_"])
        
        return [TextContent(type="text", text="\n".join(l for l in lines if l))]
    
    except Exception as e:
        return [TextContent(type="text", text=f"❌ LINT error: {e}")]


# ══════════════════════════════════════════════════════════════
# DISPATCH & SERVER REGISTRATION
# ══════════════════════════════════════════════════════════════

TOOL_HANDLERS = {
    "cw_ingest":         _handle_ingest,
    "cw_write_pages":    _handle_write_pages,
    "cw_update_index":   _handle_update_index,
    "cw_query":          _handle_query,
    "cw_stats":          _handle_stats,
    "cw_lint":           _handle_lint,
}


@server.list_tools()
async def list_tools() -> ListToolsResult:
    return ListToolsResult(tools=TOOLS)


@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
    logger.info(f"[TOOL] {name}({list(arguments.keys())})")
    
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {name}")],
            isError=True,
        )
    
    try:
        results = await handler(arguments)
        return CallToolResult(content=results, isError=False)
    except Exception as e:
        logger.error(f"[ERROR] {name}: {e}", exc_info=True)
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {e}")],
            isError=True,
        )


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

def run_mcp_server(transport: str = "stdio"):
    """
    Start the MCP Server.
    
    Args:
        transport: 'stdio' (for local Agents) or 'sse' (for remote)
    """
    if not HAS_MCP:
        print("""
╔══════════════════════════════════════════════════╗
║  ERROR: MCP library not installed               ║
║                                                 ║
║  Install: pip install mcp[cli]                  ║
║  Retry: python plugins/mcp_server.py            ║
╚════════════════════════════════════════════════╝""")
        sys.exit(1)
    
    paths = _resolve_paths()
    _ensure_dirs(paths)
    
    print(f"""
╔═══════════════════════════════════════════════════════╗
║     🧠 Compound Wiki MCP Server v2                   ║
║     Zero Config — Uses Host Agent's Brain            ║
╠═══════════════════════════════════════════════════════╣
║  Project:  {paths['project']:<42} ║
║  Mode:     Agent-Native (no API key needed!)          ║
║  Tools:    ingest · write_pages · update_index        ║
║            · query · stats · lint                     ║
╠═══════════════════════════════════════════════════════╣
║  Transport: {transport:<43} ║
╚═══════════════════════════════════════════════════════╝
""")
    
    if transport == "sse":
        server.run(transport="sse", host="127.0.0.1", port=8765)
    else:
        server.run(transport="stdio")


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    run_mcp_server(transport)
