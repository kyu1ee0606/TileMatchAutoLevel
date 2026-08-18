"""프론트 DEFAULT_CONCEPTS(150개, Lv10~1500) → 서버 boss_concepts.json 보충.

프론트는 서버가 비어 있으면 DEFAULT_CONCEPTS 를 씨딩하고 '미저장' 표시만 띄운다.
사용자가 저장 버튼을 누르기 전까지 서버엔 없다 → 백그라운드 초안 생성이 모양 문구를
못 읽는다. 여기서 **누락된 레벨만** 채운다(서버에 이미 있는 값은 절대 덮지 않음).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TSX = ROOT.parent / "frontend/src/components/BossTemplatePanel.tsx"
OUT = ROOT / "data/boss_concepts.json"


def parse_defaults() -> dict:
    s = TSX.read_text()
    i = s.index("const DEFAULT_CONCEPTS")
    j = s.index("\n};", i)
    blk = s[i:j]
    out = {}
    # '390': { chapter: '...', beat: '...', deco: '...', shape: '...', note: '...' },
    for m in re.finditer(r"'(\d+)':\s*\{([^}]*)\}", blk):
        lv, body = m.group(1), m.group(2)
        rec = {}
        for f in ("chapter", "beat", "deco", "shape", "note"):
            fm = re.search(rf"{f}:\s*'((?:[^'\\]|\\.)*)'", body)
            rec[f] = (fm.group(1).replace("\\'", "'") if fm else "")
        out[lv] = rec
    return out


def main(apply: bool):
    src = parse_defaults()
    cur = json.loads(OUT.read_text()) if OUT.exists() else {}
    missing = {k: v for k, v in src.items() if k not in cur}
    no_shape = [k for k, v in src.items() if not v.get("shape", "").strip()]

    print(f"프론트 DEFAULT_CONCEPTS: {len(src)}개")
    print(f"서버 현재: {len(cur)}개")
    print(f"보충 대상(서버에 없는 레벨): {len(missing)}개")
    if no_shape:
        print(f"⚠️ 모양 문구 비어있는 레벨: {no_shape}")

    if not apply:
        print("\n--dry-run (적용하려면 --apply)")
        for k in sorted(missing, key=int)[:5]:
            print(f"  {k}: {missing[k]['shape']}")
        return

    cur.update(missing)
    OUT.write_text(json.dumps(cur, ensure_ascii=False, indent=2))
    print(f"\n저장 완료 → {OUT}  (총 {len(cur)}개)")


if __name__ == "__main__":
    main("--apply" in sys.argv)
