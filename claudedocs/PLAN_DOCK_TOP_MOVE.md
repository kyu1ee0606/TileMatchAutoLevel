# 계획: Dock 화면 상단 이동 (하단 띠배너 대비)

> 상태: **계획만 — 미구현**. 큰 변경 + 시각적 테스트 필수.
> 착수 시점: **다른 서브 작업 완료 후**.
> 작성일: 2026-06-25

## 배경 / 목적

- 추후 **하단 광고 띠배너** 추가 예정 → 하단 배너 출력 테스트 권고받음.
- 현재 dock(7슬롯 매칭 버퍼)이 화면 **하단**에 위치 → 배너와 충돌 가능.
- 대응: dock을 화면 **상단**으로 이동, 하단을 배너 전용 공간으로 확보.
- addslot(=AddSlot 아이템 / `unlockTile` key 기믹)은 dock과 위치 연동 유지 필요.

## 사전 조사 결론 (근거)

### 데이터 영향: 없음
- dock 위치는 **레벨 데이터에 미저장**(좌표 없음). 순수 클라 UI 결정.
- `unlockTile` = 잠긴 슬롯 **개수값**(좌표 아님).
- → **1500레벨 재생성·재업로드 불필요.** 기존 배치 그대로.

### addslot 위치연동: 코드상 이미 dock 종속 (자동추종)
- 게임: `m_ItemGroup.getSlotWorldPosFunc = m_Dock.GetSlotWorldPos` (LevelController.cs:501)
  → 아이템·addslot 위치를 dock 슬롯 월드좌표 콜백으로 받음 → dock 이동 시 자동추종.
- `addVecForAddSlot = (-0.5, 0, 0)` (Dock.cs:268) = **수평 전용** → 상단이동 영향 없음.
- 에디터: addslot/잠금슬롯은 `SlotArea` 내부 index 기반 → dock div 내부 종속 → 자동추종.

## 작업 분해

### A. 에디터 프리뷰 (TileMatchAutoLevel) — 사소, 미리보기 일치용
- 파일: `frontend/src/components/GamePlayer/index.tsx` (~388줄 Game area flex-col)
- 변경: `[board][dock]` 순서 → `[dock][board]` 또는 컨테이너 `flex-col-reverse`.
- 자동 처리(작업 0):
  - 타일→dock 비행 종점 = `dockRef.getBoundingClientRect()` 실시간 → 추종.
  - addslot/잠금슬롯 = `SlotArea` 내부 → 추종.
- 검증: `npx tsc --noEmit`, 프리뷰서 dock 상단 + 타일 정확히 날아감.

### B. 실게임 (sp_meowsgarden, Unity) — 배너 실대상, 핵심작업
파일: `Assets/08.Scripts/Tile_Script/InGame/Dock.cs` (+ `LevelController.cs`)

**B1. dock 앵커 하단→상단**
- `GetBottomWorldY` (Dock.cs:323~328): `cam.ViewportToWorldPoint(new Vector3(0.5f, 0f, z))` →
  현재 viewport **y=0(하단)**. 상단은 **y=1f** + 패딩(부호 반대).
- 권장: 하드코딩 대신 `[SerializeField] bool dockAtTop` 토글 + `GetAnchorWorldPos(top?1f:0f, padding)`
  → A/B·롤백 안전.
- `bottomPaddingWorld = 4f` (Dock.cs:323): 상단이면 상단 여백 의미 전환 + 노치 SafeArea 고려.

**B2. 스폰 애니메이션 방향 반전**
- `appearInitYPos` ← `LevelController.dock_AppearInitYPos` (LevelController.cs:489) 주입.
  현재 "화면 아래서 위로". 상단이면 "위에서 아래로"(부호 반전).
- `readyDockVec = settingDockVec + Vector3.up * appearInitYPos` (Dock.cs:320) — 부호만 맞추면 동작.

**B3. 보드(타일 그리드) 겹침 회피** ⚠️ 실작업 비중 큼
- dock이 상단 점유 → 보드를 **아래로 시프트**해야 겹침 없음.
- 보드 위치(씬/프리팹 또는 보드 컨트롤러) **확인 필요** → top margin 추가.
- 미조사 항목 — 착수 시 보드 레이아웃 코드 먼저 확인.

**B4. addslot 위치연동: 대부분 자동 (위 조사 참고)**
- `getSlotWorldPosFunc` 콜백 → 자동추종. `addVecForAddSlot` 수평전용 → 무관.
- 8슬롯 배경/정렬 `SetBackgroundSlotCount` / `UseAddSlotItem`(Dock.cs:2587) = dock 로컬좌표 기준 → 자동.

**B5. 배너 SafeArea (이 작업의 목적)** ⚠️ 실작업 비중 큼
- 기존 인프라 재사용: `Assets/00.spComponents/spSafeArea/` (spSafeArea / spSafeAreaMng).
- 하단 띠배너 높이만큼 **하단 인셋 예약** → dock 상단 이동으로 하단 비워짐.
- 광고 브릿지 기존재: `SPAdsBridgeAdapter` / `IAdsSystem` → 배너 표시 연동 지점.

### 자동추종 (작업 불필요)
타일→dock 비행 / 락슬롯 / 아이템·addslot 위치 / 매치연출 — 전부
`GetSlotWorldPos` / `transform.position` 실시간 참조 → dock 옮기면 따라옴.

### 수동확인 필요 (겹침·방향)
1. 보드 그리드 top margin (B3)
2. 스폰 방향 (B2)
3. dock 상단 SafeArea(노치) + 하단 배너 인셋 (B1/B5)
4. fail/clear 연출, 콤보UI, undo셋 위치가 dock 기준인지

## 테스트 플랜 (시각적)
- 7슬롯 / 8슬롯(addslot 사용) 양쪽
- 타일→dock 비행 종점 정확도
- 다양한 종횡비 (`maxScaleXRatio = Screen.width / 1080`)
- fail(덱풀) / clear 연출, 콤보, undo
- 하단 배너 켠 상태 겹침 0
- 노치/홈인디케이터 기기 SafeArea

## 권장 진행 순서
1. **A(에디터)** 먼저 — 빠른 시각확인.
2. **B는 `dockAtTop` 토글로 구현** — A/B·롤백 안전.
3. B3(보드 시프트) · B5(배너 인셋)가 실작업 핵심 → 보드 위치코드 선조사.

## 미해결 / 착수 시 선조사
- [ ] 게임 보드(그리드) 위치 결정 코드 — 씬/프리팹 vs 컨트롤러 (B3)
- [ ] fail/clear/콤보/undo 연출 좌표가 dock 상대인지 절대인지
- [ ] 하단 배너 실제 높이 스펙 → 하단 인셋 수치
