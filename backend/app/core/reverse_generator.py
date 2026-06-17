"""
역생성 (Reverse / Constructive Generation) — v1.

설계: claudedocs/SOLVABILITY_REDESIGN.md (설계1)

핵심: 모양/레이어(=커버 의존성 DAG)는 기존 생성기 산출을 그대로 두고, **타입 배정만**
독≤7을 지키는 witness peeling 순서가 존재하도록 구성한다. 그 순서가 곧 해의 증거이므로
솔버블 100% + ÷3 자동 보장.

v1 범위 (정확성·검증가능성 우선):
- 적용 대상: **plain 타일(t1~t15)만 있는 concrete 레벨**. ice/grass 속성은 허용(순서 불변).
- 제외(폴백): craft/stack 컨테이너, 순서 기믹(chain/link/key/lock/teleport/frog/bomb/curtain).
  → 이런 레벨은 (level, applied=False)로 반환, 호출측이 기존 타입을 유지.
- 자가검증: A* 솔버(solver.solve_level)로 PROVEN_SOLVABLE 교차확인. 실패 시 미적용.

난이도 레버: max_open(동시 미완성 그룹 수). 클수록 타일을 오래 들고 계획 → 어려움.
v1은 독 안전을 위해 1~3으로 제한(held ≤ 2*max_open ≤ 6 < 7).
"""
import copy
import logging
from typing import Dict, Any, List, Tuple, Optional, Set

from .bot_simulator import BotSimulator

logger = logging.getLogger(__name__)

# [v2] 역생성이 허용하는 안전 기믹(속성). 위트니스 타입배정은 기믹과 무관하고, 봇클리어
# 검증으로 실제 플레이 가능성을 확정한다. ice/grass는 추가 탭만 요구(순서 불변), chain/link는
# 결정적이라 봇이 정확히 모델링 → 검증 통과 시 채택, 실패 시 degrade(아래 단계적 제거).
SAFE_GIMMICKS = {"ice", "grass", "chain", "link"}
# 컨테이너(craft/stack)·key 타일 외에, 비결정/복잡 기믹은 여전히 미지원(붙어있으면 폴백).
UNSUPPORTED_GIMMICKS = {"frog", "teleport", "bomb", "curtain", "unknown", "time", "timeattack", "lock"}


def _attr_base(attr: Any) -> str:
    if not attr or not isinstance(attr, str):
        return ""
    return attr.split("_")[0].lower()


def has_unsupported_features(level_json: Dict[str, Any]) -> Optional[str]:
    """역생성이 처리 못 하는 요소가 있으면 사유 문자열, 없으면 None.

    [v2] 안전 기믹(ice/grass/chain/link)은 허용. 컨테이너(craft/stack)·key 타일·비결정 기믹
    (frog/teleport/bomb/curtain/unknown/lock)만 미지원으로 폴백 처리.
    """
    num_layers = int(level_json.get("layer", 0) or 0)
    for i in range(num_layers):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            if tt.startswith("craft_") or tt.startswith("stack_"):
                return "컨테이너(craft/stack)"
            if tt == "key":
                return "key 타일"
            ab = _attr_base(td[1] if len(td) > 1 else "")
            if ab and ab not in SAFE_GIMMICKS:
                return f"미지원 기믹({ab})"
    return None


def _witness_assign(order: List[str], use_tile_count: int, max_open: int) -> Optional[Dict[str, str]]:
    """peel 순서를 따라 타입 배정. 각 그룹=정확히 3개(÷3 자동), 동시 미완성 그룹은 서로 다른 타입,
    held(=미완성 타일 수) ≤ 7 유지. 성공 시 {full_key: 'tN'}, 실패 시 None."""
    max_open = max(1, min(max_open, use_tile_count, 3))
    open_groups: List[Dict[str, Any]] = []  # {type, count}
    used_types: Set[str] = set()
    assign: Dict[str, str] = {}
    n = len(order)

    def fresh_type() -> Optional[str]:
        for idx in range(1, use_tile_count + 1):
            t = f"t{idx}"
            if t not in used_types:
                return t
        return None

    for i, key in enumerate(order):
        remaining_after = n - i - 1
        needed_to_close = sum(3 - g["count"] for g in open_groups)
        held = sum(g["count"] for g in open_groups)

        # 새 그룹을 열 수 있는가? (독 여유 + 남은 타일로 전부 마감 가능 + 빈 타입 존재)
        can_open = (
            len(open_groups) < max_open
            and held + 1 <= 7
            and remaining_after >= needed_to_close + 2  # 이 타일=새그룹1개째, 마감에 +2 더 필요
            and len(used_types) < use_tile_count
        )
        # 남은 타일이 빠듯하면 무조건 마감 모드
        must_close = remaining_after < needed_to_close + (2 if not open_groups else 0)

        open_new = (not open_groups) or (can_open and not must_close and len(open_groups) < max_open)

        if open_new:
            t = fresh_type()
            if t is None:
                # 빈 타입 없음 → 기존 그룹에 합류로 대체
                open_new = False
            else:
                open_groups.append({"type": t, "count": 1})
                used_types.add(t)
                assign[key] = t

        if not open_new:
            if not open_groups:
                return None  # 열 수도, 합류할 수도 없음
            # 합류: count==2(마감해 독 비움) 우선, 없으면 가장 오래된 것
            g = next((g for g in open_groups if g["count"] == 2), open_groups[0])
            g["count"] += 1
            assign[key] = g["type"]
            if g["count"] == 3:
                open_groups.remove(g)
                used_types.discard(g["type"])

    if open_groups:
        return None  # 마감 안 된 그룹 잔존
    return assign


