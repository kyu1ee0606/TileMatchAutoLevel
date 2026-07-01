/**
 * zWellRandom - WELL512 Algorithm Port from Unity C#
 * Ported from: sp_template/Assets/09.zMyLib/zWellRandom.cs
 *
 * This ensures identical random sequences with the same seed as in-game.
 */
export class zWellRandom {
  private static readonly WELL512_STATE_SIZE = 16;

  private _state: number[];
  private _index: number;
  public curSeed: number;

  constructor(seed: number = 0) {
    this._state = new Array(zWellRandom.WELL512_STATE_SIZE).fill(0);
    this._index = 0;
    this.curSeed = 0;
    this.seed(seed);
  }

  /**
   * Initialize state array with seed (matches C# implementation).
   */
  seed(seed: number = 0): void {
    if (seed === 0) {
      seed = Date.now() >>> 0;
    }

    // Ensure seed is unsigned 32-bit
    seed = seed >>> 0;

    this._state[0] = seed;
    for (let i = 1; i < zWellRandom.WELL512_STATE_SIZE; i++) {
      const prev = this._state[i - 1];
      // Match C# arithmetic: 1812433253 * (prev ^ (prev >> 30)) + i
      // Use Math.imul for 32-bit multiplication
      const xored = prev ^ (prev >>> 30);
      this._state[i] = (Math.imul(1812433253, xored) + i) >>> 0;
    }

    this._index = 0;
    this.curSeed = seed;
  }

  /**
   * MAT0 helper function.
   */
  private _mat0(v: number, t: number): number {
    return (v ^ (v << t)) >>> 0;
  }

  /**
   * Generate next random uint32 (matches C# _rand()).
   */
  private _rand(): number {
    let a = this._state[this._index];
    let c = this._state[(this._index + 13) & 15];

    // b = a ^ c ^ (a << 16) ^ (c << 15)
    let b = (a ^ c ^ ((a << 16) >>> 0) ^ ((c << 15) >>> 0)) >>> 0;

    c = this._state[(this._index + 9) & 15];
    c = (c ^ (c >>> 11)) >>> 0;

    a = (b ^ c) >>> 0;
    this._state[this._index] = a;

    this._index = (this._index + 15) & 15;
    const z0 = this._state[this._index];

    // _state[_index] = MAT0(z0, 2) ^ MAT0(b, 18) ^ (c << 28) ^ (a ^ ((a << 5) & 0xDA442D24))
    const result = (
      this._mat0(z0, 2) ^
      this._mat0(b, 18) ^
      ((c << 28) >>> 0) ^
      (a ^ ((a << 5) & 0xDA442D24))
    ) >>> 0;

    this._state[this._index] = result;
    return result;
  }

  /**
   * Generate random int in range [s, e] (matches C# Rand()).
   * If e is default (-999999), range is [0, s-1] (matches C# behavior).
   */
  rand(s: number, e: number = -999999): number {
    if (e === -999999) {
      e = s - 1;
      s = 0;
    }

    const rangeSize = e - s + 1;
    if (rangeSize <= 0) {
      return 0;
    }

    return s + (this._rand() % rangeSize);
  }
}


/**
 * TileDistributor - t0 Tile Distribution Logic Port from Unity C#
 * Ported from: sp_template/Assets/08.Scripts/Tile_Script/InGame/DB_Level.cs
 * Functions: DistributeTiles(), ShuffleEmptyTiles()
 */
export class TileDistributor {
  private static readonly IMBALANCE_FACTOR = 3.0;  // 불균형 강도 (matches C#)
  private static readonly KEY_TILE_INDEX = 16;     // 키타일 인덱스

  private static readonly TILES_PER_COLOR = 3;

