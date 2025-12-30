# TileMatchAutoLevel - TODO 리스트

**최종 업데이트**: 2025-12-30
**프로젝트 버전**: MVP + 레벨 생성 자동화

---

## 작업 상태 범례

- 대기 중 - 아직 시작 안 함
- 진행 중 - 현재 작업 중
- 완료 - 작업 완료
- 취소/보류 - 작업 취소 또는 보류

---

## 작업 유형 태그

| 태그 | 설명 |
|------|------|
| `[백엔드]` | Python/FastAPI 백엔드 작업 |
| `[프론트엔드]` | React/TypeScript 프론트엔드 작업 |
| `[자동화]` | CLI 도구 및 자동화 스크립트 |
| `[API]` | REST API 엔드포인트 |
| `[UI]` | 사용자 인터페이스 |
| `[기믹]` | 게임 기믹/장애물 관련 |
| `[문서]` | 문서화 작업 |
| `[테스트]` | 테스트 코드 작성 |
| `[버그]` | 버그 수정 |
| `[개선]` | 기능 개선 |

---

## 병렬 작업 규칙 (필독)

**다중 세션 작업 시 충돌 방지를 위한 규칙:**

1. **작업 시작 즉시 상태 변경**: 작업을 시작하면 **즉시** `대기 중` → `진행 중`으로 변경하고 담당자 기입
2. **담당자 명시**: `**담당자**: Claude-세션ID` 형식으로 기입
3. **작업 중인 항목 건드리지 않기**: `진행 중` 상태인 작업은 다른 세션에서 수정 금지
4. **완료 즉시 상태 변경**: 작업 완료 시 바로 `진행 중` → `완료`로 변경하고 완료 섹션으로 이동
5. **파일 수정 전 확인**: 같은 파일을 수정하는 작업이 진행 중인지 확인

**충돌 발생 시:**
- 먼저 시작한 세션이 우선권 가짐
- 충돌 발견 시 해당 작업 중단하고 다른 작업 선택

---

## 우선순위

### 높음 (High Priority)

---

#### 대기 중 [기믹] HARD 티어 레벨 구현
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `backend/app/models/benchmark_level.py`, `generate_benchmark_levels.py`

**작업 내용**:
HARD 티어 10개 레벨 생성 및 등록

**목표 클리어율**:
- Novice: 10%
- Casual: 25%
- Average: 50%
- Expert: 80%
- Optimal: 95%

**체크리스트**:
- [ ] generate_benchmark_levels.py로 HARD 티어 레벨 10개 생성
- [ ] 자동 보정(calibration)으로 목표 클리어율 달성
- [ ] 100회 반복 검증 통과 확인
- [ ] benchmark_level.py에 레벨 등록
- [ ] API 테스트 및 프론트엔드 연동 확인

**실행 프롬프트**:
```bash
python3 generate_benchmark_levels.py --tier hard --count 10 --calibrate --validate --output hard_tier.json
```

---

#### 대기 중 [기믹] MEDIUM 티어 재설계
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `backend/app/models/benchmark_level.py`

**문제 요약**:
현재 MEDIUM 티어가 너무 쉬움 (98.9-100% 클리어율)

**목표 클리어율**:
- Novice: 30%
- Casual: 55%
- Average: 75%
- Expert: 90%
- Optimal: 98%

**체크리스트**:
- [ ] 현재 MEDIUM 레벨 분석 및 문제점 파악
- [ ] generate_benchmark_levels.py로 새 레벨 생성
- [ ] 자동 보정으로 목표 클리어율 달성
- [ ] 기존 레벨 교체
- [ ] 검증 및 테스트

**실행 프롬프트**:
```bash
python3 generate_benchmark_levels.py --tier medium --count 10 --calibrate --validate --output redesigned_medium.json
```

---

#### 대기 중 [프론트엔드] 봇 시뮬레이션 뷰어 개선
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `frontend/src/components/SimulationViewer/BotTileGrid.tsx`

