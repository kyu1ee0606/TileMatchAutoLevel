"""[타운팝 템플릿 분석] 10×10 레벨 템플릿을 인게임 규격으로 편입 가능한지 Tier 분류.

PLAN_townpop_template_crop.md §6-1.
  Tier A : 공통 여백만 잘라도 목표 최대변 도달 (무손실)
  Tier B : 강제 크롭 필요하나 손실 작고 실루엣 유지(IoU 높음)
  Tier C : 손실 크거나 실루엣 뭉개짐 → 커스텀 패턴 추출 대상

홀짝 규칙: 좌우/상하 잘라내는 양을 **전 층 동일**하게 적용(짝수층 S / 홀수층 S-1 유지).
"""
import sys
import json
import copy
import argparse
import statistics
from collections import Counter

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")

TPL = "/Users/casualdev/TileMatchAutoLevel/backend/data/level_templates.json"


def layers_of(lj):
    out = []
    for i in range(int(lj.get("layer", 0) or 0)):
        L = lj.get(f"layer_{i}")
        if not isinstance(L, dict):
            continue
        t = L.get("tiles") or {}
        if not t:
            continue
        try:
            out.append((i, int(L.get("col")), int(L.get("row")), t))
        except (TypeError, ValueError):
            continue
    return out


def common_margins(lj):
    """전 층 공통 여백(좌,우,상,하). 무손실 크롭 가능량."""
    ls = layers_of(lj)
    if not ls:
        return None
    lm = rm = tm = bm = 10 ** 9
    for _, c, r, t in ls:
        xs = [int(p.split("_")[0]) for p in t]
        ys = [int(p.split("_")[1]) for p in t]
        lm = min(lm, min(xs))
        rm = min(rm, c - 1 - max(xs))
        tm = min(tm, min(ys))
        bm = min(bm, r - 1 - max(ys))
    return lm, rm, tm, bm


def base_dim(lj):
    ls = layers_of(lj)
    return max((c for _, c, _, _ in ls), default=0)


def apply_crop(lj, lcut, rcut, tcut, bcut):
    """전 층 동일량 크롭. 밖으로 나간 타일은 삭제(손실). 반환 (신레벨, 손실수)."""
    new = copy.deepcopy(lj)
    lost = 0
    for i in range(int(new.get("layer", 0) or 0)):
        L = new.get(f"layer_{i}")
        if not isinstance(L, dict):
            continue
        t = L.get("tiles") or {}
        try:
            c, r = int(L.get("col")), int(L.get("row"))
        except (TypeError, ValueError):
            continue
        nc, nr = c - lcut - rcut, r - tcut - bcut
        nt = {}
        for p, v in t.items():
            x, y = map(int, p.split("_"))
            nx, ny = x - lcut, y - tcut
            if 0 <= nx < nc and 0 <= ny < nr:
                nt[f"{nx}_{ny}"] = v
            else:
                lost += 1
        was_str = isinstance(L.get("col"), str)
        L["col"] = str(nc) if was_str else nc
        L["row"] = str(nr) if was_str else nr
        L["tiles"] = nt
        L["num"] = str(len(nt))
    return new, lost


def iou_per_layer(orig, crop, lcut, tcut):
    """층별 실루엣 IoU(원본 좌표계로 되돌려 비교). 평균 반환."""
    vals = []
    om = {i: set(t.keys()) for i, _, _, t in layers_of(orig)}
    cm = {i: {f"{int(p.split('_')[0])+lcut}_{int(p.split('_')[1])+tcut}" for p in t}
          for i, _, _, t in layers_of(crop)}
    for i, o in om.items():
        c = cm.get(i, set())
        if not o and not c:
            continue
        inter = len(o & c)
        union = len(o | c)
        vals.append(inter / union if union else 0.0)
    return statistics.mean(vals) if vals else 0.0


