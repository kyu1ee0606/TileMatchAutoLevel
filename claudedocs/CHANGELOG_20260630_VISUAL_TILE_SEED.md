# CHANGELOG 2026-06-30 — 비주얼 타일 시드 (visualTileSeed) 에디터 대응

> 게임측 v1.10.373 (sp_meowsgarden) 과 짝. t0 확장을 **배치(난이도)** 와 **비주얼 스프라이트 인덱스** 로 분리.
> 정본: `sp_meowsgarden/.../DESIGN_LEVEL_MAP_SCHEMA.md §4-1` · 에디터 알고리즘: `claudedocs/t0_tile_distribution.md`

## 배경
- 기존: t0 → `t1..t{useTileCount}` 만 사용. `useTileCount`(난이도용 종류 수)가 인덱스 상한 겸함 → useTileCount<13이면 t13~15 비주얼 구조적으로 못 씀.
- 신규: 배치(어느 위치가 같은 종류)는 `randSeed` 고정, **비주얼 스프라이트 인덱스만 `visualTileSeed`로 별도 결정** → useTileCount=6이어도 t13~15 등장 가능. 구체 시드면 **에디터 미리보기 == 인게임**.

## 필드 계약 (레벨 JSON)
| visualTileSeed | 동작 |
|---|---|
| `>= 0` | 결정적 (미리보기==인게임) |
| `-1` | 런타임 랜덤 (미리보기는 한 예시) |
| **없음** | 리맵 안 함 (현행/하위호환) |

## 프로덕션 기본값 — 구체 랜덤 시드 베이크
- `-1`: 매 실행 비주얼 변동 → 미리보기≠인게임 (핵심 요구 위반) → ❌
- `0`: 결정적이나 전 레벨 동일 시드 → 스프라이트 단조 (현행보다 다양성↓) → ❌
- **구체 랜덤 베이크(≥0)**: 결정적 + 레벨별 다양성 → ✅ 채택. `ProductionDashboard.bakeVisualTileSeed`가 생성/재생성 시 `1~2e9` 굽고 level_json 저장.

## 알고리즘 (인게임 ApplyVisualTileRemap과 100% 동일)
`assignT0Tiles`가 배치+셔플 끝낸 뒤 **별도 RNG**(배치 rng 미접촉)로:
1. assignments 사용 인덱스(1~15) 수집 → 오름차순 distinct (key/t16 제외)
2. `vSeed = seed<0 ? 0 : (seed+1)>>>0` (WELL512 seed 0=시간기반 회피)
3. `pool=[1..15]`, 부분 Fisher-Yates로 usedTypes.length개 distinct 선택 (`rand(i,14)` inclusive)
4. `map[usedTypes[k]] = pool[k]` (1:1)
5. assignments의 `t{1..15}`만 `t{map[id]}`로 재기록

골든값(usedTypes=[1..6]): seed 459838 → `4,1,7,9,12,3` / 12345 → `9,5,3,8,2,14`. **TS↔C# 바이트 일치 검증.**

## 변경 파일
| 파일 | 변경 |
|------|------|
| `frontend/src/engine/tileDistributor.ts` | `applyVisualTileRemap()` 추가 + `assignT0Tiles(visualTileSeed?)` 마지막 단계 |
| `frontend/src/engine/gameEngine.ts` | `distributeT0Tiles`/`initializeFromLevel` 패스스루 + `resolveT0TileTypes()` 공유 헬퍼(deep-clone 원본보호) |
| `frontend/src/utils/levelPreview.ts` | 평면 t0 셀을 분배 결과로 해소 → RL/Solvability/PatternSynth 미리보기 일치 |
| `frontend/src/types/index.ts` | `LevelJSON.visualTileSeed?` |
| `frontend/src/components/ProductionDashboard/index.tsx` | `bakeVisualTileSeed` (생성/재생성 3곳) |
| `backend/app/api/routes/gboost.py` | `townpop_level`에 `visualTileSeed` **조건부 emit** (있을 때만 → 레거시 무필드=게임 리맵 안 함) |
| `claudedocs/t0_tile_distribution.md` | 알고리즘 + 기본값 판단 문서화 |

