"""[프론트 동일 조건 A/B] 실제 프론트가 쓰는 API·판정 로직으로 유닛조립 v2 검증.

프론트 순차검증과 동일:
  생성   : POST /api/generate  (ProductionDashboard 페이로드)
  측정   : POST /api/rl-sim/level  (simulateLevelSkillSweep) ← 진짜 검증기
  판정   : rlVerificationPassed() 미러
             classification != 'unclearable_suspect'
             AND verification_passed === true
             (튜토리얼 1~10은 gap >= -TOL 한쪽만)
  재생성 : 실패분만, offset 학습(±3) 반영
"""
import sys
import json
import argparse
import statistics
import urllib.request

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")

API = "http://localhost:8000/api"
TUTORIAL_MAX_LEVEL = 10
RL_CLEAR_TOL = 0.12
MAX_ROUNDS = 4


def post(path, payload, timeout=300):
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def boss_scale(ln):
    """프론트 bossTargetScale — 보스는 목표 절반(더 어려워야 통과)."""
    return 0.5 if (ln % 10 == 0 and ln > 0) else 1.0


def v_at_level(ln):
    """타일종류 V — baseline 커브(프론트 TILE_TYPE_PROFILE_CURVES 미러)."""
    curve = [(3, 4), (10, 5), (30, 6), (60, 8), (100, 9), (225, 9),
             (600, 10), (1125, 11), (1500, 12)]
    for cap, v in curve:
        if ln <= cap:
            return v
    return 12


def gen_payload(ln, td, offset, unit, seed):
    cnt = max(4, min(15, v_at_level(ln)))
    ml = max(2, min(10, min(10, 3 + int(td * 7)) + offset // 2))
    psd = abs(seed)
    return {
        "target_difficulty": max(0.05, min(0.95, td)),
        "grid_size": [7, 7],
        "min_layers": 2,
        "max_layers": ml,
        "tile_types": [f"t{i+1}" for i in range(cnt)],
        "obstacle_types": [],
        "goals": [{"type": ["craft", "stack"][psd % 2],
                   "direction": ["s", "n", "e", "w"][psd % 4],
                   "count": max(2, int(3 + td * 2))}],
        "symmetry_mode": ["horizontal", "vertical", "both", "none"][psd % 4],
        "pattern_type": "aesthetic",
        "pattern_index": (psd * 7 + 10) % 60,
        "auto_select_gimmicks": True,
        "available_gimmicks": ["craft", "stack", "chain", "frog", "ice", "grass",
                               "link", "bomb", "curtain", "teleport", "unknown"],
        "gimmick_intensity": min(td, ln / 500),
        "level_number": ln,
        "unit_assembly": unit,
        "use_reverse_generation": False,
        "size_diversity_start_level": 11,
        "skip_deadlock_check": not unit,
    }


def rl_passed(ln, rl):
    """프론트 rlVerificationPassed 미러."""
    if rl.get("classification") == "unclearable_suspect":
        return False
    if ln <= TUTORIAL_MAX_LEVEL:
        return (rl.get("clear_rate_gap") or 0) >= -RL_CLEAR_TOL
    return rl.get("verification_passed") is True


def run(levels, unit, label):
    state = {ln: {"td": td, "offset": 0, "passed": False, "best_gap": 9.9, "pred": None}
             for ln, td in levels}
    for rnd in range(1, MAX_ROUNDS + 1):
        pending = [ln for ln in state if not state[ln]["passed"]]
        if not pending:
            break
        for ln in pending:
            s = state[ln]
            seed = 7700 + ln * 13 + rnd
            try:
                res = post("/generate", gen_payload(ln, s["td"], s["offset"], unit, seed))
                lj = res.get("level_json")
                if not lj:
                    continue
                rl = post("/rl-sim/level", {
                    "level_json": lj,
                    "target_difficulty": s["td"],
                    "seed": rnd,
                    "target_clear_rate_scale": boss_scale(ln),
                })
            except Exception as e:  # noqa: BLE001
                print(f"    Lv{ln} ERR {type(e).__name__}: {str(e)[:50]}")
                continue
            gap = rl.get("clear_rate_gap")
            s["pred"] = rl.get("predicted_clear_rate")
            if gap is not None and abs(gap) < abs(s["best_gap"]):
                s["best_gap"] = gap
            if rl_passed(ln, rl):
                s["passed"] = True
            else:
                if rl.get("classification") == "unclearable_suspect":
                    s["offset"] = max(-3, s["offset"] - 1)
                elif (gap or 0) > 0.12:
                    s["offset"] = min(3, s["offset"] + 1)
                else:
                    s["offset"] = max(-3, s["offset"] - 1)
        done = sum(1 for v in state.values() if v["passed"])
        print(f"  [{label}] 라운드{rnd}: 통과 {done}/{len(levels)}", flush=True)

    passed = sum(1 for v in state.values() if v["passed"])
    zero = sum(1 for v in state.values() if (v["pred"] or 0) <= 0.001)
    gaps = [abs(v["best_gap"]) for v in state.values() if abs(v["best_gap"]) < 9]
    return {"passed": passed, "zero": zero,
            "mean_gap": statistics.mean(gaps) if gaps else 0,
            "fails": sorted(ln for ln, v in state.items() if not v["passed"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=30)
    args = ap.parse_args()
    step = max(1, 1500 // args.count)
    levels = [(ln, round(0.15 + (ln / 1500) * 0.72, 2))
              for ln in range(30, 1500, step)][:args.count]

    print("=" * 70)
    print(f"프론트 동일조건 A/B — {len(levels)}레벨 × {MAX_ROUNDS}라운드 (RL 스킬스윕 판정)")
    print("=" * 70)
    print("\n[OFF] 현행")
    off = run(levels, False, "OFF")
    print("\n[ON] 유닛조립 v2")
    on = run(levels, True, "ON ")

    n = len(levels)
    print("\n" + "=" * 70)
    print(f"{'':16}{'OFF(현행)':>14}{'ON(v2)':>14}")
    print(f"{'통과':16}{off['passed']}/{n:<12}{on['passed']}/{n:<12}")
    print(f"{'통과율':16}{off['passed']/n*100:13.1f}%{on['passed']/n*100:13.1f}%")
    print(f"{'pred=0 잔존':16}{off['zero']:14}{on['zero']:14}")
    print(f"{'평균 |gap|':16}{off['mean_gap']:14.3f}{on['mean_gap']:14.3f}")
    print(f"\nOFF 미통과: {off['fails'][:15]}")
    print(f"ON  미통과: {on['fails'][:15]}")
    d = on["passed"] - off["passed"]
    print(f"\n판정: {'✅' if d >= 0 else '❌'} v2 통과율 현행 대비 {d:+d}개")


if __name__ == "__main__":
    main()
