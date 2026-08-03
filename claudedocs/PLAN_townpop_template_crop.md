# 타운팝 10×10 레벨 템플릿 → 인게임 규격 편입 계획

작성 2026-07-31. 상태: **계획(착수 전)**. 목표: **레벨링(층별 고정 패턴) 유지 + 다양성 우선**.

## 1. 현황 (실측)

`backend/data/level_templates.json` — 타운팝(`21ff4576052`) 출신 **211개**.

| ingame_cols | 개수 |
|---|---|
| **(10,9,10,9,10)** | **145** |
| **(10,9,10,9)** | **28** |
| (9,8,9,8,9) | 3 |
| (10,9,10,9,10,9) | 3 |
| (8,7,8,7) | 3 |
| (7,6,7) | 8 |

→ **9~10 계열 = 183개(87%)**. 프로덕션 인게임 규격(5·6·7, 최대 8)을 초과.

### 층별 고정 패턴 확인
층마다 `col`이 10,9,10,9…로 **홀짝 교대**하고 각 층이 서로 다른 모양 = **"그리드 크기별 고정"이 아니라 "층별 고정"**. 사용자 지적과 일치. → 크롭 시 **층 전체를 한 덩어리로** 다뤄야 레벨링이 보존된다.

### 여백 실측
| | 개수 |
|---|---|
| 가장자리에 여백 있음(무손실 크롭 가능) | **48** |
| 가장자리까지 타일이 참 | **135** |

### 균일 크롭 손실 시뮬 (전 층 동일량, 좌우/상하 대칭)
| 목표 최대변 | 무손실 | 경미(<5%) | 보통(<15%) | 심각(≥15%) | 평균손실 | 중앙값 |
|---|---|---|---|---|---|---|
| **8** | 48 | 30 | 40 | **65** | 12.2% | 7.8% |
| **7** | 3 | 2 | 20 | **158** | 33.1% | 30.7% |

→ **8로 크롭하면 78개(43%)가 손실 5% 미만**, 7까지 줄이면 대부분 붕괴.

## 2. 결론 — 단일 방식으로는 불가

"테두리 잘라내기"만으로는 **135개가 타일 손실**을 겪는다. 대신 **템플릿별 상태 판정 후 경로 분기**가 필요.

## 3. 방안 — 3-tier 분류 + 경로별 처리

각 템플릿을 **자동 판정**해 A/B/C로 분류:

### Tier A — 무손실 크롭 (예상 ~48개)
가장자리 여백이 충분해 잘라도 타일이 안 잘림.
```
전 층에서 좌/우/상/하 여백의 최소값만큼 균일 크롭
→ 홀짝 관계(짝수층 S, 홀수층 S-1) 유지
→ 최대변 ≤ 8 이면 채택
```
**레벨링 100% 보존.** 최우선 편입.

### Tier B — 경미 손실 크롭 (예상 ~70개, 손실 <15%)
가장자리에 타일이 조금 걸침.
```
① 균일 크롭으로 최대변 8 맞춤
② 잘려나간 타일 수만큼 ÷3 재보정(기존 _finalize_divisibility_guarantee)
③ 크롭 후 검증: 층별 실루엣 유사도(원본 대비 IoU) ≥ 임계값이면 채택
```
**임계값 미달이면 C로 강등.** 레벨링이 뭉개지면 다양성에 기여 못 함.

### Tier C — 크롭 부적합 (예상 ~65개)
손실 ≥15% 또는 IoU 낮음.
```
옵션 C-1: 층별 모양을 '커스텀 패턴'으로 추출해 5·6·7 변형 자동 생성
          (기존 pattern-create-multi 파이프라인 재사용)
옵션 C-2: 보류(사용 안 함) — 다양성은 A·B + 기존 패턴으로 확보
```
**C-1 권장** — 원본 크기를 못 살리더라도 **모양의 정체성**은 살릴 수 있음.

## 3-b. 【레드팀 검증 반영 — 착수 전 필수 수정】