## 렌더링 커버리지
- **엔진 경로** (GamePlayer/ProductionDashboard/PatternDebug): `distributeT0Tiles` 패스스루로 자동 반영.
- **캔버스 미리보기** (RL/Solvability/PatternSynth): `levelPreview` + `resolveT0TileTypes` 로 동일 선정.

## 미반영(의도)
- **백엔드 봇/솔버 무변경**: 리맵은 bijective(1:1) → 난이도/솔버블 동일. 시뮬 불필요.
- **백엔드 단독 생성(프론트 미경유)**: visualTileSeed 미베이크 → 게임 리맵 안 함 (레거시 안전).

## [추가 2026-06-30] 고정(t0 미사용) 레벨 비주얼 랜덤화 + 혼재 버그 가드

### 문제
- 생성기가 `useTileCount`를 **인덱스 상한으로도 해석** (`generator.py:3198` `valid_range={t1..t{useTileCount}}` 필터) → 고정 레벨은 항상 **t1..t{n} 순차**만 사용. t13~15 미사용.
- 최근 배치 실측: 고정 레벨 1414개 중 **1198개가 t1..t{n} 순차**.

### 개선 (프론트 baked relabel — 필터 우회)
- `ProductionDashboard`: 생성/재생성 시 `applyProductionTileVisuals(level_json, level_number)` 호출.
  - **순수 고정(t0無 + craft/stack無, level>3)**: 명시 타일 id → **1~15 풀 랜덤 distinct relabel** (`remapFixedTileVisuals`). 시드=level_number(결정적). bijective → 매칭/난이도/÷3 불변.
  - **stage 1~3**: 미적용(기존 t1..t{n} 유지) — 사용자 지정.
  - 필터/검증(다운스트림) 다 통과한 **최종 JSON에서 relabel** → `valid_range` 인덱스 상한 함정 우회(백엔드 무수정).

> ⚠️ **craft/stack 레벨 제외 (중요)**: craft/stack은 내부 타일이 t0(런타임 랜덤)이며 게임에서 명시타일과 **타입 공유**(GetEmptyTileList가 stack 내부 t0 포함). 명시만 relabel하면 craft 방출 타입 정렬이 깨질 위험 → `scanLevelTiles.hasCraftStack` 가드로 제외. **실측(최근 배치 1500)**: 명시 보유 레벨 중 진짜 순수(t0/craft/stack 전무)=160개만 relabel 대상. 나머지 1254개(craft/stack)+86개(t0)는 미적용(안전). craft/stack/t0 레벨 비주얼 다양화는 게임측 remap 재설계 필요(별도).

### 🔴 혼재(t0+명시) 레벨 버그 발견 + 가드
- 실측: 최근 배치 t0 레벨 86개 **전부 t0+명시 혼재** (순수 t0 = 0). t0 1~3개 + 명시 t1~t11.
- **버그**: 게임 `ApplyVisualTileRemap`은 t0 타일만 리맵 → 명시타일과 **공유하던 매칭 트리플**의 t0쪽만 비주얼 바뀜 → 트리플 붕괴 → **클리어 불가**.
- **가드**: `bakeVisualTileSeed`를 **순수 t0 레벨(명시타일 공유 0)에만** 적용하도록 제한. 혼재 레벨은 visualTileSeed 미설정 → 게임 리맵 안 함 → 안전(현행 유지).
- ⚠️ **게임측 잔여 개선 권고**(별도): `ApplyVisualTileRemap`이 명시타일과 공유하는 타입을 usedTypes/pool에서 제외하도록 수정하면 혼재 레벨도 안전하게 리맵 가능. 현재는 프론트 가드로 회피.

### 신규 함수 (index.tsx)
`scanLevelTiles`(t0/명시 스캔) · `buildVisualIndexMap`(시드→1:1 매핑, 인게임 remap 동일) · `remapFixedTileVisuals` · `bakeVisualTileSeed`(가드) · `applyProductionTileVisuals`(디스패처).

## 검증
- `npx tsc --noEmit` → 0 에러
- `python3 -m py_compile gboost.py` → OK
- TS↔C# 시드별 선정 바이트 일치 (459838/12345/-1)
- 고정 relabel: t1..t6 → 1~15 랜덤 distinct(t13~15 도달), 결정적(lvl 동일 2회 일치), bijective
