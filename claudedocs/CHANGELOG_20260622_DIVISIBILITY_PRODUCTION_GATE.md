# ÷3 클리어불가 레벨 진단·재생성 + 프로덕션 저장 안전망 (2026-06-22)

## 문제
최신 프로덕션 배치(batch_1781857657434, 1500레벨) 순차검증 시 9개 레벨이 계속 실패.
A* 솔버 판정: **PROVEN_IMPOSSIBLE — ÷3 분배 위반** (매칭타입별 개수가 3배수 아님 → 수학적 클리어 불가).
해당 레벨: 392, 530, 1000, 1340, 1380, 1390, 1410, 1429, 1440.

## 원인 (추적)
- v16 ÷3 게이트(`_finalize_divisibility_guarantee`, 커밋 2026-06-17)는 `generator.generate()` **내부에만** 존재.
- 9개는 `reverse_generated=None` + `validation_attempts=0` + `pattern_index=-1` → **generate() 미경유**(생성 후 변형: fix-centering/수동편집/패턴조작 or 외부 빌드).
- 후속 변형 경로 + 프론트 수동편집 sync(`productionServerSync`)가 ÷3 재검사 없이 `save_batch`로 직행 → 불가 레벨이 프로덕션 유출.

## 조치
1. **재생성**: 9개를 `use_reverse_generation=True`로 generate() 재생성 → ÷3 위반 0, `reverse_generated=True`(witness 솔버블·÷3 보장). 배치 백업 후 패치.
2. **근본 안전망**: `production_store.save_batch`에 `_enforce_divisibility_gate` 추가 — 게임 분배(`solver._clearability_type_counts`, DB_Level.cs 포트) 기준 ÷3 위반 레벨을 저장 직전 검출해 `meta.verification_passed=False` + `divisibility_violation` 강제. **생성 경로 무관 최종 경계 차단**. 응답에 `divisibility_flagged`/`divisibility_levels` 추가.
   - 검증: 백업(재생성전) 9개 정확 검출, 재생성 후 0건.

## 후속 권장
- 프론트 수동편집 저장 시 게이트 응답의 `divisibility_flagged>0` 경고 노출
- generate() 외 모든 타일 변형 단계 직후 `_finalize_divisibility_guarantee` 호출 검토

## 추가 조치 (2차)
1. **프론트 저장 경고**: `productionServerSync` 에 `setDivisibilityWarningHandler` 추가 + `pushBatchToServer` 가 응답의 `divisibility_flagged>0` 시 호출. ProductionDashboard 에서 `addNotification('warning', ...)` 등록 → 저장 시 클리어불가 레벨 검출되면 토스트 경고(예시 레벨번호 포함).
2. **generate() 외 변형 방어**: `analyze.fix-centering` 의 `_fix_visual_centering` 직후 `_finalize_divisibility_guarantee` 호출 추가(멱등) — 중앙정렬 변형이 ÷3 카운트 깨도 재보장.
3. **회귀 테스트**: `backend/tests/test_divisibility_gate.py` 11개 통과.

## ⚠️ 전 배치 감사 (읽기전용)
저장된 83개 배치 중 **25개 배치에 ÷3 위반 2,072 레벨** 분포 (상위 4배치 308/252/228/172 = 960). 단 대부분 **구버전/비활성 배치 파일** 추정 — 게임에 실제 서빙되는 라이브 배치만 영향. 라이브 배치 식별 후 선별 재생성 권장. (58개 배치는 클린)

## 3차 — 진짜 우회 경로 발견·차단 (root)
신규 6/22 배치(batch_1782098478233)에서 ÷3 위반 1개(L1370) 재발 → 추적 결과:
- **프론트 프로덕션 생성은 `/generate/from-template` 사용** (apiClient, ProductionDashboard).
- 이 엔드포인트(`analyze.generate_from_template`)는 저장된 템플릿 level_json 을 로드·타일 재배정 후 **`generator.generate()`/`_finalize` 를 전혀 거치지 않고 그대로 반환** → 비-÷3 템플릿이 클리어 불가 레벨로 출고. (이전 9개 + 1370 전부 pattern_index=-1 = from-template 산물)
- **수정**: `generate_from_template` 반환 직전 `LevelGenerator()._finalize_divisibility_guarantee(level_json)` 호출 추가(멱등). 실측: L1370 → ÷3 위반 0, A* UNCERTAIN(솔버블).
- 현 배치 L1370 패치 완료(서버 파일), 배치 전체 ÷3 위반 0.