### R1. 🔴 크롭 기준축 = **최상위 `row`** (층별 `col` 아님) — 직접 검증 완료
게임: `TileGroup.cs:548` `UpdateLayerRowCount(cLevel.xLayer, cLevel.xRow)` → **레벨 단위 `xRow` 하나**만 사용.
`:1196/1200` `LayerSpawn(rowCount)` / `LayerSpawn(rowCount-1)` → 짝수층 S×S, 홀수층 (S−1)×(S−1) **정사각**.
`TileLayer.cs:51`·`TileRow.cs:78-84` 루프는 `j < N` → `x ≥ N` 키는 **조용히 미스폰**(클램프·에러 없음).
출고측: `gboost.py:391` `row = first_layer.get("row")` → `:461` `"row": str(row)` = **layer_0.row 가 보드 크기**.

문제:
- 템플릿 2개(`level_41`, `level_45`)가 `col ≠ row` (col `[9,8,9,8,9]` / row `[10,9,10,9,10]`) → **col 기준 크롭하면 10×10으로 출고**
- 분석 스크립트가 `base_dim = max(col)` 만 봄(`analyze_townpop_templates.py:54-56`) → 이 케이스를 못 봄

**수정**: 크롭 기준을 `layer_0.row`로. 크롭 후 **하드 단정**(IoU 휴리스틱 아님):
```
모든 층 i에 대해  N_i = row_0 - (i % 2)
require  max(x)+1 <= N_i  AND  max(y)+1 <= N_i     위반 → 강등 아니라 거부
```

### R2. 🔴 헤더 `null` 템플릿 3개 → 현재 크롭 함수 크래시
`level_127`·`level_137`·`level_169` 는 전 층 `col: null, row: null`(타일은 실재, extent 0..9).
`generator.py:268-270` `max(... if l[1] > 0)` → 빈 시퀀스 `ValueError`. `analyze.py:2502` 는 `try` **밖** → `/generate/from-template` 에 `crop_max_dim` 주면 **지금도 500**.
**수정**: `crop_level_to_max_dim` 에 `not filled` 가드 + `analyze.py:2502` try 안으로 + 해당 3개는 `repair_header_oob.py` 의 Class B 로직(정사각교대 헤더 재구성)으로 선(先)복구.

### R3. 🔴 craft/stack 출력칸 OOB — **크롭 전부터 86개**, 무해하지 않음
실측: 46/211 템플릿에 86개(주로 `stack_s`, 75/86이 `y = row` = 아래로 벗어남). 크롭 후에도 82개 잔존.
게임: `TileCraft.cs:241` 앵커 null → `TileGroup.cs:1071` 그래도 배출 → `Tile.cs:2843-2848` `AddOffset` 이 키를 `-1_3` 같은 값으로 재작성 → `DB_Level.cs:898` 음수 인덱스 null → **영구 매칭 불가**.
개발팀도 형제 케이스를 이미 패치(`TileCraft.cs:849-859` 주석: *"배출칸이 빈 craft… 영원히 배출 못 함(데드락, 클리어 불가)"*).
현행 방어 없음: `_relocate_tiles_from_goal_outputs`(`generator.py:11196`)는 **점유만** 보고 경계는 안 봄 + `_preserve_pattern` 이면 early-return + `_finalize_level` 에 미포함.
**수정**: `_repair_goal_output_direction(level)` 신설해 **`_finalize_level` 에 편입**(방향을 격자 안 빈칸으로 회전). 실측 **82/83 회전으로 수리 가능**. 계획의 "출력칸 OOB → Tier 강등"은 **철회**(크롭 탓이 아닌 기존 결함이며, 41+ 템플릿을 부당하게 버림).

