# P0-G4 샤드 스캔 결과

- 생성: backend/scripts/pv_scan_shards.py (읽기 전용)
- production batch: `batch_1789636723287_uulknmtej.json`
- 샤드 원본: `/Users/casualdev/sp_meowsgarden/Assets/StreamingAssets/GBoost`
- 스캔 범위: level 1~1530 (1530개)

## G4 판정: PASS

- (a)+(b) 키 순서 불일치: tiles 키 0건 / map 최상위 레이어 키 0건
- 레이어 연속성 위반: 0건
- structHash 구조 차이(샤드 vs LIVE 3차 배치 canonical): 1개 → [34]
- 기존 알려진 34개(32~79 구간 33 + Lv341) 중 이번 스캔과 **다른** 레벨(예상 외 차이): 없음
- 기존 알려진 34개 중 이번 스캔에서 **차이 없음**으로 나온 레벨(예상과 다름): [32, 33, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 61, 62, 63, 64, 66, 67, 68, 69, 70, 71, 73, 74, 75, 76, 77, 78, 79, 341]

## 상세 (문제 있는 레벨만)

| level | tiles키순서 | map키순서 | 레이어연속성 | structDiff | 기존알려진34 |
|---|---|---|---|---|---|
| 34 | OK | OK | OK | DIFF | yes |
