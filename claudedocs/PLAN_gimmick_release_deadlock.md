# 기믹 해제조건 데드락 (체인 외 전 기믹) — 조사·해결 계획

작성 2026-07-30. 상태: **계획(착수 전)**. 시니어 3명 토론 + 실측 검증.

## 1. 문제 (사용자 실제 인게임 보고)
Lv81+ CHAIN 기믹: 체인 타일은 **잠김**, **수평 인접(좌/우, 같은 층) 타일이 픽되면** 해제.
보고: 3개 체인 수평 나란히 + 좌우에 일반타일 없음 → 영구 해제불가 = **인게임 하드 데드락**. 근데 타일수 ÷3 정상, RL/솔버 통과.

### 실측 재현 (확정)
`batch_1785326686078` **Lv81 layer_0**:
```
y2:  .    -    .    C    C    C    .
        (2_2빈)  3_2  4_2  5_2  (6_2빈)
3_2=[t12,chain] 4_2=[t12,chain] 5_2=[t13,chain]
```
좌우 양끝 빈칸 → 3연속 전부 해제불가. meta: pred=0, `unclearable_suspect`.

## 2. 근본원인 (시니어 3명 + 실측 합의)
### (a) 검사기가 "존재"만 봄, "픽 가능성" 안 봄
`bot_simulator.py:1966-1968` `_check_chain_impossible`:
```python
neighbor = layer_tiles.get(neighbor_pos)
if neighbor and not neighbor.picked:   # ← 잠긴 체인도 '유효한 해제자'로 카운트
    has_horizontal_neighbor = True
```
→ 잠긴 체인끼리 서로 이웃이면 **클로저 데드락 미검출**. `_check_grass_impossible`(:1887-1896) **동일 결함**.
- 실측 대조: 고립 체인(런1, 좌우 빈칸)은 잡힘(Lv450 pred=0). **런2+ 클로저는 못 잡음**.

### (b) 규칙이 4~5곳에 divergent 복제 + 순서 역전
| 위치 | 컨테이너체크 | 커버리지 | Lv81 판정 |
|---|---|---|---|
| `generator.py:14903` `_validate_and_fix_obstacles` | O | O | 거부(정상) |
| `generator.py:8438` `_add_chain_obstacles_to_layer` | O | O | 거부(정상) |
| `generator.py:7548` `_ensure_tutorial_gimmick_count` | **X** | **X** | **통과(치명)** |
| `analyze.py:2000` 인라인 strip | **X** | **X** | **통과(치명)** |
| `bot_simulator.py:1958` | **X** | n/a | **통과** |

**순서 역전**: 정상 검증기(`_validate_and_fix_obstacles`)는 `generate()` **1087/1093**에서 실행 → 튜토리얼-ensure(**1096, ~1489**)가 **그 뒤에** 기믹 추가. 마지막 변경자가 검증 뒤.
> LINK는 이 함정을 이미 발견해 `_strip_orphaned_link_tiles`를 **2회** 호출(1464 + 1492, 주석에 명시). **체인은 2회차가 없음** = LINK에서 해결한 버그 클래스의 체인 인스턴스.

### (c) 진짜 주범 = `_ensure_tutorial_gimmick_count` (시니어1 발견, 게임 C# 대조 완료)
`generator.py:7524-7571` 체인 분기: candidates를 **스냅샷 1회**로 만들고(7533-7558) **N개를 루프서 변환**(7562-7570) — **재검사 없음**:
```python
if not ndata[1] or ndata[1]=="frog": candidates.append(pos)   # 스냅샷 시점만
...
for pos in candidates: tile_data[1]="chain"   # ← 다른 후보의 앵커를 체인으로 덮음
```
Lv81(체커보드 패턴, `_preserve_pattern`, row2에 원래 col 1,3,5만): `3_2·4_2·5_2` 셋 다 스냅샷 시점엔 plain 이웃 보유 → 셋 다 통과 → **셋 다 체인화 → 양끝 앵커 소멸**(2_2/6_2는 패턴에 없음). `needed=3`(Lv81 튜토리얼 최소, :1101/:1111).
- 호출이 **`generator.py:1111` = 마지막 `_validate_and_fix_obstacles`(1087/1093) 뒤** → 재검증 안 됨.
- 다른 체인 배치기와 달리 `_is_position_covered_by_upper` 앵커체크 **누락**(cf. 8446, 9047, 10580, 14910).
- **구제 경로서 2번째 재주입**: `generate.py:157-172`가 역생성 구제 후 `playability_warning=False`로 **지운 다음** 튜토리얼 체인 3개 재주입(재검증 없음) → **솔버블 인증된 레벨이 다시 깨짐**.
- 실측: Lv81이 4배치서 반복(`1784228048122`, `1784244064945`, `1784312413374`, `1785326686078`) — 튜토리얼 강제3체인 × 희소 체커보드 패턴 조합.

