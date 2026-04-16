"""
Memory Graph — Knowledge Graph Builder
=======================================

Builds and maintains a knowledge graph from extracted facts.
Tracks relationships between:
  - Entities (people, projects, tools)
  - Concepts (ideas, patterns, technologies)
  - Facts that link them together

The graph enables:
  - "What do we know about X?" queries
  - "How does A relate to B?" traversal
  - Mermaid diagram generation for visualization in Wiki pages

Graph is persisted as JSON and can be exported to:
  - Mermaid diagrams (for Markdown Wiki rendering)
  - Graphviz DOT format
  - D3.js interactive graphs
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("cam_core.graph")


@dataclass
class GraphNode:
    """A node in the knowledge graph."""

    id: str  # Unique ID (hash-based)
    label: str  # Display name
    node_type: str  # entity | concept | fact | decision | preference
    content: str = ""  # Full text content
    source_file: str = ""  # Origin wiki page
    tags: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_updated: str = ""
    weight: int = 1  # Number of times confirmed
    agent_contributors: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.node_type,
            "content": self.content[:300],
            "source_file": self.source_file,
            "tags": self.tags,
            "first_seen": self.first_seen,
            "last_updated": self.last_updated,
            "weight": self.weight,
            "agents": list(self.agent_contributors),
        }


@dataclass
class GraphEdge:
    """An edge (relationship) between two nodes."""

    source_id: str
    target_id: str
    relation: str = "related_to"  # Semantic relationship type
    strength: float = 0.5  # 0.0 - 1.0
    first_seen: str = ""
    source_fact: str = ""  # The fact that created this edge

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_id,
            "target": self.target_id,
            "relation": self.relation,
            "strength": self.strength,
            "source_fact": self.source_fact[:100],
        }


# Relationship types
RELATION_TYPES = [
    "related_to",  # General association
    "uses",  # Entity A uses Entity B
    "is_a",  # Is a type of
    "part_of",  # Is part of
    "decided_on",  # Decision about
    "prefers",  # Preference toward
    "mentions",  # Textual mention
    "contradicts",  # Contradicts
    "supersedes",  # Replaces/updates
    "similar_to",  # Similar concept
    "depends_on",  # Dependency
    "implemented_by",  # Implementation
]


class MemoryGraph:
    """
    Knowledge graph built from conversation extractions.

    Automatically maintains relationships as facts flow in.
    Supports querying, visualization export, and persistence.
    """

    def __init__(self, graph_path: str = None):
        self.graph_path = graph_path or ".cam_core/graph.json"

        # Core data structures
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: List[GraphEdge] = []

        # Index for fast lookups
        self._label_index: Dict[str, str] = {}  # label → node_id
        self._type_index: Dict[str, List[str]] = defaultdict(list)  # type → [node_ids]

        # Statistics
        self._stats = {
            "nodes_added": 0,
            "edges_added": 0,
            "queries_served": 0,
        }

        # Load existing graph if available
        self._load()

    async def add_facts(self, facts: list) -> int:
        """Add extracted facts to the graph, creating nodes and edges."""
        edges_created = 0

        for fact in facts:
            # Create or find entity nodes from mentions
            entity_nodes = []
            for entity_name in fact.entities_mentioned:
                node = self._get_or_create_node(
                    id=self._node_id("entity", entity_name),
                    label=entity_name,
                    node_type="entity",
                    content=fact.content,
                    tags=fact.tags,
                    agent_id=fact.agent_id,
                )
                entity_nodes.append(node)

            # Create concept/fact node from the fact itself
            fact_node = self._get_or_create_node(
                id=self._node_id(fact.fact_type.value, fact.content),
                label=fact.content[:60] + ("..." if len(fact.content) > 60 else ""),
                node_type=fact.fact_type.value,
                content=fact.content,
                tags=fact.tags + [fact.fact_type.value],
                agent_id=fact.agent_id,
            )

            # Create edges: fact → entities it mentions
            for entity_node in entity_nodes:
                edge = self._add_edge(
                    source_id=fact_node.id,
                    target_id=entity_node.id,
                    relation="mentions",
                    source_fact=fact.content,
                )
                if edge:
                    edges_created += 1

            # Create edges between co-mentioned entities (they're related)
            for i, node_a in enumerate(entity_nodes):
                for node_b in entity_nodes[i + 1 :]:
                    edge = self._add_edge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        relation="related_to",
                        source_fact=fact.content,
                        strength=0.3,  # Weak default, strengthens over time
                    )
                    if edge:
                        edges_created += 1

        if edges_created > 0:
            self._save()

        return edges_created

    def _get_or_create_node(
        self,
        id: str,
        label: str,
        node_type: str,
        content: str = "",
        tags: List[str] = None,
        agent_id: str = "",
    ) -> GraphNode:
        """Get an existing node or create a new one."""
        now = datetime.utcnow().isoformat()

        if id in self._nodes:
            # Update existing node
            node = self._nodes[id]
            node.last_updated = now
            node.weight += 1
            if agent_id:
                node.agent_contributors.add(agent_id)
            if tags:
                node.tags = list(set(node.tags + tags))
            return node

        # Create new node
        node = GraphNode(
            id=id,
            label=label,
            node_type=node_type,
            content=content,
            tags=tags or [],
            first_seen=now,
            last_updated=now,
            agent_contributors={agent_id} if agent_id else set(),
        )

        self._nodes[id] = node
        self._label_index[label.lower()] = id
        self._type_index[node_type].append(id)
        self._stats["nodes_added"] += 1

        return node

    def _add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        source_fact: str = "",
        strength: float = 0.5,
    ) -> Optional[GraphEdge]:
        """Add an edge between two nodes (or strengthen existing)."""
        # Check for duplicate edge
        for edge in self._edges:
            if (edge.source_id == source_id and edge.target_id == target_id) or (
                edge.source_id == target_id and edge.target_id == source_id
            ):
                # Strengthen existing edge
                edge.strength = min(1.0, edge.strength + 0.15)
                edge.last_seen = datetime.utcnow().isoformat() if not hasattr(edge, "last_seen") else ""
                return None

        now = datetime.utcnow().isoformat()
        edge = GraphEdge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            strength=strength,
            first_seen=now,
            source_fact=source_fact,
        )

        self._edges.append(edge)
        self._stats["edges_added"] += 1
        return edge

    def query(self, query_str: str, max_results: int = 10) -> List[Dict]:
        """
        Query the knowledge graph.

        Searches by label match, content match, and tag match.
        Returns matching nodes with their connections.
        """
        self._stats["queries_served"] += 1
        query_lower = query_str.lower().strip()

        results = []

        # Direct label matches
        for node_id, node in self._nodes.items():
            score = 0.0

            # Label exact/partial match
            if query_lower in node.label.lower():
                score = max(score, 0.9 if node.label.lower() == query_lower else 0.7)

            # Content match
            if query_lower in node.content.lower():
                score = max(score, 0.5)

            # Tag match
            if any(query_lower in t.lower() for t in node.tags):
                score = max(score, 0.6)

            # Type match
            if query_lower == node.node_type.lower():
                score = max(score, 0.8)

            if score > 0:
                # Get connected nodes
                connections = self.get_connections(node_id, depth=1)

                results.append(
                    {
                        **node.to_dict(),
                        "relevance_score": score,
                        "connections": connections,
                    }
                )

        # Sort by relevance
        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return results[:max_results]

    def get_connections(self, node_id: str, depth: int = 1) -> List[Dict]:
        """Get nodes connected to a given node up to specified depth."""
        visited = {node_id}
        connections = []

        current_level = {node_id}
        for _ in range(depth):
            next_level = set()

            for current_id in current_level:
                for edge in self._edges:
                    other_id = None

                    if edge.source_id == current_id:
                        other_id = edge.target_id
                    elif edge.target_id == current_id:
                        other_id = edge.source_id

                    if other_id and other_id not in visited:
                        visited.add(other_id)
                        next_level.add(other_id)

                        other_node = self._nodes.get(other_id)
                        if other_node:
                            connections.append(
                                {
                                    **other_node.to_dict(),
                                    "relation": edge.relation,
                                    "strength": edge.strength,
                                }
                            )

            current_level = next_level

        return connections

    def generate_mermaid(self, center_node_id: str = None, max_nodes: int = 20) -> str:
        """
        Generate a Mermaid diagram of the graph.

        Can be embedded directly in Wiki Markdown pages for rendering.
        """
        lines = ["graph LR"]

        # Select nodes to include
        if center_node_id:
            # BFS from center node
            included = {center_node_id}
            queue = [center_node_id]

            while queue and len(included) < max_nodes:
                current = queue.pop(0)
                conns = self.get_connections(current, depth=1)

                for conn in conns:
                    if conn["id"] not in included:
                        included.add(conn["id"])
                        queue.append(conn["id"])

            selected_ids = included
        else:
            # Take top N nodes by weight
            sorted_nodes = sorted(self._nodes.values(), key=lambda n: n.weight, reverse=True)[:max_nodes]
            selected_ids = {n.id for n in sorted_nodes}

        # Map IDs to short labels for Mermaid compatibility
        id_map = {}
        for nid in selected_ids:
            node = self._nodes[nid]
            safe_label = node.label.replace('"', "'").replace(" ", "_")[:20]
            mermaid_id = f"N{list(selected_ids).index(nid)}"
            id_map[nid] = mermaid_id

            type_emoji = {
                "entity": "🏷️",
                "concept": "💡",
                "fact": "📌",
                "decision": "✅",
                "preference": "🎯",
                "task": "📋",
            }.get(node.node_type, "📝")

            lines.append(f'    {mermaid_id}("{type_emoji} {safe_label}")')

        # Add edges
        for edge in self._edges:
            if edge.source_id in id_map and edge.target_id in id_map:
                src = id_map[edge.source_id]
                tgt = id_map[edge.target_id]
                label = edge.relation.replace("_", " ")
                strength_style = "-->" if edge.strength > 0.5 else "-.-"
                lines.append(f"    {src} {strength_style}|{label}| {tgt}")

        return "\n".join(lines)

    def generate_d3_data(self) -> Dict:
        """
        Generate D3.js-compatible force-directed graph data.

        Used by Web UI adapter for interactive visualization.
        """
        nodes = [
            {
                "id": n.id,
                "label": n.label,
                "group": n.node_type,
                "size": n.weight * 3 + 5,
            }
            for n in self._nodes.values()
        ]

        links = [
            {
                "source": e.source_id,
                "target": e.target_id,
                "value": e.strength * 10,
                "label": e.relation,
            }
            for e in self._edges
            if e.source_id in self._nodes and e.target_id in self._nodes
        ]

        return {"nodes": nodes, "links": links}

    @property
    def summary(self) -> Dict[str, Any]:
        """Get a summary of the graph state."""
        type_counts = defaultdict(int)
        for node in self._nodes.values():
            type_counts[node.node_type] += 1

        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "by_type": dict(type_counts),
            "stats": self._stats,
        }

    # ============================================================
    # PERSISTENCE
    # ============================================================

    def _load(self):
        """Load graph from disk."""
        if not self.graph_path or not os.path.exists(self.graph_path):
            return

        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for nd in data.get("nodes", []):
                node = GraphNode(
                    id=nd["id"],
                    label=nd["label"],
                    node_type=nd["type"],
                    content=nd.get("content", ""),
                    source_file=nd.get("source_file", ""),
                    tags=nd.get("tags", []),
                    first_seen=nd.get("first_seen", ""),
                    last_updated=nd.get("last_updated", ""),
                    weight=nd.get("weight", 1),
                    agent_contributors=set(nd.get("agents", [])),
                )
                self._nodes[node.id] = node
                self._label_index[node.label.lower()] = node.id
                self._type_index[node.node_type].append(node.id)

            for ed in data.get("edges", []):
                edge = GraphEdge(**ed)
                self._edges.append(edge)

            logger.info(f"Loaded graph: {len(self._nodes)} nodes, {len(self._edges)} edges")

        except Exception as e:
            logger.warning(f"Failed to load graph: {e}")

    def _save(self):
        """Persist graph to disk."""
        if not self.graph_path:
            return

        try:
            os.makedirs(os.path.dirname(self.graph_path) or ".", exist_ok=True)

            data = {
                "version": "2.0",
                "updated": datetime.utcnow().isoformat(),
                "nodes": [n.to_dict() for n in self._nodes.values()],
                "edges": [e.to_dict() for e in self._edges],
                "summary": self.summary,
            }

            with open(self.graph_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Failed to save graph: {e}")

    @staticmethod
    def _node_id(node_type: str, content: str) -> str:
        """Generate a deterministic node ID from type + content."""
        import hashlib

        raw = f"{node_type}:{content.lower().strip()[:100]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
