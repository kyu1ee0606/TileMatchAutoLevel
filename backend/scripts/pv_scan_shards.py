"""[P0-G4, 읽기 전용] 게임 배포 샤드(levelmap_level_*) 키 순서·구조 전수 스캔.

목적 (claudedocs/difficulty_personalization/04_seed_variant_plan.md §A3-3, A7 P0-G4):
  (a) 샤드 각 레벨의 tiles 키 순서가 GB 변환 정렬 순서(row-major, gboost.py
      `_tile_pos_sort_key`)와 같은가.
  (b) 샤드 맵 최상위 키 순서가 "layer", "layer_0", "layer_1", ... 순서(= 클라
      `CLayer.layerIndex` = map 키 열거 순번, 01 §9-1)와 같은가.
  (c) 샤드의 구조(structHash, 타입 제외)가 LIVE 3차 배치(에디터 원본)를
      canonical_map()한 결과와 같은가 — 다르면 02 §3-3에서 이미 알려진 34개
      (2차/3차 배치 재업로드 drift) 뿐인지 확인.

읽기 전용: 게임 저장소(sp_meowsgarden)와 에디터 production 배치 JSON 둘 다 읽기만 한다.
쓰기는 --out 으로 지정한 결과 markdown 파일(기본 claudedocs/difficulty_personalization/
p0_scan_result.md) 하나뿐이다.

샤드 복호 포맷: spZip.EncryptBytes = XOR(LCG 키스트림) 적용 후 ZIP(SharpZipLib, entry
"data"). 복호 = 같은 XOR(대칭) 후 압축 해제. 알고리즘은
sp_meowsgarden/Assets/00.spComponents/spZipUtil/spZip.cs를 그대로 포팅했다(읽기만, 게임
코드 미수정). 경로 규칙은 LevelMapProvider.cs(GetShardKey/GetShardPath), MD5는
spBase64.cs를 따른다.

사용:
    cd backend && .venv/bin/python scripts/pv_scan_shards.py
    .venv/bin/python scripts/pv_scan_shards.py --start 1 --end 50   # 부분 스캔(디버그용)
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.routes.gboost import _tile_pos_sort_key  # noqa: E402
from app.core.pv.canonical import canonical_map, struct_hash, check_layer_continuity  # noqa: E402

# ---------------------------------------------------------------------------
# 기본 경로
# ---------------------------------------------------------------------------
DEFAULT_PRODUCTION_BATCH = (
    Path(__file__).resolve().parent.parent
    / "data" / "production" / "batch_1789636723287_uulknmtej.json"
)
DEFAULT_GAME_STREAMING_ASSETS = Path(
    "/Users/casualdev/sp_meowsgarden/Assets/StreamingAssets/GBoost"
)
DEFAULT_OUT = (
    Path(__file__).resolve().parent.parent.parent
    / "claudedocs" / "difficulty_personalization" / "p0_scan_result.md"
)
SHARD_SIZE = 100  # LevelMapProvider.cs SHARD_SIZE

# 02 §3-3 / 01 §4에서 이미 알려진 "맵 상이" 레벨(에디터 3차 배치가 샤드에 반영 안 됨).
# 참고용 표시일 뿐 — 스캔 결과를 이 목록에 맞추지 않는다.
KNOWN_DRIFT_LEVELS = sorted(
    set(range(32, 35)) | set(range(36, 45)) | set(range(46, 50))
    | set(range(61, 65)) | set(range(66, 72)) | set(range(73, 80))
    | {341}
)

# ---------------------------------------------------------------------------
# spZip 복호 (spZip.cs 읽기 전용 포팅)
# ---------------------------------------------------------------------------
_EKEYBASE = bytes([
    0x55, 0x45, 0x73, 0x44, 0x42, 0x43, 0x30, 0x41, 0x41, 0x41, 0x67, 0x49,
    0x41, 0x4B, 0x6D, 0x79, 0x53, 0x56, 0x73, 0x53, 0x34, 0x69, 0x34, 0x53,
    0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x38, 0x45,
    0x41, 0x42, 0x51, 0x41, 0x5A, 0x47, 0x46, 0x30, 0x59, 0x51, 0x45, 0x41,
    0x45, 0x41, 0x42, 0x62, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x41, 0x46, 0x30, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x55, 0x39, 0x45, 0x50, 0x54, 0x31, 0x46, 0x4F, 0x4B, 0x64, 0x5A, 0x79,
    0x72, 0x55, 0x74, 0x77, 0x55, 0x2F, 0x5A, 0x30, 0x38, 0x58, 0x4C, 0x77,
    0x64, 0x6C, 0x56, 0x32, 0x53, 0x38, 0x73, 0x71, 0x54, 0x6A, 0x4D, 0x79,
    0x73, 0x4C, 0x50, 0x52, 0x54, 0x33, 0x4E, 0x30, 0x38, 0x58, 0x47, 0x72,
    0x6A, 0x56, 0x61, 0x33, 0x4E, 0x45, 0x67, 0x7A, 0x53, 0x69, 0x7A, 0x4D,
    0x6A, 0x45, 0x34, 0x72, 0x54, 0x59, 0x32, 0x75, 0x64, 0x74, 0x44, 0x53,
    0x63, 0x41, 0x76, 0x31, 0x38, 0x48, 0x4A, 0x51, 0x54, 0x73, 0x73, 0x77,
    0x4E, 0x4C, 0x4B, 0x30, 0x4D, 0x44, 0x5A, 0x33, 0x44, 0x66, 0x56, 0x32,
    0x63, 0x54, 0x65, 0x30, 0x7A, 0x4D, 0x7A, 0x50, 0x53, 0x55, 0x7A, 0x4A,
    0x4E, 0x4E, 0x54, 0x55, 0x55, 0x41, 0x78, 0x31, 0x55, 0x58, 0x54, 0x51,
    0x74, 0x41, 0x59, 0x41, 0x55, 0x45, 0x73, 0x42, 0x41, 0x6A, 0x4D, 0x41,
    0x4C, 0x51, 0x41, 0x41, 0x43, 0x41, 0x67, 0x41, 0x71, 0x62, 0x4A, 0x4A,
    0x57, 0x78, 0x4C, 0x69, 0x4C, 0x68, 0x4C, 0x2F, 0x2F, 0x2F, 0x2F, 0x2F,
    0x2F, 0x2F, 0x2F, 0x2F, 0x2F, 0x77, 0x51, 0x41, 0x46, 0x41, 0x41, 0x41,
    0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x41, 0x41, 0x41, 0x41, 0x41, 0x47, 0x52, 0x68, 0x64, 0x47, 0x45, 0x42,
    0x41, 0x42, 0x41, 0x41, 0x57, 0x77, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x41, 0x41, 0x42, 0x64, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x41, 0x46, 0x42, 0x4C, 0x42, 0x51, 0x59, 0x41, 0x41, 0x41, 0x41, 0x41,
    0x41, 0x51, 0x41, 0x42, 0x41, 0x45, 0x59, 0x41, 0x41, 0x41, 0x43, 0x54,
    0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x41, 0x3D,
])
_MASK = bytes([0xA5, 0x5A, 0x3C, 0xC3])
_LCG_A = 5
_LCG_C = 1


def _build_ekey() -> bytes:
    n = len(_EKEYBASE)
    out = bytearray(n)
    for i in range(n):
        b = _EKEYBASE[i]
        rot = i & 7
        rotated = b if rot == 0 else ((b << rot) | (b >> (8 - rot))) & 0xFF
        x = rotated ^ _MASK[i % 4]
        out[i] = x ^ ((i * 31) & 0xFF)
    return bytes(out)


_EKEY = _build_ekey()


def _process_bytes(data: bytes) -> bytes:
    """spZip.processBytes 포팅 — XOR 스트림은 대칭이라 암/복호 동일 함수."""
    kn = len(_EKEY)
    n = len(data)
    epos = (_LCG_A ^ kn ^ n) % kn
    out = bytearray(data)
    for i in range(n):
        out[i] ^= _EKEY[epos]
        epos = (epos * _LCG_A + _LCG_C + (i ^ n)) % kn
    return bytes(out)


def decrypt_shard_file(raw_bytes: bytes) -> dict:
    """spZip.Decrypt(byte[]) 포팅: XOR 후 ZIP 엔트리("data") 압축 해제 → JSON dict."""
    unzipped = _process_bytes(raw_bytes)
    with zipfile.ZipFile(io.BytesIO(unzipped)) as zf:
        names = zf.namelist()
        if not names:
            return {}
        text = zf.read(names[0]).decode("utf-8")
    return json.loads(text) if text else {}


def shard_key_for_level(level_id: str) -> str:
    """LevelMapProvider.GetShardKey 포팅: "level_1234" -> "levelmap_level_12"."""
    prefix, idx_str = level_id.rsplit("_", 1)
    idx = int(idx_str)
    return f"levelmap_{prefix}_{(idx - 1) // SHARD_SIZE}"


def shard_path_for_key(shard_key: str, streaming_assets_dir: Path) -> Path:
    """LevelMapProvider.GetShardPath + spBase64.MD5 포팅."""
    digest = hashlib.md5(shard_key.encode("utf-8")).hexdigest()
    return streaming_assets_dir / f"a{digest}.txt"


class ShardReader:
    """샤드 파일을 레벨 요청 시점에 지연 복호하고 캐시한다(읽기 전용)."""

    def __init__(self, streaming_assets_dir: Path):
        self._dir = streaming_assets_dir
        self._cache: dict[str, dict] = {}

    def get_level_map(self, level_id: str) -> dict | None:
        key = shard_key_for_level(level_id)
        if key not in self._cache:
            path = shard_path_for_key(key, self._dir)
            if not path.exists():
                self._cache[key] = {}
            else:
                raw = path.read_bytes()
                self._cache[key] = decrypt_shard_file(raw)
        shard = self._cache[key]
        return shard.get(level_id)


# ---------------------------------------------------------------------------
# 검사
# ---------------------------------------------------------------------------

def check_tile_key_order(raw_map: dict) -> list[str]:
    """(a) 각 레이어 tiles 키 순서 == GB row-major 정렬 순서."""
    problems = []
    raw_n = raw_map.get("layer", 0)
    try:
        n = int(raw_n)
    except (TypeError, ValueError):
        return [f"non-integer layer count: {raw_n!r}"]
    for i in range(n):
        layer = raw_map.get(f"layer_{i}")
        if not isinstance(layer, dict):
            continue
        tiles = layer.get("tiles", {})
        if not isinstance(tiles, dict) or not tiles:
            continue
        actual = list(tiles.keys())
        expected = sorted(actual, key=_tile_pos_sort_key)
        if actual != expected:
            problems.append(f"layer_{i}: tiles key order != GB sort (first diff at {_first_diff_index(actual, expected)})")
    return problems


def check_map_key_order(raw_map: dict) -> list[str]:
    """(b) 최상위 map 키 순서 == "layer", "layer_0", "layer_1", ... (클라 layerIndex 전제)."""
    raw_n = raw_map.get("layer", 0)
    try:
        n = int(raw_n)
    except (TypeError, ValueError):
        return [f"non-integer layer count: {raw_n!r}"]
    expected = ["layer"] + [f"layer_{i}" for i in range(n)]
    actual = [k for k in raw_map.keys() if k == "layer" or k.startswith("layer_")]
    if actual != expected:
        return [f"map key order {actual} != expected {expected}"]
    return []


def _first_diff_index(a: list, b: list) -> int:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b))


def scan(
    production_batch_path: Path,
    streaming_assets_dir: Path,
    start: int,
    end: int,
) -> dict:
    batch = json.loads(production_batch_path.read_text())
    levels_by_number = {}
    for item in batch["levels"]:
        num = item.get("meta", {}).get("level_number")
        if isinstance(num, int):
            levels_by_number[num] = item["level_json"]

    reader = ShardReader(streaming_assets_dir)

    rows = []
    key_order_violations = 0
    layer_order_violations = 0
    layer_continuity_violations = 0
    struct_diff_levels = []
    missing_in_shard = []
    missing_in_batch = []

    for n in range(start, end + 1):
        level_id = f"level_{n}"
        raw_map = reader.get_level_map(level_id)
        if raw_map is None:
            missing_in_shard.append(n)
            continue
        prod_level_json = levels_by_number.get(n)
        if prod_level_json is None:
            missing_in_batch.append(n)
            continue

        a_problems = check_tile_key_order(raw_map)
        b_problems = check_map_key_order(raw_map)
        cont_problems = check_layer_continuity(raw_map)

        if a_problems:
            key_order_violations += 1
        if b_problems:
            layer_order_violations += 1
        if cont_problems:
            layer_continuity_violations += 1

        shard_struct = struct_hash(canonical_map(raw_map))
        prod_struct = struct_hash(canonical_map(prod_level_json))
        struct_diff = shard_struct != prod_struct
        if struct_diff:
            struct_diff_levels.append(n)

        if a_problems or b_problems or cont_problems or struct_diff:
            rows.append({
                "level": n,
                "key_order_problems": a_problems,
                "layer_order_problems": b_problems,
                "continuity_problems": cont_problems,
                "struct_diff": struct_diff,
                "known_drift": n in KNOWN_DRIFT_LEVELS,
            })

    scanned = end - start + 1 - len(missing_in_shard) - len(missing_in_batch)
    unexpected_struct_diff = sorted(set(struct_diff_levels) - set(KNOWN_DRIFT_LEVELS))
    expected_but_same = sorted(
        n for n in KNOWN_DRIFT_LEVELS
        if start <= n <= end and n not in struct_diff_levels
    )

    return {
        "scanned": scanned,
        "range": (start, end),
        "key_order_violations": key_order_violations,
        "layer_order_violations": layer_order_violations,
        "layer_continuity_violations": layer_continuity_violations,
        "struct_diff_levels": struct_diff_levels,
        "unexpected_struct_diff": unexpected_struct_diff,
        "expected_but_same": expected_but_same,
        "missing_in_shard": missing_in_shard,
        "missing_in_batch": missing_in_batch,
        "rows": rows,
    }


def render_markdown(result: dict, production_batch_path: Path, streaming_assets_dir: Path) -> str:
    g4_ok = (
        result["key_order_violations"] == 0
        and not result["unexpected_struct_diff"]
    )
    lines = []
    lines.append("# P0-G4 샤드 스캔 결과")
    lines.append("")
    lines.append(f"- 생성: backend/scripts/pv_scan_shards.py (읽기 전용)")
    lines.append(f"- production batch: `{production_batch_path.name}`")
    lines.append(f"- 샤드 원본: `{streaming_assets_dir}`")
    lines.append(f"- 스캔 범위: level {result['range'][0]}~{result['range'][1]} ({result['scanned']}개)")
    lines.append("")
    lines.append(f"## G4 판정: {'PASS' if g4_ok else 'FAIL'}")
    lines.append("")
    lines.append(f"- (a)+(b) 키 순서 불일치: tiles 키 {result['key_order_violations']}건 / map 최상위 레이어 키 {result['layer_order_violations']}건")
    lines.append(f"- 레이어 연속성 위반: {result['layer_continuity_violations']}건")
    lines.append(f"- structHash 구조 차이(샤드 vs LIVE 3차 배치 canonical): {len(result['struct_diff_levels'])}개 → {result['struct_diff_levels']}")
    lines.append(f"- 기존 알려진 34개(32~79 구간 33 + Lv341) 중 이번 스캔과 **다른** 레벨(예상 외 차이): {result['unexpected_struct_diff'] or '없음'}")
    lines.append(f"- 기존 알려진 34개 중 이번 스캔에서 **차이 없음**으로 나온 레벨(예상과 다름): {result['expected_but_same'] or '없음'}")
    if result["missing_in_shard"]:
        lines.append(f"- 샤드에 없는 레벨: {result['missing_in_shard']}")
    if result["missing_in_batch"]:
        lines.append(f"- production 배치에 없는 레벨: {result['missing_in_batch']}")
    lines.append("")
    lines.append("## 상세 (문제 있는 레벨만)")
    lines.append("")
    lines.append("| level | tiles키순서 | map키순서 | 레이어연속성 | structDiff | 기존알려진34 |")
    lines.append("|---|---|---|---|---|---|")
    for row in result["rows"]:
        lines.append(
            "| {level} | {a} | {b} | {c} | {d} | {known} |".format(
                level=row["level"],
                a="; ".join(row["key_order_problems"]) or "OK",
                b="; ".join(row["layer_order_problems"]) or "OK",
                c="; ".join(row["continuity_problems"]) or "OK",
                d="DIFF" if row["struct_diff"] else "same",
                known="yes" if row["known_drift"] else "NEW",
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=DEFAULT_PRODUCTION_BATCH)
    parser.add_argument("--game-streaming-assets", type=Path, default=DEFAULT_GAME_STREAMING_ASSETS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--end", type=int, default=1530)
    args = parser.parse_args()

    if not args.batch.exists():
        print(f"production batch not found: {args.batch}", file=sys.stderr)
        sys.exit(1)
    if not args.game_streaming_assets.exists():
        print(f"game streaming assets dir not found: {args.game_streaming_assets}", file=sys.stderr)
        sys.exit(1)

    result = scan(args.batch, args.game_streaming_assets, args.start, args.end)
    md = render_markdown(result, args.batch, args.game_streaming_assets)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n[written] {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
