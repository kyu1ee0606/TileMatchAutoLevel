"""PV 시드 변형 수동 플레이 (샌드박스 읽기 전용 + 결과 append).

샌드박스(backend/data/pv_sandbox/<copyId>)의 selection_v{2,3,4}.json(기본 v4) / t0 맵 / source.json 을 읽어
레벨별 tier(orig/e2/e1/b/h1/h2) 맵을 '명시 맵'으로 풀어 내려준다. tier 별 종류 수(seed@utc, v3·v4)는 그 tier 의
useTileCount 로 배정한다. 5단계=orig·e2·e1·b·h1·h2, 3단계=orig·b·e2·h2, 고정맵=orig.
독립 검증 결과(verify_*/_report.json, 07 보고)가 있으면 레벨·칸별 판정(pass/warn/stale)을 함께 준다. 배정은 반드시 클라와 비트 일치가
검증된 Python 포트(app.core.pv.cs_shuffle)로만 한다 — 프론트 TS 분배기·bakeFullBoard 경로는 쓰지 않는다.

- production 배치 저장/동기화/업로드 경로와 무관 (production_store 를 import 하지 않음).
- 샌드박스 원본 파일은 읽기만 한다. 쓰기는 manual_play/results.jsonl append 하나뿐.
- pv 코어(cs_shuffle/t0ize/canonical)는 import 만.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.pv.canonical import canonical_map, struct_hash, types_hash
from app.core.pv.cs_shuffle import resolve_map, shuffle_empty_tiles
from app.core.pv.t0ize import bot_level_json, t0ize_level

router = APIRouter(prefix="/api/pv-play", tags=["pv-play"])

_THIS = os.path.dirname(os.path.abspath(__file__))
COPY_ID = "pv_20261002_live3"
SANDBOX_DIR = os.path.normpath(os.path.join(_THIS, "..", "..", "..", "data", "pv_sandbox", COPY_ID))
RESULTS_PATH = os.path.join(SANDBOX_DIR, "manual_play", "results.jsonl")

TIERS = ["orig", "e2", "e1", "b", "h1", "h2"]  # UI 표시 순서 (쉬움 → 어려움)
# DDA 세트 (게임 정본 IMPL_SPEC §V2-9-2, 2026-10-08): 원본 level_N(= orig, 무변경 대조군) +
# seedvar_N = t0 사본 맵 + 토큰 "e2|e1|h1|h2"(3단계 "e2|h2", 기준 b 없음) → 주 표시: 토큰 칸을 cs_shuffle 로 배정.
# reference_baked/easy_N·hard_N = e2/h2 를 명시 타일로 구운 참고 행 → 보조 표시(재배정 없이 행 그대로).
DDA_TIERS = ["orig", "e2", "e1", "h1", "h2", "easy", "hard"]
SEEDVAR_ORDER = {4: ("e2", "e1", "h1", "h2"), 2: ("e2", "h2")}
ALL_TIERS = TIERS + ["easy", "hard"]
DDA_DIR = os.path.join(SANDBOX_DIR, "dda_sets")

# selection 버전 → (파일, 독립 검증 폴더). v3 는 정책안: relaxed(원맵 극단 레벨) 우선, 아니면 strict.
SELECTIONS: Dict[str, Dict[str, str]] = {
    "v2": {"file": "selection_v2.json", "verify": "verify"},
    "v3": {"file": "selection_v3.json", "verify": "verify_v3_relaxed"},
    "v4": {"file": "selection_v4.json", "verify": "verify_v4"},
    "dda": {"file": "dda_sets/selection_dda.json", "verify": "verify_dda"},
}
DEFAULT_SELECTION = "v4"
OUTER_MIN_DELTA = 0.08  # 07 §v4: 바깥 칸(e2·h2) 재측정 |Δ| 이 미만이면 경고

_lock = threading.Lock()
_selection_cache: Dict[str, Dict[str, Any]] = {}
_verify_cache: Dict[str, Dict[str, Any]] = {}
_source_cache: Dict[str, Any] = {"mtime": None, "by_level": None}


# ─────────────────────────────────────────────────────────────────────────────
# 샌드박스 읽기 (다른 세션이 selection_v2.json 을 갱신 중일 수 있음 → 부분 쓰기 대비)
# ─────────────────────────────────────────────────────────────────────────────
def _read_json_retry(path: str, attempts: int = 4, delay: float = 0.25) -> Any:
    last: Optional[Exception] = None
    for i in range(attempts):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            last = e
            if i + 1 < attempts:
                time.sleep(delay)
    raise last  # type: ignore[misc]


def _check_selection(selection: str) -> str:
    if selection not in SELECTIONS:
        raise HTTPException(status_code=400, detail=f"selection 은 {list(SELECTIONS)} 중 하나")
    return selection


def _selection_path(selection: str) -> str:
    if selection == "dda":
        return os.path.join(DDA_DIR, "selection_dda.json")
    return os.path.join(SANDBOX_DIR, SELECTIONS[selection]["file"])


def _load_selection(selection: str = DEFAULT_SELECTION) -> Dict[str, Any]:
    name = SELECTIONS[_check_selection(selection)]["file"]
    path = _selection_path(selection)
    cache = _selection_cache.setdefault(selection, {"mtime": None, "data": None})
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        raise HTTPException(status_code=404, detail=f"{name} 없음: {path}")
    if cache["data"] is not None and cache["mtime"] == mtime:
        return cache["data"]
    try:
        data = _read_json_retry(path)
    except Exception as e:  # 갱신 중 부분 쓰기 — 직전 정상본이 있으면 그것으로
        if cache["data"] is not None:
            return cache["data"]
        raise HTTPException(status_code=503, detail=f"{name} 읽기 실패(갱신 중?): {e}")
    cache.update(mtime=mtime, data=data)
    return data


def _parse_token(v: Any, utc_field: Any = None) -> Tuple[int, Optional[int]]:
    """seed 토큰 → (seed, utc|None). int / "123" / "123@11" + 선택적 utc 필드."""
    seed_s, _, utc_s = str(v).strip().partition("@")
    utc = int(utc_s) if utc_s else (int(utc_field) if utc_field not in (None, "") else None)
    return int(seed_s), utc


def _normalize(e: Dict[str, Any], selection: str) -> Dict[str, Any]:
    """버전별 selection 레벨 → {level, status, structHash, utc0, reason, wOrig, tiers{t: {seed, utc, delta}}}.
    status: '5tier' | '3tier' | 그 외(고정맵/미확보 등, 원 상태 문자열). utc None = 레벨 utc0."""
    out: Dict[str, Any] = {"level": int(e["level"]), "structHash": e.get("structHash"),
                           "utc0": e.get("utc0", e.get("utc")), "reason": e.get("reason"), "wOrig": e.get("wOrig"),
                           "status": e.get("status", "unknown"), "tiers": {}}
    if selection == "dda":
        tiers_in = e.get("tiers") or {}
        # 주: seedvar_N 토큰 칸
        sv_path = _seedvar_path(out["level"])
        token = e.get("token")
        if token is None and sv_path:
            token = _read_json_retry(sv_path).get("randSeed")
        toks = [x for x in str(token or "").split("|") if x]
        if sv_path and len(toks) in SEEDVAR_ORDER:
            out["seedvarPath"] = sv_path
            for t, tok in zip(SEEDVAR_ORDER[len(toks)], toks):
                seed, utc = _parse_token(tok)
                v = tiers_in.get(t) or {}
                out["tiers"][t] = {"seed": seed, "utc": utc, "delta": v.get("delta"), "seedvar": True}
        # 보조: reference_baked 구운 행
        for t, alias in (("easy", "e2"), ("hard", "h2")):  # pv_dda: easy_N = e2 구운 행, hard_N = h2 구운 행
            v = e.get(t) if isinstance(e.get(t), dict) else (tiers_in.get(t) or tiers_in.get(alias))
            if not isinstance(v, dict):
                continue
            seed, utc = (None, None)
            if v.get("seed") not in (None, ""):
                seed, utc = _parse_token(v["seed"], v.get("utc"))
            elif v.get("token") not in (None, ""):
                seed, utc = _parse_token(v["token"])
            elif isinstance(v.get("key"), str) and ":" in v["key"]:  # "utc:seed"
                u_s, s_s = v["key"].split(":", 1)
                seed, utc = int(s_s), int(u_s)
            elif v.get("utc") not in (None, ""):
                utc = int(v["utc"])
            delta = next((v[k] for k in ("deltaVsOrig", "deltaVsNormal", "delta", "deltaVsBase") if v.get(k) is not None), None)
            path = _dda_row_path(out["level"], t, v)
            if path is None and not isinstance(v.get("row"), dict):
                continue  # 행 파일 없음 → 플레이 불가 칸
            out["tiers"][t] = {"seed": seed, "utc": utc, "delta": delta, "path": path, "inline": v.get("row")}
        return out
    if selection == "v3":
        sub = next((e[k] for k in ("relaxed", "strict") if isinstance(e.get(k), dict) and e[k].get("ok")), None)
        if sub is None:
            return out
        out["variant"] = "relaxed" if sub is e.get("relaxed") else "strict"
        raw = dict(sub.get("tiers") or {})
    else:
        raw = dict(e.get("tiers") or {})
        if isinstance(e.get("base"), dict):
            raw["b"] = e["base"]
    for t, v in raw.items():
        if t not in TIERS or not isinstance(v, dict) or not v.get("seed"):
            continue
        seed, utc = _parse_token(v["seed"], v.get("utc"))
        delta = v.get("deltaVsOrig") if t == "b" else v.get("deltaVsBase")
        out["tiers"][t] = {"seed": seed, "utc": utc, "delta": delta}
    if selection == "v4":  # 배포 상태가 칸을 정한다 (고정맵에도 base 기록이 남아 있음 → 플레이 대상 아님)
        allowed = {"5tier": ("b", "e2", "e1", "h1", "h2"), "3tier": ("b", "e2", "h2")}.get(out["status"], ())
        out["tiers"] = {t: v for t, v in out["tiers"].items() if t in allowed}
    n = len(out["tiers"])
    if selection in ("v2", "v3") and n == 5:
        out["status"] = "5tier"
    return out


def _seedvar_path(level: int) -> Optional[str]:
    """seedvar_N 행: export(seedvar/seedvar_N.json) → 본 실행 작업본(work/NNNN/seedvar_row.json)."""
    for c in (f"seedvar/seedvar_{level}.json", f"work/{level:04d}/seedvar_row.json"):
        p = os.path.join(DDA_DIR, c)
        if os.path.exists(p):
            return p
    return None


def _dda_row_path(level: int, tier: str, v: Dict[str, Any]) -> Optional[str]:
    """DDA 행 파일 위치: selection 항목의 file/rowFile/path(dda_sets 기준 상대 또는 절대) → 관례 경로 순."""
    cands = [v.get(k) for k in ("file", "rowFile", "path") if isinstance(v.get(k), str)]
    cands += [f"reference_baked/{tier}_{level}.json", f"work/{level:04d}/baked_{tier}.json", f"{tier}/{level:04d}.json", f"{tier}/{level}.json", f"{tier}_{level}.json", f"{tier}_{level:04d}.json",
              f"rows/{tier}_{level}.json", f"rows/{tier}_{level:04d}.json"]
    for c in cands:
        p = c if os.path.isabs(c) else os.path.join(DDA_DIR, c)
        if os.path.exists(p):
            return p
    return None


def _dda_row(tv: Dict[str, Any]) -> Dict[str, Any]:
    """DDA 행(dict). 파일이 {"row": {...}} 래퍼여도, map 이 JSON 문자열이어도 받는다."""
    row = tv.get("inline") if isinstance(tv.get("inline"), dict) else _read_json_retry(tv["path"])
    if isinstance(row, dict) and isinstance(row.get("row"), dict):
        row = row["row"]
    m = row.get("map")
    if isinstance(m, str):
        m = json.loads(m)
    if not isinstance(m, dict):
        raise HTTPException(status_code=422, detail="DDA 행에 map 없음")
    return {**row, "map": m}


def _verify_index(selection: str) -> Dict[int, Dict[str, Any]]:
    """verify_*/_report.json (07 독립 검증) → {level: {seeds, tiers{t: verdict}, level verdict}}. 없으면 {}."""
    vdir = os.path.join(SANDBOX_DIR, SELECTIONS[selection]["verify"])
    path = os.path.join(vdir, "_report.json")
    if not os.path.exists(path):
        return {}
    mtime = os.path.getmtime(path)
    cache = _verify_cache.setdefault(selection, {"mtime": None, "data": None})
    if cache["data"] is not None and cache["mtime"] == mtime:
        return cache["data"]
    idx: Dict[int, Dict[str, Any]] = {}
    try:
        rows = _read_json_retry(path).get("rows") or []
    except Exception:
        return cache["data"] or {}
    for r in rows:
        lv = int(r["level"])
        S = r.get("S") or {}
        judge = S.get("judge") or {}
        vs = (S.get("rep") or {}).get("vsBase") or {}
        seeds: Dict[str, str] = {}
        try:  # 검증 당시 시드 (selection 이 바뀌었으면 stale)
            seeds = {k: str(v) for k, v in _read_json_retry(os.path.join(vdir, f"{lv:04d}.json"))["prep"]["seeds"].items() if v}
        except Exception:
            pass
        tiers: Dict[str, Dict[str, Any]] = {}
        for t, d in (judge.get("dirTrust") or {}).items():
            delta = (vs.get(t) or {}).get("d")
            reasons = []
            if not d.get("pass"):
                reasons.append(f"방향 신뢰 실패 {d.get('kept')}/{d.get('n')}")
            if t in ("e2", "h2") and delta is not None and abs(delta) < OUTER_MIN_DELTA:
                reasons.append(f"|Δ| {abs(delta):.3f} < {OUTER_MIN_DELTA}")
            tiers[t] = {"verdict": "warn" if reasons else "pass", "reasons": reasons,
                        "delta": delta, "kept": d.get("kept"), "n": d.get("n")}
        inner_bad = [k for k, v in (judge.get("inner") or {}).items() if v.get("unstable")]
        idx[lv] = {"seeds": seeds, "tiers": tiers, "innerUnstable": inner_bad,
                   "verdict": "warn" if inner_bad or any(v["verdict"] == "warn" for v in tiers.values()) else "pass"}
    cache.update(mtime=mtime, data=idx)
    return idx


def _verification(selection: str, n: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    v = _verify_index(selection).get(n["level"])
    if v is None:
        return None
    lu = n.get("utc0")
    cur = {t: (str(x["seed"]) if x["utc"] in (None, lu) else f"{x['seed']}@{x['utc']}") for t, x in n["tiers"].items()}
    if v["seeds"] and v["seeds"] != cur:
        return {"verdict": "stale", "tiers": {}, "innerUnstable": []}
    return {k: v[k] for k in ("verdict", "tiers", "innerUnstable")}


def _source_level(level: int) -> Dict[str, Any]:
    path = os.path.join(SANDBOX_DIR, "source.json")
    mtime = os.path.getmtime(path)
    if _source_cache["by_level"] is None or _source_cache["mtime"] != mtime:
        src = _read_json_retry(path)
        _source_cache.update(
            mtime=mtime,
            by_level={int(l["meta"]["level_number"]): l["level_json"] for l in src.get("levels", [])},
        )
    lj = _source_cache["by_level"].get(level)
    if lj is None:
        raise HTTPException(status_code=404, detail=f"source.json 에 레벨 {level} 없음")
    return lj


def _selection_entry(level: int, selection: str = DEFAULT_SELECTION) -> Dict[str, Any]:
    for e in _load_selection(selection).get("levels", []):
        if int(e.get("level", -1)) == level:
            return _normalize(e, selection)
    raise HTTPException(status_code=404, detail=f"{SELECTIONS[selection]['file']} 에 레벨 {level} 없음")


def _t0_row(level: int) -> Dict[str, Any]:
    """t0 맵 row. t0/{level}.json 이 있으면 그것, 없으면 source 원맵을 t0ize (결정적, 같은 결과)."""
    path = os.path.join(SANDBOX_DIR, "t0", f"{level:04d}.json")
    if os.path.exists(path):
        return _read_json_retry(path)["row"]
    return t0ize_level(_source_level(level), 1)["row"]


# ─────────────────────────────────────────────────────────────────────────────
# API
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/levels")
def list_levels(selection: str = DEFAULT_SELECTION) -> Dict[str, Any]:
    sel = _load_selection(selection)
    out: List[Dict[str, Any]] = []
    order = DDA_TIERS if selection == "dda" else TIERS
    for e in sel.get("levels", []):
        n = _normalize(e, selection)
        tiers = n["tiers"]
        out.append({
            "level": n["level"],
            "status": n["status"],
            "utc": n["utc0"],
            "reason": n["reason"],
            "wOrig": n["wOrig"],
            "seeds": {t: v["seed"] for t, v in tiers.items()},
            "tierUtc": {t: (v["utc"] if v["utc"] is not None else n["utc0"]) for t, v in tiers.items()},
            "deltas": {t: v["delta"] for t, v in tiers.items() if v["delta"] is not None},
            "availableTiers": [t for t in order if t == "orig" or t in tiers],
            "verification": _verification(selection, n),
        })
    out.sort(key=lambda x: x["level"])
    return {"copyId": sel.get("copyId", COPY_ID), "selection": selection, "selections": list(SELECTIONS),
            "tiers": order, "levels": out}


@router.get("/levels/{level}/{tier}")
def get_level_tier(level: int, tier: str, selection: str = DEFAULT_SELECTION) -> Dict[str, Any]:
    _check_selection(selection)
    allowed = DDA_TIERS if selection == "dda" else TIERS
    if tier not in allowed:
        raise HTTPException(status_code=400, detail=f"tier 는 {allowed} 중 하나 (selection={selection})")
    entry = _selection_entry(level, selection)
    t0row = _t0_row(level)
    if selection == "dda" and tier in TIERS and tier != "orig":
        # seedvar_N 행의 t0 사본 맵·utc0 로 배정 (클라와 같은 입력). 구조는 원본과 같아야 한다.
        if not entry.get("seedvarPath"):
            raise HTTPException(status_code=404, detail=f"레벨 {level} 에 seedvar 행 없음")
        sv = _dda_row({"path": entry["seedvarPath"]})
        t0row = {**t0row, "map": sv["map"], "useTileCount": sv.get("useTileCount", t0row["useTileCount"])}
    t0map = t0row["map"]
    utc = int(t0row["useTileCount"])  # utc0 (원맵 실제 종류 수)
    sh = struct_hash(t0map)
    if entry.get("structHash") and entry["structHash"] != sh:
        raise HTTPException(status_code=409, detail="t0 맵 structHash 가 selection 과 다름 (샌드박스 불일치)")

    seed_val: Optional[int] = None
    if tier == "orig" or (selection == "dda" and tier in ("easy", "hard")):
        if tier == "orig":
            canon = canonical_map(_source_level(level))
        else:  # DDA 구운 행: 재배정 없이 그대로 (명시 타일). 구조는 원본과 같아야 한다.
            tv = entry["tiers"].get(tier)
            if tv is None:
                raise HTTPException(status_code=404, detail=f"레벨 {level} ({entry.get('status')}) 에 DDA {tier} 행 없음")
            drow = _dda_row(tv)
            canon = canonical_map(drow["map"])
            utc = int(drow.get("useTileCount") or tv.get("utc") or utc)
            seed_val = tv.get("seed")
            if any(t[0] == "t0" for k, l in canon.items() if k.startswith("layer_") and isinstance(l, dict)
                   for t in (l.get("tiles") or {}).values() if isinstance(t, list) and t):
                raise HTTPException(status_code=409, detail="DDA 행에 t0 가 남아 있음 (명시 타일로 구워져야 함)")
        if struct_hash(canon) != sh:
            raise HTTPException(status_code=409, detail=f"{'원맵' if tier == 'orig' else 'DDA ' + tier + ' 행'} structHash 가 t0 맵과 다름 (구조 불일치)")
        # typesHash: t0 맵 슬롯 순서(GetEmptyTileList) 그대로 원맵의 명시 타입을 읽음
        slots = shuffle_empty_tiles(t0map, rand_seed=1, use_tile_count=int(t0row["useTileCount"]), strict=False).slots
        types: List[str] = []
        for s in slots:
            tile = canon[s.layer_name]["tiles"][s.pos]
            types.append(tile[0] if s.inner_index is None else tile[2][1].split("_")[s.inner_index])
        seed: Optional[int] = seed_val
        resolved = canon
    else:
        tv = entry["tiers"].get(tier)
        if tv is None:
            raise HTTPException(status_code=404, detail=f"레벨 {level} ({entry.get('status')}) 에 tier {tier} 없음")
        seed = tv["seed"]
        if tv["utc"] is not None:
            utc = int(tv["utc"])  # seed@utc: 이 tier 만 종류 수 ±1
        res = shuffle_empty_tiles(t0map, rand_seed=seed, use_tile_count=utc, strict=True)
        resolved = resolve_map(t0map, res)
        types = list(res.assigned)

    play_row = {**t0row, "randSeed": str(seed or 1), "useTileCount": str(utc)}
    level_json = bot_level_json(play_row, resolved)
    ver = _verification(selection, entry)
    return {
        "level": level,
        "tier": tier,
        "selection": selection,
        "status": entry.get("status"),
        "seed": seed,
        "utc": utc,
        "utc0": int(t0row["useTileCount"]),
        "verification": None if ver is None else {"level": ver["verdict"], "tier": ver["tiers"].get(tier)},
        "structHash": sh,
        "typesHash": types_hash(types),
        "tileCount": len(types),
        "levelJson": level_json,
    }


class ManualPlayResult(BaseModel):
    level: int
    tier: str
    seed: Optional[int] = None
    typesHash: Optional[str] = None
    won: bool
    # won: 클리어 / lost: 게임오버 / abandoned: 끝나기 전 Restart·Back·탭 이탈 (1수 이상 둔 판만)
    outcome: Literal["won", "lost", "abandoned"]
    moves: int = Field(ge=0)
    # 보드 잔여 근사 = 총 타일 - 이동 수 (1수 = 보드 타일 1개 선택). 트레이에 남은 타일은 미포함.
    boardRemainingApprox: Optional[int] = None
    trayMaxOccupancy: Optional[int] = None
    blind: bool = False
    playedAt: Optional[str] = None
    # 2026-10-02 추가 (기존 레코드엔 없음 → 요약에서 selection 없음 = "v2" 로 취급)
    selection: Optional[str] = None
    utc: Optional[int] = None
    # 2026-10-09 추가: 플레이한 맵의 출처. selection=dda 면 서버가 "dda" 로 채운다 (그 외 "seed_variant")
    source: Optional[str] = None


@router.post("/results")
def post_result(r: ManualPlayResult) -> Dict[str, Any]:
    if r.selection is not None:
        _check_selection(r.selection)
    allowed = DDA_TIERS if r.selection == "dda" else TIERS
    if r.tier not in allowed:
        raise HTTPException(status_code=400, detail=f"tier 는 {allowed} 중 하나")
    if r.won != (r.outcome == "won"):
        raise HTTPException(status_code=400, detail="won 과 outcome 불일치")
    rec = {
        **r.model_dump(),
        "source": "dda" if r.selection == "dda" else (r.source or "seed_variant"),
        "copyId": COPY_ID,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
    }
    line = json.dumps(rec, ensure_ascii=False)
    with _lock:
        os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
        with open(RESULTS_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    return {"ok": True, "record": rec}


@router.get("/results/summary")
def results_summary(selection: Optional[str] = None) -> Dict[str, Any]:
    """{level: {tier: {attempts, wins, abandoned}}} — attempts 는 끝난 판(won/lost)만. 손상 줄은 건너뜀.
    selection 지정 시 그 버전 기록만 (selection 필드가 없는 옛 기록 = v2). 미지정 = 전체."""
    if selection is not None:
        _check_selection(selection)
    summary: Dict[str, Dict[str, Dict[str, int]]] = {}
    if os.path.exists(RESULTS_PATH):
        with open(RESULTS_PATH, "r", encoding="utf-8") as f:
            for raw in f:
                try:
                    rec = json.loads(raw)
                    lv, tier = str(int(rec["level"])), str(rec["tier"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
                if selection is not None and (rec.get("selection") or "v2") != selection:
                    continue
                s = summary.setdefault(lv, {}).setdefault(tier, {"attempts": 0, "wins": 0, "abandoned": 0})
                if rec.get("outcome") == "abandoned":
                    s["abandoned"] += 1
                    continue
                s["attempts"] += 1
                s["wins"] += 1 if rec.get("won") else 0
    return {"summary": summary}
