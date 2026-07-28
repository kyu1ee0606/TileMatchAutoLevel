# 타입별 ÷3 보장 개선 계획 (데드락 근절)

작성 2026-07. 상태: **❌ 반증됨(폐기) — 구현 시도 후 롤백**.

## ⚠️ 반증 요약 (2026-07-28 실측)
이 계획의 전제("타입별 ÷3 위반 = 언클리어러블")는 **틀림**. RL 시뮬 실측:
- **Lv.15 (t2=10, ÷3 위반) → pred 1.0 클리어 가능**
- **Lv.22 (t3=13, ÷3 위반) → pred 1.0 클리어 가능**
- Lv.12/25/31 (÷3 정상) → pred 0 언클리어러블

∴ **정적 타입별 ÷3은 클리어 가능성 기준이 아님.** RL 시뮬/게임이 t0 분배·색균형·visualTileSeed로
런타임 색 재배치를 하므로, 저장된 concrete 타입 개수의 ÷3 여부는 무의미(헛다리).
- 앞선 "실패 75%=÷3 위반"은 **상관일 뿐 인과 아님** (소형 레벨서 구조적 데드락과 ÷3위반이 동시발생).
- 구현한 `_ensure_type_divisibility`(무딘 재라벨)는 클리어 가능 레벨의 색 배치를 깨 **블로킹 데드락 유발**
  (pred 0.9 → 0) → **전량 롤백**.

**진짜 언클리어러블 원인 = 구조적 데드락(블로킹: 타일이 다른 타일에 묻혀 접근불가, dock 용량 등).**
RL 검증 + 재생성 루프(페이즈 분리 루틴)가 이미 처리. 실패율 낮추려면 **소형 레벨 생성의 블로킹-인지
개선**(deadlock 체크 강화)이 방향이지 ÷3 아님. 아래 원안은 기록용으로만 보존.

---

작성 2026-07. 상태(원안): 계획(착수 전).

## 1. 문제 (실측 확정)
- 최근 1500 배치 검증 실패의 **75%가 unclearable**, 그중 **33/33이 타입별 ÷3 위반**.
- 예: Lv.12 `t3=14, t11=5, t4=5` — 총량은 45(÷3 OK)인데 **타입별로 3배수 아님** → 끝에 잔여 타일 → 클리어 불가(pred=0).
- 초반·소형 레벨 집중(타입당 타일 적어 재분배 여유 없음).

## 2. 왜 게임이 안 고쳐주나 (정본 확인)
`DESIGN_TILE_COLOR_BALANCE.md` / 게임 `ShuffleEmptyTiles`:
- ÷3 보장(색세트 3개 단위 분배 `DistributeTiles`)은 **`t0` 타일에만** 작동. `emptyCount==0`(t0 없음)이면 early return.
- 실패 레벨은 **t0=0, 전부 concrete(t1~15)** → 게임이 재분배 안 함 → 저장된 non-÷3 그대로 → **실기 데드락**.
- 색 분배 스크롤(`/tune/arrangement`)은 **다중집합 순열**(개수 보존, 위치만 섞음) → non-÷3 못 고침.

∴ **concrete 타입은 에디터가 ÷3 보장해야 함** (t0는 게임이 보장).

## 3. 원리 (해결 가능성)
- 총 타일수는 이미 ÷3 (생성기 보장).
- concrete_total = total − t0_count. total ÷3, 대부분 t0=0 → concrete_total ÷3.
- **concrete_total이 ÷3이면 타입별 ÷3은 항상 달성 가능** (3k를 3배수 뭉치들로 분할). 재라벨(td[0] 색만 변경, 개수·위치·속성 불변)로 달성.
- 규칙: **모든 concrete t1~15 타입 개수를 3의 배수로.** (t0 기여분은 항상 ÷3이라 합도 ÷3 → 최종 ÷3.)

## 4. 케이스별 처리
| 구성 | 처리 |
|------|------|
| t0만 | 손 안 댐(게임 DistributeTiles가 ÷3 보장) |
| concrete만 | concrete 타입별 ÷3 재라벨 (아래 알고리즘) |
| t0 + concrete 혼합 | concrete 부분만 타입별 ÷3 재라벨 (t0는 게임이) |

## 5. 알고리즘 — `_ensure_type_divisibility(level)` (결정적, 개수보존)
대상: td[0]가 t1~t15인 필드 타일. **제외**: craft_/stack_ 컨테이너, t16(key), t0, (골 필수 타입은 보존).

