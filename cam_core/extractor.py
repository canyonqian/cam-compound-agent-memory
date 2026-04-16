"""
Fact Extractor — The Brain of Automatic Memory
================================================

Analyzes conversation turns and extracts structured knowledge:
  - Facts: "User prefers Python over JavaScript"
  - Concepts: "Event-driven architecture decouples components"
  - Decisions: "Chose PostgreSQL for the analytics database"
  - Preferences: "User likes concise code comments"
  - Tasks: "Implement rate limiting middleware"
  - Entities: "Project Alpha, Team Bravo, Tool X"

## Two Extraction Modes

### Mode 1: Agent-Native (Recommended, Zero Cost)
    The hosting Agent uses its OWN LLM capability to extract facts during
    normal conversation flow. No extra API call needed.

    How it works:
      1. Agent receives user message
      2. Agent generates response (normal chat)
      3. Agent ALSO runs internal extraction prompt on same conversation turn
      4. Passes extracted facts directly to MemoryCore.remember()

    Integration examples:
      # In Claude Code / Cursor / any AI agent:
      mc = MemoryCore(wiki_path="./wiki")

      # After each response, agent calls extract_from_agent():
      facts = mc.extractor.extract_from_agent(
          user_message=msg,
          assistant_response=response,
          extracted_facts=[  # <-- Agent itself produced these!
              {"fact_type": "decision", "content": "User chose Redis for caching",
               "confidence": 0.9},
              {"fact_type": "preference", "content": "User prefers async/await",
               "confidence": 0.85},
          ]
      )
      await mc.store(facts)

### Mode 2: LLM Fallback (Optional, For Standalone Use)
    If no Agent is available or you want a separate (cheaper) model,
    falls back to calling OpenAI/Anthropic/Ollama API.

    Requires one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, or local Ollama.

This dual-mode design means:
  - When embedded in an AI Agent → ZERO extra cost (uses Agent's own brain)
  - When running standalone → Works with any LLM provider
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger("cam_core.extractor")


class FactType(Enum):
    """Types of knowledge extracted from conversations."""

    FACT = "fact"  # Factual statements about the world/user
    CONCEPT = "concept"  # Technical/domain concepts explained
    DECISION = "decision"  # Choices made with reasoning
    PREFERENCE = "preference"  # User's style/behavioral preferences
    TASK = "task"  # Action items / TODOs
    ENTITY = "entity"  # Named entities (people, projects, tools)
    PROBLEM = "problem"  # Errors, bugs, failures encountered
    SOLUTION = "solution"  # Fixes, workarounds, successful approaches
    CONVENTION = "convention"  # Project conventions, coding style, workflows
    EVENT = "event"  # Factual events, milestones, releases
    INSIGHT = "insight"  # Lessons learned, key takeaways, observations


@dataclass
class ExtractedFact:
    """A single piece of knowledge extracted from conversation."""

    fact_type: FactType
    content: str  # The fact text itself
    confidence: float  # 0.0 - 1.0, LLM's confidence score
    source_text: str  # Original conversation text that produced this
    context: str = ""  # Surrounding conversation for disambiguation
    tags: List[str] = field(default_factory=list)  # Auto-generated tags
    entities_mentioned: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    agent_id: str = "unknown"  # Which Agent extracted this
    turn_id: str = ""  # Conversation turn identifier

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_type": self.fact_type.value,
            "content": self.content,
            "confidence": self.confidence,
            "source_text": self.source_text[:200],  # Truncate for storage
            "context": self.context[:300],
            "tags": self.tags,
            "entities_mentioned": self.entities_mentioned,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "turn_id": self.turn_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExtractedFact":
        return cls(
            fact_type=FactType(d["fact_type"]),
            content=d["content"],
            confidence=d.get("confidence", 0.8),
            source_text=d.get("source_text", ""),
            context=d.get("context", ""),
            tags=d.get("tags", []),
            entities_mentioned=d.get("entities_mentioned", []),
            timestamp=d.get("timestamp", ""),
            agent_id=d.get("agent_id", "unknown"),
            turn_id=d.get("turn_id", ""),
        )


@dataclass
class ExtractionResult:
    """Result of an extraction operation on a conversation turn."""

    facts: List[ExtractedFact] = field(default_factory=list)
    should_extract: bool = False  # Whether extraction was triggered
    trigger_reason: str = ""  # Why extraction happened (or didn't)
    tokens_analyzed: int = 0
    processing_time_ms: float = 0.0
    mode: str = "unknown"  # "agent_native" | "llm_fallback" | "rule_based"

    @property
    def fact_count(self) -> int:
        return len(self.facts)

    def summary(self) -> str:
        if not self.facts:
            return f"No extraction ({self.trigger_reason})"
        types = [f.fact_type.value for f in self.facts]
        return f"{len(self.facts)} facts ({', '.join(types)}) [{self.trigger_reason}]"


# ============================================================
# Extraction Prompts — Designed for Agent Self-Extraction
# ============================================================

EXTRACTION_SYSTEM_PROMPT = """You are a knowledge extraction engine. Your job is to identify \
valuable, persistent information from conversations and structure it as JSON.

