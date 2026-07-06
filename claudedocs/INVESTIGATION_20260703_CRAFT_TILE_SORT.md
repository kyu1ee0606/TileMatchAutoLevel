# 조사 20260703 — craft(생성기) 타일 렌더링 sort 이상 (게임측 원인, 에디터 무관)

**결론**: 인게임 craft 렌더 sort 특수 오프셋이 원인. **맵 에디터 생성 데이터는 정상**.
수정 대상 = 게임(sp_meowsgarden), 에디터 아님. → 인게임 수정 세션에 이관.

## 증상 (사용자 보고)
GameBoost 배포 24번 레벨, 최상단 그리드에서:
1. 생성기(craft)가 배출한 타일이 그 아래 행 일반 타일보다 뒤에 렌더링.
2. 생성기 바로 아래 행 타일이 생성기 본체 + 하위 타일보다 앞에 렌더링.

## 재현 데이터
- craft_w @ layer_2 "1_2"(col1,row2), 서쪽 배출 → "0_2".
- 배출칸 "0_2"는 전 레이어 비어있음 → 배치 정상(충돌 없음).

## 게임 sort 메커니즘 (코드 확인)
- 기본: `TileGroup.SetOrder()` (`TileGroup.cs:1214`) 레이어→행(row0..N)→열 순회 count+=5.
  일반 타일은 **row 단조증가**(아래=높은sort=앞). 규칙 자체 정상.
- craft 특수: `TileCraft.SetOrder()` (`TileCraft.cs:533~553`)
  - 박스 = init(자기 count)
  - covered(내부) = init-10  ← craftTileList 전부
  - emitted(배출) = init-1

## 24레벨 layer_2 실계산 (관측과 일치)
```
row2: 1_2(craft박스)=10, 3_2=15, 4_2=20
row3: 1_3=25, 2_3=30, 3_3=35, 4_3=40
→ craft 박스=10, 배출=9, 내부=0
→ 아래행(row3, 25+)이 craft 관련 타일(0/9/10) 전부보다 앞 = 증상 그대로
```
일반 타일끼리는 완벽히 row 단조(역전 0). **craft 관련 타일만** row-major 규칙에서 벗어나 낮게 깔림.

## 에디터 대조 결론
- 좌표계/row 규칙/타일키 게임과 일치(선행 Explore 조사).
- craft 방향/위치/배출칸 정상 → **에디터 데이터 문제 아님**.
- 에디터 프리뷰(BotTileGrid/TileGrid)는 craft 특수 sort 미재현 → 프리뷰와 인게임이 craft 주변에서 다르게 보일 수 있음(프리뷰 충실도 한계, 데이터 버그 아님).

## 조치
- **인게임 수정 세션에 이관** — 프롬프트 작성 완료(craft SetOrder 의도/버그 판정 + 배출타일 sort 일관화 요청).
- 에디터측 가능 완화책(선택, 미적용): craft 배출 방향에 아래 행 타일이 겹치지 않도록 배치 유도. 단 covered=init-10은 방향 무관 상시라 **완전 해결 안 됨** → 근본은 게임측.

## 관련
- 게임 파일: `TileCraft.cs`(SetOrder 533~553), `TileGroup.cs`(SetOrder 1214, AfterAllTileSpawn 817), `Tile.cs`(SetOrder 1338~1363)
- 게임 스키마 정본: `sp_meowsgarden/.../DESIGN_LEVEL_MAP_SCHEMA.md` (좌표/정렬 §2·§9)
