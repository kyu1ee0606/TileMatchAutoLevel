# 그리드 헤더 OOB(경계초과) 버그 — 견고한 해결책

작성 2026-07-29. 상태: **계획(착수 전)**. 시니어 2명(backend-architect, system-architect) + root-cause 토론 종합.

## 1. 문제
레벨의 layer 헤더 `col`/`row`(격자크기)보다 타일 좌표가 밖에 있음. 게임은 헤더로 격자 생성(`LayerSpawn`) → 헤더 밖 타일 **스폰 안 됨(잘림)** → 인게임 클리어불가. RL sim/solver는 헤더 무시·타일 직접 읽음 → **검증 통과**하고 export됨.

현재 export 세트(batch_1785320918718, 1500레벨) **54개 깨짐**:
- **Class A (51)**: layer_0(베이스) 타일 extent가 헤더보다 **정확히 1 큼**(축은 row/col/양축 혼재: 26/19/6).
- **Class B (3: Lv247,281,362)**: 전 층 `col=0/row=0`(헤더 필드 자체 없음), 타일은 좌표 1~8. **레벨 통째 렌더불가**.

## 2. 근본원인 (확정)
### Class A — ÷3 애드백이 잘못된 경계 사용
`_finalize_divisibility_guarantee`(generator.py:1351)가 `_remove_out_of_bounds_tiles`(1324) **다음** 실행. concrete총합 not ÷3 AND `_preserve_pattern`이면 `_adjacent_empty_slots(need)`(13775)로 타일 1~2개 **추가**(모양보존 ÷3 보정). 근데 그 helper가 경계를 `level["gridWidth"/"gridHeight"]` = **기본값 7**(13704-13705)로 계산 — **이 필드는 generator가 한번도 안 씀(read-only)**. → 짝수 layer_0에 `nx<8, ny<8` 허용, 실제 헤더(6/7) 무시. 헤더 밖 1칸에 타일 추가, 이후 clip 없음 → extent = 헤더+1.
- **데이터 확증**: 51개 전부 `_preserve_pattern` O, `gridWidth` 필드 X, concrete총합 mod3==0(추가타일이 맞춤).
- layer_0 집중 이유: helper가 bottom-up 스캔(13708), 엣지타일 많은 layer_0 먼저 채우고 조기반환.

### Class B — import 템플릿 헤더 누락
3개는 import/수작업 템플릿(randSeed==level_number, pattern_index=-1). layer dict에 `col`/`row` 키 자체 없음 → `int(ld.get("col") or 0)`(254)가 0 coerce. generate() 버그 아님, **import 경계 문제**.

## 3. 핵심 불변식 (게임 스키마 §3/§90/§110 근거)
- 좌표키 `"{col}_{row}"`, `[0]`=col, `[1]`=row (§90 정본).
- 정상 레벨 = **교대 정사각**: col==row, 짝수층 = base+1, 홀수층 = base (에디터 producer 2512 convention; 데이터 확인 `(7,7)(6,6)(7,7)`).
- 블로킹(`_is_position_covered_by_upper` 7064-7118)은 `(upper_col - cur_col)`의 **부호만** 사용해 오프셋테이블 선택.
- **→ 헤더확장 안전조건**: 짝·홀 **동시 동량** 확장(패리티 락스텝)하면 모든 층쌍의 부호 불변 → 블로킹 바이트동일 → 클리어러빌리티 보존. (단일층만 확장 = 부호 뒤집힘 = 위험. 이건 금지.)
- row는 스태거 무관 → row 확장은 항상 안전.
- §110: 큰 격자+작은 중앙모양 합법(바깥칸 inert, 블로킹은 실좌표 사용).

**불변식**: 모든 층 L에 대해 `col_L > max(첫좌표)` AND `row_L > max(둘째좌표)`, `col_L,row_L≥1`, col은 패리티 교대 유지.

## 4. 해결책 (시니어 2명 최종 수렴 — 헤더확장 철회, 실헤더 바운드+relocate)

