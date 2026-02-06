# 기믹 언락 시스템 설계서 (인게임 구현용)

## 1. 개요

프로덕션 1,500레벨에 대한 기믹(장애물) 언락 타이밍 및 도입 전략입니다.
**2026년 2월 인게임 최종 확정 스펙 (13개 기믹)**에 따라 작성되었습니다.

---

## 2. 기믹 종류 및 복잡도

| 순서 | 기믹 ID | 한글명 | 언락 스테이지 | 간격 | 설정 필드 |
|------|---------|--------|---------------|------|-----------|
| 1 | `craft` | 공예 | 10 | - | goals |
| 2 | `stack` | 스택 | 20 | 10 | goals |
| 3 | `ice` | 얼음 | 30 | 10 | obstacle_types |
| 4 | `link` | 연결 | 50 | 20 | obstacle_types |
| 5 | `chain` | 사슬 | 80 | 30 | obstacle_types |
| 6 | `key` | 버퍼잠금 | 110 | 30 | **unlockTile** |
| 7 | `grass` | 풀 | 150 | 40 | obstacle_types |
| 8 | `unknown` | 상자 | 190 | 40 | obstacle_types |
| 9 | `curtain` | 커튼 | 240 | 50 | obstacle_types |
| 10 | `bomb` | 폭탄 | 290 | 50 | obstacle_types |
| 11 | `time_attack` | 타임어택 | 340 | 50 | **timea** |
| 12 | `frog` | 개구리 | 390 | 50 | obstacle_types |
| 13 | `teleport` | 텔레포터 | 440 | 50 | obstacle_types |

---

## 3. 특수 기믹 설정 방법

### 3.1 Key (버퍼잠금) - unlockTile 필드

버퍼(독) 슬롯을 잠그는 기믹입니다.

**설정 방법:**
```json
{
  "unlockTile": 2
}
```

**동작 방식:**
- `unlockTile=1` → 버퍼 1칸 잠김 → 열쇠 타일 3개 등장
- `unlockTile=2` → 버퍼 2칸 잠김 → 열쇠 타일 6개 등장
- `unlockTile=N` → 버퍼 N칸 잠김 → 열쇠 타일 3×N개 등장

**해제 규칙:**
- 열쇠 타일 3개를 모을 때마다 버퍼 1칸이 해제됨
- 열쇠 타일은 기존 타일에서 치환되어 나타남

**권장 설정:**
| 난이도 | unlockTile 값 | 열쇠 타일 수 |
|--------|---------------|-------------|
| 쉬움 | 1 | 3개 |
| 보통 | 2 | 6개 |
| 어려움 | 3 | 9개 |

### 3.2 TimeAttack (타임어택) - timea 필드

제한 시간 내에 클리어해야 하는 기믹입니다.

**설정 방법:**
```json
{
  "timea": 60
}
```

**동작 방식:**
- `timea=0` → 타임어택 비활성화 (기본값)
- `timea=60` → 60초 제한 시간
- `timea=N` → N초 제한 시간

**권장 설정:**
| 난이도 | timea 값 | 설명 |
|--------|----------|------|
| 쉬움 | 120 | 2분 |
| 보통 | 90 | 1분 30초 |
| 어려움 | 60 | 1분 |
| 매우 어려움 | 45 | 45초 |

---

## 4. 기믹 언락 스케줄

### 4.1 핵심 언락 타이밍표

```
Stage   1-9   : 기믹 없음 (순수 매칭 학습)
Stage  10     : craft 언락 ⭐ 첫 번째 기믹 (공예)
Stage  20     : stack 언락 (스택) [간격: 10]
Stage  30     : ice 언락 (얼음) [간격: 10]
Stage  50     : link 언락 (연결) [간격: 20]
Stage  80     : chain 언락 (사슬) [간격: 30]
Stage 110     : key 언락 (버퍼잠금) [간격: 30] ★신규
Stage 150     : grass 언락 (풀) [간격: 40]
Stage 190     : unknown 언락 (상자) [간격: 40]
Stage 240     : curtain 언락 (커튼) [간격: 50]
Stage 290     : bomb 언락 (폭탄) [간격: 50]
Stage 340     : time_attack 언락 (타임어택) [간격: 50] ★신규
Stage 390     : frog 언락 (개구리) [간격: 50]
Stage 440     : teleport 언락 (텔레포터) [간격: 50]
Stage 441+    : 모든 기믹 언락 완료
```

