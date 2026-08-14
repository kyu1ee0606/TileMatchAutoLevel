"""[초반 고정 레벨] 1~31 레벨을 **매번 같은 모양·같은 타일**로 내보내기 위한 전용 저장소.

왜 필요한가:
  초반 구간은 튜토리얼 성격이라 매 배치마다 모양이 바뀌면 학습 흐름·난이도 곡선이 흔들린다.
  기존엔 Lv1~3 만 생성기에 하드코딩(`_create_fixed_layout_level_1/2/3`)돼 있었고 4~31 은
  매번 절차생성이라 배치마다 달랐다. 여기 저장된 레벨은 생성 시 **그대로** 쓰인다.

보스 슬롯(10·20·30)은 **저장 대상이 아니다**:
  보스는 전용 보스 템플릿(`from-boss-template`)이 정본이고, 그쪽에서 모양·기믹·그래프가
  일관되게 관리된다. 여기서 따로 고정하면 두 정본이 생겨 드리프트가 난다.
  → 조회(확인)만 허용하고 저장/삭제는 거부한다.

엔트리 형식:
    "7": {
      "level_json": {...},          # 완성 레벨(모양+타일타입+기믹) — 그대로 출고
      "updated_at": "ISO8601",
      "source": "seed" | "manual",  # seed=기존 파이프라인 산출물 이관, manual=에디터 저장
      "note": ""
    }
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

_THIS = os.path.dirname(os.path.abspath(__file__))
STORE_PATH = os.path.normpath(os.path.join(_THIS, "..", "..", "data", "fixed_levels.json"))

# 고정 대상 구간. 이 범위 밖 레벨은 저장해도 생성에 쓰이지 않는다(오용 방지).
RANGE_START = 1
RANGE_END = 31
# 보스 슬롯 — 읽기 전용(보스 템플릿이 정본)
BOSS_LEVELS = tuple(n for n in range(RANGE_START, RANGE_END + 1) if n % 10 == 0)


def is_in_range(level_number: int) -> bool:
    return RANGE_START <= int(level_number) <= RANGE_END


def is_boss(level_number: int) -> bool:
    return int(level_number) in BOSS_LEVELS


def _load() -> Dict[str, Any]:
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(d: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(STORE_PATH), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def get_fixed(level_number: int) -> Optional[Dict[str, Any]]:
    """해당 레벨의 고정 엔트리. 범위 밖·보스·미등록이면 None."""
    n = int(level_number)
    if not is_in_range(n) or is_boss(n):
        return None
    e = _load().get(str(n))
    return e if isinstance(e, dict) and e.get("level_json") else None


def put_fixed(level_number: int, level_json: Dict[str, Any],
              source: str = "manual", note: str = "") -> Dict[str, Any]:
    n = int(level_number)
    if not is_in_range(n):
        raise ValueError(f"고정 대상 구간({RANGE_START}~{RANGE_END}) 밖: Lv{n}")
    if is_boss(n):
        raise PermissionError(f"Lv{n} 은 보스 슬롯 — 보스 템플릿이 정본이라 여기서 수정 불가")
    if not isinstance(level_json, dict) or not level_json.get("layer"):
        raise ValueError("level_json 이 비었거나 layer 필드가 없음")
    d = _load()
    entry = {
        "level_json": level_json,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "source": source,
        "note": note,
    }
    d[str(n)] = entry
    _save(d)
    return entry


def delete_fixed(level_number: int) -> bool:
    n = int(level_number)
    if is_boss(n):
        raise PermissionError(f"Lv{n} 은 보스 슬롯 — 삭제 대상 아님")
    d = _load()
    if str(n) not in d:
        return False
    d.pop(str(n))
    _save(d)
    return True


def summary(lj: Dict[str, Any]) -> Dict[str, Any]:
    """목록 표시에 쓰는 경량 요약 + 층별 좌표(미리보기용)."""
    n = int(lj.get("layer") or 0)
    layers: List[Dict[str, Any]] = []
    total = 0
    for i in range(n):
        ld = lj.get(f"layer_{i}") or {}
        tiles = ld.get("tiles") or {}
        total += len(tiles)
        try:
            col = int(ld.get("col"))
        except (TypeError, ValueError):
            col = 0
        layers.append({"col": col, "cells": sorted(tiles.keys())})
    return {"layer_count": n, "total_tiles": total, "layers": layers}


def list_slots() -> List[Dict[str, Any]]:
    """1~31 전 슬롯 상태. 보스는 readonly=True 로 표시된다."""
    d = _load()
    out: List[Dict[str, Any]] = []
    for n in range(RANGE_START, RANGE_END + 1):
        boss = is_boss(n)
        e = d.get(str(n)) if not boss else None
        item: Dict[str, Any] = {
            "level": n,
            "readonly": boss,
            "reason": "보스 슬롯 — 보스 템플릿이 정본" if boss else None,
            "fixed": bool(e and e.get("level_json")),
            "source": (e or {}).get("source"),
            "updated_at": (e or {}).get("updated_at"),
            "note": (e or {}).get("note"),
        }
        if e and e.get("level_json"):
            item.update(summary(e["level_json"]))
        out.append(item)
    return out
