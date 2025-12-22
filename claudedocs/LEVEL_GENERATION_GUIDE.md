# 레벨 생성 도구 가이드

**날짜**: 2025-12-22
**목적**: 자동화된 벤치마크 레벨 생성 및 검증

---

## 개요

`generate_benchmark_levels.py`는 벤치마크 레벨을 자동으로 생성하고 검증하는 도구입니다.

### 주요 기능

1. **파라미터 기반 레벨 생성**: 타일 수, 타입, 레이어, 최대 이동 횟수 등을 설정하여 레벨 생성
2. **자동 검증**: 생성된 레벨을 5가지 봇으로 테스트하여 난이도 검증
3. **자동 보정**: 목표 클리어율에 맞춰 파라미터 자동 조정
4. **배치 생성**: 여러 레벨을 한 번에 생성
5. **제안 시스템**: 검증 실패 시 개선 방안 제공

---

## 사용 방법

### 기본 사용법

```bash
# 단일 EASY 레벨 생성 (검증 포함)
python3 generate_benchmark_levels.py --tier easy --count 1 --validate

# MEDIUM 레벨 5개 생성
python3 generate_benchmark_levels.py --tier medium --count 5 --validate

# HARD 레벨 생성 with 자동 보정
python3 generate_benchmark_levels.py --tier hard --count 1 --calibrate --validate

# 커스텀 파라미터로 생성
python3 generate_benchmark_levels.py --tier medium --count 1 --tile-types 6 --layers 3 --validate
```

### 명령줄 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--tier` | 난이도 티어 (easy/medium/hard/expert/impossible) | 필수 |
| `--count` | 생성할 레벨 수 | 1 |
| `--start-id` | 시작 레벨 ID (예: hard_01) | 자동 생성 |
| `--tile-types` | 타일 종류 수 (3-12) | 티어별 기본값 |
| `--layers` | 레이어 수 (1-4) | 티어별 기본값 |
| `--validate` | 생성 후 검증 실행 | false |
| `--calibrate` | 자동 보정 활성화 | false |
| `--output` | 출력 파일명 | generated_levels.json |
| `--seed` | 랜덤 시드 | 42 |

---

## 난이도별 기본 파라미터

### EASY Tier
```yaml
tile_types: 4
tile_count: 36
layers: 1
max_moves: 50
effect_tiles: 없음

target_clear_rates:
  novice: 95%
  casual: 98%
  average: 99%
  expert: 100%
  optimal: 100%
```

### MEDIUM Tier
```yaml
tile_types: 5
tile_count: 45
layers: 2
max_moves: 50
effect_tiles: 없음

target_clear_rates:
  novice: 30%
  casual: 55%
  average: 75%
  expert: 90%
  optimal: 98%
```

### HARD Tier
```yaml
tile_types: 6
tile_count: 60
layers: 3
max_moves: 45
effect_tiles: 없음

target_clear_rates:
  novice: 10%
  casual: 25%
  average: 50%
  expert: 80%
  optimal: 95%
```

### EXPERT Tier
```yaml
tile_types: 10
tile_count: 120
layers: 4
max_moves: 30
effect_tiles: ICE, GRASS, LINK

target_clear_rates:
  novice: 2%
  casual: 10%
  average: 30%
  expert: 65%
  optimal: 90%
```

### IMPOSSIBLE Tier
```yaml
tile_types: 12
tile_count: 150
layers: 4
max_moves: 25
effect_tiles: 많은 ICE, GRASS, LINK

target_clear_rates:
  novice: 0%
  casual: 2%
  average: 10%
  expert: 40%
  optimal: 75%
```

---

## 검증 시스템

### 검증 기준

생성된 레벨은 다음 기준으로 검증됩니다:

- **PASS**: 모든 봇의 편차가 ±15% 이내
- **WARN**: 일부 봇의 편차가 15-22.5% 범위
- **FAIL**: 봇의 편차가 22.5% 초과

### 검증 출력 예시

```
Validation Results:
✅ novice  : Actual 93.0%, Expected 95.0%, Deviation  2.0%
✅ casual  : Actual 99.0%, Expected 98.0%, Deviation  1.0%
✅ average : Actual 100.0%, Expected 99.0%, Deviation  1.0%
✅ expert  : Actual 100.0%, Expected 100.0%, Deviation  0.0%
✅ optimal : Actual 100.0%, Expected 100.0%, Deviation  0.0%

✅ Level easy_01: VALIDATION PASSED
```

### 제안 시스템

검증 실패 시 자동으로 개선 방안을 제공합니다:

**레벨이 너무 쉬운 경우:**
- 타일 수 증가 (20% 증가 권장)
- 타일 종류 1-2개 추가
- max_moves 20-30% 감소
- 효과 타일 추가 (ICE, GRASS, LINK)

