"""수동 제작된 보스 템플릿 38개의 제작 규칙 추출.

목적: 390~1500 구간 112개를 자동 생성할 때 기존과 톤이 맞도록,
사람이 실제로 지킨 규칙을 데이터에서 뽑아낸다(추측 금지).

핵심 제작 의도(작성자 설명): **모든 층을 합쳐 봤을 때** 인게임에서 컨셉 모양이
연상되게 만든다. 층 하나하나가 모양인 게 아니라 적층 실루엣이 모양이다.
따라서 '층 간 관계'가 가장 중요한 규칙이다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def xy(p):
    a, b = p.split("_")
    return int(a), int(b)


def bbox(ps):
    if not ps:
        return None
    xs = [xy(p)[0] for p in ps]
    ys = [xy(p)[1] for p in ps]
    return min(xs), max(xs), min(ys), max(ys)


def sym_score(ps, size):
    """좌우 대칭도 — 미러 셀이 존재하는 비율."""
    if not ps:
        return 0.0
    S = set(ps)
    hit = sum(1 for p in S if f"{size - 1 - xy(p)[0]}_{xy(p)[1]}" in S)
    return hit / len(S)


def upper_support(lower, upper, lower_size, upper_size):
    """위층 셀이 아래층에 '받쳐지는' 비율.

    게임 층간 매핑(DB_Level.cs:748/760/781): 홀짝이 다르면 위층이 작을 때
    아래(x,y) 위에 위층 (x-1,y-1)/(x,y-1)/(x-1,y)/(x,y) 가 얹힌다.
    반대로 위층 셀 하나는 아래층 (x,y)/(x+1,y)/(x,y+1)/(x+1,y+1) 에 받쳐진다.
    """
    if not upper:
        return None
    L = set(lower)
    same_parity = (lower_size == upper_size)
    ok = 0
    for p in upper:
        x, y = xy(p)
        cand = [(x, y)] if same_parity else [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]
        if any(f"{a}_{b}" in L for a, b in cand):
            ok += 1
    return ok / len(upper)


def main():
    T = json.load(open("data/boss_templates.json"))
    rows = []
    for tid, t in sorted(T.items(), key=lambda kv: int(kv[1].get("level_min", 0))):
        ls = sorted(t.get("layers", []), key=lambda l: l.get("layer", 0))
        lv = int(t.get("level_min", 0))
        cells = [len(l.get("positions", [])) for l in ls]
        sizes = [int(l.get("row", 0)) for l in ls]
        gim = Counter()
        for l in ls:
            for g in (l.get("gimmicks") or {}).values():
                gim[str(g).split("_")[0]] += 1
        rows.append(dict(id=tid, lv=lv, ls=ls, cells=cells, sizes=sizes, gim=gim,
                         total=sum(cells), n=len(ls)))

    print(f"=== 보스 템플릿 {len(rows)}개 (Lv{rows[0]['lv']}~{rows[-1]['lv']}) ===\n")

    # 1) 층 수
    print("[1] 층 수 분포")
    print("   ", dict(sorted(Counter(r["n"] for r in rows).items())))
    print(f"    레벨 진행에 따른 층수: {[(r['lv'], r['n']) for r in rows[:6]]} … {[(r['lv'], r['n']) for r in rows[-4:]]}")
    print()

    # 2) 격자 크기
    print("[2] 층 격자 크기 (base = 짝수층)")
    print("   ", dict(sorted(Counter(tuple(r["sizes"]) for r in rows).items(), key=lambda x: -x[1])))
    print()

    # 3) 총 셀 수 ↔ 레벨
    print("[3] 총 셀 수 (모든 층 합)")
    tot = [r["total"] for r in rows]
    print(f"    최소 {min(tot)} / 최대 {max(tot)} / 평균 {sum(tot)/len(tot):.1f}")
    print(f"    ÷3 인 템플릿: {sum(1 for x in tot if x % 3 == 0)}/{len(tot)}")
    q = len(rows) // 4
    for name, seg in (("초반", rows[:q]), ("중반", rows[q:3*q]), ("후반", rows[3*q:])):
        s = [r["total"] for r in seg]
        print(f"    {name} Lv{seg[0]['lv']}~{seg[-1]['lv']}: 평균 {sum(s)/len(s):.0f} (범위 {min(s)}~{max(s)})")
    print()

    # 4) 층별 셀 수 패턴 — 아래가 넓고 위로 갈수록 좁아지나
    print("[4] 층별 셀 수 / 층 면적 대비 채움률")
    shrink = 0
    for r in rows:
        c = r["cells"]
        if all(c[i] >= c[i + 1] for i in range(len(c) - 1)):
            shrink += 1
    print(f"    단조 감소(아래▶위 좁아짐): {shrink}/{len(rows)}")
    fills = []
    for r in rows:
        for c, s in zip(r["cells"], r["sizes"]):
            if s:
                fills.append(c / (s * s))
    print(f"    층 채움률 평균 {sum(fills)/len(fills):.0%} (최소 {min(fills):.0%} / 최대 {max(fills):.0%})")
    for i in range(6):
        v = [r["cells"][i] / (r["sizes"][i] ** 2) for r in rows if len(r["cells"]) > i and r["sizes"][i]]
        if v:
            print(f"      L{i}: 평균 {sum(v)/len(v):.0%}  (n={len(v)})")
    print()

    # 5) 층간 받침 — 위층이 아래층에 얹혀 있는가
    print("[5] 층간 받침률 (위층 셀이 아래층에 받쳐지는 비율)")
    sup = []
    for r in rows:
        for i in range(len(r["ls"]) - 1):
            lo, up = r["ls"][i], r["ls"][i + 1]
            v = upper_support(lo.get("positions", []), up.get("positions", []),
                              int(lo.get("row", 0)), int(up.get("row", 0)))
            if v is not None:
                sup.append(v)
    if sup:
        full = sum(1 for v in sup if v >= 0.999)
        print(f"    평균 {sum(sup)/len(sup):.1%} · 100% 받침 {full}/{len(sup)}쌍 "
              f"· 90%↑ {sum(1 for v in sup if v >= 0.9)}/{len(sup)}")
    print()

    # 6) 좌우 대칭
    print("[6] 좌우 대칭도")
    sy = []
    for r in rows:
        for l in r["ls"]:
            v = sym_score(l.get("positions", []), int(l.get("row", 0)))
            sy.append(v)
    print(f"    층 단위 평균 {sum(sy)/len(sy):.1%} · 완전대칭 층 {sum(1 for v in sy if v >= 0.999)}/{len(sy)}")
    per_t = []
    for r in rows:
        v = [sym_score(l.get("positions", []), int(l.get("row", 0))) for l in r["ls"]]
        per_t.append(sum(v) / len(v))
    print(f"    템플릿 단위: 대칭 90%↑ {sum(1 for v in per_t if v >= 0.9)}/{len(per_t)}")
    print()

    # 7) bbox — 실제 쓰는 영역
    print("[7] 실사용 bbox (층별)")
    used = []
    for r in rows:
        for l, s in zip(r["ls"], r["sizes"]):
            b = bbox(l.get("positions", []))
            if b and s:
                used.append(((b[1] - b[0] + 1) / s, (b[3] - b[2] + 1) / s))
    print(f"    폭/격자 평균 {sum(u[0] for u in used)/len(used):.0%} · 높이/격자 평균 {sum(u[1] for u in used)/len(used):.0%}")
    print(f"    격자 꽉 채움(폭 100%) 층: {sum(1 for u in used if u[0] >= 0.999)}/{len(used)}")
    print()

    # 8) 기믹
    print("[8] 수동 지정 기믹")
    allg = Counter()
    for r in rows:
        allg.update(r["gim"])
    print("   ", dict(allg) or "없음")
    print(f"    기믹 쓴 템플릿: {sum(1 for r in rows if r['gim'])}/{len(rows)}")
    print()

    # 9) 개별 표
    print("[9] 개별 템플릿")
    print(f"    {'Lv':>5} {'층':>2} {'격자':<14} {'층별셀':<20} {'합':>4} {'÷3':>3} {'대칭':>5} 기믹")
    for r in rows:
        b = bbox(r["ls"][0].get("positions", []))
        symv = sum(sym_score(l.get("positions", []), int(l.get("row", 0))) for l in r["ls"]) / r["n"]
        print(f"    {r['lv']:>5} {r['n']:>2} {'·'.join(map(str, r['sizes'])):<14} "
              f"{'·'.join(map(str, r['cells'])):<20} {r['total']:>4} "
              f"{'O' if r['total'] % 3 == 0 else 'X':>3} {symv:>5.0%} "
              f"{dict(r['gim']) if r['gim'] else ''}")


if __name__ == "__main__":
    main()
