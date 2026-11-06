"""GBoost integration API routes."""
import asyncio
import base64
import copy
import io
import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)
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
from ...core.dda_seed_catalog import apply_export_fields as _apply_dda_export_fields
from ...core import dda_seed_catalog as _dda
from ...core import infinity_relabel as _inf_relabel
from ...clients.gboost import GBoostLookupError
from ...core import dda_seed_ledger as _ledger
from ..deps import get_gboost

# Local levels directory (same as in simulate.py)
LOCAL_LEVELS_DIR = Path(__file__).parent.parent.parent / "storage" / "local_levels"

router = APIRouter(prefix="/api/gboost", tags=["gboost"])


def _ledger_hook(session: Optional[str], board_id: str, row_id: str, source: str, status: str,
                 payload: Optional[dict], original: Optional[dict] = None, field_evidence: Optional[dict] = None,
                 dropped: Optional[dict] = None, relabel: Optional[dict] = None, existing="unknown",
                 message: str = "") -> None:
    """[DDA 시드 이력 장부] 실제 전송(시도)한 행을 기록한다. levels 보드만. 기록 실패는 업로드 흐름에 영향 없음.
    existing: strict 조회 행 dict / None(서버에 없음) / "unknown"(조회 안 함·실패)."""
    if board_id != _dda.DDA_BOARD_ID:
        return
    try:
        reasons = None
        if isinstance(original, dict) and isinstance(payload, dict) and "map" in payload:
            reasons = (_dda.export_fields(board_id, row_id, original, dict(payload)) or {}).get("fieldReasons")
        rec = _ledger.build_row_record(row_id=row_id, source=source, status=status, payload=payload,
                                       level_json=original, field_reasons=reasons, field_evidence=field_evidence,
                                       dropped=dropped, relabel=relabel, server_before=existing, message=message)
        try:
            if not session:
                raise _ledger.LedgerError("no session")
            _ledger.append_row(session, rec)
        except _ledger.LedgerError:
            _ledger.append_row(_ledger.auto_session(board_id, source), rec)
    except Exception as e:  # noqa: BLE001 — 장부는 부가 기록
        logger.warning("dda seed ledger record failed (%s %s): %s", board_id, row_id, e)


def _server_map_same(existing_row, townpop: dict) -> bool:
    """[썸네일 생략] 서버 기존 행 map 이 이번에 보낼 map 과 같은가(빈 층 []→{} 정규화 후 비교).
    서버 행이 없거나 어느 쪽이든 비교 불가면 False(= 지금처럼 썸네일 생성·업로드)."""
    if not isinstance(existing_row, dict) or not isinstance(townpop, dict):
        return False
    a = _dda.map_compare_sha(existing_row.get("map"))
    b = _dda.map_compare_sha(townpop.get("map"))
    return a is not None and b is not None and a == b


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
    ledger_session: Optional[str] = Query(default=None, description="[DDA 시드 이력] 기록할 장부 세션 id(없으면 자동 세션)"),
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

    # [무한 그림 치환 v1] infinity_N 이면 변환 전에 그림 번호만 치환 → map·썸네일·시드 판정 binding 모두 치환본 기준
    src_level_json, _relabel_info = _inf_relabel.prepare_export_level_json(
        level_id, request.level_json, request.infinity_relabel)

    # Store original for thumbnail generation
    original_level_json = src_level_json.copy()

    # Convert to TownPop format (adds map field with layer data)
    level_json = _convert_to_townpop_format(src_level_json)
    # [DDA 2026-11-02] levels 보드: 시드 4열은 레벨 데이터에 유효 값이 있을 때만 보낸다(없으면 키 생략 →
    # 서버 기존 값 유지). infinity_* 는 정식 level_json 의 시드를 쓰지 않는다. 상세: dda_seed_catalog.export_fields
    level_json, _seed_ev = _dda.apply_export_fields_with_evidence(board_id, level_id, original_level_json, level_json)
    _seed_dropped: dict = {}
    # [DDA 문서 47 fail-closed] levels 보드: 기존 행을 strict 조회(실패=업로드 중단),
    # 서버의 비어 있지 않은 시드를 빈 값으로 바꾸면 dda_confirm 필요.
    _ledger_existing = "unknown"
    if board_id == _dda.DDA_BOARD_ID:
        try:
            existing = await client.load_level(board_id, level_id, strict=True)
        except Exception as e:
            _ledger_hook(ledger_session, board_id, level_id, "upload_single", "failed", level_json, original_level_json,
                         _seed_ev, None, _relabel_info, "unknown", f"lookup_failed: {e}")
            raise HTTPException(status_code=502, detail=f"기존 행 조회 실패 — 업로드 중단(재검사 필요): {e}")
        _ledger_existing = (existing or {}).get("level_json") if existing else None
        # [시드 판정 근거] 서버 값과 다른 새 시드는 클리어 가능 판정(PATH/PATH_BOT) 근거가 있을 때만 보낸다.
        _seed_dropped = _dda.evidence_gate((existing or {}).get("level_json") if existing else None,
                                           level_json, _seed_ev)
        guard = _dda.write_guard((existing or {}).get("level_json") if existing else None,
                                 level_json, request.dda_confirm)
        if guard:
            _ledger_hook(ledger_session, board_id, level_id, "upload_single", "blocked", level_json, original_level_json,
                         _seed_ev, _seed_dropped, _relabel_info, _ledger_existing, guard)
            raise HTTPException(status_code=409, detail=f"{guard}: 서버 DDA 시드를 비우거나 변경합니다 — 미리보기 확인 후 dda_confirm 필요")

    result = await client.save_level(board_id, level_id, level_json)
    # [DDA 시드 이력] 실제 전송한 payload 기준 기록(성공=sent, 실패=failed)
    _ledger_hook(ledger_session, board_id, level_id, "upload_single", "sent" if result.get("success") else "failed",
                 level_json, original_level_json, _seed_ev, _seed_dropped, _relabel_info, _ledger_existing,
                 "" if result.get("success") else str(result.get("error", "")))

    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to save level"),
        )

    # Generate and upload thumbnail
    # [썸네일 생략] 서버 기존 map 과 같으면(정규화 후) 썸네일 생성·업로드를 건너뛴다. 다르거나 비교 불가면 기존대로.
    thumbnail_msg = ""
    thumbnail_data = None
    if _server_map_same(_ledger_existing, level_json):
        thumbnail_msg = " (thumbnail skipped: map same)"
    else:
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
        message=result.get("message", "Level saved successfully") + thumbnail_msg
        + (f" (그림 치환 {_relabel_info['rule']})" if _relabel_info else "")
        + (f" (DDA 미검증 새 시드 미전송: {','.join(sorted(_seed_dropped))})" if _seed_dropped else ""),
    )


