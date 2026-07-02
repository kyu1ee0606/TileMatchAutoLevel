# CHANGELOG 2026-07-01 — 경계 밖(OOB) 타일 제거로 클리어 불가 회귀 수정

## 증상
신규 프로덕션 생성 레벨 일부가 디바이스에서 **클리어 불가**. 정적 데드락 검사에서
`레이어 OOB 타일: L0 (선언 6x6) @ 6_0 = t4 → 디바이스에서 그 타일이 렌더되지 않아
클리어 불가능`. 타입별 3배수는 통과했지만, 선언 col/row 밖(x==col, x==-1, y==row 등)
타일이 존재.

## 원인
게임은 `LayerSpawn(rowCount)`(=선언 col/row)로 그리드를 만들고 **범위 밖 타일을 컬링**한다.
따라서 데이터에 `x<0 / x>=col / y<0 / y>=row` 타일이 있으면 그 타일은 렌더/픽 불가 →
해당 타입 매칭 3배수가 실질적으로 깨져 클리어 불가.

생성기의 후속 변형 단계가 타일을 경계 밖으로 밀 수 있음(코드 주석도 인정: "pyramid
enforcement / visual centering / boundary trim afterwards can violate the invariant"):
- `_fix_visual_centering`: 레이어 위치 일괄 시프트 시 한쪽 경계 클램프(`elif`)가 반대쪽
  초과를 놓칠 수 있음.
- 일부 aesthetic 패턴 생성기: centering `offset_x/y`를 `range(cols)` 전체에 더해 x==cols 방출,
  대칭 미러(`cols-1-x`)가 이를 -1로 반사.
기존 FINAL_REPAIR는 **÷3만** 보정(relabel)하고 경계는 검사하지 않아 OOB가 출고됨.
튜토리얼~일반 전 구간 영향(층별 크기 다양화 B와 무관 — B 미적용 저레벨에서도 발생).

## 수정
`generator.generate()` 반환 직전(피라미드+centering 이후, ÷3 finalize 직전) 단일 초크포인트에
`_remove_out_of_bounds_tiles(level)` 추가. 각 레이어 선언 col/row 밖 타일을 무조건 제거.
제거로 깨진 ÷3은 바로 뒤 `_finalize_divisibility_guarantee`(총합 ÷3) + FINAL_REPAIR(per-type
relabel)가 재보장. 위치만 제거하므로 새 데드락을 만들지 않음.

- `backend/app/core/generator.py`:
  - `_remove_out_of_bounds_tiles()` 헬퍼 추가
  - `generate()`에서 `_fix_visual_centering` 직후 호출

## 검증
- py_compile OK.
- OOB: 수정 전(구코드) API 21~24/각 배치 발생 → 수정 후 **인프로세스 30 gens + API 164 gens
  (일반/both/horizontal/aesthetic/size_diversity=101 조합) 전부 0 OOB**.
- 정규타일(t1..tN) ÷3: 164 gens 위반 0.
- 솔버빌리티 A*: PROVEN_SOLVABLE 14 / UNCERTAIN 2(예산), IMPOSSIBLE 0, divisibility_violation 0.

---

# 추가: 고아 link 기믹 제거 (인게임 스폰 NRE 차단)

## 증상
생성 레벨 일부(예 level 68)에서 **존재하지 않는 위치로 link 기믹이 연결** → 인게임 타일 스폰 실패 +
`NullReferenceException: TileEffect.FindLinkTile() → ActiveEffect() → TileGroup.StartSpawnRoutine()`.
예: `layer_0 "1_0":["t9","link_n"]`(북=row-1=`1_-1` OOB), `layer_2 "2_4":["t14","link_e"]`(동=`3_4` 없음).

## 원인
게임 `FindLinkTile`(TileEffect.cs:1087)은 방향별 `GetTile(layer, x±1 / y±1)[0]`로 대상 접근
(E=x+1,W=x-1,S=y+1,N=y-1; 키 "x_y"; **홀짝 보정 없음** — 에디터 규칙과 일치). 대상이 OOB(y<0 등)면
`GetTile`이 null → `null[0]` → NRE → 스폰 크래시.
에디터는 link 배치 시 대상 존재를 검증하나(generator.py:7966), **이후 변형 단계
(_fix_visual_centering 위치 시프트 / ÷3 삭제 / 피라미드 / OOB 제거)가 링크의 대상 타일을 옮기거나
지워** 고아 링크가 남는다. 마지막 obstacle 재검증(≈L1008)은 이 단계들보다 앞서 실행돼 놓친다.
- 실측: link 포함 레벨 in-process 48 gens 중 2건 고아 링크(예 Lv68 `2_2`link_s→`2_3`없음).
- **게임 link 오프셋 수정(46998fbb, 2026-07-01)은 무관** — E/W 회전→위치오프셋(비주얼 전용),
  `FindLinkTile` 로직 불변. 즉 게임 변경이 아니라 에디터의 고아 링크가 원인.

## 수정
`generate()` 반환 직전(모든 변형 이후) `_strip_orphaned_link_tiles()` 추가. 각 link_* 소스의 대상
셀을 게임과 동일 오프셋으로 재계산해 대상 타일이 없으면 **속성만 제거(plain화)**. 타일 자체는 보존
→ ÷3/타입 무영향. link 개수 소폭 감소 가능하나 크래시보다 안전.
- `backend/app/core/generator.py`: `_strip_orphaned_link_tiles()` + `generate()` 말미 호출.

## 검증
- in-process link 레벨 48 gens: 고아 링크 2→**0**.
- API 44 gens(link/chain/ice + size_diversity 포함): OOB 0 / 고아링크 0 / 정규타일 ÷3 위반 0.

---

## 디버깅 노트 (재발 방지)
- `/api/generate`는 ProcessPoolExecutor 워커에서 실행. 코드 수정 후 `pkill -f "uvicorn app.main:app"`만으로는
  `multiprocessing.spawn`으로 뜬 **워커 자식이 살아남아 구코드를 계속 서빙**(cmdline이 uvicorn 패턴과
  불일치). 반드시 `lsof -ti:8000 | xargs kill -9`로 포트 점유 프로세스까지 정리 후 재기동할 것.
  워커 로깅은 uvicorn stdout 로그로 흐르지 않으므로, 로직 검증은 **인프로세스 import 호출**로 할 것.