### R4. 🔴 파이프라인 순서 반대
계획 §6-3 "크롭 → `_finalize_level` → ÷3" 은 `_finalize_level` 도크스트링과 배치됨(`generator.py:12736-12739`: *"÷3 필요한 호출부는 `_finalize_divisibility_guarantee` 를 **먼저** 돌린 뒤 이 함수를 부른다"*).
실측: 크롭 후 ÷3 보정이 **130/208** 에서 타일 수를 바꿈 → 계획 순서면 **144/208(69%)** 이 stale `max_moves` 로 출고.
**수정**: `analyze.py:2515-2519` 순서 그대로 복사 →
```
_ensure_tutorial_unlock_gimmick → _finalize_divisibility_guarantee → _finalize_level
```

### R5. 🔴 grass 미커버
`_strip_confusing_grass`(`generator.py:13990`)는 `generate()` 와 보스 경로에만 있고 **`_finalize_level` 에 없음**.
게임: 4방 이웃 < 2 면 `canUncover=false` → `FailReason.Grass_CantRevive` 소프트락.
실측: **5개 템플릿에 21개 무효 grass**(크롭과 무관, 지금도 그대로 출고 중).
**수정**: `_finalize_level` 에 편입(기존 프로덕션 출력도 함께 고쳐짐).

### R6. 🔴 기믹 해금 레벨 미반영 — **211개 중 101개(48%)가 해금 전 기믹 보유**
| 요구 최소레벨 | 템플릿 |
|---|---|
| 제한 없음 | 110 |
| 151 (grass) | 6 |
| **241 (curtain)** | **63** |
| 291 (bomb) | 21 |
| 391 (frog) | 11 |

템플릿 자동배정(`index.tsx:910-983`)은 `measured_difficulty` 로만 정렬, **기믹 필터 없음** → 커튼 템플릿이 Lv50 배정 시 **190레벨 조기 등장**.
Tier A 74개 중 **Lv151 미만 사용 가능은 54개**.
**수정(사용자 지시)**: 임포트 시 **`min_level` 산출·메타 기록** + 배정 풀 필터.
```
min_level = max( TUTORIAL_UNLOCK_LEVELS[g] for g in 템플릿이_쓰는_기믹 )   # 없으면 0
배정 조건: level_number >= min_level
```
> 기믹은 from-template 에서 **보존**된다(`analyze.py:2455-2457` — `t0`만 색 배정, `td[1]` 속성·컨테이너 타입은 불변). 그래서 해금 필터가 **반드시** 필요.

### R7. 🟡 재생성 시 모드 유실 (기존 버그 클래스)
재생성 진입점 4곳 중 `template_id` 는 **1곳만** 살아남고 그것도 6개 가드 통과 시에만(`index.tsx:5093`) — **유닛조립 토글이 켜져 있으면 템플릿 레벨이 절차생성으로 바뀜**.
또 `index.tsx:1175` `crop_max_dim: isBossTemplate ? ... : undefined` 가 `if (templateId && !isBossTemplate)` 안에 있어 **항상 undefined** = 비보스 템플릿은 **크롭이 아예 안 걸림**.
**수정**: `genModeFields`(`index.tsx:275`)에 신규 id 배선 + 4개 재생성 경로 반영 + `:1175` 죽은 삼항 수정.

### R8. 🟡 저장 경로 비원자적
`_save_level_templates`/`_save_custom_patterns`/`_save_boss_templates` 전부 직접 `open(w)` — 락·백업 없음. `_load_*` 는 `JSONDecodeError` 를 삼켜 `{}` 반환 → 찢어진 읽기 후 저장 = **라이브러리 전체 소실**. uvicorn 워커 4개.
**수정**: `production_store.py:344-353` 의 `tempfile.mkstemp + os.replace` 패턴 사용.

