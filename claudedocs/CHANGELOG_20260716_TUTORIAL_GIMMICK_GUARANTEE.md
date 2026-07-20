# 튜토리얼 기믹 보장 — 언락 첫 스테이지 100% 포함

> 2026-07-16 · 각 기믹이 언락되는 첫 스테이지(튜토리얼)에 해당 기믹이 반드시 존재하도록 보장.

## 배경 / 문제
사용자 제보: "key(111)/teleport(441) 등 언락 첫 스테이지에 기믹이 프로덕션 레벨에 빠지는 경우 발생."
전수조사(프로덕션 배치 187개 + 신규생성 실측):
- 전 기믹의 언락 첫 스테이지에서 **18~37%가 해당 기믹 누락** (teleport L441 61/165 등).
- 신규 생성도 특정 조합에서 craft/stack 컨테이너 0개, chain/grass/bomb 누락 산발.

### 언락 첫 스테이지 정본 (canonical, `DEFAULT_GIMMICK_UNLOCK_LEVELS` 동기화)
craft=11, stack=21, ice=31, link=51, chain=81, key=111, grass=151, unknown=191,
curtain=241, bomb=291, frog=391, teleport=441.

## 원인 (3가지)
1. **후속 파괴 (Category B)**: 튜토리얼 기믹 보장(`_ensure_tutorial_gimmick_count`)이 generate() **중간**(line~1095)에 실행 → 이후 데드락 리셔플/÷3 재분배/경계·피라미드 트림/`_strip_confusing_grass`(맨끝)가 기믹을 지워도 재보장 없음.
2. **검출 누락 (Category A)**: 재생성 등 일부 경로가 `params.tutorial_gimmick`을 비워 검출 실패 → 강제 미적용.
3. **역생성 rescue strip (프로덕션 핵심)**: `/api/generate`는 프로세스풀 워커 `_generate_core_worker`에서 실행. forward 레벨이 데드락 경고면 **역생성 rescue**가 witness 폴백에서 **컨테이너/속성을 strip** → 튜토리얼 기믹 소실. (in-process 직접호출은 이 경로를 안 타서 문제 안 보임 → 진단 지연.)

## 수정 (모두 ÷3·클리어가능성 보존)
| # | 내용 | 파일 |
|---|---|---|
| 1 | `TUTORIAL_UNLOCK_LEVELS` 클래스 상수(정본맵) 추가 | `core/generator.py` |
| 2 | generate() **종료 직전**(strip 이후) 속성·unknown 기믹 재보장. `params.tutorial_gimmick` 없으면 `level_number`로 fallback (Cat.A·B 차단). attribute는 td[1]만 추가 → 타입카운트 불변=÷3 보존 | `core/generator.py` |
| 3 | craft/stack 컨테이너 goal 보장 `_ensure_container_goal_tutorial` — ÷3 finalize **직전** 최소 1개 배치(비커버 일반타일→`{base}_s`), finalize가 ÷3 마무리 | `core/generator.py` |
| 4 | grass 재보장 시 `_grass_position_valid`(홀짝착각방지) 위치에만 배치 → `_strip_confusing_grass`에 다시 안 지워짐 | `core/generator.py` |
| 5 | **역생성 rescue 직후 튜토리얼 재보장 + `_finalize_divisibility_guarantee` 재실행** (프로덕션 풀 경로 핵심 fix) | `api/routes/generate.py` `_generate_core_worker` |

## 검증 (API 실측)
- 12개 기믹 × 15회 × 5난이도(0.1~0.6) = **180회 전부 present, 누락 0/180**.
- craft/stack 컨테이너 최소 1개 보장, teleport L441 포함 전 기믹 통과.
- in-process(직접 generate) + API(풀 워커) 양쪽 0 누락.
- 기존 프로덕션 배치의 누락 레벨은 **재생성 시 자동 교정**(정본맵 fallback).

## 참고
- 게임코드(sp_meowsgarden) 무변경 — 에디터 생성기만 수정.
- key(111)는 `unlockTile`×3 + t0분배 경로로 별도 보장(기존 `_validate_and_fix_key_tile_count`). 본 수정과 독립.