### (A) 근본 수정 — 애드백을 실헤더로 바운드 (6줄, 단일지점)
`_adjacent_empty_slots`(13704-13716)가 경계를 `gridWidth/gridHeight`(phantom, 항상 7) 대신 **각 층의 실제 `col`/`row` 헤더**로 계산:
```python
# BEFORE: gcols=int(level.get("gridWidth",7) or 7); lc = gcols if is_odd else gcols+1
# AFTER:
ld = level.get(f"layer_{li}", {}) or {}
try: lc = int(ld.get("col")); lr = int(ld.get("row"))
except (TypeError, ValueError): continue   # 헤더 불명 → 이 층은 슬롯소스서 제외
```
→ ÷3 타일이 헤더 안 빈칸에 배치 → OOB 원천차단. `_remove_out_of_bounds_tiles`(12598)가 이미 쓰는 정석 idiom 재사용. 헤더/좌표 안 건드림 → 홀짝 무관.
- **폴백 기존동작 유지**: 층 꽉차 슬롯 부족시 기존 `if len(slots)>=need` 가드(13776) → else 제거경로(13783). OOB 만드느니 제거가 안전(deadlock 불가, 13695 불변식). 추가작업 없음.
- **쌍둥이 버그**: 11100-11101에 동일 phantom-gridWidth read. 같은 PR서 함께 수정(export 경로 태우는지 확인).

### (B) 기존 51 Class A — relocate (헤더확장 아님)
초과타일 = **÷3 애드백 타일 그 자체**(plain concrete `[type,""]`, 링크/골/기믹 없음 = inert). → 근처 헤더내 빈칸으로 **이동**:
```
층별 초과타일(x>=col or y>=row): BFS 4-이웃으로 최근접 빈 in-header 칸(x'<col,y'<row) 찾아 이동.
없으면 최후수단 DROP → 수정된 (A) finalize로 ÷3 재보정. 이후 solver 재검증. 실패건만 재생성 강등.
```
- 헤더 불변 → 홀짝 스태거 불변. 타입/개수/난이도 불변(÷3 유지).
- 유일 리스크: 이동타일 1칸이 블로킹 커버 1개 바꿀 수 있음. **완화**: 원위치 최근접칸으로 이동 + **레벨별 solver 재검증 필수**(불변확인, 실패시 재생성). 인게임선 그 타일 어차피 잘려서 블로킹 0 기여였음 → 안쪽 이동은 sim이 이미 본 상태로 수렴.
- **헤더확장 철회 이유**: 정상세트가 교대정사각(even S / odd S-1) 확정 → layer_0만 8로 키우면 정사각교대·스태거 붕괴. "잘못 놓인 타일 정당화하려 격자 키우지 말고, 타일을 격자 안으로."

### (C) 검출 게이트 — fail-closed (검증+export)
reconcile **이후** 하드체크:
```
층별: col<=0 or row<=0 → FAIL(Class B). 타일별: x<0|y<0|x>=col|y>=row → FAIL(Class A/음수).
```
검증(`_validate_playability`/blocking 검증부) + export 경계 양쪽. reconcile 후에도 FAIL이면 진짜 버그 → 레벨 거부(재생성). RL-sim/solver 하버스에도 추가(54개 샌 이유 = sim이 헤더 무시).

## 5. 기존 54개 처리 (시니어 합의)
| Class | 수 | 결정 | 근거 |
|---|---|---|---|
| A | 51 | **relocate**(§4B) + 레벨별 solver 재검증 | 초과타일=inert ÷3타일. 안쪽 이동=최소변경, 헤더/타입/난이도 불변. 재생성은 검증난이도 재추첨 낭비. |
| B | 3 | **import 정규화 or 재생성** + 수동확인 | 0/0 붕괴. extent+정사각교대로 헤더 복원 가능하나 3개뿐 → 복원후 render+solver 눈검증, 애매하면 재생성. |

**step 0**: 배포된 실제 아티팩트 재스캔으로 roster 재확인(이미 batch_1785320918718 스캔 완료 = 54건 확정).

## 6. 미해결/검증필요
- `_fix_visual_centering`(12624) docstring이 `row_col`이라 표기(스키마 §90은 col_row). 축혼동 재발방지 위해 같은 PR서 주석/로직 정정. **단 Class A 원인은 아님(데이터 반증)** — 별개 정리건.
- 1308 주석("device reads level.row") stale → 정정.
- (A)에서 해당 층 헤더내 빈칸 없을 때 폴백 경로 확정 필요.

## 7. 범위/순서
1. (A) 애드백 바운드 수정 → 간단레벨 생성 검증(OOB 0).
2. (B) reconcile_headers + (C) 게이트 추가 → 백엔드+프론트, tsc.
3. 기존 51 배치수정 스크립트 + solver 재검증, 3개 재생성.
4. 서버 재시작(export 상태 확인 후).
- 파일: generator.py(13704 애드백, ~1498 reconcile, 검증부 게이트), tune.py, frontend util + gameEngine.ts, export 경계.
- **착수: 사용자 승인 + export 완료 확인 후.**
