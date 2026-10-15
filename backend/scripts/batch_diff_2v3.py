"""[읽기 전용] 에디터 LIVE 배치 2차(2026.9.15) vs 3차(2026.9.17) 전체 비교 + 라이브 빌드 샤드(b741f6a3) 대조 (10 §9-11).

원본 배치 파일은 읽기만 한다. 출력: pv_sandbox/pv_20261002_live3/batch_diff_2v3/{diff.json, table.md}.
비교 항목: meta 전 키, level_json 비레이어 키, 레이어 구조(위치·효과·컨테이너 모양), 타일 타입 배정, 컨테이너 내용,
타일 종류 수·총 타일 수(num 의미: 보드 − 컨테이너 + 내용), t0 칸 수. 샤드는 af_calibration prep.json(L32~500, 1.1.0 샤드
b741f6a3 맵+행 일부 필드)로 대조한다. AF 첫시도 무도움 클리어율은 level_metrics.json.
Usage: .venv/bin/python scripts/batch_diff_2v3.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
from app.core.pv.canonical import canonical_map, struct_hash  # noqa: E402

PROD = os.path.join(BACKEND, "data", "production")
B2 = os.path.join(PROD, "batch_1789435856664_o0klei461.json")
B3 = os.path.join(PROD, "batch_1789636723287_uulknmtej.json")
SB = os.path.join(BACKEND, "data", "pv_sandbox")
OUT = os.path.join(SB, "pv_20261002_live3", "batch_diff_2v3")
SHARD = os.path.join(SB, "af_calibration", "bot_compare_L32_500", "prep.json")
METRICS = os.path.join(SB, "af_calibration", "level_metrics.json")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def layers(m):
    return {k: v for k, v in m.items() if k.startswith("layer_") and isinstance(v, dict)}


def summary(m):
    """kinds, totals, t0, effects, containers of a map (level_json or shard map)."""
    kinds, eff, cont = Counter(), Counter(), []
    board = total = t0 = 0
    for ln, v in sorted(layers(m).items()):
        tiles = v.get("tiles") or {}
        if not isinstance(tiles, dict):
            continue
        for pos, t in sorted(tiles.items()):
            tid = str(t[0])
            board += 1
            e = str(t[1]) if len(t) > 1 and t[1] else ""
            if e:
                eff[e] += 1
            if tid.startswith(("stack", "craft")):
                inner = t[2] if len(t) > 2 else None
                cnt = int(inner[0]) if inner else 0
                total += cnt
                cont.append((ln, pos, tid, json.dumps(inner)))
                if inner and len(inner) > 1:
                    for z in str(inner[1]).split("_"):
                        if z:
                            kinds[z] += 1
            else:
                total += 1
                if tid == "t0":
                    t0 += 1
                elif tid.startswith("t"):
                    kinds[tid] += 1
    return {"kinds": len(kinds), "typeCounts": dict(sorted(kinds.items())), "board": board, "total": total, "t0": t0,
            "effects": dict(sorted(eff.items())), "containers": cont, "layerCount": len(layers(m))}


def type_grid(m):
    return {(ln, pos): str(t[0]) for ln, v in layers(m).items() for pos, t in (v.get("tiles") or {}).items()
            if isinstance(v.get("tiles"), dict)}


def dict_diff(a, b, skip=()):
    out = {}
    for k in sorted(set(a) | set(b)):
        if k in skip or k.startswith("layer_"):
            continue
        if a.get(k) != b.get(k):
            out[k] = [a.get(k, "<없음>"), b.get(k, "<없음>")]
    return out


def compare_maps(m2, m3):
    c2, c3 = canonical_map(m2), canonical_map(m3)
    s2, s3 = summary(m2), summary(m3)
    g2, g3 = type_grid(m2), type_grid(m3)
    same_pos = set(g2) & set(g3)
    return {"structSame": struct_hash(c2) == struct_hash(c3), "layers": [s2["layerCount"], s3["layerCount"]],
            "kinds": [s2["kinds"], s3["kinds"]], "total": [s2["total"], s3["total"]], "board": [s2["board"], s3["board"]],
            "t0": [s2["t0"], s3["t0"]], "effectsSame": s2["effects"] == s3["effects"], "effects": [s2["effects"], s3["effects"]],
            "containersSame": s2["containers"] == s3["containers"],
            "containers": [s2["containers"], s3["containers"]] if s2["containers"] != s3["containers"] else None,
            "typeChangedCells": sum(1 for p in same_pos if g2[p] != g3[p]), "cellsCompared": len(same_pos),
            "typeCounts": [s2["typeCounts"], s3["typeCounts"]] if s2["typeCounts"] != s3["typeCounts"] else None}


def main():
    b2, b3 = load(B2), load(B3)
    head = {k: [b2.get(k), b3.get(k)] for k in ("batch_id", "saved_at", "version") if b2.get(k) != b3.get(k)}
    head["batchFieldsDiffer"] = sorted(k for k in set(b2.get("batch") or {}) | set(b3.get("batch") or {})
                                       if (b2.get("batch") or {}).get(k) != (b3.get("batch") or {}).get(k))
    L2 = {x["meta"]["level_number"]: x for x in b2["levels"]}
    L3 = {x["meta"]["level_number"]: x for x in b3["levels"]}
    shard = load(SHARD)
    af = {x["level"]: x for x in load(METRICS)["levels"]}
    changed, meta_only = {}, {}
    meta_key_counter = Counter()
    for n in sorted(set(L2) | set(L3)):
        a, b = L2.get(n), L3.get(n)
        if a is None or b is None:
            changed[n] = {"presence": [a is not None, b is not None]}
            continue
        md = dict_diff(a["meta"], b["meta"])
        for k in md:
            meta_key_counter[k] += 1
        if a["level_json"] == b["level_json"]:
            if md:
                meta_only[n] = md
            continue
        lj = dict_diff(a["level_json"], b["level_json"])
        mc = compare_maps(a["level_json"], b["level_json"])
        rec = {"levelJson": lj, "map": mc, "meta": md,
               "pred": [a["meta"].get("predicted_clear_rate"), b["meta"].get("predicted_clear_rate")],
               "afCleanFt": (af.get(n) or {}).get("clean_ft_rate"), "afCleanFtN": (af.get(n) or {}).get("clean_ft_n")}
        s = shard.get(str(n))
        if s:
            rec["shardVs2"] = compare_maps(s["map"], a["level_json"])
            rec["shardVs3"] = compare_maps(s["map"], b["level_json"])
            rec["shardRow"] = s["row"]
            rec["shardMatchEditor"] = s.get("map_match_editor")
        changed[n] = rec
    # L341 and other shard mismatches that did not change between batches
    extra = {}
    for k, s in shard.items():
        n = int(k)
        if s.get("map_match_editor") == "mismatch" and n not in changed:
            a, b = L2[n], L3[n]
            row2 = {f: a["level_json"].get(f) for f in s["row"]}
            extra[n] = {"shardRow": s["row"], "batch2Row": row2, "rowDiff": {f: [s["row"][f], row2[f]] for f in s["row"] if str(s["row"][f]) != str(row2[f])},
                        "shardVs2": compare_maps(s["map"], a["level_json"]), "batch2EqualsBatch3": a["level_json"] == b["level_json"]}
    out = {"files": {"batch2": os.path.basename(B2), "batch3": os.path.basename(B3)}, "batchHeader": head,
           "changedLevelJson": sorted(changed), "metaOnlyChanged": {str(k): v for k, v in meta_only.items()},
           "metaKeyChangeCounts": dict(meta_key_counter),
           "levels": {str(k): v for k, v in changed.items()}, "shardMismatchUnchanged": {str(k): v for k, v in extra.items()}}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "diff.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=list)
    print(json.dumps({"header": head, "changed": sorted(changed), "metaOnly": len(meta_only), "metaKeys": dict(meta_key_counter),
                      "shardMismatchUnchanged": sorted(extra)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