def apply_reverse_generation(
    level_json: Dict[str, Any],
    use_tile_count: int,
    max_open: int = 2,
    verify: bool = True,
) -> Tuple[Dict[str, Any], bool, str]:
    """
    concrete 레벨의 plain 타일 타입을 witness peeling으로 재배정.

    Returns: (level_json, applied, reason)
      applied=True 면 솔버블·÷3 보장된 새 level_json. False면 원본 그대로(사유 reason).
    """
    unsupported = has_unsupported_features(level_json)
    if unsupported:
        return level_json, False, f"미지원: {unsupported}"

    sim = BotSimulator()
    try:
        state = sim._create_initial_state(level_json, 99999)
        sim._precompute_blocking_map(state)
    except Exception as exc:  # noqa: BLE001
        return level_json, False, f"상태생성 실패: {exc}"

    tiles_by_key: Dict[str, Any] = {}
    for layer in state.tiles.values():
        for tile in layer.values():
            tiles_by_key[tile.full_key] = tile

    matchable = [
        k for k, t in tiles_by_key.items()
        if isinstance(t.tile_type, str) and t.tile_type.startswith("t")
        and t.tile_type[1:].isdigit() and t.tile_type != "t0"
    ]
    n = len(matchable)
    if n == 0:
        return level_json, False, "매칭 타일 없음"
    if n % 3 != 0:
        return level_json, False, f"매칭 타일 {n}개 ÷3 아님(생성기 ÷3 보정 선행 필요)"

    blocking: Dict[str, Set[str]] = state._blocking_map or {}
    matchset = set(matchable)

    # peel 순서: 노출(상위 블로커 전부 제거됨)된 타일을 위층부터 꺼냄
    remaining = set(matchable)
    order: List[str] = []
    guard = 0
    while remaining and guard <= n + 5:
        guard += 1
        exposed = [k for k in remaining if not (blocking.get(k, set()) & remaining)]
        if not exposed:
            return level_json, False, "peel 데드락(순환 커버?)"
        exposed.sort(key=lambda k: (tiles_by_key[k].layer_idx, tiles_by_key[k].x_idx, tiles_by_key[k].y_idx), reverse=True)
        k = exposed[0]
        order.append(k)
        remaining.discard(k)
    if len(order) != n:
        return level_json, False, "peel 순서 불완전"

    assign = _witness_assign(order, use_tile_count, max_open)
    if assign is None:
        return level_json, False, "witness 타입배정 실패"

    eff_open = min(max_open, use_tile_count, 3)
    total = sum(1 for layer in state.tiles.values() for _ in layer.values())

    def _build(keep_attrs: Optional[Set[str]]) -> Dict[str, Any]:
        """assign된 타입으로 level_json 구성. keep_attrs=None이면 속성 전부 유지,
        집합이면 base가 그 집합에 든 속성만 유지(나머지는 제거)."""
        nl = copy.deepcopy(level_json)
        for kk, tile in tiles_by_key.items():
            if kk not in assign:
                continue
            ld = nl.get(f"layer_{tile.layer_idx}")
            pos = f"{tile.x_idx}_{tile.y_idx}"
            if not isinstance(ld, dict) or pos not in ld.get("tiles", {}):
                continue
            cur = ld["tiles"][pos]
            attr = cur[1] if isinstance(cur, list) and len(cur) > 1 else ""
            if keep_attrs is not None and _attr_base(attr) not in keep_attrs:
                attr = ""
            ld["tiles"][pos] = [assign[kk], attr]
        return nl

    def _bot_clears(nl: Dict[str, Any]) -> bool:
        """optimal 봇이 한 번이라도 클리어하면 솔버블 확정(기믹 포함 실제 플레이)."""
        try:
            from .bot_simulator import get_profile, BotType
            r = BotSimulator().simulate_with_profile(
                nl, get_profile(BotType.OPTIMAL),
                iterations=3, max_moves=total + 50, seed=12345, early_termination=True,
            )
            return getattr(r, "clear_rate", 0) > 0
        except Exception:  # noqa: BLE001
            return False

    if not verify:
        return _build(None), True, f"적용 (검증생략, max_open={eff_open})"

    # degrade 단계: 기믹 최대 유지 → 실패 시 단계적 제거(솔버블 보장). 각 단계 봇클리어로 확정.
    # 1) 안전 기믹 전부 유지(ice/grass/chain/link)
    nl_full = _build(SAFE_GIMMICKS)
    if _bot_clears(nl_full):
        return nl_full, True, f"적용 (기믹 유지, 봇클리어, max_open={eff_open})"
    # 2) chain/link 제거, ice/grass만 유지 (ice/grass는 순서 불변이라 거의 항상 통과)
    nl_ig = _build({"ice", "grass"})
    if _bot_clears(nl_ig):
        return nl_ig, True, f"적용 (chain/link 제거·ice/grass 유지, max_open={eff_open})"
    # 3) 기믹 전부 제거(plain) — 위트니스 구성상 솔버블. 봇클리어 또는 A*로 확정.
    nl_plain = _build(set())
    if _bot_clears(nl_plain):
        return nl_plain, True, f"적용 (기믹 전부 제거·plain, max_open={eff_open})"
    from .solver import solve_level
    v = solve_level(nl_plain, node_budget=120000, time_budget_s=6.0)
    if v["verdict"] == "PROVEN_SOLVABLE":
        return nl_plain, True, f"적용 (plain, A* SOLVABLE, max_open={eff_open})"
    return level_json, False, f"미적용(plain도 미확인: 봇 미클리어 + A* {v['verdict']})"
