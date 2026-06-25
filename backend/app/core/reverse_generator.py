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
    """역생성이 처리 못 하는 요소가 있으면 사유, 없으면 None.

    [v3-3단계] 모든 속성 기믹 + 컨테이너(craft/stack) + key 타일까지 허용.
    위트니스는 plain 타입만 배정하고, _normalize_goal_unlock(goalCount/unlockTile 정정) +
    봇클리어 검증 + degrade(컨테이너/key 제거 폴백)로 솔버블을 보장한다. 현재 막는 요소는 없다.
    """
    return None


def _witness_assign(
    order: List[str],
    use_tile_count: int,
    max_open: int,
    held_target: Optional[int] = None,
) -> Optional[Dict[str, str]]:
    """peel 순서를 따라 타입 배정. 각 그룹=정확히 3개(÷3 자동), 동시 미완성 그룹은 서로 다른 타입,
    held(=미완성 타일 수) ≤ 7 유지. 성공 시 {full_key: 'tN'}, 실패 시 None.

    [v2 난이도 압박] held_target 지정 시 '압박 모드': held(독 점유)를 held_target까지 끌어올려
    유지(마감 지연) → 독이 빡빡 → 캐주얼 실수 시 오버플로 → 어렵지만 솔버블(불변식 held≤7 유지).
    None이면 v1 동작(압박 최소화, max_open≤3 캡) 그대로 — 하위호환.
    실측(2026-06-23): held 2→100% / 5→87% / 6→45% / 7+종류7→34% 클리어. 천장 ~34%(역생성 한계)."""
    pressure = held_target is not None
    hard_cap = 6 if pressure else 3  # 압박 모드는 동시그룹 상한을 6으로(held 7 도달 가능)
    max_open = max(1, min(max_open if not pressure else hard_cap, use_tile_count, hard_cap))
    open_groups: List[Dict[str, Any]] = []  # {type, count}
    used_types: Set[str] = set()
    assign: Dict[str, str] = {}
    n = len(order)
    # [fix 2026-06-25] 색상 round-robin 커서. 기존 fresh_type은 항상 최저 미사용 인덱스를 골라
    # 닫힌 색을 즉시 재사용 → 동시그룹 수(max_open)만큼의 색만 쓰였다(max_open=2면 2색 붕괴).
    # 커서로 1~use_tile_count를 순회하면 그룹마다 새 색이 배정돼 원래 종류수(use_tile_count)가 유지된다.
    # 솔버블 불변: 동시 열린 그룹끼리만 다른 색이면 되므로(open_types 회피) 안전.
    cursor = [0]

    def fresh_type() -> Optional[str]:
        open_types = {g["type"] for g in open_groups}
        for _ in range(use_tile_count):
            cursor[0] = (cursor[0] % use_tile_count) + 1
            t = f"t{cursor[0]}"
            if t not in open_types:
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

        if pressure:
            # 압박 모드: held가 목표 미만이고 안전하면 새 그룹 열어 독 점유↑ (마감 지연 → 난이도↑)
            open_new = (not open_groups) or (can_open and not must_close and held < held_target)
        else:
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


def _normalize_goal_unlock(nl: Dict[str, Any]) -> None:
    """레벨의 클리어 조건(goalCount/unlockTile)을 실제 타일과 일치시킨다.

    역생성(특히 컨테이너 제거/속성 strip) 후, 존재하지 않는 craft 골이나 key 없는 unlockTile이
    남으면 보드를 다 비워도 클리어 판정이 안 된다(미충족 목표). 실제 타일 기준으로 정정:
    - craft/stack 타일 없음 → goalCount 제거(클리어 = 보드 비우기)
    - key 타일 수에 맞춰 unlockTile = key수 // 3
    """
    has_container = False
    key_count = 0
    for i in range(int(nl.get("layer", 0) or 0)):
        ld = nl.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if not (isinstance(td, list) and td and isinstance(td[0], str)):
                continue
            tt = td[0]
            if tt.startswith("craft_") or tt.startswith("stack_"):
                has_container = True
            elif tt == "key":
                key_count += 1
    if not has_container:
        nl.pop("goalCount", None)
    if nl.get("unlockTile") and key_count // 3 != nl.get("unlockTile"):
        nl["unlockTile"] = key_count // 3


