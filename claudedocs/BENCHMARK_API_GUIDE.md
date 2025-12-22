# 벤치마크 레벨 API 사용 가이드

**날짜**: 2025-12-22
**목적**: 프론트엔드에서 벤치마크 레벨 접근 및 플레이

---

## API 엔드포인트

### 1. 벤치마크 레벨 목록 조회

**GET** `/api/simulate/benchmark/list`

모든 벤치마크 레벨의 메타데이터를 난이도별로 반환합니다.

#### Response Example:
```json
{
  "easy": [
    {
      "id": "easy_01",
      "name": "기본 3종류",
      "description": "3종류 타일, 1레이어. 기본 매칭 연습.",
      "tags": ["basic", "1_layer"],
      "difficulty": "easy"
    },
    {
      "id": "easy_02",
      "name": "4종류 타일",
      "description": "4종류 타일, 1레이어. 타입 다양성.",
      "tags": ["basic", "1_layer", "variety"],
      "difficulty": "easy"
    }
    // ... 총 10개
  ],
  "medium": [
    {
      "id": "medium_01",
      "name": "ICE + 2레이어",
      "description": "6종류 타일, 2레이어, ICE 1개. 기믹 도입.",
      "tags": ["ice", "layer_blocking"],
      "difficulty": "medium"
    }
    // ... 총 10개
  ],
  "hard": [],
  "expert": [],
  "impossible": []
}
```

#### 프론트엔드 사용 예시:
```typescript
async function loadBenchmarkLevels() {
  const response = await fetch('http://localhost:8000/api/simulate/benchmark/list');
  const levels = await response.json();

  // EASY 레벨 10개 표시
  levels.easy.forEach(level => {
    console.log(`${level.name} (${level.id}): ${level.description}`);
  });

  // MEDIUM 레벨 10개 표시
  levels.medium.forEach(level => {
    console.log(`${level.name} (${level.id}): ${level.description}`);
  });
}
```

---

### 2. 개별 벤치마크 레벨 조회

**GET** `/api/simulate/benchmark/{level_id}`

특정 벤치마크 레벨의 상세 데이터를 시뮬레이터 형식으로 반환합니다.

#### Path Parameters:
- `level_id` (string): 레벨 ID (예: `easy_01`, `medium_05`)

#### Response Example:
```json
{
  "level_data": {
    "layer": 1,
    "randSeed": 0,
    "useTileCount": 5,
    "layer_0": {
      "tiles": {
        "1_1": ["t1"],
        "1_2": ["t1"],
        "1_3": ["t1"],
        "2_1": ["t2"],
        "2_2": ["t2"],
        "2_3": ["t2"],
        "3_1": ["t3"],
        "3_2": ["t3"],
        "3_3": ["t3"]
      },
      "col": 5
    },
    "goals": {
      "t1": 3,
      "t2": 3,
      "t3": 3
    }
  },
  "metadata": {
    "id": "easy_01",
    "name": "기본 3종류",
    "description": "3종류 타일, 1레이어. 기본 매칭 연습.",
    "tags": ["basic", "1_layer"],
    "difficulty": "easy",
    "max_moves": 50
  }
}
```

