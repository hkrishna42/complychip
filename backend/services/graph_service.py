"""ComplyChip V3 - Knowledge Graph Service"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from backend.services.firestore_service import (
    get_documents,
    create_document,
    get_document,
    query_documents,
)

COLLECTION = "knowledge_graph"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_graph_data(
    entity_id: Optional[str] = None,
    organization_id: Optional[str] = None,
) -> dict:
    """Get full graph data (nodes + edges) for D3.js visualization.

    Optionally filter by entity_id or organization_id.
    Returns a dict with 'nodes' and 'edges' lists.
    """
    try:
        filters = []
        if organization_id:
            filters.append(("organization_id", "==", organization_id))
        edges_raw = get_documents(COLLECTION, filters=filters if filters else None, limit=200)
    except Exception:
        edges_raw = []

    if not edges_raw:
        return _demo_graph_data()

    # Build node set from edges
    node_map = {}
    edges = []
    for e in edges_raw:
        src = e.get("source_id", "")
        tgt = e.get("target_id", "")
        if entity_id and entity_id not in (src, tgt):
            continue
        if src and src not in node_map:
            node_map[src] = {
                "id": src,
                "type": e.get("source_type", "entity"),
                "label": e.get("source_label", ""),
            }
        if tgt and tgt not in node_map:
            node_map[tgt] = {
                "id": tgt,
                "type": e.get("target_type", "document"),
                "label": e.get("target_label", ""),
            }
        edges.append({
            "id": e.get("id", str(uuid.uuid4())),
            "source": src,
            "target": tgt,
            "relationship": e.get("relationship", "related_to"),
            "label": e.get("description", e.get("relationship", "")),
            "confidence": e.get("confidence", 0.8),
        })

    # Resolve labels for nodes missing them
    for node in node_map.values():
        if not node["label"]:
            node["label"] = _resolve_node_label(node["id"], node["type"])

    return {
        "nodes": list(node_map.values()),
        "edges": edges,
        "node_count": len(node_map),
        "edge_count": len(edges),
    }


def _resolve_node_label(node_id: str, node_type: str) -> str:
    """Look up a human-readable label for a node from Firestore."""
    collection = {
        "document": "documents",
        "entity": "entities",
        "vendor": "vendors",
    }.get(node_type, "documents")
    try:
        doc = get_document(collection, node_id)
        if doc:
            return doc.get("name", doc.get("title", node_id[:20]))
    except Exception:
        pass
    return node_id[:20]


def add_edge(
    source_id: str,
    source_type: str,
    target_id: str,
    target_type: str,
    relationship: str,
    confidence: float = 0.9,
    organization_id: str = "",
    source_label: str = "",
    target_label: str = "",
) -> str:
    """Add a new edge to the knowledge graph.

    Returns the edge document ID.
    """
    edge_data = {
        "source_id": source_id,
        "source_type": source_type,
        "source_label": source_label or source_id[:20],
        "target_id": target_id,
        "target_type": target_type,
        "target_label": target_label or target_id[:20],
        "relationship": relationship,
        "confidence": confidence,
        "organization_id": organization_id,
    }
    try:
        edge_id = create_document(COLLECTION, edge_data)
        if edge_id:
            return edge_id
    except Exception as e:
        print(f"Warning: Failed to create graph edge: {e}")

    return f"demo-edge-{uuid.uuid4().hex[:8]}"


def find_path(source_id: str, target_id: str) -> list:
    """Find a path between two nodes using BFS.

    Returns a list of node IDs representing the shortest path.
    Falls back to demo data when Firestore is unavailable.
    """
    try:
        edges_raw = get_documents(COLLECTION, limit=500)
    except Exception:
        edges_raw = []

    if not edges_raw:
        return [source_id, target_id]  # trivial demo fallback

    # Build adjacency list
    adjacency = {}
    for e in edges_raw:
        src = e.get("source_id", "")
        tgt = e.get("target_id", "")
        if src not in adjacency:
            adjacency[src] = []
        if tgt not in adjacency:
            adjacency[tgt] = []
        adjacency[src].append(tgt)
        adjacency[tgt].append(src)  # undirected

    # BFS
    visited = {source_id}
    queue = [[source_id]]
    while queue:
        path = queue.pop(0)
        node = path[-1]
        if node == target_id:
            return path
        for neighbor in adjacency.get(node, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(path + [neighbor])

    return []  # no path found


def get_neighbors(node_id: str, depth: int = 1) -> dict:
    """Get all neighboring nodes up to a given depth.

    Returns a subgraph dict with 'nodes' and 'edges'.
    """
    try:
        edges_raw = get_documents(COLLECTION, limit=500)
    except Exception:
        edges_raw = []

    if not edges_raw:
        return _demo_neighbors(node_id)

    # Build adjacency from edges
    all_edges = []
    adjacency = {}
    for e in edges_raw:
        src = e.get("source_id", "")
        tgt = e.get("target_id", "")
        edge_info = {
            "id": e.get("id", ""),
            "source": src,
            "target": tgt,
            "relationship": e.get("relationship", "related_to"),
            "confidence": e.get("confidence", 0.8),
        }
        all_edges.append(edge_info)
        if src not in adjacency:
            adjacency[src] = []
        if tgt not in adjacency:
            adjacency[tgt] = []
        adjacency[src].append((tgt, edge_info))
        adjacency[tgt].append((src, edge_info))

    # BFS to depth
    visited = {node_id}
    current_level = [node_id]
    result_nodes = {}
    result_edges = []

    for _ in range(depth):
        next_level = []
        for nid in current_level:
            for neighbor, edge_info in adjacency.get(nid, []):
                result_edges.append(edge_info)
                if neighbor not in visited:
                    visited.add(neighbor)
                    next_level.append(neighbor)
        current_level = next_level

    # Collect node info
    for nid in visited:
        result_nodes[nid] = {
            "id": nid,
            "type": "entity",
            "label": nid[:20],
        }

    return {
        "center_node": node_id,
        "depth": depth,
        "nodes": list(result_nodes.values()),
        "edges": result_edges,
        "node_count": len(result_nodes),
        "edge_count": len(result_edges),
    }


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------

def _demo_graph_data() -> dict:
    nodes = [
        {"id": "entity-001", "type": "entity", "label": "Sunrise Properties LLC"},
        {"id": "entity-002", "type": "entity", "label": "Harbor View Complex"},
        {"id": "entity-003", "type": "entity", "label": "Oakmont Residences"},
        {"id": "vendor-001", "type": "vendor", "label": "SafeGuard Insurance"},
        {"id": "vendor-002", "type": "vendor", "label": "EcoClean Services"},
        {"id": "doc-001", "type": "document", "label": "Insurance Policy #1042"},
        {"id": "doc-002", "type": "document", "label": "Safety Certificate"},
        {"id": "doc-003", "type": "document", "label": "Environmental Permit"},
    ]
    edges = [
        {"id": "edge-001", "source": "entity-001", "target": "doc-001", "relationship": "has_document", "confidence": 0.95},
        {"id": "edge-002", "source": "entity-001", "target": "vendor-001", "relationship": "contracts_with", "confidence": 0.90},
        {"id": "edge-003", "source": "entity-002", "target": "doc-002", "relationship": "has_document", "confidence": 0.95},
        {"id": "edge-004", "source": "entity-002", "target": "vendor-002", "relationship": "contracts_with", "confidence": 0.85},
        {"id": "edge-005", "source": "entity-003", "target": "doc-003", "relationship": "has_document", "confidence": 0.92},
        {"id": "edge-006", "source": "vendor-001", "target": "doc-001", "relationship": "issued_by", "confidence": 0.98},
        {"id": "edge-007", "source": "entity-001", "target": "entity-002", "relationship": "managed_by", "confidence": 0.88},
        {"id": "edge-008", "source": "vendor-002", "target": "doc-003", "relationship": "relevant_to", "confidence": 0.75},
        {"id": "edge-009", "source": "entity-003", "target": "vendor-001", "relationship": "contracts_with", "confidence": 0.80},
        {"id": "edge-010", "source": "entity-003", "target": "entity-001", "relationship": "subsidiary_of", "confidence": 0.95},
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


def _demo_neighbors(node_id: str) -> dict:
    data = _demo_graph_data()
    # Filter to edges touching node_id
    relevant = [e for e in data["edges"] if e["source"] == node_id or e["target"] == node_id]
    neighbor_ids = set()
    for e in relevant:
        neighbor_ids.add(e["source"])
        neighbor_ids.add(e["target"])
    neighbor_ids.discard(node_id)
    nodes = [n for n in data["nodes"] if n["id"] in neighbor_ids or n["id"] == node_id]
    return {
        "center_node": node_id,
        "depth": 1,
        "nodes": nodes,
        "edges": relevant,
        "node_count": len(nodes),
        "edge_count": len(relevant),
    }
