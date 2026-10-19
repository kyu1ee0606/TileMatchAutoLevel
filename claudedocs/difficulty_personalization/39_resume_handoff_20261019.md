# 39. 재부팅 인계 — 전체 진행 상황 (2026-10-19, 문서 32 후속)

> 작성 2026-10-19 · 메인 트리 브랜치 `feature/pv-seed-variants` · 사용자가 스왑 여유 부족으로 맥 재부팅 → 재부팅 후 새 세션이 이어받기 위한 기록. **코드·데이터 변경 없음(문서만), 서버·테스트·봇·브라우저 실행 0회.**
> 수치는 각 근거 문서의 당시 기록값을 인용한 것이며 이 문서 작성 중 재측정하지 않았다. 브랜치·커밋은 2026-10-19 `git branch -vv`·`git log` 로 확인한 값.

## A. 최상위 목표와 채택 기준 (문서 32 §A 그대로 유지)

- 목표: 맵에디터에서 **목표 실유저 클리어율 곡선**을 지정하면, 생성 → 선별 → 검증한 맵의 라이브 클리어율이 목표 범위에 가까워지게 한다. 봇이 사람처럼 플레이하는지는 목표가 아니다(문서 31 §0).
- 채택 기준: 같은 조건으로 보정 모델을 재학습했을 때 **학습에 쓰지 않은 맵에서 실유저 클리어율 예측 오차가 줄어드는가**(문서 26 §11-0). 원시 봇 지표·행동 유사성은 진단용. 라이브 실측 전에는 "목표 달성/보장" 표현 금지.

## B. 단계별 진행표

| 단계 | 상태 | 요점 | 근거 |
|---|---|---|---|
| 봇 v2.4 | **머지 완료**(규칙 정합 항목만) | `26dd967` merge: feature/bot-v24 → feature/pv-seed-variants. 행동 개선 후보는 기본 제외. 1차 목표 예측 정확도가 v2.3보다 유의하게 좋아졌다고 결론 내리지 않음 | 문서 26 §11 |
| 예측 기준선 | 확정 | 379레벨에서 새 예측 MAE 3.2%p·ρ 0.76 vs 기존 에디터 `predicted_clear_rate` 36.9%p·ρ 0.21 | 문서 31 §1-5 |
| 저구간 후보 | **미채택** | 저구간 점예측 후보·C1~C3·범위 후보 R1·R2 — 다른 구간 성능 또는 사전 기준 미충족 | 문서 33 §12, 문서 36(`_wt_lowband`) |
| 범위 상한 고정 | 원인 기록 | 범위(80%) 상한이 묶이는 현상 = 학습 데이터 정체(저구간 표본 부족) | 문서 36(`_wt_lowband`) |
| 생성 파일럿 | 부분 성과 | A90 합격(독립 확인 후 예상 93.1% — 모델 예측값, 라이브 실측 아님) · A95 합격 · B15·B50 봇 기준 충족 · **A85: 현 활성 모델·신뢰 기준으로 합격 영역 없음**(생성 횟수 증가로 해결 안 함) | 문서 33 §14·§15 |
| 검증 탭(2차) | **경량 검증 부분 완료 — 전체 목표 완료 아님** | 실제 UI PASS 4항목(목표 곡선 저장·복원, 배치 전환, 최초 배치 선택, 미리보기 문구 — Codex 브라우저·8001/5174 격리·fixture) · 순수 함수 PASS 14+14 · F1(버전 조회 실패 표시)·G1(같은 배치 맵 변경)·비동기 경합 실UI는 **준비만** · 실제 C 기록·서버 복구 **미검증** | 문서 38·38b(`_wt_clearrate`) |
| DDA 시드 세트 | 보류 | v1·v2 결과 엇갈림 | 문서 10 §9-8~§9-12 |
| 라이브 파일럿 | 준비 완료, **게임팀 대기** | pilot_B_v3.1 21레벨 | 문서 29 |

## C. 브랜치·커밋·파일 상태 (2026-10-19 확인)

