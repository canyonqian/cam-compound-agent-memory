"""
Agent SDK — Universal Adapter for Any AI Agent
===============================================

This is THE integration point. It lets any AI Agent use Memory Core
with zero code changes to the Agent itself.

Supported platforms:
  - Claude Code (via custom slash command / tool)
  - Cursor (via .cursorrules + MCP server)
  - GitHub Copilot (via extension config)
  - OpenAI Codex / ChatGPT (via MCP)
  - Custom Agents (via Python SDK)

Integration patterns:

  PATTERN 1: Decorator (Python agents) — ZERO changes needed
  ----------------------------------------------------------
  from memory_core import MemoryCore
  
  mc = MemoryCore(wiki_path="./wiki")
  
  @mc.hook
  async def my_chat_function(user_message):
      response = await llm.chat(user_message)
      return response
  # ← That's it! Every call automatically extracts & stores memory

  
  PATTERN 2: Middleware (frameworks like FastAPI/Flask)
  -----------------------------------------------------
  app = FastAPI()
  app.add_middleware(MemoryMiddleware, memory_core=mc)

  
  PATTERN 3: MCP Server — Claude Desktop / Cursor / VS Code
  ---------------------------------------------------------
  # Add to your MCP config:
  {
    "cam-memory": {
      "command": "python",
      "args": ["-m", "memory_core.mcp_server"]
    }
  }
  # Then in any AI chat: "remember that I prefer X"
  # → Automatically stored, no extra steps


  PATTERN 4: Manual Hook (for non-Python agents)
  ----------------------------------------------
  # After each response generation, make an HTTP call:
  POST http://localhost:9877/memory/hook
  {
    "user_message": "...",
    "assistant_response": "..."
  }
  → Returns extraction results, facts written to Wiki
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Awaitable, Union

logger = logging.getLogger("memory_core.agent_sdk")


class AgentType(Enum):
    """Types of AI Agents we support."""
    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    COPILOT = "copilot"
    CHATGPT = "chatgpt"
    OPENAI_API = "openai_api"
    ANTHROPIC_API = "anthropic_api"
    OLLAMA = "ollama"
    CUSTOM = "custom"


@dataclass
class AgentConfig:
    """Configuration for a specific Agent adapter."""
    
    agent_type: AgentType
    agent_id: str                           # Unique identifier for multi-Agent setups
    name: str = ""                          # Display name
    
    # Auto-memory settings
    auto_extract: bool = True               # Enable automatic extraction
    extract_on_every_turn: bool = False     # Extract every turn (expensive)
    extract_on_explicit: bool = True        # Extract on "remember" etc.
    quiet_mode: bool = True                 # Don't show extraction UI
    
    # LLM override (use different model for extraction than for chatting)
    extraction_model: Optional[str] = None  # e.g., "gpt-4o-mini" for cheap extraction
    
    # Callback hooks
    on_fact_extracted: Optional[Callable] = None   # Called when fact extracted
    on_fact_written: Optional[Callable] = None     # Called when fact saved to Wiki
    on_error: Optional[Callable] = None            # Called on error


@dataclass 
class MemoryResult:
    """Result of a memory operation (returned to calling Agent)."""
    
    success: bool
    facts_extracted: int = 0
    facts_written: int = 0
    processing_time_ms: float = 0.0
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class MemoryCore:
    """
    The main entry point for using CAM's Memory Core.
    
    This is what most users interact with. It wires together:
    - HookEngine (conversation event detection)
    - FactExtractor (LLM-powered knowledge extraction)
    - Deduplicator (duplicate detection & merging)
    - SharedWiki (concurrent-safe storage)
    - KnowledgeGraph (relationship mapping)
    
    Quick start:
        from memory_core import MemoryCore
        
        mc = MemoryCore(wiki_path="./wiki")
        
        # One-time setup
        await mc.initialize()
        
        # Then after every conversation turn:
        result = await mc.remember(user_msg, assistant_response)
        # Done! Facts automatically extracted and stored.
    """
    
    def __init__(self, wiki_path: str = "./wiki",
                 raw_path: str = "./raw",
                 config_path: str = None,
                 agent_config: AgentConfig = None):
        
        from .config import MemoryConfig, DEFAULT_CONFIG
        
        self.wiki_path = wiki_path
        self.raw_path = raw_path
        
        # Load or create configuration
        if config_path and os.path.exists(config_path):
            self.config = MemoryConfig.from_file(config_path)
        else:
            self.config = DEFAULT_CONFIG
            self.config.wiki_path = wiki_path
            self.config.raw_path = raw_path
        
        self.agent_config = agent_config or AgentConfig(
            agent_type=AgentType.CUSTOM,
            agent_id="default-agent",
        )
        
        # Components (lazy-initialized)
        self._hook_engine = None
        self._extractor = None
        self._deduplicator = None
        self._shared_wiki = None
        self._graph = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize all components. Must be called before first use.
        
        This is separated from __init__ so initialization can be async.
        """
        if self._initialized:
            return
        
        logger.info(f"Initializing Memory Core at {self.wiki_path}...")
        
        # Create core components
        self._extractor = FactExtractor(config=self.config)
        self._deduplicator = Deduplicator(config=self.config)
        self._shared_wiki = SharedWiki(
            wiki_path=self.wiki_path,
            raw_path=self.raw_path,
            config=self.config,
        )
        self._graph = MemoryGraph(graph_path=self.config.graph_path)
        
        self._hook_engine = HookEngine(
            config=self.config,
            extractor=self._extractor,
            deduplicator=self._deduplicator,
            shared_wiki=self._shared_wiki,
            graph=self._graph,
        )
        
        # Register built-in callbacks
        self._register_callbacks()
        
        # Start session
        await self._hook_engine.on_session_start(
            agent_id=self.agent_config.agent_id
        )
        
        self._initialized = True
        logger.info("Memory Core initialized successfully ✅")
    
    def _register_callbacks(self):
        """Register internal callback handlers."""
        if self.agent_config.on_fact_extracted:
            async def on_extracted(ctx):
                result = ctx.data.get("extraction_result")
                if result:
                    await self.agent_config.on_fact_extracted(result)
                return HookResult(handled=True)
            
            self._hook_engine.on(HookEvent.FACT_EXTRACTED, on_extracted)
        
        if self.agent_config.on_fact_written:
            async def on_written(ctx):
                return HookResult(handled=True)
            
            self._hook_engine.on(HookEvent.FACT_WRITTEN, on_written)
    
    # ============================================================
    # MAIN API — The methods you actually call
    # ============================================================
    
    async def remember(self, user_message: str,
                       assistant_response: str,
                       force: bool = False) -> MemoryResult:
        """
        ⭐ PRIMARY API: Process a conversation turn for automatic memory.
        
        Call this after EVERY exchange between user and AI.
        
        Parameters:
            user_message: What the human said
            assistant_response: What the AI replied
            force: Force extraction even if throttle says no
        
        Returns:
            MemoryResult with details of what happened
        
        Example:
            # In your Agent loop:
            while True:
                user_input = input("You: ")
                ai_reply = await my_agent.generate(user_input)
                
                # ← This one line enables automatic memory!
                mem_result = await mc.remember(user_input, ai_reply)
                
                print(f"AI: {ai_reply}")
                if mem_result.facts_extracted > 0:
                    print(f"🧠 Stored {mem_result.facts_extracted} facts")
        """
        if not self._initialized:
            await self.initialize()
        
        try:
            extraction_result = await self._hook_engine.on_turn_end(
                user_message=user_message,
                assistant_response=assistant_response,
                force_extract=force,
            )
            
            return MemoryResult(
                success=True,
                facts_extracted=extraction_result.fact_count,
                facts_written=len(extraction_result.facts),
                processing_time_ms=extraction_result.processing_time_ms,
                message=extraction_result.summary() if extraction_result.should_extract 
                         else f"No extraction: {extraction_result.trigger_reason}",
                details={
                    "trigger": extraction_result.trigger_reason,
                    "types": [f.fact_type.value for f in extraction_result.facts],
                },
            )
            
        except Exception as e:
            logger.error(f"Memory error: {e}")
            
            if self.agent_config.on_error:
                await self.agent_config.on_error(e)
            
            return MemoryResult(
                success=False,
                message=f"Error: {e}",
            )
    
    async def query(self, question: str) -> str:
        """
        Query the Wiki knowledge base.
        
        Uses the Wiki content to answer questions based on accumulated memory.
        """
        if not self._initialized:
            await self.initialize()
        
        results = await self._shared_wiki.search_facts(question)
        
        if not results:
            return "No relevant information found in Wiki."
        
        context_parts = []
        for r in results[:5]:  # Top 5 matches
            page_content = await self._shared_wiki.read_page(r["path"])
            if page_content:
                context_parts.append(
                    f"### {r['name']}\n{page_content[:500]}..."
                )
        
        context = "\n\n".join(context_parts)
        
        # Use LLM to synthesize answer
        prompt = (
            f"Based on the following Wiki knowledge, answer the question.\n\n"
            f"## Question: {question}\n\n"
            f"## Relevant Wiki Content:\n{context}\n\n"
            f"Provide a clear, concise answer. If the Wiki doesn't contain "
            f"sufficient information, say so."
        )
        
        try:
            answer = await self._extractor._call_llm(prompt)
            return answer
        except Exception as e:
            return f"Wiki found {len(results)} relevant pages but synthesis failed: {e}"
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the memory system."""
        stats = {
            "initialized": self._initialized,
            "agent": {
                "id": self.agent_config.agent_id,
                "type": self.agent_config.agent_type.value,
            },
            "config": {
                "auto_extract": self.agent_config.auto_extract,
                "wiki_path": self.wiki_path,
            },
        }
        
        if self._hook_engine:
            stats["hook_engine"] = self._hook_engine.stats
        
        if self._extractor:
            stats["extraction"] = self._extractor.stats
        
        if self._shared_wiki:
            stats["wiki"] = self._shared_wiki.stats
            
            pages = await self._shared_wiki.list_pages()
            stats["wiki"]["total_pages"] = len(pages)
            
            total_size = sum(p["size_bytes"] for p in pages)
            stats["wiki"]["total_size_bytes"] = total_size
        
        return stats
    
    @property
    def hook_engine(self) -> "HookEngine":
        """Access the HookEngine for advanced usage (e.g., Agent-Native mode)."""
        return self._hook_engine
    
    @property
    def extractor(self) -> "FactExtractor":
        """Access the FactExtractor for direct use."""
        return self._extractor
    
    async def shutdown(self) -> None:
        """Gracefully shut down the memory system."""
        if self._hook_engine and self._initialized:
            session_stats = await self._hook_engine.on_session_end()
            logger.info(f"Session ended. Final stats: {session_stats}")
        
        self._initialized = False
        logger.info("Memory Core shut down")
    
    # ============================================================
    # DECORATOR INTEGRATION
    # ============================================================
    
    def hook(self, func=None, *, 
              extract_user_param: str = "message",
              extract_return_value: bool = True):
        """
        Decorator to add automatic memory to any async function.
        
        Usage:
            mc = MemoryCore(wiki_path="./wiki")
            
            @mc.hook
            async def chat(message: str) -> str:
                return await llm.generate(message)
            
            # Now every call to chat() automatically extracts & stores!
        """
        def decorator(async_func):
            if not asyncio.iscoroutinefunction(async_func):
                raise TypeError("@mc.hook can only decorate async functions")
            
            async def wrapper(*args, **kwargs):
                # Extract user message from arguments
                user_message = ""
                if extract_user_param in kwargs:
                    user_message = kwargs[extract_user_param]
                elif args:
                    user_message = str(args[0])
                
                # Call original function
                result = await async_func(*args, **kwargs)
                
                # Extract response
                response = str(result) if extract_return_value else ""
                
                # Auto-extract (fire and forget — don't block the response)
                if self.agent_config.auto_extract and (user_message or response):
                    try:
                        asyncio.create_task(
                            self.remember(user_message, response)
                        )
                    except Exception as e:
                        logger.debug(f"Background extraction failed: {e}")
                
                return result
            
            wrapper.__name__ = async_func.__name__
            wrapper.__doc__ = async_func.__doc__
            wrapper._memory_hooked = True
            
            return wrapper
        
        if func is not None:
            # Used as @mc.hock without parentheses
            return decorator(func)
        
        # Used as @mc.hock(...) with options
        return decorator
    
    # ============================================================
    # CONTEXT MANAGER
    # ============================================================
    
    async def __aenter__(self):
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
        return False


# Import dependencies
import os
from .extractor import FactExtractor
from .deduplicator import Deduplicator
from .shared_wiki import SharedWiki
from .memory_graph import MemoryGraph
from .hook_engine import HookEngine, HookEvent, HookResult
