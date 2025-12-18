"""GBoost integration API routes."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from ...models.schemas import (
    GBoostSaveRequest,
    GBoostSaveResponse,
    GBoostLoadResponse,
    GBoostListResponse,
    LevelListItem,
)
from ...clients.gboost import GBoostClient, get_gboost_client, update_gboost_client
from ..deps import get_gboost

router = APIRouter(prefix="/api/gboost", tags=["gboost"])


class GBoostConfigRequest(BaseModel):
    """Request model for GBoost configuration."""
    url: str
    api_key: str
    project_id: str


class GBoostConfigResponse(BaseModel):
    """Response model for GBoost configuration."""
    configured: bool
    url: Optional[str] = None
    project_id: Optional[str] = None
    message: str


@router.get("/config", response_model=GBoostConfigResponse)
async def get_gboost_config():
    """
    Get current GBoost configuration (without sensitive data).
    """
    client = get_gboost_client()
    return GBoostConfigResponse(
        configured=client.is_configured,
        url=client.base_url if client.base_url else None,
        project_id=client.project_id if client.project_id else None,
        message="configured" if client.is_configured else "GBoost not configured",
    )


@router.post("/config", response_model=GBoostConfigResponse)
async def set_gboost_config(request: GBoostConfigRequest):
    """
    Update GBoost configuration at runtime.
    """
    update_gboost_client(
        base_url=request.url,
        api_key=request.api_key,
        project_id=request.project_id,
    )

    client = get_gboost_client()
    return GBoostConfigResponse(
        configured=client.is_configured,
        url=client.base_url,
        project_id=client.project_id,
        message="Configuration updated successfully",
    )


@router.get("/health")
async def gboost_health(
    client: GBoostClient = Depends(get_gboost),
):
    """
    Check GBoost server health and configuration status.

    Returns:
        Health status and configuration information.
    """
    if not client.is_configured:
        return {
            "configured": False,
            "message": "GBoost client not configured. Set GBOOST_URL, GBOOST_API_KEY, and GBOOST_PROJECT_ID in environment.",
        }

    health = await client.health_check()
    return {
        "configured": True,
        "healthy": health.get("healthy", False),
        "project_id": client.project_id,
        **health,
    }


@router.post("/{board_id}/{level_id}", response_model=GBoostSaveResponse)
async def save_level_to_gboost(
    board_id: str,
    level_id: str,
    request: GBoostSaveRequest,
    client: GBoostClient = Depends(get_gboost),
) -> GBoostSaveResponse:
    """
    Save a level to GBoost server.

    Args:
        board_id: Board identifier.
        level_id: Level identifier.
        request: Level data to save.
        client: GBoostClient dependency.

    Returns:
        GBoostSaveResponse with success status and timestamp.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    result = await client.save_level(board_id, level_id, request.level_json)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save level"),
        )

    return GBoostSaveResponse(
        success=True,
        saved_at=result.get("saved_at", ""),
        message=result.get("message", "Level saved successfully"),
    )


@router.get("/{board_id}/{level_id}", response_model=GBoostLoadResponse)
async def load_level_from_gboost(
    board_id: str,
    level_id: str,
    client: GBoostClient = Depends(get_gboost),
) -> GBoostLoadResponse:
    """
    Load a level from GBoost server.

    Args:
        board_id: Board identifier.
        level_id: Level identifier.
        client: GBoostClient dependency.

    Returns:
        GBoostLoadResponse with level data and metadata.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    result = await client.load_level(board_id, level_id)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Level '{level_id}' not found in board '{board_id}'",
        )

    return GBoostLoadResponse(
        level_json=result.get("level_json", {}),
        metadata=result.get("metadata", {}),
    )


@router.get("/{board_id}", response_model=GBoostListResponse)
async def list_levels_from_gboost(
    board_id: str,
    prefix: str = Query(default="level_", description="Level ID prefix filter"),
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum results"),
    client: GBoostClient = Depends(get_gboost),
) -> GBoostListResponse:
    """
    List levels from GBoost server.

    Args:
        board_id: Board identifier.
        prefix: Filter by level ID prefix.
        limit: Maximum number of results.
        client: GBoostClient dependency.

    Returns:
        GBoostListResponse with list of levels.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    levels = await client.list_levels(board_id, prefix, limit)

    return GBoostListResponse(
        levels=[
            LevelListItem(
                id=level.get("id", ""),
                created_at=level.get("created_at", ""),
                difficulty=level.get("difficulty"),
            )
            for level in levels
        ]
    )


@router.delete("/{board_id}/{level_id}")
async def delete_level_from_gboost(
    board_id: str,
    level_id: str,
    client: GBoostClient = Depends(get_gboost),
):
    """
    Delete a level from GBoost server.

    Args:
        board_id: Board identifier.
        level_id: Level identifier.
        client: GBoostClient dependency.

    Returns:
        Success status.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    success = await client.delete_level(board_id, level_id)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete level '{level_id}'",
        )

    return {
        "success": True,
        "message": f"Level '{level_id}' deleted successfully",
    }
