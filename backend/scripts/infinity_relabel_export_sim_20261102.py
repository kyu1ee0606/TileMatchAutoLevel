#!/usr/bin/env python3
"""무한 그림 치환 v1 — 서버 호출 없는 내보내기 시뮬레이션 (읽기 전용, 가짜 GBoost 클라이언트).

배치(기본: ~/sp_meowsgarden/tools/dda_level_fix/out/batch_final_dryrun.v2.json)를 업로드 화면 'append' 모드와 같은 대상
(level_1..1530 + infinity_1..1030 = 원본 500+N)으로 실제 FastAPI 라우트에 보낸다(TestClient + 메모리 가짜 서버).
확인: ① 업로드 경로 infinity_N map == 기준 infinity_maps.json map (바이트) ② level_N map == 원본 변환 map
      ③ useTileCount 원본과 같음 ④ export-preview / infinity-relabel(JSON 내보내기) 경로가 업로드와 같은 맵
usage: venv/bin/python scripts/infinity_relabel_export_sim_20261102.py [batch.json] [out.json]
"""
import copy
import json
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
logging.disable(logging.CRITICAL)

from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import get_gboost  # noqa: E402
from app.api.routes import gboost as gb_routes  # noqa: E402
from app.api.routes.gboost import _convert_to_townpop_format as conv  # noqa: E402
from app.core import dda_seed_catalog as cat  # noqa: E402
from app.main import app  # noqa: E402

REF = os.path.expanduser("~/sp_meowsgarden/tools/dda_level_fix/out")


def dump(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


class Fake:
    is_configured = True
    base_url, project_id = "fake://", "fake"

    def __init__(self):
        self.saved = {}

    async def load_level(self, *a, **k):
        return None

    async def save_level(self, board_id, level_id, level_json):
        self.saved[level_id] = json.loads(json.dumps(level_json))
        return {"success": True}

    async def save_thumbnail(self, *a, **k):
        return {"success": True}


def main():
    batch_path = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else os.path.join(REF, "batch_final_dryrun.v2.json")
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    lv = {L["meta"]["level_number"]: L["level_json"] for L in json.load(open(batch_path))["levels"]}
    ref_maps = json.load(open(os.path.join(REF, "relabel_v1", "infinity_maps.json")))
    fake = Fake()
    app.dependency_overrides[get_gboost] = lambda: fake
    gb_routes._generate_thumbnail = lambda *a, **k: None   # 썸네일 생성 생략(맵 대조와 무관, 시간 절약)
    client = TestClient(app)
    targets = [(f"level_{n}", n) for n in sorted(lv)] + [(f"infinity_{k}", 500 + k) for k in range(1, 1031) if 500 + k in lv]
    bad = []
    for tid, src in targets:
        r = client.post(f"/api/gboost/levels/{tid}", json={"level_json": lv[src]})
        if r.status_code != 200:
            bad.append({"id": tid, "why": f"http {r.status_code} {r.text[:120]}"})
    stats = {"level_rows": 0, "infinity_rows": 0, "level_map_same": 0, "infinity_map_eq_ref": 0,
             "infinity_map_differs_from_source": 0, "useTileCount_same": 0}
    for tid, src in targets:
        row = fake.saved.get(tid)
        if row is None:
            continue
        base = conv(copy.deepcopy(lv[src]))
        if row["useTileCount"] == base["useTileCount"]:
            stats["useTileCount_same"] += 1
        else:
            bad.append({"id": tid, "why": "useTileCount"})
        if tid.startswith("level_"):
            stats["level_rows"] += 1
            if dump(row["map"]) == dump(base["map"]):
                stats["level_map_same"] += 1
            else:
                bad.append({"id": tid, "why": "level map changed"})
        else:
            stats["infinity_rows"] += 1
            if dump(row["map"]) == dump(ref_maps[tid]["map"]) and cat.map_sha256(row) == ref_maps[tid]["mapSha256"]:
                stats["infinity_map_eq_ref"] += 1
            else:
                bad.append({"id": tid, "why": "infinity map != reference"})
            if dump(row["map"]) != dump(base["map"]):
                stats["infinity_map_differs_from_source"] += 1
    # JSON 내보내기 API · export-preview 경로 (무한 행 전부)
    inf = [(t, s) for t, s in targets if t.startswith("infinity_")]
    json_same = prev_ok = 0
    for i in range(0, len(inf), 200):
        part = inf[i:i + 200]
        body = [{"target_id": t, "level_json": lv[s]} for t, s in part]
        rr = client.post("/api/dda-seeds/infinity-relabel", json={"levels": body}).json()["results"]
        pp = client.post("/api/dda-seeds/export-preview", json={"board_id": "levels", "levels": body}).json()["results"]
        for (t, s), r1, p1 in zip(part, rr, pp):
            if r1["target_id"] == t and dump(conv(copy.deepcopy(r1["level_json"]))["map"]) == dump(fake.saved[t]["map"]):
                json_same += 1
            else:
                bad.append({"id": t, "why": "json export map != upload map"})
            if p1.get("relabel") and p1["relabel"]["mapping"] == ref_maps[t]["mapping"] == r1["relabel"]["mapping"]:
                prev_ok += 1
            else:
                bad.append({"id": t, "why": "export-preview relabel info mismatch"})
    res = {"batch": batch_path, "targets": len(targets), **stats, "json_export_map_eq_upload": json_same,
           "export_preview_mapping_eq": prev_ok, "problems": len(bad), "problemSamples": bad[:30]}
    if out_path:
        json.dump(res, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "problemSamples"}, ensure_ascii=False))
    print("samples:", bad[:5])
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