#### 프론트엔드 사용 예시:
```typescript
async function loadLevel(levelId: string) {
  const response = await fetch(`http://localhost:8000/api/simulate/benchmark/${levelId}`);
  const data = await response.json();

  // 레벨 데이터로 게임 초기화
  const levelData = data.level_data;
  const metadata = data.metadata;

  console.log(`Loading: ${metadata.name}`);
  console.log(`Description: ${metadata.description}`);
  console.log(`Max Moves: ${metadata.max_moves}`);

  // 게임 렌더링
  renderLevel(levelData);
}
```

---

### 3. 벤치마크 레벨 시뮬레이션 (봇 플레이 시각화)

**POST** `/api/simulate/visual`

벤치마크 레벨을 봇이 플레이하는 과정을 시각화할 수 있는 상세한 이동 히스토리를 반환합니다.

#### Request Body:
```json
{
  "level_json": {
    // GET /benchmark/{level_id} 에서 받은 level_data
  },
  "bot_types": ["novice", "casual", "average", "expert", "optimal"],
  "max_moves": 50,
  "seed": 42
}
```

#### 봇 타입:
- `novice`: 초보자 - 무작위에 가까운 플레이
- `casual`: 캐주얼 - 기본적인 매칭 인식
- `average`: 일반 - 2-3수 선읽기
- `expert`: 숙련자 - 5수 선읽기, 전략적 플레이
- `optimal`: 최적 - 10수 선읽기, 완벽한 플레이

#### Response Example:
```json
{
  "initial_state": {
    "tiles": {
      "0": {
        "1_1": ["t1"],
        "1_2": ["t1"]
        // ...
      }
    },
    "goals": {
      "t1": 3,
      "t2": 3,
      "t3": 3
    },
    "grid_info": {
      "0": {
        "col": 5,
        "row": 5
      }
    }
  },
  "bot_results": [
    {
      "profile": "optimal",
      "profile_display": "최적",
      "moves": [
        {
          "move_number": 1,
          "layer_idx": 0,
          "position": "1_1",
          "tile_type": "t1",
          "matched_positions": [],
          "tiles_cleared": 0,
          "goals_after": {"t1": 3, "t2": 3, "t3": 3},
          "score_gained": 0.0,
          "decision_reason": "목표 진행 우선",
          "dock_after": ["t1"]
        },
        {
          "move_number": 2,
          "layer_idx": 0,
          "position": "1_2",
          "tile_type": "t1",
          "matched_positions": [],
          "tiles_cleared": 0,
          "goals_after": {"t1": 3, "t2": 3, "t3": 3},
          "score_gained": 0.0,
          "decision_reason": "3매칭 완성 우선",
          "dock_after": ["t1", "t1"]
        },
        {
          "move_number": 3,
          "layer_idx": 0,
          "position": "1_3",
          "tile_type": "t1",
          "matched_positions": ["0_1_1", "0_1_2"],
          "tiles_cleared": 3,
          "goals_after": {"t1": 0, "t2": 3, "t3": 3},
          "score_gained": 30.0,
          "decision_reason": "3매칭 완성 우선",
          "dock_after": []
        }
        // ... 모든 이동
      ],
      "cleared": true,
      "total_moves": 9,
      "final_score": 90.0,
      "goals_completed": {"t1": 3, "t2": 3, "t3": 3}
    }
  ],
  "max_steps": 9,
  "metadata": {
    "elapsed_ms": 25,
    "bot_count": 1,
    "total_tiles": 9,
    "max_moves_setting": 50,
    "dock_slots": 7,
    "game_rules": "sp_template",
    "tile_count_valid": true,
    "tile_count_remainder": 0,
    "tile_count_message": "타일 9개 (3세트)"
  }
}
```

#### 프론트엔드 사용 예시 (전체 플로우):
```typescript
// 1. 벤치마크 레벨 로드
async function playBenchmarkLevel(levelId: string) {
  // 레벨 데이터 가져오기
  const levelResponse = await fetch(`http://localhost:8000/api/simulate/benchmark/${levelId}`);
  const levelData = await levelResponse.json();

  console.log(`Playing: ${levelData.metadata.name}`);

  // 시뮬레이션 요청
  const simulationRequest = {
    level_json: levelData.level_data,
    bot_types: ["optimal"],  // 최적 봇만 플레이
    max_moves: levelData.metadata.max_moves,
    seed: 42
  };

  const simResponse = await fetch('http://localhost:8000/api/simulate/visual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(simulationRequest)
  });

  const simulation = await simResponse.json();

  // 초기 상태 렌더링
  renderInitialState(simulation.initial_state);

  // 봇 플레이 애니메이션
  const optimalBot = simulation.bot_results[0];
  console.log(`Result: ${optimalBot.cleared ? 'CLEAR' : 'FAIL'}`);
  console.log(`Moves: ${optimalBot.total_moves}`);
  console.log(`Score: ${optimalBot.final_score}`);

  // 각 이동을 순차적으로 재생
  for (const move of optimalBot.moves) {
    await animateMove(move);
    await delay(500); // 0.5초 대기
  }
}

function animateMove(move: Move) {
  console.log(`Move ${move.move_number}: Pick ${move.tile_type} at ${move.layer_idx}_${move.position}`);
  console.log(`  Reason: ${move.decision_reason}`);
  console.log(`  Cleared: ${move.tiles_cleared} tiles`);
  console.log(`  Dock: [${move.dock_after.join(', ')}]`);

  // 타일 선택 애니메이션
  highlightTile(move.layer_idx, move.position);

  // 매칭된 타일들 표시
  if (move.matched_positions.length > 0) {
    showMatchAnimation(move.matched_positions);
  }

  // 덱 상태 업데이트
  updateDock(move.dock_after);
}
```

---

## 사용 시나리오

### 시나리오 1: 벤치마크 레벨 목록 표시

```typescript
// 1. 모든 벤치마크 레벨 가져오기
const levels = await fetch('/api/simulate/benchmark/list').then(r => r.json());

