# 인게임 이관 프롬프트 — craft(생성기) 뚜껑/배출타일 sort 불일치

**용도**: sp_meowsgarden 인게임 수정 세션에 그대로 붙여넣는 수정 요청 프롬프트.
**근거 조사**: `INVESTIGATION_20260703_CRAFT_TILE_SORT.md`

---

```
[인게임 수정 요청 — craft(생성기) 뚜껑/배출타일 sort가 그리드와 불일치해 부자연]

## 설계 의도 (원작자 확인)
craft 생성기는 뚜껑(top part)과 바닥(bottom part) 이미지가 분리됨.
- 바닥: 같은 자리에 겹쳐 쌓인 내부 타일들을 가려주는 역할.
- 뚜껑: 배출 애니메이션 시 회전하며 열림. 배출될 타일 1개가 바닥보다 sort 높게(앞), 뚜껑보다는 낮게(뒤) 표시되어 "뚜껑 열리며 타일이 나오는" 연출.
→ 이 내부 레이어링 자체는 의도대로 구현되어 있음. 문제는 생성기 파츠들의 sort가 주변 그리드 타일 sort와 안 맞는 것.

## 증상
생성기 뚜껑(및 배출 타일)이 인접한 아래 행 일반 타일에 덮여 부자연스럽게 보임. (재현: GameBoost 24레벨, craft_w @ layer_2 "1_2")

## 정밀 진단 (코드 확인 완료)
파일: Assets/08.Scripts/Tile_Script/InGame/TileCraft.cs
- SetOrder(int orderInLayerIndex) (533~553): m_InitOrderInLayerIndex=init(생성기 셀 그리드 sort), covered(내부)=init-10, emitted(배출)=init-1.
- SetCraftPartsOrder(bottomOrder=init-10, topOrder=init) (582~598):
  - 뚜껑(_craftTopPartRenderer)=init, colorLoop/mask=init, topEffect=init+1
  - 바닥(_craftBottomPartRenderer)=bottomOrder+7=init-3, pull FX=init-2

실제 레이어링(낮은 sort=뒤 → 높은=앞):
  init-10 내부타일 / init-3 바닥 / init-2 pullFX / init-1 배출타일 / init 뚜껑+box / init+1 topFX·remainText / init+2 box mask
내부 레이어링(covered < 바닥 < 배출 < 뚜껑) 정상.

근본 원인: 생성기 스프라이트(뚜껑 포함)는 셀 1칸보다 크고 회전 개방 시 이웃 셀까지 뻗지만, sort는 전부 "자기 셀(init)" 기준. 기본 그리드 sort는 TileGroup.SetOrder(1214)가 레이어→행(row0..N)→열 순회 count+=5로 부여하므로 셀마다 다름:
  - 생성기 바로 아래행(row+1) 일반 타일 = init+5 → 뚜껑(init)보다 앞 → 뚜껑이 아래행 타일에 덮임.
  - 배출타일(init-1)도 같은 이유로 아래행 타일 뒤로 밀림.

## 요청
생성기 뚜껑 및 배출 타일이 "시각적으로 겹치는 이웃 셀 타일들보다 앞"에 렌더링되도록 sort 재설계. 내부 레이어링(covered < 바닥 < 배출 < 뚜껑)은 유지.

검토 옵션:
- A) 뚜껑/배출 sort를 생성기가 걸치는 셀들의 최대 grid sort + α 로 산정 (TileGroup.GetTopSortOrderInLayer(2583) 활용 가능).
- B) 배출 타일은 착지 셀(배출 방향 칸)의 grid sort 기준으로 재부여.
- 어느 쪽이든 배출 완료 후 정상 (row,col) sort 복귀 여부도 검토(배출 끝난 타일이 계속 떠 있지 않도록).

## 제약/규칙
- 작업 전 INDEX.md → InGame/02_TILE_BOARD_SYSTEM.md 확인. 완료 후 CHANGELOG.md + TODO.md + 관련 노드 갱신.
- 로그 최소화(디버그 로그 잔여 금지).
- 다른 SetOrder 경로 회귀 점검: TileGroup.SetOrder(1214), Tile.SetOrder(1338), TileEffect.AdjustOrder(699~743), Frog(2108/2323 = max sort 오버레이, 의도됨), Dock.SetOrder. (teleport/shuffle는 제자리 타입교환이라 sort 정상 — 건드리지 말 것.)

## 참고 (에디터측 감사 결론)
맵 에디터 전면 감사 결과 실제 sort 버그는 craft 이 케이스 하나뿐. teleport/shuffle/frog는 오탐(제자리 교환 or 의도된 오버레이). 에디터 데이터/좌표는 게임과 완전 일치 — 데이터 문제 아님.
```