### R9. 🟡 기타
- **id 스킴**: `lp_<origid>_c8` 은 재크롭 시 키가 바뀜 + `_c7`/`_c8` 동시 활성 → 중복 실루엣. → **`lp_<origid>` 고정**, `target_max_dim` 은 body, **소스당 활성 크롭 1개** 강제.
- **이름 충돌**: `pattern_templates.py:2081` 에 이미 `is_layered_pattern()` 존재(Category 10). → 새 저장소는 **`level_shapes`** 로 명명.
- **IoU 측정 시점**: 크롭 직후가 아니라 **전체 파이프라인 통과 후** 최종 `level_json` 기준(÷3 보정이 130/208 에서 타일 추가). 
- **탭 추가 함정**: `App.tsx:389-486` 은 default 없는 `&&` 체인 → `TabId` 만 추가하고 렌더 분기를 빠뜨리면 **컴파일 통과 + 빈 화면**. `React.lazy` 로 신규 패널만 지연로딩(기존 15개 정적 import + ProductionDashboard 상시 마운트).
- **프리뷰 재사용**: `utils/levelPreview.ts:62` `renderLevelCanvasPreview` (홀짝 스태거·z정렬 정확). ⚠️ 좌표키 규약 불일치 주의(`levelPreview.ts:83` = `x_y`, `levelThumbnailRenderer.ts:30` = `y_x`).
- **데이터 정규화**: `level_34` 는 key 타일 3개인데 `unlockTile` 없음 → 임포트 시 보정. `num` stale 다수(무해).
- 템플릿 수는 **211** (문서 208 표기 정정).

### 레드팀이 "문제없음"으로 확인해준 항목
| 항목 | 근거 |
|---|---|
| 홀짝 균일크롭 | 0/208 위반, 구조적으로 보존 |
| per-type ÷3 | 실측 **0 위반**(단 R4 순서 적용 시) |
| chain | `_finalize_level` 에 포함, 크롭 유발 13건 전부 plain화 |
| link orphan | `_finalize_level` 에 포함, 크롭 유발 19건 전부 제거 |
| bomb/frog | `_finalize_level` 에 포함 |
| max_dim 8 가독성 | 게임측 제한 없음(`LevelScaler.cs` 연속 스케일) |
| 파일 크기·임포트 성능 | 141개 ≈ 0.26MB, 전체 처리 ~1.0초 |

## 4. 홀짝 규칙 준수 (필수 제약)

게임 규칙: 짝수층 `S×S`, 홀수층 `(S-1)×(S-1)`, `row`는 층 무관 동일(실측상 col=row).
크롭 시:
```
base_new = base_old - cut        (cut = 좌+우 잘라낸 총량)
짝수층 col = base_new
홀수층 col = base_new - 1
```
→ **좌우 잘라내는 양이 전 층 동일**해야 홀짝 관계가 깨지지 않음. 상하도 동일.
> 기존 `crop_level_to_max_dim`(generator.py:~240)이 이미 이 규칙으로 균일 크롭한다 → **재사용**.

## 5. 다양성 우선 원칙 (사용자 지시 반영)

- **원본 레벨링(층별 모양) 보존이 1순위**, 크기 맞추기는 2순위
- 크롭으로 모양이 뭉개지면 채택하지 않음(IoU 게이트)
- Tier C는 버리지 말고 **커스텀 패턴으로 추출** → 층별 고정은 잃되 모양 다양성은 확보
- 편입 후 **중복 실루엣 제거**(기존 패턴/템플릿과 유사도 높으면 스킵)

## 5-b. 【확정】신규 탭 — "층별 패턴(Layered Patterns)"

### 왜 별도 탭인가
기존 **패턴 라이브러리**와 저장 모델이 근본적으로 다르다.

| | 기존 패턴 디버그 탭 | **신규 층별 패턴 탭** |
|---|---|---|
| 저장 단위 | `{index}_{S}x{S}` — **그리드 크기별** 변형 | `{id}` — **레벨 1개 = 층 스택 전체** |
| 층 처리 | 한 모양을 층마다 축소/재사용 | **층마다 다른 고정 모양** |
| 홀짝 | 생성기가 층 크기 부여 | 템플릿이 이미 10,9,10,9… 보유 |
| 소비 | `pattern_index` 로 참조 | `template_id` 로 통째 사용 |