**현재 상태**:
BotTileGrid.tsx 파일이 수정됨 (git status에서 확인)

**요구 사항**:
- [ ] 현재 수정 내용 확인 및 완성
- [ ] 타일 시각화 개선
- [ ] 애니메이션 안정화
- [ ] 봇 이동 경로 표시 개선

---

### 중간 (Medium Priority)

#### 대기 중 [프론트엔드] 벤치마크 대시보드 UI
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `frontend/src/components/`

**작업 내용**:
벤치마크 시스템 전체 현황을 한눈에 볼 수 있는 대시보드 UI 구현

**체크리스트**:
- [ ] 티어별 레벨 개수 및 상태 표시
- [ ] 클리어율 통계 차트
- [ ] 레벨 검증 결과 표시
- [ ] 티어 선택 및 레벨 상세 보기

---

#### 대기 중 [기믹] EXPERT 티어 구현
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `backend/app/models/benchmark_level.py`

**목표 클리어율**:
- Novice: 2%
- Casual: 10%
- Average: 30%
- Expert: 65%
- Optimal: 90%

**체크리스트**:
- [ ] HARD 티어 완료 후 진행
- [ ] 10개 레벨 생성 및 검증
- [ ] benchmark_level.py에 등록

---

#### 대기 중 [기믹] IMPOSSIBLE 티어 구현
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `backend/app/models/benchmark_level.py`

**목표 클리어율**:
- Novice: 0%
- Casual: 2%
- Average: 10%
- Expert: 40%
- Optimal: 75%

**체크리스트**:
- [ ] EXPERT 티어 완료 후 진행
- [ ] 10개 레벨 생성 및 검증
- [ ] benchmark_level.py에 등록

---

#### 대기 중 [API] 게임부스트 서버 연동
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `backend/app/clients/gboost.py`, `backend/app/api/routes/gboost.py`

**작업 내용**:
로컬 레벨을 게임부스트 서버에 업로드하는 기능 구현

**체크리스트**:
- [ ] GBoostClient 클래스 구현
- [ ] 인증 시스템 구현
- [ ] 레벨 업로드 API 완성
- [ ] 레벨 다운로드 API 구현
- [ ] 테스트 및 문서화

---

### 낮음 (Low Priority)

#### 대기 중 [프론트엔드] 레벨 에디터 개선
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `frontend/src/components/GridEditor/`

**작업 내용**:
- 드래그 앤 드롭 타일 배치
- 복사/붙여넣기 기능
- 실행 취소/다시 실행

---

#### 대기 중 [테스트] E2E 테스트 작성
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `tests/`, `frontend/tests/`

**작업 내용**:
전체 시스템 통합 테스트 작성

**체크리스트**:
- [ ] 백엔드 API 테스트
- [ ] 프론트엔드 컴포넌트 테스트
- [ ] 시뮬레이션 정확성 테스트

---

#### 대기 중 [문서] 사용자 가이드 작성
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `claudedocs/USER_GUIDE.md`

**작업 내용**:
일반 사용자를 위한 도구 사용 가이드 작성

---

## 완료된 작업

### 완료 [자동화] 레벨 난이도 자동 검증 시스템
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `validate_level_difficulty.py`

**구현 내용**:
- 100회 반복 테스트로 통계적 유의성 확보
- 5가지 봇(Novice, Casual, Average, Expert, Optimal) 테스트
- 허용 편차: ±15% 이내 PASS, 15-22.5% WARN, 22.5% 초과 FAIL
- 개선 제안 시스템
- 티어 단위 및 개별 레벨 검증 지원

---