### 4.2 상세 언락 데이터 (JSON 형식)

```json
{
  "gimmick_unlock_schedule": {
    "craft": {
      "unlock_level": 10,
      "practice_levels": 9,
      "integration_start": 20,
      "description": "공예 - 특정 방향으로 타일 수집 목표"
    },
    "stack": {
      "unlock_level": 20,
      "practice_levels": 9,
      "integration_start": 30,
      "description": "스택 - 겹쳐진 타일 수집 목표"
    },
    "ice": {
      "unlock_level": 30,
      "practice_levels": 19,
      "integration_start": 50,
      "description": "얼음 - 인접 타일 클리어로 녹임"
    },
    "link": {
      "unlock_level": 50,
      "practice_levels": 29,
      "integration_start": 80,
      "description": "연결 - 연결된 타일 동시 선택 필요"
    },
    "chain": {
      "unlock_level": 80,
      "practice_levels": 29,
      "integration_start": 110,
      "description": "사슬 - 인접 타일 클리어로 해제"
    },
    "key": {
      "unlock_level": 110,
      "practice_levels": 39,
      "integration_start": 150,
      "field": "unlockTile",
      "description": "버퍼잠금 - unlockTile 필드로 잠금 칸 수 설정"
    },
    "grass": {
      "unlock_level": 150,
      "practice_levels": 39,
      "integration_start": 190,
      "description": "풀 - 인접 타일 클리어로 제거"
    },
    "unknown": {
      "unlock_level": 190,
      "practice_levels": 49,
      "integration_start": 240,
      "description": "상자 - 상위 타일 제거 전까지 숨겨짐"
    },
    "curtain": {
      "unlock_level": 240,
      "practice_levels": 49,
      "integration_start": 290,
      "description": "커튼 - 가려진 타일, 기억력 테스트"
    },
    "bomb": {
      "unlock_level": 290,
      "practice_levels": 49,
      "integration_start": 340,
      "description": "폭탄 - 카운트다운 후 폭발, 시간 압박"
    },
    "time_attack": {
      "unlock_level": 340,
      "practice_levels": 49,
      "integration_start": 390,
      "field": "timea",
      "description": "타임어택 - timea 필드로 제한 시간(초) 설정"
    },
    "frog": {
      "unlock_level": 390,
      "practice_levels": 49,
      "integration_start": 440,
      "description": "개구리 - 매 턴 이동, 전략적 배치 필요"
    },
    "teleport": {
      "unlock_level": 440,
      "practice_levels": 49,
      "integration_start": 490,
      "description": "텔레포터 - 타일 위치 변경"
    }
  }
}
```

---

## 5. 기믹 도입 4단계 시스템

각 기믹은 4단계를 거쳐 플레이어에게 자연스럽게 익숙해집니다:

### 5.1 단계 정의

| 단계 | 영문 | 설명 | 난이도 조절 |
|------|------|------|-------------|
| 1단계 | TUTORIAL | 기믹 첫 등장 | 매우 쉬움, 해당 기믹만 등장 |
| 2단계 | PRACTICE | 연습 기간 | 쉬움~중간, 해당 기믹 집중 |
| 3단계 | INTEGRATION | 통합 기간 | 이전 기믹과 조합 시작 |
| 4단계 | MASTERY | 숙달 | 자유롭게 조합 사용 |

### 5.2 기믹별 단계 레벨 범위