→ 기존 탭에 끼워 넣으면 두 모델이 섞여 혼란. **분리가 맞다.**

### 원본 보존 원칙 (사용자 지시)
```
data/level_templates.json        ← 원본. 절대 수정하지 않음(읽기 전용 취급)
data/layered_patterns.json (신규) ← 크롭 결과만 저장. 원본 참조 id 보관
```
크롭본 엔트리:
```jsonc
{
  "lp_<원본id>_c8": {
    "name": "타운팝 level_42 (크롭 8)",
    "source_template_id": "21ff4576052__level_42",   // 원본 역참조
    "tier": "B",
    "orig_max_dim": 10, "max_dim": 8,
    "crop": [lcut, rcut, tcut, bcut],
    "lost_tiles": 2, "iou": 0.98,
    "level_json": { ... }          // 크롭된 층 스택
  }
}
```
→ 원본은 그대로 남고, 크롭본은 **되돌리기·재크롭 가능**.

### 탭 UI (`🧩 층별 패턴`)
- 목록: 썸네일(층 겹침 미니뷰) + Tier 배지 + `10→8` 크기표기 + 손실%/IoU
- 필터: Tier(A/B/C) · 층수 · 최대변 · 손실률
- 상세: **층별 그리드 나열** + 겹침뷰(홀수층 반칸 스태거) + 원본 대비 diff(잘린 칸 빨강)
- 액션: `프로덕션 사용 ON/OFF` · `재크롭(목표변 변경)` · `삭제`(크롭본만) · `원본 보기`
- 상단: **일괄 임포트** 버튼 — 원본 208개 스캔 → Tier 분류 → A·B 자동 편입

### 백엔드 엔드포인트 (신규)
```
GET    /api/debug/layered-patterns            목록(요약)
GET    /api/debug/layered-patterns/{id}       상세(level_json 포함)
POST   /api/debug/layered-patterns/import     원본 스캔 → Tier 분류 → A·B 저장
                                              body: {target_max_dim, iou_gate, tiers:["A","B"]}
PATCH  /api/debug/layered-patterns/{id}       enabled 토글 / 재크롭
DELETE /api/debug/layered-patterns/{id}       크롭본만 삭제(원본 무영향)
```

### 프로덕션 편입
- 기존 템플릿 배정(`templateAssignments`)과 **동일 경로** 재사용 — `template_id` 대신 `layered_pattern_id` 허용
- `enabled=true` 인 것만 배정 풀에 포함
- 보스는 기존 보스 템플릿 우선(충돌 없음)

## 6. 구현 단계

> 순서는 레드팀 권고(선행 파이프라인 수리 → 그 다음 신규 기능) 반영. 1~4단계는 **기존 프로덕션 출력도 함께 고쳐진다**.

### Phase 1 — 기존 결함 수리 (신규 기능 없이 즉시 이득)
1. **`index.tsx:1175` 죽은 삼항 수정** — `crop_max_dim` 이 항상 `undefined` 라 비보스 템플릿이 크롭 안 됨. 고치면 **Tier A 74개 즉시 사용 가능**(신규 저장소·탭 불필요).
2. **null 헤더 3개 복구** + `crop_level_to_max_dim` 빈-시퀀스 가드 + `analyze.py:2502` try 안으로 (R2).
3. **`_finalize_level` 보강** (R3·R5): `_repair_goal_output_direction` 신설 + `_strip_confusing_grass` 편입
   → 기존 출고분의 컨테이너 82개·grass 21개도 함께 수리.
4. **저장 원자화** — `tempfile.mkstemp + os.replace` (R8).

### Phase 2 — 층별 패턴 저장소 + 임포트
5. **저장소 신설** `data/level_shapes.json`(R9 명명) + CRUD
   - 원본 `level_templates.json` **읽기 전용**, 절대 수정 금지
   - id **`lp_<origid>` 고정**, `target_max_dim` 은 body, 소스당 활성 크롭 1개