def _has_containers(level_json: Dict[str, Any]) -> bool:
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if isinstance(td, list) and td and isinstance(td[0], str) and (td[0].startswith("craft_") or td[0].startswith("stack_")):
                return True
    return False


def _has_special(level_json: Dict[str, Any]) -> bool:
    """컨테이너(craft/stack) 또는 key 타일이 있으면 True (제거 폴백 대상)."""
    for i in range(int(level_json.get("layer", 0) or 0)):
        ld = level_json.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for td in ld["tiles"].values():
            if isinstance(td, list) and td and isinstance(td[0], str):
                if td[0].startswith("craft_") or td[0].startswith("stack_") or td[0] == "key":
                    return True
    return False


def _strip_special(level_json: Dict[str, Any]) -> Dict[str, Any]:
    """컨테이너(craft/stack)·key 타일을 삭제하고 goalCount/unlockTile 제거 + ÷3 재보정한 새
    level_json. 특수 타일+witness 조합이 안 풀릴 때의 최후 degrade — 특수 타일을 포기하고
    plain 솔버블을 보장한다."""
    nl = copy.deepcopy(level_json)
    nl.pop("goalCount", None)
    nl["unlockTile"] = 0
    for i in range(int(nl.get("layer", 0) or 0)):
        ld = nl.get(f"layer_{i}")
        if not isinstance(ld, dict) or not isinstance(ld.get("tiles"), dict):
            continue
        for pos in [p for p, td in ld["tiles"].items()
                    if isinstance(td, list) and td and isinstance(td[0], str)
                    and (td[0].startswith("craft_") or td[0].startswith("stack_") or td[0] == "key")]:
            del ld["tiles"][pos]
    # ÷3 재보정 (특수타일 삭제로 깨진 매칭타입 총합을 generator 로직으로 정정)
    try:
        from .generator import LevelGenerator
        nl = LevelGenerator()._finalize_divisibility_guarantee(nl)
    except Exception:  # noqa: BLE001
        pass
    return nl


def apply_reverse_generation(
    level_json: Dict[str, Any],
    use_tile_count: int,
    max_open: int = 2,
    verify: bool = True,
    held_target: Optional[int] = None,
) -> Tuple[Dict[str, Any], bool, str]:
    """
    레벨의 plain 타일 타입을 witness peeling으로 재배정해 솔버블·÷3 보장.

    Returns: (level_json, applied, reason)
    1차: 컨테이너/key/기믹 유지한 채 시도. 실패 시 특수타일(컨테이너·key) 제거 후 재시도.
    held_target: 지정 시 압박 모드(독 점유를 그만큼 유지 → 난이도↑). None이면 v1(쉬움) 동작.
    """
    new_level, applied, reason = _attempt_reverse(level_json, use_tile_count, max_open, verify, held_target)
    if applied:
        return new_level, True, reason
    # 컨테이너/key가 있으면 제거하고 재시도(plain 솔버블 보장). 특수타일은 포기.
    if _has_special(level_json):
        stripped = _strip_special(level_json)
        nl2, applied2, reason2 = _attempt_reverse(stripped, use_tile_count, max_open, verify, held_target)
        if applied2:
            return nl2, True, f"적용 (특수타일 제거 후 {reason2})"
    return level_json, False, reason