@router.get("/{board_id}/{level_id}", response_model=GBoostLoadResponse)
async def load_level_from_gboost(
    board_id: str,
    level_id: str,
    project_id: str = Query(default="", description="Override project ID"),
    client: GBoostClient = Depends(get_gboost),
) -> GBoostLoadResponse:
    """
    Load a level from GBoost server.
    """
    if not client.is_configured:
        raise HTTPException(
            status_code=503,
            detail="GBoost client not configured",
        )

    result = await client.load_level(board_id, level_id, project_id_override=project_id)

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
    limit: int = Query(default=100, ge=1, le=10000, description="Maximum results"),
    project_id: str = Query(default="", description="Override project ID (다른 프로젝트에서 가져오기)"),
    strict: bool = Query(default=False, description="[문서 47] 조회 실패를 빈 목록 대신 502 로 반환"),
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

    if strict:
        try:
            levels = await client.list_levels(board_id, prefix, limit, project_id_override=project_id, strict=True)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"서버 목록 조회 실패: {e}")
    else:
        levels = await client.list_levels(board_id, prefix, limit, project_id_override=project_id)

    return GBoostListResponse(
        levels=[
            LevelListItem(
                id=level.get("id", ""),
                created_at=level.get("created_at", ""),
                difficulty=level.get("difficulty"),
                dda_easy_seeds=level.get("dda_easy_seeds"),
                dda_hard_seeds=level.get("dda_hard_seeds"),
                dda_easy2_seeds=level.get("dda_easy2_seeds"),
                dda_hard2_seeds=level.get("dda_hard2_seeds"),
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


def _tile_pos_sort_key(pos: str) -> tuple:
    """Sort key for tile position strings ("col_row") in row-major order (top→bottom, left→right)."""
    try:
        x, y = pos.split("_")
        return (0, int(y), int(x))
    except (ValueError, AttributeError):
        # Malformed keys go last, preserving relative order among themselves
        return (1, 0, 0)


def _normalize_tiles_order(tiles: dict) -> dict:
    """
    Re-emit tiles in row-major key order.

    The in-game client derives block order from the JSON key sequence, so the
    generator's placement-order keys must be normalized before upload.
    """
    if not isinstance(tiles, dict):
        return {}
    return {pos: tiles[pos] for pos in sorted(tiles, key=_tile_pos_sort_key)}


_NORMAL_TILE_RE = re.compile(r"^t([1-9]|1[0-5])$")


def _is_key_tile(tile_id: str, effect) -> bool:
    """게임 DdaMapTransformer.IsKey (DB_Level isKeyTile): id t16 / "key" 또는 effect "key" (대소문자 무시)."""
    if tile_id == "t16" or tile_id.lower() == "key":
        return True
    return isinstance(effect, str) and effect.lower() == "key"


def _py_int(x) -> Optional[int]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return int(x)
    if isinstance(x, str):
        try:
            return int(x.strip())
        except ValueError:
            return None
    return None


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
            layer_data["tiles"] = _normalize_tiles_order(src_layer.get("tiles", {}))
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

    # Recompute useTileCount from the level's actual regular tile types.
    # Some saved levels carry stale/inflated useTileCount (e.g., 6 when only 2 colors present)
    # because /generate/from-template wrote the requested count without verifying that any
    # t0 placeholders actually got replaced. Shipping a stale value to the client can break
    # color distribution at runtime, so we always emit the value derived from the level itself.
    # [2026-11-02] 게임 DdaMapTransformer.Analyze 의 명시 종류 수 N 과 같은 규칙으로 센다
    #   (DdaMapTransformer.cs:347 행 useTileCount == N 게이트, 런타임 t0 풀 1..useTileCount):
    #   - 보드 칸: id 가 t1~t15(정확히 ^t([1-9]|1[0-5])$) 이고 열쇠가 아닌 칸만. 열쇠 = id t16/"key" 또는
    #     effect "key"(대소문자 무시, IsKey :36-41) — effect 가 key 인 일반 id 칸도 제외.
    #   - 새 형식 stack/craft 의 명시 내부 문자열(tile[2][1], 예 "t3_t5_t9"): 토큰 수 == tile[2][0] 일 때만
    #     t1~t15 토큰을 센다(:130-141 — 불일치면 게임도 그 컨테이너 내부를 세지 않음). t0·t16·key 제외.
    actual_tile_types: set = set()
    for i in range(num_layers):
        layer_key = f"layer_{i}"
        ld = level_json.get(layer_key)
        if not isinstance(ld, dict):
            continue
        tiles = ld.get("tiles")
        if not isinstance(tiles, dict):
            continue
        for tile in tiles.values():
            if not isinstance(tile, list) or len(tile) < 1:
                continue
            tt = tile[0] if isinstance(tile[0], str) else ""
            eff = tile[1] if len(tile) > 1 else ""
            if _NORMAL_TILE_RE.match(tt) and not _is_key_tile(tt, eff):
                actual_tile_types.add(tt)
            if (tt.startswith("stack_") or tt.startswith("craft_")) and len(tile) > 2 \
                    and isinstance(tile[2], list) and len(tile[2]) > 1 and isinstance(tile[2][1], str) \
                    and tile[2][1]:
                toks = tile[2][1].split("_")
                n = _py_int(tile[2][0])          # 게임 TryPyInt(:66-73): 숫자(소수 버림) 또는 정수 문자열
                if n is None or len(toks) != n:
                    continue
                for tok in toks:
                    if _NORMAL_TILE_RE.match(tok):
                        actual_tile_types.add(tok)
    stored_use_tile_count = int(level_json.get("useTileCount", 6) or 6)
    derived_use_tile_count = len(actual_tile_types) if actual_tile_types else stored_use_tile_count
    if derived_use_tile_count != stored_use_tile_count:
        logger.info(
            "[townpop] useTileCount stored=%s but actual=%s (%s) — emitting actual",
            stored_use_tile_count, derived_use_tile_count, sorted(actual_tile_types),
        )

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
        "autoCollectCount": str(level_json.get("autoCollectCount", 0)),
        "useInRandomizer": "1" if level_json.get("useInRandomizer", False) else "0",
        "randSeed": str(level_json.get("randSeed", level_json.get("seed", 0))),
        "shuffleLayer": str(level_json.get("shuffleLayer", 0)),
        # visualTileSeed: 배치 고정 후 t0 스프라이트 인덱스만 재매핑하는 비주얼 시드.
        #   필드 있으면 그대로 운반(>=0 결정적/-1 런타임랜덤). 없으면 아래에서 키 자체를 생략 → 게임은 리맵 안 함(하위호환).
        **(
            {"visualTileSeed": str(int(level_json["visualTileSeed"]))}
            if level_json.get("visualTileSeed") is not None
            else {}
        ),
        "shuffleTile": str(level_json.get("shuffleTile", 0)),
        # [v16] difficulty 필드 = 인게임 표시용 "예측 유저 클리어율(%)".
        # 게임 xDifficulty는 파싱만 하고 미사용(셔플 영향X) → 클리어% 운반에 재사용.
        # predicted_clear_rate(0~1)를 round(×100) 정수로. 미검증(없음)이면 -1(게임이 숨김).
        "difficulty": str(
            max(0, min(100, round(level_json["predicted_clear_rate"] * 100)))
            if isinstance(level_json.get("predicted_clear_rate"), (int, float))
            else -1
        ),
        "useTeleportInRandomizer": "1" if level_json.get("useTeleportInRandomizer", False) else "0",
        "teleportRandSeed": str(level_json.get("teleportRandSeed", 0)),

        # Calculated fields
        "num": str(total_tiles),
        "sets": str(total_tiles // 3),
        "layer": str(active_layers),
        "useTileCount": str(derived_use_tile_count),
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
    ledger_session: Optional[str] = Query(default=None, description="[DDA 시드 이력] 기존 장부 세션 id(없으면 이 요청용 세션을 만들고 끝에 마감)"),
    ledger_memo: str = Query(default="", description="[DDA 시드 이력] 메모"),
    ledger_tag: str = Query(default="", description="[DDA 시드 이력] 버전 태그"),
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

    # [DDA 시드 이력] levels 보드: 세션 id 가 없으면 이 요청 1회를 스냅샷 1개로 기록(끝에 재조회 + 마감)
    _ledger_sid, _ledger_own = ledger_session, False
    if request.board_id == _dda.DDA_BOARD_ID and not _ledger_sid:
        try:
            _ledger_sid = _ledger.open_session(kind="upload", board=request.board_id, memo=ledger_memo, tag=ledger_tag,
                                               source="upload_local",
                                               options={"infinity_relabel": request.infinity_relabel,
                                                        "dda_confirm": request.dda_confirm,
                                                        "rename_strategy": request.rename_strategy})["id"]
            _ledger_own = True
        except Exception as e:  # noqa: BLE001
            logger.warning("dda seed ledger session open failed: %s", e)
            _ledger_sid = None

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

        # [무한 그림 치환 v1] 대상 id 가 infinity_N 이면 변환 전에 치환(업로드 화면과 같은 결과)
        level_json, _ledger_relabel = _inf_relabel.prepare_export_level_json(target_id, level_json, request.infinity_relabel)

        # Store original level data for thumbnail generation
        original_level_json = level_json.copy()

        # Convert to TownPop-compatible format
        level_json = _convert_to_townpop_format(level_json)
        # [DDA 2026-11-02] levels 보드: 시드 4열은 레벨 데이터에 유효 값이 있을 때만(없으면 키 생략).
        level_json, _seed_ev = _dda.apply_export_fields_with_evidence(
            request.board_id, target_id, original_level_json, level_json)
        _seed_dropped: dict = {}
        _ledger_existing = "unknown"
        # [DDA 문서 47 fail-closed] levels 보드: 기존 행 strict 조회 실패 → 실패 처리(업로드 안 함),
        # 서버 시드를 빈 값으로 비우는 경우는 dda_confirm 없으면 건너뜀.
        if request.board_id == _dda.DDA_BOARD_ID:
            try:
                existing_row = await client.load_level(request.board_id, target_id, strict=True)
            except Exception as e:
                results.append(UploadProgressItem(level_id=level_id, target_id=target_id, status="failed",
                                                  message=f"기존 행 조회 실패 — 업로드 안 함: {e}"))
                failed += 1
                _ledger_hook(_ledger_sid, request.board_id, target_id, "upload_local", "failed", level_json,
                             original_level_json, _seed_ev, None, _ledger_relabel, "unknown", f"lookup_failed: {e}")
                continue
            _ledger_existing = existing_row.get("level_json") if existing_row else None
            _seed_dropped = _dda.evidence_gate(existing_row.get("level_json") if existing_row else None,
                                               level_json, _seed_ev)
            guard = _dda.write_guard(existing_row.get("level_json") if existing_row else None,
                                     level_json, request.dda_confirm)
            if guard:
                results.append(UploadProgressItem(level_id=level_id, target_id=target_id, status="skipped",
                                                  message=f"{guard}: 서버 DDA 시드 비움/변경 — 확인 필요"))
                skipped += 1
                _ledger_hook(_ledger_sid, request.board_id, target_id, "upload_local", "blocked", level_json,
                             original_level_json, _seed_ev, _seed_dropped, _ledger_relabel, _ledger_existing, guard)
                continue

        # Upload to GBoost
        result = await client.save_level(request.board_id, target_id, level_json)
        # [DDA 시드 이력] 실제 전송한 payload 기준 기록
        _ledger_hook(_ledger_sid, request.board_id, target_id, "upload_local",
                     "sent" if result.get("success") else "failed", level_json, original_level_json, _seed_ev,
                     _seed_dropped, _ledger_relabel, _ledger_existing,
                     "" if result.get("success") else str(result.get("error", "")))

        if result.get("success"):
            # Generate and upload thumbnail
            # [썸네일 생략] 서버 기존 map 과 같으면(정규화 후) 건너뜀. 다르거나 비교 불가면 기존대로.
            thumbnail_msg = ""
            thumbnail_data = None
            if _server_map_same(_ledger_existing, level_json):
                thumbnail_msg = " (thumbnail skipped: map same)"
            else:
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
                message=f"Uploaded successfully{thumbnail_msg}"
                + (f" (DDA 미검증 새 시드 미전송: {','.join(sorted(_seed_dropped))})" if _seed_dropped else ""),
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

    if _ledger_own and _ledger_sid:
        try:
            await _ledger.readback_session(client, _ledger_sid)
            _ledger.finalize(_ledger_sid, {"uploaded": uploaded, "failed": failed, "skipped": skipped,
                                           "total": len(request.level_ids)})
        except Exception as e:  # noqa: BLE001
            logger.warning("dda seed ledger finalize failed: %s", e)

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


# ── DDA 시드만 내보내기 v2 (2026-11-03, PLAN_DDA_SEED_ONLY_EXPORT_FIX_20261103) ───────────────────
# 값 출처 = 맵툴 배치 파일(backend/data/production/<batch>.json). 탭(IndexedDB) 사본은 쓰지 않는다 —
# 탭은 행 id·원본 레벨 번호·자기가 아는 배치 버전만 보낸다. 서버 행 = 보드 전체 1회 조회. 전송 = 순차, 첫 실패에서 정지.
# [리뷰 반영 v2] ① 같은 프로세스 안 동시 실행 금지(전역 잠금, 잡혀 있으면 409) ② 배치 파일 sha/version 을 보드 조회 직후·
# 매 행 전송 직전(stat 비교, 바뀌면 sha 재계산)·SEED_EXPORT_FULL_RECHECK_EVERY 행마다·요청 끝에 다시 확인, 바뀌면 즉시 409 중단
# ③ 미리보기 저장소(_SEED_PREVIEWS): 업로드는 preview_id 필수, 대상·옵션·배치·GameBoost 대상이 미리보기 때와 같아야 함.
# 한계: GameBoost 서버 행이 다른 경로(다른 프로세스·도구·사람)로 바뀌는 경합은 막지 못한다 — 청크마다 보드 재조회 digest 비교로만 줄인다.
class DdaSeedExportTarget(BaseModel):
    target_id: str
    source_level: int
    expected_server_digest: Optional[str] = None


class DdaSeedExportRequest(BaseModel):
    batch_id: str
    expected_batch_version: int
    expected_batch_sha256: Optional[str] = None    # 업로드(dry_run=False)에서 필수 — 미리보기 응답 값
    preview_id: Optional[str] = None               # 업로드(dry_run=False)에서 필수 — 미리보기 응답 값
    targets: list[DdaSeedExportTarget]
    dry_run: bool = True
    confirm: bool = False
    trial: bool = False                             # 시험 1행(통과 기록 생성). 대상 정확히 1개일 때만
    infinity_relabel: bool = True
    client_unsynced_edits: int = 0                  # 탭에서 아직 배치 파일로 안 올린 편집 수(>0 이면 차단). 클라이언트 신고값 —
    #                                                 서버가 독립 확인할 수 없다(배치 파일 sha 재확인이 서버 쪽 방어).
    selection: Optional[dict] = None                # 화면 선택 식별값(범위·무한 모드 등) — 미리보기 때와 같아야 업로드


_SEED_EXPORT_LOCK = asyncio.Lock()
_SEED_PREVIEWS: "dict[str, dict]" = {}
_SEED_PREVIEWS_MAX = 8
SEED_EXPORT_FULL_RECHECK_EVERY = 25


def _seed_export_code_hash() -> str:
    """시험 기록을 묶는 코드 해시 — 관련 모듈 파일 전체 내용 + 판정 설정 상수(호출마다 계산)."""
    from ... import config as _cfg
    from ...clients import gboost as _gbc
    from ...core.pv import cs_shuffle as _cs
    from ...models import schemas as _sch
    from . import production_store as _ps
    # 한계: 파일 바이트 기준이라 '디스크 ≠ 이미 import 된 메모리 코드'(--reload 없이 파일만 바뀐 경우)는 구분하지 못한다.
    return _dda.code_fingerprint_files(
        [_dda.__file__, _inf_relabel.__file__, _cs.__file__, __file__, _gbc.__file__, _ps.__file__,
         _sch.__file__, _cfg.__file__],
        _dda.seed_settings_snapshot())


def _gb_target(client) -> dict:
    """시험 기록·미리보기를 묶는 GameBoost 대상(정규화 base_url · project_id · board)."""
    return _dda.normalize_gb_target(getattr(client, "base_url", ""), getattr(client, "project_id", ""), _dda.DDA_BOARD_ID)


def _seed_summary(results: list) -> dict:
    cells = {k: 0 for k in _dda.SEED_ONLY_CELL_STATES}
    rows: dict = {}
    for r in results:
        for c in (r.get("cells") or {}).values():
            cells[c.get("state", "blocked")] = cells.get(c.get("state", "blocked"), 0) + 1
        k = r.get("status") or ("blocked" if r.get("blocked") else "preview")
        rows[k] = rows.get(k, 0) + 1
    return {"cells": cells, "rows": rows}


class _BatchWatch:
    """배치 파일 변경 감시: stat(ino·mtime_ns·size)이 바뀌면 sha/version 을 다시 계산해 비교."""

    def __init__(self, batch_id: str, version: int, sha: str):
        from .production_store import _path
        self.path, self.version, self.sha = _path(batch_id), version, sha
        self.stat = self._stat()

    def _stat(self):
        import os
        try:
            st = os.stat(self.path)
            return (st.st_ino, st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def changed(self, full: bool = False) -> Optional[str]:
        import hashlib
        st = self._stat()
        if st is None:
            return "batch_missing"
        if not full and st == self.stat:
            return None
        try:
            with open(self.path, "rb") as f:
                raw = f.read()
            ver = int(json.loads(raw.decode("utf-8")).get("version", 0) or 0)
        except Exception as e:  # noqa: BLE001
            return f"batch_unreadable: {e}"
        if hashlib.sha256(raw).hexdigest() != self.sha or ver != self.version:
            return "batch_changed_during_export"
        self.stat = st
        return None


def _preview_key(batch_id: str, version: int, sha: str, relabel: bool, target: dict, selection) -> dict:
    return {"batch_id": batch_id, "batchVersion": version, "batchFileSha256": sha, "infinity_relabel": bool(relabel),
            "gbTarget": target, "selection": selection if isinstance(selection, dict) else None}


@router.post("/dda-seed-export")
async def dda_seed_export(
    request: DdaSeedExportRequest,
    client: GBoostClient = Depends(get_gboost),
    ledger_session: Optional[str] = Query(default=None, description="[DDA 시드 이력] 장부 세션 id(dry_run=False 일 때만 기록)"),
    ledger_memo: str = Query(default=""),
    ledger_tag: str = Query(default=""),
):
    """levels 보드 기존 행의 DDA 시드 4열 중 '바뀌고 근거 있는' 열만 update(new=0) 로 보낸다.

    dry_run=True : 배치 파일 + 보드 1회 조회로 칸 단위 판정만(쓰기 없음) → preview_id·batchFileSha256·serverDigest 반환.
    dry_run=False: preview_id 의 대상·옵션·배치 version/sha·GameBoost 대상이 같아야 함(아니면 409) → 보드 1회 재조회 →
                   행 digest 비교 → 변경 열은 confirm 필요 → 부분 수정 게이트(시험 통과 기록) → 순차 전송, 첫 실패에서 정지.
                   전송 중 배치 파일이 바뀌면 즉시 409 중단(이미 보낸 행은 응답 detail.results 와 장부에 남음).
    trial=True   : 대상 1개 · 게이트 우회 · 전송 후 보드 재조회 대조 → 통과/실패 기록 파일 생성.
    같은 프로세스에서 동시에 두 요청이 돌면 뒤 요청은 409(seed_export_busy).
    """
    if not client.is_configured:
        raise HTTPException(status_code=503, detail="GBoost client not configured")
    if _SEED_EXPORT_LOCK.locked():
        raise HTTPException(status_code=409, detail={
            "reason": "seed_export_busy", "message": "다른 시드만 내보내기 요청이 진행 중입니다 — 끝난 뒤 다시 하세요."})
    async with _SEED_EXPORT_LOCK:
        return await _dda_seed_export_locked(request, client, ledger_session, ledger_memo, ledger_tag)


async def _dda_seed_export_locked(request: DdaSeedExportRequest, client, ledger_session, ledger_memo, ledger_tag):
    from .production_store import read_batch_file
    if request.client_unsynced_edits > 0:
        raise HTTPException(status_code=409, detail={
            "reason": "unsynced_local_edits", "count": request.client_unsynced_edits,
            "message": "탭에 아직 저장(서버 동기화)되지 않은 편집이 있습니다 — 동기화 후 다시 미리보기하세요."})
    bf = read_batch_file(request.batch_id)
    if bf is None:
        raise HTTPException(status_code=404, detail="batch not found")
    if bf["version"] != request.expected_batch_version:
        raise HTTPException(status_code=409, detail={
            "reason": "batch_version_mismatch", "server_version": bf["version"],
            "your_version": request.expected_batch_version,
            "message": "탭의 배치 사본과 저장된 배치 버전이 다릅니다 — 새로고침(배치 당기기) 후 다시 미리보기하세요."})
    gb_target = _gb_target(client)
    key = _preview_key(request.batch_id, bf["version"], bf["sha256"], request.infinity_relabel, gb_target, request.selection)
    if not request.dry_run:
        if not request.expected_batch_sha256 or request.expected_batch_sha256 != bf["sha256"]:
            raise HTTPException(status_code=409, detail={
                "reason": "batch_changed_since_preview", "message": "미리보기 후 배치 파일이 바뀌었습니다 — 다시 미리보기하세요."})
        pv = _SEED_PREVIEWS.get(request.preview_id or "")
        if pv is None:
            raise HTTPException(status_code=409, detail={
                "reason": "preview_unknown", "message": "미리보기 기록이 없습니다(만료·서버 재시작) — 다시 미리보기하세요."})
        if pv["key"] != key:
            diff = sorted(k for k in key if key[k] != pv["key"].get(k))
            raise HTTPException(status_code=409, detail={
                "reason": "preview_mismatch", "fields": diff,
                "message": "미리보기 때와 대상/옵션/배치/서버 설정이 다릅니다 — 다시 미리보기하세요."})
        extra = [t.target_id for t in request.targets if pv["targets"].get(t.target_id) != t.source_level]
        if extra:
            raise HTTPException(status_code=409, detail={
                "reason": "preview_mismatch", "fields": ["targets"], "sample": extra[:10],
                "message": "미리보기에 없던 대상(또는 원본 번호 다름)이 있습니다 — 다시 미리보기하세요."})
        if request.trial and len(request.targets) != 1:
            raise HTTPException(status_code=400, detail="trial 은 대상 정확히 1개만")
    code_hash = _seed_export_code_hash()
    gate = ({"allowed": True, "by": "trial"} if request.trial
            else _dda.partial_update_allowed(code_hash, gb_target))
    by_level = {}
    for lv in (bf["doc"].get("levels") or []):
        meta = lv.get("meta") if isinstance(lv, dict) else None
        if isinstance(meta, dict) and isinstance(lv.get("level_json"), dict):
            by_level[meta.get("level_number")] = lv["level_json"]
    watch = _BatchWatch(request.batch_id, bf["version"], bf["sha256"])
    try:
        board = await client.load_board_rows(_dda.DDA_BOARD_ID)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"서버 보드 조회 실패 — 판정/업로드 안 함: {e}")
    srv_rows, board_keys = board.get("rows") or {}, board.get("keys")

    out: list = []
    _lctx: dict = {}
    _ledger_state = {"done": False}

    def _ledger_once():
        if not request.dry_run and not _ledger_state["done"]:
            _ledger_state["done"] = True
            _ledger_seed_export(out, _lctx, ledger_session, ledger_memo, ledger_tag)

    def _abort(reason: str):
        _ledger_once()
        raise HTTPException(status_code=409, detail={
            "reason": reason, "results": out, "summary": _seed_summary(out),
            "message": "전송 중 배치 파일이 바뀌어 즉시 중단했습니다 — 결과 확인 후 다시 미리보기하세요."})

    inflight: dict = {"plan": None}
    try:
        ch = watch.changed(full=True)                    # 보드 조회 직후 재확인
        if ch:
            _abort(ch)
        stopped = False
        posts = 0
        for t in request.targets:
            lj0 = by_level.get(t.source_level)
            if lj0 is None:
                out.append({"target_id": t.target_id, "source_level": t.source_level, "blocked": True,
                            "status": "blocked", "reason": "no_batch_level",
                            "cells": {f: {"state": "blocked", "why": "no_batch_level"} for f in _dda.EXPORT_SEED_FIELDS}})
                continue
            lj, _rl = _inf_relabel.prepare_export_level_json(t.target_id, copy.deepcopy(lj0), request.infinity_relabel)
            srv = srv_rows.get(t.target_id)
            plan = _dda.seed_only_plan_v2(t.target_id, lj, _convert_to_townpop_format(dict(lj)), srv, board_keys)
            plan["source_level"] = t.source_level
            payload = plan.pop("payload", None) or {}
            _lctx[t.target_id] = (srv, payload, _rl, lj)
            if request.dry_run or plan["blocked"]:
                plan["status"] = "blocked" if plan["blocked"] else "preview"
                out.append(plan)
                continue
            if stopped:
                plan.update({"blocked": True, "status": "blocked", "reason": "stopped_after_failure"})
                out.append(plan)
                continue
            if not t.expected_server_digest or t.expected_server_digest != plan.get("serverDigest"):
                plan.update({"blocked": True, "status": "blocked", "reason": "server_changed_since_preview"})
                out.append(plan)
                continue
            if not payload:
                plan["status"] = "unchanged"
                out.append(plan)
                continue
            if plan["change"] == "change" and not request.confirm:
                plan.update({"blocked": True, "status": "blocked", "reason": "needs_dda_confirm"})
                out.append(plan)
                continue
            guard = _dda.write_guard(srv, payload, request.confirm)
            if guard:
                plan.update({"blocked": True, "status": "blocked", "reason": guard})
                out.append(plan)
                continue
            if not gate.get("allowed"):
                plan.update({"blocked": True, "status": "blocked", "reason": "partial_update_unverified"})
                out.append(plan)
                continue
            try:
                _dda.assert_seed_payload(payload)
            except ValueError as e:                     # 첫 실패 중단 원칙: 이 행 차단 + 이후 행 전송 안 함
                plan.update({"blocked": True, "status": "failed", "reason": "payload_invalid", "detail": str(e)})
                out.append(plan)
                stopped = True
                continue
            ch = watch.changed(full=(posts > 0 and posts % SEED_EXPORT_FULL_RECHECK_EVERY == 0))   # 매 행 전송 직전
            if ch:
                _abort(ch)
            # update 전용(new=0, '=upt' 확인, new=1 폴백 없음 — 중복 레코드 방지). 순차 1건씩.
            inflight["plan"] = plan
            result = await client.update_existing_level(_dda.DDA_BOARD_ID, t.target_id, payload)
            inflight["plan"] = None
            posts += 1
            plan["status"] = "saved" if result.get("success") else "failed"
            plan["sent"] = sorted(payload)
            if not result.get("success"):
                plan["detail"] = result.get("error", "")
                stopped = True
            out.append(plan)
        if not request.dry_run and posts:
            ch = watch.changed(full=True)                # 요청(청크) 끝 재확인
            if ch:
                _abort(ch)

        trial_info = None
        if request.trial and not request.dry_run:
            r0 = out[0] if out else {}
            tid = r0.get("target_id")
            payload = (_lctx.get(tid) or (None, {}))[1] if tid else {}
            rec = {"target_id": tid, "payload": payload, "status": r0.get("status"), "codeHash": code_hash,
                   "gbTarget": gb_target,
                   "batch_id": request.batch_id, "batchVersion": bf["version"], "batchFileSha256": bf["sha256"],
                   "boardRawSha256Before": board.get("raw_sha256"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if r0.get("status") == "saved":
                try:
                    after = await client.load_board_rows(_dda.DDA_BOARD_ID)
                    rec["boardRawSha256After"] = after.get("raw_sha256")
                    rec["judge"] = _dda.judge_partial_trial(tid, payload, srv_rows, after.get("rows") or {})
                except Exception as e:  # noqa: BLE001
                    rec["judge"] = {"passed": False, "error": f"readback_failed: {e}"}
            else:
                rec["judge"] = {"passed": False, "error": f"not_saved: {r0.get('reason') or r0.get('status')}"}
            try:
                rec["recordPath"] = _dda.write_partial_trial_record(rec)
            except Exception as e:  # noqa: BLE001
                rec["recordError"] = str(e)
            trial_info = rec
    except BaseException as e:                       # 예외·취소(CancelledError 포함): 처리한 행을 장부에 남기고 재raise
        p_ = inflight.get("plan")
        if p_ is not None and p_ not in out:         # 전송 중 끊김 — 서버 반영 여부 불명
            p_.update({"status": "failed", "reason": "interrupted_uncertain", "detail": type(e).__name__})
            out.append(p_)
        _ledger_once()
        raise
    preview_id = None
    if request.dry_run:
        import uuid
        preview_id = uuid.uuid4().hex
        _SEED_PREVIEWS[preview_id] = {"key": key, "targets": {t.target_id: t.source_level for t in request.targets}}
        while len(_SEED_PREVIEWS) > _SEED_PREVIEWS_MAX:
            _SEED_PREVIEWS.pop(next(iter(_SEED_PREVIEWS)))
    _ledger_once()
    return {"dry_run": request.dry_run, "preview_id": preview_id, "trial": trial_info, "batchVersion": bf["version"],
            "batchFileSha256": bf["sha256"], "boardRawSha256": board.get("raw_sha256"), "gbTarget": gb_target,
            "partialUpdate": {**gate, "codeHash": code_hash}, "summary": _seed_summary(out), "results": out}


def _ledger_seed_export(out: list, ctx: dict, session: Optional[str], memo: str, tag: str) -> None:
    """[DDA 시드 이력] 시드만 내보내기(dry_run=False) 결과 기록. 세션 없으면 이 요청용 세션을 만들고 마감한다.
    payload 는 보낸 시드 열만(부분 수정). server_before = 보드 1회 조회 행. 기록 실패는 응답에 영향 없음."""
    try:
        own = not session
        sid = session or _ledger.open_session(kind="upload", board=_dda.DDA_BOARD_ID, memo=memo, tag=tag,
                                              source="dda_seed_export")["id"]
        st_map = {"saved": "sent", "failed": "failed", "unchanged": "unchanged", "blocked": "blocked"}
        for plan in out:
            tid = plan.get("target_id")
            existing, payload, rl, lj = ctx.get(tid, ("unknown", None, None, None))
            st = st_map.get(plan.get("status"), "blocked" if plan.get("blocked") else "failed")
            rec = _ledger.build_row_record(row_id=tid, source="dda_seed_export", status=st,
                                           payload=payload,
                                           level_json=lj, relabel=rl, server_before=existing,
                                           message=str(plan.get("reason") or "") + (
                                               f" {plan.get('detail')}" if plan.get("detail") else ""))
            _ledger.append_row(sid, rec)
        if own:
            _ledger.finalize(sid, {"results": len(out)})
    except Exception as e:  # noqa: BLE001
        logger.warning("dda seed ledger (seed export) failed: %s", e)