// 2. UI에 표시
function renderLevelList() {
  return (
    <div>
      <h2>EASY Tier</h2>
      <ul>
        {levels.easy.map(level => (
          <li key={level.id}>
            <button onClick={() => playLevel(level.id)}>
              {level.name} - {level.description}
            </button>
          </li>
        ))}
      </ul>

      <h2>MEDIUM Tier</h2>
      <ul>
        {levels.medium.map(level => (
          <li key={level.id}>
            <button onClick={() => playLevel(level.id)}>
              {level.name} - {level.description}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

### 시나리오 2: 특정 레벨 플레이

```typescript
async function playLevel(levelId: string) {
  // 1. 레벨 데이터 가져오기
  const response = await fetch(`/api/simulate/benchmark/${levelId}`);
  const { level_data, metadata } = await response.json();

  // 2. 게임 초기화
  initGame(level_data);

  // 3. 사용자 플레이 또는 봇 플레이 선택
  // Option A: 사용자가 직접 플레이
  startUserPlay(level_data, metadata.max_moves);

  // Option B: 봇 플레이 시청
  watchBotPlay(level_data, metadata);
}
```

### 시나리오 3: 봇 비교 모드

```typescript
async function compareBots(levelId: string) {
  // 1. 레벨 데이터 가져오기
  const { level_data, metadata } = await fetch(`/api/simulate/benchmark/${levelId}`).then(r => r.json());

  // 2. 모든 봇으로 시뮬레이션
  const simulation = await fetch('/api/simulate/visual', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      level_json: level_data,
      bot_types: ['novice', 'casual', 'average', 'expert', 'optimal'],
      max_moves: metadata.max_moves,
      seed: 42
    })
  }).then(r => r.json());

  // 3. 결과 비교 표시
  simulation.bot_results.forEach(bot => {
    console.log(`${bot.profile_display}:`);
    console.log(`  Cleared: ${bot.cleared ? 'YES' : 'NO'}`);
    console.log(`  Moves: ${bot.total_moves}`);
    console.log(`  Score: ${bot.final_score}`);
  });
}
```

---

## 현재 사용 가능한 레벨

### EASY Tier (10 levels)
- `easy_01` ~ `easy_10`: 기본 메커닉 검증용
- 특징: 99-100% 클리어율 (모든 봇)
- 목적: 기본 타일 매칭, 간단한 블로킹, 기믹 도입

### MEDIUM Tier (10 levels)
- `medium_01` ~ `medium_10`: 중급 난이도 (현재 너무 쉬움 - 재설계 예정)
- 특징: 98.9-100% 클리어율 (재설계 필요)
- 목적: 복잡한 블로킹, 여러 기믹 조합

### HARD, EXPERT, IMPOSSIBLE Tiers
- 아직 구현되지 않음 (0 levels)

---

## 테스트 방법

### CLI 테스트
```bash
# API 테스트 스크립트 실행
./test_benchmark_api.sh

# 벤치마크 시스템 전체 테스트 (100 iterations × 10 levels × 5 bots)
python3 test_benchmark.py

# 단일 레벨 디버깅
python3 test_single_benchmark.py
```

### cURL 테스트
```bash
# 레벨 목록
curl http://localhost:8000/api/simulate/benchmark/list

# 개별 레벨
curl http://localhost:8000/api/simulate/benchmark/easy_01

# 시뮬레이션
curl -X POST http://localhost:8000/api/simulate/visual \
  -H "Content-Type: application/json" \
  -d '{
    "level_json": {...},
    "bot_types": ["optimal"],
    "max_moves": 50,
    "seed": 42
  }'
```

---

## 관련 파일

- **API Router**: [backend/app/api/routes/simulate.py](../backend/app/api/routes/simulate.py:641-701)
- **Benchmark Levels**: [backend/app/models/benchmark_level.py](../backend/app/models/benchmark_level.py)
- **Test Runner**: [test_benchmark.py](../test_benchmark.py)
- **API Test Script**: [test_benchmark_api.sh](../test_benchmark_api.sh)
- **Final Summary**: [FINAL_SUMMARY.md](FINAL_SUMMARY.md)

---

## 다음 단계

1. **프론트엔드 UI 구현**
   - 벤치마크 레벨 선택 화면
   - 봇 플레이 시각화
   - 결과 비교 차트

2. **MEDIUM Tier 재설계**
   - 현재 너무 쉬움 (98.9-100% 클리어)
   - 목표: Novice 20-45%, Optimal 95-100%

3. **HARD Tier 구현**
   - 10개 레벨 생성
   - 목표: Novice 5-25%, Optimal 90-100%

---

**작성자**: Claude Sonnet 4.5
**문서 버전**: 1.0
**마지막 업데이트**: 2025-12-22
