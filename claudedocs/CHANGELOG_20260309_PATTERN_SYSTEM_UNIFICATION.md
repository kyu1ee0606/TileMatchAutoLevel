# 패턴 시스템 통합 (2026-03-09)

## 개요

레벨 생성 시 사용되는 패턴 시스템을 **64개 aesthetic 패턴**으로 통합하고, 기존의 `geometric`/`clustered` 패턴 타입을 제거했습니다.

## 변경 사항

### 1. 패턴 타입 통합

**기존 (3가지 패턴 타입):**
| 패턴 타입 | 설명 | 문제점 |
|-----------|------|--------|
| `aesthetic` | 64개 정교한 패턴 (하트, 별, 문자 등) | - |
| `geometric` | 12개 랜덤 기하학 도형 | 불규칙한 모양, 명확한 형태 없음 |
| `clustered` | 클러스터 기반 랜덤 배치 | 불규칙한 모양 |

**변경 후 (1가지 패턴 타입):**
- 모든 레벨: `aesthetic` 패턴만 사용
- 64개 명확한 모양 중 하나 선택

### 2. 레벨 타입별 패턴 선택

| 레벨 타입 | 패턴 풀 | 예시 |
|-----------|---------|------|
| 보스 레벨 (x0) | `BOSS_PATTERNS` | ❤️ 하트, ⭐ 별, 🦋 나비, 🌸 꽃, 🌙 초승달 |
| 특수 레벨 (x9) | `SPECIAL_PATTERNS` | ✚ 십자가, ◎ 도넛, H/U/X 문자, ▲ 삼각형 |
| 일반 레벨 | 전체 64개 중 랜덤 | 모든 패턴 가능 |

### 3. 성능 개선

**기존 문제:**
- `pattern_index = undefined`일 때 백엔드에서 64개 패턴 모두 생성 후 스코어링
- 레벨당 6레이어 × 64패턴 = 384번 패턴 생성
- 1500레벨 배치 생성 시 ~2시간 소요

**해결:**
- 모든 레벨에 `pattern_index` 명시적 지정
- 레벨당 6레이어 × 1패턴 = 6번 패턴 생성
- **64배 성능 향상** → ~5분 소요

## 코드 변경

### 수정된 파일
- `frontend/src/components/ProductionDashboard/index.tsx`

### 수정 위치 (4곳)

1. **초기 생성** (line ~420)
```typescript
// 기존
const patternRoll = Math.random();
if (isEarlyLevel) {
  patternType = patternRoll < 0.50 ? 'geometric' : patternRoll < 0.90 ? 'aesthetic' : 'clustered';
} else if (isBossLevel) {
  patternType = patternRoll < 0.75 ? 'aesthetic' : ...
}

// 변경
const patternType: 'aesthetic' = 'aesthetic';
```

2. **레벨 검증 재생성** (line ~1125)
3. **handleRegenerateLevel** (line ~2542)
4. **batchRegenerateCore** (line ~2810)

## 64개 패턴 목록

### 기본 도형 (0-9)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 0 | Rectangle | ▢ |
| 1 | Diamond | ◇ |
| 2 | Oval | ⬭ |
| 3 | Cross | ✚ |
| 4 | Donut | ◎ |
| 5 | Concentric Diamond | ◈ |
| 6 | Corner Anchored | ⌗ |
| 7 | Hexagonal | ⬡ |
| 8 | Heart | ❤️ |
| 9 | T-Shape | ⊤ |

### 화살표 (10-14)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 10 | Arrow Up | ⬆️ |
| 11 | Arrow Down | ⬇️ |
| 12 | Arrow Left | ⬅️ |
| 13 | Arrow Right | ➡️ |
| 14 | Chevron | ⋀ |

### 별/천체 (15-19)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 15 | Star 5-pointed | ⭐ |
| 16 | Star 6-pointed | ✡️ |
| 17 | Crescent Moon | 🌙 |
| 18 | Sun Burst | ☀️ |
| 19 | Spiral | 🌀 |

### 문자 (20-29)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 20-29 | H, I, L, U, X, Y, Z, S, O, C | 알파벳 |

### 기하학 (30-39)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 30-31 | Triangle Up/Down | ▲▼ |
| 32-33 | Hourglass, Bowtie | ⧗⋈ |
| 34-35 | Stairs Asc/Desc | 📶📉 |
| 36-37 | Pyramid/Inverted | △▽ |
| 38-39 | Zigzag, Wave | ⚡〰️ |

### 프레임 (40-44)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 40-44 | Frame, Double Frame, Corner Triangles, Center Hollow, Window | ⬜⧈◢⬚⊞ |

### 예술 (45-49)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 45 | Butterfly | 🦋 |
| 46 | Flower | 🌸 |
| 47 | Scattered Islands | 🏝️ |
| 48 | Diagonal Stripes | ╱ |
| 49 | Honeycomb | 🍯 |