6. **임포트 파이프라인** — 원본 스캔 → 크롭 → 검증 → Tier 판정 → 저장
   - 크롭 기준축 **`layer_0.row`** (R1). 무손실이면 `crop_level_to_max_dim` 재사용
   - 순서 **`_ensure_tutorial_unlock_gimmick` → `_finalize_divisibility_guarantee` → `_finalize_level`** (R4)
   - 크롭 후 **하드 단정**: 모든 층 `max(x)+1 ≤ N_i` and `max(y)+1 ≤ N_i` (`N_i = row_0 - i%2`). 위반 = 거부
   - **IoU 는 파이프라인 통과 후** 최종 `level_json` 기준으로 산출 (R9)
   - **메타 기록**: `min_level`(기믹 해금 최댓값), `tier`, `orig_max_dim`, `max_dim`, `crop`, `lost_tiles`, `iou`, `gimmicks`, `enabled`
7. **백엔드 엔드포인트 5개** (§5-b)

### Phase 3 — 프론트
8. **신규 탭** `🧩 층별 패턴` — 목록/필터(Tier·min_level·층수)/상세(층별+겹침뷰)/일괄 임포트/토글
   - `TabId` 추가 + **`App.tsx` 렌더 분기 반드시 추가**(빠뜨리면 빈 화면, R9)
   - `React.lazy` 로 지연로딩, 프리뷰는 `renderLevelCanvasPreview` 재사용(좌표키 규약 확인)
9. **배정 필터** — `min_level` 로 후보 제한(R6). `genModeFields` + 재생성 4경로에 id 배선(R7)

### Phase 4 — 마무리
10. **Tier C 추출**(후순위) — 층별 모양 → 5·6·7 → `pattern-create-multi`
11. **검증**
    - 크롭본 전수: 하드 단정 통과 / ÷3 0 / 사슬 0 / 링크 0 / 출력칸 정상 / grass 정상
    - `min_level` 필터 동작 확인(커튼 템플릿이 Lv241 미만에 안 배정되는지)
    - 크롭본으로 레벨 생성 → RL 통과율이 기존 대비 열세 아님

## 7. 【확정】1단계 분석 결과 + 결정

### 실측 Tier 분류 (208개)
| 목표 최대변 | A(무손실) | B(경미) | C(부적합) | **편입(A+B)** |
|---|---|---|---|---|
| **8** (채택) | **74** | **67** | 67 | **141 (68%)** |
| 7 | 23 | 22 | 163 | 45 (22%) |

- B 평균: 손실 6.7% / **IoU 0.94** → 레벨링 정체성 유지됨
- C 평균: 손실 26.6% / IoU 0.80 → 모양 붕괴
- IoU 0.85 vs 0.90 차이 미미(141 vs 135) → **0.85 채택**
- 원본 최대변 분포: 10칸 **178개(86%)**, 9칸 5, 8칸 6, 7칸 19

### 결정
| 항목 | 확정 |
|---|---|
| **목표 최대변** | **8** — 보스 레벨에서 이미 허용·검증된 크기(`crop_max_dim=8`, 가독성 한계 9 미만). 7로 하면 자산 78% 폐기 |
| **IoU 임계** | **0.85** |
| **Tier C 처리** | **C-1 패턴 추출** — 층별 고정은 포기하되 모양 정체성은 커스텀 패턴으로 살림 |
| **원본 보존** | **사본 추가**(`_cropped: true`, `_orig_size` 기록) — 되돌리기 가능 |

## 8. 리스크

- 크롭이 **골(craft/stack) 출력칸**을 격자 밖으로 밀 수 있음 → 크롭 후 골 방향 재검증 필요
- 층별 여백이 다르면 균일 크롭이 특정 층만 심하게 깎음 → **층별 최소 여백** 기준으로 잘라야 함
- 최대변 8은 기존 프로덕션(5·6·7)보다 큼 → **가독성/난이도 영향** 별도 확인