  /**
   * [v15.40] 색상 버킷 2단계 분배 - 인게임 DistributeTiles() 동기화
   *
   * 1단계: 색상 단위 분배 (용량 비례 + 불균형)
   * 2단계: 색상 내 타일 분배 (Fisher-Yates로 rnd 사용)
   *
   * @param setLength - Number of tile sets (total t0 tiles / 3)
   * @param tileTypeCount - Number of tile types to use (useTileCount, 1~15)
   * @param specifiedCount - Number of key tile (t16) sets
   * @param imbalance - Imbalance factor (0.0~1.0)
   * @param rnd - zWellRandom instance for deterministic Fisher-Yates
   * @returns List of tile type indices (e.g., [1, 1, 1, 4, 4, 4, 7, ...])
   */
  static distributeTiles(
    setLength: number,
    tileTypeCount: number,
    specifiedCount: number = 0,
    imbalance: number = 0.0,
    rnd?: zWellRandom
  ): number[] {
    if (setLength <= 0 || tileTypeCount <= 0) {
      return [];
    }

    const specifiedIndex = TileDistributor.KEY_TILE_INDEX;
    const nonSpecifiedTotal = setLength - specifiedCount;
    if (nonSpecifiedTotal <= 0) {
      return new Array(specifiedCount).fill(specifiedIndex);
    }

    const activeColors = Math.ceil(tileTypeCount / TileDistributor.TILES_PER_COLOR);

    // 색상별 용량 계산: ColorCapacity(c) = min(3, max(0, useTileCount - c*3))
    const colorCap: number[] = [];
    for (let c = 0; c < activeColors; c++) {
      colorCap.push(Math.min(3, Math.max(0, tileTypeCount - c * 3)));
    }

    // === 1단계: 색상 단위 분배 ===

    // 1-A: 용량 비례 base 분배
    const totalCap = colorCap.reduce((a, b) => a + b, 0);
    const colorSet: number[] = colorCap.map(cap =>
      Math.floor(nonSpecifiedTotal * cap / totalCap)
    );

    // 1-B: 나머지를 색상 인덱스 순으로 +1 (rnd 미사용)
    let remainder = nonSpecifiedTotal - colorSet.reduce((a, b) => a + b, 0);
    for (let c = 0; remainder > 0; c++) {
      colorSet[c % activeColors] += 1;
      remainder--;
    }

    // 1-C: 불균형 적용
    if (imbalance > 0 && activeColors > 1) {
      const baseShare = nonSpecifiedTotal / activeColors;
      for (let c = 0; c < activeColors; c++) {
        const normFactor = (2 * c - (activeColors - 1)) / (activeColors - 1);
        const delta = Math.round(baseShare * imbalance * TileDistributor.IMBALANCE_FACTOR * normFactor);
        colorSet[c] = Math.max(0, colorSet[c] + delta);
      }
      // 총합 재보정 (rnd 미사용)
      let diff = nonSpecifiedTotal - colorSet.reduce((a, b) => a + b, 0);
      while (diff !== 0) {
        if (diff > 0) {
          // 가장 적은 색상에 추가
          let minIdx = 0;
          for (let c = 1; c < activeColors; c++) {
            if (colorSet[c] < colorSet[minIdx]) minIdx = c;
          }
          colorSet[minIdx] += 1;
          diff--;
        } else {
          // 가장 많은 색상에서 제거
          let maxIdx = 0;
          for (let c = 1; c < activeColors; c++) {
            if (colorSet[c] > colorSet[maxIdx]) maxIdx = c;
          }
          colorSet[maxIdx] -= 1;
          diff++;
        }
      }
    }

    // === 2단계: 색상 내 타일 분배 ===
    const tilePerSlot: number[][] = [];
    for (let c = 0; c < activeColors; c++) {
      const cap = colorCap[c];
      const slots = new Array(3).fill(0);

      if (cap <= 0 || colorSet[c] <= 0) {
        tilePerSlot.push(slots);
        continue;
      }

      const quotient = Math.floor(colorSet[c] / cap);
      const rem = colorSet[c] % cap;

      for (let offset = 0; offset < cap; offset++) {
        slots[offset] = quotient;
      }

      // rem개를 rnd로 랜덤 offset에 +1 (Fisher-Yates)
      if (rem > 0 && cap > 1 && rnd) {
        const indices: number[] = [];
        for (let i = 0; i < cap; i++) indices.push(i);
        // Fisher-Yates shuffle (역순, rnd.rand(0, i) inclusive)
        for (let i = cap - 1; i >= 1; i--) {
          const j = rnd.rand(0, i);
          [indices[i], indices[j]] = [indices[j], indices[i]];
        }
        for (let k = 0; k < rem; k++) {
          slots[indices[k]] += 1;
        }
      } else if (rem > 0) {
        slots[0] += rem;
      }

      tilePerSlot.push(slots);
    }

    // === 3단계: 결과 리스트 생성 ===
    const resultList: number[] = [];
    for (let c = 0; c < activeColors; c++) {
      const cap = colorCap[c];
      for (let offset = 0; offset < cap; offset++) {
        const tileId = c * 3 + offset + 1; // 1-based
        for (let n = 0; n < tilePerSlot[c][offset]; n++) {
          resultList.push(tileId);
        }
      }
    }

    // 키타일(t16) 추가
    for (let i = 0; i < specifiedCount; i++) {
      resultList.push(specifiedIndex);
    }

    return resultList;
  }