## 최종 방어 계층 (5중)
1. generate() v16 게이트 (표준 생성)
2. from-template 게이트 (템플릿 생성) ← root fix
3. fix-centering 직후 게이트 (중앙정렬 변형)
4. save_batch 게이트 (저장 경계, 경로무관 최종망)
5. 프론트 토스트 경고 (사용자 가시화)

## 4차 — A* 솔버 통과봇 (검증 false-negative 해소)
문제: 신규 배치 검증실패 18개 분석 → ÷3 진짜불가 0, 전부 '봇이 못 깬 것'(A* PROVEN_SOLVABLE 9 / UNCERTAIN 9). 휴리스틱 봇이 후반 고난도·기믹 레벨을 못 깨 클리어 가능한 레벨을 탈락.

수정: `_verify_single_level` 에 **A* 솔버 통과봇 fallback** 추가.
- `passed=False` 일 때만 `solve_level` 실행(비용 절약).
- `PROVEN_SOLVABLE` → 통과 승격(`solver_verified=True`). `PROVEN_IMPOSSIBLE` → 실패확정. `UNCERTAIN` → 봇결과 유지.
- `BatchVerifyResultItem` 에 `solver_verified`/`solver_verdict` 필드 추가.
- 효과: 18 실패 → 9 통과(솔버검증), 진짜불가 0.

남은 과제: UNCERTAIN 9 = A* 상태폭발(timeout) 또는 미지원 기믹(bomb/frog/unknown). 예산 상향 또는 솔버 기믹 모델 보강 필요(별도).

## 5차 — max_moves 가짜 제약 제거 (실제 게임 정합)
조사: 실제 게임(sp_meowsgarden Dock.IsGameOver)은 fail 조건이 **폭탄 폭발 / 덱 가득참** 둘뿐. 이동 횟수 제한 없음, 타임어택 타이머도 코드상 비활성(LevelController 주석). 즉 max_moves 는 게임 규칙이 아니라 **봇 시뮬레이터의 무한루프 방지 안전 상한**일 뿐인데, 기본값 30이 fail 기준으로 쓰여 무제한 레벨(L1061 등)을 오탈락시킴.

수정: max_moves 미지정 레벨은 **타일수 + 50** 으로 설정 (봇 1수=타일1선택 → 최소 타일수 필요 + 여유). 백엔드 `bot_simulator.simulate_with_profile` + 프론트 `gameEngine`(수동 플레이) 양쪽 동일 적용.
- L1061(98타일→148수): expert/optimal 100% 클리어 = 통과(이전 0%).
- 명시적 max_moves 있는 레벨은 그대로 존중.

## 수동 플레이 실패사유 표시 (부가)
GamePlayer 게임오버 시 6종 실패사유 표시: 덱풀/폭탄/이동소진/잔디불가/체인불가/데드락 (+ 남은 목표·타일 수). 기존 하드코딩 "Slots are full" 대체.

## 6차 — 재생성 난이도 수렴 (RL 적응 생성 통합)
문제: `batch-verify-regenerate` 재생성이 **동일 파라미터로 generate() 재롤만** 반복 → 난이도가 목표서 구조적으로 빗나가면 몇 번 돌려도 수렴 안 함. 반면 `/generate/validated`(RL)는 gap 기반으로 difficulty_offset/기믹/그리드/타일종류를 **적응 조정**하며 수렴.

수정: 재생성 루프의 단순 재롤(for attempt + generator.generate)을 **`generate_validated_level()` 단일 호출로 교체**. 내부 적응 루프가 목표 난이도로 수렴. 결과를 `_verify_single_level`(솔버봇 fallback 포함)로 일관 판정.
- 검증: 목표 0.3/0.6/0.85 전부 통과=True(1회 수렴).
- 효과: 재생성도 RL과 동일하게 목표 난이도에 수렴 → "여러 번 재생성해도 안 맞던" 문제 해결.
