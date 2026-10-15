"""LIVE 일치 에디터 배치 만들기 (10 §9-12) — 3차 배치 복제 + L32~79(33레벨) 2차 항목 교체 + L341 timea.

  build  : 새 배치 페이로드를 만들고 라이브 빌드 샤드(b741f6a3 = 1.1.0 / iOS 2.1.0, 게임 저장소 git show 읽기만)와
           1530레벨 전부 대조한다 — canonical_map 전체 해시 + GameBoost 내보내기 행(_convert_to_townpop_format) 주요 필드.
           저장하지 않는다(out: pv_sandbox/.../live_match_batch/payload.json, precheck.json).
  save   : 에디터 정식 저장 API PUT /api/production/batches/{id}(신규 → base_version 없음)로 저장. 기존 배치·인덱스 항목은 건드리지 않는다.
  verify : 저장본을 GET /api/production/batches/{id} 로 다시 읽어 같은 대조 + 목록 노출 + 기존 3개 배치 sha256·인덱스 항목 불변.
GameBoost 업로드·서버 동기화·배포 없음.
Usage: .venv/bin/python scripts/live_match_batch.py build|save|verify
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import string
import sys
import time
import urllib.request

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)
sys.path.insert(0, os.path.join(BACKEND, "scripts"))
from app.api.routes.gboost import _convert_to_townpop_format  # noqa: E402
from app.core.pv.canonical import canonical_map  # noqa: E402

PROD = os.path.join(BACKEND, "data", "production")
B1 = "batch_1788744001053_wa5xrgv82"
B2 = "batch_1789435856664_o0klei461"
B3 = "batch_1789636723287_uulknmtej"
FROM_B2 = [32, 33, 34, *range(36, 45), *range(46, 50), *range(61, 65), *range(66, 72), *range(73, 80)]
L341_TIMEA = 180
NAME = "톱니바퀴 1500 [LIVE 일치본: 3차 + 2차 L32~79] - 2026. 10. 15."
SHARD_COMMIT = "b741f6a3"
OUT = os.path.join(BACKEND, "data", "pv_sandbox", "pv_20261002_live3", "live_match_batch")
API = os.environ.get("PROD_API", "http://localhost:8000/api/production")
ROW_KEYS = ("randSeed", "useTileCount", "unlockTile", "shuffleTile", "typeImbalance", "autoCollectCount", "timea", "layer",
            "col", "row", "num")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def chash(m, norm=False):
    c = canonical_map(m)
    if norm:  # null effect slot == "" (editor L341 stores [type, null], shard stores [type, ""])
        for k, v in c.items():
            if k.startswith("layer_") and isinstance(v, dict) and isinstance(v.get("tiles"), dict):
                v["tiles"] = {p: ["" if z is None else z for z in t] if isinstance(t, list) else t for p, t in v["tiles"].items()}
    return hashlib.sha256(json.dumps(c, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def shard():
    import bot_af_L32_500 as BA
    maps, i = {}, 0
    while True:
        try:
            maps.update(BA._git_key(SHARD_COMMIT, f"levelmap_level_{i}"))
        except RuntimeError:
            break
        i += 1
    tab = BA._git_key(SHARD_COMMIT, "levels")
    keys = tab["__keys"]
    rows = {}
    for v in tab["__vals"]:
        o = {keys[j]: v[j] for j in range(min(len(keys), len(v)))}
        rows[str(o.get("id"))] = o
    return maps, rows


def compare(levels, maps, rows):
    res = {"mapHashMatch": 0, "mapMismatch": [], "rowDiffs": {}, "missingInShard": []}
    for x in levels:
        n = x["meta"]["level_number"]
        key = f"level_{n}"
        if key not in maps:
            res["missingInShard"].append(n)
            continue
        if chash(x["level_json"]) == chash(maps[key]):
            res["mapHashMatch"] += 1
        else:
            res["mapMismatch"].append(n)
        if chash(x["level_json"], True) == chash(maps[key], True):
            res["mapHashMatchNullEqEmpty"] = res.get("mapHashMatchNullEqEmpty", 0) + 1
        ex = _convert_to_townpop_format(copy.deepcopy(x["level_json"]))
        sr = rows.get(key) or {}
        d = {k: [ex.get(k), sr.get(k)] for k in ROW_KEYS if k in sr and str(ex.get(k)) != str(sr.get(k))}
        if d:
            res["rowDiffs"][n] = d
    res["levels"] = len(levels)
    return res


def build():
    b2, b3 = load(os.path.join(PROD, f"{B2}.json")), load(os.path.join(PROD, f"{B3}.json"))
    by2 = {x["meta"]["level_number"]: x for x in b2["levels"]}
    levels = []
    for x in b3["levels"]:
        n = x["meta"]["level_number"]
        y = copy.deepcopy(by2[n] if n in FROM_B2 else x)
        if n == 341:
            y["level_json"]["timea"] = L341_TIMEA
        levels.append(y)
    now_ms = int(time.time() * 1000)
    bid = f"batch_{now_ms}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=9))}"
    iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now_ms / 1000))
    batch = copy.deepcopy(b3["batch"])
    batch.pop("__server_version", None)
    batch.update({"id": bid, "name": NAME, "created_at": iso, "updated_at": iso})
    batch["_provenance"] = {"base": B3, "replacedFrom": {"batch": B2, "levels": FROM_B2},
                            "l341": f"level_json.timea = {L341_TIMEA} (live shard {SHARD_COMMIT} levels row)",
                            "reason": "editor set matching live build 1.1.0 / iOS 2.1.0 (10 §9-11, §9-12)"}
    maps, rows = shard()
    pre = compare(levels, maps, rows)
    pre3 = compare(b3["levels"], maps, rows)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "payload.json"), "w", encoding="utf-8") as f:
        json.dump({"batch_id": bid, "batch": batch, "levels": levels}, f, ensure_ascii=False)
    with open(os.path.join(OUT, "precheck.json"), "w", encoding="utf-8") as f:
        json.dump({"newBatch": pre, "batch3ForReference": {k: pre3[k] for k in ("mapHashMatch", "mapMismatch", "levels")},
                   "shardLevels": len(maps), "shardRows": len(rows)}, f, ensure_ascii=False, indent=1, default=str)
    print(bid, json.dumps({k: pre[k] for k in ("levels", "mapHashMatch", "mapMismatch", "missingInShard")}),
          "rowDiffs", len(pre["rowDiffs"]), "| b3 match", pre3["mapHashMatch"], "shard maps", len(maps))
    print(json.dumps(dict(list(pre["rowDiffs"].items())[:15]), ensure_ascii=False))


def old_state():
    idx = load(os.path.join(PROD, "_index.json"))
    return {b: {"sha256": sha256(os.path.join(PROD, f"{b}.json")), "index": idx.get(b)} for b in (B1, B2, B3)}


def save():
    pay = load(os.path.join(OUT, "payload.json"))
    before = old_state()
    with open(os.path.join(OUT, "before.json"), "w") as f:
        json.dump(before, f, indent=1)
    body = json.dumps({"batch_id": pay["batch_id"], "batch": pay["batch"], "levels": pay["levels"]}, ensure_ascii=False).encode()
    req = urllib.request.Request(f"{API}/batches/{pay['batch_id']}", data=body, method="PUT",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.loads(r.read())
    with open(os.path.join(OUT, "save_response.json"), "w") as f:
        json.dump(resp, f, indent=1)
    print(json.dumps(resp, ensure_ascii=False))


def verify():
    pay = load(os.path.join(OUT, "payload.json"))
    bid = pay["batch_id"]
    with urllib.request.urlopen(f"{API}/batches", timeout=120) as r:
        lst = json.loads(r.read())
    listed = [x for x in lst if x["batch_id"] == bid]
    with urllib.request.urlopen(f"{API}/batches/{bid}", timeout=120) as r:
        got = json.loads(r.read())
    maps, rows = shard()
    post = compare(got["levels"], maps, rows)
    meta_changed = [x["meta"]["level_number"] for x, y in zip(got["levels"], pay["levels"]) if x["meta"] != y["meta"]]
    lj_changed = [x["meta"]["level_number"] for x, y in zip(got["levels"], pay["levels"]) if x["level_json"] != y["level_json"]]
    before, after = load(os.path.join(OUT, "before.json")), old_state()
    rep = {"batchId": bid, "listed": listed, "loadedLevels": len(got["levels"]), "version": got.get("version"),
           "shardCompare": post, "metaChangedBySaveGates": meta_changed, "levelJsonChangedBySave": lj_changed,
           "oldBatchesUnchanged": all(before[b]["sha256"] == after[b]["sha256"] for b in before),
           "oldIndexEntriesUnchanged": all(before[b]["index"] == after[b]["index"] for b in before),
           "oldSha256": {b: after[b]["sha256"][:16] for b in after}, "savedFileSha256": sha256(os.path.join(PROD, f"{bid}.json"))}
    with open(os.path.join(OUT, "verify.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: v for k, v in rep.items() if k != "shardCompare"}, ensure_ascii=False, default=str))
    print(json.dumps({k: post.get(k) for k in ("levels", "mapHashMatch", "mapHashMatchNullEqEmpty", "mapMismatch", "missingInShard")}), "rowDiffs", len(post["rowDiffs"]), sorted({k for v in post["rowDiffs"].values() for k in v}))


def rowdiff():
    """All non-map export-row fields vs the live shard row (every key present on either side)."""
    from collections import Counter, defaultdict
    maps, rows = shard()
    pay = load(os.path.join(OUT, "payload.json"))
    diff = defaultdict(dict)
    for x in pay["levels"]:
        n = x["meta"]["level_number"]
        ex = _convert_to_townpop_format(copy.deepcopy(x["level_json"]))
        sr = rows[f"level_{n}"]
        for k in (set(sr) | set(ex)) - {"map"}:
            a, b = ex.get(k, "<none>"), sr.get(k, "<none>")
            if str(a) != str(b):
                diff[k][str(n)] = [str(a), str(b)]
    # difficulty: explained by the upload panel injecting meta.predicted_clear_rate (ProductionExport.tsx:892)?
    meta = {str(x["meta"]["level_number"]): x["meta"] for x in pay["levels"]}
    unexplained = []
    for n, (_, b) in diff.get("difficulty", {}).items():
        pc = meta[n].get("predicted_clear_rate")
        exp = str(max(0, min(100, round(pc * 100)))) if isinstance(pc, (int, float)) else "-1"
        if exp != b:
            unexplained.append([int(n), pc, b])
    out = {"fields": {k: {"levels": len(v), "pairs": Counter(f"{a}->{b}" for a, b in v.values()).most_common(8),
                          "sampleLevels": sorted(map(int, v))[:20]} for k, v in diff.items()},
           "difficultyUnexplainedByPredicted": unexplained, "detail": diff}
    with open(os.path.join(OUT, "rowdiff_all.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out["fields"], ensure_ascii=False))
    print("difficulty unexplained", unexplained)


if __name__ == "__main__":
    {"build": build, "save": save, "verify": verify, "rowdiff": rowdiff}[sys.argv[1]]()
