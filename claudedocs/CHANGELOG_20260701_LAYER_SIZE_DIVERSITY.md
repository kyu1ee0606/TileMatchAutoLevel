# CHANGELOG 2026-07-01 — 층별 그리드 크기 다양화 (B)

절차생성 멀티레이어 레벨에서 각 층의 채움 모양 크기를 랜덤(min 3×3~그리드, 인접층 회피)으로
다양화하고 중앙 배치 → 스택 실루엣 단조로움 해소. **레이어 col/row(홀짝 교대값)는 유지**하여
게임 무변경(게임은 rowCount 교대값으로 그리드 생성, FindAllUpperTiles는 데이터 xCol로 블로킹 계산).

설계·검증 상세: `DESIGN_LAYER_SIZE_DIVERSITY.md`.

## 변경 파일

### 백엔드
- `app/models/schemas.py`: `GenerateRequest.size_diversity_start_level: Optional[int]` 추가.
- `app/models/level.py`: `GenerationParams.size_diversity_start_level: Optional[int]` 추가.
- `app/core/generator.py`:
  - 정책 상수 `SIZE_DIVERSITY_MODE="single"`, `SIZE_DIVERSITY_MIN_SIZE=3`.
  - 헬퍼 `_compute_layer_size_diversity(...)` — start_level 게이팅 + 층별 랜덤 s(인접 회피, min 3, ≤그리드).
  - standard/master 패턴 경로 + auto 경로 레이어 루프에 주입: 활성 시 step 기반 크기 대신 s×s override,
    기존 중앙 오프셋 로직 재사용. col/row는 base(교대값) 유지.
- `app/api/routes/generate.py`: 주 생성/폴백/validated `GenerationParams(...)`에 필드 전달.

### 프론트엔드
- `src/types/index.ts`: `GenerationParams.size_diversity_start_level?`.
- `src/api/generate.ts`: `GenerateRequest` 인터페이스 + `generateLevel` 요청 빌더 매핑.
- `src/components/ProductionDashboard/index.tsx`: 상태 `sizeDiversityStartLevel`(기본 101),
  `GenerateTab` prop 전달, 숫자 입력 UI(배치 설정), 주 배치 생성 `params`에 전달.

## 함께 커밋된 선행 작업 (A, 미검증 상태였음)
- `ProductionDashboard`: `max_layers` 캡 7→10 상향(일반/보스 공식 여러 경로). 어려운 레벨 최대 10층.

## 검증
- `py_compile`(4파일) OK, `tsc --noEmit` 0.
- 헬퍼 유닛 12000픽: min<3/grid초과/인접동일 각 0, 비단조 2000/2000. 게이팅 경계(100 OFF/101 ON) 확인.
- API: col 교대값 유지, num%3==0, ON span≥3·중앙 적합, OFF(90/None) 미적용.
- 솔버빌리티 A* 회귀 없음(÷3 위반 0, IMPOSSIBLE 0). 봇 autoplay ON 정상.
- GameBoost 업로드(level_110/112) + TownPop map 라운드트립에서 다양화 데이터 보존.
- Unity 실기: MCP 미연결로 수동(게임 정합 원리는 level_91/92로 기검증). level_110/112 업로드 완료.

## 한계
- 다양화는 주 배치 생성 경로에만 배선. Test/Review 탭 단일 재생성/enhance는 미배선(후속).
- layered(nested-frame) 특수모양·배치/템플릿 레벨은 제외.
