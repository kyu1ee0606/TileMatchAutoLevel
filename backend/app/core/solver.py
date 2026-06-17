"""
A* / best-first 완전탐색 솔버 — 레벨 클리어 가능성을 양방향 확정 판정.

설계: claudedocs/SOLVABILITY_REDESIGN.md (설계2)

휴리스틱 봇(가지치기 그리디)과 달리 **모든 합법 이동을 탐색**한다. 단, 이동 합법성/
기믹/매칭/독 규칙은 검증된 BotSimulator 원시함수를 그대로 재사용해 게임 규칙과
정확히 일치시킨다(휴리스틱 '선택'만 완전탐색으로 대체).

판정:
- PROVEN_SOLVABLE: 클리어 경로(witness) 발견 — 확실히 풀 수 있음
- PROVEN_IMPOSSIBLE: (a) 타입 카운트 ÷3 위반(즉시), 또는 (b) 메모이즈 상태공간 완전 소진
- UNCERTAIN: 노드 예산 초과 — 확정 못 함(휴리스틱 결과로 폴백)

주의: max_moves(이동 제한)는 '솔버블' 판정에서 무력화한다 — "이동 제한 안에서 풀리나"가
아니라 "애초에 풀 수 있는 구조인가"를 본다. t0 타일은 randSeed 기반 분배 후 그 구체
분배를 푼다(인게임과 동일).
"""
import heapq
import logging
import time
from typing import Dict, Any, List, Optional, Tuple

from .bot_simulator import BotSimulator

logger = logging.getLogger(__name__)

DEFAULT_NODE_BUDGET = 60000
DEFAULT_TIME_BUDGET_S = 5.0  # 벽시계 제한 — 큰 레벨에서 행 방지(초과 시 UNCERTAIN)


def _clearability_type_counts(level_json: Dict[str, Any]) -> Dict[str, int]:
    """실게임(클라이언트) 분배 기준 매칭타입별(t1~t15) 최종 카운트.

    ÷3 클리어가능성은 '실제 플레이에 등장하는 모든 타일'로 판정해야 한다. 이는:
      concrete(t1~t15 고정배치) + (regular t0 + craft/stack 내부 t0 전체)를 클라 분배
      (TileDistributor.assign_t0_tiles, DB_Level.cs 포트)한 결과다.
    주의: 봇의 state.all_tile_type_counts나 위치기반 카운트는 craft 컨테이너 내부타일을
    덜 세어(시뮬 특성) false ÷3 위반을 만든다 — 반드시 클라 분배로 측정한다.
    """
    from .bot_simulator import TileDistributor

    concrete: Dict[str, int] = {}
    t0_count = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            if tt == "t0":
                t0_count += 1
            elif tt.startswith("craft_") or tt.startswith("stack_"):
                if len(td) > 2 and isinstance(td[2], list) and td[2]:
                    try:
                        t0_count += int(td[2][0])
                    except (ValueError, TypeError):
                        pass
            elif tt.startswith("t") and tt[1:].isdigit():
                concrete[tt] = concrete.get(tt, 0) + 1

    combined = dict(concrete)
    if t0_count > 0:
        use_tile_count = min(int(level_json.get("useTileCount", 6) or 6), 15)
        existing = [t for t in concrete if t[1:].isdigit()]
        offset = 0
        if existing:
            mn = min(int(t[1:]) for t in existing)
            offset = mn - 1 if mn > use_tile_count else 0
        assigns = TileDistributor.assign_t0_tiles(
            t0_count=t0_count, use_tile_count=use_tile_count,
            rand_seed=int(level_json.get("randSeed", 0) or 0),
            shuffle_tile=level_json.get("xShuffleTile", 0),
            type_imbalance=level_json.get("xTypeImbalance", 0),
            unlock_tile=level_json.get("unlockTile", level_json.get("xUnlockTile", 0)),
            tile_type_offset=offset, existing_tile_counts=concrete,
        )
        for t in assigns:
            if isinstance(t, str) and t.startswith("t") and t[1:].isdigit():
                combined[t] = combined.get(t, 0) + 1
    return {t: c for t, c in combined.items() if c > 0}


def _state_signature(state) -> Tuple:
    """미래 플레이에 영향을 주는 모든 것을 담은 해시 가능한 시그니처."""
    tiles_sig = []
    for layer_idx, layer in state.tiles.items():
        for pos, tile in layer.items():
            if tile.picked:
                continue
            ed = tile.effect_data or {}
            # 기믹 상태 중 플레이에 영향 주는 핵심만(ice/grass 잔여, chain 잠금)
            eff = (
                tile.effect_type.value if hasattr(tile.effect_type, "value") else str(tile.effect_type),
                ed.get("remaining"),
                ed.get("unlocked"),
            )
            tiles_sig.append((layer_idx, pos, tile.tile_type, eff))
    tiles_sig.sort()
    dock_sig = tuple(sorted(t.tile_type for t in state.dock_tiles))
    return (tuple(tiles_sig), dock_sig)


def _remaining_count(state) -> int:
    return sum(1 for layer in state.tiles.values() for t in layer.values() if not t.picked)


