"""PV (레벨 개인화 seed-variant) 정규화·해시 — 담당: E-P0-2.

정규 맵 정의, 구조 해시(structHash), 타입 해시(typesHash), 레이어 연속성 검사.
근거: claudedocs/difficulty_personalization/04_seed_variant_plan.md §A3-3, §A6.

canonical_map()은 기존 GB 변환 함수 `_convert_to_townpop_format`
(backend/app/api/routes/gboost.py)를 그대로 import해 재사용한다. gboost.py는 수정하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.api.routes.gboost import _convert_to_townpop_format


def canonical_map(level_json: dict) -> dict:
    """level_json(또는 샤드 맵 그 자체)을 GB 정규 순서의 map dict으로 변환한다.

    정규 순서 = GB가 만드는 `{"layer": N, "layer_0": {...}, ...}` 형태이며, 각 레이어의
    tiles 키는 row-major `(row, col)` 오름차순으로 정렬돼 있다(`_normalize_tiles_order`,
    `_tile_pos_sort_key`, gboost.py). 에디터 저장 순서와 무관하게 결정적이다(04 §A3-3).

    샤드에서 복호한 레벨별 map 하나를 그대로 넘겨도 동작하도록, `layer` 필드가 문자열
    숫자("1")여도 허용한다(샤드 포맷은 전부 문자열, 생성기 level_json은 int — 02 §3-3 확인).
    `_convert_to_townpop_format`은 이 값으로 `range()`를 돌리므로 int가 아니면 TypeError.

    샤드 실측(backend/scripts/pv_scan_shards.py 스캔)에서 빈 레이어의 `tiles`가 `{}`가 아니라
    `[]`로 직렬화된 레벨이 9개 발견됐다(real_array.php 쪽 빈 연관배열 → JSON 배열 직렬화
    추정). `_convert_to_townpop_format` 내부 `_count_tiles_in_level`은 `tiles.values()`를 바로
    불러 dict를 가정하므로(gboost.py:512, 수정 금지 범위) 그대로 넘기면 AttributeError가 난다.
    여기서 그런 `tiles`를 `{}`로 정규화한 뒤 넘긴다(원본 dict는 변경하지 않음).
    """
    layer_val = level_json.get("layer")
    if isinstance(layer_val, str):
        level_json = {**level_json, "layer": int(layer_val)}

    patched: dict[str, Any] = {}
    for key, value in level_json.items():
        if (
            key.startswith("layer_")
            and isinstance(value, dict)
            and isinstance(value.get("tiles"), list)
        ):
            patched[key] = {**value, "tiles": {}}
    if patched:
        level_json = {**level_json, **patched}

    return _convert_to_townpop_format(level_json)["map"]


def check_layer_continuity(canon_map: dict) -> list[str]:
    """레이어 키 연속성 검사: `layer` 값만큼 `layer_0..layer_{N-1}`가 모두 있어야 한다.

    04 §A2 단언 ②("레이어 키 `layer_0..N-1` 연속"). 누락되면 클라 NRE·layerIndex 어긋남
    위험(01 §3-7, §9-1: `CLayer.layerIndex` = map 키 열거 순번이라 레이어 키가 비연속이면
    순번이 레이어 번호와 어긋난다).

    Returns: 문제 설명 목록(빈 리스트 = 이상 없음).
    """
    problems: list[str] = []
    raw_n = canon_map.get("layer", 0)
    try:
        n = int(raw_n)
    except (TypeError, ValueError):
        return [f"non-integer layer count: {raw_n!r}"]

    for i in range(n):
        key = f"layer_{i}"
        if key not in canon_map:
            problems.append(f"missing {key} (declared layer count={n})")

    extra = sorted(
        (
            int(k[len("layer_"):])
            for k in canon_map
            if k.startswith("layer_") and k[len("layer_"):].isdigit()
        )
    )
    out_of_range = [i for i in extra if i >= n]
    if out_of_range:
        problems.append(
            f"layer_N keys beyond declared count {n}: {[f'layer_{i}' for i in out_of_range]}"
        )
    return problems


def _tile_struct_sig(tile: Any) -> tuple:
    """타일 1칸의 "구조" 서명: (containerRootId, effect, innerCount). 타입 ID는 제외한다.

    관측된 형태(실측, LIVE 3차 배치 1530레벨 전수 스캔):
      - 일반/기믹 타일: ["tN"|"t0"|"key", effect]            → containerRootId 없음
      - 스택/생성기 컨테이너: ["stack_e"|"craft_s"|.., effect, [cnt]]           (구포맷)
                              ["stack_e"|"craft_s"|.., effect, [cnt, "id0_id1.."]] (신포맷)
    `tile[0]`은 일반 타일에서는 타입(t0화 대상)이므로 서명에서 제외하고, 컨테이너에서는
    방향 루트 id(t0화해도 불변, 04 §A2)이므로 포함한다. effect는 스왑 대상이 아니라 위치에
    고정되므로(01 §3-2) 항상 포함한다. innerCount(컨테이너 내부 개수)는 유지 대상이므로 포함.
    """
    if not isinstance(tile, list) or len(tile) < 2:
        return ("MALFORMED", repr(tile), 0)

    effect = tile[1] if isinstance(tile[1], str) and tile[1] else ""

    is_container = (
        len(tile) >= 3
        and isinstance(tile[2], list)
        and len(tile[2]) >= 1
    )
    if is_container:
        root = tile[0] if isinstance(tile[0], str) else repr(tile[0])
        try:
            inner_count = int(tile[2][0])
        except (TypeError, ValueError):
            inner_count = -1
        return (root, effect, inner_count)

    return ("", effect, 0)


def struct_hash(canon_map: dict) -> str:
    """정규 맵의 "구조" sha256: (layerIdx, posKey, effect, containerRootId, innerCount).

    타입(ID)은 제외하므로 t0화 전후(타입만 바뀜)에는 값이 같아야 하고, 위치·레이어·효과·
    컨테이너 모양·순서가 하나라도 바뀌면 값이 달라져야 한다(04 §A6). 순서를 포함하기 위해
    집합이 아니라 순서 있는 리스트를 join해서 해시한다 — canon_map의 tiles는 이미
    row-major로 정렬돼 있으므로(canonical_map 참조) 이 순서가 그대로 해시에 들어간다.

    레이어가 선언된 개수보다 적게 존재해도(연속성 깨짐) 그 자리를 "MISSING" 마커로 채워
    해시에 반영한다 — 그래야 레이어 누락이 조용히 무시되지 않는다(check_layer_continuity와
    별도로, 해시만 봐도 구조 차이가 드러나게 하기 위함).
    """
    raw_n = canon_map.get("layer", 0)
    try:
        n = int(raw_n)
    except (TypeError, ValueError):
        n = 0

    parts: list[str] = [f"LAYER_COUNT={n}"]
    for i in range(n):
        layer = canon_map.get(f"layer_{i}")
        if not isinstance(layer, dict):
            parts.append(f"{i}|MISSING")
            continue
        tiles = layer.get("tiles", {})
        if not isinstance(tiles, dict):
            tiles = {}
        for pos, tile in tiles.items():
            root, effect, inner_count = _tile_struct_sig(tile)
            parts.append(f"{i}|{pos}|{effect}|{root}|{inner_count}")

    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def types_hash(type_list: list[str]) -> str:
    """정규 순서 최종 타일 타입 ID 배열(key 포함)의 sha256.

    입력은 호출측(평가/t0화 파이프라인, 이번 범위 밖)이 정규 순회 순서
    (`GetEmptyTileList(false)` 포팅, 04 §A3-2)대로 만든 배정 결과 타입 ID 문자열 배열이다.
    이 함수 자체는 순서를 보존한 입력을 그대로 직렬화해 해시할 뿐, 순회 로직은 갖지 않는다.
    """
    payload = json.dumps(list(type_list), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