### C-1. 원격에 push 된 브랜치 (로컬 = 원격 여부)
| 브랜치 | 로컬 | 원격 | 비고 |
|---|---|---|---|
| `feature/pv-seed-variants`(메인 트리) | `329a1a0` | `329a1a0` | 동일. 이 문서 커밋은 로컬에만 추가됨(아래 §C-4) |
| `feature/clear-rate-display`(`_wt_clearrate`) | `3b50d17` | `581d4f6` | **로컬이 11커밋 앞섬**(C-2) |
| `feature/clear-rate-lowband`(`_wt_lowband`) | `db9a206` | `db9a206` | 동일 |
(그 밖에 `main` 은 원격보다 5커밋 앞섬 — 이번 작업과 무관, 손대지 않음.)

### C-2. 로컬에만 있는 커밋 — `feature/clear-rate-display` (`git log origin/feature/clear-rate-display..feature/clear-rate-display`, 오래된 순)
`4ef96cc` C 확인 작업 백엔드 · `0381bbd` 레벨별 A 목표 곡선 · `24ec6d2` 검증 탭 UI·저장·복원 · `4e8c2b7` 문서 38 §10-16 · `66fc314` 38b 경량 검증 로그 · `4727af4` 38b 정적 감사 · `413154e` 배치 전환 경계·버전 미확인 배지·맵 다시 읽기 수정 · `be57225` 38b fixture 보정 · `91ca0a9` 38b 단위 테스트 기록 · `6ff7695` 38b 서버 fixture 인계 · `3b50d17` 최초 배치 선택·미리보기 문구 수정. (push·병합 안 함 — 사용자 결정 대기)

### C-3. 미커밋 파일 — **보존 필요(삭제·되돌리기·임의 커밋 금지)**
- `_wt_clearrate/claudedocs/difficulty_personalization/38_validation_tab_integration.md` — 상단 '최신 인계'(사용자 작성, 미커밋).
- `_wt_clearrate/claudedocs/difficulty_personalization/38b_light_ui_verification_log.md` — Codex 실제 UI 기록(미커밋) + 하위 세션 추가분(최종 상태표, 10-18 "남은 미검증 재개 준비" 절차서).
- 메인 트리: `backend/data/backups/`(미추적, 이번 작업과 무관 — 손대지 않음).

### C-4. 이번 문서 커밋
메인 트리에서 이 문서(39)와 `README.md` 만 지정해 로컬 커밋(push 안 함).

### C-5. fixture·런타임 파일 (미추적, git-ignored)
- `_wt_clearrate/backend/data/production/`: `codex_ui_fixture_20261016_a.json`(L237 골든×3), `codex_ui_fixture_20261016_empty.json`(빈 배치), `codex_ui_fixture_20261018_g1.json`(L237 골든 layer 정수화 1레벨, G1용), `_index.json`(서버 캐시). 모두 실제 레벨 아님(`fixture_note` 명시). 메인 트리 `backend/data/production`(운영)과 별개.
- `_wt_clearrate/frontend/node_modules`: 설치됨(`npm ci`, git-ignored).

### C-6. 워크트리 (`git worktree list`) — **삭제는 사용자 확인 필요**
| 경로 | 브랜치/커밋 |
|---|---|
| `/Users/casualdev/TileMatchAutoLevel` | `feature/pv-seed-variants` 329a1a0 |
| `/Users/casualdev/TileMatchAutoLevel_wt_clearrate` | `feature/clear-rate-display` 3b50d17 |
| `/Users/casualdev/TileMatchAutoLevel_wt_lowband` | `feature/clear-rate-lowband` db9a206 |
| `/Users/casualdev/TileMatchAutoLevel_wt_botv24` | `feature/bot-v24` b757f70 (머지 완료분) |
| `/Users/casualdev/TileMatchAutoLevel_wt_botv21` | `feature/bot-rule-parity` cb55a60 |
| `/Users/casualdev/TileMatchAutoLevel_wt_sep` | detached 6e7b65e |

## D. 재부팅 후 재개 절차

