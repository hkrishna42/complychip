"""ComplyChip V3 - Knowledge Graph Routes"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from backend.dependencies import get_current_user
from backend.services.graph_service import (
    get_graph_data,
    get_neighbors,
    add_edge,
)

router = APIRouter()


@router.get("/nodes")
async def get_graph_nodes(
    entity_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Get all graph nodes, optionally filtered by entity."""
    org_id = user.get("org_id", "")
    data = get_graph_data(entity_id=entity_id, organization_id=org_id)
    return {"nodes": data["nodes"], "count": data["node_count"]}


@router.get("/edges")
async def get_graph_edges(
    entity_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Get all graph edges, optionally filtered by entity."""
    org_id = user.get("org_id", "")
    data = get_graph_data(entity_id=entity_id, organization_id=org_id)
    return {"edges": data["edges"], "count": data["edge_count"]}


@router.get("/visualize")
async def visualize_graph(
    entity_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """Get full graph data (nodes + edges) for D3.js visualization."""
    org_id = user.get("org_id", "")
    return get_graph_data(entity_id=entity_id, organization_id=org_id)


@router.get("/neighbors/{node_id}")
async def get_node_neighbors(
    node_id: str,
    depth: int = Query(1, ge=1, le=3),
    user: dict = Depends(get_current_user),
):
    """Get neighboring nodes up to a given depth."""
    return get_neighbors(node_id, depth=depth)
