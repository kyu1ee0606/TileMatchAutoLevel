# CHANGELOG 2026-07-22 — 패턴 합성 강화 · 커스텀 패턴 프로덕션 편입 · 검증 정합 수정

세션 범위: 패턴 자동생성(합성) 대폭 강화, 커스텀 패턴을 프로덕션 생성에 실제 편입,
검증 false-pass 수정, 보스 템플릿 기믹/스토리 보강, 타일수 튜너 신설.
**게임코드(sp_meowsgarden) 무변경.**

---

## 1. 보스 템플릿 패널 (BossTemplatePanel.tsx)

- **팔레트 기믹 추가**: `unknown(📦 상자)`, `teleport(🌀 텔레포터)` — 오른쪽 그리기 팔레트에
  누락돼 선택 불가였음. `GIMMICK_PALETTE` + `PALETTE_UNLOCK_KEY` 2줄씩 추가.
  - teleport = 에디터 내부 `teleport`, 배포 시 `teleporter`로 export 정규화(기존 경로) → 백엔드 무변경.
- **보스 스토리 컨셉노트 테마3~5 추가**: 기존 10~280(테마1·2)에 이어 **290~1500(122개)** 생성.
  - 출처: sp_meowsgarden `DESIGN_DECORATION_THEME_CATALOG.md`(스토리) + `DESIGN_DECORATION_STAR_DISTRIBUTION.md`(레벨매핑).
  - 챕터 star 분배(T3=425·T4=570·T5=250 레벨)로 보스 매핑. 챕터 피날레=편지(710·1280·1500).
  - `THEMES` 배열에 T3(290~710)·T4(720~1280)·T5(1290~1500) 추가.

## 2. 타일 종류 수 튜너 (신규 `/tune/tilecount`, tune.py)

- 필드 타일을 N색 팔레트로 **재타이핑**(종류 수 조절). 종류↑ = 어려움(트레이 다양↑).
- **컨테이너-aware ÷3**: craft/stack 배출 타입 강제 팔레트 포함 + 필드 완성분(r_t) 배정으로
  `(필드+컨테이너)≡0 mod3` 직접 보장. finalize(필드-only) 미사용(오히려 깨뜨림).
- 프론트: 색 분산 슬라이더 밑 "타일 종류" 입력+적용 (ProductionDashboard).
- 검증: Lv30 보스 7종 0.69 / 9종 0.52(목표 도달) / 11종 0.41 — 단조 감소.

## 3. 커스텀 패턴 프로덕션 편입 (ProductionDashboard.tsx)

- **문제**: `preComputePatternIndices` 일반풀 = 0~63만 → 커스텀(64+) 절대 미사용.
- **수정**: 생성 시작 시 `/debug/pattern-list`에서 활성 커스텀(is_custom+count>0+비활성아님)
  수집 → 일반레벨 풀에 concat → 저장한 커스텀 모양이 실제 등장(~28% 비율, 검증).

## 4. 검증 false-pass 수정 (ProductionDashboard.tsx)

- **원인**: 리스트 개별검증(`handleValidateSingleLevel`)이 autoplay 봇 `matchScore≥70`으로
  `verification_passed` 덮어씀 → bossTargetScale 미적용 + clear_rate_gap 방치 →
  이미 RL 측정된 too-easy 보스(gap>0.12)가 봇 점수로 통과되는 desync.
- **수정**: canonical RL 게이트(`simulateLevelSkillSweep`+bossTargetScale+rlVerificationPassed)로
  통일. clear_rate_gap 등 메타 일괄 기록(부분갱신 desync 제거).
- **freshest json**: 다이얼(기믹/색) 조정 후 리스트 검증 시 프리뷰(selectedLevel) json 측정.
- **봇3게이지**: RL 통일로 끊긴 `bot_clear_rates` → autoplay 병행 실행해 표시 복원.

## 5. 패턴 합성기 강화 (pattern_synth.py, analyze.py, PatternSynthModal.tsx)

- **품질(사람템플릿 활용)**: `template_ratio` 0.30→0.45. recombine 연산 확대
  (union만→union/intersect/diff). 누락 씨앗 54·56·60 추가(전 idx<64 커버).
- **랜덤성 슬라이더**(`diversity`): pretty·min_quality·template/cellular_ratio 매핑
  (0=정돈~1=최대랜덤). synthesize + auto-generate 양쪽.
- **씨앗 기반 생성**(A): `seed_positions`/`seed_grid` — 그린 모양 기반 회전·변주·재조합.
  - `_build_seed_variants`: 다운스케일 조각남 → 팽창(dilate) 재연결로 전 크기 견고 생성.
  - `seed_strength`: 변형 강도(0=씨앗충실~1=크게변형, 서브모드 분포 조절).
  - 개수 부족 수정: 큐레이션 Jaccard 유사도 컷 씨앗모드 완화(0.82→0.95).
- **프론트**: 씨앗 그리기 그리드 + 🎲 랜덤(대칭 랜덤 모양) + 변형강도/랜덤성 슬라이더 +
  드래그 페인트 버그 수정(onMouseUp/e.buttons). 프리뷰 2종(전체쌓임 vs 프로덕션 6·7홀짝).

## 6. 패턴 디버거 (PatternDebugPanel.tsx, analyze.py)

- **신규 패턴 = 크기별 따로 그리기** + 이름 입력 (`/debug/pattern-create-multi`).
  기존 저장 무반응 버그(positions 쿼리 해석) 대체. **5·6·7 필수 입력** 강제(프로덕션 레이어 col).
- **인덱스 주 식별자화**: 카드 `#번호` 굵게, 커스텀 목록 항상 번호순 정렬, 상단 "번호로 찾기".
- **고아 방지**: `/debug/pattern-usage/{idx}` — 삭제 전 그 패턴 쓰는 프로덕션 레벨 경고
  (재번호 안 함 = 인덱스 고정 = 참조 안전).
- **프로덕션 배지**: 커스텀(64+) 생성 레벨에 "🎨 커스텀 #N" 표시.
- **커스텀 fallthrough 결정성 fix** (generator.py): 커스텀 인덱스가 요청 크기 변형 없어
  fall-through 시 랜덤 auto-select → 프리뷰 깜빡임/생성 비결정. `pattern_index % 64`
  결정적 매핑으로 수정.

---

## 다음 작업 (착수 예정): 유닛 조립 레이어 생성 (A안)

- **목적**: 위층 STEP 축소본이 sparse → 타일수 미달 문제 해결.
- **방식**: 바닥 큰층=주 패턴 / 위 작은층=밀도 높은 소형 유닛(3·6·9칸) 조립.
- **검증된 설계**(외부 AI 자문 2회 + 우리 규칙 교차검증):
  1. support 매핑 = 우리 covering 역함수 일치, **인접 층 받침만으로 floating/데드락 0%**.
  2. **경량 Bottom-Up (Support-Mask)** — 전면 탑다운 재작성 불필요.
  3. 유닛 타일수 3배수 + 층 예산 3배수 반올림 → ÷3 자연 확보.
  4. 타입할당·클리어보장 = **기존 reverse_generation 재사용**.
  5. 경계 = clamp 후 벗어나면 reject. 앵커 스냅(중심/대칭축)으로 시각 안정.
- **구현 순서**: 유닛 라이브러리 → 예산분배 → mask배치 → 앵커 → 패딩 → reverse연결 → 프로덕션 플래그.
