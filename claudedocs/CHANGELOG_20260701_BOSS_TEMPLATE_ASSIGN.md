# 레벨 템플릿 → 보스 배치 (2026-07-01)

## 변경
레벨 템플릿(`level_templates.json`) 자동배치를 **전 레벨 흩뿌리기 → 보스 레벨 전용**으로 교체.

- **정책**: 측정 템플릿 `measured_difficulty` 오름차순 → 보스(10,20,30,…)에 순차 배치 (쉬운 것 → 첫 보스).
- **overflow**(템플릿 > 보스): 미배치 + 경고 (`overflow='unused'`).
- **underflow**(템플릿 < 보스): 남는 보스 = 기존 절차생성.
- **수동 할당** 우선 유지.
- **확장 격리**: 기존 best-gap(전 레벨 매칭) 로직은 `TEMPLATE_SLOT_POLICY.overflow='spill'` 핸들러로 **보존**(미호출). 템플릿 많아지면 플래그만 켜 non-boss 개방.

## 파일
- `frontend/src/components/ProductionDashboard/index.tsx`: 자동배치 블록 교체(정책 상수 + 보스 순차 + overflow).
- 백엔드 **무변경** (`/debug/level-templates`·`/generate/from-template` 재사용, 스키마 영향 0).

## 검증
- `tsc --noEmit` 0에러.
- 로직 시뮬 4케이스: 5템플릿→쉬운3개 10/20/30 오름차순+초과2 미배치 / 3=정확 / 2=underflow(30절차) / 수동10 우선. 전부 통과.
- Playwright MCP 부재 → 실제 배치 생성 UI 검증은 후속(수동).

## 문서
- 신규 `DESIGN_BOSS_TEMPLATE_ASSIGN.md` (레벨 템플릿 배치 설계 — 기존 문서 없어 생성).
- `PROJECT_INDEX.md`, `TODO.md` 갱신.
