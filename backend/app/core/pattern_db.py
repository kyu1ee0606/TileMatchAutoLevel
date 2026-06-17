"""
[v16 🅑] 절차생성/AI 패턴 영속 저장소 (SQLite).

배경: AI 자동 큐레이션으로 생성한 패턴 템플릿을 'DB 형태'로 영속 저장해야 한다.
프로젝트엔 기존 SQL 인프라가 없고 모든 패턴 reader(생성기 `_get_custom_pattern`,
에디터 `/debug/pattern-list`·`/debug/custom-patterns`, 미리보기)가 custom_patterns.json을
읽는다. 따라서 SQLite를 **정본(source of truth)** 으로 두되, 쓰기마다 synth 항목을
custom_patterns.json으로 **materialize** 해 기존 파이프라인을 무변경으로 유지한다.

스키마: 한 행 = (pattern_index, grid_size) 변형 1개 — custom_patterns.json의 size_key 입도와
동일해 materialize가 단순(1:1). 한 컨셉은 여러 사이즈 행으로 구성(같은 pattern_index).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "data", "patterns.db"))
CUSTOM_PATTERNS_PATH = os.path.normpath(
    os.path.join(_THIS_DIR, "..", "..", "data", "custom_patterns.json")
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS synth_patterns (
    pattern_index INTEGER NOT NULL,
    grid_size     INTEGER NOT NULL,
    positions     TEXT    NOT NULL,   -- JSON 배열 ["x_y", ...]
    count         INTEGER NOT NULL,
    score         REAL,
    strategy      TEXT,
    symmetry      TEXT,
    name          TEXT,
    created_at    REAL,
    PRIMARY KEY (pattern_index, grid_size)
);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(_SCHEMA)
    return conn


def init_db() -> None:
    _connect().close()


def next_index(start: int = 64) -> int:
    """다음 빈 pattern_index. DB와 custom_patterns.json 양쪽에서 사용 중인 인덱스 회피."""
    used: set[int] = set()
    with _connect() as conn:
        for r in conn.execute("SELECT DISTINCT pattern_index FROM synth_patterns"):
            used.add(int(r["pattern_index"]))
    # JSON에 있는 인덱스(빌트인/수동 포함)도 회피 — 충돌 방지
    try:
        with open(CUSTOM_PATTERNS_PATH, "r") as f:
            data = json.load(f)
        for k in data.keys():
            try:
                used.add(int(k.split("_")[0]))
            except (ValueError, IndexError):
                continue
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    idx = start
    while idx in used:
        idx += 1
    return idx


def save_concept(
    pattern_index: int,
    variants: List[Dict[str, Any]],
    score: Optional[float] = None,
    strategy: Optional[str] = None,
    symmetry: Optional[str] = None,
    name: Optional[str] = None,
) -> List[int]:
    """한 컨셉의 모든 사이즈 변형을 한 pattern_index 아래 upsert. 저장된 사이즈 목록 반환."""
    ts = _now()
    sizes: List[int] = []
    with _connect() as conn:
        for v in variants:
            gs = int(v["grid_size"])
            positions = list(v["positions"])
            conn.execute(
                "INSERT OR REPLACE INTO synth_patterns "
                "(pattern_index, grid_size, positions, count, score, strategy, symmetry, name, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (pattern_index, gs, json.dumps(positions), len(positions),
                 score, strategy, symmetry, name, ts),
            )
            sizes.append(gs)
        conn.commit()
    return sorted(sizes)


def delete_index(pattern_index: int) -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM synth_patterns WHERE pattern_index = ?", (pattern_index,))
        conn.commit()
        return cur.rowcount


def list_indices(max_size: Optional[int] = None) -> List[int]:
    """저장된 synth pattern_index 목록. max_size 지정 시 해당 크기 이하 변형이 있는 인덱스만."""
    q = "SELECT DISTINCT pattern_index FROM synth_patterns"
    args: tuple = ()
    if max_size is not None:
        q += " WHERE grid_size <= ?"
        args = (int(max_size),)
    with _connect() as conn:
        return sorted(int(r["pattern_index"]) for r in conn.execute(q, args))


def all_variants() -> List[Dict[str, Any]]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM synth_patterns ORDER BY pattern_index, grid_size")]


def materialize_to_json() -> int:
    """DB의 synth 항목 전체를 custom_patterns.json에 반영(정본=DB). 기존 비-synth 항목은 보존,
    JSON에 남은 고아 synth 항목(DB에 없음)은 제거. 반영된 변형 수 반환."""
    try:
        with open(CUSTOM_PATTERNS_PATH, "r") as f:
            data: Dict[str, Any] = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}

    # 1) 기존 synth 항목 모두 제거(DB가 정본) — 비-synth(빌트인/수동)는 보존
    for k in [k for k, v in list(data.items()) if isinstance(v, dict) and v.get("synth")]:
        del data[k]

    # 2) DB 항목으로 재구성
    n = 0
    for r in all_variants():
        size_key = f"{r['pattern_index']}_{r['grid_size']}x{r['grid_size']}"
        entry: Dict[str, Any] = {
            "grid_size": r["grid_size"],
            "positions": json.loads(r["positions"]),
            "count": r["count"],
            "synth": True,
        }
        if r["name"]:
            entry["name"] = r["name"]
        data[size_key] = entry
        n += 1

    tmp = CUSTOM_PATTERNS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, CUSTOM_PATTERNS_PATH)
    return n


def _now() -> float:
    return time.time()
