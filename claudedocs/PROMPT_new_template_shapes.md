# 신규 타일 모양 템플릿 생성 프롬프트

아래 `=== 프롬프트 시작 ===` ~ `=== 프롬프트 끝 ===` 사이를 통째로 복사해 다른 AI에게 주면 됨.

---

=== 프롬프트 시작 ===

You are a pixel-shape designer for a **tile-matching puzzle game**. I need NEW shape templates as JSON.

## What a "shape" is
A shape = which cells of a square grid are **filled** (a tile sits there). Empty cells = no tile.
- Coordinates are strings `"x_y"` where `x` = column (0-indexed, left→right), `y` = row (0-indexed, **top→bottom**).
- Example 3×3 plus: `["1_0","0_1","1_1","2_1","1_2"]`

## Each shape must be a BUNDLE of 4 grid sizes
Provide the SAME shape at **4×4, 5×5, 6×6, 7×7** (4 variants). Larger = more detail, smaller = simplified core of the same shape. They must look like the same design at different resolutions.

## HARD RULES (every variant must pass ALL — verify by counting)
1. **Divisible by 3 (CRITICAL):** the number of filled cells in EACH variant MUST be exactly divisible by 3 (the game clears tiles in groups of 3). Count your cells; if not ÷3, add/remove cells symmetrically until it is.
2. **Bilateral symmetry:** mirror-symmetric about the vertical center axis (left half = right half mirrored). This makes shapes read as intentional/pretty.
3. **Connected:** all filled cells form ONE connected blob (4-directional adjacency). No floating/detached cells.
4. **No single holes:** no empty cell fully surrounded by filled cells on all 4 sides.
5. **Centered:** the shape sits centered in the grid (balanced margins).
6. **Fill ratio:** roughly 40–70% of the grid filled. Not too sparse, not a full block.
7. **Resolution reality:** the visible grid is capped at 7×7, so design shapes that are RECOGNIZABLE at 7×7. Detailed objects (realistic animals) won't read — favor bold simple silhouettes/icons/emblems.

## Existing shapes — DO NOT duplicate these (we already have them)
These are mostly abstract/geometric (solid blocks, diamonds, crosses, frames, octagons, arrows, spirals). Format `#index WxH cellcount: row/row/...` (`#`=filled, `.`=empty):

```
#0 7x7 48c: #######/#######/#######/###.###/#######/#######/#######
#1 7x7 24c: ...#.../..###../.#####./###.###/.#####./..###../...#...
#2 7x7 36c: ..###../.#####./#######/###.###/#######/.#####./..###..
#3 7x7 33c: ..###../..###../#######/#######/#######/..###../..###..
#4 7x7 33c: .#####./##...##/#.###.#/#.###.#/#.###.#/##...##/.#####.
#5 7x7 21c: ...#.../..#.#../.#####./#.###.#/.#####./..#.#../...#...
#6 7x7 33c: #######/##...##/#.#.#.#/#..#..#/#.#.#.#/##...##/#######
#7 7x7 36c: ..###../.#####./#######/###.###/#######/.#####./..###..
#8 6x6 24c: .#..#./######/######/.####./..##../##..##
#9 7x7 27c: #######/###.###/..#.#../..###../..###../..###../..###..
#10 7x7 27c: ...#.../..###../.#####./#######/..###../..###../.#####.
#11 7x7 27c: .#####./..###../..###../#######/.#####./..###../...#...
#12 7x7 27c: ...#.../..##..#/.######/#######/.######/..##..#/...#...
#13 7x7 27c: ...#.../#..##../######./#######/######./#..##../...#...
#14 7x7 30c: .#####./###.###/##...##/#.....#/#..#..#/#.###.#/#.###.#
#15 7x7 24c: ...#.../..###../#######/.#####./...#.../..###../.##.##.
#16 6x6 24c: ..##../######/.####./.####./######/..##..
#17 7x7 30c: ..#####/.####../####.../####.../####.../.####../..#####
#18 6x6 24c: #.##.#/.####./##..##/##..##/.####./#.##.#
#19 7x7 27c: .#####./#.....#/#.###.#/#.#.#.#/#.###.#/#....../.#####.
#20 7x7 33c: ##...##/##...##/#.###.#/#######/#.###.#/##...##/##...##
#21 7x7 27c: #######/..#.#../..###../..###../..###../..#.#../#######
#22 7x7 24c: ##...../##...../##...../##...../##...../#######/#######
#23 6x6 24c: ##..##/##..##/##..##/##..##/##..##/.####.
#24 7x7 27c: ##...##/###.###/..###../...#.../..###../###.###/##...##
#25 7x7 27c: ##...##/###.###/.#####./..###../..###../..###../..###..
#26 6x6 21c: ######/....##/...##./.###../##..../######
#27 7x7 27c: .#####./##...../.####../..####./....###/##...##/.#####.
#28 4x4 9c: .###/#..#/#..#/.##.
#29 7x7 30c: ..#####/.######/###..../##...../###..../.######/..#####
#30 7x7 30c: ......./...#.../..###../.#####./#######/#######/#######
#31 7x7 30c: #######/#######/#######/.#####./..###../...#.../.......
#32 7x7 33c: #######/.#####./#.###../...#.../..###.#/.#####./#######
#33 7x7 27c: #.....#/##...##/.##.##./..###../.#####./#######/..#.#..
#34 7x7 30c: ......./......#/....###/..#####/#######/#######/#######
#35 7x7 24c: #######/#######/..#####/....###/.....##/......./.......
#36 7x7 33c: ...#.../..###../..###../.#####./#######/#######/#######
#37 7x7 33c: #######/#######/#######/.#####./..###../..###../...#...
#38 7x7 24c: ###..../####.../.####../..####./...####/....###/.....##
#39 7x7 21c: ..###../.#####./##...##/#.....#/..###../.#...#./#.....#
#40 6x6 28c: ######/#.##.#/##..##/##..##/#.##.#/######
#41 6x6 24c: ######/#....#/#.##.#/#.##.#/#....#/######
#42 7x7 33c: ###.###/##...##/#.###.#/..###../#.###.#/##...##/###.###
#43 7x7 24c: #######/#.....#/#.....#/#.....#/#.....#/#.....#/#######
#44 7x7 33c: ##.####/#...###/..#..../#...###/##.####/##.####/##.####
#45 7x7 27c: #..#..#/##.#.##/##...##/..###../##...##/##.#.##/#..#..#
#46 7x7 25c: .#####./#.....#/#.###.#/#.....#/.#####./...#.../##.#.##
#47 7x7 21c: ##.#.##/......./#.###.#/...#.../#.###.#/......./##.#.##
#48 7x7 27c: ##..###/.##..##/..##..#/#..##../##..##./.##..##/#.##..#
#49 7x7 24c: .#.#.#./#.#.#.#/.#.#.#./#.#.#.#/.#.#.#./#.#.#.#/.#.#.#.
#50 7x7 31c: ##...##/##...##/##...##/#######/##...##/##...##/##...##
#51 7x7 37c: #######/#######/..###../..###../..###../#######/#######
#52 7x7 24c: ..###../..###../..###../...#.../##...##/###.###/.##.##.
#53 7x7 30c: ###.###/###.###/......./......./###.###/###.###/###.###
#55 6x6 24c: ..##../.####./######/######/.####./..##..
#57 7x7 28c: .#####./#.....#/#.###.#/#.#.#.#/#.###.#/#.....#/.#####.
#58 6x6 18c: ##...#/###.../.###../..###./...###/#...##
#59 7x7 33c: #.....#/##...##/#######/#######/#######/##...##/#.....#
#61 6x6 20c: ..##../..##../######/######/..##../..##..
#62 7x7 21c: #######/......./......./#######/......./......./#######
#63 7x7 30c: ######./#.....#/#.###.#/#.#.#.#/#.###.#/#.....#/.######
```

