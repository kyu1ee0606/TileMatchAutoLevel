"""[난이도 캘리브레이션] RL 예측 클리어율 5% 간격 버킷을 채우는 레벨 세트를 만든다.

왜 필요한가:
  순차검증 통과/미달은 RL 봇 시뮬 클리어율로 판정한다. 그런데 이 눈금이 **사람 체감과
  맞는지 한 번도 검증된 적이 없다**. 실측에서 RL 0.000 인 레벨을 A* 가 노드 108개 만에
  풀어버렸다(Lv710) — 봇이 약한 것인지, 레벨이 정말 극악한 것인지 구분이 안 된다.
  5%~100% 를 고르게 덮는 레벨을 만들어 직접 플레이해보면 그 답이 나온다.

방법:
  기준 레벨 하나를 잡고 **색 종류(V) × 기믹 강도** 를 스윕한다. 이 둘이 난이도 지배 인자다
  (실측 Lv710: 12색 0.000 / 9색 0.030 / 7색 0.171 / 6색 0.549 / 5색 0.980).
  각 조합을 RL 측정해 5% 버킷에 넣고, 버킷당 1개씩만 채택한다.

산출: JSON 배열 [{bucket, predicted_clear_rate, use_tile_count, intensity, level_json}, ...]
     프론트에서 배치로 임포트해 수동 플레이 → perceivedDifficulty 기록.
"""
import argparse, json, sys, urllib.request

API = "http://localhost:8000/api"


def post(path, body, timeout=900):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def bucket_of(p):
    """0.0~1.0 → 5% 버킷 인덱스(0=0~5%, 19=95~100%). 상한 1.0 은 마지막 버킷."""
    return min(19, int(p * 20))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="기준 레벨을 가져올 배치 id")
    ap.add_argument("--level", type=int, required=True, help="기준 레벨 번호")
    ap.add_argument("--out", default="/tmp/calibration_set.json")
    ap.add_argument("--colors", default="3,4,5,6,7,8,9,10,11,12,13",
                    help="스윕할 색 종류 수(쉼표)")
    ap.add_argument("--intensity", default="0,0.25,0.5,0.75,1.0",
                    help="스윕할 기믹 강도(쉼표)")
    args = ap.parse_args()

    batch = json.load(urllib.request.urlopen(f"{API}/production/batches/{args.batch}", timeout=600))
    src = next((l for l in batch["levels"] if l["meta"]["level_number"] == args.level), None)
    if src is None:
        sys.exit(f"배치에 Lv{args.level} 없음")
    base_json, base_meta = src["level_json"], src["meta"]
    td = base_meta.get("target_difficulty")
    print(f"기준 Lv{args.level}  V={base_json.get('useTileCount')}  "
          f"층={base_json.get('layer')}  target_difficulty={td}", flush=True)

    colors = [int(x) for x in args.colors.split(",")]
    intensities = [float(x) for x in args.intensity.split(",")]

    found = {}     # bucket -> record
    tried = 0
    # 쉬운 쪽(색 적음)부터 돌면 버킷이 위에서부터 채워져 진행 상황이 눈에 보인다.
    for v in colors:
        for inten in intensities:
            if len(found) >= 20:
                break
            tried += 1
            lj = base_json
            # 색 종류 조절. **enforce_limit=False 로 ±2 제한을 끈다** — 캘리브레이션은
            # 난이도 전 구간(0~100%)을 덮는 게 목적이라 제한이 걸리면 한 지점에 뭉친다
            # (실측: 끄지 않으면 V=3~13 요청이 전부 10으로 클램프돼 55회 시도에 1버킷만 채워짐).
            try:
                lj = post("/tune/tilecount", {"level_json": lj, "tile_count": v,
                                              "evaluate": False, "enforce_limit": False})["best_level_json"]
            except Exception as e:  # noqa: BLE001
                print(f"  V={v} 색 조절 실패: {e}", flush=True)
                continue
            if inten is not None:
                try:
                    lj = post("/tune/gimmick", {"level_json": lj, "level_number": args.level,
                                                "intensity": inten, "evaluate": False})["best_level_json"]
                except Exception as e:  # noqa: BLE001
                    print(f"  V={v} int={inten} 기믹 조절 실패: {e}", flush=True)
                    continue
            try:
                rl = post("/rl-sim/level", {"level_json": lj, "target_difficulty": td})
            except Exception as e:  # noqa: BLE001
                print(f"  V={v} int={inten} 측정 실패: {e}", flush=True)
                continue
            p = float(rl.get("predicted_clear_rate") or 0.0)
            b = bucket_of(p)
            mark = ""
            if b not in found:
                found[b] = {"bucket": b, "range": f"{b*5}~{(b+1)*5}%",
                            "predicted_clear_rate": round(p, 4),
                            "classification": rl.get("classification"),
                            "use_tile_count": v, "gimmick_intensity": inten,
                            "level_json": lj}
                mark = f"  ← 버킷 {b*5}~{(b+1)*5}% 채움 ({len(found)}/20)"
            print(f"  V={v:>2} int={inten:<4} → {p:.3f} {rl.get('classification'):<18}{mark}", flush=True)

    out = [found[b] for b in sorted(found)]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"\n시도 {tried}회 · 확보 {len(out)}/20 버킷 → {args.out}")
    print("빈 버킷:", [f"{b*5}~{(b+1)*5}%" for b in range(20) if b not in found])


if __name__ == "__main__":
    main()