def solve_level(
    level_json: Dict[str, Any],
    node_budget: int = DEFAULT_NODE_BUDGET,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
) -> Dict[str, Any]:
    """
    레벨 클리어 가능성 판정. 반환:
    {
      verdict: "PROVEN_SOLVABLE" | "PROVEN_IMPOSSIBLE" | "UNCERTAIN",
      reason: str,
      nodes_expanded: int,
      moves_to_clear: int | None,   # SOLVABLE일 때 witness 길이
      divisibility_violation: dict | None,
    }
    """
    sim = BotSimulator()

    total_tiles_raw = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if isinstance(ld, dict) and isinstance(ld.get("tiles"), dict):
            total_tiles_raw += len(ld["tiles"])

    # 이동 제한 무력화 — 솔버블 판정은 구조적 가능성만 본다
    lvl = dict(level_json)
    lvl["max_moves"] = total_tiles_raw + 100

    # raw json의 t0(런타임 분배) 타일 수 — 진단 메시지용
    raw_t0 = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for t in ld["tiles"].values():
            if isinstance(t, list) and t and isinstance(t[0], str) and t[0] == "t0":
                raw_t0 += 1

    try:
        base_state = sim._create_initial_state(lvl, lvl["max_moves"])
        sim._precompute_blocking_map(base_state)
    except Exception as exc:
        return {"verdict": "UNCERTAIN", "reason": f"초기상태 생성 실패: {exc}",
                "nodes_expanded": 0, "moves_to_clear": None, "divisibility_violation": None}

    # (a) ÷3 카운트 체크 — 실게임(클라) 분배 기준 매칭타입 카운트로 판정.
    #   2026-06-16 규명: '언클리어러블'의 ÷3 위반은 분배기 포트 버그가 아니라 **생성기가
    #   비÷3 총 타일 수를 출고**한 것이 원인이었다(generator._finalize_divisibility_guarantee로
    #   수정). 분배기(assign_t0_tiles)는 총합 ÷3이면 per-type ÷3을 항상 만든다(증명).
    #   따라서 여기서 ÷3 위반이 잡히면 t0/concrete 무관하게 **생성 단계의 총합 ÷3 보정 실패**다.
    counts = _clearability_type_counts(level_json)
    bad = {t: c for t, c in counts.items() if c % 3 != 0}
    if bad:
        return {
            "verdict": "PROVEN_IMPOSSIBLE",
            "reason": f"매칭타입 3배수 위반(총합 비÷3 = 클리어 불가): {bad}. "
                      f"생성기 ÷3 보정 누락 의심(raw_t0={raw_t0}) — 재생성 필요",
            "nodes_expanded": 0, "moves_to_clear": None,
            "divisibility_violation": bad,
        }

    # (b) 완전탐색 (best-first: 남은 타일 적은 상태 우선 → 해를 빠르게 발견)
    start_remaining = _remaining_count(base_state)
    if start_remaining == 0:
        return {"verdict": "PROVEN_SOLVABLE", "reason": "타일 없음(이미 클리어)",
                "nodes_expanded": 0, "moves_to_clear": 0, "divisibility_violation": None}

    visited = set()
    visited.add(_state_signature(base_state))
    # heap entries: (remaining, tiebreak, counter, state, depth)
    counter = 0
    heap: List[Tuple] = [(start_remaining, 0, counter, base_state, 0)]
    nodes = 0
    t_start = time.monotonic()
    timed_out = False

    while heap and nodes < node_budget:
        if nodes % 256 == 0 and (time.monotonic() - t_start) > time_budget_s:
            timed_out = True
            break
        remaining, _, _, state, depth = heapq.heappop(heap)
        nodes += 1

        moves = sim._get_available_moves(state)
        if not moves:
            continue  # dead end (no legal move) — 다른 분기 계속

        # will_match(매치 완성) 이동을 먼저 펼침 — 해를 빠르게 발견(완전성 유지: 가지치기 아님, 정렬만)
        moves.sort(key=lambda m: (not m.will_match,))

        for move in moves:
            child = sim._fast_copy_state(state)
            try:
                sim._apply_move(child, move)
            except Exception:
                continue
            sim._is_game_over(child)  # cleared/failed 플래그 세팅

            if child.cleared:
                return {
                    "verdict": "PROVEN_SOLVABLE",
                    "reason": "클리어 경로 발견",
                    "nodes_expanded": nodes,
                    "moves_to_clear": depth + 1,
                    "divisibility_violation": None,
                }
            if child.failed:
                continue  # 이 가지는 실패(독 오버플로/기믹 불가 등) — 버림

            sig = _state_signature(child)
            if sig in visited:
                continue
            visited.add(sig)
            counter += 1
            child_remaining = _remaining_count(child)
            heapq.heappush(heap, (child_remaining, 0, counter, child, depth + 1))

    if timed_out or nodes >= node_budget:
        cap = f"시간({time_budget_s}s)" if timed_out else f"노드({node_budget})"
        return {
            "verdict": "UNCERTAIN",
            "reason": f"{cap} 예산 초과 — 너무 큰 상태공간. 휴리스틱 결과 참조",
            "nodes_expanded": nodes,
            "moves_to_clear": None,
            "divisibility_violation": None,
        }

    # 상태공간 완전 소진했는데 클리어 못 함 → 진짜 불가능 증명
    return {
        "verdict": "PROVEN_IMPOSSIBLE",
        "reason": f"도달 가능한 모든 상태({nodes}개) 탐색했으나 클리어 경로 없음 — 구조적 데드락",
        "nodes_expanded": nodes,
        "moves_to_clear": None,
        "divisibility_violation": None,
    }


def solve_level_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """ProcessPool 워커 (레벨 단위 병렬). args: {level_number, level_json, node_budget}"""
    try:
        result = solve_level(args["level_json"], node_budget=args.get("node_budget", DEFAULT_NODE_BUDGET))
        result["level_number"] = args.get("level_number")
        result["error"] = None
        return result
    except Exception as exc:
        logger.exception("[solver] task failed (level %s)", args.get("level_number"))
        return {"level_number": args.get("level_number"), "error": str(exc),
                "verdict": "UNCERTAIN", "reason": f"오류: {exc}",
                "nodes_expanded": 0, "moves_to_clear": None, "divisibility_violation": None}
