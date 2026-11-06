#!/usr/bin/env python3
"""무한 그림 치환 v1 — 맵툴 구현(app.core.infinity_relabel) vs sp_meowsgarden 기준 산출물 바이트 대조 (읽기 전용).

기준: ~/sp_meowsgarden/tools/dda_level_fix/out/relabel_v1/{vectors.json, infinity_maps.json, summary.json}
입력: 같은 폴더 상위 out/batch_final_dryrun.v2.json (기준 구현이 쓴 정식 배치, level_{500+N} 원본)
맵툴 경로: prepare_export_level_json("infinity_N", 정식 level_json) → _convert_to_townpop_format → map
usage: venv/bin/python scripts/infinity_relabel_crosscheck_20261102.py [out.json]
"""
import copy
import hashlib
import json
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
logging.disable(logging.CRITICAL)

from app.api.routes.gboost import _convert_to_townpop_format  # noqa: E402
from app.core import infinity_relabel as R  # noqa: E402
from app.core.dda_seed_catalog import map_sha256  # noqa: E402

REF = os.path.expanduser("~/sp_meowsgarden/tools/dda_level_fix/out")


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def sha(o):
    return hashlib.sha256(dump(o).encode()).hexdigest()


def main():
    batch = json.load(open(os.path.join(REF, "batch_final_dryrun.v2.json")))
    lv = {L["meta"]["level_number"]: L["level_json"] for L in batch["levels"]}
    ref_raw = open(os.path.join(REF, "relabel_v1", "infinity_maps.json"), "rb").read()
    ref = json.loads(ref_raw)
    vec = json.load(open(os.path.join(REF, "relabel_v1", "vectors.json")))["vectors"]
    summ = json.load(open(os.path.join(REF, "relabel_v1", "summary.json")))

    mine = {}
    mism = []
    for n in range(1, 1031):
        src = copy.deepcopy(lv[500 + n])
        src_t = _convert_to_townpop_format(copy.deepcopy(src))
        rj, info = R.prepare_export_level_json(f"infinity_{n}", src, True)
        t = _convert_to_townpop_format(copy.deepcopy(rj))
        mine[f"infinity_{n}"] = {"map": t["map"], "useTileCount": t["useTileCount"], "mapping": info["mapping"],
                                 "sourceMapSha256": sha(src_t["map"]), "mapSha256": sha(t["map"])}
        r = ref[f"infinity_{n}"]
        bad = [k for k in ("map", "useTileCount", "mapping", "sourceMapSha256", "mapSha256")
               if dump(mine[f"infinity_{n}"][k]) != dump(r[k])]
        if t["useTileCount"] != src_t["useTileCount"]:
            bad.append("useTileCount_changed")
        if map_sha256(t) != r["mapSha256"]:
            bad.append("map_sha256(binding)")
        if dump(src) != dump(lv[500 + n]):
            bad.append("input_mutated")
        if bad:
            mism.append({"id": f"infinity_{n}", "fields": bad})
    raw = dump(mine).encode()
    vbad = []
    for v in vec:
        n = int(v["id"].split("_")[1])
        src = lv[500 + n]
        got = {"key": R.rule_key(n), "h": R.fnv1a32(R.rule_key(n)), "types": R.types_of(src),
               "mapping": mine[v["id"]]["mapping"], "sourceMapSha256": mine[v["id"]]["sourceMapSha256"],
               "mapSha256": mine[v["id"]]["mapSha256"], "useTileCount": mine[v["id"]]["useTileCount"]}
        d = [k for k in got if dump(got[k]) != dump(v[k])]
        if d:
            vbad.append({"id": v["id"], "fields": d})
    res = {
        "rows": len(mine), "rowMismatch": len(mism), "mismatches": mism[:50],
        "vectors": len(vec), "vectorMismatch": vbad,
        "infinityMapsBytesEqual": raw == ref_raw,
        "mineSha256": hashlib.sha256(raw).hexdigest(), "refSha256": summ.get("infinityMapsSha256"),
        "relabelled": sum(1 for x in mine.values() if x["mapping"]),
    }
    if len(sys.argv) > 1:
        json.dump(res, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "mismatches"}, ensure_ascii=False))
    return 0 if (not mism and not vbad and raw == ref_raw) else 1


if __name__ == "__main__":
    sys.exit(main())
