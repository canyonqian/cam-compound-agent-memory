"""
Deduplicator — Prevent Memory Bloat & Handle Conflicts
========================================================

Key problem: If 3 Agents are all extracting from conversations,
you'll get tons of duplicates, contradictions, and near-duplicates.

This module handles:
1. Exact duplicate detection → skip
2. Near-duplicate detection → merge or supersede
3. Conflict resolution (Agent A says X, Agent B says not-X)
4. Fact lifecycle: active → superseded → archived

Design principle from Karpathy's LLM-Wiki:
"Supersede rather than delete" — keep history traceable.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("memory_core.deduplicator")


class MergeAction(Enum):
    """What to do with a new fact relative to existing ones."""
    KEEP_NEW = "keep_new"              # No conflict, add it
    SKIP_DUPLICATE = "skip_duplicate"   # Exact match exists
    MERGE = "merge"                     # Near-duplicate, merge into existing
    SUPERSEDE = "supersede"             # New version replaces old
    CONFLICT = "conflict"               # Contradiction detected!
    SPLIT = "split"                     # Related but distinct, keep both


@dataclass
class DedupResult:
    """Result of deduplicating a batch of new facts against existing Wiki."""
    
    unique_facts: List = field(default_factory=list)      # Facts to write
    duplicate_facts: List = field(default_factory=list)    # Skipped (exact dupes)
    merged_facts: List = field(default_factory=list)      # Merged into existing
    superseded_facts: List = field(default_factory=list)   # Old facts marked superseded
    conflicts: List = field(default_factory=list)          # Contradictions found
    
    @property
    def total_input(self) -> int:
        return (len(self.unique_facts) + len(self.duplicate_facts) +
                len(self.merged_facts) + len(self.superseded_facts))
    
    def summary(self) -> str:
        parts = []
        if self.unique_facts:
            parts.append(f"{len(self.unique_facts)} new")
        if self.duplicate_facts:
            parts.append(f"{len(self.duplicate_facts)} dupe(s)")
        if self.merged_facts:
            parts.append(f"{len(self.merged_facts)} merged")
        if self.superseded_facts:
            parts.append(f"{len(self.superseded_facts)} superseded")
        if self.conflicts:
            parts.append(f"⚠️ {len(self.conflicts)} CONFLICTS")
        return ", ".join(parts) if parts else "empty"


@dataclass
class ExistingFact:
    """A fact that already exists in the Wiki."""
    
    fact_id: str                        # SHA256 hash of content
    content: str
    fact_type: str
    source_file: str                     # Which wiki page this is in
    status: str = "active"              # active | superseded | archived
    superseded_by: Optional[str] = None  # ID of replacing fact
    first_seen: str = ""                 # ISO timestamp
    last_updated: str = ""
    agent_id: str = "unknown"
    times_confirmed: int = 1            # How many agents have confirmed this
    confidence: float = 0.8
    
    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            self.content.lower().strip().encode()
        ).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "content": self.content,
            "fact_type": self.fact_type,
            "source_file": self.source_file,
            "status": self.status,
            "superseded_by": self.superseded_by,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "agent_id": self.agent_id,
            "times_confirmed": self.times_confirmed,
            "confidence": self.confidence,
        }
    
    @classmethod
    def from_dict(cls, d: Dict) -> "ExistingFact":
        return cls(**{k: v for k, v in d.items() 
                      if k in cls.__dataclass_fields__})


class SimilarityEngine:
    """
    Multi-strategy similarity comparison for deduplication.
    
    Supports three modes (configurable via DedupConfig.similarity_method):
    - keyword: Fast keyword overlap (default, no external deps)
    - tfidf: TF-IDF vector cosine similarity (needs scikit-learn)
    - embedding: Semantic embedding similarity (needs API call)
    """
    
    def __init__(self, method: str = "keyword"):
        self.method = method
        self._tfidf_vectorizer = None
        self._embedding_cache: Dict[str, List[float]] = {}
        
        # Common stop words for keyword mode
        self._stop_words = set([
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "through", "during", "before", "after",
            "above", "below", "between", "out", "off", "over", "under",
            "again", "further", "then", "once", "here", "there", "when",
            "where", "why", "how", "all", "each", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own",
            "same", "so", "than", "too", "very", "just", "and", "but",
            "or", "if", "it", "its", "this", "that", "these", "those",
            "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
            "you", "your", "yours", "yourself", "yourselves", "he", "him",
            "his", "himself", "she", "her", "hers", "herself", "they",
            "them", "their", "theirs", "what", "which", "who", "whom",
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
            "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
            "你", "会", "着", "没有", "看", "好", "自己", "这",
        ])
    
    def compute(self, text_a: str, text_b: str) -> float:
        """
        Compute similarity between two texts.
        Returns float in [0.0, 1.0].
        """
        if not text_a or not text_b:
            return 0.0
        
        if self.method == "keyword":
            return self._keyword_similarity(text_a, text_b)
        elif self.method == "tfidf":
            return self._tfidf_similarity(text_a, text_b)
        elif self.method == "embedding":
            return self._embedding_similarity(text_a, text_b)
        else:
            return self._keyword_similarity(text_a, text_b)
    
    def _tokenize(self, text: str) -> set:
        """Tokenize text into a set of normalized tokens."""
        text = text.lower().strip()
        # Extract words (alphanumeric + CJK characters)
        tokens = re.findall(r'[a-zA-Z0-9_]+|[\u4e00-\u9fff]+', text)
        return set(t for t in tokens if t not in self._stop_words and len(t) > 1)
    
    def _keyword_similarity(self, a: str, b: str) -> float:
        """
        Jaccard similarity on keyword sets.
        Fast, no dependencies, good enough for most cases.
        """
        tokens_a = self._tokenize(a)
        tokens_b = self._tokenize(b)
        
        if not tokens_a or not tokens_b:
            return 0.0
        
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        
        jaccard = len(intersection) / len(union)
        
        # Bonus for exact substring matches
        shorter = min(len(a), len(b))
        longer = max(len(a), len(b))
        ratio = shorter / longer if longer > 0 else 0
        
        # Blend Jaccard (70%) with length ratio bonus (30%)
        return jaccard * 0.7 + ratio * 0.3
    
    def _tfidf_similarity(self, a: str, b: str) -> float:
        """TF-IDF cosine similarity (requires sklearn)."""
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity
            
            if self._tfidf_vectorizer is None:
                self._tfidf_vectorizer = TfidfVectorizer()
            
            tfidf_matrix = self._tfidf_vectorizer.fit_transform([a, b])
            sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])
            return float(sim[0][0])
            
        except ImportError:
            logger.warning("sklearn not available, falling back to keyword similarity")
            return self._keyword_similarity(a, b)
    
    async def _embedding_similarity(self, a: str, b: str) -> float:
        """Semantic embedding similarity (requires API)."""
        # This would call an embedding model API
        # For now, fall back to keyword
        logger.debug("Embedding similarity not implemented, using keyword")
        return self._keyword_similarity(a, b)


class ConflictDetector:
    """
    Detects contradictory statements between facts.
    
    Examples of contradictions:
    - "User prefers dark mode" vs "User prefers light mode"
    - "Chose Redis" vs "Chose Memcached"
    - "Project uses Python" vs "Project is written in Go"
    """
    
    # Negation/contradiction patterns
    CONTRADICTION_PATTERNS = [
        (r"prefers\s+(\w+)", r"prefers\s+(?!\\1)(\w+)"),
        (r"uses\s+(\w+)", r"(?:doesn't\s+use|not\s+using)\s+\\1"),
        (r"chose\s+(\w+)", r"(?:chose|decided\s+on)\s+(?!\\1)(\w+)"),
        (r"is\s+(\w+)", r"is\s+not\s+\\1"),
        (r"likes?\s+(\w+)", r"hates?|(?:doesn't\s+like)\s+\\1"),
        (r"(?:will|going to)\s+\w+", r"(?:won't|will not)\s+\\w+"),
    ]
    
    def check(self, new_fact: "ExtractedFact", 
               existing: "ExistingFact") -> bool:
        """Check if two facts contradict each other."""
        new_text = new_fact.content.lower().strip()
        exist_text = existing.content.lower().strip()
        
        # Quick check: if very similar but different key terms
        # might be a contradiction
        words_new = set(re.findall(r'\b\w+\b', new_text))
        words_exist = set(re.findall(r'\b\w+\b', exist_text))
        
        shared = words_new & words_exist
        if len(shared) < 3:
            # Too different to be a contradiction — just unrelated
            return False
        
        # Check for explicit negation patterns
        negation_words = {"not", "never", "no", "none", "neither", "nor",
                         "doesn't", "don't", "won't", "wouldn't", "couldn't",
                         "isn't", "aren't", "wasn't", "weren't",
                         "不", "没", "无", "非", "不是", "不会", "不要"}
        
        has_negation_in_one = (
            any(n in exist_text for n in negation_words) != 
            any(n in new_text for n in negation_words)
        )
        
        # High overlap + negation asymmetry = likely contradiction
        if has_negation_in_one and len(shared) >= 4:
            return True
        
        # Check preference contradictions specifically
        pref_patterns = [
            (r"prefers? (\w+)", r"prefers? (\w+)"),
            (r"likes? (\w+)", r"(?:hates?|dislikes?) (\w+)"),
            (r"chose? (\w+)", r"chose? (\w+)"),
        ]
        
        for pos_pattern, _ in pref_patterns:
            m_new = re.search(pos_pattern, new_text)
            m_exist = re.search(pos_pattern, exist_text)
            if m_new and m_exist and m_new.group(1) != m_exist.group(1):
                return True
        
        return False


class Deduplicator:
    """
    Main deduplication engine.
    
    Coordinates:
    - Similarity comparison (find near-duplicates)
    - Merge logic (combine complementary info)
    - Supersede tracking (replace old facts)
    - Conflict detection (flag contradictions)
    """
    
    def __init__(self, config=None, wiki_index=None):
        from .config import MemoryConfig, DEFAULT_CONFIG
        
        self.config = config or DEFAULT_CONFIG
        self.wiki_index = wiki_index  # Index of existing Wiki facts
        self.similarity = SimilarityEngine(
            method=self.config.deduplication.similarity_method
        )
        self.conflict_detector = ConflictDetector()
        self._stats = {
            "total_checked": 0,
            "duplicates_found": 0,
            "merges_performed": 0,
            "supersedes_performed": 0,
            "conflicts_detected": 0,
        }
    
    async def deduplicate(self, new_facts: list) -> DedupResult:
        """
        Main entry point: deduplicate new facts against existing Wiki.
        
        Parameters:
            new_facts: List of ExtractedFact from current extraction
        
        Returns:
            DedupResult with categorized facts
        """
        result = DedupResult()
        
        if not new_facts:
            return result
        
        # Load existing facts from index
        existing_facts = await self._load_existing_facts()
        
        for new_fact in new_facts:
            self._stats["total_checked"] += 1
            action, match = await self._classify(new_fact, existing_facts)
            
            if action == MergeAction.SKIP_DUPLICATE:
                result.duplicate_facts.append((new_fact, match))
                self._stats["duplicates_found"] += 1
                
            elif action == MergeAction.MERGE:
                result.merged_facts.append((new_fact, match))
                self._stats["merges_performed"] += 1
                # Merged fact goes into unique (with updated content)
                merged = await self._merge_facts(new_fact, match)
                result.unique_facts.append(merged)
                
            elif action == MergeAction.SUPERSEDE:
                result.superseded_facts.append((new_fact, match))
                self._stats["supersedes_performed"] += 1
                result.unique_facts.append(new_fact)  # New fact replaces old
                
            elif action == MergeAction.CONFLICT:
                result.conflicts.append((new_fact, match))
                self._stats["conflicts_detected"] += 1
                # Still write the new fact, but flag the conflict
                new_fact.tags.append("CONFLICT")
                new_fact.tags.append(f"contradicts:{match.fact_id}")
                result.unique_facts.append(new_fact)
                
            else:  # KEEP_NEW or SPLIT
                result.unique_facts.append(new_fact)
        
        logger.info(f"Dedup complete: {result.summary()}")
        return result
    
    async def _classify(self, new_fact, existing_facts: list) \
            -> Tuple[MergeAction, Optional[ExistingFact]]:
        """Classify what to do with a new fact."""
        best_match = None
        best_sim = 0.0
        
        for existing in existing_facts:
            if existing.status != "active":
                continue
            
            sim = self.similarity.compute(new_fact.content, existing.content)
            
            if sim > best_sim:
                best_sim = sim
                best_match = existing
        
        cfg = self.config.deduplication
        
        if best_match:
            # Check for contradiction FIRST (higher priority than similarity)
            if self.conflict_detector.check(new_fact, best_match):
                return MergeAction.CONFLICT, best_match
            
            if sim >= cfg.exact_match_threshold:
                return MergeAction.SKIP_DUPLICATE, best_match
                
            elif sim >= cfg.near_duplicate_threshold:
                # Decide: merge or supersede?
                if new_fact.confidence > best_match.confidence + 0.15:
                    # New one is much more confident → supersede
                    return MergeAction.SUPERSEDE, best_match
                else:
                    return MergeAction.MERGE, best_match
                    
            elif sim >= cfg.merge_threshold:
                return MergeAction.SPLIT, best_match
        
        # No significant match found
        return MergeAction.KEEP_NEW, None
    
    async def _merge_facts(self, new_fact, existing: ExistingFact):
        """Merge a new fact into an existing one, producing enriched output."""
        # Combine tags
        merged_tags = list(set(existing.__dict__.get('tags', []) + new_fact.tags))
        
        # Boost confidence if both agree
        merged_confidence = min(0.99, 
                                (new_fact.confidence + existing.confidence) / 2 + 0.05)
        
        # Increment confirmation count
        merged = type(new_fact)(
            fact_type=new_fact.fact_type,
            content=new_fact.content,  # Keep newer wording
            confidence=merged_confidence,
            source_text=new_fact.source_text,
            context=f"{existing.content} // MERGED WITH: {new_fact.context}",
            tags=merged_tags,
            entities_mentioned=list(set(
                new_fact.entities_mentioned + 
                existing.__dict__.get('entities_mentioned', [])
            )),
            agent_id=new_fact.agent_id,
            turn_id=new_fact.turn_id,
        )
        merged.tags.append("merged")
        
        return merged
    
    async def _load_existing_facts(self) -> List[ExistingFact]:
        """Load existing facts from Wiki index or by scanning wiki directory."""
        if self.wiki_index:
            try:
                return await self.wiki_index.get_all_facts()
            except Exception as e:
                logger.warning(f"Failed to load from wiki_index, falling back to scan: {e}")

        # Fallback: scan wiki directories directly
        facts = []
        wiki_path = Path(self.config.storage.wiki_path) if self.config else None
        if not wiki_path or not wiki_path.exists():
            return facts

        for subdir in ["concept", "entity", "synthesis"]:
            dir_path = wiki_path / subdir
            if not dir_path.exists():
                continue

            for md_file in dir_path.glob("*.md"):
                try:
                    content = md_file.read_text(encoding="utf-8")
                    blocks = content.split("---")
                    for block in blocks:
                        block = block.strip()
                        if len(block) > 20 and not block.startswith("#") and not block.startswith("Auto-generated"):
                            lines = [l.strip() for l in block.split("\n") if l.strip()]
                            if lines:
                                ef = ExistingFact(
                                    fact_id=hashlib.sha256(block.encode()).hexdigest()[:16],
                                    content=lines[0][:200] if lines else block[:200],
                                    fact_type=subdir[:-1] if subdir != "synthesis" else "decision",
                                    source_file=str(md_file.relative_to(wiki_path)),
                                    status="active",
                                )
                                facts.append(ef)
                except Exception as e:
                    logger.debug(f"Error reading {md_file}: {e}")

        logger.info(f"Deduplicator loaded {len(facts)} existing facts from Wiki scan")
        return facts
    
    @property
    def stats(self) -> Dict[str, Any]:
        return dict(self._stats)


# Need ExtractedFact reference for type hints
# Import at bottom