### (d) 내 전제 2개 정정 (시니어1, 게임 C# 대조)
**정정A — 시뮬은 게임 규칙 안 틀림.** 잠긴 체인 픽 불가 확정: `bot_simulator.py:493-494`(`CHAIN → unlocked` 반환), `:2711`(`if not tile.can_pick(): continue`). 게임 대조: `TileEffect.cs:932-951`(`IsNearTile(...,true)`=수평만, `CheckUpperTileExist()==false`), `:1066-1069`(`case Chain: if(chainRemoved==false) canPick=false`). **일치.**
→ 약한 검사가 false-pass를 만드는 게 아니라, 봇은 "합법수 없음"으로 **실제 0% 실패**(측정 clear_rate=0.0). 문제는 **늦은/약한 검출** = 생성단계 구조적 게이트로 못 씀.
→ **게임의 자체 검출기도 동일하게 약함**: `TileEffect.CheckEffectTileCanUncover()`(`TileEffect.cs:1338-1345`) → `Tile.CheckRemainNearTile`(`Tile.cs:1523-1546`)도 `checkTile!=null && !m_Picked` = **존재 검사**. ∴ 인게임서 `FailReason.Chain` 자동실패 팝업도 **안 뜨고** 플레이어는 그냥 합법수 0 = 보고된 하드 데드락.

**정정B — fast path가 데드락 검사 스킵 안 함.** `generator.py:1210-1225`의 else 분기(skip=True)도 `_ensure_no_deadlock(max_attempts=2)` → `_quick_deadlock_check`(봇 5회, `clear_rate<0.3`, :14504) 실행. Lv81서 **발동함**. 근데 **고칠 수도 거부할 수도 없음**: 수단이 reseed/reshuffle뿐(:14841-14848), 수용선 `best_clear_rate>=0.1`(:14855), 실패시 로그 + `_last_playability_warning=True`(:1227)만.
→ ∴ "검사 없음"이 아니라 **"검사하고도 통과시킴"**.

## 3. 정적 vs 동적 (시니어3 측정, 채택)
**게임 동역학은 monotone**(픽은 제거만 함, 재잠금/재추가 없음) → "결국 픽 가능(EP)"의 **최소 고정점 = 정확한 답**(근사 아님). 해제조건 충족성은 **정적 결정가능**.

| | 비용 | Lv81 판정 |
|---|---|---|
| BotSimulator 10회(`_ensure_no_deadlock`) | 711ms/레벨 → 1500개 **~18분** | **clear_rate=1.0 (틀림)** |
| 정적 고정점 클로저 | **0.249ms**/체인레벨 → 배치 전체 **~48ms** | dead=1 (정답) |

→ **2857배 싸고 정확**. `skip_deadlock_check=True` 유지(스케줄링 오라클로 도달성 질문 풀지 말 것).
- 정적 결정가능: chain, link, grass, header-OOB, ÷3, 컨테이너 출력칸
- 시뮬 필요: max_moves, dock 용량, 트리플 순서, timea, 난이도

## 4. 해결책: `_strip_unreleasable_gimmick_tiles` (고정점 클로저)
`_strip_orphaned_link_tiles` 형제. 로그태그 `[RELEASE_SANITIZE]`.

**선행 리팩터(수술적)**: `generator.py:7064` `_is_position_covered_by_upper` → `_covering_keys(...)->Set` 추출 + 불리언은 1줄 wrapper. 기존 10개 호출부 무변경. (커버리지가 **집합**이어야 discharge 가능.)

**알고리즘**
```
seed: td[1] 빈칸 or 비해제조건 속성, AND _covering_keys()=={}
     (craft_/stack_ 컨테이너: 커버리지 해제용으론 EP 진입, 해제자로는 제외)
propagate: coverers(t) ⊆ EP AND (속성 무해제조건 or RELEASE_PRECONDITION[attr](EP,...))
   chain: col±1 같은층 이웃 ∈ EP, 컨테이너 아님
   grass: 4방향 중 ≥2가 EP (겹수 반영)
종료: EP 단조증가·N상한 → O(N·d)
위반: 해제조건 속성인데 고정점에서 EP 밖
```

