"""
CAM Daemon HTTP Server
======================

FastAPI-based HTTP server that provides the universal Agent memory API.
This is THE single entry point for ALL Agents.

API Endpoints:
    POST /hook          — Send conversation turn for auto-extraction
    GET  /query?q=...   — Query knowledge base
    GET  /stats         — Get daemon & wiki statistics
    GET  /health        — Health check
    POST /ingest        — Manual content ingestion (raw → wiki)
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Try FastAPI, fall back to built-in http.server ──────────
try:
    from fastapi import FastAPI, Request, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field

    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    # Fallback: use aiohttp or plain http.server
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import urllib.parse


logger = logging.getLogger("cam_daemon.server")

# ── Request/Response Models (used by both FastAPI and fallback) ───


class HookRequest:
    """Incoming conversation hook request.

    Supports two modes:

    Mode 1 — Agent-Native (recommended, zero cost):
        Agent extracts facts using its own LLM, passes them in extracted_facts.
        Daemon only does dedup + store. No API key needed.

    Mode 2 — LLM Fallback (daemon-side extraction):
        Only user_message + ai_response provided. Daemon calls
        external LLM for extraction. Requires API key / Ollama.
    """

    __slots__ = (
        "user_message",
        "ai_response",
        "agent_id",
        "session_id",
        "metadata",
        "extracted_facts",
    )

    def __init__(
        self,
        user_message: str = "",
        ai_response: str = "",
        agent_id: str = "unknown",
        session_id: str = "",
        metadata: Dict[str, Any] = None,
        extracted_facts: Optional[List[Dict]] = None,
    ):
        self.user_message = user_message
        self.ai_response = ai_response
        self.agent_id = agent_id or "unknown"
        self.session_id = session_id
        self.metadata = metadata or {}
        # Agent-Native facts: pre-extracted by the Agent itself
        self.extracted_facts = extracted_facts or []

    @property
    def combined_content(self) -> str:
        return f"{self.user_message}\n{self.ai_response}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.combined_content.encode("utf-8")).hexdigest()[:16]


class HookResult:
    """Result of processing a hook."""

    def __init__(
        self,
        success: bool = True,
        status: str = "",
        facts_extracted: int = 0,
        facts_written: int = 0,
        message: str = "",
        processing_time_ms: float = 0.0,
        throttled: bool = False,
    ):
        self.success = success
        self.status = status  # "ok" | "throttled" | "error"
        self.facts_extracted = facts_extracted
        self.facts_written = facts_written
        self.message = message
        self.processing_time_ms = processing_time_ms
        self.throttled = throttled

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "status": self.status,
            "facts_extracted": self.facts_extracted,
            "facts_written": self.facts_written,
            "message": self.message,
            "processing_time_ms": round(self.processing_time_ms, 1),
            "throttled": self.throttled,
            "timestamp": datetime.utcnow().isoformat(),
        }


# ── Throttle Controller ───────────────────────────────────────


class ThrottleController:
    """
    Prevents duplicate/near-duplicate hooks in rapid succession.

    Uses sliding window of recent content hashes + time tracking.
    """

    def __init__(self, min_interval_sec: float = 10.0, window_size: int = 50):
        self.min_interval_sec = min_interval_sec
        self.window_size = window_size
        # OrderedDict as LRU cache: hash → timestamp
        self._history: OrderedDict = OrderedDict()
        self._last_hook_per_agent: Dict[str, float] = {}

    def should_process(self, req: HookRequest) -> tuple[bool, str]:
        """
        Check if this hook should be processed.

        Returns (should_process, reason).
        """
        now = time.time()
        content_hash = req.content_hash

        # Check same-content dedup
        if content_hash in self._history:
            elapsed = now - self._history[content_hash]
            if elapsed < self.min_interval_sec:
                return (
                    False,
                    f"Throttled: same content seen {elapsed:.0f}s ago (min interval: {self.min_interval_sec}s)",
                )
            else:  # Old entry, refresh
                del self._history[content_hash]

        # Per-agent rate limiting
        last_hook = self._last_hook_per_agent.get(req.agent_id)
        if last_hook and (now - last_hook) < self.min_interval_sec * 0.5:
            return (
                False,
                f"Throttled: agent '{req.agent_id}' hooked {(now - last_hook):.0f}s ago",
            )

        # Record this hook
        self._history[content_hash] = now
        # Evict old entries
        while len(self._history) > self.window_size:
            self._history.popitem(last=False)

        self._last_hook_per_agent[req.agent_id] = now
        return True, ""


# ── Core Daemon Engine ────────────────────────────────────────


class CamEngine:
    """
    The brain of the daemon. Handles extraction → dedup → write pipeline.

    This class owns all the heavy logic; the server is just a thin transport.
    """

    def __init__(self, config):
        from .config import DaemonConfig

        self.config: DaemonConfig = config

        # Lazy-loaded components
        self._wiki = None
        self._extractor = None
        self._deduplicator = None
        self._graph = None

        # Stats
        self._stats = {
            "hooks_received": 0,
            "hooks_processed": 0,
            "hooks_throttled": 0,
            "total_facts_extracted": 0,
            "total_facts_written": 0,
            "total_errors": 0,
            "start_time": datetime.utcnow().isoformat(),
            "agents_seen": set(),
        }
        self._throttle = ThrottleController(
            min_interval_sec=config.throttle_interval_sec,
            window_size=config.throttle_window_size,
        )

    @property
    def wiki(self):
        if self._wiki is None:
            from cam_core.shared_wiki import SharedWiki

            self._wiki = SharedWiki(
                wiki_path=self.config.wiki_path,
                raw_path=self.config.raw_path,
            )
        return self._wiki

    @property
    def extractor(self):
        if self._extractor is None:
            from cam_core.extractor import FactExtractor

            self._extractor = FactExtractor(config=None)
            # Override LLM settings with daemon's own config
            self._extractor.llm_config = {
                "provider": self.config.llm.provider,
                "model": self.config.llm.model,
                "api_key": self.config.llm.api_key,
                "base_url": self.config.llm.base_url,
                "temperature": self.config.llm.temperature,
                "max_tokens": self.config.llm.max_tokens,
            }
        return self._extractor

    @property
    def deduplicator(self):
        if self._deduplicator is None:
            from cam_core.deduplicator import Deduplicator
            from cam_core.config import DEFAULT_CONFIG

            # Build config with correct dedup threshold
            cfg = DEFAULT_CONFIG
            if hasattr(cfg, "deduplication") and hasattr(cfg.deduplication, "near_duplicate_threshold"):
                cfg.deduplication.near_duplicate_threshold = self.config.dedup_similarity_threshold
            self._deduplicator = Deduplicator(config=cfg, wiki_index=self.wiki)
        return self._deduplicator

    @property
    def graph(self):
        """Lazy-loaded knowledge graph — auto-built from Wiki facts."""
        if self._graph is None:
            from cam_core.memory_graph import MemoryGraph

            graph_path = str(Path(self.config.wiki_path) / ".cam" / "graph.json")
            self._graph = MemoryGraph(graph_path=graph_path)
            self._graph._load()
        return self._graph

    async def on_conversation_turn(self, req: HookRequest) -> HookResult:
        """
        Process a single conversation turn.

        Pipeline: throttle → extract → dedup → write → update index
        """
        start = time.time()
        self._stats["hooks_received"] += 1

        # Step 1: Throttle check
        should_process, reason = self._throttle.should_process(req)
        if not should_process:
            self._stats["hooks_throttled"] += 1
            return HookResult(
                status="throttled",
                message=reason,
                throttled=True,
                processing_time_ms=(time.time() - start) * 1000,
            )

        try:
            # Track agent
            self._stats["agents_seen"].add(req.agent_id)

            # Skip if no meaningful content (Agent-Native: extracted_facts counts as content)
            has_content = bool(req.user_message.strip() or req.ai_response.strip())
            has_native_facts = bool(req.extracted_facts)
            if not has_content and not has_native_facts:
                return HookResult(
                    status="ok",
                    message="Empty content, skipped.",
                    processing_time_ms=(time.time() - start) * 1000,
                )

            # Step 2: Extract knowledge using daemon's LLM
            extracted_facts = await self._do_extraction(req)
            fact_count = len(extracted_facts) if extracted_facts else 0

            if fact_count == 0:
                self._stats["hooks_processed"] += 1
                return HookResult(
                    status="ok",
                    facts_extracted=0,
                    facts_written=0,
                    message="No significant facts to extract.",
                    processing_time_ms=(time.time() - start) * 1000,
                )

            # Step 3: Deduplicate against existing Wiki content
            new_facts = await self._deduplicate(extracted_facts)

            if not new_facts:
                self._stats["hooks_processed"] += 1
                return HookResult(
                    status="ok",
                    facts_extracted=fact_count,
                    facts_written=0,
                    message=f"All {fact_count} facts already exist in Wiki (dedup).",
                    processing_time_ms=(time.time() - start) * 1000,
                )

            # Step 4: Write to Wiki (atomic transaction)
            written_count = await self._write_facts(new_facts, req.agent_id)

            # Step 5: Update index
            await self._update_index()

            # Stats
            self._stats["hooks_processed"] += 1
            self._stats["total_facts_extracted"] += fact_count
            self._stats["total_facts_written"] += written_count

            elapsed_ms = (time.time() - start) * 1000
            logger.info(
                f"[{req.agent_id}] Extracted {fact_count} facts, wrote {written_count} new ({elapsed_ms:.0f}ms)"
            )

            return HookResult(
                status="ok",
                facts_extracted=fact_count,
                facts_written=written_count,
                message=f"Processed {fact_count} facts, {written_count} new.",
                processing_time_ms=elapsed_ms,
            )

        except Exception as e:
            self._stats["total_errors"] += 1
            logger.error(f"Hook processing error [{req.agent_id}]: {e}", exc_info=True)
            return HookResult(
                success=False,
                status="error",
                message=str(e),
                processing_time_ms=(time.time() - start) * 1000,
            )

    async def _do_extraction(self, req: HookRequest) -> list:
        """
        Extract facts from conversation.

        Priority:
          1. Agent-Native — use facts provided by the Agent itself (zero cost)
          2. LLM Fallback  — call external LLM API (needs API key / Ollama)
          3. Heuristic      — rule-based fallback (no LLM at all)
        """
        from cam_core.extractor import FactType, ExtractedFact

        # ── Mode 1: Agent-Native (preferred) ──
        if req.extracted_facts:
            logger.info(f"[{req.agent_id}] Using Agent-Native mode: {len(req.extracted_facts)} pre-extracted facts")
            parsed = []
            for item in req.extracted_facts:
                try:
                    fact = ExtractedFact(
                        fact_type=FactType(item.get("fact_type", "fact")),
                        content=item.get("content", "").strip(),
                        confidence=float(item.get("confidence", 0.85)),
                        source_text=req.combined_content[:200],
                        agent_id=req.agent_id,
                        tags=item.get("tags", []),
                        entities_mentioned=item.get("entities_mentioned", []),
                    )
                    if len(fact.content) >= 5:  # skip trivially short
                        parsed.append(fact)
                except (ValueError, KeyError) as e:
                    logger.warning(f"Skipping malformed fact: {e}")
            return parsed

        # ── Mode 2: LLM Fallback (external API) ──
        try:
            result = await self.extractor.extract(
                user_message=req.user_message,
                assistant_response=req.ai_response,
                agent_id=f"daemon:{req.agent_id}",
            )
            if isinstance(result, list):
                return result
            if hasattr(result, "facts") and result.facts:
                return result.facts
            return []
        except Exception as e:
            logger.warning(f"LLM extraction failed, using heuristic: {e}")

        # ── Mode 3: Heuristic (pure rules, no LLM) ──
        return self._heuristic_extract(req)

    def _heuristic_extract(self, req: HookRequest) -> list:
        """
        Simple rule-based extraction when LLM is unavailable.
        Catches common patterns like decisions, preferences, facts, problems, solutions.
        """
        from cam_core.extractor import FactType, ExtractedFact

        facts = []
        text = f"{req.user_message} {req.ai_response}"
        source_text = req.combined_content[:200]

        # ── Decision patterns ──
        decision_patterns = [
            "we decided",
            "we choose",
            "i decided",
            "we will use",
            "we chose",
            "using ",
            "we're using",
            "deploy on",
            "decided",
            "chose",
            "selected",
            "决定",
            "选择",
            "采用",
        ]
        for pat in decision_patterns:
            if pat.lower() in text.lower():
                for sentence in re.split(r'[.\n。]', text):
                    if pat in sentence:
                        facts.append(
                            ExtractedFact(
                                fact_type=FactType.DECISION,
                                content=sentence.strip(),
                                confidence=0.7,
                                source_text=source_text,
                                agent_id="daemon-heuristic",
                            )
                        )
                break

        # ── Preference patterns ──
        pref_patterns = [
            "prefer",
            "like to",
            "always use",
            "we prefer",
            "偏好",
            "喜欢用",
            "习惯用",
            "更喜欢",
        ]
        for pat in pref_patterns:
            if pat.lower() in text.lower():
                for sentence in re.split(r'[.\n。]', text):
                    if pat in sentence:
                        facts.append(
                            ExtractedFact(
                                fact_type=FactType.PREFERENCE,
                                content=sentence.strip(),
                                confidence=0.65,
                                source_text=source_text,
                                agent_id="daemon-heuristic",
                            )
                        )
                break

        # ── Problem patterns (bugs, errors, failures) ──
        problem_patterns = [
            "error",
            "bug",
            "crash",
            "failed",
            "failure",
            "broken",
            "doesn't work",
            "problem",
            "issue with",
            "错误",
            "崩溃",
            "失败",
            "问题",
        ]
        for pat in problem_patterns:
            if pat.lower() in text.lower():
                for sentence in re.split(r'[.\n。]', text):
                    if pat.lower() in sentence.lower():
                        # Only extract if it looks like a real problem report
                        if len(sentence.strip()) > 10:
                            facts.append(
                                ExtractedFact(
                                    fact_type=FactType.PROBLEM,
                                    content=sentence.strip(),
                                    confidence=0.6,
                                    source_text=source_text,
                                    agent_id="daemon-heuristic",
                                )
                            )
                break

        # ── Solution patterns (fixes, workarounds) ──
        solution_patterns = [
            "fixed",
            "solved",
            "workaround",
            "resolved",
            "the fix",
            "turns out",
            "instead of",
            "switched to",
            "修复",
            "解决",
            "替代方案",
        ]
        for pat in solution_patterns:
            if pat.lower() in text.lower():
                for sentence in re.split(r'[.\n。]', text):
                    if pat.lower() in sentence.lower():
                        if len(sentence.strip()) > 10:
                            facts.append(
                                ExtractedFact(
                                    fact_type=FactType.SOLUTION,
                                    content=sentence.strip(),
                                    confidence=0.65,
                                    source_text=source_text,
                                    agent_id="daemon-heuristic",
                                )
                            )
                break

        # ── Convention patterns (standards, workflows) ──
        convention_patterns = [
            "we always",
            "we never",
            "our convention",
            "our standard",
            "the convention",
            "the way we",
            "always do",
            "never do",
            "我们总是",
            "我们从不",
            "我们的惯例",
        ]
        for pat in convention_patterns:
            if pat.lower() in text.lower():
                for sentence in re.split(r'[.\n。]', text):
                    if pat.lower() in sentence.lower():
                        if len(sentence.strip()) > 10:
                            facts.append(
                                ExtractedFact(
                                    fact_type=FactType.CONVENTION,
                                    content=sentence.strip(),
                                    confidence=0.65,
                                    source_text=source_text,
                                    agent_id="daemon-heuristic",
                                )
                            )
                break

        # ── Entity mentions (tech stack) ──
        entity_patterns = [
            "PostgreSQL",
            "Redis",
            "Docker",
            "Kubernetes",
            "React",
            "Vue",
            "Python",
            "Go",
            "Rust",
            "FastAPI",
            "Django",
            "Flask",
            "GitHub Actions",
            "CI/CD",
        ]
        for entity in entity_patterns:
            if entity in text:
                facts.append(
                    ExtractedFact(
                        fact_type=FactType.ENTITY,
                        content=entity,
                        confidence=0.85,
                        source_text=source_text,
                        agent_id="daemon-heuristic",
                    )
                )

        return facts[:10]  # Cap at 10 heuristic facts

    async def _deduplicate(self, facts: list) -> list:
        """Filter out facts already present in the Wiki."""
        if not facts or not self.deduplicator:
            return facts
        # Use Deduplicator's main entry point: deduplicate() → DedupResult
        result = await self.deduplicator.deduplicate(facts)
        return result.unique_facts if hasattr(result, "unique_facts") else facts

    async def _write_facts(self, facts: list, agent_id: str) -> int:
        """Write facts to Wiki via atomic transaction, then auto-update knowledge graph."""
        written = await self.wiki.write_facts(
            facts=facts,
            agent_id=agent_id,
            source="daemon_auto",
        )

        # Auto-update knowledge graph with new facts
        if written > 0:
            try:
                from cam_core.extractor import FactType

                for fact in facts:
                    if hasattr(fact, "fact_type") and hasattr(fact, "content"):
                        node_type = {
                            FactType.ENTITY: "entity",
                            FactType.CONCEPT: "concept",
                            FactType.DECISION: "decision",
                            FactType.PREFERENCE: "preference",
                            FactType.TASK: "task",
                            FactType.FACT: "entity",
                        }.get(fact.fact_type, "entity")

                        self.graph._get_or_create_node(
                            id=self.graph._node_id(node_type, fact.content),
                            label=fact.content[:80],
                            node_type=node_type,
                            content=fact.content,
                            source_file=getattr(fact, "wiki_path", ""),
                            agent_id=agent_id,
                        )
                self.graph._save()
            except Exception as e:
                logger.warning(f"Graph update failed: {e}")

        return written

    async def _update_index(self) -> None:
        """Rebuild the index file with current page listing."""
        pages = await self.wiki.list_pages()

        type_counts = {"concept": 0, "entity": 0, "synthesis": 0}
        entries = []

        for page in pages:
            ptype = page["path"].split("/")[0] if "/" in page["path"] else "concept"
            if ptype in type_counts:
                type_counts[ptype] += 1

            entries.append(
                {
                    "title": page["name"].replace("-", " ").title(),
                    "path": page["path"],
                    "type": ptype,
                    "summary": "",
                    "updated": page["modified"],
                }
            )

        total = sum(type_counts.values())

        index_lines = [
            "# CAM - 全局索引\n",
            f"> **最后更新**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}\n",
            f"> **页面总数**: {total}\n",
            "> **状态**: 活跃\n",
            "\n---\n\n",
            "## 📊 统计概览\n\n",
            "| 类型 | 数量 |\n|------|------|\n",
            f"| 概念页 (`concept/`) | {type_counts['concept']} |\n",
            f"| 实体页 (`entity/`) | {type_counts['entity']} |\n",
            f"| 综合页 (`synthesis/`) | {type_counts['synthesis']} |\n",
            f"| **合计** | **{total}** |\n",
            "\n---\n\n",
            "## 📚 页面列表\n\n",
        ]

        for entry in sorted(entries, key=lambda x: x["path"]):
            index_lines.append(
                f"- **[{entry['title']}]({entry['path']})** "
                f"`[{entry['type']}]` "
                f"*Updated: {entry['updated'].split('T')[0]}*\n"
            )

        index_content = "".join(index_lines)

        full_path = Path(self.config.wiki_path) / "index.md"
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(index_content, encoding="utf-8")

    async def query(self, question: str, top_k: int = 5) -> Dict[str, Any]:
        """Query the knowledge base."""
        results = await self.wiki.search_facts(question)

        output = {
            "question": question,
            "results_found": len(results),
            "matches": [],
        }

        for r in results[:top_k]:
            page_content = await self.wiki.read_page(r["path"])
            output["matches"].append(
                {
                    "page": r["path"],
                    "name": r["name"],
                    "preview": r.get("preview", ""),
                    "match_count": r.get("match_count", 0),
                    "content_snippet": (page_content or "")[:300],
                }
            )

        return output

    async def get_stats(self) -> Dict[str, Any]:
        """Comprehensive stats about daemon and wiki."""
        pages = await self.wiki.list_pages()

        return {
            "daemon": {
                "uptime_sec": (datetime.utcnow() - datetime.fromisoformat(self._stats["start_time"])).total_seconds(),
                "hooks_received": self._stats["hooks_received"],
                "hooks_processed": self._stats["hooks_processed"],
                "hooks_throttled": self._stats["hooks_throttled"],
                "total_facts_extracted": self._stats["total_facts_extracted"],
                "total_facts_written": self._stats["total_facts_written"],
                "total_errors": self._stats["total_errors"],
                "agents_seen": sorted(list(self._stats["agents_seen"])),
            },
            "wiki": {
                "total_pages": len(pages),
                "total_bytes": sum(p["size_bytes"] for p in pages),
                "pages_by_type:": {},
            },
            "llm": {
                "provider": self.config.llm.provider,
                "model": self.config.llm.model,
            },
        }

    async def ingest_raw(self, content: str, source: str = "manual") -> Dict[str, Any]:
        """
        Manual ingestion: save raw content → trigger extraction.
        This is equivalent to putting a file into raw/ and running ingest.
        """
        from pathlib import Path
        import uuid

        raw_dir = Path(self.config.raw_path)
        raw_dir.mkdir(parents=True, exist_ok=True)

        # Save to raw/
        filename = f"{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.md"
        filepath = raw_dir / filename
        filepath.write_text(content, encoding="utf-8")

        # Create a synthetic hook request and process it
        req = HookRequest(
            user_message=content[:2000],
            ai_response="(manual ingest)",
            agent_id="manual-ingest",
            metadata={"source": source, "raw_file": str(filepath)},
        )

        result = await self.on_conversation_turn(req)
        return {
            "raw_file": str(filepath),
            "hook_result": result.to_dict(),
        }


# ── Server Implementation ──────────────────────────────────────

if HAS_FASTAPI:
    app = FastAPI(
        title="CAM Daemon",
        description="Universal AI Memory Service — One endpoint, any Agent",
        version="2.0.0",
    )

    _engine_instance: Optional[CamEngine] = None

    def get_engine() -> CamEngine:
        global _engine_instance
        assert _engine_instance, "Daemon engine not initialized!"
        return _engine_instance

    # ---- Pydantic models for FastAPI validation ----

    class HookRequestModel(BaseModel):
        user_message: str = ""
        ai_response: str = ""
        agent_id: str = "unknown"
        session_id: str = ""
        metadata: Dict[str, Any] = Field(default_factory=dict)
        # Agent-Native mode: pre-extracted facts from the Agent's own LLM
        extracted_facts: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description="Pre-extracted facts (Agent-Native mode). "
            "If provided, daemon skips LLM call and uses these directly.",
        )
        # Alternative format: full conversation array (auto-parsed)
        conversation: Optional[List[Dict[str, str]]] = Field(
            default=None,
            description="Conversation history. Auto-parsed to user_message + ai_response if not set directly.",
        )

        def parse_conversation(self) -> tuple:
            """Extract user_message and ai_response from conversation array."""
            if self.user_message or self.ai_response:
                return self.user_message, self.ai_response
            if not self.conversation:
                return "", ""
            user_msgs = [m.get("content", "") for m in self.conversation if m.get("role") == "user"]
            ai_msgs = [m.get("content", "") for m in self.conversation if m.get("role") in ("assistant", "ai")]
            return (user_msgs[-1] if user_msgs else "", ai_msgs[-1] if ai_msgs else "")

    class IngestRequestModel(BaseModel):
        content: str
        source: str = "manual"

    class QueryParams(BaseModel):
        q: str
        top_k: int = 5

    # ---- Endpoints ----

    @app.post("/hook")
    async def api_hook(req: HookRequestModel) -> JSONResponse:
        """Main entry point: send conversation turn for auto-memory.

        Agent-Native mode (zero cost):
            Include extracted_facts in the request body.
            The Agent uses its own LLM to extract facts, daemon only dedups + stores.

        Fallback mode:
            Omit extracted_facts. Daemon will call external LLM or use heuristics.
        """
        engine = get_engine()
        um, ar = req.parse_conversation()
        hook_req = HookRequest(
            user_message=um,
            ai_response=ar,
            agent_id=req.agent_id,
            session_id=req.session_id,
            metadata=req.metadata,
            extracted_facts=req.extracted_facts,
        )
        result = await engine.on_conversation_turn(hook_req)
        return JSONResponse(result.to_dict(), status_code=200 if result.success else 500)

    @app.post("/ingest")
    async def api_ingest(req: IngestRequestModel) -> JSONResponse:
        """Manual content ingestion."""
        engine = get_engine()
        result = await engine.ingest_raw(content=req.content, source=req.source)
        return JSONResponse(result)

    @app.get("/query")
    async def api_query(q: str, top_k: int = 5) -> JSONResponse:
        """Query the knowledge base."""
        engine = get_engine()
        results = await engine.query(question=q, top_k=top_k)
        return JSONResponse(results)

    @app.get("/stats")
    async def api_stats() -> JSONResponse:
        """Get daemon and wiki statistics."""
        engine = get_engine()
        stats = await engine.get_stats()
        return JSONResponse(stats)

    @app.get("/health")
    async def api_health() -> JSONResponse:
        """Health check endpoint."""
        return JSONResponse(
            {
                "status": "healthy",
                "version": "2.0.0",
                "timestamp": datetime.utcnow().isoformat(),
            }
        )

else:
    # ── Fallback: pure Python HTTP server (no FastAPI dependency) ───

    app = None  # Not used in fallback mode

    class _FallbackHandler(BaseHTTPRequestHandler):
        """Lightweight HTTP handler when FastAPI isn't available."""

        engine: CamEngine = None

        def do_POST(self):
            import asyncio

            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else b"{}"

            try:
                data = json.loads(body)
            except Exception:
                data = {}

            path = self.path.rstrip("/")
            response_data = {}
            status_code = 200

            try:
                if path == "/hook":
                    # Support conversation array format
                    um = data.get("user_message", "")
                    ar = data.get("ai_response", "")
                    if not um and not ar:
                        conv = data.get("conversation", [])
                        if conv:
                            user_msgs = [m.get("content", "") for m in conv if m.get("role") == "user"]
                            ai_msgs = [m.get("content", "") for m in conv if m.get("role") in ("assistant", "ai")]
                            um = user_msgs[-1] if user_msgs else ""
                            ar = ai_msgs[-1] if ai_msgs else ""
                    req = HookRequest(
                        user_message=um,
                        ai_response=ar,
                        agent_id=data.get("agent_id", "unknown"),
                        session_id=data.get("session_id", ""),
                        metadata=data.get("metadata", {}),
                        extracted_facts=data.get("extracted_facts"),
                    )
                    result = asyncio.get_event_loop().run_until_complete(self.engine.on_conversation_turn(req))
                    response_data = result.to_dict()
                    status_code = 200 if result.success else 500

                elif path == "/ingest":
                    result = asyncio.get_event_loop().run_until_complete(
                        self.engine.ingest_raw(
                            content=data.get("content", ""),
                            source=data.get("source", "manual"),
                        )
                    )
                    response_data = result

                elif path == "/query":
                    results = asyncio.get_event_loop().run_until_complete(
                        self.engine.query(
                            question=data.get("q", ""),
                            top_k=data.get("top_k", 5),
                        )
                    )
                    response_data = results

                else:
                    response_data = {"error": f"Not found: {path}"}
                    status_code = 404

            except Exception as e:
                response_data = {"success": False, "status": "error", "message": str(e)}
                status_code = 500

            self._send_json(response_data, status_code)

        def do_GET(self):
            path = self.path.rstrip("?").rstrip("/")
            params = urllib.parse.parse_qs(self.path.split("?", 1)[-1]) if "?" in self.path else {}

            if path == "/health":
                self._send_json({"status": "healthy", "version": "2.0.0"})
            elif path == "/stats":
                loop = asyncio.new_event_loop()
                stats = loop.run_until_complete(self.engine.get_stats())
                loop.close()
                self._send_json(stats)
            elif path == "/query":
                q = params.get("q", [""])[0]
                top_k = int(params.get("top_k", ["5"])[0])
                loop = asyncio.new_event_loop()
                results = loop.run_until_complete(self.engine.query(q, top_k))
                loop.close()
                self._send_json(results)
            else:
                self._send_json({"error": f"Not found: {path}"}, 404)

        def _send_json(self, data: dict, code: int = 200):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            logger.debug(f"[HTTP] {args}")


def create_server(engine: CamEngine, host: str = "127.0.0.1", port: int = 9877):
    """
    Create the HTTP server instance (with engine attached).

    Returns (server, startup_coro_or_none).
    """
    global _engine_instance
    _engine_instance = engine

    if HAS_FASTAPI:
        import uvicorn

        # Use uvicorn's Server API directly (not uvicorn.run which calls
        # asyncio.run() internally — that fails when we're already in an
        # event loop from _run.py's asyncio.run(main()))
        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        server = uvicorn.Server(config)
        coro = server.serve()
        return app, coro
    else:
        # Fallback server
        _FallbackHandler.engine = engine
        server = HTTPServer((host, port), _FallbackHandler)
        return server, None