**레벨이 너무 어려운 경우:**
- 타일 수 감소 (20% 감소 권장)
- 타일 종류 1-2개 제거
- max_moves 20-30% 증가
- 효과 타일 제거 또는 감소

---

## 자동 보정 (Auto-Calibration)

`--calibrate` 옵션을 사용하면 목표 클리어율에 맞춰 파라미터를 자동으로 조정합니다.

### 작동 방식

1. 초기 파라미터로 레벨 생성
2. 50회 반복 테스트로 실제 클리어율 측정
3. 목표와의 편차 계산
4. 파라미터 자동 조정:
   - 너무 쉬움 → 타일 증가, 타입 증가, 이동 감소
   - 너무 어려움 → 타일 감소, 타입 감소, 이동 증가
5. 최대 10회 반복하여 최적 파라미터 탐색
6. 편차 15% 이내 달성 시 조기 종료

### 사용 예시

```bash
# MEDIUM 레벨 3개를 자동 보정하여 생성
python3 generate_benchmark_levels.py --tier medium --count 3 --calibrate --validate --output calibrated_medium.json

# 출력:
🔧 Auto-calibrating level: medium_01
  Iteration 1: avg deviation = 35.2%
  Iteration 2: avg deviation = 22.1%
  Iteration 3: avg deviation = 14.5%
  ✅ Calibration successful: 14.5% deviation
```

---

## 출력 파일 형식

생성된 레벨은 JSON 형식으로 저장됩니다:

```json
{
  "generator_version": "1.0",
  "generation_date": "2025-12-22",
  "seed": 42,
  "levels": [
    {
      "config": {
        "tier": "medium",
        "level_id": "medium_01",
        "name": "Generated MEDIUM #1",
        "description": "Auto-generated medium level with 5 tile types",
        "tags": ["generated", "2_layer"],
        "tile_types": 5,
        "tile_count": 45,
        "layers": 2,
        "max_moves": 50,
        "ice_tiles": 0,
        "grass_tiles": 0,
        "link_tiles": 0,
        "expected_clear_rates": {
          "novice": 0.30,
          "casual": 0.55,
          "average": 0.75,
          "expert": 0.90,
          "optimal": 0.98
        },
        "seed": 42,
        "grid_cols": 9,
        "grid_rows": 9
      },
      "level_json": {
        "layer": 2,
        "randSeed": 42,
        "useTileCount": 5,
        "goals": {
          "t1": 9,
          "t2": 9,
          "t3": 9,
          "t4": 9,
          "t5": 9
        },
        "max_moves": 50,
        "layer_0": {
          "tiles": {
            "3_5": ["t2"],
            "7_4": ["t5"],
            ...
          },
          "col": 9
        },
        "layer_1": {
          "tiles": {
            "2_8": ["t1"],
            "9_3": ["t4"],
            ...
          },
          "col": 9
        }
      },
      "actual_clear_rates": {
        "novice": 0.77,
        "casual": 0.97,
        "average": 1.00,
        "expert": 1.00,
        "optimal": 1.00
      },
      "validation_status": "fail",
      "suggestions": [
        "Level too easy - increase difficulty:",
        "  - Increase tile count by 9 tiles",
        "  - Add 1-2 more tile types",
        "  - Reduce max_moves to 40",
        "  - Add effect tiles (ICE, GRASS, LINK)"
      ]
    }
  ]
}
```

---

## 실전 워크플로우

### 1. 새로운 MEDIUM 티어 레벨 10개 생성

```bash
# Step 1: 자동 보정 없이 생성하여 기본 파라미터 테스트
python3 generate_benchmark_levels.py --tier medium --count 10 --validate --output new_medium_levels.json

# Step 2: 결과 확인 후 필요시 파라미터 조정
# 너무 쉬우면: --tile-types 6 --layers 3 추가
# 너무 어려우면: --tile-types 4 --max-moves 60 추가

# Step 3: 자동 보정 활성화하여 최종 생성
python3 generate_benchmark_levels.py --tier medium --count 10 --calibrate --validate --output final_medium_levels.json
```

### 2. HARD 티어 레벨 생성 (첫 구현)

```bash
# Step 1: 단일 레벨로 파라미터 테스트
python3 generate_benchmark_levels.py --tier hard --count 1 --validate --output test_hard.json

# Step 2: 제안 사항 확인 및 수동 조정
python3 generate_benchmark_levels.py --tier hard --count 1 --tile-types 7 --tile-count 75 --max-moves 40 --validate

# Step 3: 자동 보정으로 10개 생성
python3 generate_benchmark_levels.py --tier hard --count 10 --calibrate --validate --output hard_tier_levels.json
```

### 3. 생성된 레벨을 벤치마크 시스템에 통합

