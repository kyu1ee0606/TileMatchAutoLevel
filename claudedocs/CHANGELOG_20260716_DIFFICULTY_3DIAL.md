# 난이도 3단 다이얼 — 모양 → 기믹 → 색

> 2026-07-16 · 재생성 반복 없이 3개 레버로 난이도 조절. 레벨 상세패널서 다이얼 조정 → 보드 즉시 갱신.

## 개념
난이도 = 3층 레버. 굵음→미세 순으로 다듬음(찰흙→형태→사포):

| 레버 | 폭 | 방식 | 재생성 |
|---|---|---|---|
| **모양** | 굵음 | 완전 새 레이아웃 | O (기존 재생성) |
| **기믹 강도** | 중간 | 속성기믹 밀도 0~1 | X (배치만) |
| **색 미세** | 좁음 | 색 재배치 target 근접 | X (기존 색튜너) |

## 캐스케이드 (upstream 바뀌면 downstream만)
- **모양 변경** → 기믹·색 **둘 다 리셋** (positions/멀티셋 바뀜).
- **기믹 변경** → 색 **초기화 불필요** (색배치는 모양 커버순서에만 의존, 기믹과 직교. td[1]만 바꿔 색 멀티셋 불변 = ÷3·색순열 유효). "⟳색 재추천"만 표시(권장).
- **색 변경** → 하위 없음.

## 백엔드 `POST /api/tune/gimmick`
```
{ level_json, level_number, intensity:0~1, evaluate:bool, skill_mean? }
→ { best_level_json, predicted_clear_rate, original_predicted, gimmick_count, ... }
```
- 원리: 속성기믹(chain/ice/grass/link/curtain/bomb/frog/teleport/unknown)은 td[1]만 추가/제거 → **타입카운트 불변 = ÷3 자동보존**. key/craft/stack(구조·골)·색(td[0])은 불변.
- 절차: ① 전 속성기믹 리셋(strip, plain 'bomb' 등 변형도 base매칭 제거) → ② 강도→총목표수(field×0.22×intensity) → ③ 언락된 기믹만 라운드로빈 분배 → ④ 생성기 `_ensure_*`로 유효배치(chain 이웃/grass 홀짝/link 페어/unknown 커버/bomb_N 카운트다운).
- **튜토리얼 기믹 강도0에서도 최소 3 보장** (언락 첫 스테이지 규칙 연동).
- 결정적(시드고정), evaluate=false=배치만(즉시 보드), true=RL 예측까지(~1s). 검증 RL = 순차검증/색튜너와 동일.

## 프론트 (ProductionDashboard 레벨 상세)
- 🎛️ 난이도 다이얼 패널: [🔄재생성] · [기믹 강도 슬라이더] · [🎚️색 미세] · [💾적용(저장)].
- 슬라이더 놓으면 → `/tune/gimmick` → `selectedLevel.level_json` in-memory 교체 → 보드 즉시 재렌더(저장 X). [적용]서 디스크 저장(재검증 대상).
- base는 항상 **디스크 원본**서 캡처(`gimmickBaseRef`) → 슬라이더 프리뷰로 base 안 흔들림, 강도는 원본 기준 결정적.
- 캐스케이드: 재생성/저장 → `loadLevels` → 디스크 sync → base·다이얼 리셋. 기믹 변경 → `colorStale=true`(색버튼 ⟳표시).

## 검증
- 강도 0~1 → 기믹수 **단조 증가** (예 L291: 3→21). 결정적(같은 강도=같은 결과).
- **÷3 보존**: td0 타입카운트 조정 전후 완전 동일(전 레벨 True).
- **튜토리얼 강도0 유지**: attr-튜토리얼 9종 전부 강도0서 tut≥3.
- bomb = `bomb_N`(카운트다운, plain 'bomb' 자동교정 → 게임 즉사버그 회피).
- 클리어율 반응폭 = 레벨 언락 기믹 다양성 비례(초반 좁음~후반 넓음). 색튜너보다 넓음.
- 프론트 `tsc --noEmit` 통과, vite HMR 정상.

## 파일
- `backend/app/api/routes/tune.py` — `/gimmick` 엔드포인트 + 헬퍼
- `frontend/src/components/ProductionDashboard/index.tsx` — 다이얼 상태/핸들러/패널
- 게임코드(sp_meowsgarden) 무변경.

## 한계
- Playwright MCP 미가용 → UI 상호작용은 tsc+HMR+API 검증까지(수동 웹뷰 확인 권장).
- 강도 다이얼 중간구간 RL 노이즈 ±2~3%p(색튜너와 동일 한계).