### 섬/브릿지 (50-55)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 50-55 | H-Bridge, V-Bridge, Triangle Islands, Grid Islands, Archipelago, Central Hub | ═║∴⊕🗾⊛ |

### GBoost (56-63)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 56-63 | Corner Blocks, Octagon Ring, Diagonal Staircase, Symmetric Wings, Scattered Clusters, Cross Bridge, Triple Bar, Frame with Center | ⌐⯃⤡🪽⁘╋☰⊡ |

### 레이어드 (64)
| Index | 이름 | 아이콘 |
|-------|------|--------|
| 64 | Nested Frames | 🔳 |

## 관련 상수

```typescript
// frontend/src/constants/patterns.ts

// 보스 레벨용 (화려한 패턴)
export const BOSS_PATTERNS = [8, 15, 16, 45, 46, 17, 18];
// 하트, 별5각, 별6각, 나비, 꽃, 초승달, 태양

// 특수 레벨용
export const SPECIAL_PATTERNS = [3, 4, 20, 23, 24, 30, 33];
// 십자가, 도넛, H, U, X, 삼각형, 나비넥타이

// 일반 레벨용 (전체 풀)
export const GENERAL_PATTERNS = [0-63 모두];
```

## 테스트 결과

- TypeScript 빌드: ✅ 통과
- 레벨 생성: ✅ 모든 레벨이 명확한 패턴 사용
- 성능: ✅ 1500레벨 생성 ~5분 (기존 ~2시간에서 개선)

## 제거된 기능

1. **geometric 패턴 타입** (12개 랜덤 도형)
   - Rectangle, Diamond, L-shape, T-shape, Cross, Donut
   - Zigzag, Diagonal, Corner cluster, Scattered, H-bar, V-bar

2. **clustered 패턴 타입** (클러스터 기반 랜덤 배치)

3. **패턴 타입 확률 선택 로직**
   - 기존: 레벨 타입별 geometric/aesthetic/clustered 확률
   - 변경: 모든 레벨 aesthetic 고정

---

## 64개 패턴 개선 (2026-03-09 추가)

### 수정된 패턴

| Index | 패턴명 | 변경 내용 |
|-------|--------|-----------|
| 4 | Donut | 테두리 굵기 1→2칸으로 증가 |
| 5 | Concentric Diamond | 채움→링 형태, 테두리 굵기 2칸 |
| 6 | Corner Only | 코너에만 스폰 (기존: 코너 제외 스폰) |
| 14 | Chevron | 굽은 테두리 굵기 2→3칸으로 증가 |
| 36 | Pyramid | 위아래로 더 길쭉하게 (세로 확장) |
| 37 | Inverted Pyramid | 위아래로 더 길쭉하게 (세로 확장) |

### 대체된 패턴

| Index | 기존 패턴 | 새 패턴 | 설명 |
|-------|-----------|---------|------|
| 54 | Archipelago (군도) | Corner + Center Circle | 4꼭짓점 + 중앙 원형 |
| 57 | Octagon Ring (팔각 링) | Corner + Center Square | 4꼭짓점 + 중앙 네모 |

### 코너 패턴 3종 (통합)

| Index | 패턴명 | 중앙 스폰 |
|-------|--------|-----------|
| 6 | Corner Anchored | 없음 (꼭짓점 연결) |
| 54 | Corner + Center Circle | 원형 ◉ |
| 57 | Corner + Center Square | 네모 ▣ |

---

## 패턴 6 (Corner Anchored) 추가 개선 (2026-03-09)

### 변경 내용

**기존:** 4꼭짓점에 삼각형만 배치 (꼭짓점 간 연결 없음)
```
###..###
##....##
#......#
........
........
#......#
##....##
###..###
```

**변경 후:** 4꼭짓점 삼각형 + 1타일 너비 브릿지로 연결
```
########  ← 상단: 코너 삼각형 + 1타일 브릿지
###..###
##....##
#......#  ← 좌우 1타일 브릿지
#......#
##....##
###..###
########  ← 하단: 코너 삼각형 + 1타일 브릿지
```

### 수정 파일

**1. `backend/app/core/pattern_templates.py`**
- Pattern 6 템플릿 업데이트 (small, medium6, medium, large)

**2. `backend/app/core/generator.py`**
- `corner_anchored()` 함수 수정
- 4꼭짓점 삼각형 생성 + 상/하/좌/우 1타일 브릿지 추가

### 코드 변경

```python
# generator.py - corner_anchored 함수

def corner_anchored():
    positions = []
    corner_size = max(2, min(cols, rows) // 3)

    # 1-4. 4꼭짓점 삼각형 (기존 로직 유지)
    # Top-left, Top-right, Bottom-left, Bottom-right triangles
    ...

    # 5. 꼭짓점 간 1타일 브릿지 추가 (신규)
    # Top edge (상단 연결)
    for x in range(corner_size, cols - corner_size):
        positions.append(f"{x}_0")

    # Bottom edge (하단 연결)
    for x in range(corner_size, cols - corner_size):
        positions.append(f"{x}_{rows - 1}")

    # Left edge (좌측 연결)
    for y in range(corner_size, rows - corner_size):
        positions.append(f"0_{y}")

    # Right edge (우측 연결)
    for y in range(corner_size, rows - corner_size):
        positions.append(f"{cols - 1}_{y}")

    return positions
```