  /**
   * Shuffle tile assignments matching C# ShuffleEmptyTiles() shuffle logic.
   *
   * @param assignments - List of tile type strings (e.g., ["t1", "t1", "t1", "t2", ...])
   * @param rng - zWellRandom instance (already seeded)
   * @param shuffleCount - Number of swap operations (emptyTileCount + xShuffleTile)
   * @returns Shuffled list of tile type strings
   */
  static shuffleTileAssignments(
    assignments: string[],
    rng: zWellRandom,
    shuffleCount: number
  ): string[] {
    if (!assignments || assignments.length === 0 || shuffleCount <= 0) {
      return assignments;
    }

    const result = [...assignments];
    const n = result.length;

    for (let i = 0; i < shuffleCount; i++) {
      const idx1 = rng.rand(0, n - 1);
      const idx2 = rng.rand(0, n - 1);

      // Swap
      [result[idx1], result[idx2]] = [result[idx2], result[idx1]];
    }

    return result;
  }

  /**
   * Get list of tile indices to add for balancing existing tiles to multiples of 3.
   * Matches C# GetToAddIndexList() logic.
   *
   * @param existingTileCounts - Map of tile type (e.g., "t1", "t2") to count
   * @returns List of tile indices (1-16) to add before random distribution
   */
  static getToAddIndexList(existingTileCounts: Map<string, number>): number[] {
    const toAddIndexList: number[] = [];

    // Check each tile type (t1-t15, key=t16)
    for (let tileIdx = 1; tileIdx <= 16; tileIdx++) {
      const tileType = tileIdx === 16 ? 'key' : `t${tileIdx}`;
      const count = existingTileCounts.get(tileType) || 0;

      if (count === 0) continue; // Skip tiles not used in level

      const oddCount = count % 3;
      if (oddCount !== 0) {
        // Add (3 - oddCount) tiles to make it divisible by 3
        const toAdd = 3 - oddCount;
        for (let j = 0; j < toAdd; j++) {
          toAddIndexList.push(tileIdx);
        }
      }
    }

    return toAddIndexList;
  }

  /**
   * [비주얼 타일 시드] ApplyVisualTileRemap 포트 — 인게임 DB_Level.ApplyVisualTileRemap() 동기화.
   *
   * 배치(그룹)는 고정한 채 t0 출신 타일의 스프라이트 인덱스(t1~t15)만 비주얼 시드로 재매핑.
   * 같은 로직 종류 = 같은 비주얼 인덱스(1:1 distinct) → 매칭 불변. 구체 시드면 인게임과 픽셀 일치.
   *
   * 알고리즘(인게임과 100% 동일해야 함):
   *   1) assignments에서 실제 사용 인덱스(1~15) 수집 → 오름차순 distinct (key/t16 제외)
   *   2) vSeed = seed<0 ? 0(런타임랜덤) : (seed+1)>>>0   // WELL512 seed 0(=시간기반) 회피
   *   3) pool=[1..15], 부분 Fisher-Yates로 usedTypes.length개 distinct 선택 (rand(i,14) inclusive)
   *   4) map[usedTypes[k]] = pool[k]
   *   5) assignments의 "t{1..15}"만 "t{map[id]}"로 재기록 (key/스택/크래프트 무관)
   *
   * @param assignments - 배치 완료된 타일 타입 문자열 배열 (예: ["t3","t1","key",...])
   * @param visualTileSeed - 비주얼 시드 (>=0 결정적 / <0 런타임랜덤)
   * @returns 비주얼 인덱스 재매핑된 배열
   */
  static applyVisualTileRemap(assignments: string[], visualTileSeed: number): string[] {
    const POOL = 15;
    if (!assignments || assignments.length === 0) return assignments;

    // 1) 사용 인덱스(1~15) → 오름차순 distinct
    const present = new Array(POOL + 1).fill(false);
    for (const a of assignments) {
      const m = /^t(\d+)$/.exec(a);
      if (m) {
        const id = parseInt(m[1], 10);
        if (id >= 1 && id <= POOL) present[id] = true;
      }
    }
    const usedTypes: number[] = [];
    for (let v = 1; v <= POOL; v++) if (present[v]) usedTypes.push(v);
    if (usedTypes.length === 0) return assignments;

    // 2) 비주얼 RNG (배치 rnd와 독립)
    const vSeed = visualTileSeed < 0 ? 0 : (visualTileSeed + 1) >>> 0;
    const vrnd = new zWellRandom(vSeed);

    // 3) pool=[1..15], 부분 Fisher-Yates
    const pool: number[] = [];
    for (let i = 0; i < POOL; i++) pool.push(i + 1);
    const n = usedTypes.length;
    for (let i = 0; i < n; i++) {
      const j = vrnd.rand(i, POOL - 1); // inclusive [i, 14]
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }

    // 4) 1:1 매핑
    const map = new Array(POOL + 1).fill(0);
    for (let k = 0; k < n; k++) map[usedTypes[k]] = pool[k];

    // 5) 재기록
    return assignments.map(a => {
      const m = /^t(\d+)$/.exec(a);
      if (m) {
        const id = parseInt(m[1], 10);
        if (id >= 1 && id <= POOL) return `t${map[id]}`;
      }
      return a;
    });
  }