### 완료 [API] 통합 대시보드 API
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/api/routes/simulate.py`

**구현된 엔드포인트**:
- `GET /api/simulate/benchmark/list` - 벤치마크 레벨 목록
- `GET /api/simulate/benchmark/{level_id}` - 개별 레벨 조회
- `GET /api/simulate/benchmark/dashboard/summary` - 대시보드 요약
- `POST /api/simulate/benchmark/validate/{level_id}` - 레벨 검증

---

### 완료 [자동화] 레벨 생성 도구 자동화
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `generate_benchmark_levels.py`

**구현 내용**:
- 파라미터 기반 레벨 생성
- 자동 검증 통합
- 자동 보정(Calibration) 기능
- 배치 생성 지원
- 검증 실패 시 개선 제안

---

### 완료 [API] 로컬 레벨 관리 시스템
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/api/routes/simulate.py`, `backend/app/storage/local_levels/`

**구현된 엔드포인트**:
- `GET /api/simulate/local/list` - 로컬 레벨 목록
- `GET /api/simulate/local/{level_id}` - 개별 레벨 조회
- `POST /api/simulate/local/save` - 레벨 저장
- `DELETE /api/simulate/local/{level_id}` - 레벨 삭제
- `POST /api/simulate/local/import-generated` - 일괄 임포트

---

### 완료 [백엔드] 봇 시뮬레이터 구현
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/core/bot_simulator.py`

**구현 내용**:
- 5종 봇 프로필 (Novice, Casual, Average, Expert, Optimal)
- 15개 기믹 지원 (Ice, Chain, Grass, Link, Frog, Teleport, Curtain, Bomb, Craft, Stack 등)
- 결정론적 시뮬레이션 (동일 시드 = 동일 결과)
- 시각적 시뮬레이션 (단계별 게임 상태 추적)

---

### 완료 [백엔드] 레벨 생성기 구현
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `backend/app/core/generator.py`

**구현 내용**:
- 장애물 생성 (Ice, Chain, Grass)
- 장애물 개수 min/max 범위 설정
- 유효성 검증 강화
- 타일 수 조정 후 장애물 재검증

---

### 완료 [프론트엔드] GeneratorPanel UI
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `frontend/src/components/GeneratorPanel/index.tsx`

**구현 내용**:
- 장애물 개수 슬라이더 (min/max)
- Grass 장애물 옵션
- API 파라미터 확장 (`obstacle_counts`)

---

### 완료 [프론트엔드] GridEditor 개선
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `frontend/src/components/GridEditor/index.tsx`

**구현 내용**:
- effect_type 시각화
- Dock 상태 유지 (게임 오버 시에도 보존)

---

### 완료 [테스트] 기믹별 시뮬레이션 테스트
**담당자**: Claude
**완료일**: 2025-12-30
**관련 파일**: `test_gimmicks.py`

**테스트 결과**: 10/10 PASS (Multi-bot + Visual Simulation 모두 통과)

| 기믹 | 결과 | 설명 |
|------|------|------|
| Ice | PASS | 노출 시 다른 타일 선택마다 1겹씩 감소 |
| Bomb | PASS | 노출 시 카운트다운 감소, 0이면 게임오버 |
| Chain | PASS | 좌우 인접 타일 클리어로 해제 |
| Grass | PASS | 인접 타일 클리어 시 1겹씩 제거 |
| Link | PASS | 연결된 타일 함께 선택 (독 2칸 사용) |
| Frog | PASS | 랜덤 점프하여 타일 블로킹 |
| Stack | PASS | 방향별 타일 밀림 |
| Curtain | PASS | 열림/닫힘 토글 |
| Teleport | PASS | 3회 클릭마다 위치 교환 |
| Craft | PASS | 타일 생성 |

**수정 내역** (2025-12-30):
- `test_gimmicks.py`: Visual Simulation API 응답 파싱 로직 수정
  - `bot_results[0]`에서 `cleared`, `total_moves` 추출하도록 변경

---

### 완료 [백엔드] EASY 티어 레벨 구현
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/models/benchmark_level.py`