| 기믹 | TUTORIAL | PRACTICE | INTEGRATION | MASTERY |
|------|----------|----------|-------------|---------|
| craft | 10 | 11-19 | 20-29 | 30+ |
| stack | 20 | 21-29 | 30-49 | 50+ |
| ice | 30 | 31-49 | 50-79 | 80+ |
| link | 50 | 51-79 | 80-109 | 110+ |
| chain | 80 | 81-109 | 110-149 | 150+ |
| key | 110 | 111-149 | 150-189 | 190+ |
| grass | 150 | 151-189 | 190-239 | 240+ |
| unknown | 190 | 191-239 | 240-289 | 290+ |
| curtain | 240 | 241-289 | 290-339 | 340+ |
| bomb | 290 | 291-339 | 340-389 | 390+ |
| time_attack | 340 | 341-389 | 390-439 | 440+ |
| frog | 390 | 391-439 | 440-489 | 490+ |
| teleport | 440 | 441-489 | 490+ | - |

---

## 6. 레벨 구간별 사용 가능 기믹

### 6.1 간략 테이블

| 레벨 범위 | 사용 가능 기믹 | 기믹 수 |
|-----------|---------------|---------|
| 1-9 | 없음 | 0 |
| 10-19 | craft | 1 |
| 20-29 | craft, stack | 2 |
| 30-49 | craft, stack, ice | 3 |
| 50-79 | craft, stack, ice, link | 4 |
| 80-109 | +chain | 5 |
| 110-149 | +key | 6 |
| 150-189 | +grass | 7 |
| 190-239 | +unknown | 8 |
| 240-289 | +curtain | 9 |
| 290-339 | +bomb | 10 |
| 340-389 | +time_attack | 11 |
| 390-439 | +frog | 12 |
| 440+ | +teleport (전체) | 13 |

---

## 7. 튜토리얼 레벨 특별 처리

### 7.1 튜토리얼 레벨 목록

클라이언트에서 다음 레벨에서는 **튜토리얼 UI**를 표시해야 합니다:

```json
{
  "tutorial_levels": {
    "10": {"gimmick": "craft", "name": "공예"},
    "20": {"gimmick": "stack", "name": "스택"},
    "30": {"gimmick": "ice", "name": "얼음"},
    "50": {"gimmick": "link", "name": "연결"},
    "80": {"gimmick": "chain", "name": "사슬"},
    "110": {"gimmick": "key", "name": "버퍼잠금", "field": "unlockTile"},
    "150": {"gimmick": "grass", "name": "풀"},
    "190": {"gimmick": "unknown", "name": "상자"},
    "240": {"gimmick": "curtain", "name": "커튼"},
    "290": {"gimmick": "bomb", "name": "폭탄"},
    "340": {"gimmick": "time_attack", "name": "타임어택", "field": "timea"},
    "390": {"gimmick": "frog", "name": "개구리"},
    "440": {"gimmick": "teleport", "name": "텔레포터"}
  }
}
```

---

## 8. 클라이언트 구현 가이드

### 8.1 레벨 데이터 필드 매핑

```typescript
interface LevelData {
  // 기본 필드
  obstacle_types?: string[];  // 장애물 기믹 (ice, link, chain, grass, unknown, curtain, bomb, frog, teleport)
  goals?: Goal[];             // 목표 기믹 (craft, stack)

  // 특수 기믹 필드
  unlockTile?: number;        // key 기믹: 버퍼 잠금 칸 수 (1, 2, 3...)
  timea?: number;             // time_attack 기믹: 제한 시간(초)
  timeAttack?: number;        // timea의 별칭
}
```

### 8.2 기믹별 클라이언트 처리

| 기믹 | 설정 필드 | 렌더링 | 상호작용 |
|------|-----------|--------|----------|
| craft | goals | 공예 목표 UI | 특정 방향 타일 수집 |
| stack | goals | 스택 목표 UI | 겹쳐진 타일 수집 |
| ice | obstacle_types | 얼음 레이어 | 인접 클리어 시 녹임 |
| link | obstacle_types | 연결선 표시 | 연결된 타일 동시 선택 |
| chain | obstacle_types | 체인 오버레이 | 인접 클리어 시 해제 |
| **key** | **unlockTile** | 버퍼 잠금 표시 | 열쇠 타일 3개 모으면 1칸 해제 |
| grass | obstacle_types | 풀 이미지 | 인접 클리어 시 제거 |
| unknown | obstacle_types | ? 마크 표시 | 상위 타일 제거 시 공개 |
| curtain | obstacle_types | 커튼 오버레이 | 탭 시 열림/닫힘 토글 |
| bomb | obstacle_types | 카운트다운 숫자 | 턴마다 감소, 0 시 폭발 |
| **time_attack** | **timea** | 타이머 UI | 시간 내 클리어 필요 |
| frog | obstacle_types | 개구리 스프라이트 | 매 턴 이동 애니메이션 |
| teleport | obstacle_types | 포탈 이펙트 | 클리어 시 위치 변경 |

