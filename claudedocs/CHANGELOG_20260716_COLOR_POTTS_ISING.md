# 색 분산 슬라이더 — Potts–Metropolis(Ising) 엔진 + Join-Count 지표

> 2026-07-16 · 색 뭉침↔흩어짐을 물리모델 기반으로 정교화. 3단 다이얼 중 '색' 단계 고도화.

## 배경
초기 색 분산 = 이산 block(뭉침 max_c~분산 1) → run-length 프록시. 유저 제보: "75% 아래 다 붙어보임, 100%만 쓸만" = 하위 죽은구간. 원인 = block 이산 + run↔난이도 비선형.

## 온라인검색 반영 (이론 정본화)
- **Kawasaki 스왑 dynamics**: 두 타일 색 교환 + Metropolis 수락 → **색 개수 보존 = ÷3 자동안전** (단일플립 Glauber 아님).
- **Join-count statistic** (Moran 창안, 범주형 정본): 같은색 인접쌍 수. **Moran's I는 연속형이라 색(범주형)엔 부적합** → 색인덱스에 직접 쓰면 t1↔t2가 "가깝다" 오판. join-count가 맞음.
- **하이브리드 이웃그래프**: 공간(시각) + 노출순(난이도) → 7슬롯 트레이 수집게임은 난이도=노출순서(트레이 진입순).

## 구현 (백엔드 `tune.py`)
- **에너지** `E = Σ_(i,j)∈W w·[color_i==color_j]` (Potts/join-count).
- **이웃그래프 W**: 같은레이어 rook 4방(α=1) + reveal 연속쌍(β=1).
- **극단 배치 프로브**: greedy+SA로 `E_max`(완전뭉침)·`E_min`(완전분산) 실측 → 정규화·목표범위.
- **슬라이더 선형매핑**: `E* = E_min + (E_max−E_min)(1−spread)`. spread0=뭉침(쉬움)~1=분산(어려움).
- **greedy 목표추적 어닐**(오르막 없음) → target 정밀명중 → **cluster_index 단조**. 극단(spread 0/1)은 프로브 배치 그대로 = ±1 정확.
- **cluster_index** = 정규화 join-count `−1(체스판)~0(랜덤)~+1(뭉침)`.
- **td[0]만 스왑** → td[1](기믹)·위치·색멀티셋 불변 = 기믹·모양·÷3 전부 보존.

## 프론트 (ProductionDashboard)
- 색 슬라이더 라벨에 **cluster_index 실시간 표시** (예 "뭉침 +0.66"). `recomputeDials`가 `/tune/color` 응답서 캡처.
- 파이프라인 유지: 모양→기믹(td1)→색(td0), 캐스케이드 동일.

## 검증 (실측)
- **전 레벨 cluster_index 단조 + 균등**: 예 L4 `+1.00 +0.78 +0.56 +0.32 +0.10 −1.00` (죽은구간 없음).
- **÷3 보존**: td[0] 스왑만 → 타입카운트 불변 (전 레벨 True).
- **기믹 보존**: 파이프라인서 attrs 유지 (L80 15개 유지).
- **결정적**: 같은 spread=같은 배치 (True).
- **속도**: 3~4ms (RL 없는 배치, 목표 <100ms 대폭 하회).
- 최종 난이도는 여전히 RL이 확정(cluster_index는 뭉침 프록시).

## 파일
- `backend/app/api/routes/tune.py` — 그래프·에너지·Kawasaki-Metropolis 엔진 + `/color` 재작성, `cluster_index` 응답.
- `frontend/.../ProductionDashboard/index.tsx` — cluster_index state·표시.
- 게임코드 무변경.

## 한계 (정직)
- 색배치 난이도폭 = 레벨 크기·색종류 의존(작은레벨 좁음). cluster_index는 뭉침도지 난이도 정본 아님(RL이 확정).
- spread 0.8→1.0 구간은 분산극단(−1, 체스판)까지라 지표 간격 다소 큼(정규화 piecewise). 단조성·유효성은 유지.

## Sources
- Kawasaki dynamics (conserved order parameter): link.springer.com/article/10.1007/BF01049728
- Join count statistic (categorical spatial autocorr): en.wikipedia.org/wiki/Join_count_statistic
- Match-3 difficulty RL balancing: doi.org/10.3390/electronics12214456
