# CHANGELOG: useTileCount 버그 수정

**날짜**: 2026-03-04
**버전**: v15.2
**작성자**: Claude

## 문제 요약

프로덕션 레벨 재생성 시 `useTileCount`가 레벨 번호에 맞지 않게 설정되는 문제 발견.

### 증상
- 레벨 1259 재생성 결과: `useTileCount: 3`
- 예상값: `useTileCount: 11` (Level 1126-1500 범위)
- 타일 타입이 t0, t1, t2, t3 혼합되어 있음

### 영향
- 고레벨에서 타일 종류가 부족하여 난이도 불균형
- 봇 시뮬레이션 결과와 실제 플레이 경험 불일치

---

## 근본 원인 분석

### 문제 위치
`backend/app/api/routes/generate.py` - `/api/generate` 엔드포인트의 fallback 로직

### 문제 코드 (수정 전)
```python
# Line 1003 (attempt >= 1)
tile_types=params.tile_types[:4] if params.tile_types else ["t1", "t2", "t3", "t4"],

# Line 1020 (attempt >= 2)
tile_types=["t1", "t2", "t3"],  # Minimum tile types
```

### 발생 메커니즘
1. 프론트엔드에서 `tile_types: undefined`로 요청 (백엔드 자동 선택 의도)
2. 첫 번째 생성 시도 실패
3. Fallback 로직에서 `tile_types = ["t1", "t2", "t3"]` 고정값 설정
4. `_create_base_level()`에서 `uses_t0 = False` (t0가 없으므로)
5. `useTileCount = len(valid_tile_types) = 3`으로 설정

### 정상 동작 (수정 후)
1. `tile_types = None` 유지
2. `_create_base_level()`에서 `get_tile_types_for_level(level_number)` 호출
3. t0 모드 활성화 → `get_use_tile_count_for_level(level_number)` 호출
4. 레벨 1259 → `useTileCount = 11` 정상 설정

---

## 수정 내용

### 1. 백엔드 수정

**파일**: `backend/app/api/routes/generate.py`

```python
# 수정 후 (Line 997-1028)
if attempt >= 1:
    # CRITICAL: Keep tile_types as None to allow level_number-based auto-selection
    params = GenerationParams(
        ...
        tile_types=None,  # Let level_number-based auto-selection work
        ...
        level_number=request.level_number,
    )

if attempt >= 2:
    # CRITICAL: Keep tile_types as None for proper useTileCount
    params = GenerationParams(
        ...
        tile_types=None,  # Let level_number-based auto-selection work
        ...
        level_number=request.level_number,
    )
```

### 2. 프론트엔드 UI 추가

**파일**: `frontend/src/components/ProductionDashboard/index.tsx`

#### 유틸리티 함수 추가
```typescript
// 레벨 번호 + 난이도 기반 useTileCount 허용 범위 계산
// 두 가지 생성 방식 모두 허용:
// 1. /api/generate: 레벨 번호 기반 고정값
// 2. /api/generate/validated: 난이도 등급 기반 범위
function getExpectedUseTileCountRange(levelNumber: number, targetDifficulty?: number): {
  min: number;
  max: number;
  levelBased: number;
}

// useTileCount 검증 (범위 기반)
function validateUseTileCount(levelNumber: number, useTileCount: number, targetDifficulty?: number): {
  isValid: boolean;
  range: { min: number; max: number };
  levelBased: number;
}

// 잘못된 레벨 탐지 (명백한 오류만: 3 이하 또는 범위 벗어남)
function findLevelsWithWrongTileCount(levels: ProductionLevel[]): ProductionLevel[]
```

#### 타일 종류 수 허용 범위

**레벨 번호 기반 (get_gboost_style_layer_config)**:
| 레벨 범위 | 고정값 |
|-----------|--------|
| 1-10 | 4 |
| 11-30 | 5 |
| 31-60 | 7 |
| 61-225 | 8 |
| 226-600 | 9 |
| 601-1125 | 10 |
| 1126-1500 | 11 |
| 1501+ | 12 |

**난이도 등급 기반 (TILE_RANGES)**:
| 등급 | 범위 (min-max) |
|------|----------------|
| S (0~20%) | 5-7 |
| A (20~35%) | 6-8 |
| B (35~50%) | 6-10 |
| C (50~70%) | 7-10 |
| D (70~85%) | 7-11 |
| E (85~100%) | 8-12 |

#### Overview 탭 UI 추가
- 노란색 경고 박스: 잘못된 useTileCount 레벨 수 표시
- 각 레벨 태그: 현재값 → 예상값 (예: `Lv.1259 (3→11)`)
- "일괄 재생성" 버튼: 감지된 모든 레벨 재생성

---

## 레벨별 타일 종류 수 기준표

| 레벨 범위 | useTileCount | 설명 |
|-----------|--------------|------|
| 1-10 | 4 | Tutorial |
| 11-30 | 5 | Early game |
| 31-60 | 7 | Early-mid game |
| 61-100 | 8 | Mid game |
| 101-225 | 8 | Mid-late game |
| 226-600 | 9 | Standard |
| 601-1125 | 10 | Advanced (기준선) |
| 1126-1500 | 11 | Expert |
| 1501+ | 12 | Master |

---

## 톱니바퀴 패턴과 타일 모드

### SAWTOOTH_PATTERN_10
```
위치: [0,   1,    2,    3,    4,    5,    6,    7,    8,    9]
난이도: [0.20, 0.52, 0.55, 0.35, 0.55, 0.75, 0.55, 0.50, 0.55, 0.85]
```

### 타일 모드 선택
- **최저 난이도 위치 (0, 3, 7)**: 고정 타일 사용 (`["t1", "t2", ...]`)
- **나머지 위치 (1, 2, 4, 5, 6, 8, 9)**: t0 모드 사용 (`["t0"]`)

### t0 모드 동작
1. 레벨 JSON에 `"t0"` 타일로 저장
2. 클라이언트에서 `randSeed`와 `useTileCount` 기반으로 실제 타일 결정
3. 같은 레벨을 여러 번 플레이해도 동일한 타일 배치

---

## 테스트 방법

### 1. 기존 잘못된 레벨 확인
1. 프로덕션 대시보드 → Overview 탭
2. 노란색 경고 박스 확인
3. 잘못된 레벨 목록 및 현재값→예상값 확인

### 2. 일괄 재생성
1. "일괄 재생성" 버튼 클릭
2. 진행 상황 확인 (x/n 표시)
3. 완료 후 경고 박스 사라짐 확인

### 3. 새 레벨 생성 검증
```bash
# 레벨 1259 생성 테스트
curl -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "target_difficulty": 0.85,
    "grid_size": [7, 7],
    "max_layers": 5,
    "level_number": 1259
  }' | jq '.level_json.useTileCount'
# 예상 결과: 11
```

---

## 관련 파일

- `backend/app/api/routes/generate.py` - API 엔드포인트
- `backend/app/core/generator.py` - 레벨 생성기 (get_use_tile_count_for_level)
- `frontend/src/components/ProductionDashboard/index.tsx` - 대시보드 UI
- `backend/app/models/leveling_config.py` - SAWTOOTH_PATTERN_10 정의

---

## 향후 고려사항

1. **로깅 강화**: Fallback 발생 시 경고 로그 추가
2. **모니터링**: useTileCount 불일치 자동 감지 메트릭
3. **테스트**: 레벨 번호별 useTileCount 단위 테스트 추가
