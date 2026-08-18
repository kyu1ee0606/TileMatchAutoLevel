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
from dataclasses import replace
from typing import Dict, Any, List, Optional, Tuple

from .bot_simulator import BotSimulator

logger = logging.getLogger(__name__)

DEFAULT_NODE_BUDGET = 60000
DEFAULT_TIME_BUDGET_S = 5.0  # 벽시계 제한 — 큰 레벨에서 행 방지(초과 시 UNCERTAIN)

# 솔버(=봇 엔진)의 모델이 불완전/비결정적인 기믹.
# 이런 기믹이 있으면 이동을 과소 생성해 '풀 수 있는데도 막다른 길'로 보일 수 있다(false dead-end).
# → '구조적 데드락' 결론을 신뢰 불가 → PROVEN_IMPOSSIBLE 대신 UNCERTAIN으로 강등.
# (÷3 수학적 위반은 기믹과 무관하므로 그대로 IMPOSSIBLE 유지.)
# 설계 근거: SOLVABILITY_REDESIGN.md "미지원 기믹 포함 레벨은 UNCERTAIN 처리".
UNRELIABLE_GIMMICKS = {"frog", "teleport", "bomb", "curtain", "unknown"}


def is_key_tile(tile_type: str, gimmick: str = "") -> bool:
    """게임의 키타일 판정을 그대로 따른다.

    DB_Level.cs:234
        isKeyTile => xTileID == "t16"
                  || xTileID.ToLower() == "key"
                  || xEffect.ToLower() == "key";

    **기믹(effect)이 "key" 이면 타일 색을 버리고 키타일(tileIDNum=16)로 취급한다.**
    즉 ["t8","key"] 는 게임에서 t8 이 아니라 키타일이다. 이걸 t8 로 세면
    에디터만 t8 이 ÷3 이라고 믿고 게임에선 1장 모자라 영구 매칭불가가 된다
    (실측: Lv111 튜토리얼이 key 를 속성으로 찍어 t7/t8/t11 이 전부 깨졌다).
    """
    return (
        tile_type == "t16"
        or tile_type.lower() == "key"
        or (gimmick or "").lower() == "key"
    )


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
    key_count = 0
    t0_count = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            gim = td[1] if len(td) > 1 and isinstance(td[1], str) else ""
            # [게임정합] 기믹이 key 면 색이 아니라 키타일 — 매칭타입 카운트에서 제외한다.
            if is_key_tile(tt, gim):
                key_count += 1
                continue
            if tt == "t0":
                t0_count += 1
            elif tt.startswith("craft_") or tt.startswith("stack_"):
                if len(td) > 2 and isinstance(td[2], list) and td[2]:
                    # [BAKE 정합] 내부타일이 명시 baked(td[2][1]="t3_t5_key…")면 그 타입을 '직접' 센다.
                    # 프론트 bake(bakeFullBoard)가 게임분배로 내부색을 이미 확정해 문자열로 박아넣는데,
                    # 여기서 개수(td[2][0])만 보고 백엔드 분배기로 재분배하면 프론트-분배와 어긋나
                    # (top-level은 concrete로 굳고 inner만 재분배) per-type ÷3 오탐이 난다.
                    # 명시 baked면 실제 데이터 그대로 평가 → 오탐 제거. placeholder(개수만/빈문자열/t0
                    # 포함)면 기존대로 t0로 재분배.
                    inner_str = td[2][1] if len(td[2]) > 1 and isinstance(td[2][1], str) else ""
                    baked = [s for s in inner_str.split("_") if s] if inner_str else []
                    is_baked = bool(baked) and all(
                        s == "key" or (s.startswith("t") and s[1:].isdigit() and s != "t0")
                        for s in baked
                    )
                    if is_baked:
                        for s in baked:
                            if s == "key":
                                key_count += 1  # 매칭 카운트엔 안 넣지만 toAdd 균형엔 필요
                            else:
                                concrete[s] = concrete.get(s, 0) + 1
                    else:
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
            # [KEY 균형] 게임 GetToAddIndexList(DB_Level.cs:1094)는 indexCountArr[16]까지 세서
            # **키 개수도 3배수로 맞춘다**. 명시 키가 4장이면 toAdd=[16,16] 이 되어 t0 두 장이
            # 매칭타일이 아니라 키로 승격된다. 여기서 key 를 빼고 넘기면 분배기가 그 사실을
            # 모른 채 그 t0 들을 색타일에 배정해 **없는 ÷3 위반을 만든다**
            # (실측 Lv1102: 게임은 t1=9 정상인데 게이트만 t1=11 위반이라 배포 차단).
            tile_type_offset=offset,
            existing_tile_counts=({**concrete, "key": key_count} if key_count else concrete),
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


