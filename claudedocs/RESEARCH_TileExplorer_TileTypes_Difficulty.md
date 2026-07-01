# Tile Explorer 등 Triple-Match 게임: 레벨 구간별 타일 종류 갯수와 난이도 연관 고찰

> 작성일: 2026-06-30
> 목적: 실제 시장 출시작(특히 **Tile Explorer - Triple Match**) 및 동종 트리플 매치(Triple Match / Mahjong-Triple) 장르의 **레벨 구간별(초·중·후반) 타일 종류 수 운용**과 그것이 **난이도에 끼치는 영향**을 온라인 자료 기반으로 정리.
> 비고: 본 프로젝트(TileMatchAutoLevel)의 자동 레벨 생성·난이도 분석 설계에 직접 적용 가능한 시사점 포함.

---

## 1. 대상 게임 정의

**Tile Explorer - Triple Match** (개발사 oakever, iOS/Android)
- 장르: 마작 솔리테어 계열 **트리플 매치(3개 매칭)** 퍼즐.
- 코어 룰: 보드의 타일을 탭 → 하단 **트레이(tray)** 로 이동. 같은 타일 3개가 트레이에 모이면 자동 제거. 보드 전체를 비우면 클리어.
- 패배 조건: 트레이가 가득 차면(미매칭 타일이 쌓이면) 실패. 자료상 **트레이 슬롯 7칸** 기준 — 7개가 안 맞고 쌓이면 게임 오버.
- 콘텐츠 규모: 국가(테마) 단위로 묶이며, **국가당 약 60레벨**, 난이도 점증.
- 타일 외형: 기본은 과일(딸기·체리·바나나·버섯 등). 5종 타일셋(크리스마스/아시아풍/꽃/포커 등) 선택 가능. **포커 스타일은 타일 구분이 어려워 체감 난이도 상승** — 즉 "종류 수"뿐 아니라 "시각적 변별력"도 난이도 변수.

장르 일반(Triple Tile, Tile Busters, Mahjong Triple 3D 등): 레벨 수 수천~1만+ 단위. 매주 수백 레벨 추가가 일반적(라이브 운영).

---

## 2. 핵심 수학: 왜 "타일 종류 수"가 난이도 레버인가

트리플 매치는 **모든 타일 수가 3의 배수**여야 풀 수 있다(각 종류 num % 3 == 0). 여기서 두 변수가 난이도를 가른다:

| 변수 | 정의 | 난이도 방향 |
|------|------|-------------|
| **타일 종류 수 (variety, V)** | 보드에 등장하는 서로 다른 타일 종류 개수 | V 클수록 어려움 |
| **종류당 개수 (count per type, C)** | 한 종류가 보드에 몇 개 있는가(3·6·9…) | C 클수록 매칭 여유, 쉬움 |

고정 보드 크기 N = V × C 에서:
- **V↑ (C↓)**: 종류는 많고 각 종류는 적음(예: 3개씩). 트레이 7칸 안에서 "딱 3개"를 동시에 모으기 어려움 → **실수 허용폭 축소, 후반 난이도**.
- **V↓ (C↑)**: 종류 적고 각 종류 다수. 아무 타일이나 집어도 같은 종류가 곧 또 나옴 → **트레이 압박 낮음, 초반 난이도**.

즉 **트레이 슬롯(7) 대비 "동시에 미완성 상태로 떠 있는 종류 수"** 가 실질 난이도. V가 트레이 용량에 근접/초과할수록 위험.

> 보조 난이도 레버(종류 수와 곱해져 작용): **레이어 수(스택 깊이)**, **상하 가림(은폐된 타일)**, **보드 크기/타일 총량**, **시각 변별력**, **이동 제한/시간 제한**, 후반의 ice/chain/lock 류 **기믹**.

---

## 3. 초·중·후반 구간별 운용 패턴 (자료 종합)

여러 가이드·리뷰·레벨디자인 자료에서 반복 확인되는 공통 패턴:

### 초반 (Early / 튜토리얼 구간)
- **타일 종류 수 적음** + **스택(레이어) 얕음** + 가림 거의 없음.
- 종류당 개수 충분 → 트레이가 거의 안 참. 룰 학습이 목적.
- "early levels ease you in with **fewer tile types and simpler stacking**".

### 중반 (Mid)
- **종류 수 점증** + **레이어 추가**(상하 가림 시작) + 패턴 복잡화.
- 신규 타일/배치를 점진 도입해 신선도 유지. 트레이 관리가 변수로 등장.
- "boards become more challenging with extra layers, **more tile types**, and trickier patterns".

