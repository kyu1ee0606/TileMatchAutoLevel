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

  /**
   * Distribute tile type indices matching C# DistributeTiles().
   *
   * @param setLength - Number of tile sets (total t0 tiles / 3)
   * @param tileTypeCount - Number of tile types to use (useTileCount)
   * @param specifiedCount - Number of key tile (t16) sets
   * @param imbalanceSliderValue - Imbalance factor (0.0 = balanced, 1.0 = imbalanced)
   * @returns List of tile type indices (e.g., [1, 1, 1, 2, 2, 2, 3, ...])
   */
  static distributeTiles(
    setLength: number,
    tileTypeCount: number,
    specifiedCount: number = 0,
    imbalanceSliderValue: number = 0.0
  ): number[] {
    if (setLength <= 0 || tileTypeCount <= 0) {
      return [];
    }

    const specifiedIndex = TileDistributor.KEY_TILE_INDEX;

    // 1. Calculate non-specified total
    const nonSpecifiedTotal = setLength - specifiedCount;

    // 1-1. Allocate minimum 1 set per tile type
    const nonSpecifiedCounts = new Array(tileTypeCount).fill(1);

    // 2. Distribute remaining sets based on imbalance setting
    if (imbalanceSliderValue > 0) {
      // Imbalanced distribution
      let remainingSets = nonSpecifiedTotal - tileTypeCount;
      if (remainingSets > 0) {
        const baseCount = remainingSets / tileTypeCount;

        for (let i = 0; i < tileTypeCount; i++) {
          // Normalization factor: (2*i - (tileTypeCount-1)) / (tileTypeCount-1)
          let normalizationFactor = 0;
          if (tileTypeCount > 1) {
            normalizationFactor = (2 * i - (tileTypeCount - 1)) / (tileTypeCount - 1);
          }

          const calculatedSetCount = baseCount * (
            imbalanceSliderValue * TileDistributor.IMBALANCE_FACTOR * normalizationFactor
          );
          nonSpecifiedCounts[i] += Math.max(0, Math.round(calculatedSetCount));
        }
      }
    } else {
      // Balanced distribution (round-robin)
      let remainingSets = nonSpecifiedTotal - tileTypeCount;
      if (remainingSets > 0) {
        for (let i = 0; i < remainingSets; i++) {
          const targetIndex = i % tileTypeCount;
          nonSpecifiedCounts[targetIndex] += 1;
        }
      }
    }

    // 3. Adjust if total doesn't match
    let currentTotal = nonSpecifiedCounts.reduce((a, b) => a + b, 0);
    let difference = nonSpecifiedTotal - currentTotal;

    if (difference !== 0) {
      // Create indexed counts for sorting (matches C# adjustTiles - NOT updated in loop)
      const indexedCounts: Array<[number, number]> = nonSpecifiedCounts.map(
        (count, idx) => [count, idx]
      );

      for (let j = 0; j < Math.abs(difference); j++) {
        if (difference > 0) {
          // Add to tile with lowest count
          // C# uses OrderBy which doesn't modify original, so we copy and sort
          const sorted = [...indexedCounts].sort((a, b) => a[0] - b[0]);
          const minIdx = sorted[0][1];
          nonSpecifiedCounts[minIdx] += 1;
          // NOTE: C# doesn't update adjustTiles here, so we don't update indexedCounts
        } else {
          // Remove from tile with highest count
          // C# uses OrderByDescending which doesn't modify original, so we copy and sort
          const sorted = [...indexedCounts].sort((a, b) => b[0] - a[0]);
          const maxIdx = sorted[0][1];
          nonSpecifiedCounts[maxIdx] -= 1;
          // NOTE: C# doesn't update adjustTiles here, so we don't update indexedCounts
        }
      }
    }

    // 4. Generate final list (tile type indices)
    const resultList: number[] = [];
    for (let i = 0; i < nonSpecifiedCounts.length; i++) {
      const count = nonSpecifiedCounts[i];
      // Tile indices are 1-based (t1, t2, ..., t15)
      const tileIndex = i + 1;
      for (let j = 0; j < count; j++) {
        resultList.push(tileIndex);
      }
    }

    // Add specified (key tile) sets
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
   * Complete t0 tile assignment matching in-game logic.
   *
   * This is the main entry point that combines:
   * 1. GetToAddIndexList() - Balance existing tiles to multiples of 3
   * 2. DistributeTiles() - Generate tile type index list
   * 3. ShuffleEmptyTiles() - Shuffle tile positions
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
    existingTileCounts: Map<string, number> = new Map()
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

    // Generate tile type indices from DistributeTiles
    const typeIndices = TileDistributor.distributeTiles(
      setCount,
      useTileCount,
      unlockTile,
      imbalanceValue
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

    return shuffled;
  }
}
