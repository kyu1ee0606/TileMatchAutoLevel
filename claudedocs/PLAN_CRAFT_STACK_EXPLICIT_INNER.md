# PLAN: craft/stack 명시 내부타일 지원 (t0 원천 제거 → 전 레벨 비주얼 다양화)

> 대상: 게임 `sp_meowsgarden` (Unity/C#) + 에디터 `TileMatchAutoLevel` (React/FastAPI)
> 목적: craft/stack 내부 타일을 "무조건 t0(런타임 분배)"에서 **명시 id 지정 가능**으로 확장 → 프로덕션 레벨의 t0를 에디터에서 사전 해소 → **전 레벨 순수 명시화 → 비주얼(t1~15) 전면 다양화**.
> 게임측 정본: `sp_meowsgarden/.../DESIGN_LEVEL_MAP_SCHEMA.md §1.3/§4-1`
> 상태: **확정(v1.0)** — 아래 §0.5 결정 6건 잠금.

---

## 0.5 확정 결정 (잠금)

| # | 항목 | 확정 |
|---|------|------|
| **A** | bake 위치 | **프론트엔드** (`ProductionDashboard`, 기존 `applyProductionTileVisuals` 자리 확장) |
| **B** | 내부 id 순서 | **`id_string[k]` = 게임 `stackCTileList[k]` = stackIndex k** (k=0 바닥/root, k=last 꼭대기). 게임 확정(TileRow.cs:161-217·L198-202). 에디터 emit이 이 순서 준수 + 구현 1단계 골든테스트로 뒤집힘 최종 확인 |
| **C** | 적용 스코프 | **신규 생성분만** + "재생성" 시 자동 bake. 기존 배치 전량 마이그레이션은 안 함(선택) |
| **D** | bot_simulator | **최소 파싱 안전만** (신포맷 `[count,ids]` 크래시 방지). 난이도는 bijective라 무영향 |
| **E** | 기존 `remapFixedTileVisuals` | **통합·대체** — 신 bake 로직이 순수160 경로 흡수, 기존 함수 제거 (알고리즘 `buildVisualIndexMap` 재사용) |
| **F** | gboost useTileCount | **자기보정 허용**(더 정확) — bake 후 former-t0 타입 explicit 카운트로 값 정정. 단 검증 6종에 "difficulty_tier 회귀 없음" 포함, 회귀 시 useTileCount 명시고정 폴백 |
| G11 | craft root | 데드코드 → **무관**(컨테이너, 손 안 댐) |

---

## 0. 핵심 원리 (왜 되나)

1. **에디터가 게임의 t0 분배를 이미 정확히 계산 가능** — `t0AssignmentMap`(gameEngine) / `assign_t0_tiles`(bot)가 게임 `ShuffleEmptyTiles`와 바이트 일치. 즉 "게임이 이 시드로 내부 타일을 무슨 타입으로 만들지" 100% 예측.
2. **그걸 그대로 구우면(bake)** → 내부/top-level t0가 전부 명시 id가 됨 → 게임이 재분배 안 함 → **런타임 결과와 동일**(회귀 0).
3. 구운 뒤 **보드 전체 타입→비주얼 1:1 relabel**(bijective) → 매칭/난이도/÷3 불변 + t1~15 자유 사용.
4. 단 게임이 **명시 내부 id를 읽어야** 함(현재 강제 t0) → 게임 1곳 핵심 수정 필수.

**결과**: 프로덕션 레벨에서 t0 제거 → craft/stack 포함 **모든 레벨** 비주얼 다양화 + `visualTileSeed`(런타임 remap) 불필요화(하위호환용으로 잔존).

---

## 1. 포맷 스펙 (계약)

### 현재
```json
"0_0": ["craft_s", "", [3]]        // [3] = 내부 개수만
```

### 확장 (하위호환)
```json
"0_0": ["craft_s", "", [3, "t7_t2_t9"]]   // [count, "id_string"]
```
- `[2][0]` = 내부 개수 (int) — **불변**.
- `[2][1]` = (선택) 내부 타일 id 문자열, **`_` 조인, N개**, **stackIdx 0..N-1 순서**. 각 id ∈ `t1`~`t15` 또는 `key`.
- `[2][1]` **없으면**(배열 길이 1) → **현행 t0 분배**(하위호환).
- 검증: id 개수 == `[2][0]`, 종류별 총합(보드 명시 + 내부 명시) `% 3 == 0`.

### top-level t0 (standalone)
```json
"2_3": ["t0",""]  →  "2_3": ["t9",""]   // 에디터가 계산된 타입으로 치환
```
게임은 명시 board 타일을 이미 그대로 렌더 → **게임 수정 불필요**.

### 순서 규약 (양측 필수 일치) — B 확정

**게임 확정** (TileRow.cs:161-217):
- `stackCTileList[k]` → `tile.stackIndex = k`, 위치 = `base + stackOffset*k`.
- `k=0` = **root = 바닥**(L170-172), `underStackedTile` 없음·`upperStackedTile=[1]` (L200-202).
- `k=last` = **꼭대기**(highest, 게임플레이서 먼저 pick).
- `GetEmptyTileList`가 `k=0→last` 순 수집 → `ShuffleEmptyTiles`가 그 순서로 타입 배정.
- 신포맷: `GetTileIDArr()[k]` → `stackCTileList[k]`.

**규약**: **`[2][1]`의 k번째 id = 게임 stackIndex k (0=바닥 ~ last=꼭대기)**.

**에디터**: gameEngine은 내부를 `stackIdx=count-1→0` 역순 수집(주석 "stackIdx0=top") → 게임(k=0=바닥)과 **표기 반대 가능성** → emit 시 게임 stackIndex k 기준으로 재정렬 필수. **구현 1단계 골든테스트**(레벨 bake→게임 로드→내부 위치별 대조)로 뒤집힘 확정, 뒤집혔으면 emit에서 reverse.

---

## 2. 게임측 수정 (sp_meowsgarden) — `DB_Level.cs` 중심

| # | 위치 | 현재 | 수정 |
|---|------|------|------|
| G1 | `CTileStackInfo` 필드 L115 | `//xTileIDList` 주석 | `List<string> xInnerTileIDs` 필드 선언 (또는 string) |
| G2 | `CTileStackInfo` 생성자 L124-153 | stackData[0]만 | `stackData.Count>=2`면 `stackData[1]` 파싱 → `xInnerTileIDs`. 없으면 null |
| G3 | `GetTileIDArr()` L155-168 | 무조건 t0 | `xInnerTileIDs != null`이면 그 배열 반환, 아니면 t0 (현행) |
| G4 | 파싱 분기 L341-379 | `Count>2` 스택 판정 | **불변** (여전히 `[2]` 존재로 스택 판정, 내부는 G2/G3가 처리) |
| G5 | `GetEmptyTileList` L797-872 | 내부 t0 수집 | **불변** — 명시 내부는 `tileIDNum!=0`이라 자동 미수집(분배 대상 제외). 정상 |
| G6 | `ShuffleEmptyTiles` L1114 | emptyTiles 분배 | **불변** — 전부 명시면 emptyTiles 비어 early-return(L1119). 정상 |
| G7 | `GetToAddIndexList` L1050 | ÷3 카운트 | **불변** — 명시 내부가 `GetEmptyTileList(true)`에 명시로 잡혀 카운트됨. 에디터가 ÷3 보장 전제 |
| G8 | `Tile.Init` (Tile.cs:428) | 명시 id→sprite | **불변** — 이미 명시 렌더 |
| G9 | 매칭/독 (Dock.cs) | tileIDNum 기반 | **불변** — 내부/외부 구분 없음 |
| G10 | 방향 `xStackDirection` L137 | root split | **불변** — root id "craft_s" 유지 |
| G11 | `SetCraftRootTileID` L194-209 | ~~craft root t0 강제~~ | ✅ **해결 — 데드코드(호출부 없음)**. root는 "craft_w" 유지·tileIDNum=-1=컨테이너(매칭 안 됨). **손댈 필요 없음** |

**핵심 = G1~G3 (약 15줄).** root(G11)는 컨테이너라 무관 — **내부 타일만** 처리. 나머지는 불변이거나 점검만. `GetTileIDArr`가 stackData 접근 필요 → 생성자에서 `xInnerTileIDs` 필드에 저장(G1/G2) 후 G3에서 참조.

### 게임측 하위호환
- 구 레벨 `[3]` → stackData.Count==1 → `xInnerTileIDs=null` → G3가 t0 반환 → **완전 동일 동작**.
- 신 레벨 `[3,"..."]` → 명시 파싱.
- 회귀 0.

---

## 3. 에디터측 수정 (TileMatchAutoLevel)

### 3-A. 사전계산 + bake + relabel (신규 핵심 로직)

**어디**: **프론트엔드 `ProductionDashboard`** (기존 `applyProductionTileVisuals` 자리 확장) — A 확정. bot sim **후** 실행이라 난이도 bijective 안전. TS 포트(`tileDistributor`/`gameEngine`)로 내부 타입 계산.

**절차** (레벨당):
1. 게임 분배 재현 → `t0AssignmentMap` 획득 (gameEngine `resolveT0TileTypes` 확장: 내부 stackIdx 타입 포함).
2. 보드 전체 논리 타입 수집: board 명시 + top-level t0(계산) + craft/stack 내부(계산).
3. `buildVisualIndexMap(usedTypes, seed=level_number)` → 논리→비주얼 1:1 (기존 함수 재사용).
4. **bake**:
   - top-level t0 셀 → `tiles[pos][0] = "t{visual}"`.
   - craft/stack → `tiles[pos][2] = [count, "v1_v2_..vN"]` (내부 stackIdx 순서, relabel 적용).
   - board 명시 타일도 relabel 적용(전체 bijective 일관성).
5. stage 1~3 / randSeed<0 → skip(현행 유지).

### 3-B. 파일별 수정

| # | File:Line | 현재 | 수정 |
|---|-----------|------|------|
| E1 | `generator.py:703` `_create_goal_tile` | `[count]` emit | (선택) 그대로 두고 에디터 bake 단계에서 확장. **또는** 여기서 내부 id 계산 emit |
| E2 | `generator.py:1431-1444` | craft/stack 컨테이너만 카운트 | 내부 명시 id 배열 파싱 → 종류별 카운트 포함(÷3 계산) |
| E3 | `generator.py:984-1479` ÷3 | 내부 t0 전제 | 내부 명시 종류별 ÷3 보장 (bake가 게임 분배 결과라 이미 ÷3 → 검증만) |
| E4 | `gboost.py:403,496,521-523` | tiles dict 그대로 직렬화 | **불변** — `[count,"ids"]` 배열 자동 운반. `_count_tiles_in_level`은 [0] 계속 count로 읽음(OK) |
| E5 | `types/index.ts:7` `TileData` | `[string,string,number[]?]` | `[string, string, (number|string)[]?]` 또는 헬퍼로 `[count, idString]` 수용 |
| E6 | `gameEngine.ts:356-384` 수집 | 내부 t0로 펼침 | `extraData[1]` 있으면 그 id를 t0AssignmentMap에 직접 세팅(계산 skip) |
| E7 | `gameEngine.ts:509-510,728-729` | t0AssignmentMap 배정 | 명시 id override 경로 추가 |
| E8 | `bot_simulator.py:1339-1545` | 내부 t0 전제 | `stack_info[1]` 있으면 그 id 사용(난이도 시뮬 정합) |
| E9 | `levelPreview.ts:76-94` | 컨테이너만 렌더 | (선택) 내부 타일 비주얼 표시 — `extraData[1]` 파싱해 미리보기 |
| E10 | `resolveT0TileTypes`(gameEngine) | 평면 t0만 | craft/stack 내부 stackIdx 타입까지 반환하도록 확장(bake용) |

### 에디터측 하위호환
- 기존 배치(구 포맷)는 재생성 전까지 그대로. bake는 **신규 생성/재생성 시**만.
- randSeed 구체값 전제(프로덕션 OK). -1이면 bake 불가 → 현행 t0 유지.

---

## 4. ÷3 보장 (핵심 제약)

- **원리로 자동 충족**: bake하는 내부 타입 = 게임 `DistributeTiles`가 만든 값 = **이미 종류별 ÷3**. relabel은 bijective → ÷3 보존.
- 에디터는 **검증만**(방어): bake 후 종류별 카운트 % 3 == 0 assert. 실패 시 로그 + 해당 레벨 bake skip(현행 t0 폴백).

---

## 5. 검증 계획

1. **게임 하위호환**: 구 포맷 레벨(`[3]`) 로드 → 기존과 100% 동일(스폰/매칭/클리어). Unity 컴파일 0에러.
2. **신 포맷 스폰**: `[3,"t7_t2_t9"]` 레벨 → 내부 타일이 t7/t2/t9로 스폰·렌더, 매칭 정상.
3. **🔴 B 골든테스트(순서)**: bake한 스택 레벨 게임 로드 → 내부 타일 **위치별(바닥~꼭대기)** 타입이 에디터 emit `id_string[k]`와 일치. 뒤집힘 없음 확정. (뒤집혔으면 emit reverse 후 재검)
4. **bake 무회귀**: 동일 레벨 (a)구 t0 런타임 vs (b)bake(relabel 없이) → 매칭/솔버블/봇클리어율 동일.
5. **에디터=게임 일치**: bake+relabel 레벨 미리보기 == 인게임 스폰(픽셀).
6. **÷3**: 무작위 100레벨 bake → 종류별 ÷3 assert 통과.
7. **혼재 안전**: craft/stack + board 명시 공유 타입 → relabel 후 매칭 트리플 유지(전체 bijective).
8. **F 티어 회귀**: bake 전/후 `difficulty_tier`(클리어% 티어) 변동 없음. 변동 시 useTileCount 명시고정 폴백.

---

## 6. 리스크 & 완화

| 리스크 | 완화 |
|--------|------|
| stackIdx 순서 양측 불일치 | §1 순서 규약 고정 + 골든값 대조(게임 로그 vs 에디터) |
| ÷3 깨짐 | bake=게임분배 결과라 자동 ÷3 + 검증 assert + 폴백 |
| craft root 타일 자체 id(G11) | 조사: craft root가 매칭 타일인지 컨테이너인지 확인 후 처리 |
| 구/신 포맷 혼재 배치 | 포맷 판정은 배열 길이 → 레벨별 독립, 혼재 안전 |
| randSeed=-1 레벨 | bake 불가 → 현행 t0 유지(가드) |
| bot_simulator 미반영 시 난이도 오측 | E8 동반 필수(게임/봇 동일 파싱) |

---

## 7. 작업 순서 (단계별)

**Phase 1 — 게임 (게이팅)**
1. G1~G3 구현(`xInnerTileIDs` + 파싱 + `GetTileIDArr` 분기) + G11 조사.
2. 하위호환 테스트(구 포맷) + 신 포맷 수동 레벨 스폰 테스트.
3. 스키마 doc §1.3 갱신(포맷) + §4-1 연계.

**Phase 2 — 에디터 계산/bake**
4. E10(resolveT0TileTypes 내부 포함) + E6/E7(gameEngine 명시 override).
5. bake+relabel 로직(3-A) `ProductionDashboard`.
6. E5(types) + E9(preview, 선택).

**Phase 3 — 백엔드 정합**
7. E2/E3(generator ÷3 카운팅) + E8(bot_simulator 파싱) + E4 확인.

**Phase 4 — 검증/배포**
8. §5 검증 6종.
9. Unity 빌드·배포 + 에디터 배포.
10. 문서 최종(CHANGELOG 양측 + DECISIONS).

**게이트**: Phase 1 완료·검증 전 Phase 2 진행 금지(게임이 명시 내부 못 읽으면 bake 무효).

---

## 8. 기존 작업과의 관계

- **supersede**: 현 `remapFixedTileVisuals`(순수 고정 160개만) → 본 계획이 전 레벨 커버로 확장. buildVisualIndexMap/relabel 알고리즘 **재사용**.
- **visualTileSeed(게임 v1.10.373)**: bake 방식에선 불필요(생성 시 relabel). **하위호환/롤백용으로 잔존**. bake 레벨은 visualTileSeed 미설정.
- **혼재 버그 가드**: bake로 t0 소멸 → 혼재 자체가 사라져 근본 해소.

---

## 8-1. 🔴 배포 순서 게이트 (필수 — 안 지키면 레벨 깨짐)

**게임(Phase 1) 배포 → 플레이어 업데이트 확인 → 그 다음 에디터 신포맷 emit.**

- 이유: 에디터가 board relabel + `[count,ids]` emit했는데 **구 게임**이 받으면 → 구 게임은 내부를 t0 강제·재분배(logical) → relabel된 board와 **불일치 → 매칭 붕괴**.
- 완화: 에디터 emit에 **게임 버전 게이트**(지원 버전 이상에만 신포맷). 미지원 타겟이면 현행(t0 + 순수레벨 visualTileSeed) 유지.
- 기존 배포 배치: 자동 마이그레이션 안 됨. 신규 생성분만 bake. 구 레벨은 t0로 계속 정상 동작.

## 8-2. 전체 문제없음 점검 (요약)

| 항목 | 판정 |
|------|------|
| 게임 수정 범위 | 최소·격리(G1~G3), 하위호환 완전 ✅ |
| root 처리(G11) | 데드코드 확인 → 불필요 ✅ |
| ÷3 | bake=게임분배결과 → 자동 충족 + 검증 ✅ |
| 결정론 재현 | 포트 바이트일치(검증필요) — 골든값 대조로 확정 ⚠️ |
| 매칭/솔버블/난이도 | bijective → 불변 ✅ |
| randSeed=-1 | bake 불가 → t0 유지(가드) ⚠️ |
| bot_simulator | E8 동반 필수(파싱) — 누락 시 난이도 오측 ⚠️ |
| 배포 순서 | 게임 먼저(§8-1) — 어기면 붕괴 🔴 |

→ **구조적 결함 없음.** 주의점은 (a)배포 순서 게이트 (b)포트 골든값 검증 (c)bot 동반 (d)-1 가드. 전부 계획에 반영됨.

### 애매점 6건 해소 (전부 확정 — §0.5)
- A(위치)=프론트 / B(순서)=게임 stackIndex k 확정+골든테스트 / C(스코프)=신규만 / D(bot)=파싱안전 / E(중복)=통합 / F(카운트)=자기보정+티어검증. **미결정 0.**

## 9. 산출물

- 게임: `DB_Level.cs`(G1~G3) + 스키마 doc.
- 에디터: gameEngine/tileDistributor/ProductionDashboard/types/levelPreview + generator/bot_simulator/gboost.
- 문서: 본 PLAN + 양측 CHANGELOG + DECISIONS(설계 근거).
- 테스트: §5 6종 결과.
