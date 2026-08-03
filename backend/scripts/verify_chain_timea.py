"""[검증] chain 클로저 + timea 티어 정상작동 확인.

1) 유닛: 고립 사슬 / 앵커1 정상 / null 앵커(Lv149형) / ice 앵커(Lv190형) / run2 커버리지
2) 통합: 사슬 튜토리얼(Lv81) + 타임어택 튜토리얼(Lv341) 실제 생성
"""
import sys
sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.generator import (
    LevelGenerator, TIMEA_BASE_MILLI, TIMEA_TIER_MILLI, TIMEA_MIN_SEC, TIME_ATTACK_UNLOCK_LEVEL,
)
from app.models.level import GenerationParams
from app.core.solver import _clearability_type_counts

g = LevelGenerator()
OK = "✅"
NG = "❌"
fails = []


def chains_of(lj, li=0):
    t = (lj.get(f"layer_{li}") or {}).get("tiles") or {}
    return {p for p, d in t.items() if isinstance(d, list) and len(d) > 1 and d[1] == "chain"}


def mk(tiles, col=7, row=7, layers=1, extra=None):
    lv = {"layer": layers, f"layer_0": {"col": str(col), "row": str(row),
          "num": str(len(tiles)), "tiles": tiles}}
    if extra:
        lv.update(extra)
    return lv


print("=" * 62)
print("1) chain 클로저 유닛 테스트")
print("=" * 62)

