# 보스 레벨 = 항상 보스 템플릿 보장 계획 (A+B)

작성 2026-07. 상태: **계획(착수 전 — export 완료 후 착수)**. 프론트 전용.

## 1. 문제
보스레벨(레벨번호 %10==0)이 순차검증서 재생성되며 **비보스(일반 7x7 템플릿) 모양**으로 바뀌는 경우.

### 근본 원인 (코드 확인됨)
- **라운드 재생성**(`handleRegenerateLevel`)은 보스 안전: `!isBossRegen` 가드(4734)로 일반템플릿 차단, boss_mode 폴백.
- 근데 **QD 2차패스**(`runFailedLevelSecondPass`→`genCandidate`, index.tsx:4226)는 **보스 미고려** — grid[7,7]+aesthetic 패턴+craft/stack goal의 **generic 후보**를 밴드풀서 실패슬롯에 배정 → 보스 슬롯에 generic 배정 시 **비보스화**.
- 또 라운드 재생성의 보스템플릿 사용은 `level_json._boss_template_id` **스탬프에만 의존**(4684) → 스탬프 없는 보스(구생성/이미 깨진 것)는 템플릿 대신 boss_mode 절차생성.

## 2. 목표
%10 레벨은 **어떤 재생성 경로로도**:
1. 일반(비보스) 템플릿 절대 안 씀, AND
2. 준비된 **보스 템플릿 모양** 유지(스탬프 유무 무관).

## 3. 수정 (A+B, 프론트 전용)

### A. QD 2차패스에서 보스 제외
- `runFailedLevelSecondPass(stillFailed, signal)` 호출부(index.tsx:4191)에서 **stillFailed를 비보스만** 필터, 또는 함수 내부서 `ln%10==0` 스킵.
- 효과: 보스는 generic 밴드풀 배정 대상에서 빠짐 → **비보스화 원천 차단**. 보스가 모든 라운드서 미달이면 **보스 best-snapshot 유지**(라운드 재생성이 만든 보스 모양).
- 근거: 밴드풀 다양성 배정 모델은 템플릿 고정 보스에 안 맞음. 보스는 B의 라운드 재생성이 담당.

### B. 보스 라운드 재생성을 level_number로 템플릿 조회 (스탬프 무관)
- `handleRegenerateLevel`(index.tsx:4684) 조건 변경:
  ```
  // AS-IS: const bossTplId = level.level_json?._boss_template_id;
  //        if (bossTplId && !forceNoTemplate && !newShape) { from-boss-template ... }
  // TO-BE:
  const isBossRegen = levelNumber % 10 === 0 && levelNumber > 0;
  if (isBossRegen && !options?.forceNoTemplate && !options?.newShape) {
    → POST /generate/from-boss-template { level_number, target_difficulty, ... }
      .catch(404 → null)   // 구간 템플릿 없으면 폴백
    if (resp) { save + return; }
    // 404 → 아래 기존 boss crop/boss_mode 폴백(그대로)
  }
  ```
- 효과: 스탬프 없는 보스도 **level_number로 준비된 템플릿 조회 → 모양 복구**. 초기생성(1406)과 동일 패턴 이식(일관성).
- **이미 2차패스로 깨진 보스**도 재검증→라운드 재생성 시 **템플릿 모양 복구**(B가 self-heal).

## 4. from-boss-template 안전성 (확인됨)
- `_finalize_divisibility_guarantee` + `_strip_orphaned_link_tiles` 거침(analyze.py:237-238) → ÷3 총합·링크 클린.
- `max_moves = total + 50` 버퍼 → 무브부족 없음.
- `_boss_template_id` 스탬프됨 → 이후 재생성도 인식.

## 5. 불변식/엣지 체크 (문제없음 검증)
| 엣지 | 처리 |
|------|------|
| 보스 템플릿 없는 구간(404) | from-boss-template 404 → boss_mode 폴백(보스 8/7 유지). 일반템플릿 X. ✓ |
| 보스 템플릿이 언클리어러블 | `forceNoTemplate` → 템플릿 스킵 → boss_mode. (기존 `!forceNoTemplate` 가드 유지) ✓ |
| 이미 비보스화된 보스 | 재검증→라운드 재생성(B) → 템플릿 복구 ✓ |
| 보스가 전 라운드 미달 | 2차패스 제외(A) → 보스 best-snapshot 유지(비보스화 X) ✓ |
| 일반레벨 | A/B 무관(isBossRegen=false) → 기존 그대로 ✓ |
| /tune/auto | 모양보존(색·기믹 순열) → 보스모양 안 바뀜 ✓ |
| 템플릿 자동배정(936) | 이미 보스슬롯 제외 → 영향 없음 ✓ |

### 남은 리스크 (플랜 외, 별개 인지)
- **보스 템플릿 자체가 per-type ÷3 위반**이면(명시 내부 타일, 스키마 §84): from-boss-template가 `_finalize`(총합÷3)는 하나 per-type 보정은 불확실 → 서버 ÷3 게이트가 실패처리 → B가 같은 템플릿 재생성 → 수렴 못할 수 있음. **이건 템플릿 저작 품질 문제**(A+B 탓 아님). 발생 시 해당 보스 템플릿을 per-type ÷3로 재저작 필요.

## 6. 검증 단계 (착수 후)
1. tsc 0.
2. 보스레벨(10,20,...340) 재생성 호출 → level_json에 `_boss_template_id` 있는지 + 그리드 8/7(비보스 7x7 아님) 확인.
3. 스탬프 없는 보스(강제로 _boss_template_id 제거) 재생성 → 여전히 from-boss-template 타는지(B 검증).
4. 실패 보스가 2차패스 대상서 빠지는지(A 검증) — stillFailed에 보스 없음.
5. 일반레벨 재생성 회귀 없음 확인.
6. (수동) 브라우저서 보스 순차검증 → 재생성돼도 보스 모양 유지 확인.

## 7. 범위
- 파일: `frontend/src/components/ProductionDashboard/index.tsx` (2곳: 4191 근처 A, 4684 근처 B).
- 백엔드 무변경. 서버 안 건드림.
- **착수: export 완료 후.**
