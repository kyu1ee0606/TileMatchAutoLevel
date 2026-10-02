"""E-P1-1: copy the LIVE production batch into an isolated PV sandbox (read-only on the source).

Sandbox lives OUTSIDE backend/data/production so it never shows up in the
production batch list / browser sync / GameBoost upload paths
(04_seed_variant_plan.md §A1). Never import sandbox files into the editor UI:
bakeFullBoard would re-bake t0 tiles (PD:376-449).

Usage: python scripts/pv_make_sandbox.py [--copy-id pv_20261002_live3] [--batch batch_...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCTION = os.path.join(BACKEND, "data", "production")
SANDBOX_ROOT = os.path.join(BACKEND, "data", "pv_sandbox")
DEFAULT_BATCH = "batch_1789636723287_uulknmtej"  # [LIVE 패치본 3차]


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--copy-id", default="pv_20261002_live3")
    ap.add_argument("--batch", default=DEFAULT_BATCH)
    args = ap.parse_args()

    if args.copy_id.startswith("batch_") or "/" in args.copy_id or ".." in args.copy_id:
        print("invalid copy id (must not start with batch_)", file=sys.stderr)
        return 2
    src = os.path.join(PRODUCTION, f"{args.batch}.json")
    dst_dir = os.path.join(SANDBOX_ROOT, args.copy_id)
    dst = os.path.join(dst_dir, "source.json")
    if os.path.exists(dst):
        print(f"already exists: {dst} (refusing to overwrite)")
        return 0

    src_sha = sha256_file(src)
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copyfile(src, dst)  # byte copy
    dst_sha = sha256_file(dst)
    if dst_sha != src_sha:
        os.remove(dst)
        print("copy hash mismatch", file=sys.stderr)
        return 1

    batch = data.get("batch") or {}
    manifest = {
        "copyId": args.copy_id,
        "sourceBatchId": data.get("batch_id", args.batch),
        "sourceName": batch.get("name"),
        "sourceVersion": data.get("version"),
        "sourceSavedAt": data.get("saved_at"),
        "sourceLevelCount": len(data.get("levels") or []),
        "sourceSha256": src_sha,
        "note": "PV sandbox copy. Do not move into backend/data/production. Do not import into the editor UI.",
    }
    with open(os.path.join(dst_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
