# TileMatchAutoLevel - TODO 리스트

## 봇 계획 능력·craft 공개 추론 (2026-10-27)

- [x] **(2026-10-28)** 문서 70 dock_reserve_play D3 PREREG 6,144판 **미지지**(채택 안 함, 코어 a89a29ab… 불변) · 문서 71 보정모델 재학습 판단 **조건부**(5단계 재측정 승인 후) · DDA 공용 측정 프로필 `bot_measure_profile.py` + 래퍼 `dda_aligned_games_20261028.py`(검증 192/192). 누적 약 136,984/195,000. 재개: [resume_note_20261028](difficulty_personalization/resume_note_20261028.md). 남은 일: 5단계 재측정 승인(한도 약 210,000 필요)·후속 기믹 후보 보류·push 승인.

- [ ] **(재개 대기 2026-10-27 20:00)** A 완료(dev 96행·2,048판, pick **D3**) · B-1 코어 정렬 완료(코어 a89a29ab…, parity 통과), B-2 DDA 프로필 정렬 미착수(계획만). 남은 C(문서 70 PREREG, 다음 주)→D→E: [resume_note_20261027_2000](difficulty_personalization/resume_note_20261027_2000.md). 누적 약 130,456/195,000.

- [x] `skill_planning`(#1)·`public_craft_belief`(#2) opt-in 구현, 테스트, 비용 측정(판당 ≤0.5초). 코어 4196e75a. [56](difficulty_personalization/56_bot_planning_craft_belief_20261027.md).
- [x] PREREG 16,000판 완료: P1·P2·P12 모두 기계 판정 미지지. P2는 N TV 부동소수 오차(1e-16)만 실패. craft 맵 일반 실패 크게 감소. N 맵이 쉬운 초반 맵 위주라 검정력 부족. [56 §6~8](difficulty_personalization/56_bot_planning_craft_belief_20261027.md).
- [x] P2 사후 허용오차(1e-12) 재판정: P2 지지(원판정 보존, 사후 적용 명시). [56 §6](difficulty_personalization/56_bot_planning_craft_belief_20261027.md).
- [x] 열쇠 배치·독 잠금 게임 정합(사용자 승인 기본 반영, 코어 cbc2e652): golden 불일치 0, unlockTile=0·출하 key 맵 결과 불변. L138 원인 = 봇 전략(c). [26 상단](difficulty_personalization/26_bot_v24.md), [56 §9](difficulty_personalization/56_bot_planning_craft_belief_20261027.md).
- [x] 자원 가드 변경: swap 0MB 환경 → `scripts/run_guard_20261027.py`(압력 critical 아님·가용 ≥1.5GB·디스크 ≥10GiB, 미달 시 대기/중지). [57 §2](difficulty_personalization/57_bot_hard_maps_key_prereg_20261027.md).
- [x] 57 PREREG 측정 완료 21,120판(누적 약 60,700): H(어려운 미사용 10맵) P2·P12 미지지 / K(key 28맵) K1·K2 모두 지지(KN 클리어 MAE 37.3→14.5·14.8%p, L138 0.8→77~83%). [57 §6](difficulty_personalization/57_bot_hard_maps_key_prereg_20261027.md).
- [ ] (사용자 결정) K1(key_first, 코어 변경 없음) 또는 K2(코어 이식 필요, 277·424 악화) 기본 채택 · P2 기본 채택(근거 엇갈림) · H 잔여 오차(풀 실패 과소·폭탄 과대).
- [ ] 다음 러너부터 STOP 플래그 파일(행 경계에서 확인 후 정상 종료) 도입 — 57 러너는 SIGINT 무시로 SIGTERM 정지 필요했음(manifest/sha 고정 때문에 57 러너는 수정 안 함).
- [x] Codex 리뷰(20261027-113836) 테스트 보강: g5 `key` 허용을 unlockTile>0으로 한정, 수정 전 코어(4196e75a) 스냅샷 `tests/golden/key_parity/legacy_4196e75a.json` 대비 unlockTile=0 2,009건 불변(문자열·카운트·잠금·RNG), 해석기 예외 강제 폴백 10건, t16·효과 key 혼재 정규화·3매치 해제. 회귀 4,393 PASS. 코어 무수정.
- [ ] (기록) 기존 코어 특성: `all_tile_type_counts`가 스택 맨 위(state.tiles의 스택 타일)를 세지 않음(bot_simulator.py:1492-1503, 열쇠 수정과 무관·모든 스택 맵). 의도 여부 확인 필요.
- [x] 58 풀·폭탄 PREREG 16,704판(누적 약 77,600): G(덮인 풀 무지각) gate 실패·미지지, C(폭탄 인지 유지) 클리어·폭탄 실패 오차 크게 개선했으나 실패 분포 TV 악화로 미지지, GC 동일, ALL(K1+P2+G+C) 보고 V 클리어 MAE 13.3→7.9%p. [58 §6](difficulty_personalization/58_bot_grass_bomb_perception_20261027.md).
- [x] 59 채택 판정 PREREG(B vs COMBO=K1+P2+C) 11,520판(누적 약 89,150): **미지지** — craft 층 공동 MSE 2.5배(L82 P2 악화, 쉬운 맵이라 절대값 작음). 전체 클리어 MAE 15.2→10.6%p, key 19.8→8.4, bomb 18.5→9.5. [59 §7](difficulty_personalization/59_bot_combo_adoption_prereg_20261027.md).
- [x] 60 K1C(K1+C) 소규모 채택 PREREG 8,320판(누적 약 97,470): **지지**(4조건). 클리어 MAE 23.8→12.2%p, 새 맵(폭탄 tier1 8) 15.2→8.8, key(재사용) 48.8→17.6. TV 악화(보고만), AF<.80 폭탄 맵은 범주 오차 악화. [60 §7](difficulty_personalization/60_bot_k1c_adoption_prereg_20261027.md).
- [x] 61 plain 진단(784판, 누적 약 98,260): plain 오차는 L378(−47.7)·L388(+23.1) 두 맵(체인·링크·스택). 혼합 문제 기각. **stack_early(보류 옵션)로 L378 θ1.0 0→11/16·L57 →16/16** — 스택 파기 시점이 주원인 가설. 랜덤 배치 맵을 PREREG에서 배치 1개로 측정한 설계 문제 발견(L388·L292). [61](difficulty_personalization/61_bot_plain_diagnosis_20261027.md).
- [ ] (사용자 결정) stack_early 재검증 PREREG(약 6,400판, 한도 상향 필요) · 랜덤 배치 맵 다중 배치 측정(다음 러너부터) · L275 커튼 소진단 · 체인 위험 무지각 가설(클릭 로그 후).
- [x] **K1C 기본 채택 반영**(사용자 승인): C 코어 이식 + V24_DEFAULT에 key_first·bomb_count_awareness. 새 코어 `39d2de55…`(미커밋). 이식 정합 P1 220/220·문서60 재현 P2 15/15·OFF 불변 P3 90/90, 테스트 28건, 회귀 4,433 PASS. 측정 BASE(prior.BASE)·DDA 스크립트 v2.4 기본이 자동 반영, API/에디터(v1) 불변. [26 상단](difficulty_personalization/26_bot_v24.md).
- [x] 62 stack_early 재검증 6,400판(누적 약 106,870/120,000): **미지지**(bomb/grass 층 L269 과대로 2.5배). 전체 클리어 MAE 15.4→7.3%p(목표 달성), 새 맵 9개 12.0→2.7. [62 §7](difficulty_personalization/62_bot_stack_early_prereg_20261027.md).
- [x] 63 진단 2~4단계(3,456판, 누적 약 110,330/120,000): ① 랜덤 배치 착시 맵당 평균 |20.2|%p(최대 48), 16배치 기준 랜덤 맵 클리어 MAE 27.4%p, L388 과대는 실제(93 vs 65), 공통 유틸 `bot_layouts_util_20261027.py`(16배치) ② 체인: 봇은 미인지 턴에도 함정 수 94~100% 회피(비매치라 안 고름), θ1.2 롤아웃 상상 규칙 오인 시 L388 7/8→2/8 — 후보 `chain_cover_misbelief`(상수 q 1개) 설계 제안 ③ L275: 실패가 항상 남은 23타일 병목 독 가득, 정보 공개 무영향 — 병목 전 독 정리 가설. [63](difficulty_personalization/63_bot_layouts_chain_curtain_diag_20261027.md).
- [ ] (사용자 결정) 5단계 모집단 재측정(θ.65/.85 32판+θ1.2 128판=맵당 192, 379맵 ≈72,800판, 한도 ~185,000 필요, stack_early 결정 후) · chain_cover_misbelief PREREG(q 결정 방식) · 병목 독 정리 후보 · 보정 모델 재학습(착수 조건 미충족).
- [x] 64 stack_early 원인 추적(368판, 누적 약 110,700/120,000): 62의 L269 차이(+18%p)는 θ1.2 한 행 6판 차이가 거의 전부, 새 시드 44판에선 1판(+2%p) — **표본 잡음 수준**. 정보 이득 가설 기각(스택이 풀을 안 덮음, SE에서 풀 감소 오히려 늦음), 낮은 θ 독 압박은 방향 불일치. 62 판정 유지. [64](difficulty_personalization/64_bot_stack_early_cause_20261027.md).
- [x] 65 SE 검정력 보완 재검증 7,296판(누적 약 118,000/120,000): **미지지(4조건 모두 실패)**. 미사용 스택 맵 15개(전부 AF≥.95). craft 없는 고정 스택 맵 6개 일관 개선(L137 61→93%), craft+스택 랜덤 맵 L208 74→32%(AF 99%) 큰 악화. 채택 안 함 권장. [65 §7](difficulty_personalization/65_bot_stack_early_power_prereg_20261027.md).
- [x] 66 L208·L149 SE 악화 원인 추적(216판, 누적 약 118,210/120,000): L208 SE는 첫 수부터 스택 7연속 파기(S7→S1)로 독을 단일 타입으로 채우는데 짝이 craft 상자 속·덮인 보드에 있어 초반(남은 47~49) 독 가득 — 16배치 중 10곳에서 악화(배치 특이 아님), craft 픽 2.7 vs 6.0. L149 B′ 과소는 배치별 고정 병목(남은 38/41, 짝이 craft 상자에 갇힘) — L275 병목 계열, SE와 무관. [66](difficulty_personalization/66_bot_stack_early_craft_cause_20261027.md).
- [x] (결정 2026-10-27) stack_early 기각 확정(62·65 미지지, 66 기전), V24_DEFAULT 불변. 누적 한도 120,000→195,000 상향(67 진단 + 5단계용, 5단계는 별도 지시 전 시작 금지).
- [x] 67 랜덤 craft 맵 진단(576판, 누적 약 118,790/195,000): B′ θ1.2 탐색이 미방출 craft 있으면 결정화 거부(5589)로 86~99.5% 꺼짐 — 공개 정보(craft 남은 수, 게임 TileCraft.cs:827-831) 미사용. P2(공개 개수 표본)로 L208 23→29, L149 17→24, L256 15→24/32(정보 상한과 거의 같음). 66 롤아웃 낙관 추론 기각(정정 주석). 사람 가설 지표: craft 첫 오픈 33~44픽(늦음), 빈칸 1~2에서도 비매치 25~75%. [67](difficulty_personalization/67_bot_craft_random_maps_diag_20261027.md).
- [ ] **(중단 2026-10-27 18:46, 재개 대기)** 5단계 dock_reserve_play dev(44/96행·928/2,048판, STOP 정상 정지). P2 채택 완료(코어 `4b31534c…`). 재개·sha·남은 순서·대기열(보정모델 재학습 착수 판단 문서): [resume_note_20261027_1846](difficulty_personalization/resume_note_20261027_1846.md). 누적 약 128,950/195,000(5단계 미포함·시작 금지).
- [x] 68 P2 PREREG 완료(재개 후 8,064판): **지지(4조건)** — craft 20맵 클리어 MAE 10.5→5.8%p, 공동 MSE .0114→.0021. [68 §7](difficulty_personalization/68_bot_p2_craft_parity_prereg_20261027.md).
- [x] 69 L82 추적(192판, P2 −1/48 잡음) · 열쇠 맵 탐색 거부(96판, 잠금 사유 0 → 열쇠 PREREG 불필요). [69](difficulty_personalization/69_bot_l82_trace_key_refusal_20261027.md).
- [x] **P2 기본 채택**(사용자 사전 승인): V24_DEFAULT += public_craft_belief, 코어 `4b31534c…`(미커밋). parity A0✓·ON 9/9·OFF 9/9·V24_DEFAULT 단독 30/30·v1 8/8, 테스트 14건, 스위트 4,647 PASS(test_generator 기존 불안정). 누적 약 128,000/195,000. [26 상단](difficulty_personalization/26_bot_v24.md).
- [ ] (결정 필요) V24_DEFAULT 단독 경로(DDA `make_skill_profile(θ,'v2.4')`, hcs 없음=레거시 롤아웃)와 측정 BASE 정렬 여부 — P2 이전부터의 차이. [69 §2](difficulty_personalization/69_bot_l82_trace_key_refusal_20261027.md).
- [ ] (사용자 결정, 5단계 전) 규칙 정합 수정: 기본 결정화에서 craft 공개 개수 표본(P2 방식) PREREG(craft 맵 고정·랜덤 20맵×2셀×192 ≈7,700판) + 59 L82 악화 추적(~200판). 그 후 행동 후보 dock_reserve_play(새 상수 2, 설계만) 검토.
- [ ] (보류·사후 가설) craft 없는 맵 한정 SE — 새 맵 PREREG 필요.
- [ ] (사용자 결정) SE 보류 유지 vs craft 제외 범위 SE 새 PREREG(미사용 맵 소진·한도 상향 필요) · 랜덤 배치 craft 맵 오차(B′ 149: 49%, 208: 74% vs AF 98~99%) 진단.
- [ ] (사용자 결정) 검정력 보완 SE 재검증 PREREG(θ1.2 128+θ.65/.85 32, 18맵 ≈6,900판, 한도 안) 또는 5단계 모집단 측정에 셀로 포함.
- [ ] (사용자 결정) stack_early: 보류+원인 추적(~300판) 또는 기믹 범위 한정 새 PREREG(~4,000판). DDA 319레벨 재측정(별도 승인). 랜덤 배치 맵 다중 배치 원칙(62 러너 구현).
- [ ] (기록) `test_generator.py` 3건 무작위 불안정 실패(이전 코어로도 재현) — 봇 변경과 무관, 별도 확인 필요.
- [ ] (사용자 결정) K1C 기본 채택 → C 코어 이식·V24_DEFAULT/BASE/API 기본 반영·OFF/ON/이식 정합 테스트·DDA 시드 재측정(319레벨, 우선순위 60 §7-3) — 누적 한도 상향 필요.
- [ ] (사용자 결정) K1+C(P2 제외) 채택용 새 PREREG 여부(누적 잔여 약 10,850판 — 한도 상향 또는 소규모), 채택 시 C 코어 이식·기본값 반영·DDA 시드 재측정(K1+C 319레벨, COMBO 689레벨).
- [ ] (사용자 결정) C 채택(TV 조건 유지 여부)·ALL 조합 채택용 새 PREREG·G 기각 및 풀 과소 실패 새 가설(클릭 로그 필요)·폭탄 맵 남은 일반 실패 과대.
- [ ] (사용자 결정 보류) P2 기본값 채택 · production 배치 약 27,575레벨(unlockTile>0+t0) 봇 결과 재검증 · 프론트 `tileDistributor.ts` 열쇠 배치 정합 · unlockTile=0인데 열쇠 있는 레벨 1개(v1/v2 봇 잠금 0칸).
- [ ] (게임 계측 QA, 마더 전달) `c_KeyTileList`(GetComponentsInChildren)가 비활성 스택/craft 속 타일을 빼는지 런타임 확인 — 빠지면 게임 잠금 칸 0일 수 있음.

## 봇 판 요약(level_summary 동일 정의) (2026-10-27)

- [x] `backend/app/core/bot_play_summary.py`(코어 수정 없음) + 테스트 6건 + 검증 192판(강한 parity 96/96, 범위 위반 0). [26](difficulty_personalization/26_bot_v24.md).
- [ ] (결정 필요) link 짝 포함 범위(cont_first·bomb_left_min), 힌트 폭탄 해제, key_unlock 기록 시점, 동시 종료 우선순위, −1 스캔 범위. 봇 개선 측정은 보류.

## 폭탄+스택 원인 추적·G′ (2026-10-26)

- [x] 리뷰 2 반영: 롤아웃 파기 상태 수정(타당), 잠긴 칸 지적은 해당 없음(테스트로 확인), trace를 강한 parity로 전환(기존 trace는 약한 parity로 표기), 재사용 키별 복사, judge gate 실패 처리. 코어 8592974.
- [x] 원인 추적: 악화 판 18/18이 '미인지 노출 폭탄 + 파기 시작'에서 폭발. 새 seed에서는 악화가 재현되지 않음.
- [x] G′(dig_bomb_yield) PREREG 6,832판: G′≈Gf로 미지지. 미사용 새 8맵에서 Gf가 B보다 악화(L304 73.9→6.1%). 기본 채택 없음.
- [ ] (결정 필요) craft 맵 파기 악화(L304) 원인 추적. 파기 후보를 key·스택 맵으로 한정할지(맵별 예외가 아닌 컨테이너 종류 규칙) 결정. 누적 약 22,360판.

## 파기 여유(container_dig_capacity) 2×2 (2026-10-26)

- [x] opt-in 구현(코어 186b73ab, 기존 stack_early_w 재사용, RNG 미사용) + 테스트 4건. PREREG 2×2 새 실행 6,352판(누적 약 14,250).
- [x] 판정: G·MG 모두 PREREG 미지지. 새 10맵 공동 MSE .0609→.0355, 클리어 MAE 37.8→30.1%p로 크게 개선. 그러나 일반 실패 개선 맵 5/9(<6/9), 폭탄 오차 악화. 기본 채택 없음.
- [ ] (보류·결정 필요) 폭탄+스택 맵 악화 원인 추적(파기 가점과 폭탄 처리 순서의 경쟁 가설). 사후에 기준이나 설계를 고치면 새 PREREG·새 맵이 필요. 두 번째 후보·craft 공개 belief·독 이중 차감·L152는 보류 유지.

## 기억 재측정·독 가득 원인 추적 (2026-10-26)

- [x] `bomb_threat_memory` RNG 분리(코어 17f6445d) 후 기억 ON 2,000판 + regress 16판. 새 8맵 공동 MSE .0755→.0703, 폭탄 오차 8/8 감소 → PREREG 지지, 기본 채택 안 함. baseline은 같은 seed 짝 재사용(독립 재측정 아님).
- [x] 독 가득 추적 160판(+대조 160판): L138 실패 32/37에서 열쇠 2장이 스택 파기 중 독에 고립. L292·306은 θ1.2 탐색이 craft 때문에 대체됨(102/103, 28/29). link·배출 새 타입이 독을 채움.
- [x] `container_dig_capacity` 구현·PREREG 2×2 측정 완료(아래 '파기 여유 2×2' 절).
- [ ] (미실행, 보류) 새 타입 투입량 기준 독 여유 평가. craft 공개 belief 지원 여부 결정.


- [x] 원인 추적 80판(+무추적 대조 80판, 결과 일치): L293 폭탄 사망 = 턴별 독립 인지 재추첨으로 카운트1 턴에 놓침. L152 풀은 클릭 로그 없이 확인 불가, L161과 방향이 반대라 후보 없음.
- [x] `bomb_threat_memory` opt-in(기본 OFF) PREREG 5,200판: 새 8맵 공동 MSE .0755→.0713, 폭탄 실패 오차 7/8 감소 → 사전 기준 충족, 기본 채택 안 함. L292·306은 일반 실패로 이동해 악화.
- [x] key 새 6맵: 클리어 오차 감소 2/6 → 일반화 미지지.
- [ ] (사용자 결정 대기) 레거시 hidden-info 공식의 독 이중 차감: 비실행 경로(ENABLE_HIDDEN_INFO_BLOCK=True라 도달하지 않음, 호출 0회). 현 상태 유지, 정리 여부 미정.
- [ ] 새 맵 봇 과소 성공(클리어 MAE 약 35~46%p)의 주원인(독 관리·탐색) 조사. [26](difficulty_personalization/26_bot_v24.md). 게임·서버 불변, 재선정·업로드 보류, 운영 DDA OFF.

## 공개 컨테이너 잔수 A2·폭탄 마감 (2026-10-26)

- [x] A1(`public_deadline_20261026`) 부분 종료: 배출 좌표 조회 결함으로 실제 상자 조회 0건 → 유효한 잔수 실험 아님. 폭탄 B 무변화는 효과 없음 입증 아님.
- [x] A2 `public_container_origin_value` 71조건·1,136판 완료(seed18M): 진단 공동 MSE .05801→.05808, 확인4맵 .02424→.02728 악화 → 미채택(기본 OFF). L161 +30.6%p·L294 −9.6%p 반대 방향.
- [ ] L152 풀 실패 과소(봇0.8% vs AF58.6%)·폭탄 맵(293/294/449) 폭탄 실패 과대 원인 진단, key 추론 새 맵 일반화. [결과](difficulty_personalization/26_bot_v24.md). 게임·서버 불변, 재선정·업로드 보류, 운영 DDA OFF.

## 행동 가설 분리 비교 (2026-10-26)

- [x] 기억·판별 성향·공개 열쇠/스택 추론 3옵션 독립 비교. 71회귀 실행 PASS(상속 중복 포함),180조건3,840판 완료.
- [x] 사전 기준으로 key 단일 후보 선택 후 새 난수 확인: L448 46.43→60.65%,6맵 MAE21.92→19.55%p. 나머지5맵 동일.
- [ ] 기본 적용 보류: L152/284/293 오차 잔존, 다른 key/stack 맵 일반화 미확인. 기억/성향 미채택. 게임·서버 불변, 재선정·업로드 보류, 운영 DDA OFF. [결과](difficulty_personalization/26_bot_v24.md).

## L152·448·284 기믹 판단 후속 (2026-10-26)

- [x] 36판 추적 +12판 fallback 진단. 연결짝 위험 누락/unsupported 탐색 우회/잠금슬롯 압박 확인.
- [x] `public_gimmick_planning` 비교옵션,53회귀검사 및6맵1,920판 paired 검증 완료.
- [ ] 기본 봇 채택 보류: MAE23.58→24.18%p로 개선 미확인. L152 과대성공, L448/284 과소성공 잔존. [결과와 한계](difficulty_personalization/26_bot_v24.md). 재선정/업로드 보류·운영 DDA OFF.

## 봇 풀 인지·숨김 탐색 국소 보완 (2026-10-26)

- [x] `grass_skill_attention` / `hidden_common_samples` opt-in 구현, 고숙련 미인지·실수 유지, 공개 정보/스택 사본 회귀 42 PASS.
- [x] L151·184·241·293 동일 난수·고정 혼합비 변경 전후 1,024판 비교 및 실패 원인 분포 기록. L293 개선, L184 과대성공 반전·L151/241 과대성공 잔존. [정본](difficulty_personalization/26_bot_v24.md).
- [x] 풀 인지 상한3종·숙련도5종 공동 적합16맵/확인10맵, 5,504판·43건 회귀 완료. 후보 cap0.65·혼합 θ0.65/0.85/1.2=11.64/12.55/75.80%. 확인 MAE15.18→14.67%p, 실패분포 TV0.296→0.249이나 공동 MSE 소폭 악화.
- [ ] L152·448·284 잔차 원인과 새 표본 일반화 검증. 기본 봇 교체·시드 재선정 재개 보류. 실제 업로드 보류, 운영 DDA OFF 유지.

**최종 업데이트**: 2026-07-22
**프로젝트 버전**: MVP + 레벨 생성 자동화 + 봇 시뮬레이터 + 난이도 튜너 + 패턴 합성 강화 + 커스텀 패턴 프로덕션 편입

---

## ⏸ DDA 시드 전 범위 업로드 — 계획·로컬 준비 완료, 업로드 보류 (2026-10-23)
- 계획·분류·드라이런: [52](difficulty_personalization/52_dda_fullrange_upload_plan_20261023.md), 산출물 `backend/data/dda_seeds/fullrange_plan_20261023/`. 서버 요청 0, 운영/무한 DDA OFF.
- 난이도 확인(2026-10-26, 봇 기준): 선별→정밀 방식으로 실행 완료 [53](difficulty_personalization/53_dda_screen_then_refine_20261026.md), 산출물 `backend/data/dda_seeds/screen_refine_20261026/`. 선별통과 475 · 불확실 87 · 평가불가 356 · **재선별 후보(정밀 역전 유지) 58**(교차 역전 7, 업로드완료 L35·45·61·64·72·78·87·93·97 포함) · 정밀 해소/없음 16 · 불확실(정밀) 9 · 정밀 예산 초과 198. 시드 교체 없음.
- 정책 변경(2026-10-26, `codex-dda-shared-official-infinity-20261026`): 목표 = 정식 L32~1530 전체 활성화(지금 아님, 운영·무한 DDA OFF 유지) · 정식/무한 **공통 진행**(DDA 단계·연승·다음 판 예약 공유) · 맵별 lock(시드·실패 횟수, 단계 변경은 다음 판부터) — ~~무한 별도 상태/원본 시작~~ 대체됨. 무한 시드 = `level_501~1530` 4필드 복사 계약 유지, 무한 스위치 별도 유지, 난이도 판단 = `level_{500+N}` 결과 재사용(53 §3-4). 런타임 구현·공통 진행/lock QA = Codex 담당(이 저장소 측정 범위 변화 없음). 상세 52 §1-1.
- 승인 대기: 재선별 후보 58 처리 방식 · 예산 초과 198/불확실 87 추가 정밀 여부 · 평가불가 356 판단 방법 · planned_change 정책(reorder5/write3/미전송, 10필드·7레벨) · 업로드 대상 범위(53 분류 기준으로 재결정) · 무한 853행 복사용 업로더 변경 · 보류 레벨(L86 등 6행) 서버 시드 처리 · L158/L1466/L1523 · 새 manifest(fresh GET) 후 1행 probe.

## ✅ 완료 (2026-07-22)
- **패턴 합성 강화**: 씨앗 기반 생성(A) `seed_positions`+`seed_strength`, 랜덤성 슬라이더, recombine ∪∩∖, template_ratio↑, `_build_seed_variants`(다운스케일 재연결). [문서](CHANGELOG_20260722_PATTERN_SYNTH_AND_FIXES.md)
- **커스텀 패턴 프로덕션 편입**: `preComputePatternIndices`에 활성 커스텀(64+) 합류 → 실제 등장(~28%).
- **검증 false-pass 수정**: 개별검증 canonical RL 통일(봇 matchScore≥70 폐기) + freshest json + 봇게이지 복원.
- **타일 종류 수 튜너** `/tune/tilecount`: 컨테이너-aware ÷3 재타이핑(종류↑=어려움).
- **패턴 디버거**: 크기별 그리기+이름(`/pattern-create-multi`), 5·6·7 필수, 인덱스 주식별자·번호검색·번호순정렬, 고아가드(`/pattern-usage`), 프로덕션 #배지, fallthrough 결정성 fix.
- **보스 템플릿**: unknown·teleport 팔레트, 스토리 컨셉 테마3~5(290~1500, 122개).

### 🔄 착수 예정: 유닛 조립 레이어 생성 (A안 본구현)
- 위층 sparse(타일 미달) 해결: 바닥 큰층=주패턴 / 위층=밀도 높은 소형 유닛(3·6·9) 조립.
- 설계 확정(외부 AI 자문 2회 + covering 교차검증): 경량 Bottom-Up Support-Mask, 인접 받침만으로 floating 0%, 유닛 3배수+예산 3배수→÷3 자연확보, reverse_generation 재사용, 앵커스냅.
- 순서: 유닛 라이브러리 → 예산분배 → mask배치 → 앵커 → 패딩 → reverse연결 → 프로덕션 플래그.

---

## ✅ 완료 (2026-07-16)
- **튜토리얼 기믹 보장**: 언락 첫 스테이지 기믹 100%(생성 종료 재보장+컨테이너+역생성 rescue 후 재보장). 180/180. [문서](CHANGELOG_20260716_TUTORIAL_GIMMICK_GUARANTEE.md)
- **난이도 3단 다이얼**(모양→기믹→색): `/tune/gimmick`, 즉시 프리뷰·캐스케이드·🎲다른모양. [문서](CHANGELOG_20260716_DIFFICULTY_3DIAL.md)
- **색 분산 Potts–Ising**: `/tune/color`, Kawasaki 스왑(÷3보존)+join-count 지표. [문서](CHANGELOG_20260716_COLOR_POTTS_ISING.md)
- **자동 튜너 연동**: `/tune/auto`(색→기믹 target) 순차검증 재생성 대체. A/B 구 대비 3~4배·구제율↑. [문서](CHANGELOG_20260716_AUTO_TUNE_INTEGRATION.md)
- **봇 정확도**: ice 불가판정 게임규칙 완화 + 컨테이너 배출 임팩트 우선 → 보스 거짓실패 해소(L60 0→0.73). RL 자동반영. [문서](CHANGELOG_20260716_BOT_ICE_STACK_FIX.md)
- **좁고깊은(중간보스) 실현성**: `layer_steps`·`concentric_deep` 동심 침식+역생성. 에디터 전체층 표시. [문서](CHANGELOG_20260716_NARROW_DEEP_CONCENTRIC.md)

### 후속(선택)
- 중간보스(×5,¬×10) 정식 슬롯 UI + 난이도스케일. 동심 클리어 패턴 화이트리스트. 봇 탐색 강화(근본).

---

## ✅ 완료 (2026-07-15) — 난이도 미세조절 색 재배치 튜너
- 재생성 없이 타일 색(t1~15)만 재배치해 목표 클리어율 근접(모양·÷3·기믹 보존).
- 백엔드 `POST /api/tune/arrangement` (신규 독립 파일 `tune.py`) + 레벨행 🎚️미세 버튼 + 순차검증 실패시 색조절 우선 폴백.
- 검증: L100/L120 목표 명중(gap≤0.02), 모양·÷3·기믹 보존 확인. 양극화 지형(L50)은 재생성 폴백.
- 문서: [CHANGELOG_20260715_ARRANGEMENT_TUNER.md](CHANGELOG_20260715_ARRANGEMENT_TUNER.md)
- 향후(선택): 달성범위 프로브, 후보 refinement, 생성 파이프라인 2단계화(t0→난이도최적 색베이크).

---

## 작업 상태 범례

- 대기 중 - 아직 시작 안 함
- 진행 중 - 현재 작업 중
- 완료 - 작업 완료
- 취소/보류 - 작업 취소 또는 보류

---

## 최근 (2026-07-06)

- 🧪 **[프론트][백엔드][기능] 보스 템플릿 반자동 제작 시스템**: 프로덕션 보스(10의배수)를 모양=수동그림/타입·기믹·검증=자동으로 제작. 🏰 탭(다층 t0 그리기·홀짝8/7·인게임충실 프리뷰·수동기믹 팔레트·스토리 컨셉노트·난이도파악 3레버[목표난이도 자동/skill_mean 슬라이더/타일종류 슬라이더]). 백엔드 boss_templates·boss_concepts 스토어 + /generate/from-boss-template(인라인 layers 미리보기·useTileCount override). 기믹 자동배치(속성 _add_obstacles + craft/stack 골, 수동기믹 보존). 순차검증 _boss_template_id 재생성 정합. **레벨대별 완화**: 10~30(floor없음·목표×0.75)/40~100(floor8·×0.65)/110+(floor9·×0.5) — 초반 튜토리얼 보호. 스토리=할아버지정원 1~5챕터 실데이터 연계. tsc/문법0, RL파이프·수동기믹보존·craft골·완화 검증. **사용자 테스트 중**. → `CHANGELOG_20260706_BOSS_TEMPLATE_SYSTEM.md`
  - 🔎 주의: 챕터별 실 star cost = GameBoost 서버 런타임(repo에 없음). 설계문서 star값(테마1=14)은 실데이터(20)와 불일치(stale).
  - ⬜ 후속: 보스 기믹 craft sort는 게임측 수정 대기(HANDOFF_INGAME_CRAFT_SORT). 작은 보스=쉬움(타일수 부족)→셀/층 늘려야.

## 최근 (2026-07-03)

- 🔎 **[조사][게임측] craft 뚜껑/배출 sort 불일치 + 인게임 sort 전면감사 — 인게임 이관**: 24레벨 craft_w@layer2 "1_2" 뚜껑/배출타일이 아래행 일반타일에 덮여 부자연. 설계의도(바닥=내부가림, 뚜껑=회전개방하며 배출타일이 바닥<배출<뚜껑)는 정상 구현되나, 생성기 파츠 sort가 전부 자기셀(init) 기준인데 스프라이트는 여러셀 걸침 → 아래행(init+5)이 뚜껑(init)보다 앞. `SetCraftPartsOrder`(TileCraft.cs:582): 뚜껑=init, 바닥=init-3, 배출=init-1, 내부=init-10. 인게임 sort 전면감사 결과 **실 sort 버그=craft 하나뿐**(teleport/shuffle=제자리 타입교환 sort정상, frog=의도된 max오버레이 → 오탐). 수정방향 A(걸치는셀 최대 grid sort+α)/B(착지셀 기준) 제시. → `INVESTIGATION_20260703_CRAFT_TILE_SORT.md`, 이관 프롬프트 `HANDOFF_INGAME_CRAFT_SORT.md`
- 🧪 **[프론트][기능] 프로덕션 자동 연속생성 큐**: 자리비움(야간) 운용 — 1500레벨 배치를 목표 개수(0=무한)까지 순차 자동 생성. `handleStartGeneration`에 `overrideBatchId` 추가(명시 batchId → 상태 비의존) + `Promise<boolean>` 반환. `handleAutoQueueStart` 루프(create→await 생성 완료→다음), `autoQueueStopRef`로 즉시 중단. 생성 탭 최상단 패널(프리셋+목표수+시작/정지+진행표시, localStorage 유지). 로컬 CPU 상한이라 순차(back-to-back), 배치당 ~20~40분 → 야간 8h ≈ 12~19배치. **주의**: 절전 해제(`caffeinate -dis`)+탭 열어두기. tsc 0. **사용자 E2E 테스트 중**. → `CHANGELOG_20260703_AUTO_QUEUE.md`
  - 💡 온라인 위임 대안(기각): 백엔드 무상태라 Cloud Run에 올리고 `VITE_API_URL` 하나로 교체 시 동시 다수 배치 진짜 병렬(오토스케일). 무료티어 월 180k vCPU-초(결제계정당·매월리셋)≈20배치. 이번엔 로컬 자동화 채택.
- ✅ **[백엔드][프론트][기능] 보스 레벨 전용 생성기 + 템플릿 크롭 + 디바이스 그리드 제약** (커밋 `dd457ba`): 10x10 보스 실기 가독성 문제(타일 과소) 해결. `boss_mode` 파라미터 → 그리드 선언 최대 8·5~6층·`BOSS_RECIPES` 12종 결정적 로테이션·목표 클리어율 절반. `crop_level_to_max_dim`(순수 좌표 시프트, 타일수·÷3 불변)로 기존 템플릿 A(원래≤8)/B(크롭→≤8) 차용, D(불가)는 레시피 폴백. 순차검증 그리드 게이트(>8 실패)로 무한루프 차단. Test탭 skill_mean 표시 UI. 크롭 12템플릿 검증(B5→8, D7 유지, 무결), 보스 스모크 8층·÷3 0. 데이터: B보스 30개 크롭(v38). → `CHANGELOG_20260703_BOSS_GENERATOR_AND_CROP.md`
- ✅ **[백엔드][프론트][버그] craft/stack 내부 타일 단색 뭉치 해소 + bake 폴백 + sync** (커밋 `4522f67`,`31fa822`,`e133d7b`): 상자/스택 내부가 동일 타입 3개로 배출되던 문제. (1) `bakeFullBoard` 미해결 inner `t1` 몰빵 폴백 제거(개수만 유지→게임 재분배). (2) `_diversify_container_inner_tiles`(생성 마지막 단계): 게임 분배 재현 후 컨테이너 중복 슬롯↔필드 다른타입 라벨 스왑(순열→÷3 불변) → 명시 신포맷 출고. 근본원인=필드 전량 명시라 내부만 t0분배+세트단위 배정→단색 확정. 기존 배치 87레벨 192스왑 수리(v35). (3) 서버 배치 버전비교 pull(`__server_version`) → stale 로컬 자동 갱신 + 리로드 후 충돌감지. → `CHANGELOG_20260703_CONTAINER_INNER_DIVERSIFY.md`

---

## 최근 (2026-07-01)

- ✅ **[백엔드][프론트][개선] 재생성 타일종류 그래프 고정 + 독천장 제거 + RL 난이도 기준 실력 슬라이더**: (1) 순차검증 재생성(`handleRegenerateLevel`/`genCandidate`)이 난이도식으로 종류수 덮어쓰던 것 → `vAtLevel(그래프)` 고정. (2) 독천장(`allow_high_tile_variety`+dock 캡+td 캡) 전면 제거 → useTileCount=그래프값(800→11,1200→12). (3) `/api/rl-sim/level`에 `skill_mean`(0 초보~1 고수) 추가 + 프로덕션 슬라이더 → 순차검증 RL 기준 실력 조절 = 전체 난이도 조절(초기 생성값 불변, 검증 기준만). py+tsc 0, API 실측(그래프값·재가중·통과판정) 확인. → `CHANGELOG_20260701_TILE_VARIETY_AND_RL_SKILL.md`
  - ⬜ 후속: 실플레이 캘리브레이션(테스트셋 플레이 → θ 피팅 → skill_mean 자동 추천) 도구 — 사용자 플레이 중
  - 🔎 트레이드오프: 타일종류 고정↔난이도목표 물리충돌(종류=지배레버). RL 신뢰성: 고종류 레벨서 과소예측(솔버/expert봇 병행 확인 권장)
- ✅ **[백엔드][버그] OOB 타일 클리어 불가 회귀 수정**: 선언 col/row 밖(x==col/x==-1/y==row 등) 타일이 디바이스에서 컬링→렌더 불가→타입 3배수 실질 붕괴→클리어 불가. 원인: `_fix_visual_centering` 시프트 클램프 누락 + 일부 aesthetic 패턴 생성기 offset over-range + 미러 반사. `generator.generate()` 반환 직전 단일 초크포인트 `_remove_out_of_bounds_tiles` 추가(÷3은 뒤 finalize+FINAL_REPAIR 재보장). 검증: 인프로세스 30 + API 164 gens 전부 OOB 0·정규÷3 위반 0, 솔버빌리티 IMPOSSIBLE 0. B와 무관(저레벨도 발생). → `CHANGELOG_20260701_OOB_TILE_REPAIR.md`
  - 🔎 디버깅 주의: `/generate`는 pool 워커 실행 → `pkill -f uvicorn`만으로 spawn 자식 잔존(구코드 서빙). `lsof -ti:8000 | xargs kill -9` 후 재기동. 검증은 인프로세스 import로.
- ✅ **[백엔드][버그] 고아 link 기믹 인게임 스폰 NRE 수정**: 존재하지 않는 위치로 link 연결(예 Lv68 `1_0`link_n→`1_-1` OOB, `2_4`link_e→`3_4` 없음) → 게임 `FindLinkTile` `GetTile(...)[0]` null → NullReferenceException 스폰 크래시. 원인: 링크 배치 후 변형단계(centering 시프트/÷3 삭제/OOB 제거)가 대상 타일 이동·삭제 → 고아. 반환 직전 `_strip_orphaned_link_tiles`(대상 없는 link 속성만 제거) 추가. 검증: link 레벨 48 gens 고아 2→0, API 44 gens 0. **게임 link 오프셋 수정(46998fbb)은 무관**(E/W 비주얼 오프셋만, FindLinkTile 불변). → `CHANGELOG_20260701_OOB_TILE_REPAIR.md`
- 🔎 **[백엔드][진단] 타일 종류 수 고정 그래프 미준수 — 원인=검증/재생성 경로**: 프로덕션 그래프(레벨번호별 useTileCount)가 생성 후 더 적게 사용됨. 실측: **코어 `/api/generate`는 그래프 준수**(t0 레벨 useTileCount=cfg 유지, 클라 런타임 분배). **`/api/generate/validated`(순차검증)가 원인** — `generate_validated_level`이 그래프 대신 난이도등급 기반 `TILE_RANGES[grade]`로 base 결정(generate.py:1730)하고 재시도 시 `current_tile_types.pop()`으로 `min_tile_types`(=3)까지 감소(generate.py:2294) → 실측 Lv200~800 utc 9~11 → **3으로 붕괴**. tile_type_profile/레벨그래프 미참조. ⬜ 제안: validated가 `get_use_tile_count_for_level(level_number, tile_type_profile)`를 base로 쓰고 고정변량이면 pop 비활성(변량을 난이도 레버에서 제외). **사용자 확인 후 구현 예정**(동작 변경).
- ✅ **[백엔드][프론트엔드][개선] 층별 그리드 크기 다양화 (B)**: 절차생성 멀티레이어에서 각 층 채움 모양을 랜덤 s×s(min 3~그리드, 인접층 회피)로 중앙배치 → 스택 실루엣 다양화. **레이어 col/row(홀짝 교대값) 유지 → 게임 무변경**(rowCount 그리드 생성, FindAllUpperTiles xCol 블로킹). `size_diversity_start_level`(기본 101, <start 미적용). generator standard/master+auto 경로 주입, ProductionDashboard UI. py_compile+tsc 0, 헬퍼 유닛 12000픽 위반0·비단조 2000/2000, API col교대·num%3·게이팅 확인, 솔버빌리티 회귀0, GameBoost 라운드트립 보존. → `DESIGN_LAYER_SIZE_DIVERSITY.md`
  - ✅ 동봉(A): `max_layers` 캡 7→10 상향(ProductionDashboard 여러 경로)
  - ⬜ 후속: Test/Review 탭 단일 재생성/enhance에 다양화 미배선(주 배치 생성만) → tab prop 전파 검토
  - ⬜ 후속: Unity 실기 수동 확인(MCP 미연결). level_110/112 GameBoost 업로드 완료 → 수동 플레이
- ✅ **레벨 템플릿 → 보스 배치**: 전 레벨 흩뿌리기 → 보스(10,20,..) 전용 순차배치(measured_difficulty 오름차순). overflow=unused, best-gap은 spill 정책으로 격리 보존. `ProductionDashboard`. tsc 0 + 로직 시뮬 4케이스 통과. → `DESIGN_BOSS_TEMPLATE_ASSIGN.md`
  - ⬜ 후속: 실제 배치 생성 UI 검증(Playwright 부재로 수동), 템플릿 많아지면 overflow='spill' 활성 검토

---

## 작업 유형 태그

| 태그 | 설명 |
|------|------|
| `[백엔드]` | Python/FastAPI 백엔드 작업 |
| `[프론트엔드]` | React/TypeScript 프론트엔드 작업 |
| `[자동화]` | CLI 도구 및 자동화 스크립트 |
| `[API]` | REST API 엔드포인트 |
| `[UI]` | 사용자 인터페이스 |
| `[기믹]` | 게임 기믹/장애물 관련 |
| `[문서]` | 문서화 작업 |
| `[테스트]` | 테스트 코드 작성 |
| `[버그]` | 버그 수정 |
| `[개선]` | 기능 개선 |

---

## 병렬 작업 규칙 (필독)

**다중 세션 작업 시 충돌 방지를 위한 규칙:**

1. **작업 시작 즉시 상태 변경**: 작업을 시작하면 **즉시** `대기 중` → `진행 중`으로 변경하고 담당자 기입
2. **담당자 명시**: `**담당자**: Claude-세션ID` 형식으로 기입
3. **작업 중인 항목 건드리지 않기**: `진행 중` 상태인 작업은 다른 세션에서 수정 금지
4. **완료 즉시 상태 변경**: 작업 완료 시 바로 `진행 중` → `완료`로 변경하고 완료 섹션으로 이동
5. **파일 수정 전 확인**: 같은 파일을 수정하는 작업이 진행 중인지 확인

**충돌 발생 시:**
- 먼저 시작한 세션이 우선권 가짐
- 충돌 발견 시 해당 작업 중단하고 다른 작업 선택

---

## 우선순위

### 높음 (High Priority)

---

#### 대기 중 [프론트엔드] 봇 시뮬레이션 뷰어 개선
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `frontend/src/components/SimulationViewer/BotTileGrid.tsx`

**현재 상태**:
BotTileGrid.tsx 파일이 수정됨 (git status에서 확인)

**요구 사항**:
- [ ] 현재 수정 내용 확인 및 완성
- [ ] 타일 시각화 개선
- [ ] 애니메이션 안정화
- [ ] 봇 이동 경로 표시 개선

---

### 중간 (Medium Priority)

#### 완료 [프론트엔드] 벤치마크 대시보드 UI
**담당자**: Claude
**완료일**: 2026-02-24
**관련 파일**: `frontend/src/components/BenchmarkDashboard/index.tsx`

**구현 내용**:
벤치마크 시스템 전체 현황을 한눈에 볼 수 있는 대시보드 UI 구현

**체크리스트**:
- [x] 티어별 레벨 개수 및 상태 표시
- [x] 레벨 검증 결과 표시 (봇별 목표/실제 클리어율)
- [x] 티어 선택 및 레벨 상세 보기
- [x] 전체 검증 기능
- [x] 에디터로 레벨 로드 기능

---

---

#### 완료 [API] 게임부스트 서버 연동
**담당자**: Claude
**완료일**: 2026-02-24
**관련 파일**: `backend/app/clients/gboost.py`, `backend/app/api/routes/gboost.py`, `frontend/src/components/GBoostPanel/`

**구현 내용**:
로컬 레벨을 게임부스트 서버에 업로드하는 기능 구현 완료

**체크리스트**:
- [x] GBoostClient 클래스 구현 (TownPop 패턴)
- [x] 인증 시스템 구현 (선택적 API key)
- [x] 레벨 업로드 API 완성 (썸네일 자동 생성 포함)
- [x] 레벨 다운로드 API 구현
- [x] 레벨 목록 조회 및 삭제 API
- [x] 로컬 레벨 일괄 업로드 기능
- [x] 프론트엔드 설정 패널 및 마이그레이션 도구

---

### 낮음 (Low Priority)

#### 대기 중 [프론트엔드] 레벨 에디터 추가 개선
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `frontend/src/components/GridEditor/`

**작업 내용**:
- 드래그 앤 드롭 타일 배치
- 복사/붙여넣기 기능
- ~~실행 취소/다시 실행~~ ✅ 완료 (2026-02-11)

---

#### 대기 중 [테스트] E2E 테스트 작성
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `tests/`, `frontend/tests/`

**작업 내용**:
전체 시스템 통합 테스트 작성

**체크리스트**:
- [ ] 백엔드 API 테스트
- [ ] 프론트엔드 컴포넌트 테스트
- [ ] 시뮬레이션 정확성 테스트

---

#### 대기 중 [문서] 사용자 가이드 작성
**담당자**: 미정
**생성일**: 2025-12-30
**관련 파일**: `claudedocs/USER_GUIDE.md`

**작업 내용**:
일반 사용자를 위한 도구 사용 가이드 작성

---

## 완료된 작업

### 완료 [개선][백엔드] 패턴 밀도 동적 조정 (v15.7)
**담당자**: Claude
**완료일**: 2026-03-10
**관련 파일**: `backend/app/core/generator.py`

**구현 내용**:
- `target_difficulty` 파라미터를 패턴 생성 함수에 전달
- 난이도에 따른 패턴 밀도 자동 조정 (높은 난이도 = 더 밀집된 패턴)

---

### 완료 [개선][프론트엔드] 레벨 생성 실패율 개선 (v15.6)
**담당자**: Claude
**완료일**: 2026-03-09
**관련 파일**: `frontend/src/components/ProductionDashboard/index.tsx`

**구현 내용**:
- 점진적 허용오차: 5% → 7.5% → 10% (시도 횟수에 따라)
- API 실패 시 1회 재시도 로직 추가
- 후보 다양성 증가: 레이어 ±1, 기믹 강도 ±20%
- MAX_ATTEMPTS: 5 → 6 증가

**문서**: [CHANGELOG_20260309_GENERATION_FAILURE_IMPROVEMENT.md](CHANGELOG_20260309_GENERATION_FAILURE_IMPROVEMENT.md)

---

### 완료 [개선][백엔드] 패턴 다양성 개선 (v15.5)
**담당자**: Claude
**완료일**: 2026-03-09
**관련 파일**: `backend/app/core/generator.py`, `frontend/src/components/ProductionDashboard/index.tsx`

**구현 내용**:
- 피라미드 효과: 상위 레이어가 점점 작아지는 3D 깊이감 적용 (shrink_rate 0.9)
- 연속 패턴 방지: 연속 레벨에서 동일 패턴 재사용 방지
- 패턴 6 (Corner Anchored) 개선: 4꼭짓점 + 1타일 브릿지 연결

**문서**: [CHANGELOG_20260309_PATTERN_SYSTEM_UNIFICATION.md](CHANGELOG_20260309_PATTERN_SYSTEM_UNIFICATION.md)

---

### 완료 [개선][프론트엔드] 패턴 시스템 통합 (v15.4)
**담당자**: Claude
**완료일**: 2026-03-09
**관련 파일**: `frontend/src/components/ProductionDashboard/index.tsx`

**구현 내용**:
- 64개 aesthetic 패턴만 사용 (geometric/clustered 제거)
- 보스/특수/일반 레벨별 패턴 풀 선택
- 모든 레벨에 pattern_index 명시적 지정 → 64배 성능 개선

---

### 완료 [버그][백엔드] useTileCount Fallback 버그 수정
**담당자**: Claude
**완료일**: 2026-03-04
**관련 파일**: `backend/app/api/routes/generate.py`, `frontend/src/components/ProductionDashboard/index.tsx`

**문제**: `/api/generate` 엔드포인트의 fallback 로직에서 `tile_types`가 고정값 `["t1", "t2", "t3"]`으로 설정되어 `useTileCount`가 3으로 잘못 설정됨

**해결**:
- Fallback 로직에서 `tile_types = None`으로 변경하여 level_number 기반 자동 선택 유지
- 프론트엔드에 잘못된 useTileCount 레벨 감지 및 일괄 재생성 UI 추가

**결과**: 레벨 1259의 useTileCount가 11로 정상 설정됨

**문서**: [CHANGELOG_20260304_USETILECOUNT_FIX.md](CHANGELOG_20260304_USETILECOUNT_FIX.md)

---

### 완료 [프론트엔드][UI] 프로덕션 탭 레벨 분포도 그래프 UI
**담당자**: Claude
**완료일**: 2026-03-04
**관련 파일**: `frontend/src/components/ProductionDashboard/LevelDistributionChart.tsx`

**구현 내용**:
- recharts 라이브러리를 사용한 ScatterChart 기반 레벨 분포 시각화
- Y축 선택: 목표 난이도 / Casual/Average/Expert 클리어율 / 매치 점수
- 색상 모드: 검증 상태 (통과/실패/미검증/미생성) 또는 난이도 등급 (S/A/B/C/D)
- Brush 컴포넌트로 레벨 범위 선택
- 커스텀 Tooltip으로 레벨 상세 정보 표시
- 통계 요약: 검증 상태별 레벨 수

**체크리스트**:
- [x] `npm install recharts` 실행
- [x] `LevelDistributionChart.tsx` 컴포넌트 생성
- [x] ScatterChart로 레벨 분포 시각화
- [x] 검증 상태별 색상 구분
- [x] Y축 전환 기능
- [x] Brush 컴포넌트로 범위 선택
- [x] 레벨 클릭 이벤트 핸들러
- [x] ResponsiveContainer로 반응형 디자인
- [x] ProductionDashboard Overview 탭에 통합

---

### 완료 [버그][백엔드] Key 타일 이중 생성 버그 수정
**담당자**: Claude
**완료일**: 2026-03-03
**관련 파일**: `backend/app/core/bot_simulator.py`

**문제**: 레벨 JSON에 명시적 `key` 타일 + `unlockTile` 설정 시 t0 분배에서 추가 key 생성 → 초과 key 문제

**해결**:
- `_create_initial_state()`에서 명시적 key 타일 카운트
- `effective_unlock_tile = max(0, unlock_tile - explicit_key_sets)` 계산
- t0 분배 시 조정된 값 사용

**결과**: 12개 → 6개 (정확히 `unlockTile * 3`)

---

### 완료 [개선][백엔드] 봇 희생 전략 (Strategic Unblock Bonus) 구현
**담당자**: Claude
**완료일**: 2026-03-03
**관련 파일**: `backend/app/core/bot_simulator.py`

**구현 내용**:
- `_score_move_with_profile()`에 레이어 블로킹 해제 보너스 추가
- 언블로킹된 타일이 dock 타입 매칭 시 추가 점수
- 같은 타입 타일 언블로킹 시 연속 플레이 보너스
- `blocking_awareness >= 0.5` 봇에서 활성화

**목적**: 봇이 즉시 매칭 안 되더라도 하위 레이어 접근을 위해 전략적 타일 선택

---

### 완료 [개선][백엔드] Generator Key 타일 검증 함수 추가
**담당자**: Claude
**완료일**: 2026-03-03
**관련 파일**: `backend/app/core/generator.py`

**구현 내용**:
- `_validate_and_fix_key_tile_count()` 함수 추가
- 게임 클라이언트 호환성: `unlockTile > 0`이면 모든 명시적 key를 t0로 변환
- 게임 클라이언트(C#/Unity)의 t0 분배가 정확한 key 개수 생성하도록 보장

---

### 완료 [버그][백엔드] 폭탄 기믹 가시성 수정
**담당자**: Claude
**완료일**: 2026-03-03
**관련 파일**: `backend/app/core/generator.py`

**문제**: 폭탄이 상위 레이어 타일에 가려진 위치에 배치되면 플레이어에게 보이지 않음

**해결**:
- `_add_bomb_obstacles_to_layer()` 함수 수정
- 상위 레이어에 의해 가려진 위치는 `covered_positions` 세트로 사전 계산
- 가려진 위치에는 폭탄을 배치하지 않음

**결과**: 폭탄이 항상 플레이어에게 보이는 위치에 배치됨

---

### 완료 [프론트엔드] 레벨 에디터 UX 대규모 개선 (P0-P2)
**담당자**: Claude
**완료일**: 2026-02-11
**관련 파일**: `frontend/src/components/`, `frontend/src/stores/`

**구현 내용**:

| 우선순위 | 개선 항목 | 설명 |
|----------|-----------|------|
| P0 | 자동생성 → 에디터 연결 | GenerationResultCard, 탭 자동 전환 |
| P0 | 시뮬레이션 결과 시각화 | 목표/실제 등급 비교, 재검증 알림 |
| P1 | 기믹 언락 레벨 표시 | 레벨별 기믹 해금 표시, 미해금 비활성화 |
| P1 | 에디터 내 즉시 검증 | levelVersion 추적, 변경 감지 알림 |
| P2 | 레이어 3D 프리뷰 | LayerStackPreview 컴포넌트, 밀도/기믹 시각화 |
| P2 | Undo/Redo 기능 | 히스토리 50개, Ctrl+Z/Y 단축키 |

**수정된 파일**:
- `App.tsx` - 탭 전환 지원
- `AutoPlayPanel/index.tsx` - 시뮬레이션 시각화 개선
- `GeneratorPanel/index.tsx` - 결과 카드, 기믹 언락 표시
- `GridEditor/index.tsx` - Undo/Redo 버튼, 키보드 단축키
- `GridEditor/LayerStackPreview.tsx` - 신규 컴포넌트
- `levelStore.ts` - 히스토리 스택, 버전 추적
- `uiStore.ts` - 탭 전환 상태 관리

**문서**: [UX_IMPROVEMENT_PLAN.md](UX_IMPROVEMENT_PLAN.md)

---

### 완료 [자동화] 레벨 난이도 자동 검증 시스템
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `validate_level_difficulty.py`

**구현 내용**:
- 100회 반복 테스트로 통계적 유의성 확보
- 5가지 봇(Novice, Casual, Average, Expert, Optimal) 테스트
- 허용 편차: ±15% 이내 PASS, 15-22.5% WARN, 22.5% 초과 FAIL
- 개선 제안 시스템
- 티어 단위 및 개별 레벨 검증 지원

---

### 완료 [API] 통합 대시보드 API
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/api/routes/simulate.py`

**구현된 엔드포인트**:
- `GET /api/simulate/benchmark/list` - 벤치마크 레벨 목록
- `GET /api/simulate/benchmark/{level_id}` - 개별 레벨 조회
- `GET /api/simulate/benchmark/dashboard/summary` - 대시보드 요약
- `POST /api/simulate/benchmark/validate/{level_id}` - 레벨 검증

---

### 완료 [자동화] 레벨 생성 도구 자동화
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `generate_benchmark_levels.py`

**구현 내용**:
- 파라미터 기반 레벨 생성
- 자동 검증 통합
- 자동 보정(Calibration) 기능
- 배치 생성 지원
- 검증 실패 시 개선 제안

---

### 완료 [API] 로컬 레벨 관리 시스템
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/api/routes/simulate.py`, `backend/app/storage/local_levels/`

**구현된 엔드포인트**:
- `GET /api/simulate/local/list` - 로컬 레벨 목록
- `GET /api/simulate/local/{level_id}` - 개별 레벨 조회
- `POST /api/simulate/local/save` - 레벨 저장
- `DELETE /api/simulate/local/{level_id}` - 레벨 삭제
- `POST /api/simulate/local/import-generated` - 일괄 임포트

---

### 완료 [백엔드] 봇 시뮬레이터 구현
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/core/bot_simulator.py`

**구현 내용**:
- 5종 봇 프로필 (Novice, Casual, Average, Expert, Optimal)
- 15개 기믹 지원 (Ice, Chain, Grass, Link, Frog, Teleport, Curtain, Bomb, Craft, Stack 등)
- 결정론적 시뮬레이션 (동일 시드 = 동일 결과)
- 시각적 시뮬레이션 (단계별 게임 상태 추적)

---

### 완료 [백엔드] 레벨 생성기 구현
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `backend/app/core/generator.py`

**구현 내용**:
- 장애물 생성 (Ice, Chain, Grass)
- 장애물 개수 min/max 범위 설정
- 유효성 검증 강화
- 타일 수 조정 후 장애물 재검증

---

### 완료 [프론트엔드] GeneratorPanel UI
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `frontend/src/components/GeneratorPanel/index.tsx`

**구현 내용**:
- 장애물 개수 슬라이더 (min/max)
- Grass 장애물 옵션
- API 파라미터 확장 (`obstacle_counts`)

---

### 완료 [프론트엔드] GridEditor 개선
**담당자**: Claude
**완료일**: 2025-12-23
**관련 파일**: `frontend/src/components/GridEditor/index.tsx`

**구현 내용**:
- effect_type 시각화
- Dock 상태 유지 (게임 오버 시에도 보존)

---

### 완료 [테스트] 기믹별 시뮬레이션 테스트
**담당자**: Claude
**완료일**: 2025-12-30
**관련 파일**: `test_gimmicks.py`

**테스트 결과**: 10/10 PASS (Multi-bot + Visual Simulation 모두 통과)

| 기믹 | 결과 | 설명 |
|------|------|------|
| Ice | PASS | 노출 시 다른 타일 선택마다 1겹씩 감소 |
| Bomb | PASS | 노출 시 카운트다운 감소, 0이면 게임오버 |
| Chain | PASS | 좌우 인접 타일 클리어로 해제 |
| Grass | PASS | 인접 타일 클리어 시 1겹씩 제거 |
| Link | PASS | 연결된 타일 함께 선택 (독 2칸 사용) |
| Frog | PASS | 랜덤 점프하여 타일 블로킹 |
| Stack | PASS | 방향별 타일 밀림 |
| Curtain | PASS | 열림/닫힘 토글 |
| Teleport | PASS | 3회 클릭마다 위치 교환 |
| Craft | PASS | 타일 생성 |

**수정 내역** (2025-12-30):
- `test_gimmicks.py`: Visual Simulation API 응답 파싱 로직 수정
  - `bot_results[0]`에서 `cleared`, `total_moves` 추출하도록 변경

---

### 완료 [백엔드] EASY 티어 레벨 구현
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/models/benchmark_level.py`

**구현 내용**:
- 10개 레벨 (easy_01 ~ easy_10)
- 99-100% 클리어율 달성
- 기본 매칭 연습용

---

### 완료 [백엔드] MEDIUM 티어 레벨 구현 (초기 버전)
**담당자**: Claude
**완료일**: 2025-12-22
**관련 파일**: `backend/app/models/benchmark_level.py`

**구현 내용**:
- 10개 레벨 (medium_01 ~ medium_10)
- 현재 98.9-100% 클리어율 (재설계 필요)
- ICE, 2레이어 도입

---

## 작업 유형별 요약

### 구현 현황

| 기능 | 상태 | 비고 |
|------|------|------|
| 봇 시뮬레이터 | 완료 | 15개 기믹, 5종 봇, v15.7 |
| 레벨 생성기 | 완료 | 64개 패턴, 피라미드 효과 |
| 프로덕션 대시보드 | 완료 | 1500레벨 자동 생성/검증 |
| 레벨 검증기 | 완료 | CLI 도구 |
| 대시보드 API | 완료 | 4개 엔드포인트 |
| 로컬 레벨 관리 | 완료 | CRUD API |
| 게임부스트 연동 | 완료 | 업로드/다운로드/삭제 |

### 봇 프로필

| 봇 | 실수율 | Lookahead | 목표 클리어율 |
|----|--------|-----------|--------------|
| NOVICE | 40% | 0 | ~40% |
| CASUAL | 20% | 1 | ~60% |
| AVERAGE | 10% | 2 | ~75% |
| EXPERT | 2% | 5 | ~90% |
| OPTIMAL | 0% | 10 | ~98% |

### 구현된 기믹 (15개)

| 기믹 | 코드 | 봇 지원 |
|------|------|---------|
| None | `none` | 완료 |
| Ice | `ice` | 완료 |
| Chain | `chain` | 완료 |
| Grass | `grass` | 완료 |
| Link East/West/South/North | `link_e/w/s/n` | 완료 |
| Frog | `frog` | 확률적 |
| Teleport | `teleport` | 완료 |
| Curtain | `curtain` | 완료 |
| Bomb | `bomb` | 완료 |
| Craft | `craft` | 완료 |
| Stack N/S/E/W | `stack_n/s/e/w` | 완료 |

---

## 작업 추가 방법

새 작업을 추가할 때는 다음 형식을 사용하세요:

```markdown
#### 상태 [태그] 작업 제목
**담당자**: [이름 또는 미정]
**생성일**: YYYY-MM-DD
**관련 파일**: [파일 경로]

**작업 내용**:
- 작업 상세 설명

**체크리스트**:
- [ ] 세부 작업 1
- [ ] 세부 작업 2
```

**상태 변경 시**:
- `대기 중` → `진행 중` (작업 시작)
- `진행 중` → `완료` (작업 완료, "완료된 작업" 섹션으로 이동)
- `대기 중` 또는 `진행 중` → `취소/보류` (작업 취소)

---

## 관련 문서

- [PROJECT_INDEX.md](PROJECT_INDEX.md) - 프로젝트 인덱스
- [AUTOMATION_SUMMARY.md](AUTOMATION_SUMMARY.md) - 자동화 시스템 요약
- [BENCHMARK_API_GUIDE.md](BENCHMARK_API_GUIDE.md) - API 가이드
- [LEVEL_GENERATION_GUIDE.md](LEVEL_GENERATION_GUIDE.md) - 레벨 생성 가이드
- [LOCAL_LEVELS_GUIDE.md](LOCAL_LEVELS_GUIDE.md) - 로컬 레벨 관리 가이드
- [SPECIFICATION.md](../SPECIFICATION.md) - 구현 명세서

---

**문서 버전**: 1.0
**작성자**: Claude

## [웹뷰 개선] 백그라운드 작업 완료 알림 (2026-06-18)
**문제:** 웹뷰에서 백그라운드 팀원(에이전트) 작업 지시 후, 완료 시 웹뷰로 돌아오는 훅/알림이 없어 응답을 오래 못 받음.
**개선:** 백그라운드 task 완료 시 웹뷰에 알림(notification/폴링/SSE) 띄우는 훅 추가 필요.
- 후보: task 완료 이벤트 → 웹뷰 토스트/뱃지, 또는 작업목록 패널에 상태 폴링.
**상태:** 미착수 (별도 작업으로 분리).
