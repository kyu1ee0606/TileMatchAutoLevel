# 맵에디터 3개 수정 계획 (chain 클로저 / timea 티어 / link 게이트)

작성 2026-07-30. 상태: **계획(레드팀 검증 중)**. 근거: `PLAN_gimmick_release_deadlock.md` §6-0(게임 C# 13/13 대조 완료).

## 전제 (확정된 사실)
- 검증기 필요 = **chain, timea 2개만**. 나머지 10개 기믹은 게임이 처리(추가 금지).
- 게임에 "합법수 0 → 자동 리셔플" 없음 → 무알림 소프트락은 치명.
- 게임 실패 경로: dock overflow / bomb / **TimeOver** / can't-uncover(Grass·Chain·Ice).
- chain 게임 검출은 `CheckRemainNearTile(true) < 1`(`TileEffect.cs:1341`) — *살아있는* 이웃만 셈 → **잠긴 사슬끼리 이웃하면 영구 미발동**.

---

## ① chain 고정점 클로저 검증기

### 문제
사슬 2+개 수평 연속 + 양끝에 픽 가능 앵커 없음 → 영구 해제불가. 게임도 실패처리 안 함(무알림 소프트락).

### 주범 (재확인)
`_ensure_tutorial_gimmick_count`(`generator.py:7454`, 호출 **1111** 및 **1487**)이 candidates를 스냅샷 1회로 만들고 N개를 루프서 변환 → **서로의 앵커를 사슬로 덮음**. 마지막 정상 검증기는 **1087/1093**(그 이전).

### 알고리즘 (정적, monotone → 최소고정점 = 정확) — **레드팀 교정 반영**
> ⚠️ 초안의 "seed" 개념 **삭제**. 전파규칙이 `이웃이 사슬 아니면 OK`라서 시드 집합을 참조하지 않음(inert). 시드를 진짜로 구현하면 **2.5배 과잉엄격**(위반 10→25타일) + RL통과 **Lv190**(앵커=`ice`) 사슬 파괴. 단일 조건형으로 확정:

```
attr(td) = "" if td[1] is None else td[1]        # ⚠️ null 정규화 필수 (실측 null 26,745개 ≈10%)

사슬 c ∈ EP  ⟺  수평 같은층 이웃 n ∈ {(x-1,y), (x+1,y)} 중 하나가:
    보드에 존재 (타일 OR craft 방출칸 OR stack 컨테이너 루트)   AND
    craft 컨테이너 루트 아님                                  AND
    ( attr(n) != "chain"  OR  n ∈ EP )
반복: 더 안 늘 때까지 (단조증가, N상한 → O(N·d))
위반: 사슬인데 고정점에서 EP 밖
```

**앵커 자격 확정 (사용자 승인)**:
- **ice / grass / curtain / unknown / bomb / teleport / link 속성 타일 = 유효 앵커** (결국 픽 가능. `bot_simulator.py:476-503` else분기 + `TileEffect.cs:1021-1088`)
- **`frog`는 앵커 아님** — `on_frog`면 `can_pick=False`(`bot_simulator.py:488`, `TileEffect.cs:1031-1035`). 초안이 시드에 넣은 건 오류
- **stack 컨테이너 루트 = 유효 앵커** — top 타일이 루트 셀에 있어 직접 픽 가능(`bot_simulator.py:1538-1541`). 초안이 잘못 제외
- **craft 컨테이너 루트만 제외** — 직접 픽 불가, 방출은 오프셋 셀로(`TileCraft.cs:1073` AddOffset)

**판정 원칙**
- **런타임 보드 기준**: craft 방출칸을 실제 타일로 인정. raw JSON만 보면 과대보고(52건 → 런타임 10타일)
- **앵커 1개면 충분**: plain 1개가 좌우 사슬 둘 다 해제 → 런 길이 무죄. 과잉제한 금지
- **커버리지는 판정 제외**: 가려진 사슬 + 앵커1 순서함정(실측 122레벨)은 게임이 `FailReason.Chain`으로 **명시 실패** → 설계된 동작

### 실측 (레드팀, 3000레벨 / 2배치)
| 항목 | 값 |
|---|---|
| 사슬보유 레벨 | 410 / 사슬타일 2,152 |
| **위반 레벨** | **8** (450,590,770,780,1480 / 1180,1360,1370) |
| **위반 타일** | **10 (0.46%)** |
| `verification_passed=true` | **0** (플레이어 도달 없음) |
| 비용 | **0.029ms/레벨, 배치 40.7ms** (봇 321~1256ms의 1/10000~45000) |
| 수리 불변식 | 8/8 전부 ÷3·max_moves·타입카운트 **완전 보존**, 1패스 수렴 |

### ⚠️ 초안 "주범" 지목 = 데이터 반증 (교정)
- 수평 사슬런 분포: **길이1 = 2,106 / 길이2 = 23(전부 정상해제) / 길이3+ = 0**
- 위반 10건 전부 = **수평 이웃 양쪽 다 빈칸인 고립 사슬**
- **Lv81 무위반**(`passed=true`). `_ensure_tutorial_gimmick_count` 상호덮기 실패 **0건**
→ 진짜 결함 = **"수평 이웃 없는 칸에 사슬 배정"**. **배정 시점 O(1) 조건**("대상 칸은 같은층 수평 이웃 셀 ≥1개 보유")으로 **10/10 예방**.
→ 초안의 "3연속 사슬 유닛테스트"는 **존재하지 않는 케이스**. 테스트는 **고립 사슬**로 작성.
→ 클로저는 **불변식/백스톱**으로 유지(41ms/배치로 공짜급).

### 튜토리얼 충돌 — 데이터상 미발생
Lv81 무위반. 수리 후 사슬 0개 되는 레벨 4개(590,780,1180,1370) 전부 **튜토리얼 플래그 아님**. relocate-우선 폴백은 **합성 케이스 방어용** → 후순위로 미뤄도 됨.

### 수리
위반 사슬의 **속성만 제거** `td[1] = ""` → 일반타일. 타일 개수·타입·좌표 불변 → **÷3·패턴모양·max_moves 전부 보존**.
- EP 재계산(하나 풀리면 연쇄 해방, 단조라 종료)
- **튜토리얼 사슬 레벨(81)** 은 relabel하면 사슬 0개 → 튜토리얼 위반. 순서: ① 안전 호스트로 **relocate**(속성 이동) 시도 → ② 실패 시 relabel + `playability_warning` 세워 재생성 위임
- 금지: 타일 삽입(홀짝 2칸 격자 파괴 + header-OOB 유발), 타일 삭제(÷3 파괴)

### 배치
| 위치 | 모드 |
|---|---|
| `generator.py` **1492 직후**(link 백스톱 뒤, max_moves 백스톱 1498 **전**) | REPAIR |
| `tune.py:433`, `:1004` (link sanitize 옆) | REPAIR |
| `analyze.py:2000` 보스템플릿 인라인 strip → 공용 호출 | REPAIR |
| `production_store.py` 저장 게이트 | **FAIL-CLOSED**(플래그) |
| 프론트 `index.tsx` self-heal(RL측정 **전**) | REPAIR |
| 프론트 `ProductionExport.tsx` export 게이트 | **FAIL-CLOSED** |

**순서 중요**: max_moves 백스톱(1498) **전**에 실행 — relabel은 개수 안 바꾸므로 실제 영향 없으나, 향후 relocate 확장 대비 안전 순서.

---

## ② timea = 타일수 연동 + 5단계 티어 (난이도 레버)

### 문제
현재 `generator.py:1263-1278`이 **난이도만 보고** 45/60/90/120초 배정, **타일수 무연동**.
실측: timea>0 116레벨 / 초당타일 <0.6s(물리적 촉박) **48건**(passed=true 11건). 최악 `Lv1280 45s·144타일=0.312s/타일`.
시뮬은 `timea` 참조 **0회** → 검증이 이걸 통과시킴(에디터 LOOSER = 위험).

### 새 공식 (사용자 지정 + 레드팀 상수 교정)
```python
BASE_SEC_PER_TILE = 0.9        # 참조 페이스. ⚠️ 하한 아님 — C#서 도출 불가(인간 탭속도 추정)
# 【사용자 확정】3단계. 1=넉넉 / 2=보통 / 3=촉박
TIMEA_TIER_MULT = {
    1: 1.15,   # 넉넉 (실효 1.035s/타일) — Lv341 튜토리얼 및 저난이도
    2: 0.85,   # 보통 (실효 0.765s/타일)
    3: 0.60,   # 촉박 (실효 0.540s/타일, 물리하한 0.25s의 2.2배)
}
TIMEA_MIN_SEC = 60                    # 게임 스키마 계약(timea 60~600) 준수. ⚠️ 초안 30은 계약 위반
TIMEA_MAX_SEC = 600                   # 스키마 상한 클램프
TIMEA_OVERHEAD_SEC = 0                # 확정: 연출 중 레이캐스트 비활성 + 연출완료 후 StartTimer
TIMEA_ABS_MIN_SEC_PER_TILE = 0.45     # 시작 assert: BASE*MULT[3] >= 이 값

# ⚠️ 정수 산술 고정 (프론트 미러와 1초 불일치 방지 — float 평가순서 차이로 26개 타일수에서 어긋남)
#   예: n=100,mult=1.6 → (n*0.9)*t=144 vs n*(0.9*t)=145
BASE_MILLI = 900                      # 0.9s
TIER_MILLI = {1: 1150, 2: 850, 3: 600}
timea = clamp(TIMEA_MIN_SEC, TIMEA_MAX_SEC,
              -(-(tile_count * BASE_MILLI * TIER_MILLI[tier]) // 1_000_000) + TIMEA_OVERHEAD_SEC)
```

#### 【사용자 확정】Lv341 = 타임어택 대상 + 티어1(가장 쉬움)
현재 `generator.py:1257` `if level_number >= 341 and gimmick_intensity > 0:` 조건이 **Lv341을 배제**(보존패턴 튜토리얼이라 `gimmick_intensity == 0`).
→ 튜토리얼 분기를 `gimmick_intensity` 게이트 **밖으로** 이동:
```
if level_number == 341:                          # 튜토리얼: intensity 무관하게 적용
    tier = 1
elif level_number > 341 and gimmick_intensity > 0 and level_number % 10 == 0:
    tier = 난이도 유도  (<0.5→1, <0.7→2, else→3)
else:
    timea 미적용
```
→ 실측 분포 대응: T1 = 38+1(341) / T2 = 70 / T3 = 124. **3티어 전부 도달 가능.**
→ `params.timea_tier` 명시 지정 시 최우선(난이도 무관 독립 레버).

#### 초안 상수(0.95~2.00)를 버린 이유 — 게임 C# 실측
| 항목 | 값 | 출처 |
|---|---|---|
| 탭 입력 락 | **없음**(탭 완전 파이프라인) | `LevelController.cs:1269-1283` |
| 타일 비행 | 0.5s — **코스메틱**(다음 탭 안 막음) | `Dock.cs:154` |
| 매치 판정 | 탭 시점 **동기** | `Dock.cs:964, 2450-2462` |
| 타이머 | 벽시계, 애니 무관 정지 안 함 | `LevelTimer.cs:78,98-100` |
| 타이머 시작 | **연출 완료 콜백서 StartTimer + 그동안 레이캐스트 OFF** → 오버헤드 0 | `LevelController.cs:1192-1215` |
→ **애니 하한 ≈ 0s. 실질 하한 = 인간 탭속도 ≈0.25s/타일.**
→ 초안 티어5(0.855s/타일)는 하한의 **3.4배 = 넉넉** → "촉박" 티어가 안 물음. 총 예산 **+35%**(레버 무력화).
→ 권고값 티어5 = **0.54s/타일**(하한 2.2배), 총 예산 **+6%**(중립), 레버 폭 **3.3배**(초안 1.37배).

#### 예시 (81타일, 3티어)
**t1=84s / t2=62s → 62s(하한60 근접) / t3=44s → 60s(하한 적용)**
> ⚠️ 하한 60s 때문에 소형 레벨은 티어 구분이 사라짐(81타일 t3=44→60). 티어가 실제로 갈리는 건 **약 111타일 이상**(t3: 111×0.54=60s). 소형 보스레벨은 전부 60s로 수렴 — 의도된 안전동작.

#### 실측 효과
- 물리적 불가(0.6s/타일 미만) **137/232 → 해소**(최소 s/타일 0.246 → **0.557**)
- 초안 적용시: 시간증가 164/232(70.7%), 최대 **+118s**(Lv430 90→208s) = 과보정
- `collectable_tile_count` = **`_calculate_max_moves(level)` 와 동일 기준**(plain + craft/stack 내부타일). 별도 계산 금지 = 단일 진실.
- 티어는 **난이도와 분리된 독립 레버**. 기본값은 난이도에서 유도, 파라미터로 명시 오버라이드 가능.
- 레벨에 `_timea_tier` 스탬프 → 추적/재현/UI 표시.

### 티어 결정 — 【사용자 확정: 3단계 + Lv341 편입】
```
tier = params.timea_tier               (명시 지정 최우선 = 독립 난이도 레버)
     else 1                            (Lv341 튜토리얼 = 가장 쉬운 조건)
     else 난이도 유도(보스만): <0.5→1, <0.7→2, else→3
```
초안의 5티어는 **1·2가 도달 불가(죽은 상수)** 로 실측 확인 → 3티어로 축소 + Lv341 편입으로 해소.
- 이전 5티어 실측: 3=38 / 4=70 / 5=124, 티어1·2 = **0건**
- 신 3티어: T1 = 38+1(Lv341) / T2 = 70 / T3 = 124 → **전부 도달**
- 레버 폭: 1.15/0.60 = **1.92배** (초안 5티어 실효 1.37배보다 넓음)

### ⚠️ 배정 시점 이동 (필수) — 검증 완료
현재 **1276줄**에서 배정하나 이후 타일수가 변함:
- `1323` 경계밖 타일 제거
- `1351` `_finalize_divisibility_guarantee` (÷3 위해 타일 **추가/제거**)
- `1487` `_ensure_tutorial_gimmick_count`
→ **1276의 timea는 stale**. `max_moves` 백스톱(1498)이 정확히 같은 이유로 존재.
**∴ timea 계산을 1498 옆(max_moves 재계산 직후)으로 이동.** 1276에서는 "티어 결정 + 적용 여부"만 정하고 값은 마지막에 산출.

**이동 안전성 확인(직접 검증)**: `1276~1500` 구간의 `timea` 참조 = **쓰기 1줄뿐**(`level["timea"] = time_limit`), **읽는 코드 없음** → 깨질 소비자 없음.
**드리프트 실측(레드팀)**: `_calculate_max_moves`가 첫 호출 대비 1498서 **18/14회 생성 중 변동**, 최대 **−18타일**(예: Lv1100 d=0.75, 75→57). 권고 티어5 요율로 **10초 오차** → 이동 필수 근거 정량 확인.

### 적용 범위 (기존 유지)
`level_number >= 341 AND gimmick_intensity > 0 AND (튜토리얼 341 OR 보스 %10==0)`.
→ 범위 확대는 이번 스코프 아님(별건).

### 게이트 — **1차엔 경고만(fail-closed 금지)**
```
timea > 0 이면  timea >= ceil(tiles * BASE_SEC_PER_TILE * TIMEA_TIER_MULT[5])
```
= 티어5보다 촉박하면 위반. 구코드 생성분·수동편집분 검출.
> ⚠️ 레드팀: 초안 상수로 fail-closed면 기존 **137/232** 차단, 권고 상수로도 **89/232** 차단 → **기존 보스레벨 전멸**.
> ∴ 1차는 `meta.timea_tight` 플래그 + 경고만. 재생성으로 해소된 뒤 fail-closed 승격.

### RL 캘리브레이션 영향 = **없음** (확인됨)
`timea` 값은 **소비자 없음**: `analyzer.py:93` `has_time_attack = timea > 0` **존재플래그로만** 사용(`:255`,`:304`). `bot_simulator.py`·RL 참조 **0회**. 프로젝트 전체서 generator 쓰기 / analyzer 플래그 / `gboost.py:458` export / 프론트 타입선언뿐.
→ `predicted_clear_rate`·`target_clear_rate` **불변**. timea 변경이 기존 검증 무효화 안 함.
→ 반대로 **현재 137레벨의 시간부족은 RL이 한 번도 못 본 무모델 리스크**.

### 프론트
- 미러: 티어 상수 + 공식(생성기와 동기 필요, CLAUDE.md 규칙) → self-heal서 stale timea 교정(max_moves self-heal과 동일 패턴)
- export 게이트에 위 부등식 추가
- (선택) 배치 생성 UI에 티어 선택 노출 → 난이도 레버로 활용

---

## ③ link 게이트 승격 (수리 → 차단)

### 문제
orphan link = 게임 **크래시**: `TileEffect.cs:464-465`가 `linkedTile` null 역참조(NRE). `TileGroup` 초기화 루프서 터져 **이후 전 타일 기믹 초기화 유실**. craft/stack 셀 지목도 동일.

### 현 상태
`_strip_orphaned_link_tiles`(`generator.py:12390`)가 유일 방어. 실측 orphan **0건** = 작동 중.

### 왜 바꾸나
chain 버그가 정확히 이 패턴 — **검증기는 있는데 나중 단계가 다시 망가뜨림**(1487 튜토리얼 ensure). link도 파이프라인 재정렬 시 구멍 재개 가능. 조용한 수리는 재발을 숨김.

### 수정
저장·export 게이트에 **정적 단정** 추가(수리 아님, 차단):
```
각 link_{e,w,s,n} 소스 (x,y)에 대해 target = (x+dx, y+dy):
  같은 층에 존재 AND
  타입이 craft_/stack_ 로 시작 안 함 AND
  속성이 빈 문자열
위반 = FAIL
```
= sanitizer 자체 조건을 그대로 단정으로. 파이프라인이 재정렬돼도 유출 불가.
- sanitizer는 **그대로 유지**(정상 경로에선 게이트가 조용히 통과)
- 게이트가 걸리면 = 진짜 회귀 → 로그로 드러남

---

## ⚠️ 추가 구멍 — 구제 경로 (직접 검증, 계획 교정)
`api/routes/generate.py:157-174` 실제 코드:
```python
if applied and needs_rescue:
    response.playability_warning = False              # ① 경고 먼저 지움
...
_tut = TUTORIAL_UNLOCK_LEVELS.get(level_number)
if _tut:
    ...
    else: _lj = generator._ensure_tutorial_gimmick_count(_lj, _tut, 3)   # ② 사슬 재주입
    _lj = generator._finalize_divisibility_guarantee(_lj)                # ③ ÷3만 재확정
    response.level_json = _lj                                            # ④ 클로저/link 검증 없이 반환
```
- `generate()` 내부 백스톱(1492/1498)은 **이미 지나간 뒤** → **이 경로는 백스톱 밖**
- 사슬 재주입 후 클로저 검증 **없음** → ①만 1492에 넣으면 **이 경로로 유출**
**교정**: `generate.py:174` `response.level_json = _lj` **직전에** 클로저 sanitize + link sanitize 호출. `playability_warning` 해제는 **재주입·검증 이후**로 미룸.

## 프론트 필드 확인 (직접 검증)
`LevelJSON`에 `timeAttack`(21행)과 `timea`(27행) **둘 다 선언**됨:
- `timeAttack` 사용처 **3곳뿐**, 전부 GridEditor 수동편집(`ToolPalette.tsx:160`, `levelStore.ts:300`). **변환 코드 없음**
- 백엔드/게임이 쓰는 건 **`timea`**
→ **미러는 `timea`만** 다룸. `timeAttack`은 레거시(스코프 밖).
→ 별건 부채: `timeAttack`으로 수동편집한 값은 게임에 **반영 안 됨**.

## 상호작용 체크
| 항목 | 영향 | 판정 |
|---|---|---|
| ① relabel ↔ ÷3 | `td[1]`만 변경, `td[0]` 불변 → `_clearability_type_counts` 무영향 | 안전 |
| ① relabel ↔ 패턴모양 | 좌표·개수 불변 | 안전 |
| ① relabel ↔ max_moves | 개수 불변 → 값 동일. 단 1498 **전** 실행으로 순서 안전 확보 | 안전 |
| ① ↔ 튜토리얼 보장(81) | 사슬 0개 될 수 있음 → relocate 우선, 실패시 재생성 위임 | 처리됨 |
| ② timea ↔ max_moves | 동일 `_calculate_max_moves` 기준 사용 → 두 값 정합 | 안전 |
| ② 시점 이동 ↔ ÷3/튜토리얼 | 1498 옆으로 이동 = 모든 타일 변경 이후 → stale 불가 | 해결 |
| ② 티어 ↔ 기존 난이도 | 티어 기본값이 기존 4구간 대응 → 회귀 최소 | 안전 |
| ③ 게이트 ↔ sanitizer | 정상 경로선 게이트 무침묵 통과. 이중방어 | 안전 |
| ①③ ↔ 실행중 검증 | 프론트 편집 = HMR 리로드 → 진행중 검증 중단됨 | **순차검증 정지 상태서 착수** |

## 착수 순서
1. ① 백엔드 클로저 + 1492 배선 → 유닛테스트(3연속 사슬 케이스 + 앵커1 정상 케이스 회귀)
2. ② timea 티어 상수·공식 + 1498 옆 이동 → 실측 재측정(촉박 0건 확인)
3. ③ 게이트 단정 추가
4. 저장/export 게이트(①②③) + 프론트 미러 + `tsc --noEmit`
5. 기존 배치 실측 재스캔(chain stuck 0 / timea 위반 0 / link 0)
6. 서버 재시작 → 순차검증 재개

## 🔴 레드팀 A 추가 지적 — 반드시 반영 (전수 317배치 / 398,780레벨 / 사슬 308,698타일)

### A1·A2 시드 (레드팀 B와 동일 결론, 규모 더 큼)
- 리터럴 `td[1] == ""` 만 쓰면 **주배치 사슬의 74.9%(799/1067) 오탐**, 전수 **38.3%(~118,000)**. `None`이 두 번째로 흔한 값(전수 ~1.99M).
- 좁은 시드(ice 등 제외)면 잔여 오탐 **55.2%(1,729/3,134)**. 구제 앵커: `ice 651, unknown 338, bomb 317, link 199, grass 117, curtain 102, teleport 89`.
- **확정**: 시드 = **`chain` 제외 전부**. 하드코딩 말고 `bot_simulator.EFFECT_MAPPING`(`:747-770`)서 유도 — 미매핑은 `NONE`→`can_pick=True`(`:502-503`). `key`(720), `time_attack`(302)도 자동 포함.
- 회귀 테스트 케이스: **Lv149 layer_4**(null 앵커), **Lv190 layer_2**(ice 앵커).

### A3 🔴 커버리지 — "판정 제외"는 run≥2에서 **틀림** (초안 교정)
초안은 "가려진 사슬 순서함정은 게임이 `FailReason.Chain`으로 잡음"이라 제외했으나, 이는 **런길이 1에만** 성립.
- 런2에서 사슬A 가려진 채 앵커P 소진 → A 영구잠김. 근데 A의 다른 이웃 = 사슬B(살아있음) → `CheckRemainNearTile(true)` = 1 → `1<1` false → **FailReason 미발동 = 동일한 무알림 소프트락**
- `_add_blocking_tiles_above_gimmicks`(`generator.py:8311-8312`)가 기믹 칸 또는 `col±1`(= 앵커)에 상위 블로커를 **의도적으로 배치** → 이 함정을 **적극 생산**

| 클래스 | 런 인스턴스 | 레벨 | passed=true |
|---|---|---|---|
| 초안 타깃(run≥2, 앵커없음) | 161 | 104 | **31** |
| **잔여(run≥2, 앵커있음, 멤버 1+ 가려짐)** | **808** | **681** | **49** |

→ **확정**: 클로저를 **run≥2 사슬에만 커버리지 인식**. run1(전체의 95.4% = 294,445타일)은 면제 유지 → 과잉엄격 재발 불가. 총 플래그율 0.05% → 0.31%.

### A4·A5 🔴 삽입지점 — 단일 라인 추가로는 못 막음
`generate.py:157-174`는 `generate()` **반환 후**라 1492 백스톱 밖 + `playability_warning`을 먼저 지움. 추가 미커버:
- `analyze.py:1983-2013` 보스템플릿 — `generate()` 완전 우회. 인라인 사슬검사(`:2000-2002`)는 **이웃 키 존재만** 확인, `_finalize_divisibility_guarantee`가 **그 뒤**(`:2006`)
- `tune.py:433`/`:1004` — `_gimmick_arrangement`(`:360-393`)가 속성 전부 strip 후 사슬 재추가(`:377-385`), 뒤에 link sanitize만
- `generate.py:2703`, `analyze.py:1250` `_add_chain_to_tile` — 새 사슬만 검증, 앵커를 잡아먹힌 기존 사슬은 미검증

→ **확정**: 라인 추가 대신 **`_finalize_level(level)` 추출** = ÷3 finalize → 사슬 클로저 수리 → link sanitize → max_moves. 호출: `generator.py:1492`, `generate.py:174`, `analyze.py:2013`, `tune.py:433`, `tune.py:1004`. (반복 버그의 원인은 **중복된 tail** 자체 — 6번째 손수 tail을 만들면 재발.)
→ 삽입은 **1487 이후 & 1492 이전**. 이유 정정: `_calculate_max_moves`는 `td[1]` 안 읽어 1498 순서는 무관. 진짜 제약은 "1487 이후" + relocate가 link 타깃에 속성 부여 시 이미 지나간 link sanitize를 되살려야 함.

### A8·A9 🔴 게이트 배선 오류
- **A8**: `ProductionExport.tsx:252` try ~ `:288` `catch { /* 진행 */ }` → 새 검사에서 예외 나면 **÷3·headerOOB 게이트까지 통째로 무력화**(fail-OPEN). → 순수함수 검사는 **네트워크 try 밖**에서 계산.
- **A9**: `_bad` 게이트는 `handleExportJson`(`:243`)에만 있음. **실제 배포 경로 `handleUpload`(`:484`, GBoost)** 및 `handleBackupAndUpload`(`:455`), `handleSaveToLocal`(`:337`), `handleMigration`(`:628`)은 **게이트 전무**. `getExportableLevels()`(`:390-394`)는 `level_json` 존재만 확인 → `generated` 상태도 포함.
  → **확정**: 단정을 `getExportableLevels()` 또는 공용 `assertDeployable()`에 넣어 5경로 전부 상속. (∴ "게이트가 Lv81을 막았을 것" 이라는 이전 주장은 **무효**.)

### B-급 반영 항목
- **B5**: `_calculate_max_moves`는 `max(30, total)` **하한 포함**(`:2454`) → 소형 레벨 시간 과다(Lv780 18→30 = 1.67배). **raw `_collectable_tile_count()` 추출**해서 timea는 raw 사용.
- **B4**: 이동 근거 정정 — `_ensure_tutorial_gimmick_count`(1487)는 **타일수 안 바꿈**(속성만). 실제 변경자: `:1292-1305` 경계트림, `:1315` 피라미드, `:1324` OOB제거, `:1345` `_ensure_container_goal_tutorial`(+2), `:1351` ÷3 finalize(−2..+2).
- **B3**: timea 게이트 폭발반경 — 전수 `timea>0` 24,730건 중 **15,388(62.2%) 위반**(그중 `passed=true` **2,035**). ∴ **1차 경고만** 확정 + 백필/마이그레이션 순서 명시 필요.
- **B7**: `sanitizeHeaderOob` relocate가 **link heal 이후** 실행(`index.tsx:4151` → `:4155`), BFS가 link 무인식 → 실측 1건(Lv51). 순서 교정(무료). 더 큰 orphan 생산지: `analyze.py:1389-1415` `/analyze/fix-centering`(link strip **없음** — sanitizer docstring이 지목한 원인 함수 2개를 그대로 실행), `analyze.py:2501`, `repair_header_oob.py`.
- **B2**: link 게이트 fail-closed 시 전수 **6,219레벨** 플래그. 절: (a) 타깃부재 2,844(치명) vs (c) 타깃속성보유 3,883(정상 상호쌍 223레벨 포함 — 예 Lv145 `2_0=link_e` ↔ `3_0=link_w`). → **(a)만 fail-closed**.
- **B8**: `stack_*`는 **방출칸 없음**(AddOffset은 craft 전용). "craft/stack 방출칸" 표기는 **under-strict** → 실측 14타일 **오통과(위험방향)**. 반대로 `stack_` **루트 자체는 유효 앵커** → 제외 해제하면 오탐 72개 감소.
- **B9 ⚠️ 미해결**: craft 방출칸이 게임서 진짜 앵커인지 의문. `SetNearTile()`이 스폰 시 **1회만** 실행(`TileGroup.cs:568-579`)해 `nearTile[]` 스냅샷 고정, 사슬 해제는 그 배열 참조비교(`Tile.cs:1511-1516`). `AddOffset`은 좌표만 바꾸고 `SetNearTile` **재실행 안 함**. → 방출칸 앵커가 게임서 무효일 수 있음(노출 **31타일**). **게임팀 확인 필요.**
- **B6**: 튜토리얼81 "처리됨" 아님 — 재생성 위임 대상이 `playability_warning` 후보를 **수용**(`index.tsx:5100-5103` "모든 후보가 warning → 폴백 채택"), 튜토리얼 사슬수 검사 주체 **없음**. 잠긴 쌍은 **한쪽만 풀면** 되므로 **최소집합 strip + re-ensure 고정점** 방식으로(일괄 strip 금지).
- **B12**: `gboost.py:458`이 `timeAttack` **우선** 읽음 → 게이트는 **exporter가 읽는 필드** 기준으로.
- **B13**: 레거시 timea writer 존재 — `batch_1770*` 6파일 2,053건이 63~103s(타일수 무관 100s 근처). "현재=45/60/90/120" 전제 불완전.
- **B14**: `341` 상수 3중복(`generator.py:1256`, `leveling_config.py:187`, `levelSet.ts:172`) → 4번째 추가 말고 단일화.

### 레드팀 A 오판 1건 (내가 코드로 반증)
"orphan link NRE는 게임서 이미 수정됨(v1.10.583)" → **틀림**. `FindLinkTile()`(`TileEffect.cs:1108-1130`)에 null 가드는 생겼으나, 호출부가 직후 그대로 역참조:
```csharp
FindLinkTile();               // orphan이면 linkedTile = null 유지
tile.isLinkTile = true;
linkedTile.isLinkTile = true; // ← NRE 여전
```
∴ 크래시 유효. 게임측 보고 유지.

## 해결된 애매함 (교정 완료)
| 항목 | 결론 |
|---|---|
| 클로저 시드 정의 | **시드 개념 삭제**, 단일조건형. ice/grass/curtain/bomb/unknown/teleport/link = **앵커 인정**(사용자 승인) |
| frog 앵커 여부 | **앵커 아님**(`can_pick=False`) |
| null 속성 | `attr = "" if td[1] is None else td[1]` **정규화 필수**(실측 null 26,745개) |
| stack 루트 앵커 | **인정**(top이 루트 셀) |
| craft 루트 앵커 | **제외**(직접 픽 불가) |
| 진짜 주범 | 3연속 아님 → **고립 사슬**(수평 이웃 양쪽 빈칸). 배정시점 O(1) 조건으로 10/10 예방 |
| 유닛테스트 케이스 | 3연속 아니라 **고립 사슬**로 작성 |
| timea 이동 안전성 | 1276~1500에 **읽는 코드 없음** → 안전. 드리프트 최대 −18타일 확인 |
| `TIMEA_OVERHEAD_SEC` | **0 확정** — 연출 중 레이캐스트 OFF + 연출완료 콜백서 StartTimer(`LevelController.cs:1192-1215`) |
| 티어5 물리 타당성 | 권고 0.54s/타일 = 물리하한(0.25s) **2.2배** → 타당. 초안 0.855는 3.4배로 느슨 |
| RL 캘리브레이션 무효화 | **없음** — timea는 존재플래그로만 소비 |
| 튜토리얼 충돌 | Lv81 무위반, 사슬0 되는 4레벨 전부 비튜토리얼 → relocate 폴백 후순위 |
| 프론트 필드 | **`timea`만** 미러(`timeAttack`은 레거시 3곳) |
| 게이트 강도 | **1차 경고만**(fail-closed면 89~137건 차단) |
| 구제경로 구멍 | `generate.py:174` 직전 sanitize 추가로 교정 |

## 남은 미확정 (착수 가능, 후속 캘리브레이션)
- **`BASE_SEC_PER_TILE = 0.9` 는 인간 페이스 추정치** — C#에서 도출 **불가**(탭 파이프라인되어 애니 하한 ≈0). 물리하한 0.25s/타일은 Fitts식 추정.
  → **정확히 정하려면**: 실플레이 탭 타임스탬프 로깅(보스 5~10레벨) 또는 기존 분석 이벤트의 레벨 완주시간. 그 1개 데이터셋이 `BASE`와 티어 스프레드를 동시 확정.
  → 그 전까진 `TIMEA_ABS_MIN_SEC_PER_TILE = 0.45` assert가 안전선 역할.
- **티어 1·2 도달불가 처리** — Lv341 편입 vs 3티어 축소. **사용자 결정 대기**(미결시 명시지정으로만 사용).
- 티어 배수는 상수 **1곳**에 모아 플레이 피드백으로 조정.

## 게임측 추가 보고 (이번 조사 산출)
1. `LevelTimer.cs:98-100` — `1/60`씩 프레임당 감소 → **30fps 기기서 약 2배 느리게** = 프레임률 의존
2. `LevelTimer.cs:137` `ReviveTimer(30)` — **30초로 리셋(가산 아님)** → timea 큰 레벨서 100골드 부활 무의미
3. `TileEffect.cs:464-465` orphan link **NRE**(우리 sanitizer가 차단 중)
4. (경미) `teleportRandSeed` dead config — `TileGroup.cs:1633` 미사용, `:1635` unseeded