Analyze the conversation and extract facts worth remembering long-term. Focus on:

**Decisions & Preferences:**
- Decisions made (with reasoning)
- User preferences and patterns

**Technical Knowledge:**
- Technical concepts explained
- Problems encountered (bugs, errors, failures)
- Solutions that worked (fixes, workarounds, configs)
- Project conventions (coding style, workflows, standards)

**Facts & Events:**
- Named entities and their relationships
- Factual events (releases, milestones, deadlines)
- Insights and lessons learned
- Action items and tasks

Rules:
1. Only extract information that has LASTING value (not transient greetings etc.)
2. Each fact should be atomic (one piece of info per fact)
3. Assign confidence 0.5-1.0 based on how clearly stated the information is
4. Include relevant tags for easy retrieval
5. Skip trivial exchanges like greetings, acknowledgments, simple Q&A

Output ONLY valid JSON:
{
  "facts": [
    {
      "fact_type": "decision|fact|concept|preference|task|entity|problem|solution|convention|event|insight",
      "content": "The fact text (complete sentence)",
      "confidence": 0.85,
      "tags": ["tag1", "tag2"],
      "entities_mentioned": ["entity1"]
    }
  ]
}

If nothing worth extracting, output: {"facts": []}"""

# --- Prompt for AGENT SELF-EXTRACTION (Mode 1) ---
AGENT_EXTRACTION_PROMPT = """\
[MEMORY CORE EXTRACTION REQUEST]

You are currently running inside an Agent that has MemoryCore enabled.
The conversation just happened. Using YOUR own intelligence (no external API call needed),
extract any valuable knowledge from this exchange.

CONVERSATION:
--- User said ---
{user_message}
--- You responded ---
{assistant_response}

Extract structured facts using this EXACT JSON format (output only the JSON, nothing else):
{{"facts": [{{"fact_type": "decision|fact|concept|preference|task|entity|problem|solution|convention|event|insight", "content": "...", "confidence": 0.0-1.0, "tags": ["..."], "entities_mentioned": ["..."]}}]}}