## Your task (2 parts)
**Part A — Recommend:** First list 12–20 NEW shape ideas that are NOT in the catalog above and that read well at 7×7. The existing set is almost all abstract geometry, so prefer recognizable ICON/EMBLEM silhouettes. Good candidates: star, crown, gem/jewel, key, leaf/clover, fish, bell, anchor, lightning bolt, flower/tulip, shield, teardrop, ribbon/bow, paw print, gear/cog, crescent moon, sun, mushroom, butterfly, hourglass, arrow-cluster, snowflake, spade/club. For each, one line on why it reads at 7×7.

**Part B — Produce JSON:** Pick the best 8–12 and output them as a JSON object in EXACTLY this format (one entry per shape per size; indices start at 100 to avoid collision):

```json
{
  "100_4x4": { "grid_size": 4, "positions": ["x_y", "..."] },
  "100_5x5": { "grid_size": 5, "positions": ["x_y", "..."] },
  "100_6x6": { "grid_size": 6, "positions": ["x_y", "..."] },
  "100_7x7": { "grid_size": 7, "positions": ["x_y", "..."] },
  "101_4x4": { "grid_size": 4, "positions": ["..."] }
}
```

Also add a `"name"` field per the 7×7 entry, e.g. `"name": "star"`.

## Before you output — self-check EVERY variant
- [ ] cell count ÷3 == 0 (count them)
- [ ] left-right symmetric
- [ ] one connected blob, no floating cells
- [ ] no fully-surrounded empty cell
- [ ] centered, 40–70% fill
- [ ] the 4 sizes of one shape look like the same design

Output Part A (the list) first, then Part B (the JSON). Make the JSON valid and copy-pasteable.

=== 프롬프트 끝 ===

---

## 받은 JSON 등록하는 법 (우리 시스템)
1. 다른 AI가 준 JSON을 검증: 각 variant 셀수 ÷3, 대칭, 연결성 (안 맞으면 우리 `/patterns/accept`가 거부하거나 ÷3 보정함).
2. 등록 경로 2가지:
   - **API**: 각 모양을 `POST /api/patterns/accept` 로 `{variants:[{grid_size, positions}...], name}` 전송 → 64+ 자동 인덱스로 저장(synth:true).
   - **직접 편집**: `backend/data/custom_patterns.json`에 인덱스 충돌 없게(64+ 또는 100+) 병합 후 `synth:true` 표식. 단 정본은 SQLite DB라 materialize와 어긋날 수 있으니 API 권장.
3. 등록되면 프로덕션 레벨 생성의 상·중간 레이어 풀에 자동 주입됨(generator.py).

## 주의 (정직)
- 다른 AI는 **÷3 제약을 자주 틀림** (4사이즈×채움수 맞추기 어려움). 받은 JSON은 반드시 우리 검증 통과시킬 것 — `/patterns/accept`가 ÷3 위반 시 400 반환.
- 7×7 해상도 한계상 "별·왕관"도 단순 실루엣으로만 읽힘. 복잡한 사물 요청해도 결과는 추상화됨.
