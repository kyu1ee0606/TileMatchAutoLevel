# 레벨 템플릿 → 보스 배치 (설계)

> 상태: **구현 완료 (2026-07-01)**. 대상: `frontend/src/components/ProductionDashboard/index.tsx` 자동배치.
> ⚠️ "템플릿" 2종 구분: **레벨 템플릿**(`level_templates.json`, 저장된 완성 레벨 — 본 문서) vs **패턴 템플릿**(`custom_patterns.json`, 모양 씨앗 — `DESIGN_TEMPLATE_BASED_SHAPES.md`). 서로 다름.

## 1. 배경
`level_templates.json`에 저장된 **레벨 템플릿**(손제작/검증 완성 레벨)을 프로덕션 배치에 자동 삽입.
- **기존(v15.55)**: 측정 난이도(`measured_difficulty`) 오름차순 → **전 레벨** 슬롯에 targetDiff 근접(best-gap) 매칭 → 아무 레벨에나 흩어짐.
- **변경**: **보스 레벨(10,20,30,…)에만** 배치. 템플릿끼리 난이도 순위로 쉬운 것부터 첫 보스에 배치.

## 2. 배치 정책 (확정)
```
측정된 템플릿 → measured_difficulty 오름차순
→ 쉬운 것: 10레벨(첫 보스), 다음: 20, … 순차
→ overflow(템플릿 > 보스): 미배치 + 경고 (쉬운 것부터 보스 채움)
→ underflow(템플릿 < 보스): 남는 보스 = 기존 절차생성 (변경 없음)
→ 수동 할당(templateAssignments) 우선 (해당 보스는 수동 유지)
```

- **난이도 산정**: 기존 `measured_difficulty`(봇 autoplay 점수 0~1)로만 정렬. 별도 재측정 없음.
- **보스 정의**: `level % 10 === 0` (게임 보스와 동일, generate.py `SPECIAL_SHAPE_CYCLE_SIZE=10`).

## 3. 확장성 (정책 상수)
```ts
const TEMPLATE_SLOT_POLICY = { primary: 'boss', overflow: 'unused' | 'spill' };
```
- `overflow: 'unused'` (현재): 보스 초과 템플릿 미배치.
- `overflow: 'spill'` (미래 격리 보존): 초과 템플릿을 **non-boss 슬롯에 best-gap 매칭**(기존 로직 그대로 보존, 미호출). 템플릿 많아지면 이 플래그만 켜면 non-boss 개방.
- 향후 `primary`도 확장 가능(보스+특정레벨 등).

## 4. 구현 위치
| 파일 | 변경 |
|------|------|
| `frontend/.../ProductionDashboard/index.tsx` (자동배치 블록) | best-gap 전레벨 매칭 → **보스 순차배치 + overflow 정책** 교체. best-gap은 `overflow:'spill'` 핸들러로 격리 보존 |
| `analyze.py` `/debug/level-templates`, `/generate/from-template` | **무변경** (재사용). 스키마/엔드포인트 영향 0 |

## 5. 불변식
- 백엔드 스키마/엔드포인트 무변경 (프론트 배치 로직만).
- 수동 할당 우선 유지.
- 보스 아닌 레벨 = 기존 절차생성 무변경.
- 미측정(`measured_difficulty == null`) 템플릿 = 자동 배치 제외(경고).

## 6. 검증 (Playwright MCP 부재 → 로직 시뮬)
| 케이스 | 결과 |
|--------|------|
| 30레벨·5템플릿 | 쉬운 3개 → 10/20/30 오름차순, 초과 2 미배치 ✅ |
| 30·3 | 10/20/30 정확 배치 ✅ |
| 30·2 (underflow) | 10/20만, 30=절차 ✅ |
| 수동 10 고정 | 수동 유지 + 자동 20/30 ✅ |
- `tsc --noEmit` 0에러.

## 관련
- `DESIGN_TEMPLATE_BASED_SHAPES.md` (패턴 템플릿 — 별개)
- `LEVEL_GENERATION_GUIDE.md`, `LEVEL_CONFIG_TABLE.md`
- `PROJECT_INDEX.md` §레벨 생성