1. **자원 측정**(문서 37 §3): ① 재부팅 직후·개발 도구(Unity·cc-web·에디터 백엔드·브라우저 탭 복원) 실행 **전**, 로그인 후 약 2분 안정 대기 뒤 1회 → ② Unity·cc-web 을 평소처럼 실행하고 약 10분 뒤 1회 + ②-스왑 10분 증가분. 결과는 문서 37 §4 표에 추가. 한 번의 값으로 부족/충분을 단정하지 않는다.
2. **서비스 기동**: 맵에디터 백엔드는 자동 시작 아님 → 필요 시 `bash scripts/dev-watch.sh`(메인 트리). cc-web 은 LaunchAgent 로 자동 시작.
3. **F1·G1·비동기 경합 실UI 확인**: `_wt_clearrate` 의 38b "남은 미검증 재개 준비 — F1·G1·비동기 경합" 절차서대로(Codex 브라우저 또는 사용자 직접).
   - 조건: **스왑 여유 ≥ 500MB 이고 메모리 압박 단계 < 3** 일 때만 기동.
   - 반드시 `:5174` **새 브라우저 프로필** + 워크트리 백엔드 `:8001`(fixture 저장소). 메인 `:8000`/`:5173` 사용 금지(대시보드가 마운트 시 로컬 배치를 연결된 서버로 자동 업로드).
   - 지연·실패 주입은 `/tmp` vite 설정 플러그인(절차서 전문) — 비-GET 은 허용 목록 외 403.
   - **[실행](C 측정)·[배치 검증]·[검증+재생성]·[재생성] 금지.** mock PASS 단계 결과는 "mock 검증"으로 구분 보고, 끝나면 테스트 프로필 폐기.
4. **하위 세션 재생성 시 지시에 넣을 규칙**:
   - 봇 측정 금지 범위 명시(1판도 금지 / 허용 시 판수·대상 명시), C 실행·작업 생성 API 금지, 생성 탐색·재학습·전체 테스트/빌드 금지(별도 승인).
   - 300초 무출력 금지, 중간 보고와 최종 보고 구분, 백그라운드 작업 완료 알림을 막연히 기다리지 말 것.
   - 워크트리 문서 38·38b 의 미커밋분 보존(전체 staging·되돌리기 금지, 파일 지정 add 만).
   - 정적 검토/순수 함수 PASS ≠ 실제 UI PASS, fixture/mock 결과와 실데이터 구분.

## E. 사용자 결정 대기 목록

1. 실행 검증 승인: 봇 미실행 pytest(`test_clear_rate*.py` 중 봇 실행 3개 제외 명령 — 38b), `npx tsc --noEmit`.
2. F1·G1·경합 실UI 진행 방식(Codex 브라우저 vs 사용자 직접, mock PASS 단계 포함 여부).
3. 브랜치 병합·push(`feature/clear-rate-display` 로컬 11커밋, 병합 시 `ProductionDashboard/index.tsx` 충돌 지점 5곳 확인 — 38b).
4. 라이브 파일럿 시점(문서 29, 게임팀 전달).
5. 85% 이하 구간 데이터 확보 — 추천 순서: 기존 AF 재집계·무한 모드 데이터 확인 → 라이브 파일럿 h2 → 101~300 신규 레벨 소규모 출시 → 선택형 도전 레벨.
6. Q2 대안 기준(G1~G6, 문서 36 §14 — 미적용 초안).
7. `/api/analyze/fix-centering` 이 문자열 `layer`(게임 빌드 형식)에서 500 이 날 가능성(정적 확인, 검증 탭 범위 밖, 운영 영향 미확인 — 38b §5).
8. 작업 폴더 정리(워크트리 6개·fixture·백업 디렉터리 — 삭제 전 확인).

## F. 자원 기록 (재부팅 전 참고값)

| 시각 | 여유율 | 압박 단계 | 스왑 사용/전체 (여유) | 비고 |
|---|---|---|---|---|
| 2026-10-16 17:31 | 35% | — | 52,176 / 53,248 MB | 문서 37 §4 |
| 2026-10-18 11:15 | 36% | 2(경고) | 54,744.25 / 55,296 MB (**551.75 MB**) | 38b 10-18 절, 디스크 여유 49Gi |

재부팅 후 측정 ①·② 와 비교해 개발 도구 실행분 증가량을 본다.

## 근거
[문서 32](32_resume_handoff_20261016.md) · [26](26_bot_v24.md)(봇 v2.4, 원본은 `_wt_botv24`) · [29](29_pilot_handoff.md) · [31](31_target_clear_rate_design.md) · [33](33_parallel_display_scope.md) · [37](37_resource_baseline.md) · 문서 10 §9-8~12 · 문서 36(`/Users/casualdev/TileMatchAutoLevel_wt_lowband/claudedocs/difficulty_personalization/36_lowband_candidates.md`) · 문서 38·38b(`/Users/casualdev/TileMatchAutoLevel_wt_clearrate/claudedocs/difficulty_personalization/`). 이 문서는 모델 교체·기준 변경·병합·push 승인이 아니다.