**왜 클로저인가(로컬규칙 이식 금지)** — 시니어3 실측(20배치, 체인레벨 3241, 체인타일 14695):
- 로컬규칙 semantics: **9300개(63.3%) 플래그** ← 96.3%가 `covered`(영구가림 가정 오류)
- 정적 고정점: **22개(0.15%)**
→ `_validate_and_fix_obstacles`를 끝으로 옮기면 **체인 기믹 63% 파괴**. 클로저가 유일하게 감당 가능.

**수리 = 속성 relabel `td[1]=""`**
| 방식 | ÷3 | 패턴모양 | 판정 |
|---|---|---|---|
| relabel(chain→plain) | 보존 | 보존 | **채택** |
| relocate(안전 호스트로 속성 이동) | 보존 | 보존 | 튜토리얼 레벨 2순위 |
| 이웃 타일 삽입 | 깨짐 | 깨짐 | **금지**(홀짝 격자 2칸간격 파괴, header-OOB 유발) |
| 타일 삭제 | 깨짐 | 깨짐 | **금지** |

**수리 순서(최소침습)**: EP계산 → 튜토리얼 기믹이면 relocate 우선 시도 → 아니면 relabel → EP 재계산(연쇄 해방, 단조라 종료) → 안전 호스트 전무면 강제배치 말고 `playability_warning`으로 재생성 위임.
**근본(생성단계)**: `chain ∈ obstacle_types`면 **패턴 선택 단계**에서 수평인접 가용성 게이트. Lv81은 94타일 중 수평쌍 **1개뿐**(컨테이너가 격자 깨서 생긴 것) → 사후수리 불가. **체인은 shape-coupled 기믹**.

## 5. 방어 배치 (defense-in-depth)
| # | 레이어 | 위치 | 모드 |
|---|---|---|---|
| 1 | generate() 끝 | `generator.py` 1492(LINK백스톱)~1497(max_moves) 사이 | REPAIR |
| 1b | 규칙 통합 | 7548/8438/14903 이웃테스트 → 공용 `_chain_release_ok()` | REPAIR |
| 2 | tune | `tune.py:433`, `:1004` (link sanitize 옆). `_gimmick_arrangement`는 현재 체인검증 **0** | REPAIR |
| 3 | 보스템플릿 | `analyze.py:2000-2005` 인라인 strip 제거→클로저 | REPAIR |
| 4 | 저장 게이트 | `production_store.py` `_enforce_release_closure_gate`(`_enforce_header_bounds_gate:145` 미러), `:200`서 호출 | **FAIL-CLOSED** |
| 5 | 프론트 self-heal | `index.tsx` `sanitizeUnreleasableGimmicks` → `sanitizeOrphanLinks/sanitizeHeaderOob` 옆(RL측정 **전**) | REPAIR |
| 6 | export 게이트 | `ProductionExport.tsx` `_bad`에 `_hasUnreleasableGimmick` 추가 | **FAIL-CLOSED** |

- 4는 REPAIR 금지: 낙관적동시성 경계(`base_version` 계약 거짓말 방지) → 플래그만(÷3/OOB 게이트와 동일).
- **6이 Lv81을 막았을 레이어**(해당 레코드 `verification_passed=true`로 4·6 다 통과).
- JS미러 의무(CLAUDE.md) + `tsc --noEmit`. **미러는 index/Export 공용 1개**(3번째 복제 = 이 버그 재생산).

## 6-0. 【최종 확정】게임 C# 실동작 대조 완료 — 13/13 기믹
에이전트 3팀이 게임 C#(`sp_meowsgarden/.../Tile_Script/InGame/*.cs`) 직접 대조 + 내 프로덕션 실측 교차검증.