```
1. concrete 타일을 타입별 그룹핑(위치 목록). counts[type], positions[type].
2. concrete_total = Σcounts. 
   if concrete_total % 3 != 0:   # 혼합 엣지 (t0가 비-÷3)
       r = concrete_total % 3
       r개 concrete 타일을 t0로 전환(또는 t0 r개를 concrete로) → concrete_total ÷3 정렬.
3. floating = []   # 재배정할 타일 위치
   for type, cnt in counts:
       rem = cnt % 3
       floating += (해당 타입 위치 중 rem개)   # 이만큼 떼어냄 → 남은건 ÷3
   # |floating| = Σrem ≡ concrete_total ≡ 0 (mod 3) → 3m개
4. floating(3m개)을 3개씩 m묶음으로 타입에 재배정:
   - use_tile_count(고유 타입수) 유지 우선: 개수 0 될 위기의 타입(cnt<3, 전부 floating)엔
     묶음 하나 되돌려 3으로(타입 유지). 나머지 묶음은 잔량 많은/균형 위해 라운드로빈.
   - 목표 타입 사용 그래프(색상 균등) 유지하려면 기존 타입에만 배정.
5. floating 위치의 td[0]를 배정 타입으로 재라벨. td[1](속성)·위치 불변.
6. (선택) 재라벨로 같은색 블로킹 데드락 생길 수 있으니 후단 _ensure_no_deadlock가 처리.
```
불변식: 총 타일수 불변, 각 concrete 타입 개수 ÷3, 속성/좌표/기믹 불변.

## 6. 통합 지점 (모든 경로 필수 통과 + 하드 게이트)
- **generate() 최종 백스톱**: 모든 mutating(트림/피라미드/링크·튜토리얼 ensure/inner diversify) **이후**,
  링크 정화 백스톱(1492) 근처에 `level = self._ensure_type_divisibility(level)` 추가.
  - 이유: 기존 `_finalize_divisibility_guarantee`(1351)는 후속 단계가 ÷3 재파괴 가능 + 알고리즘 엣지 실패.
    맨 끝 백스톱이면 어떤 경로·단계 후에도 최종 출력이 ÷3.
- **하드 게이트**: 백스톱 직후 재검사. concrete 타입에 % 3 != 0 남으면 →
  (a) 로그 ERROR + (b) validated 경로면 재시도 트리거(비-÷3 절대 저장 금지).
- **모든 경로 커버**: 일반 생성·validated·역생성·unit_assembly·보스·**순차검증 재생성**(handleRegenerateLevel→/generate)
  전부 `generator.generate()` 단일 초크포인트 통과 → 자동 적용.
- **tune 무해 확인**: /tune/auto·/tune/gimmick은 색 순열(개수보존)·속성만 변경 → 타입 개수 불변 → ÷3 유지.

## 7. 기존 코드 정리
- `_ensure_tile_divisibility`(1897)·`_finalize_divisibility_guarantee`(1351)·FINAL_REPAIR: 새 백스톱으로 대체 또는
  새 함수가 상위 호출. 중복 로직 제거(재분배 실패 로그 `REDISTRIBUTE Final validation failed`의 근원).
- `_validate_playability`의 ÷3 bad_types 검사는 게이트로 재활용.

## 8. 엣지/리스크
- **use_tile_count 유지 불가한 초소형**(total=3, 2타입 요청 → 1타입×3만 가능): 타입수 강제 축소 + 로그.
- **골 타입(craft/stack 내부)**: 재라벨 제외(골 요구 색 보존). 그 타입이 non-÷3면 골 설계 문제 → 별도.
- **재라벨 → 블로킹 데드락**: ÷3은 필요조건이지 충분조건 아님. 후단 `_ensure_no_deadlock`/솔버가 담당(순서: ÷3 백스톱 → deadlock 체크).
- **혼합 concrete_total 비-÷3**: 2단계 t0↔concrete 전환으로 정렬(드묾).

## 9. 검증
- 생성 N개(밴드별, 특히 Lv.1~100 소형) → **concrete 타입별 ÷3 위반 0** 단정.
- 실패분석 재실행(§1 스크립트) → unclearable-÷3 = 0 확인.
- e2e: 순차검증 재생성 경로도 통과(백스톱 태움) 확인.
- 게이트: 인위적 non-÷3 주입 → 저장 거부/재시도 확인.

## 10. 착수 순서
1. `_ensure_type_divisibility` 신규 구현(§5) + 단위 검증(임의 counts → 전부 ÷3).
2. generate() 백스톱 + 하드 게이트 배선(§6).
3. 구 중복 ÷3 로직 정리(§7).
4. 배치 생성 → 실패분석 재실행으로 ÷3 실패 0 실측(§9).