### 후반 (Late / Skill 구간)
- **종류 수 많음** + **다층 스택 + 강한 은폐** + 트레이 여유 최소.
- "later boards add variety and depth, **with very little margin for error**".
- "limited number of moves demands careful planning" — 실수 한 번이 트레이 풀 → 실패. **스킬 레벨**(여러 번 재시도해야 통과)이 후반에 집중 배치됨.

| 구간 | 타일 종류 수 | 종류당 개수 | 레이어/은폐 | 트레이 압박 | 주 난이도 원천 |
|------|:---:|:---:|:---:|:---:|---------------|
| 초반 | 적음 | 많음 | 얕음/없음 | 낮음 | 룰 학습 |
| 중반 | 중간 | 중간 | 증가 | 중간 | 종류↑ + 가림 |
| 후반 | 많음 | 적음(3~) | 다층/강함 | 높음 | 종류↑ × 은폐 × 트레이 |

---

## 4. 레벨 디자인 방법론 시사점

업계 레벨 디자인 자료(Room8 / Game Developer)에서:
- 디자이너는 **"projected difficulty curve"(마스터 문서의 목표 난이도 곡선)** 에 맞춰 레벨을 배치·재정렬.
- 핵심 과제: 플레이 가능한 보드 생성 → 재미있는 메카닉 조합 → 플레이어 진행 예측 → **목표 난이도율 설정**.
- 현대 트렌드는 **동적 난이도(개인 맞춤)** + 정적 pass-rate 대신 **평균/중앙값 시도 횟수**를 난이도 지표로 사용. 소프트런치 데이터로 곡선 재조정.

→ "타일 종류 수"는 디자이너가 **곡선을 끌어올리는 1차 레버**, 레이어·은폐·기믹은 곱셈 보조 레버.

---

## 5. 본 프로젝트(TileMatchAutoLevel) 적용 시사점

1. **난이도 = f(V, C, 레이어, 은폐율, 트레이여유)** 의 복합. 정적 분석/봇 시뮬에서 "타일 종류 수 V"와 "트레이 용량 대비 동시 미매칭 종류 수"를 핵심 feature로 다룰 것.
2. **구간별 V 스케줄**을 명시적 곡선으로: 초반 저V·고C·얕은 스택 → 후반 고V·저C(3개)·다층 은폐. 본 프로젝트의 레벨 1~3 고정 레이아웃이 "초반 저난이도" 패턴과 정합.
3. **트레이 7칸이 하드 컷오프** — V가 7에 근접/초과하면 난이도 급상승. 자동 생성기에서 V와 트레이 용량 비율을 난이도 게이트로 사용 가능.
4. **시각 변별력도 난이도** — 같은 V라도 유사 외형 타일셋은 체감 난이도↑. 난이도 라벨링 시 타일셋 변별력 가중치 고려.
5. **난이도 측정 지표**: 정적 pass-rate보다 **봇 평균 시도 횟수**가 업계 표준에 더 부합 → 현 AutoPlay 봇 클리어율 + (가능하면)평균 시도 횟수 병행.

---

## 출처 (Sources)

- [Tile Explorer: Tiles Clear! — App Store](https://apps.apple.com/us/app/tile-explorer-tiles-clear/id6498883328)
- [Tile Explorer - Triple Match — Google Play](https://play.google.com/store/apps/details?id=com.oakever.tiletrip&hl=en)
- [Tile Explorer — Uptodown (리뷰: 타일셋/난이도 점증/포커셋 난이도)](https://tile-explorer.en.uptodown.com/android)
- [Tile Explorer Triple Match Tips — KashKick (트레이 7칸/구간별 난이도)](https://kashkick.com/guide/game-tips/tile-explorer-triple-match-tips/)
- [Smart & Casual: Tile Puzzle Games Level Design (Part 1) — Game Developer](https://www.gamedeveloper.com/design/smart-casual-the-state-of-tile-puzzle-games-level-design-part-1)
- [Smart & Casual: How to Build Match 3 Games Level Design — Room 8 Studio](https://room8studio.com/news/smart-casual-the-state-of-tile-puzzle-games-level-design-part-1/)
- [Tile-matching video game — Wikipedia](https://en.wikipedia.org/wiki/Tile-matching_video_game)
- [The Ultimate Guide To The Best Tile-Matching Games — ExitLag](https://www.exitlag.com/blog/tile-matching-games/)
- [Match Game Mechanics: An exhaustive survey — Game Developer](https://www.gamedeveloper.com/design/match-game-mechanics-an-exhaustive-survey)