### 전역 사실 (판정 기준)
- **게임에 "합법수 0 → 자동 리셔플" 없음.** 셔플은 유료 아이템 + `m_SpawnIndex`(타입)만 교환(`TileGroup.cs:1518-1548`) → **픽불가 락 구제 불가**. ∴ 무알림 소프트락은 레벨 포기만 가능.
- **실패 경로 4개뿐**: dock overflow(`Dock.cs:1879`), bomb(`Dock.cs:2324`), TimeOver(`LevelTimer.cs:121`), can't-uncover **Grass/Chain/Ice**(`TileGroup.cs:2380-2440`). **frog/teleport/curtain/unknown FailReason 없음.**
- **게임에 goal/mission 카운터 자체 없음**(`grep goal` 0건). 클리어 = 전체 타일 픽. ∴ "골 달성 불가 → 언클리어러블"은 **도달 불가 실패모드**.
- **컨테이너 내부타일은 root 셀 좌표 공유**(`DB_Level.cs:158`) → 데이터 모델에 "출력칸" 개념 없음.

### 🔴 검증기 필요 = 2개
| 기믹 | 확정 근거 | 검증기 |
|---|---|---|
| **chain (81)** | 게임 검출 임계값 `CheckRemainNearTile(true) < 1`(`TileEffect.cs:1341`)이 *살아있는* 이웃만 셈(`Tile.cs:1542`) → **3연속은 count=1 → `1<1` false → FailReason.Chain 영구 미발동** = 무알림 소프트락. 구제 없음. | **고정점 클로저**(전이). 0.249ms. 수리 `td[1]=""` relabel |
| **timea (341)** | 타이머 **살아있음·레벨단위**(`LevelController.cs:1191-1212`), 만료 = 하드실패. 생성기는 난이도만 보고 45/60/90s 배정(`generator.py:1271-1278`) **타일수 무연동**. 시뮬 `timea` 참조 **0회** → 에디터가 LOOSER(위험방향) | **`timea >= 타일수 × 초/타일 × 여유`** 게이트 |

**timea 실측(현재배치)**: timea>0 **116레벨**(45s×62, 60s×35, 90s×19) / `passed=true` **27건** / 초당타일 0.6s 미만(물리적 촉박) **48건, 그중 passed=true 11건**. 최악 `Lv1280 45s·144타일=0.312s/타일 passed=TRUE`, `Lv1150 45s·183타일=0.246s/타일`.
> ⚠️ 에이전트는 구 `test_results`(timea 전무) 기준으로 "latent"라 판정 → **내 프로덕션 실측이 정정**. 라이브 위험.

### 🟡 형태 변경 = 1개
**link (51)** — orphan link는 데드락 아니라 **게임 크래시**: `TileEffect.cs:464-465`가 `linkedTile` null 역참조(NRE) → `TileGroup` 루프 안에서 터져 **이후 전 타일 effect init 유실**. craft/stack 셀 지목도 동일 NRE(root CTile 참조 불일치).
→ 우리 `_strip_orphaned_link_tiles`(`generator.py:12390`)가 **유일 방어**(실측 orphan 0건). 파이프라인 재정렬로 구멍 재개 가능(Lv81과 동일 실패모드) → **조용한 수리 대신 fail-the-build 정적 단정으로 승격**.