# T1: 고립 사슬(좌우 빈칸) → 제거되어야 함  [실측 위반 10건이 전부 이 형태]
lv = mk({"3_3": ["t1", "chain"], "3_1": ["t1", ""], "3_5": ["t2", ""]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T1 고립 사슬 제거      : {OK if not r else NG}  남은사슬={sorted(r)}")
if r:
    fails.append("T1")

# T2: 앵커 1개면 정상 → 보존 (과잉제한 금지)
lv = mk({"3_3": ["t1", "chain"], "4_3": ["t2", ""]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T2 앵커1 보존          : {OK if r == {'3_3'} else NG}  남은사슬={sorted(r)}")
if r != {"3_3"}:
    fails.append("T2")

# T3: null 속성 앵커(Lv149형) → 보존.  td[1]=="" 리터럴이면 오탐 발생하는 케이스
lv = mk({"3_2": ["t3", None], "4_2": ["t3", "chain"], "5_2": ["t3", None]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T3 null 앵커 보존      : {OK if r == {'4_2'} else NG}  남은사슬={sorted(r)}")
if r != {"4_2"}:
    fails.append("T3")

# T4: ice 앵커(Lv190형) → 보존. ice/grass 등은 결국 픽 가능 = 유효 앵커
lv = mk({"3_2": ["t4", "ice"], "4_2": ["t10", "chain"], "5_2": ["t10", "ice"]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T4 ice 앵커 보존       : {OK if r == {'4_2'} else NG}  남은사슬={sorted(r)}")
if r != {"4_2"}:
    fails.append("T4")

# T5: 사슬 3연속 + 양끝 빈칸 → 전부 제거 (사용자 보고 Lv81형)
lv = mk({"3_2": ["t12", "chain"], "4_2": ["t12", "chain"], "5_2": ["t13", "chain"]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T5 3연속 앵커없음 제거 : {OK if not r else NG}  남은사슬={sorted(r)}")
if r:
    fails.append("T5")

# T6: 사슬 3연속 + 오른쪽 앵커 1개 → 전부 보존(연쇄 해방)
lv = mk({"3_2": ["t12", "chain"], "4_2": ["t12", "chain"], "5_2": ["t13", "chain"],
         "6_2": ["t1", ""]})
g._chain_release_closure(lv)
r = chains_of(lv)
exp = {"3_2", "4_2", "5_2"}
print(f"T6 3연속+앵커1 보존    : {OK if r == exp else NG}  남은사슬={sorted(r)}")
if r != exp:
    fails.append("T6")

# T7: craft 루트는 앵커 아님 → 제거
lv = mk({"3_2": ["t1", "chain"], "4_2": ["craft_s", "", [3, "t1_t1_t1"]]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T7 craft루트 앵커아님  : {OK if not r else NG}  남은사슬={sorted(r)}")
if r:
    fails.append("T7")

# T8: stack 루트는 앵커 → 보존
lv = mk({"3_2": ["t1", "chain"], "4_2": ["stack_s", "", [3, "t1_t1_t1"]]})
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T8 stack루트 앵커 보존 : {OK if r == {'3_2'} else NG}  남은사슬={sorted(r)}")
if r != {"3_2"}:
    fails.append("T8")

# T9: run2 + plain 앵커 + 가려짐 → **보존** (커버리지는 상향 DAG라 결국 해소 = 구조적 불가 아님)
#     실측 Lv190(RL 통과, 앵커 plain)이 이 형태 → 제거하면 정상 사슬 파괴(과잉엄격)
lv = {"layer": 2,
      "layer_0": {"col": "8", "row": "8", "num": "3",
                  "tiles": {"3_2": ["t1", "chain"], "4_2": ["t1", "chain"], "5_2": ["t2", ""]}},
      "layer_1": {"col": "7", "row": "7", "num": "4",
                  "tiles": {"3_2": ["t3", ""], "4_2": ["t3", ""], "2_1": ["t3", ""], "3_1": ["t3", ""]}}}
g._chain_release_closure(lv)
r = chains_of(lv)
exp9 = {"3_2", "4_2"}
print(f"T9 run2+가려짐 보존    : {OK if r == exp9 else NG}  남은사슬={sorted(r)}")
if r != exp9:
    fails.append("T9")

# T10: run1 + 가려짐 → 보존 (게임이 FailReason.Chain으로 명시실패 → 면제)
lv = {"layer": 2,
      "layer_0": {"col": "8", "row": "8", "num": "2",
                  "tiles": {"3_2": ["t1", "chain"], "4_2": ["t2", ""]}},
      "layer_1": {"col": "7", "row": "7", "num": "4",
                  "tiles": {"3_2": ["t3", ""], "2_1": ["t3", ""], "3_1": ["t3", ""], "2_2": ["t3", ""]}}}
g._chain_release_closure(lv)
r = chains_of(lv)
print(f"T10 run1+가려짐 보존   : {OK if r == {'3_2'} else NG}  남은사슬={sorted(r)}")
if r != {"3_2"}:
    fails.append("T10")

# T11: 수리 불변식 — ÷3/타일수/좌표 보존
tiles = {f"{x}_0": ["t1", ""] for x in range(3)}
tiles.update({f"{x}_1": ["t2", ""] for x in range(3)})
tiles["1_3"] = ["t3", "chain"]
tiles["0_3"] = ["t3", ""]
tiles["2_3"] = ["t3", ""]
lv = mk(dict(tiles))
before_types = _clearability_type_counts(lv)
before_moves = g._calculate_max_moves(lv)
before_keys = set((lv["layer_0"]["tiles"]).keys())
g._chain_release_closure(lv)
inv = (_clearability_type_counts(lv) == before_types
       and g._calculate_max_moves(lv) == before_moves
       and set(lv["layer_0"]["tiles"].keys()) == before_keys)
print(f"T11 수리 불변식 보존   : {OK if inv else NG}  (÷3·max_moves·좌표)")
if not inv:
    fails.append("T11")

print()
print("=" * 62)
print("2) timea 공식/티어 유닛 테스트")
print("=" * 62)
for tier in (1, 2, 3):
    for n in (30, 81, 111, 144, 183, 500):
        lv = mk({f"{i}_0": ["t1", ""] for i in range(n)}, col=999, row=999)
        lv["_timea_tier"] = tier
        g._apply_timea(lv)
        t = lv["timea"]
        spt = t / n
        print(f"  tier{tier} tiles={n:4}  timea={t:4}s  s/타일={spt:.3f}")
        if not (TIMEA_MIN_SEC <= t <= 600):
            fails.append(f"timea range t{tier} n{n}")
        if spt < 0.45 and t < 600:
            fails.append(f"timea below floor t{tier} n{n}")

# 정수 산술 확인(부동소수 평가순서 무관)
import math
for n in (25, 50, 100, 200, 300):
    for tier in (1, 2, 3):
        want = max(TIMEA_MIN_SEC, min(600, -(-(n * TIMEA_BASE_MILLI * TIMEA_TIER_MILLI[tier]) // 1_000_000)))
        lv = mk({f"{i}_0": ["t1", ""] for i in range(n)}, col=999, row=999)
        lv["_timea_tier"] = tier
        g._apply_timea(lv)
        if lv["timea"] != want:
            fails.append(f"int-arith n{n} t{tier}")
print(f"  정수산술 일치         : {OK if not [f for f in fails if 'int-arith' in f] else NG}")

print()
print("=" * 62)
print("3) 통합 — 실제 레벨 생성 (사슬 Lv81 / 타임어택 Lv341)")
print("=" * 62)


def scan_chain_violations(lj):
    """수리 후에도 해제불가 사슬 남았나(클로저 재적용해 변화 확인)"""
    import copy
    before = {}
    for i in range(int(lj.get("layer", 0) or 0)):
        before[i] = chains_of(lj, i)
    cp = copy.deepcopy(lj)
    g._chain_release_closure(cp)
    after = {}
    for i in range(int(cp.get("layer", 0) or 0)):
        after[i] = chains_of(cp, i)
    return {i: sorted(before[i] - after.get(i, set())) for i in before if before[i] - after.get(i, set())}


for ln, label in [(81, "사슬 튜토리얼"), (341, "타임어택 튜토리얼"), (350, "타임어택 보스")]:
    try:
        params = GenerationParams(
            target_difficulty=0.35 if ln == 81 else 0.72,
            grid_size=(7, 7),
            level_number=ln,
            pattern_type="aesthetic",
            pattern_index=(ln * 7 + 10) % 60,
            skip_deadlock_check=True,
        )
        res = g.generate(params)
        lj = res.level_json
        nch = sum(len(chains_of(lj, i)) for i in range(int(lj.get("layer", 0) or 0)))
        viol = scan_chain_violations(lj)
        tiles = g._collectable_tile_count(lj)
        timea = lj.get("timea")
        tier = lj.get("_timea_tier")
        spt = (timea / tiles) if timea and tiles else None
        types = _clearability_type_counts(lj)
        bad3 = {t: c for t, c in types.items() if c % 3}
        print(f"\nLv{ln} ({label})")
        print(f"  사슬 수={nch}  해제불가 잔여={viol if viol else 'NONE ' + OK}")
        print(f"  타일={tiles}  max_moves={lj.get('max_moves')}  timea={timea}  tier={tier}"
              + (f"  s/타일={spt:.3f}" if spt else ""))
        print(f"  ÷3 위반={bad3 if bad3 else 'NONE ' + OK}")
        if viol:
            fails.append(f"Lv{ln} chain residual")
        if bad3:
            fails.append(f"Lv{ln} div3")
        if ln in (341, 350):
            if not timea:
                print(f"  {NG} timea 미적용!")
                fails.append(f"Lv{ln} timea missing")
            elif spt and spt < 0.45:
                print(f"  {NG} 물리 하한 위반")
                fails.append(f"Lv{ln} timea floor")
        if ln == 341 and tier != 1:
            print(f"  {NG} 튜토리얼 티어가 1이 아님: {tier}")
            fails.append("Lv341 tier")
    except Exception as e:
        import traceback
        print(f"\nLv{ln} ERROR: {type(e).__name__}: {e}")
        traceback.print_exc()
        fails.append(f"Lv{ln} exception")

print()
print("=" * 62)
print(f"결과: {OK + ' 전부 통과' if not fails else NG + ' 실패: ' + str(sorted(set(fails)))}")
print("=" * 62)
