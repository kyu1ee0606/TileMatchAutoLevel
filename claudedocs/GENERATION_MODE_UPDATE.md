# 생성 모드 업데이트 (v15.3)

## 개요
레벨 생성 시 "빠른 생성"과 "패턴 생성" 모드를 명확히 구분하여 선택할 수 있도록 UI 개선.

## 변경 사항

### 1. 생성 모드 타입 추가
**파일**: `frontend/src/types/levelSet.ts`

```typescript
export type GenerationMode = 'quick' | 'pattern';
```

- `quick`: 빠른 생성 - 각 레이어가 독립적인 패턴으로 생성
- `pattern`: 패턴 생성 - 모든 레이어가 동일한 타일 위치 공유

### 2. 레벨 세트 생성기 UI 추가
**파일**: `frontend/src/components/LevelSetGenerator/LevelSetConfig.tsx`

- 세트 이름 아래에 생성 모드 선택 UI 추가
- ⚡ **빠른 생성**: 레이어별 다른 패턴으로 빠르게 생성
- ✨ **패턴 생성**: 모든 레이어가 동일한 타일 위치 공유 (기본값)

### 3. 프로덕션 대시보드 재생성 모달 개선
**파일**: `frontend/src/components/ProductionDashboard/index.tsx`

- 개별 레벨 재생성 모달에 생성 모드 선택 추가
- `regenGenerationMode` 상태 추가
- 빠른 생성 모드: `pattern_index = undefined`
- 패턴 생성 모드: 선택한 `pattern_index` 사용

### 4. 패턴 모양 보존 수정 (핵심)
**파일**: `backend/app/core/generator.py`

**문제점**:
- 기존에는 3의 배수를 맞추기 위해 타일을 추가/제거
- 이로 인해 템플릿에서 정의한 패턴 모양이 변형됨

**해결**:
- 패턴 모드에서 3의 배수 패딩/제거 로직 완전 제거
- 템플릿 모양을 100% 그대로 유지
- 타일 타입 분배는 게임 클라이언트에서 처리

```python
# 변경 전: 인접 위치에 타일 추가
positions_to_add = 3 - remainder
for pos in master_positions:
    # 인접 위치 찾아서 추가... (패턴 모양 변형)

# 변경 후: 원본 패턴 그대로 유지
if remainder != 0:
    _logger.info(f"[PATTERN_SHAPE] Preserving exact shape...")
```

## 테스트 결과

| 패턴 | 템플릿 수 | 실제 생성 | 결과 |
|------|----------|----------|------|
| oval | 52 | 52 | ✅ 완벽 일치 |
| cross | 28 | 28 | ✅ 완벽 일치 |
| concentric_diamond | 20 | 20 | ✅ 완벽 일치 |
| letter_H | 40 | 40 | ✅ 완벽 일치 |

## 동작 방식

### 빠른 생성 모드 (`quick`)
- `pattern_index` 미사용
- 각 레이어가 독립적인 패턴/위치
- 기존 자동 생성과 동일

### 패턴 생성 모드 (`pattern`)
- `pattern_index` 지정
- 모든 레이어가 동일한 타일 위치 공유
- 템플릿 모양 100% 유지

## 관련 문서
- [LEVEL_CONFIG_TABLE.md](./LEVEL_CONFIG_TABLE.md) - 레벨 설정 통합 테이블
