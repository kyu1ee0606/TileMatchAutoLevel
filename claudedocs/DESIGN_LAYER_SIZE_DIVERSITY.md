# DESIGN: 층별 그리드 크기 다양화 (Layer Size Diversity, "B")

**작성일**: 2026-07-01
**대상**: 절차생성 멀티레이어 프로덕션 레벨 (배치·템플릿 레벨 무영향)
**상태**: 구현 완료, 데이터+솔버빌리티 검증 통과, Unity 실기 확인은 수동(사유 하단)

---

## 1. 문제

현재 프로덕션 멀티레이어 레벨은 모든 층이 **홀짝 교대 그리드**(짝수층=cols+1, 홀수층=cols, 예 7↔6)로
고정된 크기를 채워 스택 실루엣이 단조롭다. 층마다 다른 크기의 모양을 넣어 시각적 다양성과
난이도 변화를 주려는 것이 이 작업(B)이다.

## 2. 게임 정합 원리 (게임 코드 무변경 확정)

큰 그리드(예 7×7) 데이터 안에 작은 모양(예 3×3)을 **중앙 배치**하고 바깥칸을 비우면,
게임은 그대로 정상 렌더/클리어/블로킹한다. 이유:

- `TileLayer.LayerSpawn`은 `rowCount`(홀짝 교대값)로 그리드를 생성하고, 레이어 데이터의
  `col`/`row`는 무시한다.
- `FindAllUpperTiles`(`DB_Level.cs:699`)는 데이터의 `xCol`을 비교해 상하층 블로킹을 계산한다.

따라서 **레이어 데이터의 `col`/`row`는 교대값 그대로 두고, 실제로 채우는 셀만 작게** 하면
게임과 정합된다. 홀짝 0.5칸 오프셋은 게임이 자동 적용하는 정상 동작이다.

> 이 원리는 사용자가 `level_91`, `level_92`를 GameBoost에 업로드해 Unity 실기로 이미 검증했다
> (큰 그리드 + 작은 중앙 모양이 정상 렌더/클리어/블로킹). B는 이 데이터 형태를 절차적으로 생성할 뿐이다.

**불변식 (깨면 블로킹 붕괴)**:
1. 레이어 `col`/`row`는 **반드시 홀짝 교대값 유지**.
2. 채움 모양은 그리드 안에 중앙 배치(범위 이탈 금지).
3. 최소 채움 크기 **3×3**.

## 3. 정책 (확정, 잠금)

| 항목 | 결정 |
|------|------|
| 모드 | `single`(기본): 전 층 동일 `pattern_index`, **크기만** 층별 다양화. `per_layer`(예약): 층마다 다른 pattern_index — 상수로 구조만 확보, 현재 미사용 |
| 크기 배정 | **제약 랜덤** — 층별 s ∈ `[min_size, min(base_cols, base_rows)]` 랜덤, **인접층과 같은 크기 회피** |
| 최소 크기 | 3×3 (`SIZE_DIVERSITY_MIN_SIZE = 3`) |
| 적용 시작 | `size_diversity_start_level` 이상만. 기본 프리필 **101**(튜토리얼/초반은 단순 유지). `None`/0 = 미적용 |
| 게임 | **무변경** |
| 대상 경로 | 절차생성만: (a) standard/master 패턴 경로(`pattern_index` 지정), (b) auto 경로(`pattern_index=None`). layered(nested-frame 특수모양) 및 배치/템플릿(from-template)은 **제외** |

## 4. 구현

### 4-1. 스키마/파라미터
- `backend/app/models/schemas.py` `GenerateRequest.size_diversity_start_level: Optional[int]`
- `backend/app/models/level.py` `GenerationParams.size_diversity_start_level: Optional[int]`
- `backend/app/api/routes/generate.py`: 주 생성(`_generate_level_impl`)·폴백·validated 경로의
  `GenerationParams(...)`에 `size_diversity_start_level=request.size_diversity_start_level` 전달.
  워커(`_generate_core_worker`)는 `GenerateRequest(**request_dict)`로 재구성 → 필드 자동 전파.

