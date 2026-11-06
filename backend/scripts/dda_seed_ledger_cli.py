"""DDA 시드 이력 장부 CLI (서버 호출 없음).

  python scripts/dda_seed_ledger_cli.py baseline-file <levels.raw.json> [--tag v0] [--memo ...]
      서버 원본 파일(real_array load 원문)로 기준점 스냅샷 생성.
  python scripts/dda_seed_ledger_cli.py plan-batch <batch.json> [--base <id>] [--infinity append|off|only]
                                         [--persist] [--out <dir>]
      배치 파일({batch, levels:[{meta, level_json}]})을 업로드 경로와 같은 계산으로 '보낼 값' 계획 → 기준 스냅샷과 비교.
      --persist 면 dryrun 스냅샷으로 저장. --out 이 있으면 diff JSON/CSV 저장.
  python scripts/dda_seed_ledger_cli.py diff <a> <b> [--out <dir>]
  python scripts/dda_seed_ledger_cli.py list
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from app.core import dda_seed_ledger as L  # noqa: E402


def _write(out_dir: str, name: str, res: dict) -> None:
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(out_dir, name + ".csv"), "w", encoding="utf-8-sig") as f:
        f.write(L.diff_csv(res["items"]))
    print("wrote", os.path.join(out_dir, name + ".{json,csv}"))


def main() -> None:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("baseline-file")
    b.add_argument("path")
    b.add_argument("--tag", default="v0")
    b.add_argument("--memo", default="")
    p = sp.add_parser("plan-batch")
    p.add_argument("path")
    p.add_argument("--base", default=None)
    p.add_argument("--infinity", default="append", choices=("off", "append", "only"))
    p.add_argument("--no-relabel", action="store_true")
    p.add_argument("--persist", action="store_true")
    p.add_argument("--memo", default="")
    p.add_argument("--out", default="")
    d = sp.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--out", default="")
    sp.add_parser("list")
    a = ap.parse_args()

    if a.cmd == "baseline-file":
        print(json.dumps(L.baseline_from_raw_file(a.path, memo=a.memo, tag=a.tag), ensure_ascii=False, indent=1))
    elif a.cmd == "list":
        for s in L.list_snapshots():
            print(s["id"], s.get("kind"), s.get("status"), s.get("tag"), s.get("counts"), s.get("memo"))
    elif a.cmd == "diff":
        res = L.diff_snapshots(L.load(a.a), L.load(a.b), only_changed=True)
        print(json.dumps(res["summary"], ensure_ascii=False))
        if a.out:
            _write(a.out, f"diff_{a.a}_vs_{a.b}", res)
    elif a.cmd == "plan-batch":
        from app.api.routes.dda_seed_ledger import plan_rows_from_batch, _latest_base_id
        with open(a.path, encoding="utf-8") as f:
            doc = json.load(f)
        levels = [{"level_number": int(l["meta"]["level_number"]), "level_json": l["level_json"]} for l in doc["levels"]]
        base_id = a.base or _latest_base_id()
        base = L.load(base_id)
        rows = plan_rows_from_batch(levels, base["rows"], infinity_mode=a.infinity, infinity_relabel=not a.no_relabel)
        bt = doc.get("batch") or {}
        if a.persist:
            saved = L.create_snapshot(kind="dryrun", rows=rows, memo=a.memo or "가상 — 배치 파일 기준 계획(업로드 아님)",
                                      batch_id=bt.get("id", doc.get("batch_id", "")), batch_name=bt.get("name", ""),
                                      source="batch_plan_cli", options={"base": base_id, "path": a.path,
                                                                        "infinity_mode": a.infinity})
            virt = L.load(saved["id"])
            print("saved", saved["id"])
        else:
            virt = {"id": "(virtual)", "kind": "dryrun", "status": "virtual", "rows": rows,
                    "batchId": bt.get("id", ""), "batchName": bt.get("name", "")}
        res = L.diff_snapshots(base, virt, only_changed=True)
        print("base", base_id, "planned rows", len(rows), "virtual rowsSha256", L.rows_sha256(rows))
        print(json.dumps(res["summary"], ensure_ascii=False))
        if a.out:
            _write(a.out, f"diff_{base_id}_vs_batch", res)


if __name__ == "__main__":
    main()