def _attempt_reverse(
    level_json: Dict[str, Any],
    use_tile_count: int,
    max_open: int = 2,
    verify: bool = True,
    held_target: Optional[int] = None,
) -> Tuple[Dict[str, Any], bool, str]:
    """witness 1회 시도(컨테이너 제거 폴백 없음). apply_reverse_generation이 호출."""
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

    # plain t1~t15만 위트니스 대상. 컨테이너(craft/stack) 및 그 내부에서 나온 타일은 제외
    # (내부 타입은 런타임 t0 분배가 결정 — 위트니스가 건드리면 안 됨). 컨테이너 내부의 ÷3은
    # generator의 _finalize_divisibility_guarantee가 concrete/t0 분리 보장으로 이미 처리.
    matchable = [
        k for k, t in tiles_by_key.items()
        if isinstance(t.tile_type, str) and t.tile_type.startswith("t")
        and t.tile_type[1:].isdigit() and t.tile_type != "t0"
        and not getattr(t, "is_stack_tile", False) and not getattr(t, "is_craft_tile", False)
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

    assign = _witness_assign(order, use_tile_count, max_open, held_target)
    if assign is None:
        return level_json, False, "witness 타입배정 실패"

    eff_open = min(max_open, use_tile_count, 6 if held_target is not None else 3)
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
        _normalize_goal_unlock(nl)
        return nl

    def _bot_clears(nl: Dict[str, Any]) -> bool:
        """optimal 봇이 한 번이라도 클리어하면 솔버블 확정(기믹 포함 실제 플레이).

        frog/teleport/bomb/curtain 등 비결정 기믹은 고정시드로도 매 iteration 결과가 달라
        3회로는 솔버블인데도 우연히 0% 클리어가 나올 수 있다(false negative). iteration을 충분히
        늘려(15) 솔버블이면 ≥1회 클리어가 거의 항상 잡히게 한다. early_termination으로 명백히
        잘 풀리는 레벨은 조기 종료(속도 유지)."""
        try:
            from .bot_simulator import get_profile, BotType
            r = BotSimulator().simulate_with_profile(
                nl, get_profile(BotType.OPTIMAL),
                iterations=15, max_moves=total + 50, seed=12345, early_termination=True,
            )
            return getattr(r, "clear_rate", 0) > 0
        except Exception:  # noqa: BLE001
            return False

    if not verify:
        return _build(None), True, f"적용 (검증생략, max_open={eff_open})"

    # degrade 단계: 기믹 최대 유지 → 실패 시 위험요소 단계적 제거(솔버블 보장). 각 단계 봇클리어 확정.
    #  0) 모든 속성 기믹 유지(frog/teleport/bomb/curtain/unknown 포함)
    #  1) 비결정 기믹 제거, 결정적 기믹(ice/grass/chain/link)만 유지
    #  2) chain/link 제거, ice/grass만 유지
    #  3) 전부 제거(plain) — 위트니스 구성상 솔버블, A*로 확정
    stages = [
        (None,                          "모든 기믹 유지"),
        (SAFE_GIMMICKS,                 "비결정 기믹 제거(결정적 기믹 유지)"),
        ({"ice", "grass"},              "chain/link 제거(ice/grass 유지)"),
    ]
    for keep, label in stages:
        nl = _build(keep)
        if _bot_clears(nl):
            return nl, True, f"적용 ({label}, 봇클리어, max_open={eff_open})"
    # plain(기믹 전부 제거)
    nl_plain = _build(set())
    # 특수타일(컨테이너·key)이 없으면 plain witness는 구성상 솔버블이 증명된다(커버 DAG peel +
    # 독≤7). 봇 휴리스틱이 못 찾거나 A*가 예산초과해도 해는 존재하므로 검증 없이 채택.
    if not _has_special(nl_plain):
        return nl_plain, True, f"적용 (plain·구성보장, max_open={eff_open})"
    # 컨테이너가 남아있으면 구성보장 불가 → 봇클리어/A*로 확정 시도(여기 실패 시 상위 래퍼가
    # 컨테이너 제거 후 재시도 → 그땐 plain·구성보장으로 반드시 통과).
    if _bot_clears(nl_plain):
        return nl_plain, True, f"적용 (plain+컨테이너, 봇클리어, max_open={eff_open})"
    from .solver import solve_level
    v = solve_level(nl_plain, node_budget=120000, time_budget_s=6.0)
    if v["verdict"] == "PROVEN_SOLVABLE":
        return nl_plain, True, f"적용 (plain+컨테이너, A* SOLVABLE, max_open={eff_open})"
    return level_json, False, f"미적용(컨테이너 plain 미확인: A* {v['verdict']})"
