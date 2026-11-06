"""무한 사본 그림 치환 v1 ("그림만 바꿔 끼우기", 2026-11-02 사용자 승인).

infinity_N 은 정식 level_{500+N} 의 배치(칸·층·기믹·종류별 개수·같은 그림 관계)를 그대로 쓰고,
일반 타일 그림 t1..t15 만 1:1 순열로 바꿔 다른 레벨처럼 보이게 한다.

규칙 v1 (정본 — sp_meowsgarden tools/dda_level_fix/relabel_infinity.py 와 바이트 단위 동일해야 한다):
  key   = "infinity_{N}|relabel.v1" (UTF-8). h = FNV-1a 32bit(offset 2166136261, prime 16777619). h == 0 -> 1
  rng   = 게임 zWellRandom(h) (Assets/00.spComponents/zWellRandom.cs, Rand(min,max) 양끝 포함)
          — 포트: app.core.pv.cs_shuffle.ZWellRandom
  types = 맵의 일반 타일 id t1..t15 서로 다른 값, 숫자 오름차순:
          보드 칸 id(effect "key" 칸 = 열쇠 → 제외) + stack/craft 내부 토큰(토큰 수 == tile[2][0] 일 때만).
          useTileCount 재계산(gboost._convert_to_townpop_format)과 같은 판정.
  K<2   -> 치환 없음. K>=2 -> Sattolo: p=types 복사; for i=K-1..1: j=rnd.Rand(0,i-1); swap(p[i],p[j]); types[i]->p[i]
  적용  = 보드 칸 id 와 내부 토큰의 t1..t15 만. 열쇠(t16/key/effect key)·t0·기믹 효과·컨테이너 이름·층·기타 필드 불변.

적용 위치: 변환(_convert_to_townpop_format) **전** 에디터 level_json 에 적용한다. 변환은 tiles 값을 그대로 옮기므로
결과 map = 정본(변환된 map 에 치환)과 같고, map sha256 판정 근거(binding)·썸네일·useTileCount 도 치환본 기준이 된다.
같은 맵에 두 번 적용하면 결과가 달라진다(멱등 아님) — 반드시 정식 원본 level_json 에 한 번만 적용한다.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Tuple

from .pv.cs_shuffle import ZWellRandom

RULE = "relabel.v1"
INFINITY_ID_RE = re.compile(r"^infinity_([1-9][0-9]*)$")
_NORMAL_RE = re.compile(r"^t([1-9]|1[0-5])$")
_FNV_OFFSET = 2166136261
_FNV_PRIME = 16777619


def fnv1a32(s: str) -> int:
    h = _FNV_OFFSET
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & 0xFFFFFFFF
    return h or 1


def rule_key(n: int) -> str:
    return f"infinity_{n}|{RULE}"


def infinity_slot(target_id: Optional[str]) -> Optional[int]:
    """'infinity_N' 이면 N, 아니면 None."""
    m = INFINITY_ID_RE.match(target_id or "")
    return int(m.group(1)) if m else None


def _py_int(x: Any) -> Optional[int]:
    # gboost._py_int 와 같은 판정(게임 TryPyInt): 숫자(소수 버림)·정수 문자열. bool 제외.
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


def _cells(level_json: Dict[str, Any]):
    """변환이 map 에 넣는 층(layer_0..layer-1)의 칸 리스트."""
    try:
        num_layers = int(level_json.get("layer", 8))
    except (TypeError, ValueError):
        return
    for i in range(num_layers):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict):
            continue
        tiles = ld.get("tiles")
        if not isinstance(tiles, dict):
            continue
        for c in tiles.values():
            if isinstance(c, list) and c and isinstance(c[0], str):
                yield c


def _is_effect_key(c: list) -> bool:
    return len(c) > 1 and isinstance(c[1], str) and c[1].lower() == "key"


def _inner_tokens(c: list) -> Optional[List[str]]:
    tt = c[0]
    if not (tt.startswith("stack_") or tt.startswith("craft_")):
        return None
    if len(c) < 3 or not isinstance(c[2], list) or len(c[2]) < 2 or not isinstance(c[2][1], str) or not c[2][1]:
        return None
    toks = c[2][1].split("_")
    n = _py_int(c[2][0])
    return toks if n is not None and len(toks) == n else None


def types_of(level_json: Dict[str, Any]) -> List[int]:
    t = set()
    for c in _cells(level_json):
        if _NORMAL_RE.match(c[0]) and not _is_effect_key(c):
            t.add(int(c[0][1:]))
        toks = _inner_tokens(c)
        if toks:
            t.update(int(x[1:]) for x in toks if _NORMAL_RE.match(x))
    return sorted(t)


def mapping_for(n: int, types: List[int]) -> Dict[int, int]:
    if len(types) < 2:
        return {}
    rnd = ZWellRandom(fnv1a32(rule_key(n)))
    p = list(types)
    for i in range(len(p) - 1, 0, -1):
        j = rnd.rand(0, i - 1)
        p[i], p[j] = p[j], p[i]
    return {types[i]: p[i] for i in range(len(types))}


def relabel_level_json(level_json: Dict[str, Any], n: int) -> Tuple[Dict[str, Any], Dict[int, int]]:
    """(치환된 깊은 복사본, {원래 번호: 새 번호}). 입력은 바꾸지 않는다. K<2 면 복사본 그대로."""
    out = copy.deepcopy(level_json)
    mp = mapping_for(n, types_of(level_json))
    if not mp:
        return out, mp

    def tr(x: str) -> str:
        return f"t{mp[int(x[1:])]}" if _NORMAL_RE.match(x) else x

    for c in _cells(out):
        if _NORMAL_RE.match(c[0]) and not _is_effect_key(c):
            c[0] = tr(c[0])
        toks = _inner_tokens(c)
        if toks:
            c[2][1] = "_".join(tr(x) for x in toks)
    return out, mp


def prepare_export_level_json(target_id: Optional[str], level_json: Dict[str, Any],
                              enabled: bool = True) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """내보내기 직전 공통 진입점. infinity_N 행이고 enabled 면 치환본, 아니면 입력 그대로.

    반환 (level_json, info). info = None(대상 아님/꺼짐) 또는 {"rule", "slot", "mapping": {"t3": "t7", ...}}.
    """
    n = infinity_slot(target_id)
    if n is None or not enabled:
        return level_json, None
    out, mp = relabel_level_json(level_json, n)
    return out, {"rule": RULE, "slot": n, "mapping": {f"t{k}": f"t{v}" for k, v in sorted(mp.items())}}