### 4-2. 헬퍼 (`generator.py`)
```
LevelGenerator._compute_layer_size_diversity(active_layers, base_sizes,
    level_number, start_level, min_size=3) -> Optional[Dict[layer_idx, s]]
```
- `start_level` None이거나 `level_number < start_level` → `None`(미적용).
- 각 층: `max_s = min(base_cols, base_rows)`. `max_s <= min_size`면 s=max_s.
  그 외 `[min_size..max_s]`에서 인접층(prev_s) 회피 랜덤.
- 반환은 층→s 매핑. **col/row는 호출측이 base(교대값)로 유지**(불변식 1).

### 4-3. 주입
두 경로 각각, 레이어 루프 진입 전에 `size_div_map`을 계산하고, 루프 내에서 활성 시
기존 step 기반 `layer_cols/layer_rows`를 **랜덤 s×s로 override**. 그 뒤 기존 중앙 오프셋
로직(`(base_cols - s)//2`)이 그대로 중앙 배치를 수행한다(기 검증된 코드 재사용).
`level[layer_key]["col"]`은 기존대로 base로 세팅(auto 경로는 base_structure의 교대값 유지).

### 4-4. 3배수/타입/솔버빌리티
위치만 바꾸므로 하류 `_ensure_tile_count_divisible_by_3` + 타입배정 + 봇검증이 3배수를
자동 처리 → B에 별도 3배수 로직 불필요.

### 4-5. 프론트
- `types/index.ts` `GenerationParams.size_diversity_start_level?`
- `api/generate.ts` `GenerateRequest` + `generateLevel` 요청 빌더에 매핑
- `ProductionDashboard`: 상태 `sizeDiversityStartLevel`(기본 101) + `GenerateTab`에 prop 전달
  + 숫자 입력 UI(배치 설정, 역생성 토글 아래). 주 배치 생성 `params`에 전달(0이면 undefined).

## 5. 검증 결과 (2026-07-01)

- `py_compile` 4파일 OK, `tsc --noEmit` 0.
- 헬퍼 유닛: 게이팅(None/level<start/level=None → None, level==start → 적용) 정확.
  2000 draw×6층=12000 픽 중 min<3 **0건**, grid 초과 **0건**, 인접동일 **0건**,
  비단조(랜덤 증명) draw **2000/2000**.
- API(레벨 110/115 ON, 90/None OFF): 모든 케이스 `col_seq` 교대값(7,6,7,6…) 유지,
  `num%3==0`, ON 최소 span≥3, span은 col 이내(중앙 적합). 100↔101 경계 게이팅 확인.
- 솔버빌리티 A*(ON 5레벨): PROVEN_SOLVABLE 4 / UNCERTAIN 1(예산초과, IMPOSSIBLE 아님),
  ÷3 위반 0 → 회귀 없음(오히려 작은 모양=상태공간 축소로 증명 용이).
- 봇 autoplay ON vs OFF 동일 config: ON 클리어율 정상, OFF 대비 열위 아님.
- GameBoost 업로드(level_110/112) 성공+썸네일, TownPop `map` 라운드트립에서 col 교대값·
  중앙 소형 모양·층별 크기 다양성 보존 확인.

### 5-1. Unity 실기
Unity MCP 서버 미연결 → 플레이모드 자동 구동 불가. 다만 §2대로 게임 정합 원리는
사용자가 `level_91/92`로 **이미 실기 검증** 완료. 본 작업물은 `level_110`, `level_112`를
GameBoost에 업로드해 둠 → 수동 플레이로 다양한 크기 층 렌더/클리어/블로킹 최종 확인 가능.

## 6. 범위 한계 (알려진)

- 다양화는 **주 배치 생성 경로**(ProductionDashboard 배치 생성)에만 배선. Test/Review 탭의
  단일 레벨 재생성(`handleRegenerateLevel`)·배치 타일수 재생성·enhance는 해당 탭이 별도
  컴포넌트로 상태(`sizeDiversityStartLevel`)를 받지 않아 미배선(재생성 시 다양화 미적용).
  필요 시 후속으로 tab에 prop 전파. MVP 범위 밖으로 판단해 보류.
- layered(nested-frame) 특수모양 패턴은 설계 형태 보존 위해 제외.