def _copy_state(sim, state):
    """솔버용 mid-game 완전 복사.

    BotSimulator._fast_copy_state는 '한 시뮬 iteration 시작용 base 복사'라 dock_tiles/
    stacked_tiles/moves_used/combo 등 진행중 누적값을 초기화한다(봇은 같은 state에 누적
    플레이하므로 무관). 솔버는 진행중 상태를 복사하므로 이 누적값을 반드시 복원해야 한다.
    (복원 안 하면 dock이 매 수마다 비워져 3매치가 영원히 안 일어나 false IMPOSSIBLE.)
    """
    import copy as _copy
    child = sim._fast_copy_state(state)
    child.dock_tiles = [_copy.copy(t) for t in state.dock_tiles]
    child.moves_used = state.moves_used
    child.combo_count = getattr(state, "combo_count", 0)
    child.total_tiles_cleared = getattr(state, "total_tiles_cleared", 0)
    if getattr(state, "stacked_tiles", None):
        child.stacked_tiles = {k: _copy.copy(v) for k, v in state.stacked_tiles.items()}
    return child


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

    # 솔버 모델이 불완전한 기믹 탐지 — 구조적 IMPOSSIBLE 신뢰성 판단용
    unreliable: set = set()
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for t in ld["tiles"].values():
            if isinstance(t, list) and len(t) > 1 and isinstance(t[1], str) and t[1]:
                base = t[1].split("_")[0].lower()
                if base in UNRELIABLE_GIMMICKS:
                    unreliable.add(base)

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

    # time_budget_s <= 0 → 벽시계 무제한(노드 예산만으로 종료). 의심 레벨 정밀 검증용.
    no_time_limit = time_budget_s <= 0
    while heap and nodes < node_budget:
        if not no_time_limit and nodes % 256 == 0 and (time.monotonic() - t_start) > time_budget_s:
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
            child = _copy_state(sim, state)
            # 🔴 핵심: move.tile_state는 '부모' state의 타일 객체를 가리킨다. 복사된 child에
            # 그대로 적용하면 부모 타일을 건드려 child 보드가 안 바뀐다(타일 제거 안 됨 → 영원히
            # 클리어 불가로 오판). 반드시 child의 동일 위치 타일로 tile_state를 교체해 적용한다.
            child_tile = child.tiles.get(move.layer_idx, {}).get(move.position)
            if child_tile is None:
                continue
            cmove = replace(move, tile_state=child_tile)
            try:
                sim._apply_move(child, cmove)
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
    # 상태공간 완전 소진했는데 클리어 못 함 → 보통 진짜 구조적 데드락.
    # 단, 솔버 모델이 불완전한 기믹(frog/teleport/bomb/curtain/unknown)이 있으면 이동을 과소
    # 생성해 '풀 수 있는데도' 막다른 길로 보였을 수 있다 → IMPOSSIBLE 단정 불가, UNCERTAIN 강등.
    if unreliable:
        return {
            "verdict": "UNCERTAIN",
            "reason": f"도달 상태({nodes}개) 모두 막혔으나 미지원 기믹({', '.join(sorted(unreliable))}) 포함 — "
                      f"솔버가 해당 기믹 이동을 완전 모델링 못 해 false 데드락 가능. 불가능 단정 보류",
            "nodes_expanded": nodes,
            "moves_to_clear": None,
            "divisibility_violation": None,
            "unsupported_gimmicks": sorted(unreliable),
        }
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


# ─────────────────────────────────────────────────────────────────────────────
# 실수 내성(robustness) — A* 기반 객관 난이도 눈금
#
# 왜 필요한가:
#   난이도 판정을 RL 봇 시뮬(predicted_clear_rate)에 의존해 왔는데, 이 값은 봇 휴리스틱의
#   강약에 좌우된다(실측: RL 전 구간 0.000 인 Lv710 을 A* 는 108노드로 해결). 반면 solve_level
#   은 "풀리는가"만 답하는 이진값이라 난이도 눈금이 못 된다.
#
#   실수 내성은 그 사이를 메운다: **각 시점에서 아무 수나 뒀을 때 여전히 클리어 가능한 수의 비율**.
#     1.0 = 무슨 수를 둬도 클리어 (아주 쉬움)
#     0.05 = 20수 중 1수만 정답 (극악)
#   봇의 판단력이 아니라 레벨 구조만으로 정해지므로 봇 편향이 없다.
#
# 비용:
#   결정지점 × 합법수 × solve_level 1회. 81타일/합법수 7이면 ~570회 호출.
#   그래서 표본 파라미터(max_depth / move_cap)로 상한을 둔다 — 전수 측정이 아니라
#   **RL 눈금을 검증·보정하기 위한 기준자** 용도.
# ─────────────────────────────────────────────────────────────────────────────