**구현 내용**:
- 10개 레벨 (easy_01 ~ easy_10)
- 99-100% 클리어율 달성
- 기본 매칭 연습용

---

### 완료 [백엔드] MEDIUM 티어 레벨 구현 (초기 버전)
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/models/benchmark_level.py`

**구현 내용**:
- 10개 레벨 (medium_01 ~ medium_10)
- 현재 98.9-100% 클리어율 (재설계 필요)
- ICE, 2레이어 도입

---

## 작업 유형별 요약

### 구현 현황

| 기능 | 상태 | 비고 |
|------|------|------|
| 봇 시뮬레이터 | 완료 | 15개 기믹, 5종 봇 |
| 레벨 생성기 | 완료 | 장애물 생성 포함 |
| 레벨 검증기 | 완료 | CLI 도구 |
| 대시보드 API | 완료 | 4개 엔드포인트 |
| 로컬 레벨 관리 | 완료 | CRUD API |
| EASY 티어 | 완료 | 10개 레벨 |
| MEDIUM 티어 | 재설계 필요 | 너무 쉬움 |
| HARD 티어 | 대기 중 | 도구 준비 완료 |
| EXPERT 티어 | 대기 중 | |
| IMPOSSIBLE 티어 | 대기 중 | |
| 게임부스트 연동 | 대기 중 | placeholder 구현됨 |

### 봇 프로필

| 봇 | 실수율 | Lookahead | 목표 클리어율 |
|----|--------|-----------|--------------|
| NOVICE | 40% | 0 | ~40% |
| CASUAL | 20% | 1 | ~60% |
| AVERAGE | 10% | 2 | ~75% |
| EXPERT | 2% | 5 | ~90% |
| OPTIMAL | 0% | 10 | ~98% |

### 구현된 기믹 (15개)

| 기믹 | 코드 | 봇 지원 |
|------|------|---------|
| None | `none` | 완료 |
| Ice | `ice` | 완료 |
| Chain | `chain` | 완료 |
| Grass | `grass` | 완료 |
| Link East/West/South/North | `link_e/w/s/n` | 완료 |
| Frog | `frog` | 확률적 |
| Teleport | `teleport` | 완료 |
| Curtain | `curtain` | 완료 |
| Bomb | `bomb` | 완료 |
| Craft | `craft` | 완료 |
| Stack N/S/E/W | `stack_n/s/e/w` | 완료 |

---

## 작업 추가 방법

새 작업을 추가할 때는 다음 형식을 사용하세요:

```markdown
#### 상태 [태그] 작업 제목
**담당자**: [이름 또는 미정]
**생성일**: YYYY-MM-DD
**관련 파일**: [파일 경로]

**작업 내용**:
- 작업 상세 설명

**체크리스트**:
- [ ] 세부 작업 1
- [ ] 세부 작업 2
```

**상태 변경 시**:
- `대기 중` → `진행 중` (작업 시작)
- `진행 중` → `완료` (작업 완료, "완료된 작업" 섹션으로 이동)
- `대기 중` 또는 `진행 중` → `취소/보류` (작업 취소)

---

## 관련 문서

- [PROJECT_INDEX.md](PROJECT_INDEX.md) - 프로젝트 인덱스
- [AUTOMATION_SUMMARY.md](AUTOMATION_SUMMARY.md) - 자동화 시스템 요약
- [BENCHMARK_API_GUIDE.md](BENCHMARK_API_GUIDE.md) - API 가이드
- [LEVEL_GENERATION_GUIDE.md](LEVEL_GENERATION_GUIDE.md) - 레벨 생성 가이드
- [LOCAL_LEVELS_GUIDE.md](LOCAL_LEVELS_GUIDE.md) - 로컬 레벨 관리 가이드
- [SPECIFICATION.md](../SPECIFICATION.md) - 구현 명세서

---

**문서 버전**: 1.0
**작성자**: Claude