def classify(lj, target, iou_gate):
    ls = layers_of(lj)
    if not ls:
        return "SKIP", {}
    base = base_dim(lj)
    total = sum(len(t) for _, _, _, t in ls)
    if base <= target:
        return "A", {"base": base, "final": base, "lost": 0, "loss_pct": 0.0, "iou": 1.0, "note": "이미 규격"}

    m = common_margins(lj)
    lm, rm, tm, bm = m
    # ── Tier A: 공통 여백만으로 도달? (좌우 여백 합 >= 필요량, 상하도 동일)
    need = base - target
    if lm + rm >= need and tm + bm >= need:
        lcut = min(lm, need // 2 + need % 2)
        rcut = need - lcut
        if rcut > rm:
            rcut = rm
            lcut = need - rcut
        tcut = min(tm, need // 2 + need % 2)
        bcut = need - tcut
        if bcut > bm:
            bcut = bm
            tcut = need - bcut
        new, lost = apply_crop(lj, lcut, rcut, tcut, bcut)
        if lost == 0:
            return "A", {"base": base, "final": base - lcut - rcut, "lost": 0,
                         "loss_pct": 0.0, "iou": 1.0, "cut": (lcut, rcut, tcut, bcut)}

    # ── Tier B/C: 강제 균일 크롭
    lcut = need // 2
    rcut = need - lcut
    tcut = need // 2
    bcut = need - tcut
    new, lost = apply_crop(lj, lcut, rcut, tcut, bcut)
    pct = lost / total * 100 if total else 100.0
    iou = iou_per_layer(lj, new, lcut, tcut)
    tier = "B" if (pct < 15 and iou >= iou_gate) else "C"
    return tier, {"base": base, "final": target, "lost": lost, "loss_pct": pct,
                  "iou": iou, "cut": (lcut, rcut, tcut, bcut)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=8, help="목표 최대변")
    ap.add_argument("--iou", type=float, default=0.85, help="Tier B 실루엣 IoU 임계")
    args = ap.parse_args()

    d = json.load(open(TPL))
    tpls = d.get("templates") or d
    rows = []
    for k, v in tpls.items():
        if not isinstance(v, dict):
            continue
        lj = v.get("level_json") or {}
        tier, info = classify(lj, args.target, args.iou)
        if tier == "SKIP":
            continue
        rows.append((k, tier, info))

    cnt = Counter(t for _, t, _ in rows)
    print("=" * 78)
    print(f"타운팝 템플릿 Tier 분류 — 목표 최대변 {args.target}, IoU 임계 {args.iou}")
    print("=" * 78)
    print(f"총 {len(rows)}개 → A(무손실) {cnt['A']} · B(경미손실) {cnt['B']} · C(부적합) {cnt['C']}")
    print(f"   편입 가능(A+B) = {cnt['A']+cnt['B']} ({(cnt['A']+cnt['B'])/len(rows)*100:.0f}%)")

    for tier in ("A", "B", "C"):
        sub = [(k, i) for k, t, i in rows if t == tier]
        if not sub:
            continue
        losses = [i["loss_pct"] for _, i in sub]
        ious = [i["iou"] for _, i in sub]
        print(f"\n[{tier}] {len(sub)}개  손실 평균{statistics.mean(losses):.1f}%/중앙{statistics.median(losses):.1f}%  "
              f"IoU 평균{statistics.mean(ious):.2f}")
        for k, i in sub[:5]:
            print(f"    {k[-18:]:20} {i['base']}→{i['final']} 손실{i['lost']:3}({i['loss_pct']:4.1f}%) IoU{i['iou']:.2f}")

    # 원본 크기 분포
    print("\n원본 최대변 분포:", dict(Counter(i["base"] for _, _, i in rows)))

    out = "/tmp/townpop_tiers.json"
    json.dump({k: {"tier": t, **{kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in i.items()}}
               for k, t, i in rows}, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"\n상세 저장: {out}")


if __name__ == "__main__":
    main()