### 8.3 Key 기믹 상세 구현

```typescript
// key 기믹 처리 예시
function processKeyGimmick(levelData: LevelData) {
  const lockedSlots = levelData.unlockTile || 0;

  if (lockedSlots > 0) {
    // 버퍼 슬롯 잠금
    lockBufferSlots(lockedSlots);

    // 열쇠 타일 생성 (잠금 칸당 3개)
    const keyTileCount = lockedSlots * 3;
    spawnKeyTiles(keyTileCount);
  }
}

// 열쇠 타일 수집 시
function onKeyTileCollected() {
  keyCount++;
  if (keyCount >= 3) {
    keyCount = 0;
    unlockOneBufferSlot();
  }
}
```

---

## 9. API 엔드포인트 참조

### 9.1 언락된 기믹 조회

```http
GET /api/leveling/unlocked-gimmicks/{level_number}
```

**응답 예시** (level_number=150):
```json
{
  "level_number": 150,
  "unlocked_gimmicks": ["craft", "stack", "ice", "link", "chain", "key", "grass"],
  "tutorial_gimmick": "grass",
  "gimmick_intro_phases": {
    "craft": "mastery",
    "stack": "mastery",
    "ice": "mastery",
    "link": "mastery",
    "chain": "mastery",
    "key": "integration",
    "grass": "tutorial"
  }
}
```

---

## 10. 레벨 생성 파라미터 요약

### 10.1 구간별 기믹 설정 (인게임 확정)

```
Stage   1-9   : 기믹 없음 (튜토리얼)
Stage  10-19  : craft만
Stage  20-29  : craft, stack
Stage  30-49  : craft, stack, ice
Stage  50-79  : craft, stack, ice, link
Stage  80-109 : +chain
Stage 110-149 : +key (unlockTile 필드)
Stage 150-189 : +grass
Stage 190-239 : +unknown
Stage 240-289 : +curtain
Stage 290-339 : +bomb
Stage 340-389 : +time_attack (timea 필드)
Stage 390-439 : +frog
Stage 440+    : 모든 기믹 (teleport 추가)
```

---

## 11. 부록: 레벨별 기믹 언락 함수 (의사코드)

```python
def get_unlocked_gimmicks(level_number: int) -> List[str]:
    """해당 레벨에서 사용 가능한 기믹 목록"""
    schedule = {
        "craft": 10, "stack": 20, "ice": 30, "link": 50,
        "chain": 80, "key": 110, "grass": 150, "unknown": 190,
        "curtain": 240, "bomb": 290, "time_attack": 340,
        "frog": 390, "teleport": 440
    }
    return [gimmick for gimmick, unlock in schedule.items()
            if unlock <= level_number]

def is_tutorial_level(level_number: int) -> Optional[str]:
    """튜토리얼 레벨이면 해당 기믹 반환, 아니면 None"""
    tutorial_levels = {
        10: "craft", 20: "stack", 30: "ice", 50: "link",
        80: "chain", 110: "key", 150: "grass", 190: "unknown",
        240: "curtain", 290: "bomb", 340: "time_attack",
        390: "frog", 440: "teleport"
    }
    return tutorial_levels.get(level_number)
```

---

## 12. 변경 이력

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| 1.0 | 2026-02-06 | 초안 작성 (11개 기믹) |
| 2.0 | 2026-02-06 | 인게임 확정 스펙 반영 |
| 3.0 | 2026-02-06 | Key, TimeAttack 기믹 추가 (13개) + 언락 레벨 조정 |

---

## 13. 연락처

- 레벨 생성 API: `/api/generate`, `/api/leveling` 엔드포인트
- 기믹 정의: `backend/app/models/gimmick_profile.py`
- 언락 설정: `backend/app/models/leveling_config.py`
