"""실시간 키 `hurdleActiveLevels` 파서(게임 규칙 이식)와 추천 문자열 자동 검증.

파서 = 게임 `Assets/08.Scripts/Tile_Script/InGame/Dda/DdaHurdleConfig.cs` ParseActive/ParseActiveBundles/TryRange/ValidPreset
(1.1.3.13, 2026-11-06) 를 그대로 옮김. 게임 규칙이 바뀌면 이 파일만 고친다(C# 하네스 tools/dda_hurdle_check 에는 활성 키
파싱 CLI 모드가 없어 백엔드 이식으로 검사 — PARSER_KIND 로 화면에 표시).

  - 문자열에 '=' 가 하나라도 있으면 묶음 형식(';' 묶음, '강도=레벨|a-b,…'), 없으면 기존 형식('a-b:강도,…').
  - 전체 길이 > 4000 = 전부 무시(too_long). 입력 토큰(오류 포함, 묶음 형식은 강도 이름 제외) 200개 뒤 = too_many.
  - 강도 = [a-z0-9_]{1,24}(소문자화 후), 레벨 1 ≤ a ≤ b ≤ 100000, 숫자는 부호·공백 없는 십진수(NumberStyles.None).
  - 앞 묶음·앞 항목 우선(같은 레벨 여러 번이면 먼저 나온 것).
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

PARSER_KIND = "backend"   # 'backend' = 게임 C# 규칙을 옮긴 이 함수, 'csharp' = 게임 하네스(미지원)
PARSER_SRC = "DdaHurdleConfig.ParseActive(1.1.3.13) 규칙 이식"
MAX_ITEMS, MAX_LENGTH, MAX_PRESET_LEN, MAX_LEVEL = 200, 4000, 24, 100000
_DIGITS = re.compile(r"^[0-9]+$")
_PRESET = re.compile(r"^[a-z0-9_]+$")


def _head(s: str) -> str:
    return s[:20]


def _try_int(s: str, lo: int, hi: int) -> Optional[int]:
    if not _DIGITS.match(s or ""):
        return None
    n = int(s)
    return n if lo <= n <= hi else None


def _try_range(r: str) -> Optional[Tuple[int, int]]:
    if "-" not in r:
        a = _try_int(r.strip(), 1, MAX_LEVEL)
        return (a, a) if a is not None else None
    i = r.index("-")
    a = _try_int(r[:i].strip(), 1, MAX_LEVEL)
    b = _try_int(r[i + 1:].strip(), 1, MAX_LEVEL)
    return (a, b) if a is not None and b is not None and a <= b else None


def _valid_preset(p: str) -> bool:
    return 0 < len(p) <= MAX_PRESET_LEN and bool(_PRESET.match(p))


def parse_active(text: Optional[str]) -> Dict[str, Any]:
    """→ {active:[(a,b,preset)], bad:[…], tokens:int, length:int, format:'grouped'|'legacy'|'empty'}."""
    t = (text or "").strip()
    out: Dict[str, Any] = {"active": [], "bad": [], "tokens": 0, "length": len(t), "format": "empty"}
    if not t:
        return out
    if len(t) > MAX_LENGTH:
        out["bad"].append("too_long")
        return out
    act, bad = out["active"], out["bad"]
    tokens = 0
    if "=" in t:
        out["format"] = "grouped"
        for raw_b in t.split(";"):
            bundle = raw_b.strip()
            if not bundle:
                continue
            eq = bundle.find("=")
            preset = "" if eq < 0 else bundle[:eq].strip().lower()
            if eq < 0 or not _valid_preset(preset):
                if tokens >= MAX_ITEMS:
                    bad.append("too_many")
                    break
                tokens += 1
                bad.append(_head(bundle))
                continue
            any_tok = False
            stop = False
            for raw in bundle[eq + 1:].split(","):
                tok = raw.strip()
                if not tok:
                    continue
                any_tok = True
                if tokens >= MAX_ITEMS:
                    bad.append("too_many")
                    stop = True
                    break
                tokens += 1
                rg = _try_range(tok) if (":" not in tok and "=" not in tok) else None
                if rg:
                    act.append((rg[0], rg[1], preset))
                else:
                    bad.append(_head(tok))
            if stop:
                break
            if not any_tok:
                bad.append(_head(bundle))
    else:
        out["format"] = "legacy"
        for raw in t.split(","):
            item = raw.strip()
            if not item:
                continue
            if tokens >= MAX_ITEMS:
                bad.append("too_many")
                break
            tokens += 1
            c = item.find(":")
            preset = "" if c < 0 else item[c + 1:].strip().lower()
            rng = item if c < 0 else item[:c].strip()
            rg = _try_range(rng) if _valid_preset(preset) else None
            if rg:
                act.append((rg[0], rg[1], preset))
            else:
                bad.append(_head(item))
    out["tokens"] = tokens
    return out


def active_map(parsed: Dict[str, Any]) -> Dict[int, str]:
    """레벨 → 강도(앞 항목 우선 = 게임 ActivePreset 과 같음)."""
    m: Dict[int, str] = {}
    for a, b, p in parsed["active"]:
        for L in range(a, b + 1):
            m.setdefault(L, p)
    return m


def _compress(levels) -> str:
    out: List[List[int]] = []
    for L in sorted(set(levels)):
        if out and out[-1][1] + 1 == L:
            out[-1][1] = L
        else:
            out.append([L, L])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in out)


_DATA_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def load_hurdle_data(path: str) -> Optional[Dict[str, Any]]:
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    c = _DATA_CACHE.get(path)
    if c and c[0] == mt:
        return c[1]
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    _DATA_CACHE[path] = (mt, d)
    return d


def check_string(text: str, intent: Dict[int, Optional[str]], max_level: int, data: Optional[Dict[str, Any]],
                 data_path: str, equivalent: Optional[bool]) -> Dict[str, Any]:
    """추천 문자열 1개 자동 검증 4항목. pass = ①②④ 통과(③ 은 정보)."""
    p = parse_active(text)
    m = active_map(p)
    c1 = {"ok": not p["bad"] and p["tokens"] <= MAX_ITEMS and p["length"] <= MAX_LENGTH and p["format"] == "grouped",
          "parser": PARSER_KIND, "parserSrc": PARSER_SRC, "format": p["format"], "bad": p["bad"][:10], "nBad": len(p["bad"]),
          "tokens": p["tokens"], "maxTokens": MAX_ITEMS, "length": p["length"], "maxLength": MAX_LENGTH}
    want = {L: v for L, v in intent.items() if v}
    mism = [L for L in range(1, max(max_level, max(m, default=0)) + 1) if m.get(L) != want.get(L)]
    over = [L for L in m if L > max_level]
    c2 = {"ok": not mism, "range": [1, max_level], "levels": len(m), "intentLevels": len(want), "nMismatch": len(mism),
          "mismatch": _compress(mism)[:300], "beyondMax": _compress(over)[:100],
          "byPreset": {k: sum(1 for v in m.values() if v == k) for k in sorted(set(m.values()))}}
    if data is None:
        c3 = {"ok": None, "path": data_path, "error": "빌드 데이터 없음/읽기 실패"}
    else:
        lv = data.get("level") or {}
        miss = [L for L, q in sorted(m.items()) if str(L) not in (lv.get(q) or {})]
        unknown = sorted({q for q in m.values() if q not in (data.get("presets") or {})})
        c3 = {"ok": not unknown, "path": data_path, "created": data.get("created"), "n": data.get("n"),
              "nMissing": len(miss), "missing": _compress(miss)[:300], "unknownPresets": unknown,
              "note": "데이터 없는 레벨은 게임이 자동 제외(보스·L1 등) — 정보"}
    c4 = {"ok": equivalent is True, "value": equivalent}
    return {"pass": bool(c1["ok"] and c2["ok"] and c4["ok"] and c3.get("ok") is not False),
            "parse": c1, "intent": c2, "data": c3, "equivalent": c4}
