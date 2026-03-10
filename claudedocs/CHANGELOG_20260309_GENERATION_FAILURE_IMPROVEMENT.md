# 프로덕션 레벨 생성 실패율 개선 (v15.6)

**날짜**: 2026-03-09
**버전**: v15.6

## 문제 분석

프로덕션 레벨 생성 시 실패가 자주 발생하는 원인:

1. **모든 후보 API 실패**: 15개 후보 (5 attempts × 3 candidates) 모두 null 반환
2. **네트워크/타임아웃**: 동시 생성 시 서버 과부하로 API 호출 실패
3. **고정된 허용오차**: 5% 오차가 일부 난이도 범위에서 너무 엄격함

## 개선 사항

### 1. 재시도 로직 추가
- 단일 후보 생성 실패 시 1회 자동 재시도
- API 타임아웃/일시적 오류 복구 가능

```typescript
const generateOneCandidate = async (...): Promise<GenerationResult | null> => {
  try {
    return await generateLevel(params, gimmickOpts);
  } catch {
    // 1회 재시도
    try {
      return await generateLevel(params, gimmickOpts);
    } catch {
      return null;
    }
  }
};
```

### 2. 점진적 허용오차 완화
- 초반 시도 (0-2): 5% 오차 (기본)
- 중반 시도 (3-4): 7.5% 오차
- 후반 시도 (5): 10% 오차

```typescript
const currentTolerance = attempt < 3 ? BASE_TOLERANCE :
                          attempt < 5 ? BASE_TOLERANCE * 1.5 :
                          BASE_TOLERANCE * 2.0;
```

### 3. 후보 다양성 증가
- 레이어 수 변화: -1, 0, +1
- 기믹 강도 변화: 0.8x, 1.0x, 1.2x
- 다양한 파라미터로 더 넓은 난이도 범위 커버

```typescript
const layerVariations = [-1, 0, 1];
const intensityMultipliers = [0.8, 1.0, 1.2];
```

### 4. 최대 시도 횟수 증가
- `MAX_ATTEMPTS`: 5 → 6
- 총 후보 수: 15 → 18개

### 5. Best-match 폴백 개선
- 허용오차 초과해도 최선의 결과 사용 (기존 동작 유지)
- 경고 로그 추가로 모니터링 가능

```typescript
if (bestGap > BASE_TOLERANCE) {
  console.warn(`Level ${levelNumber}: Using best-match fallback (gap: ${bestGap.toFixed(1)}%)`);
}
```

## 예상 효과

| 항목 | 기존 | 개선 후 |
|------|------|---------|
| 총 후보 수 | 15개 | 18개 |
| API 실패 복구 | 없음 | 1회 재시도 |
| 허용오차 범위 | 5% 고정 | 5%→10% 점진적 |
| 후보 다양성 | 동일 파라미터 | 레이어/기믹 변화 |

## 적용 범위

1. **초기 레벨 생성** (`generateOneLevel` 함수)
2. **일괄 재생성** (`batchRegenerateCore` 함수)

## 파일 변경

- `frontend/src/components/ProductionDashboard/index.tsx`
  - 초기 생성 로직 개선 (라인 538-645)
  - 재생성 로직 개선 (라인 2869-3000)

## 테스트 결과

- TypeScript 빌드: ✅ 성공
- API 테스트: ✅ 정상 동작 (target 0.30 → actual 0.31)
