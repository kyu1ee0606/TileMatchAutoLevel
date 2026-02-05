"""GBoost integration API routes."""
import base64
import io
import json
import time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from ...models.schemas import (
    GBoostSaveRequest,
    GBoostSaveResponse,
    GBoostLoadResponse,
    GBoostListResponse,
    LevelListItem,
    UploadLocalToGBoostRequest,
    UploadLocalToGBoostResponse,
    UploadProgressItem,
)
from ...clients.gboost import GBoostClient, get_gboost_client, update_gboost_client
from ..deps import get_gboost

# Local levels directory (same as in simulate.py)
LOCAL_LEVELS_DIR = Path(__file__).parent.parent.parent / "storage" / "local_levels"

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

    Automatically converts to TownPop format and generates thumbnail.

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

    # Store original for thumbnail generation
    original_level_json = request.level_json.copy()

    # Convert to TownPop format (adds map field with layer data)
    level_json = _convert_to_townpop_format(request.level_json)

    result = await client.save_level(board_id, level_id, level_json)

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save level"),
        )

    # Generate and upload thumbnail
    thumbnail_msg = ""
    thumbnail_data = _generate_thumbnail(original_level_json, size=192)
    if thumbnail_data:
        thumb_result = await client.save_thumbnail(
            board_id,
            level_id,
            thumbnail_data,
            size=128
        )
        if thumb_result.get("success"):
            thumbnail_msg = " (with thumbnail)"
        else:
            thumbnail_msg = " (thumbnail failed)"

    return GBoostSaveResponse(
        success=True,
        saved_at=result.get("saved_at", ""),
        message=result.get("message", "Level saved successfully") + thumbnail_msg,
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


def _count_gimmicks(level_json: dict) -> dict:
    """Count all gimmicks in the level."""
    gimmick_counts = {
        "chain": 0,
        "frog": 0,
        "ice": 0,
        "grass": 0,
        "bomb": 0,
        "link": 0,
        "unknown": 0,
        "curtain": 0,
        "teleport": 0,
    }
    goal_counts = {}

    num_layers = level_json.get("layer", 8)
    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        for tile_data in tiles.values():
            if not isinstance(tile_data, list):
                continue

            tile_type = tile_data[0] if len(tile_data) > 0 else ""
            attribute = tile_data[1] if len(tile_data) > 1 else ""

            # Count goals (craft/stack)
            if tile_type.startswith("craft_") or tile_type.startswith("stack_"):
                extra = tile_data[2] if len(tile_data) > 2 else None
                count = 1
                if extra and isinstance(extra, list) and len(extra) >= 1:
                    count = extra[0] if isinstance(extra[0], int) else 1
                goal_counts[tile_type] = goal_counts.get(tile_type, 0) + count

            # Count gimmicks from attributes
            if attribute:
                if attribute == "chain":
                    gimmick_counts["chain"] += 1
                elif attribute == "frog":
                    gimmick_counts["frog"] += 1
                elif attribute.startswith("ice"):
                    gimmick_counts["ice"] += 1
                elif attribute.startswith("grass"):
                    gimmick_counts["grass"] += 1
                elif attribute == "bomb":
                    gimmick_counts["bomb"] += 1
                elif attribute.startswith("link"):
                    gimmick_counts["link"] += 1
                elif attribute == "unknown":
                    gimmick_counts["unknown"] += 1
                elif attribute.startswith("curtain"):
                    gimmick_counts["curtain"] += 1
                elif attribute == "teleport":
                    gimmick_counts["teleport"] += 1

    return {"gimmicks": gimmick_counts, "goals": goal_counts}


def _count_active_layers(level_json: dict) -> int:
    """Count layers that have at least one tile."""
    active = 0
    num_layers = level_json.get("layer", 8)
    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_json.get(layer_key, {})
        if layer_data.get("tiles"):
            active += 1
    return active


def _convert_to_townpop_format(level_json: dict) -> dict:
    """
    Convert level data to TownPop/GBoost-compatible format with all metadata.

    GBoost expects specific field structure matching the admin panel:
    - Root fields: col, row, rewardCoin, randSeed, unlockTile, tileSkin, etc.
    - map field: contains layer data with layer_0, layer_1, etc.
    """
    # Extract layer count
    num_layers = level_json.get("layer", 8)

    # Get col/row from first layer or use defaults
    first_layer = level_json.get("layer_0", {})
    col = first_layer.get("col", level_json.get("col", "7"))
    row = first_layer.get("row", level_json.get("row", "7"))

    # Build map data (contains all layer info) - GBoost format
    map_data = {"layer": str(num_layers)}
    for i in range(num_layers):
        layer_key = f"layer_{i}"
        if layer_key in level_json:
            layer_data = {}
            src_layer = level_json[layer_key]
            # Copy layer data with proper types
            layer_data["col"] = str(src_layer.get("col", col))
            layer_data["row"] = str(src_layer.get("row", row))
            layer_data["tiles"] = src_layer.get("tiles", {})
            layer_data["num"] = str(len(layer_data["tiles"]))
            map_data[layer_key] = layer_data

    # Count total tiles
    total_tiles = _count_tiles_in_level(level_json)

    # Count gimmicks and goals
    counts = _count_gimmicks(level_json)
    gimmick_counts = counts["gimmicks"]
    auto_goal_counts = counts["goals"]

    # Count active layers
    active_layers = _count_active_layers(level_json)

    # Get goal counts (from level data or auto-calculated)
    goal_count = level_json.get("goalCount", auto_goal_counts)
    if not goal_count:
        goal_count = auto_goal_counts

    # Build GBoost-compatible structure (matching admin panel fields EXACTLY)
    # All fields from GBoost admin panel must be included
    # IMPORTANT: GBoost stores fields as columns, so nested objects like 'map' must be stringified
    townpop_level = {
        # Display order matches GBoost admin panel
        "backgroundIndex": str(level_json.get("backgroundIndex", level_json.get("bgIdx", 0))),
        "tileSkin": str(level_json.get("tileSkin", 0)),
        "timea": str(level_json.get("timeAttack", level_json.get("timea", 0))),
        "unlockTile": str(level_json.get("unlockTile", 0)),
        "col": str(col),
        "row": str(row),
        "rewardCoin": str(level_json.get("rewardCoin", 10)),
        "useInRandomizer": "1" if level_json.get("useInRandomizer", False) else "0",
        "randSeed": str(level_json.get("randSeed", level_json.get("seed", 0))),
        "shuffleLayer": str(level_json.get("shuffleLayer", 0)),
        "shuffleTile": str(level_json.get("shuffleTile", 0)),
        "difficulty": str(level_json.get("difficulty", level_json.get("target_difficulty", 0))),
        "useTeleportInRandomizer": "1" if level_json.get("useTeleportInRandomizer", False) else "0",
        "teleportRandSeed": str(level_json.get("teleportRandSeed", 0)),

        # Calculated fields
        "num": str(total_tiles),
        "sets": str(total_tiles // 3),
        "layer": str(active_layers),
        "useTileCount": str(level_json.get("useTileCount", 6)),
        "typeImbalance": str(level_json.get("typeImbalance", level_json.get("tileImbalance", ""))),
        "rewardList": json.dumps(level_json.get("rewardList", [])),
        "etime": str(int(time.time())),

        # Map data - THE KEY FIELD containing all layer data
        "map": map_data,
    }

    return townpop_level


def _count_tiles_in_level(level_data: dict) -> int:
    """Count total tiles in a level including hidden tiles in stack/craft boxes."""
    total = 0
    num_layers = level_data.get("layer", 8)

    for i in range(num_layers):
        layer_key = f"layer_{i}"
        layer_data = level_data.get(layer_key, {})
        tiles = layer_data.get("tiles", {})

        for tile_data in tiles.values():
            if not isinstance(tile_data, list):
                continue

            tile_type = tile_data[0] if len(tile_data) > 0 else ""
            extra = tile_data[2] if len(tile_data) > 2 else None

            # Stack/craft boxes may contain multiple tiles
            if tile_type.startswith("stack_") or tile_type.startswith("craft_"):
                if extra and isinstance(extra, list) and len(extra) >= 1:
                    tile_count = extra[0] if isinstance(extra[0], int) else 1
                    total += tile_count
                else:
                    total += 1
            else:
                total += 1

    return total


# Tile color mapping for thumbnail generation (fallback)
TILE_COLORS = {
    "t0": (148, 163, 184),   # slate
    "t1": (248, 113, 113),   # red
    "t2": (248, 113, 113),   # red
    "t3": (74, 222, 128),    # green
    "t4": (74, 222, 128),    # green
    "t5": (96, 165, 250),    # blue
    "t6": (192, 132, 252),   # purple
    "t7": (120, 113, 108),   # stone
    "t8": (120, 113, 108),   # stone
    "t9": (87, 83, 78),      # stone dark
    "t10": (250, 204, 21),   # yellow
    "t11": (251, 146, 60),   # orange
    "t12": (244, 114, 182),  # pink
    "t13": (34, 211, 238),   # cyan
    "t14": (34, 211, 238),   # cyan
    "t15": (167, 139, 250),  # violet
}

# Tile image paths (relative to frontend/public)
TILE_IMAGES = {
    "t0": "tiles/skin0/s0_t0.png",
    "t1": "tiles/skin0/s0_t1.png",
    "t2": "tiles/skin0/s0_t2.png",
    "t3": "tiles/skin0/s0_t3.png",
    "t4": "tiles/skin0/s0_t4.png",
    "t5": "tiles/skin0/s0_t5.png",
    "t6": "tiles/skin0/s0_t6.png",
    "t7": "tiles/skin0/s0_t7.png",
    "t8": "tiles/skin0/s0_t8.png",
    "t9": "tiles/skin0/s0_t9.png",
    "t10": "tiles/skin0/s0_t10.png",
    "t11": "tiles/skin0/s0_t11.png",
    "t12": "tiles/skin0/s0_t12.png",
    "t13": "tiles/skin0/s0_t13.png",
    "t14": "tiles/skin0/s0_t14.png",
    "t15": "tiles/skin0/s0_t15.png",
    "craft_s": "tiles/special/tile_craft.png",
    "craft_e": "tiles/special/tile_craft.png",
    "craft_w": "tiles/special/tile_craft.png",
    "craft_n": "tiles/special/tile_craft.png",
    "stack_s": "tiles/special/stack_s.png",
    "stack_e": "tiles/special/stack_e.png",
    "stack_w": "tiles/special/stack_w.png",
    "stack_n": "tiles/special/stack_n.png",
    "stack_ne": "tiles/special/stack_ne.png",
    "stack_nw": "tiles/special/stack_nw.png",
    "stack_se": "tiles/special/stack_se.png",
    "stack_sw": "tiles/special/stack_sw.png",
}

# Special attribute overlay images
SPECIAL_IMAGES = {
    "chain": "tiles/special/tile_chain.png",
    "frog": "tiles/special/frog.png",
    "link": "tiles/special/tile_link.png",
    "link_n": "tiles/special/tile_link_n.png",
    "link_s": "tiles/special/tile_link_s.png",
    "link_e": "tiles/special/tile_link_e.png",
    "link_w": "tiles/special/tile_link_w.png",
    "ice_1": "tiles/special/tile_ice_1.png",
    "ice_2": "tiles/special/tile_ice_2.png",
    "ice_3": "tiles/special/tile_ice_3.png",
    "ice": "tiles/special/tile_ice_1.png",
    "grass": "tiles/special/tile_grass.png",
    "grass_1": "tiles/special/tile_grass.png",
    "grass_2": "tiles/special/tile_grass.png",
    "bomb": "tiles/special/bomb.png",
    "unknown": "tiles/special/tile_unknown.png",
    "curtain": "tiles/special/curtain_close.png",
    "curtain_open": "tiles/special/curtain_open.png",
    "curtain_close": "tiles/special/curtain_close.png",
    "teleport": "tiles/special/teleport.png",
}

# Cache for loaded images
_image_cache: dict = {}


def _get_tile_assets_path() -> Path:
    """Get the path to tile assets (frontend/public)."""
    # Try relative paths from backend
    backend_dir = Path(__file__).parent.parent.parent.parent  # app/api/routes -> backend
    candidates = [
        backend_dir.parent / "frontend" / "public",  # ../frontend/public
        backend_dir.parent / "frontend" / "dist",    # ../frontend/dist (built)
        Path("/Users/casualdev/TileMatchAutoLevel/frontend/public"),  # Absolute fallback
    ]
    for path in candidates:
        if path.exists() and (path / "tiles").exists():
            return path
    return candidates[0]  # Default


def _load_tile_image(image_path: str, tile_size: int) -> Optional[Image.Image]:
    """Load and cache a tile image, resized to tile_size."""
    cache_key = f"{image_path}_{tile_size}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    try:
        assets_path = _get_tile_assets_path()
        full_path = assets_path / image_path

        if not full_path.exists():
            return None

        img = Image.open(full_path).convert("RGBA")
        img = img.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
        _image_cache[cache_key] = img
        return img
    except Exception as e:
        print(f"Failed to load tile image {image_path}: {e}")
        return None


def _generate_thumbnail(level_data: dict, size: int = 192) -> Optional[bytes]:
    """
    Generate a PNG thumbnail for the level using actual tile images.
    Shows all layers with offset for depth effect.

    Args:
        level_data: Level JSON data.
        size: Output image size (square).

    Returns:
        PNG bytes or None if generation fails.
    """
    if not PIL_AVAILABLE:
        return None

    try:
        # Calculate tile bounds (only render used area)
        num_layers = level_data.get("layer", 8)
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        # Collect tiles from all layers with layer info
        tiles_by_layer: list[list[tuple]] = [[] for _ in range(num_layers)]

        for i in range(num_layers):
            layer_key = f"layer_{i}"
            layer_data = level_data.get(layer_key, {})
            tiles = layer_data.get("tiles", {})

            for pos, tile_data in tiles.items():
                if not isinstance(tile_data, list) or len(tile_data) == 0:
                    continue

                parts = pos.split("_")
                if len(parts) != 2:
                    continue

                try:
                    y, x = int(parts[0]), int(parts[1])
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
                    tiles_by_layer[i].append((x, y, tile_data, i))  # Include layer index
                except ValueError:
                    continue

        if min_x == float('inf'):
            return None

        # Calculate dimensions with layer offset
        used_width = max_x - min_x + 1
        used_height = max_y - min_y + 1

        # Layer offset for 3D stacking effect (pixels per layer)
        layer_offset = 3

        # Render at larger size for quality, then resize
        render_size = max(size * 2, 256)
        tile_size = render_size // max(used_width, used_height)

        # Add extra space for layer offsets
        total_offset = layer_offset * (num_layers - 1)
        canvas_width = used_width * tile_size + total_offset
        canvas_height = used_height * tile_size + total_offset

        # Create RGBA image for proper alpha compositing
        image = Image.new("RGBA", (canvas_width, canvas_height), (31, 41, 55, 255))  # gray-800

        # Draw tiles layer by layer (lower layers first, with offset)
        for layer_idx, layer_tiles in enumerate(tiles_by_layer):
            # Calculate layer offset (lower layers offset more to bottom-right)
            layer_x_offset = (num_layers - 1 - layer_idx) * layer_offset
            layer_y_offset = (num_layers - 1 - layer_idx) * layer_offset

            # Calculate brightness for this layer (lower = dimmer)
            if num_layers > 1:
                brightness = 0.5 + 0.5 * (layer_idx / (num_layers - 1))
            else:
                brightness = 1.0

            for x, y, tile_data, _ in layer_tiles:
                rel_x = x - min_x
                rel_y = y - min_y
                px = rel_x * tile_size + layer_x_offset
                py = rel_y * tile_size + layer_y_offset

                tile_type = tile_data[0] if len(tile_data) > 0 else ""
                attribute = tile_data[1] if len(tile_data) > 1 else ""

                # Draw t0 as background for non-t0 tiles (like the game does)
                # t0 is the base tile background image
                t0_bg_img = _load_tile_image(TILE_IMAGES.get("t0", ""), tile_size)

                if t0_bg_img and tile_type != "t0":
                    # Apply brightness to background
                    if brightness < 1.0:
                        t0_bg = t0_bg_img.copy()
                        from PIL import ImageEnhance
                        enhancer = ImageEnhance.Brightness(t0_bg)
                        t0_bg = enhancer.enhance(brightness)
                    else:
                        t0_bg = t0_bg_img
                    image.paste(t0_bg, (px, py), t0_bg)
                elif not t0_bg_img:
                    # Fallback: draw colored rectangle if t0 image not available
                    if tile_type.startswith("craft_"):
                        bg_color = (16, 185, 129)  # emerald
                    elif tile_type.startswith("stack_"):
                        bg_color = (139, 92, 246)  # violet
                    else:
                        bg_color = TILE_COLORS.get(tile_type, (107, 114, 128))
                    bg_color = tuple(int(c * brightness) for c in bg_color)
                    draw = ImageDraw.Draw(image)
                    draw.rectangle([px, py, px + tile_size - 1, py + tile_size - 1], fill=(*bg_color, 255))

                # Try to load actual tile image
                tile_img = None
                if tile_type in TILE_IMAGES:
                    tile_img = _load_tile_image(TILE_IMAGES[tile_type], tile_size)

                if tile_img:
                    # Apply brightness to tile image
                    if brightness < 1.0:
                        tile_img = tile_img.copy()
                        from PIL import ImageEnhance
                        enhancer = ImageEnhance.Brightness(tile_img)
                        tile_img = enhancer.enhance(brightness)

                    # Paste tile image with alpha
                    image.paste(tile_img, (px, py), tile_img)

                # Draw direction arrow for craft tiles
                if tile_type.startswith("craft_"):
                    direction = tile_type.split("_")[1] if "_" in tile_type else "s"
                    draw = ImageDraw.Draw(image)

                    # Arrow parameters - purple color, centered
                    arrow_color = (180, 80, 255, 255)  # Purple
                    outline_color = (120, 40, 180, 255)  # Dark purple outline
                    center_x = px + tile_size // 2
                    center_y = py + tile_size // 2
                    arrow_size = tile_size // 4  # Smaller for better centering

                    # Calculate arrow points based on direction (centered)
                    if direction == "s":  # South (down)
                        points = [
                            (center_x, center_y + arrow_size),  # Tip
                            (center_x - arrow_size, center_y - arrow_size // 2),
                            (center_x + arrow_size, center_y - arrow_size // 2),
                        ]
                    elif direction == "n":  # North (up)
                        points = [
                            (center_x, center_y - arrow_size),  # Tip
                            (center_x - arrow_size, center_y + arrow_size // 2),
                            (center_x + arrow_size, center_y + arrow_size // 2),
                        ]
                    elif direction == "e":  # East (right)
                        points = [
                            (center_x + arrow_size, center_y),  # Tip
                            (center_x - arrow_size // 2, center_y - arrow_size),
                            (center_x - arrow_size // 2, center_y + arrow_size),
                        ]
                    elif direction == "w":  # West (left)
                        points = [
                            (center_x - arrow_size, center_y),  # Tip
                            (center_x + arrow_size // 2, center_y - arrow_size),
                            (center_x + arrow_size // 2, center_y + arrow_size),
                        ]
                    else:
                        points = None

                    if points:
                        # Draw outline first
                        draw.polygon(points, outline=outline_color)
                        # Draw filled arrow
                        draw.polygon(points, fill=arrow_color)

                # Add attribute overlay if present
                if attribute and attribute in SPECIAL_IMAGES:
                    attr_img = _load_tile_image(SPECIAL_IMAGES[attribute], tile_size)
                    if attr_img:
                        # Apply slight transparency to overlay
                        overlay = attr_img.copy()
                        # Make overlay semi-transparent
                        overlay.putalpha(Image.eval(overlay.split()[3], lambda a: int(a * 0.8)))
                        image.paste(overlay, (px, py), overlay)

        # Resize to target size with high quality
        final_image = Image.new("RGBA", (size, size), (31, 41, 55, 255))

        # Scale and center
        scale = min(size / canvas_width, size / canvas_height)
        scaled_width = int(canvas_width * scale)
        scaled_height = int(canvas_height * scale)
        offset_x = (size - scaled_width) // 2
        offset_y = (size - scaled_height) // 2

        scaled = image.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)
        final_image.paste(scaled, (offset_x, offset_y), scaled)

        # Convert to RGB for PNG (no alpha needed for final output)
        final_rgb = Image.new("RGB", (size, size), (31, 41, 55))
        final_rgb.paste(final_image, mask=final_image.split()[3] if final_image.mode == 'RGBA' else None)

        # Convert to PNG bytes
        buffer = io.BytesIO()
        final_rgb.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    except Exception as e:
        print(f"Thumbnail generation error: {e}")
        import traceback
        traceback.print_exc()
        return None


@router.post("/upload-local", response_model=UploadLocalToGBoostResponse)
async def upload_local_to_gboost(
    request: UploadLocalToGBoostRequest,
    client: GBoostClient = Depends(get_gboost),
) -> UploadLocalToGBoostResponse:
    """
    Upload local levels to GBoost server.

    Args:
        request: Upload configuration with level IDs and options.
        client: GBoostClient dependency.

    Returns:
        UploadLocalToGBoostResponse with per-level results.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured. Set GBOOST_URL and GBOOST_PROJECT_ID.",
        )

    results: list[UploadProgressItem] = []
    uploaded = 0
    failed = 0
    skipped = 0

    for idx, level_id in enumerate(request.level_ids):
        # Determine target ID based on rename strategy
        if request.rename_strategy == "sequential":
            target_id = f"{request.target_prefix}{request.start_index + idx:03d}"
        elif request.rename_strategy == "custom" and request.custom_names:
            target_id = request.custom_names.get(level_id, level_id)
        else:  # "keep"
            target_id = level_id

        # Load local level
        file_path = LOCAL_LEVELS_DIR / f"{level_id}.json"
        if not file_path.exists():
            results.append(UploadProgressItem(
                level_id=level_id,
                target_id=target_id,
                status="failed",
                message=f"Local level '{level_id}' not found",
            ))
            failed += 1
            continue

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                local_data = json.load(f)
        except Exception as e:
            results.append(UploadProgressItem(
                level_id=level_id,
                target_id=target_id,
                status="failed",
                message=f"Failed to read level: {str(e)}",
            ))
            failed += 1
            continue

        # Extract level_data from local storage format
        # Format 1: {level_data: {...}, metadata: {...}}
        # Format 2: {layer: N, ...} (flat)
        if "level_data" in local_data and isinstance(local_data["level_data"], dict):
            level_json = local_data["level_data"]
            # Handle double-nesting
            if "level_data" in level_json and isinstance(level_json["level_data"], dict):
                level_json = level_json["level_data"]
        elif "layer" in local_data:
            level_json = local_data
        else:
            results.append(UploadProgressItem(
                level_id=level_id,
                target_id=target_id,
                status="failed",
                message="Invalid level data format",
            ))
            failed += 1
            continue

        # Check if level exists on server (if not overwriting)
        if not request.overwrite:
            existing = await client.load_level(request.board_id, target_id)
            if existing is not None:
                results.append(UploadProgressItem(
                    level_id=level_id,
                    target_id=target_id,
                    status="skipped",
                    message=f"Level already exists on server",
                ))
                skipped += 1
                continue

        # Store original level data for thumbnail generation
        original_level_json = level_json.copy()

        # Convert to TownPop-compatible format
        level_json = _convert_to_townpop_format(level_json)

        # Upload to GBoost
        result = await client.save_level(request.board_id, target_id, level_json)

        if result.get("success"):
            # Generate and upload thumbnail
            thumbnail_msg = ""
            thumbnail_data = _generate_thumbnail(original_level_json, size=192)
            if thumbnail_data:
                thumb_result = await client.save_thumbnail(
                    request.board_id,
                    target_id,
                    thumbnail_data,
                    size=128
                )
                if thumb_result.get("success"):
                    thumbnail_msg = " (with thumbnail)"
                else:
                    thumbnail_msg = " (thumbnail failed)"

            results.append(UploadProgressItem(
                level_id=level_id,
                target_id=target_id,
                status="success",
                message=f"Uploaded successfully{thumbnail_msg}",
            ))
            uploaded += 1
        else:
            results.append(UploadProgressItem(
                level_id=level_id,
                target_id=target_id,
                status="failed",
                message=result.get("error", "Unknown error"),
            ))
            failed += 1

    return UploadLocalToGBoostResponse(
        success=failed == 0,
        total=len(request.level_ids),
        uploaded=uploaded,
        failed=failed,
        skipped=skipped,
        results=results,
    )


class ThumbnailUploadRequest(BaseModel):
    """Request model for thumbnail upload with base64 data."""
    board_id: str
    level_id: str
    png_base64: str  # Base64 encoded PNG data
    size: int = 128


class ThumbnailUploadResponse(BaseModel):
    """Response model for thumbnail upload."""
    success: bool
    message: str


@router.post("/thumbnail", response_model=ThumbnailUploadResponse)
async def upload_thumbnail(
    request: ThumbnailUploadRequest,
    client: GBoostClient = Depends(get_gboost),
) -> ThumbnailUploadResponse:
    """
    Upload a thumbnail image for a level.

    Args:
        request: Thumbnail upload request with base64 PNG data.
        client: GBoostClient dependency.

    Returns:
        ThumbnailUploadResponse with success status.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    try:
        # Decode base64 PNG data
        png_data = base64.b64decode(request.png_base64)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base64 data: {str(e)}",
        )

    result = await client.save_thumbnail(
        request.board_id,
        request.level_id,
        png_data,
        request.size,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to upload thumbnail"),
        )

    return ThumbnailUploadResponse(
        success=True,
        message=result.get("message", "Thumbnail uploaded successfully"),
    )