  /**
   * Complete t0 tile assignment matching in-game logic.
   *
   * This is the main entry point that combines:
   * 1. GetToAddIndexList() - Balance existing tiles to multiples of 3
   * 2. DistributeTiles() - Generate tile type index list
   * 3. ShuffleEmptyTiles() - Shuffle tile positions
   * 4. ApplyVisualTileRemap() - 비주얼 시드 있으면 스프라이트 인덱스 재매핑
   *
   * @param t0Count - Total number of t0 tiles to assign
   * @param useTileCount - Number of tile types (useTileCount from level JSON)
   * @param randSeed - Random seed (randSeed from level JSON)
   * @param shuffleTile - Additional shuffle count (xShuffleTile from level, default 0)
   * @param typeImbalance - Imbalance setting (xTypeImbalance from level, 0-10)
   * @param unlockTile - Number of key tile sets (xUnlockTile from level)
   * @param tileTypeOffset - Offset to add to tile type indices (e.g., 10 for t11~t15)
   * @param existingTileCounts - Map of existing tile counts for toAddIndexList calculation
   * @returns List of tile type strings in shuffled order (e.g., ["t3", "t1", "t2", ...])
   */
  static assignT0Tiles(
    t0Count: number,
    useTileCount: number,
    randSeed: number,
    shuffleTile: number = 0,
    typeImbalance: number = 0,
    unlockTile: number = 0,
    tileTypeOffset: number = 0,
    existingTileCounts: Map<string, number> = new Map(),
    visualTileSeed?: number | null
  ): string[] {
    if (t0Count <= 0 || useTileCount <= 0) {
      return [];
    }

    // Initialize zWellRandom with seed
    const rng = new zWellRandom(randSeed > 0 ? randSeed : 0);

    // Calculate set count (3 tiles per set)
    const setCount = Math.floor(t0Count / 3);

    // Imbalance slider value (0.0 - 1.0)
    const imbalanceValue = typeImbalance / 10.0;

    // [v15.40] Generate tile type indices with color-balanced distribution
    // rng를 전달하여 색상 내 Fisher-Yates 셔플이 인게임과 동일한 시드로 동작
    const typeIndices = TileDistributor.distributeTiles(
      setCount,
      useTileCount,
      unlockTile,
      imbalanceValue,
      rng
    );

    // Get toAddIndexList for balancing existing tiles (C# GetToAddIndexList)
    const toAddIndexList = TileDistributor.getToAddIndexList(existingTileCounts);

    console.log(`[assignT0Tiles] toAddIndexList:`, toAddIndexList);
    console.log(`[assignT0Tiles] typeIndices:`, typeIndices);

    // Convert to tile type strings using C# assignment logic:
    // 1. First consume toAddIndexList
    // 2. Then use curIndex = setCount / 3 for typeIndices
    const assignments: string[] = [];
    let toAddIdx = 0;
    let assignSetCount = 0;

    for (let i = 0; i < t0Count; i++) {
      let tileType: string;

      if (toAddIdx < toAddIndexList.length) {
        // First consume toAddIndexList
        const typeIdx = toAddIndexList[toAddIdx];
        toAddIdx++;
        if (typeIdx === TileDistributor.KEY_TILE_INDEX) {
          tileType = "key";
        } else {
          tileType = `t${typeIdx + tileTypeOffset}`;
        }
      } else {
        // Then use typeIndices with curIndex = setCount / 3
        const curIndex = Math.floor(assignSetCount / 3);
        assignSetCount++;

        if (curIndex < typeIndices.length) {
          const typeIdx = typeIndices[curIndex];
          if (typeIdx === TileDistributor.KEY_TILE_INDEX) {
            tileType = "key";
          } else {
            tileType = `t${typeIdx + tileTypeOffset}`;
          }
        } else {
          // Fallback: use last type or t1
          tileType = `t${1 + tileTypeOffset}`;
        }
      }

      assignments.push(tileType);
    }

    console.log(`[assignT0Tiles] Before shuffle:`, assignments);

    // Shuffle tile positions
    const shuffleCount = t0Count + shuffleTile;
    const shuffled = TileDistributor.shuffleTileAssignments(assignments, rng, shuffleCount);

    // [비주얼 타일 시드] 배치 rng 소비 완료 후 별도 RNG로 스프라이트 인덱스만 재매핑 (필드 없으면 현행)
    if (visualTileSeed !== null && visualTileSeed !== undefined) {
      return TileDistributor.applyVisualTileRemap(shuffled, visualTileSeed);
    }

    return shuffled;
  }
}