Guidelines:
- Extract: decisions, preferences, technical concepts, problems/solutions, conventions, events, insights
- SKIP: greetings, thanks, "ok", "sure", simple acknowledgments
- Each fact = one clear, complete statement
- For problems: capture what went wrong and any error messages
- For solutions: capture what fixed it
- For conventions: capture project-specific patterns ("we always...", "the convention is...")
- confidence: 0.9+ if explicitly stated, 0.7-0.9 if implied, 0.5-0.7 if inferred
- If nothing is worth remembering: {{"facts": []}}
"""


class FactExtractor:
    """
    Dual-mode fact extractor.

    Mode 1 (Agent-Native): Accepts pre-extracted facts from the hosting Agent.
        Zero extra cost. Recommended for all Agent integrations.

    Mode 2 (LLM Fallback): Calls an external LLM API for extraction.
        Useful for standalone usage or when Agent cannot do self-extraction.
    """

    def __init__(self, config=None, llm_client=None):
        from .config import MemoryConfig

        self.config = config or MemoryConfig()
        self.llm_client = llm_client  # Optional external client

        self._stats = {
            "total_extractions": 0,
            "total_facts_found": 0,
            "agent_native_count": 0,
            "llm_fallback_count": 0,
            "rule_based_count": 0,
            "errors": 0,
        }

    # ================================================================
    # MODE 1: Agent-Native Extraction (Zero Cost)
    # ================================================================

    def extract_from_agent(
        self,
        user_message: str,
        assistant_response: str,
        extracted_facts: Optional[List[Dict]] = None,
        agent_id: str = "default",
        turn_id: str = "",
    ) -> ExtractionResult:
        """
        Accept facts extracted by the hosting Agent itself.

        This is the PRIMARY recommended mode. The Agent uses its own LLM
        intelligence to analyze the conversation and produce extracted facts,
        then passes them here for deduplication and storage.

        Args:
            user_message: What the user said
            assistant_response: What the Agent replied
            extracted_facts: List of dict facts from Agent's own analysis
                              Each dict: {"fact_type": "...", "content": "...", ...}
            agent_id: Identifier of the extracting Agent
            turn_id: Conversation turn identifier

        Returns:
            ExtractionResult with validated, typed ExtractedFact objects

        Example (inside an Agent's chat loop):
            # Agent just generated its response
            response = await llm.chat(user_message)

            # Agent also extracts (using its own intelligence, no extra API call!)
            raw_facts = await llm.extract(AGENT_EXTRACTION_PROMPT.format(...))

            # Feed into MemoryCore
            result = mc.extractor.extract_from_agent(user_message, response, raw_facts)
            await mc.store(result.facts)
        """
        start = time.time()
        result = ExtractionResult(mode="agent_native")
        combined_text = f"{user_message} {assistant_response}"
        result.tokens_analyzed = len(combined_text.split())

        if extracted_facts is None:
            result.should_extract = False
            result.trigger_reason = "no_facts_provided_by_agent"
            self._stats["agent_native_count"] += 1
            return result

        try:
            parsed_facts = self._parse_extraction_response(
                json.dumps({"facts": extracted_facts}) if isinstance(extracted_facts, list) else extracted_facts,
                source_text=combined_text,
                agent_id=agent_id,
            )

            # Apply quality filters
            filtered = self._filter_by_quality(parsed_facts)

            # Set turn IDs
            for f in filtered:
                f.turn_id = turn_id or f"agent_{self._stats['total_extractions']}"

            result.facts = filtered
            result.should_extract = len(filtered) > 0
            result.trigger_reason = (
                f"agent_provided_{len(filtered)}_facts" if filtered else "all_facts_filtered_by_quality"
            )

            self._stats["total_facts_found"] += len(filtered)
            self._stats["agent_native_count"] += 1
            logger.info(f"[Agent-Native] Extracted {len(filtered)} facts from Agent")

        except Exception as e:
            logger.error(f"[Agent-Native] Fact parsing failed: {e}")
            result.trigger_reason = f"parse_error: {e}"
            self._stats["errors"] += 1

        result.processing_time_ms = (time.time() - start) * 1000
        self._stats["total_extractions"] += 1
        return result

    def get_extraction_prompt(self, user_message: str, assistant_response: str) -> str:
        """
        Return the formatted extraction prompt for the Agent to execute.

        The Agent should feed this prompt into its OWN LLM (same one it uses for chat),
        get back JSON, then call extract_from_agent() with the result.

        This is the "one-hop" pattern: Agent→Agent's own LLM→MemoryCore
        No external API, no extra cost.
        """
        return AGENT_EXTRACTION_PROMPT.format(
            user_message=user_message,
            assistant_response=assistant_response,
        )

    # ================================================================
    # MODE 2: LLM Fallback (External API)
    # ================================================================

    async def extract(
        self,
        user_message: str,
        assistant_response: str,
        history: List[Dict] = None,
        agent_id: str = "default",
        force: bool = False,
    ) -> ExtractionResult:
        """
        Full extraction pipeline with LLM fallback.

        Tries Mode 1 (Agent native) first if facts are available via hook context,
        otherwise falls back to Mode 2 (external LLM API).

        Args:
            user_message: User's message in this turn
            assistant_response: Assistant's reply
            history: Recent conversation for context
            agent_id: Which agent is doing the extraction
            force: Force extraction even for short messages

        Returns:
            ExtractionResult with extracted facts
        """
        start = time.time()
        result = ExtractionResult(mode="llm_fallback")
        combined_text = f"{user_message} {assistant_response}"
        result.tokens_analyzed = len(combined_text.split())

        # Step 1: Should we extract?
        if not force and not self.should_extract(user_message, assistant_response):
            result.should_extract = False
            result.trigger_reason = "below_threshold"
            result.processing_time_ms = (time.time() - start) * 1000
            return result

        result.should_extract = True

        try:
            # Step 2: Call LLM (external API)
            user_prompt = self._build_extraction_prompt(user_message, assistant_response, history)

            raw_response = await self._call_llm(user_prompt)

            # Step 3: Parse response into facts
            parsed_facts = self._parse_extraction_response(raw_response, combined_text, agent_id)

            # Step 4: Quality filtering
            filtered_facts = self._filter_by_quality(parsed_facts)

            # Step 5: Set metadata
            for f in filtered_facts:
                f.turn_id = f"turn_{self._stats['total_extractions']}"
                f.agent_id = agent_id

            result.facts = filtered_facts
            result.trigger_reason = "llm_extraction_complete"

            self._stats["total_facts_found"] += len(filtered_facts)
            self._stats["llm_fallback_count"] += 1

            if self.config.log_extraction:
                logger.info(f"[LLM-Fallback] {result.summary()} [{result.trigger_reason}]")

        except Exception as e:
            logger.error(f"[LLM-Fallback] Extraction failed: {e}")
            result.trigger_reason = f"extraction_error: {e}"
            self._stats["errors"] += 1

        result.processing_time_ms = (time.time() - start) * 1000
        self._stats["total_extractions"] += 1
        return result

    async def _call_llm(self, user_prompt: str) -> str:
        """
        Call the configured LLM for extraction.

        Uses injected llm_client if available, otherwise falls back
        to built-in HTTP clients for OpenAI/Anthropic/Ollama.
        """
        if self.llm_client:
            return await self.llm_client.chat(
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=self.config.llm_temperature,
                max_tokens=2000,
                response_format={"type": "json_object"},
            )

        return await self._call_llm_fallback(user_prompt)

    async def _call_llm_fallback(self, user_prompt: str) -> str:
        """Fallback LLM caller using environment-detected provider."""

        provider = self.config.llm_provider
        model = self.config.llm_model

        if provider == "auto":
            provider = self._detect_available_provider()

        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            return await self._openai_call(base_url, api_key, model, user_prompt)

        elif provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            model = model or "claude-sonnet-4-20250514"
            return await self._anthropic_call(api_key, model, user_prompt)

        elif provider == "ollama":
            base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            model = model or os.environ.get("OLLAMA_MODEL", "llama3")
            return await self._ollama_call(base_url, model, user_prompt)

        else:
            raise RuntimeError(
                "No LLM provider available. "
                "Use Agent-Native mode (extract_from_agent), or set "
                "OPENAI_API_KEY / ANTHROPIC_API_KEY / run Ollama locally."
            )

    async def _openai_call(self, base_url, api_key, model, prompt):
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.config.llm_temperature,
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def _anthropic_call(self, api_key, model, prompt):
        import httpx

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 2000,
                    "system": EXTRACTION_SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    async def _ollama_call(self, base_url, model, prompt):
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{base_url}/api/chat",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": self.config.llm_temperature},
                },
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]

    def _detect_available_provider(self) -> str:
        """Auto-detect which LLM provider is available via env vars."""
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        try:
            import httpx

            resp = httpx.get("http://localhost:11434/api/tags", timeout=2)
            if resp.status_code == 200:
                return "ollama"
        except Exception:
            pass
        raise RuntimeError(
            "No LLM provider detected for fallback mode. "
            "Recommended: Use Agent-Native mode instead (extract_from_agent). "
            "Or set one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, or run Ollama."
        )

    # ================================================================
    # Rule-Based Fast Path (No LLM at all)
    # ================================================================

    def should_extract(self, user_message: str, assistant_response: str) -> Tuple[bool, str]:
        """
        Quick rule-based check: does this conversation contain memorable info?

        This is the FIRST gate before any LLM call. Filters out ~70% of
        trivial exchanges (greetings, acknowledgments, etc.) instantly,
        at zero cost.
        """
        rules = self.config.extraction
        combined = f"{user_message} {assistant_response}".lower()

        # Length check
        if len(combined.strip()) < rules.min_exchange_length:
            return False, "too_short"

        # Trivial pattern detection
        trivial_patterns = [
            r"^(hi|hello|hey|thanks|thank you|ok|okay|sure|yes|no|bye|goodbye)[\s!.,?]*$",
            r"^(got it|understood|sounds good|alright|cool|nice|great|perfect)[\s!.,?]*$",
            r"^(what|how|why|when|where|who)\s+(are|is|was|were|did|do|does)\s+(you|it|that|this)\??",
        ]
        for pattern in trivial_patterns:
            if re.match(pattern, combined.strip()):
                return False, "trivial_exchange"

        # Signal detection — look for indicators of valuable content
        signal_patterns = [
            # Decision signals
            r"(decided|chose|choose|selected|going with|going to use|will use|prefer|using)\b",
            r"(i think|i believe|my opinion|in my view|we should|let's go with)\b",
            # Preference signals
            r"(like|love|hate|don't like|prefer not|always|never|usually)\b",
            # Task signals
            r"(need to|have to|must|should|todo|to-do|task|implement|build|create|fix)\b",
            # Concept/explanation signals
            r"(basically|essentially|the idea is|means that|works by|architecture|pattern|design)\b",
            # Entity signals
            r"(project|team|company|tool|library|framework|service|api|database|server)\b",
            # Problem signals (bugs, errors, failures)
            r"(error|bug|issue|crash|fail(ed|ure)?|broken|doesn'?t work|problem|wrong|traceback|exception|stack trace)\b",
            # Solution signals (fixes, workarounds)
            r"(fixed|solved|workaround|patch|resolved|the fix is|turns out|instead of|switched to)\b",
            # Convention signals (standards, workflows)
            r"(convention|standard|practice|style guide|always do|never do|the way we|our process|the rule is)\b",
            # Event signals (milestones, releases)
            r"(released|launched|deployed|meeting|deadline|milestone|shipped|announced|version)\b",
            # Insight signals (lessons learned)
            r"(learned|discovered|key takeaway|important|note|remember|lesson|pitfall|gotcha|trick)\b",
        ]

        signal_count = sum(1 for p in signal_patterns if re.search(p, combined))
        if signal_count < rules.min_signal_count:
            return False, "too_few_signals"

        return True, f"signals_detected({signal_count})"

    # ================================================================
    # Shared Utilities
    # ================================================================

    def _parse_extraction_response(self, raw_response: str, source_text: str, agent_id: str) -> List[ExtractedFact]:
        """Parse LLM/Agent JSON response into ExtractedFact objects."""
        try:
            json_match = re.search(r"\{[\s\S]*\}", raw_response)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(raw_response)

            facts = []
            for item in data.get("facts", []):
                fact = ExtractedFact(
                    fact_type=FactType(item.get("fact_type", "fact")),
                    content=item.get("content", "").strip(),
                    confidence=float(item.get("confidence", 0.8)),
                    source_text=item.get("source_text", source_text)[:200],
                    context="",
                    tags=item.get("tags", []),
                    entities_mentioned=item.get("entities_mentioned", []),
                    agent_id=agent_id,
                )
                facts.append(fact)

            return facts

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction JSON: {e}")
            return []

    def _filter_by_quality(self, facts: List[ExtractedFact]) -> List[ExtractedFact]:
        """Filter out low-quality extractions."""
        rules = self.config.extraction
        filtered = []

        for f in facts:
            if f.confidence < rules.min_confidence:
                continue
            if len(f.content) < rules.min_fact_length:
                continue
            if len(f.content) > rules.max_fact_length:
                f.content = f.content[: rules.max_fact_length] + "..."
            if not f.content.strip() or f.content.strip() in (".", "!", "?"):
                continue
            filtered.append(f)

        return filtered

    def _build_extraction_prompt(self, user_message: str, assistant_response: str, history: List[Dict] = None) -> str:
        """Build the full extraction prompt for LLM."""
        recent_context = self._format_recent_context(history)

        prompt = f"""## Latest Exchange
**User:** {user_message}

**Assistant:** {assistant_response}
"""
        if recent_context:
            prompt += f"""
## Recent Context (for disambiguation)
{recent_context}
"""
        prompt += """

## Instructions
Analyze the above conversation and extract ALL facts, decisions, preferences, concepts, tasks, and entities worth remembering. Output JSON only."""
        return prompt

    def _format_recent_context(self, history: List[Dict] = None) -> str:
        """Format recent conversation history as context for extraction."""
        if not history:
            return ""
        lines = []
        for turn in history[-5:]:
            role = turn.get("role", "unknown")
            content = turn.get("content", "")[:200]
            lines.append(f"- **{role}**: {content}")
        return "\n".join(lines)

    @property
    def stats(self) -> Dict[str, Any]:
        """Return extraction statistics."""
        return dict(self._stats)


# Need os for env var checks
import os
