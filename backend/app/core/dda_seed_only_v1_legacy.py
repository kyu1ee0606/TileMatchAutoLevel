"""[옛 v1 · 보존용] 문서 47 §5 '시드만 내보내기' 1판 판정 (2026-10-20, 두 열·v1 목록·출시 스냅샷 기준).

2026-11-03 맵툴 /dda-seed-export 는 v2(dda_seed_catalog.seed_only_plan_v2 — 배치 파일·4열·보드 1회 조회)로
바뀌어 이 모듈을 쓰지 않는다. backend/scripts/dda_seed_server_apply_20261020.py 가 아직 쓰므로 옮겨 보존한다
(동작 무변경 — 원래 dda_seed_catalog.py 에 있던 코드 그대로).
"""
from typing import Any, Dict

from .dda_seed_catalog import (CatalogError, SEED_FIELDS, _LEVEL_ID, _norm, _seed_values, _server_map_sha,
                               is_valid_seed_str, load_catalog, load_source_rows, row_diff, row_digest)


def seed_only_plan(level_id: str, level_json: Dict[str, Any], townpop: Dict[str, Any],
                   server_row: Any) -> Dict[str, Any]:
    """'시드만 내보내기' — 서버 현재 행을 그대로 두고 두 컬럼만 바꾼 payload.

    신뢰 조건(하나라도 실패하면 blocked, 기본값 추정 없음):
      levels 행 id · 원본 행 스냅샷 존재 · 서버 행 존재·dict·두 컬럼 존재 ·
      서버 행(map/시드/etime/id 제외)이 스냅샷과 같음 · 서버 map 해시 = sourceMapSha256.
    payload = 두 시드 필드만 (부분 수정, §9). 서버 행 전체 재전송은 하지 않는다.
    """
    res: Dict[str, Any] = {"target_id": level_id, "blocked": True}
    m = _LEVEL_ID.match(level_id or "")
    if not m:
        res["reason"] = "not_level_row"
        return res
    level = int(m.group(1))
    try:
        snap = load_source_rows()["rows"].get(level_id)
        entry = load_catalog()["_byLevel"].get(level)
    except CatalogError as e:
        res.update({"reason": "catalog_error", "detail": str(e)})
        return res
    if snap is None or entry is None:
        res["reason"] = "no_snapshot"
        return res
    if server_row is None:
        res["reason"] = "no_server_row"
        return res
    if not isinstance(server_row, dict):
        res["reason"] = "server_row_invalid"
        return res
    if any(f not in server_row for f in SEED_FIELDS):
        res["reason"] = "no_seed_column"
        return res
    diff = row_diff(server_row, snap)
    if diff:
        res.update({"reason": "server_row_differs", "detail": ",".join(diff[:8])})
        return res
    msha = _server_map_sha(server_row.get("map"))
    if msha is None:
        res["reason"] = "server_map_unverifiable"
        return res
    if msha != entry["sourceMapSha256"]:
        res["reason"] = "server_map_differs"
        return res
    seeds = _seed_values(level, level_json, townpop)
    # [§9] 전체 행 재전송 금지 — 2026-10-20 L159 시험에서 null rewardList 가 [["null",0,0,0]] 로 바뀌었다.
    # payload 는 두 시드 필드만(부분 수정). 실제 전송은 PARTIAL_UPDATE_VERIFIED 가 True 일 때만.
    payload = {"ddaEasySeeds": seeds["ddaEasySeeds"], "ddaHardSeeds": seeds["ddaHardSeeds"]}
    before = (_norm(server_row.get("ddaEasySeeds")), _norm(server_row.get("ddaHardSeeds")))
    after = (seeds["ddaEasySeeds"], seeds["ddaHardSeeds"])
    change = ("same" if before == after else "clear" if after == ("", "") else
              "fill" if before == ("", "") else "change")
    res.update({"blocked": False, "reason": seeds["reason"], "change": change,
                "server": {"ddaEasySeeds": before[0], "ddaHardSeeds": before[1]},
                "ddaEasySeeds": after[0], "ddaHardSeeds": after[1],
                "serverDigest": row_digest(server_row), "payload": payload})
    return res


def assert_partial_payload(payload: Dict[str, Any]) -> None:
    """전송 payload 는 정확히 두 시드 필드만, 각 값은 5개 시드 문자열 또는 "" 여야 한다."""
    if set(payload) != set(SEED_FIELDS):
        raise ValueError(f"partial payload keys must be exactly {SEED_FIELDS}: {sorted(payload)}")
    for f in SEED_FIELDS:
        if payload[f] != "" and not is_valid_seed_str(payload[f]):
            raise ValueError(f"invalid seed value for {f}")
