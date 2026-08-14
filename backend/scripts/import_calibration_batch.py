"""[난이도 캘리브레이션] build_calibration_set.py 산출물을 **프로덕션 배치**로 등록한다.

플레이해서 체감을 기록해야 하는데, 파일로만 있으면 플레이할 수단이 없다. 프로덕션 배치로
올리면 기존 수동 플레이 탭·체감 난이도 입력(perceivedDifficulty)을 그대로 쓸 수 있다.

레벨 번호는 **버킷 순서대로 1..N** 을 붙인다(쉬운 것부터가 아니라 낮은 클리어율부터).
meta.target_difficulty 는 `1 - 예측클리어율` 로 둔다 — 이 배치는 난이도 곡선을 따르는
프로덕션이 아니라 '눈금 확인용'이라 레벨번호와 목표난이도를 연동하지 않는다.
"""
import argparse, json, time, urllib.request

API = "http://localhost:8000/api"


def put(path, body, timeout=600):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="PUT")
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="/tmp/calibration_set.json")
    ap.add_argument("--name", default=None)
    # 레벨 번호 시작값. 기믹 언락 규칙(craft 11, stack 21, ... teleport 441)을 전부 통과하는
    # 구간이어야 한다 — 1부터 붙이면 원본 레벨의 기믹이 전부 '언락 전 사용'으로 규칙 위반이 된다
    # (실측: Lv1~12 로 등록 시 12개 중 10개가 rule_flagged).
    ap.add_argument("--start", type=int, default=501)
    args = ap.parse_args()

    recs = json.load(open(args.src, encoding="utf-8"))
    recs.sort(key=lambda r: r["bucket"])
    now_ms = int(time.time() * 1000)
    bid = f"batch_{now_ms}_calib"
    name = args.name or f"난이도 캘리브레이션 {len(recs)}개 - {time.strftime('%Y-%m-%d %H:%M')}"
    iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    levels = []
    for i, r in enumerate(recs, args.start):
        p = float(r["predicted_clear_rate"])
        lj = dict(r["level_json"])
        levels.append({
            "meta": {
                "level_number": i,
                "set_index": 0, "local_index": i - args.start,
                # 이 배치는 '눈금 확인'이 목적 — 레벨번호와 목표난이도를 연동하지 않는다.
                "target_difficulty": round(1.0 - p, 4),
                "actual_difficulty": round(1.0 - p, 4),
                "grade": "C",
                "status": "generated",
                "generated_at": iso, "status_updated_at": iso,
                "pattern_type": "aesthetic", "pattern_index": -1,
                "validation_attempts": 0,
                "playtest_required": True, "playtest_priority": i - args.start + 1, "playtest_results": [],
                # 측정값 보존 — 플레이 후 체감과 대조할 기준선
                "verification_method": "rl", "verified": True,
                "predicted_clear_rate": p,
                "rl_classification": r.get("classification"),
                # 캘리브레이션 표식(플레이 화면에서 어떤 버킷인지 알아야 한다)
                "calibration_bucket": r["range"],
                "calibration_use_tile_count": r["use_tile_count"],
                "calibration_gimmick_intensity": r["gimmick_intensity"],
            },
            "level_json": lj,
        })

    body = {
        "batch_id": bid,
        "batch": {
            "id": bid, "name": name,
            "total_levels": len(levels), "levels_per_set": len(levels), "total_sets": 1,
            "generated_count": len(levels), "playtest_count": 0,
            "approved_count": 0, "rejected_count": 0, "exported_count": 0,
            "difficulty_start": 0.0, "difficulty_end": 1.0, "use_sawtooth": False,
            "created_at": iso, "updated_at": iso,
        },
        "levels": levels,
        "base_version": None,      # 신규 생성 — 버전 검사 생략
    }
    res = put(f"/production/batches/{bid}", body)
    print(f"등록 완료: {bid}")
    print(f"  이름: {name}")
    print(f"  레벨 {len(levels)}개 (Lv{args.start} = 가장 낮은 클리어율 버킷)")
    for l in levels:
        m = l["meta"]
        print(f"    Lv{m['level_number']:<3} {m['calibration_bucket']:<10} "
              f"RL {m['predicted_clear_rate']:.3f}  V={m['calibration_use_tile_count']} "
              f"기믹={m['calibration_gimmick_intensity']}")
    print(f"  서버 응답: {res}")


if __name__ == "__main__":
    main()