### 템플릿 예시 (8x8 large)

```
########   ← row 0: 전체 연결
###..###   ← row 1: 코너 삼각형
##....##   ← row 2: 코너 삼각형
#......#   ← row 3-4: 좌우 1타일
#......#
##....##   ← row 5: 코너 삼각형
###..###   ← row 6: 코너 삼각형
########   ← row 7: 전체 연결
```

### 테스트 결과

- ✅ 8x8 그리드: 40개 타일 (코너 삼각형 + 브릿지)
- ✅ 7x7 그리드: 28개 타일
- ✅ 모든 레이어에서 연속된 형태 유지

---

## 패턴 다양성 개선 (2026-03-09)

### 문제점
- 후반 레벨로 갈수록 동일한 패턴 반복 → 단조로움
- 모든 레이어가 동일한 크기 → 시각적 깊이감 부족

### 해결: 옵션 B + D 적용

#### 옵션 B: 레이어별 크기 변화 (피라미드 효과)

**변경 전:**
```
Layer 0: 8x8 그리드 - ❤️ 하트 (100%)
Layer 1: 7x7 그리드 - ❤️ 하트 (100%)
Layer 2: 8x8 그리드 - ❤️ 하트 (100%)
Layer 3: 7x7 그리드 - ❤️ 하트 (100%)
```

**변경 후 (피라미드 효과):**
```
Layer 0: 8x8 그리드 - ❤️ 하트 (100%) - 41 타일
Layer 1: 7x7 그리드 - ❤️ 하트 (90%)  - 27 타일 (중앙 정렬)
Layer 2: 6x6 그리드 - ❤️ 하트 (81%)  - 27 타일 (중앙 정렬)
Layer 3: 5x5 그리드 - ❤️ 하트 (73%)  - 16 타일 (중앙 정렬)
```

**구현:**
```python
# backend/app/core/generator.py

# Shrink rate: 0.9 = 각 레이어가 이전의 90%
pyramid_shrink_rate = 0.9

# Layer 0: 100%, Layer 1: 90%, Layer 2: 81%, Layer 3: 73%
shrink_factor = pyramid_shrink_rate ** layer_idx
layer_cols = max(4, int(base_cols * shrink_factor))
layer_rows = max(4, int(base_rows * shrink_factor))

# 중앙 정렬 오프셋
layer_offset_x = (base_cols - layer_cols) // 2
layer_offset_y = (base_rows - layer_rows) // 2
```

#### 옵션 D: 연속 레벨 동일 패턴 방지

**변경 전:**
```
Level 100: ❤️ 하트
Level 101: ❤️ 하트 (우연히 같은 패턴)
Level 102: ⭐ 별
Level 103: ⭐ 별 (우연히 같은 패턴)
```

**변경 후:**
```
Level 100: ❤️ 하트
Level 101: ⭐ 별 (이전과 다른 패턴 보장)
Level 102: 🦋 나비 (이전과 다른 패턴 보장)
Level 103: ◇ 다이아몬드 (이전과 다른 패턴 보장)
```

**구현:**
```typescript
// frontend/src/components/ProductionDashboard/index.tsx

const preComputePatternIndices = (count: number, startLevelNumber: number): number[] => {
  const indices: number[] = [];
  let previousIndex = -1;

  for (let i = 0; i < count; i++) {
    // 레벨 타입에 맞는 패턴 풀 선택
    let pool = isBossLevel ? BOSS_PATTERNS : isSpecialShape ? SPECIAL_PATTERNS : [0..63];

    // 이전 패턴 제외
    if (previousIndex >= 0 && pool.length > 1) {
      pool = pool.filter(p => p !== previousIndex);
    }

    const selectedIndex = pool[Math.floor(Math.random() * pool.length)];
    indices.push(selectedIndex);
    previousIndex = selectedIndex;
  }

  return indices;
};
```

### 효과

| 항목 | 개선 전 | 개선 후 |
|------|---------|---------|
| 레이어 깊이감 | 모든 레이어 동일 크기 | 상위 레이어가 점점 작아지며 3D 효과 |
| 패턴 다양성 | 연속 동일 패턴 가능 | 연속 동일 패턴 방지 |
| 시각적 인지 | 패턴 겹쳐서 불분명 | 피라미드 효과로 패턴 명확히 보임 |
| 3배수 검증 | ✅ 유지 | ✅ 유지 (111 ÷ 3 = 37) |

### 수정된 파일

| 파일 | 변경 내용 |
|------|-----------|
| `backend/app/core/generator.py` | 피라미드 효과 (shrink_rate 0.9 적용) |
| `frontend/src/components/ProductionDashboard/index.tsx` | 연속 패턴 방지 로직 |