```bash
# Step 1: 생성된 레벨 검증
python3 validate_level_difficulty.py hard --iterations 100 --tolerance 15

# Step 2: 벤치마크 모델에 추가
# backend/app/models/benchmark_level.py 파일에 레벨 정의 추가

# Step 3: API 테스트
./test_benchmark_api.sh

# Step 4: 전체 벤치마크 시스템 테스트
python3 test_benchmark.py
```

---

## 파라미터 튜닝 가이드

### 난이도 조절 원칙

1. **타일 수 (tile_count)**
   - 9의 배수여야 함 (3-match 게임)
   - 증가 → 난이도 상승
   - 권장 범위: 36-150

2. **타일 종류 (tile_types)**
   - 증가 → 난이도 상승
   - 권장 범위: 3-12
   - 타일 수 / 타일 종류 = 매칭 기회

3. **레이어 (layers)**
   - 증가 → 난이도 상승 (블로킹 증가)
   - 권장 범위: 1-4

4. **최대 이동 (max_moves)**
   - 감소 → 난이도 상승
   - 권장 범위: 10-60

5. **효과 타일 (effect_tiles)**
   - ICE: 1회 추가 선택 필요
   - GRASS: 위에 있는 타일부터 제거 필요
   - LINK: 연결된 타일 동시 제거 필요
   - 추가 → 난이도 상승

### 난이도별 권장 범위

| 티어 | 타일 수 | 타입 | 레이어 | 이동 | 효과 |
|------|---------|------|--------|------|------|
| EASY | 36-45 | 3-5 | 1 | 50-60 | 없음 |
| MEDIUM | 45-60 | 5-6 | 2 | 40-50 | 선택 |
| HARD | 60-90 | 6-8 | 2-3 | 35-45 | 적음 |
| EXPERT | 90-120 | 8-10 | 3-4 | 25-35 | 보통 |
| IMPOSSIBLE | 120-150 | 10-12 | 4 | 20-30 | 많음 |

---

## 통합 자동화 파이프라인

3가지 자동화 도구를 조합한 완전 자동화 워크플로우:

### 도구 1: Level Generation (이 문서)
```bash
python3 generate_benchmark_levels.py --tier medium --count 10 --calibrate --validate
```

### 도구 2: Level Validation
```bash
python3 validate_level_difficulty.py medium --iterations 100 --tolerance 15 --suggest
```

### 도구 3: Integrated Dashboard API
```bash
# 대시보드 요약 조회
curl http://localhost:8000/api/simulate/benchmark/dashboard/summary

# 특정 레벨 검증
curl -X POST http://localhost:8000/api/simulate/benchmark/validate/medium_01
```

### 완전 자동화 스크립트 예시

```bash
#!/bin/bash
# generate_and_validate.sh

TIER=$1
COUNT=${2:-10}

echo "1. Generating $COUNT $TIER levels..."
python3 generate_benchmark_levels.py --tier $TIER --count $COUNT --calibrate --validate --output ${TIER}_generated.json

echo "2. Validating generated levels..."
python3 validate_level_difficulty.py $TIER --iterations 200 --tolerance 15 --suggest

echo "3. Testing API integration..."
./test_benchmark_api.sh

echo "4. Dashboard summary:"
curl -s http://localhost:8000/api/simulate/benchmark/dashboard/summary | python3 -m json.tool

echo "✅ Complete! Check ${TIER}_generated.json for results"
```

사용:
```bash
chmod +x generate_and_validate.sh
./generate_and_validate.sh medium 10
```

---

## 문제 해결

### Q: 생성된 레벨의 클리어율이 0%입니다
**A**: 타일 수가 너무 많거나 max_moves가 너무 적습니다. `--tile-count`를 줄이거나 `--max-moves`를 늘려보세요.

### Q: 모든 봇이 100% 클리어합니다
**A**: 레벨이 너무 쉽습니다. `--tile-types`를 늘리거나 `--layers`를 추가하세요.

### Q: 자동 보정이 실패합니다
**A**: 초기 파라미터가 너무 극단적일 수 있습니다. 수동으로 파라미터를 조정한 후 보정을 시도하세요.

### Q: 생성된 레벨에 타일이 부족합니다
**A**: 버그 수정됨 (2025-12-22). 최신 버전 사용 확인.

---

## 관련 파일

- **생성 도구**: [generate_benchmark_levels.py](../generate_benchmark_levels.py)
- **검증 도구**: [validate_level_difficulty.py](../validate_level_difficulty.py)
- **API 라우터**: [backend/app/api/routes/simulate.py](../backend/app/api/routes/simulate.py)
- **벤치마크 모델**: [backend/app/models/benchmark_level.py](../backend/app/models/benchmark_level.py)
- **API 가이드**: [BENCHMARK_API_GUIDE.md](BENCHMARK_API_GUIDE.md)

---

**작성자**: Claude Sonnet 4.5
**문서 버전**: 1.0
**마지막 업데이트**: 2025-12-22