### ❌ 검증기 불필요 = 10개 (추가 금지)
| 기믹 | 반증 근거(게임 C#) |
|---|---|
| craft (11) | 출력칸 밖(83건): 이미 스폰된 타일이 셀만 이동 → `FindAllUpperTiles` 미발견 → **항상 픽가능**. 점유(16건): 점유자가 craft 스택 top으로 **편입**(`TileCraft.cs:243-268`) → 픽하면 방출 재개 = 자기해소. 컨테이너 영구가림 없음(`c_TileList` 미포함) |
| stack (21) | 전 내부타일 **동일 셀** 스폰(`TileRow.cs:161-189`), 셀 이동 없음(`AddOffset`은 craft 전용) → "출력칸 OOB 83건"은 **에디터 모델 허상**. 파일 내 픽은 intra-pile(`Tile.cs:1235-1250`) |
| ice (31) | 인접조건 없음(어느 픽이든 1겹). 소진 케이스는 게임이 `CheckIceTileCanUncover`(`TileGroup.cs:2446-2481`) → **FailReason.Ice 명시실패**. 시뮬 정확 포팅. 가려짐 771건 = 정상(틱 일시정지) |
| grass (151) | `CheckRemainNearTile() < 남은겹수` → **FailReason.Grass 의도된 실패**(사용자 확인). 겹 감소 진행되며 자기수정. 실측 stuck 2건 |
| unknown (191) | 타입(`xTileID`)·기믹(`xEffect`) **별개 필드**(`DB_Level.cs:375-376`), reveal은 애니/sortingOrder만 → **multiset 불변 = ÷3 못 깸**. 실측 ÷3 위반 0건 |
| curtain (241) | **전용 안티데드락 루틴**(`TileGroup.cs:1713-1749`, 매 픽): 커튼만 남으면 1개 **무력화**(`effectActived=false` → 영구 픽가능) 또는 다 닫혔으면 **강제 open**. open 168/close 457 실존 |
| bomb (291) | **가려지면 틱 안 함**(사용자 확정 + 시뮬 `not _is_blocked_by_upper` 일치) → 가려진 폭탄 161건 **무해** |
| key (111) | 락 슬롯 = **실제 보드의 key 타일 수/3**(`Dock.cs:741-752`) → 자기정규화. 생성기 `unlockTile<=2` 캡 + 슬롯 하한 5. **t0 없으면 완전 무력화**(`DB_Level.cs:1148` early return) — 실측 t0 전무 97.5% |
| frog (391) | 초과 frog **파괴**(`FrogManager.cs:101-124`), 후보 0이면 **전부 파괴** → 최종타일 영구점유 **불가**. `onFrog`가 자기 타일 제외 → 제자리·중첩 불가 |
| teleport (441) | **타입만 단일사이클 회전**(`TileGroup.cs:1676-1682`) → **multiset 보존 = ÷3 유지**. 위치·이웃·레이어 불변 → 스트랜딩 구조적 불가 |

### chain 세부 — 필요한 건 클로저 1가지뿐
| 시나리오 | 앵커 픽 후 count | 게임 검출 | 판정 |
|---|---|---|---|
| 앵커 1개 → 순서 실수(가려진 동안 픽) | **0** → `0<1` ✅ | FailReason.Chain 발동 | 설계된 실패, 회피가능. 실측 122레벨(passed=true 6) — **검증기 불필요** |
| **이웃이 잠긴 체인(2+연속, 양끝 없음)** | **1** → `1<1` ❌ | **영구 미발동** | 🔴 **유일 진짜 버그** |

### 런타임 보드 실측 (raw JSON 과대보고 교정)
craft 방출칸을 유효 앵커로 인정 + 컨테이너 제외 + 전이 클로저:
- 현재배치 stuck **5레벨**(450,590,770,780,1480) — `passed=true` **0건**
- 내보낸배치 stuck **3레벨**(1180,1360,1370) — `passed=true` **0건**
- (raw JSON 스캔 52건 → 런타임 5건. 시니어1 경고 확증)

### 게임측 버그 (우리 수정 불가 — 게임팀 보고용)
1. `TileGroup.cs:1655-1662` remove-while-iterating → **multiset 손상** 가능 → 카운트상 언클리어러블
2. `TileGroup.cs:1650-1653` early return이 `onTeleport=false` 리셋 전 → **영구 픽불가 타일**
3. `TileEffect.cs:464-465` orphan link **NRE** (우리 sanitizer가 차단 중)
4. `FrogManager.cs:134` `isFrogMoving` 미리셋(현재 무해)
5. `teleportRandSeed` **dead config**(`TileGroup.cs:1633` 미사용, `:1635` unseeded) → 재현 불가

### 부수 개선 여지 (정확성 무관)
- 에디터가 게임보다 **엄격**한 곳(무해하나 난이도 왜곡): curtain 구제 미모델링 → 커튼레벨 과잉거부·클리어율 저평가. stack에 `_is_blocked_by_upper` 적용. key `7-unlockTile` 무조건 적용.
- `_relocate_tiles_from_goal_outputs`를 `craft_*`만으로 축소 가능(stack은 개념 없음).
- 시뮬이 link 픽을 dock **2칸**으로 세는지 확인 필요.
- `TileDistributor` 포트가 현행 C# color-bucket `DistributeTiles`와 다르고 `DB_Level.cs:1158-1164` Fisher-Yates 누락 → **t0 배포 켜기 전 수정 필요**(현재 t0 전무라 moot).

## 6. 【초기 스윕 기록】81 이후 전 기믹 (시니어2 + 실측) — 위 §6-0이 최종
기믹 해금(frontend/src/types/levelSet.ts:161): key111, grass151, unknown191, curtain241, bomb291, timea341, frog391, teleport441.
게임 정본 규칙표: `sp_meowsgarden/.../DESIGN_UNLOCK_CONTENT.md:889-897` (§16.3) — 스키마는 enum만.

| 기믹 | Lv | 시니어2 RISK | **실측 검증** | 판정 |
|---|---|---|---|---|
| chain | 81 | (확정) | stuck 52건(런1 49 / **런3 3**=Lv81) | **확정 HIGH** |
| grass | 151 | HIGH(체인과 동형 클로저) | **stuck 2레벨**(Lv200, Lv1467) 확인 | **확정, 빈도 낮음** |
| bomb | 291 | HIGH(커버리지 parity-blind `generator.py:8727-8731`) | 가려진 폭탄 161건 존재하나 **사용자 확정: 가려진 폭탄은 틱 안 됨** | **반증 → LOW**. 시뮬도 `not _is_blocked_by_upper`로 동일 게이트(`bot_simulator.py:1757`) = **정확**. 161건 무해. 남는 건 배치 위생(parity-blind union)뿐 |
| unknown | 191 | HIGH(`_ensure_unknown_tutorial_count`가 ÷3 finalize **뒤** 타일 신규생성 `:7906-7910`) | **Lv191 ÷3 위반 없음**(현 배치) | 코드경로 리스크 실재, **현 배치 미발현** |
| curtain | 241 | HIGH(생성기가 `curtain_close`만 emit → 전역 phase 동기 → lockstep freeze) | **반증: open 168 / close 457 존재** | **전제 반증** → 재검토 필요 |
| key | 111 | MEDIUM(dock 슬롯 7-unlockTile, 런타임 랜덤배치로 에디터 검증 무의미) | key 타일 3개뿐 | MEDIUM 유지 |
| timea | 341 | MEDIUM(`timea` 시뮬/솔버서 **참조 0회**) | — | MEDIUM |
| frog | 391 | MEDIUM(`_ensure_tutorial_gimmick_count:7702` 무제약 분기가 검증 **뒤** 실행 → 가려진 frog/bomb, 홀수 teleport 누출) | 가려진폭탄 161건이 이 경로 뒷받침 | MEDIUM |
| teleport | 441 | LOW~MED(하드freeze 없음, 단 monotone 파괴 → 클로저 정확성 미보장) | teleporter 396개 | LOW |

**부차 확인**: 생성기 bomb는 5~10 emit인데 `bomb_4` 12개 존재 + 시뮬은 `max(3,min(5,...))` 클램프(`bot_simulator.py:1238`) → **계약 불일치**(검증이 폭탄에 낙관/비관 왜곡).

## 7. 기존 레벨 처리
시니어3 전수(321배치): 체인보유 레코드 60,916 / 고정점-dead 보유 **1,164(1.9%)** / 그중 **`verification_passed=true` 25건**(= 유일하게 플레이어 도달 가능).
- **Severity A (passed=true 25건)**: **제자리 relabel**. 속성만 바꿔 ÷3·모양 보존 → 난이도 재검증 불필요(잠긴타일이 픽가능해질 뿐 = clear rate만 상승).
- **Severity B (passed=false/null ~1139)**: 이미 차단됨. 프론트 self-heal(레이어5)로 다음 라운드 무료 치유.
- **예외 — 튜토리얼 해금레벨(chain=81 등)**: relabel하면 튜토리얼 기믹 0개 → **체인가용 패턴으로 재생성**(§4 근본).
- 스크립트: `backend/scripts/repair_gimmick_release.py` (`repair_header_oob.py` 형식 — dry-run 기본, `--apply`시 백업+덮어쓰기, 사후 `scan==0` + `solve_level` 재확인).

## 7-b. 시니어1 추가 발견 (반드시 반영)
### 앵커 1개면 충분 — 과잉제한 금지
plain 타일 1개가 좌우 체인 **둘 다** 동시 해제(`_update_adjacent_effects`가 양쪽 순회). ∴ **한쪽 끝만 앵커 있는 체인런은 정당하게 클리어 가능**(합성테스트 clear_rate=1.0 확인). 런 길이 자체는 죄가 아님.

### "이웃 존재하나 실제 픽 불가" 전수 (앵커로 절대 세면 안 되는 것)
1. 잠긴 체인(자신이 해제가능하지 않으면) ← 보고된 버그
2. **craft_/stack_ 컨테이너 셀**(직접 픽 안 됨)
3. 셀 자체 없음(희소/체커보드 패턴)
4. **층 헤더(col/row) 밖 셀** — 게임이 스폰 안 함(= 우리가 고친 OOB 버그와 교차)
5. link_* 중 파트너가 픽 불가

조건부(순서 제약 있으면 유효): 6. 상위층 가림 — **⚠️ 체인이 가려진 동안 앵커가 픽되면 해제 기회 영구 소실**(`bot_simulator.py:2653`, 게임 `TileEffect.cs:941`). 그리고 `_add_blocking_tiles_above_gimmicks`(`generator.py:8307-8320`)가 **기믹 좌/우 칸에 상위 블로커를 의도적으로 배치** = 이 함정을 **적극 생산**. 7. ice/grass 앵커 8. curtain 앵커(스폰시 닫힘) 9. frog 점유(일시적, 이미 화이트리스트) 10. bomb 앵커(순서 틀리면 폭발) 11. stack top/teleport(teleport는 타입만 스왑, 체인 안 옮김)

### 추가 결함 지점
- `generator.py:10890-10906` ÷3 타일 제거: `other_side = f"{col-2}_{row}"; if other_side not in tiles:` — **존재만 검사**(체인/골박스/기믹/가림 무시) = 같은 버그 클래스가 생성단계에도 존재.
- `_validate_and_fix_obstacles`(14886-14919)는 클로저 무인식 → 정당히 앵커된 캐스케이드를 **과잉 제거**(반대방향 버그).

### 실측 정정 — 런타임 보드로 판정해야
raw JSON 스캔은 **과대보고**. 예: Lv980의 "고립 체인"(layer4 `3_5`)은 시뮬 상태선 craft 박스 방출로 `2_5` 실제 이웃 생김.
시니어1 정확측정(최신 6배치, 시뮬 초기상태 클로저): **23/6690 = 0.34%**. 그중 19건은 `playtest_queue`에 **검증메타 없음**, 4건 `unclearable_suspect`, **1건(Lv980) `verification_passed=true`**.
∴ **게이트는 raw JSON이 아니라 런타임 보드(craft/stack 방출·t0 분배 후)에서 평가**해야 함.

### 누락 게이트 (시니어1 강조)
`production_store.py`에 **"RL이 unclearable_suspect / pred=0인데 verification_passed=true로 승격"을 거부하는 규칙이 없음**. 23건 전부를 막을 수 있던 유일 지점.

## 8. 미해결 / 검증필요
1. **게임이 가려진 폭탄 tick하나?** — bomb HIGH 판정 결정적. 정본 표현("타 타일 수집 시" 무조건 vs 커튼만 "비가림 후 작동")이 근거이나 C# 미확인. **실측 161건 존재하므로 우선 확인 대상**.
2. **커튼 phase 전역 vs per-tile** — open/close 둘 다 emit 확인됨(시니어2 전제 반증) → lockstep 무조건 freeze 주장 재검토.
3. **컨테이너 liveness** — craft/stack이 실제로 사라지나(커버리지 해제). 아니면 클로저가 과허용.
4. **ice가 체인 해제자인가** — 시니어3는 O, `_add_chain_obstacles_to_layer:8443`은 X. 43+27+18 타일 영향.
5. **teleport monotone 파괴** → 해당 레벨서 클로저는 sound-but-incomplete(위반 누락 가능, 오탐은 안 냄 — 미증명).
6. 게임측 curtain/frog/teleport/unknown **설계 노드 자체 없음**(`03_EFFECT_SYSTEM.md`는 Grass/Bomb까지) → 9개 중 4개는 sp_template 상속 미검증. **이 부재 자체가 발견사항**.

## 9. 착수 순서
1. `_covering_keys` 추출(리팩터, 무동작변경) → 클로저 `_strip_unreleasable_gimmick_tiles`(chain 우선, grass 등록) → generate() 1492+ 배선.
2. 규칙 통합(7548/8438/14903/analyze2000 → 공용 헬퍼).
3. 저장·export 게이트(4·6) + 프론트 미러(5) + `tsc`.
4. bomb 커버리지 helper 교체(`generator.py:8727-8731` → `_is_position_covered_by_upper`) — 1줄급, 독립.
5. `generator.py:1487` 뒤 재검증(frog/bomb/teleport 누출 차단).
6. 기존 Severity A 25건 repair 스크립트 + 튜토리얼 레벨 재생성.
7. (조사) 게임 C#서 폭탄 tick·커튼 phase 확인 → HIGH 등급 확정.
- **착수: 사용자 승인 후.** 현재 순차검증 진행중 → 서버 영향 작업은 완료 후.