def _solvable_from_state(sim: "BotSimulator", state, node_budget: int, time_budget_s: float) -> Optional[bool]:
    """주어진 중간 상태에서 클리어 가능한지. True/False/None(예산초과 미확정)."""
    if _remaining_count(state) == 0:
        return True
    visited = {_state_signature(state)}
    counter = 0
    heap: List[Tuple] = [(_remaining_count(state), 0, counter, state, 0)]
    nodes = 0
    t0 = time.monotonic()
    no_limit = time_budget_s <= 0
    while heap and nodes < node_budget:
        if not no_limit and nodes % 256 == 0 and (time.monotonic() - t0) > time_budget_s:
            return None
        _, _, _, cur, _d = heapq.heappop(heap)
        nodes += 1
        moves = sim._get_available_moves(cur)
        if not moves:
            continue
        moves.sort(key=lambda m: (not m.will_match,))
        for move in moves:
            child = _copy_state(sim, cur)
            ct = child.tiles.get(move.layer_idx, {}).get(move.position)
            if ct is None:
                continue
            try:
                sim._apply_move(child, replace(move, tile_state=ct))
            except Exception:  # noqa: BLE001
                continue
            sim._is_game_over(child)
            if child.cleared:
                return True
            if child.failed:
                continue
            sig = _state_signature(child)
            if sig in visited:
                continue
            visited.add(sig)
            counter += 1
            heapq.heappush(heap, (_remaining_count(child), 0, counter, child, _d + 1))
    if nodes >= node_budget:
        return None
    return False   # 상태공간 소진 → 이 지점에서는 클리어 불가 확정


def measure_robustness(
    level_json: Dict[str, Any],
    max_depth: int = 40,
    move_cap: int = 8,
    node_budget: int = 20000,
    time_budget_s: float = 2.0,
) -> Dict[str, Any]:
    """실수 내성 측정. 클리어 경로를 따라가며 각 시점의 '안전한 수 비율'을 잰다.

    진행 방식: 안전한 수 중 하나를 골라 실제로 진행한다(안전수가 없으면 종료).
    안전수 우선 진행이므로 **클리어 경로 위의 난이도**를 재는 것이고, 이는
    "정답을 아는 플레이어가 겪는 선택 압박"에 해당한다.

    Args:
        max_depth: 측정할 결정지점 수 상한(비용 상한). 0=제한 없음
        move_cap: 한 지점에서 평가할 합법수 상한(많으면 앞쪽 will_match 우선)
    """
    sim = BotSimulator()
    total_raw = 0
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if isinstance(ld, dict) and isinstance(ld.get("tiles"), dict):
            total_raw += len(ld["tiles"])
    lvl = dict(level_json)
    lvl["max_moves"] = total_raw + 100
    try:
        state = sim._create_initial_state(lvl, lvl["max_moves"])
        sim._precompute_blocking_map(state)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"초기상태 생성 실패: {exc}"}

    started = time.monotonic()
    points: List[Dict[str, Any]] = []
    depth = 0
    uncertain_hits = 0
    unmeasured = 0
    while True:
        if max_depth and depth >= max_depth:
            break
        moves = sim._get_available_moves(state)
        if not moves:
            break
        moves.sort(key=lambda m: (not m.will_match,))
        evaluated = moves[:move_cap] if move_cap else moves
        safe_children = []
        safe = 0
        unsafe = 0
        for move in evaluated:
            child = _copy_state(sim, state)
            ct = child.tiles.get(move.layer_idx, {}).get(move.position)
            if ct is None:
                continue
            try:
                sim._apply_move(child, replace(move, tile_state=ct))
            except Exception:  # noqa: BLE001
                continue
            sim._is_game_over(child)
            if child.cleared:
                safe += 1
                safe_children.append(child)
                continue
            if child.failed:
                unsafe += 1
                continue
            v = _solvable_from_state(sim, child, node_budget, time_budget_s)
            if v is None:
                uncertain_hits += 1
                continue          # 미확정은 안전/위험 어느 쪽으로도 세지 않는다
            if v:
                safe += 1
                safe_children.append(child)
            else:
                unsafe += 1
        # [중요] 비율의 분모는 '평가한 수'가 아니라 **결론이 난 수**여야 한다.
        # 예산 초과(None)를 위험수로 세면 예산이 빡빡할 때 비율이 0으로 붕괴한다
        # (실측: Lv504 가 6개 전부 미확정인데 ratio 0.0 으로 기록됨 → 최난이도로 오판).
        n_conclusive = safe + unsafe
        if n_conclusive == 0:
            # 이 지점은 측정 불가 — 기록하지 않고, 진행만 시도한다(안전수 후보도 없음)
            unmeasured += 1
            break
        points.append({"depth": depth, "legal_moves": len(moves),
                       "evaluated": len(evaluated), "conclusive": n_conclusive, "safe": safe,
                       "ratio": round(safe / n_conclusive, 4)})
        if not safe_children:
            break                  # 안전수 없음 → 여기서 종료(막다른 지점)
        state = safe_children[0]   # 안전수 하나 골라 진행
        if state.cleared:
            break
        depth += 1

    ratios = [p["ratio"] for p in points]
    return {
        "ok": True,
        "total_tiles": total_raw,
        "use_tile_count": int(level_json.get("useTileCount") or 0),
        "points_measured": len(points),
        # 평균 안전수 비율 = 주 지표. 낮을수록 어렵다.
        "safe_move_ratio": round(sum(ratios) / len(ratios), 4) if ratios else None,
        "min_safe_ratio": round(min(ratios), 4) if ratios else None,
        "avg_legal_moves": round(sum(p["legal_moves"] for p in points) / len(points), 2) if points else 0,
        "uncertain_evals": uncertain_hits,
        "unmeasured_points": unmeasured,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "points": points,
    }
