"""[기존 배치 수리] 규칙 위반 자동 교정.

수리 가능(속성만 변경 → ÷3/모양/max_moves 불변):
  - 해제 불가 사슬 → plain 화 (_chain_release_closure)
  - 폭탄 카운트다운 범위 밖 → 3~5 로 정규화
  - 고아 링크 → plain 화
수리 불가(재생성 필요) → 플래그만 남기고 verification_passed=False:
  - 튜토리얼 기믹 누락
  - timea 부족

기본 dry-run. --apply 시 원본 백업 후 덮어쓰기.
"""
import sys
import json
import glob
import argparse
import copy
import shutil
import time
from collections import Counter

sys.path.insert(0, "/Users/casualdev/TileMatchAutoLevel/backend")
from app.core.generator import LevelGenerator                      # noqa: E402
from app.api.routes.production_store import _scan_rule_violations  # noqa: E402
from app.core.solver import _clearability_type_counts              # noqa: E402

STORE = "/Users/casualdev/TileMatchAutoLevel/backend/data/production"
gen = LevelGenerator()


def repair_level(lj):
    """수리 가능 항목만 적용. 반환: 수리 내역 Counter."""
    done = Counter()
    before_chain = _chain_count(lj)
    gen._chain_release_closure(lj)
    d = before_chain - _chain_count(lj)
    if d:
        done["chain_plain"] += d
    n = gen._normalize_bomb_countdowns.__wrapped__ if hasattr(gen._normalize_bomb_countdowns, "__wrapped__") else None
    before_bomb = _bad_bomb_count(lj)
    gen._normalize_bomb_countdowns(lj)
    if before_bomb:
        done["bomb_fixed"] += before_bomb
    before_link = _link_count(lj)
    gen._strip_orphaned_link_tiles(lj)
    dl = before_link - _link_count(lj)
    if dl:
        done["link_plain"] += dl
    return done


def _chain_count(lj):
    c = 0
    for i in range(int(lj.get("layer", 0) or 0)):
        tiles = (lj.get(f"layer_{i}") or {}).get("tiles") or {}
        c += sum(1 for d in tiles.values() if isinstance(d, list) and len(d) > 1 and d[1] == "chain")
    return c


def _link_count(lj):
    c = 0
    for i in range(int(lj.get("layer", 0) or 0)):
        tiles = (lj.get(f"layer_{i}") or {}).get("tiles") or {}
        c += sum(1 for d in tiles.values()
                 if isinstance(d, list) and len(d) > 1 and isinstance(d[1], str) and d[1].startswith("link_"))
    return c


def _bad_bomb_count(lj):
    from app.core.generator import BOMB_COUNTDOWN_MIN as LO, BOMB_COUNTDOWN_MAX as HI
    c = 0
    for i in range(int(lj.get("layer", 0) or 0)):
        tiles = (lj.get(f"layer_{i}") or {}).get("tiles") or {}
        for d in tiles.values():
            if not (isinstance(d, list) and len(d) > 1 and isinstance(d[1], str)):
                continue
            a = d[1]
            if not a.startswith("bomb"):
                continue
            p = a.split("_")
            if len(p) == 2 and p[1].isdigit():
                if not (LO <= int(p[1]) <= HI):
                    c += 1
            else:
                c += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch", default=None, help="특정 배치 파일명(미지정=최근 2개)")
    args = ap.parse_args()

    files = ([f"{STORE}/{args.batch}"] if args.batch
             else sorted(glob.glob(f"{STORE}/batch_*.json"), key=lambda p: -__import__("os").path.getmtime(p))[:2])

    for fp in files:
        try:
            d = json.load(open(fp))
        except Exception as e:
            print(f"skip {fp}: {e}")
            continue
        levels = d.get("levels") or []
        repaired = Counter()
        lv_repaired = 0
        residual = Counter()
        residual_lv = []
        inv_broken = []

        for e in levels:
            lj = e.get("level_json")
            m = e.get("meta") or {}
            if not isinstance(lj, dict):
                continue
            before_types = _clearability_type_counts(lj)
            before_moves = gen._calculate_max_moves(lj)
            r = repair_level(lj)
            if r:
                lv_repaired += 1
                repaired.update(r)
                # 불변식 확인
                if (_clearability_type_counts(lj) != before_types
                        or gen._calculate_max_moves(lj) != before_moves):
                    inv_broken.append(m.get("level_number"))
            v = _scan_rule_violations(lj, m.get("level_number"))
            if v:
                residual.update(v.keys())
                residual_lv.append((m.get("level_number"), list(v.keys())))
                m["verification_passed"] = False
                m["rule_violations"] = v

        name = fp.split("/")[-1]
        print(f"\n=== {name} ({len(levels)} levels) ===")
        print(f"  수리된 레벨: {lv_repaired}  내역: {dict(repaired)}")
        print(f"  불변식 깨짐: {inv_broken if inv_broken else 'NONE ✅'}")
        print(f"  잔여(재생성 필요): {dict(residual)}")
        for x in residual_lv[:10]:
            print(f"    {x}")

        if args.apply and not inv_broken:
            bak = fp + f".bak_{int(time.time())}"
            shutil.copy(fp, bak)
            d["version"] = int(d.get("version", 0)) + 1
            json.dump(d, open(fp, "w"), ensure_ascii=False)
            print(f"  APPLIED. backup={bak.split('/')[-1]} v{d['version']}")
        elif args.apply:
            print("  NOT APPLIED — 불변식 깨짐. 수동 검토 필요.")
        else:
            print("  (dry-run — --apply 로 적용)")


if __name__ == "__main__":
    main()
