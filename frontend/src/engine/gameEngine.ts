/**
 * TileMatch Game Engine
 *
 * 백엔드 bot_simulator.py와 완전히 동일한 게임 규칙 구현
 * - 7슬롯 덱 시스템
 * - 3타일 연속 매칭 (3개씩만 제거)
 * - 레이어 블로킹 (layer_cols 기반)
 * - 기믹 시스템 (ice, chain, grass, link, frog, bomb, curtain, teleport)
 */

// ==================== 타입 정의 ====================

export enum TileEffectType {
  NONE = 'none',
  ICE = 'ice',
  CHAIN = 'chain',
  GRASS = 'grass',
  LINK_EAST = 'link_e',
  LINK_WEST = 'link_w',
  LINK_SOUTH = 'link_s',
  LINK_NORTH = 'link_n',
  FROG = 'frog',
  BOMB = 'bomb',
  CURTAIN = 'curtain',
  TELEPORT = 'teleport',
  UNKNOWN = 'unknown',
  CRAFT = 'craft',
  STACK_NORTH = 'stack_n',
  STACK_SOUTH = 'stack_s',
  STACK_EAST = 'stack_e',
  STACK_WEST = 'stack_w',
}

export interface TileEffectData {
  remaining?: number;      // ice, grass, bomb
  unlocked?: boolean;      // chain
  canPick?: boolean;       // link
  linkedPos?: string;      // link
  isOpen?: boolean;        // curtain
  onFrog?: boolean;        // frog가 위에 있는지
}

export interface TileState {
  tileType: string;
  layerIdx: number;
  xIdx: number;
  yIdx: number;
  effectType: TileEffectType;
  effectData: TileEffectData;
  picked: boolean;

  // Stack/Craft 타일 관련
  isStackTile: boolean;
  isCraftTile: boolean;
  isCrafted: boolean;
  stackIndex: number;
  stackMaxIndex: number;
  upperStackedTileKey: string | null;
  underStackedTileKey: string | null;
  rootStackedTileKey: string | null;
  craftDirection: string;
  originGoalType: string;
}

export interface GameState {
  tiles: Map<number, Map<string, TileState>>;  // layerIdx -> posKey -> TileState
  layerCols: Map<number, number>;              // layerIdx -> col count
  dockTiles: TileState[];
  goalsRemaining: Map<string, number>;
  movesUsed: number;
  cleared: boolean;
  failed: boolean;
  maxMoves: number;
  maxDockSlots: number;

  // 기믹 추적
  linkPairs: Map<string, string>;
  frogPositions: Set<string>;
  bombTiles: Map<string, number>;
  curtainTiles: Map<string, boolean>;
  iceTiles: Map<string, number>;
  stackedTiles: Map<string, TileState>;
  craftBoxes: Map<string, string[]>;
  teleportClickCount: number;
  teleportTiles: Array<[number, string]>;

  // 캐시
  maxLayerIdx: number;
}

export interface Move {
  layerIdx: number;
  position: string;
  tileType: string;
  tileState: TileState | null;
  willMatch: boolean;
  linkedTiles: Array<[number, string]>;
}

// ==================== 상수 ====================

const MATCHABLE_TYPES = new Set([
  't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8',
  't9', 't10', 't11', 't12', 't13', 't14', 't15', 't16'
]);

const EFFECT_MAPPING: Record<string, TileEffectType> = {
  'ice': TileEffectType.ICE,
  'chain': TileEffectType.CHAIN,
  'grass': TileEffectType.GRASS,
  'link_e': TileEffectType.LINK_EAST,
  'link_w': TileEffectType.LINK_WEST,
  'link_s': TileEffectType.LINK_SOUTH,
  'link_n': TileEffectType.LINK_NORTH,
  'frog': TileEffectType.FROG,
  'bomb': TileEffectType.BOMB,
  'curtain': TileEffectType.CURTAIN,
  'curtain_close': TileEffectType.CURTAIN,
  'curtain_open': TileEffectType.CURTAIN,
  'teleport': TileEffectType.TELEPORT,
  'unknown': TileEffectType.UNKNOWN,
  'craft': TileEffectType.CRAFT,
  'stack_n': TileEffectType.STACK_NORTH,
  'stack_s': TileEffectType.STACK_SOUTH,
  'stack_e': TileEffectType.STACK_EAST,
  'stack_w': TileEffectType.STACK_WEST,
};

// 레이어 블로킹 오프셋 (백엔드와 동일)
const BLOCKING_OFFSETS_SAME_PARITY: [number, number][] = [[0, 0]];
const BLOCKING_OFFSETS_UPPER_BIGGER: [number, number][] = [[0, 0], [1, 0], [0, 1], [1, 1]];
const BLOCKING_OFFSETS_UPPER_SMALLER: [number, number][] = [[-1, -1], [0, -1], [-1, 0], [0, 0]];

// ==================== 유틸리티 함수 ====================

function createTileState(partial: Partial<TileState>): TileState {
  return {
    tileType: partial.tileType || 't0',
    layerIdx: partial.layerIdx || 0,
    xIdx: partial.xIdx || 0,
    yIdx: partial.yIdx || 0,
    effectType: partial.effectType || TileEffectType.NONE,
    effectData: partial.effectData || {},
    picked: partial.picked || false,
    isStackTile: partial.isStackTile || false,
    isCraftTile: partial.isCraftTile || false,
    isCrafted: partial.isCrafted || false,
    stackIndex: partial.stackIndex ?? -1,
    stackMaxIndex: partial.stackMaxIndex ?? -1,
    upperStackedTileKey: partial.upperStackedTileKey || null,
    underStackedTileKey: partial.underStackedTileKey || null,
    rootStackedTileKey: partial.rootStackedTileKey || null,
    craftDirection: partial.craftDirection || '',
    originGoalType: partial.originGoalType || '',
  };
}

function getPositionKey(x: number, y: number): string {
  return `${x}_${y}`;
}

function getFullKey(tile: TileState): string {
  if (tile.stackIndex >= 0) {
    return `${tile.layerIdx}_${tile.xIdx}_${tile.yIdx}_${tile.stackIndex}`;
  }
  return `${tile.layerIdx}_${tile.xIdx}_${tile.yIdx}`;
}

// ==================== 게임 엔진 클래스 ====================

export class GameEngine {
  private state: GameState;

  constructor() {
    this.state = this.createEmptyState();
  }

  private createEmptyState(): GameState {
    return {
      tiles: new Map(),
      layerCols: new Map(),
      dockTiles: [],
      goalsRemaining: new Map(),
      movesUsed: 0,
      cleared: false,
      failed: false,
      maxMoves: 50,
      maxDockSlots: 7,
      linkPairs: new Map(),
      frogPositions: new Set(),
      bombTiles: new Map(),
      curtainTiles: new Map(),
      iceTiles: new Map(),
      stackedTiles: new Map(),
      craftBoxes: new Map(),
      teleportClickCount: 0,
      teleportTiles: [],
      maxLayerIdx: -1,
    };
  }

  /**
   * 레벨 JSON으로 게임 상태 초기화
   */
  initializeFromLevel(levelJson: Record<string, unknown>): void {
    this.state = this.createEmptyState();

    const numLayers = typeof levelJson.layer === 'number'
      ? levelJson.layer
      : parseInt(String(levelJson.layer || '8'), 10);

    this.state.maxMoves = typeof levelJson.max_moves === 'number'
      ? levelJson.max_moves
      : 50;

    // 레이어별 타일 파싱
    for (let layerIdx = 0; layerIdx < numLayers; layerIdx++) {
      const layerKey = `layer_${layerIdx}`;
      const layerData = levelJson[layerKey] as Record<string, unknown> | undefined;

      if (!layerData) continue;

      // 레이어 col 저장
      const layerCol = typeof layerData.col === 'number' ? layerData.col : 7;
      this.state.layerCols.set(layerIdx, layerCol);

      const tilesData = layerData.tiles as Record<string, unknown[]> | undefined;
      if (!tilesData) continue;

      if (!this.state.tiles.has(layerIdx)) {
        this.state.tiles.set(layerIdx, new Map());
      }
      const layerTiles = this.state.tiles.get(layerIdx)!;

      for (const [pos, tileData] of Object.entries(tilesData)) {
        if (!Array.isArray(tileData) || tileData.length === 0) continue;

        const [rowStr, colStr] = pos.split('_');
        const xIdx = parseInt(rowStr, 10);
        const yIdx = parseInt(colStr, 10);

        const tileType = String(tileData[0] || 't0');
        const effectStr = String(tileData[1] || '');
        const extraData = tileData[2];

        // 기믹 타입 파싱
        let effectType = TileEffectType.NONE;
        const effectData: TileEffectData = {};

        if (effectStr) {
          effectType = EFFECT_MAPPING[effectStr] || TileEffectType.NONE;

          // 기믹별 데이터 초기화
          switch (effectType) {
            case TileEffectType.ICE:
              effectData.remaining = 3;
              this.state.iceTiles.set(`${layerIdx}_${pos}`, 3);
              break;

            case TileEffectType.CHAIN:
              effectData.unlocked = false;
              break;

            case TileEffectType.GRASS:
              effectData.remaining = 1;
              break;

            case TileEffectType.LINK_EAST:
            case TileEffectType.LINK_WEST:
            case TileEffectType.LINK_SOUTH:
            case TileEffectType.LINK_NORTH:
              effectData.canPick = false;
              // 링크 대상 위치 계산
              let linkedX = xIdx, linkedY = yIdx;
              if (effectType === TileEffectType.LINK_EAST) linkedX += 1;
              else if (effectType === TileEffectType.LINK_WEST) linkedX -= 1;
              else if (effectType === TileEffectType.LINK_SOUTH) linkedY += 1;
              else if (effectType === TileEffectType.LINK_NORTH) linkedY -= 1;
              effectData.linkedPos = getPositionKey(linkedX, linkedY);
              break;

            case TileEffectType.FROG:
              this.state.frogPositions.add(`${layerIdx}_${pos}`);
              break;

            case TileEffectType.BOMB:
              const bombCount = typeof extraData === 'number' ? extraData : 3;
              effectData.remaining = Math.max(3, Math.min(5, bombCount));
              this.state.bombTiles.set(`${layerIdx}_${pos}`, effectData.remaining);
              break;

            case TileEffectType.CURTAIN:
              effectData.isOpen = effectStr.includes('open');
              this.state.curtainTiles.set(`${layerIdx}_${pos}`, effectData.isOpen);
              break;

            case TileEffectType.TELEPORT:
              this.state.teleportTiles.push([layerIdx, pos]);
              break;
          }
        }

        const tile = createTileState({
          tileType,
          layerIdx,
          xIdx,
          yIdx,
          effectType,
          effectData,
        });

        layerTiles.set(pos, tile);
      }
    }

    // max layer 캐시
    this.state.maxLayerIdx = Math.max(...Array.from(this.state.tiles.keys()), -1);

    // 링크 타일 상태 업데이트
    this.updateLinkTilesStatus();

    // 목표 로드
    const goalCount = levelJson.goalCount as Record<string, number> | undefined;
    if (goalCount) {
      for (const [key, count] of Object.entries(goalCount)) {
        this.state.goalsRemaining.set(key, count);
      }
    }
  }

  /**
   * 타일이 선택 가능한지 확인 (기믹 효과 기반)
   */
  canPickTile(tile: TileState): boolean {
    if (tile.picked) return false;

    // Frog가 위에 있으면 선택 불가
    if (tile.effectData.onFrog) return false;

    switch (tile.effectType) {
      case TileEffectType.ICE:
        return (tile.effectData.remaining || 0) <= 0;

      case TileEffectType.CHAIN:
        return tile.effectData.unlocked === true;

      case TileEffectType.GRASS:
        return (tile.effectData.remaining || 0) <= 0;

      case TileEffectType.LINK_EAST:
      case TileEffectType.LINK_WEST:
      case TileEffectType.LINK_SOUTH:
      case TileEffectType.LINK_NORTH:
        return tile.effectData.canPick === true;

      case TileEffectType.CURTAIN:
        return tile.effectData.isOpen === true;

      default:
        return true;
    }
  }

  /**
   * 타일이 상위 레이어에 의해 막혀있는지 확인
   * 백엔드 _is_blocked_by_upper와 동일한 로직
   */
  isBlockedByUpper(tile: TileState): boolean {
    if (tile.layerIdx >= this.state.maxLayerIdx) return false;

    const tileParity = tile.layerIdx % 2;
    const curLayerCol = this.state.layerCols.get(tile.layerIdx) || 7;

    for (let upperLayerIdx = tile.layerIdx + 1; upperLayerIdx <= this.state.maxLayerIdx; upperLayerIdx++) {
      const layer = this.state.tiles.get(upperLayerIdx);
      if (!layer) continue;

      const upperParity = upperLayerIdx % 2;
      const upperLayerCol = this.state.layerCols.get(upperLayerIdx) || 7;

      // 패리티와 레이어 크기에 따른 블로킹 오프셋 결정
      let blockingOffsets: [number, number][];

      if (tileParity === upperParity) {
        // 같은 패리티: 같은 위치만 확인
        blockingOffsets = BLOCKING_OFFSETS_SAME_PARITY;
      } else {
        // 다른 패리티: 레이어 col 비교
        if (upperLayerCol > curLayerCol) {
          blockingOffsets = BLOCKING_OFFSETS_UPPER_BIGGER;
        } else {
          blockingOffsets = BLOCKING_OFFSETS_UPPER_SMALLER;
        }
      }

      for (const [dx, dy] of blockingOffsets) {
        const bx = tile.xIdx + dx;
        const by = tile.yIdx + dy;
        const posKey = getPositionKey(bx, by);
        const upperTile = layer.get(posKey);

        if (upperTile && !upperTile.picked) {
          return true;
        }
      }
    }

    return false;
  }

  /**
   * 선택 가능한 모든 타일 가져오기
   */
  getAvailableMoves(): Move[] {
    const moves: Move[] = [];

    // 덱의 타일 타입별 개수 계산
    const dockTypeCounts = new Map<string, number>();
    for (const tile of this.state.dockTiles) {
      dockTypeCounts.set(tile.tileType, (dockTypeCounts.get(tile.tileType) || 0) + 1);
    }

    // 모든 레이어 순회
    for (const [layerIdx, layerTiles] of this.state.tiles) {
      for (const [pos, tile] of layerTiles) {
        if (tile.picked) continue;
        if (!MATCHABLE_TYPES.has(tile.tileType)) continue;

        // 기믹 효과로 선택 불가능한지 확인
        if (!this.canPickTile(tile)) continue;

        // 상위 레이어에 의해 막혀있는지 확인
        if (this.isBlockedByUpper(tile)) continue;

        // 스택 타일 블로킹 확인
        if (tile.isStackTile && this.isStackBlocked(tile)) continue;

        // 링크 타일 찾기
        const linkedTiles = this.findLinkedTiles(tile);

        // 매치 정보 계산
        const dockCount = dockTypeCounts.get(tile.tileType) || 0;
        const willMatch = dockCount >= 2;

        moves.push({
          layerIdx,
          position: pos,
          tileType: tile.tileType,
          tileState: tile,
          willMatch,
          linkedTiles,
        });
      }
    }

    return moves;
  }

  /**
   * 스택 타일이 위의 타일에 의해 막혀있는지 확인
   */
  private isStackBlocked(tile: TileState): boolean {
    if (!tile.isStackTile) return false;

    if (tile.upperStackedTileKey) {
      const upperTile = this.state.stackedTiles.get(tile.upperStackedTileKey);
      if (upperTile && !upperTile.picked) {
        return true;
      }
    }
    return false;
  }

  /**
   * 링크된 타일 찾기
   */
  private findLinkedTiles(tile: TileState): Array<[number, string]> {
    const linked: Array<[number, string]> = [];

    if (tile.effectType === TileEffectType.LINK_EAST ||
        tile.effectType === TileEffectType.LINK_WEST ||
        tile.effectType === TileEffectType.LINK_SOUTH ||
        tile.effectType === TileEffectType.LINK_NORTH) {
      const linkedPos = tile.effectData.linkedPos;
      if (linkedPos) {
        linked.push([tile.layerIdx, linkedPos]);
      }
    }

    return linked;
  }

  /**
   * 타일 선택 (클릭) 처리
   */
  selectTile(layerIdx: number, position: string): boolean {
    const layer = this.state.tiles.get(layerIdx);
    if (!layer) return false;

    const tile = layer.get(position);
    if (!tile || tile.picked) return false;

    // 선택 가능 여부 확인
    if (!this.canPickTile(tile)) return false;
    if (this.isBlockedByUpper(tile)) return false;
    if (tile.isStackTile && this.isStackBlocked(tile)) return false;

    // 덱이 가득 찼는지 확인
    if (this.state.dockTiles.length >= this.state.maxDockSlots) return false;

    // 선택 전 노출된 얼음 타일 수집 (백엔드 로직과 동일)
    const unblockedIceBeforePick = new Set<string>();
    for (const [iceKey, remaining] of this.state.iceTiles) {
      if (remaining <= 0) continue;
      const parts = iceKey.split('_');
      if (parts.length >= 3) {
        const lIdx = parseInt(parts[0], 10);
        const posKey = `${parts[1]}_${parts[2]}`;
        const layerTiles = this.state.tiles.get(lIdx);
        const iceTile = layerTiles?.get(posKey);
        if (iceTile && !iceTile.picked && !this.isBlockedByUpper(iceTile)) {
          unblockedIceBeforePick.add(`${lIdx}_${posKey}`);
        }
      }
    }

    // 링크된 타일 찾기
    let linkedTile: TileState | null = null;
    if (tile.effectType === TileEffectType.LINK_EAST ||
        tile.effectType === TileEffectType.LINK_WEST ||
        tile.effectType === TileEffectType.LINK_SOUTH ||
        tile.effectType === TileEffectType.LINK_NORTH) {
      const linkedPos = tile.effectData.linkedPos;
      if (linkedPos) {
        linkedTile = layer.get(linkedPos) || null;
      }
    } else {
      // 역방향 링크 확인
      for (const [, t] of layer) {
        if (t.picked) continue;
        if (t.effectData.linkedPos === position) {
          linkedTile = t;
          break;
        }
      }
    }

    // 타일 선택 처리
    tile.picked = true;

    // 폭탄 제거
    if (tile.effectType === TileEffectType.BOMB) {
      this.state.bombTiles.delete(`${layerIdx}_${position}`);
    }

    // 덱에 추가 (같은 타입끼리 그룹화)
    this.addToDock(tile);

    // 링크된 타일도 선택
    if (linkedTile && !linkedTile.picked) {
      linkedTile.picked = true;
      this.addToDock(linkedTile);
      this.updateAdjacentEffects(linkedTile, unblockedIceBeforePick);
    }

    // 인접 타일 효과 업데이트
    this.updateAdjacentEffects(tile, unblockedIceBeforePick);

    // 덱 매칭 처리 (3개씩만 제거 - 백엔드와 동일)
    this.processDockMatches();

    // 이동 횟수 증가
    this.state.movesUsed++;

    // 게임 상태 확인
    this.checkGameState();

    // 링크 타일 상태 업데이트
    this.updateLinkTilesStatus();

    return true;
  }

  /**
   * 덱에 타일 추가 (같은 타입끼리 그룹화)
   */
  private addToDock(tile: TileState): void {
    // 같은 타입의 타일 그룹 끝 찾기
    let insertIndex = this.state.dockTiles.length;

    for (let i = 0; i < this.state.dockTiles.length; i++) {
      if (this.state.dockTiles[i].tileType === tile.tileType) {
        // 그룹 끝 찾기
        let endOfGroup = i;
        while (endOfGroup < this.state.dockTiles.length &&
               this.state.dockTiles[endOfGroup].tileType === tile.tileType) {
          endOfGroup++;
        }
        insertIndex = endOfGroup;
        break;
      }
    }

    this.state.dockTiles.splice(insertIndex, 0, tile);
  }

  /**
   * 덱 매칭 처리 - 백엔드와 동일하게 3개씩만 제거
   */
  private processDockMatches(): Map<string, number> {
    const clearedByType = new Map<string, number>();

    // 타입별 타일 그룹화
    const typeGroups = new Map<string, TileState[]>();
    for (const tile of this.state.dockTiles) {
      if (!typeGroups.has(tile.tileType)) {
        typeGroups.set(tile.tileType, []);
      }
      typeGroups.get(tile.tileType)!.push(tile);
    }

    // 3개 이상인 그룹 제거 (한 번에 3개씩만!)
    for (const [tileType, tiles] of typeGroups) {
      while (tiles.length >= 3) {
        // 3개만 제거
        for (let i = 0; i < 3; i++) {
          const removed = tiles.shift()!;
          const idx = this.state.dockTiles.indexOf(removed);
          if (idx >= 0) {
            this.state.dockTiles.splice(idx, 1);
          }
          clearedByType.set(tileType, (clearedByType.get(tileType) || 0) + 1);

          // 골 감소
          if (removed.isCraftTile && removed.originGoalType) {
            const goalKey = removed.originGoalType;
            if (this.state.goalsRemaining.has(goalKey)) {
              this.state.goalsRemaining.set(
                goalKey,
                Math.max(0, this.state.goalsRemaining.get(goalKey)! - 1)
              );
            }
          }
        }
      }
    }

    return clearedByType;
  }

  /**
   * 인접 타일 효과 업데이트 (얼음, 체인, 잔디)
   */
  private updateAdjacentEffects(pickedTile: TileState, unblockedIceBeforePick: Set<string>): void {
    const x = pickedTile.xIdx;
    const y = pickedTile.yIdx;
    const layerIdx = pickedTile.layerIdx;

    // 얼음 처리: 선택 전에 이미 노출된 얼음만 녹음
    for (const [lIdx, layerTiles] of this.state.tiles) {
      for (const [posKey, tile] of layerTiles) {
        if (tile.picked) continue;

        if (tile.effectType === TileEffectType.ICE) {
          if (unblockedIceBeforePick.has(`${lIdx}_${posKey}`)) {
            const remaining = tile.effectData.remaining || 0;
            if (remaining > 0) {
              tile.effectData.remaining = remaining - 1;
              this.state.iceTiles.set(`${lIdx}_${posKey}`, remaining - 1);
            }
          }
        }
      }
    }

    // 인접 위치 (4방향)
    const adjacentPositions: [number, number][] = [
      [x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]
    ];

    const layer = this.state.tiles.get(layerIdx);
    if (!layer) return;

    for (const [adjX, adjY] of adjacentPositions) {
      const posKey = getPositionKey(adjX, adjY);
      const adjTile = layer.get(posKey);
      if (!adjTile || adjTile.picked) continue;

      // 잔디 효과
      if (adjTile.effectType === TileEffectType.GRASS) {
        if (!this.isBlockedByUpper(adjTile)) {
          const remaining = adjTile.effectData.remaining || 0;
          if (remaining > 0) {
            adjTile.effectData.remaining = remaining - 1;
          }
        }
      }
    }

    // 체인: 수평 인접만
    const horizontalPositions: [number, number][] = [[x + 1, y], [x - 1, y]];

    for (const [adjX, adjY] of horizontalPositions) {
      const posKey = getPositionKey(adjX, adjY);
      const adjTile = layer.get(posKey);
      if (!adjTile || adjTile.picked) continue;

      if (adjTile.effectType === TileEffectType.CHAIN) {
        adjTile.effectData.unlocked = true;
      }
    }
  }

  /**
   * 링크 타일 상태 업데이트
   */
  private updateLinkTilesStatus(): void {
    for (const [, layerTiles] of this.state.tiles) {
      for (const [, tile] of layerTiles) {
        if (tile.picked) continue;

        if (tile.effectType === TileEffectType.LINK_EAST ||
            tile.effectType === TileEffectType.LINK_WEST ||
            tile.effectType === TileEffectType.LINK_SOUTH ||
            tile.effectType === TileEffectType.LINK_NORTH) {
          const linkedPos = tile.effectData.linkedPos;

          const linkedTile = layerTiles.get(linkedPos || '');

          if (!linkedTile || linkedTile.picked) {
            tile.effectData.canPick = true;
          } else {
            const tileBlocked = this.isBlockedByUpper(tile);
            const linkedBlocked = this.isBlockedByUpper(linkedTile);
            tile.effectData.canPick = !tileBlocked && !linkedBlocked;
          }
        }
      }
    }
  }

  /**
   * 게임 상태 확인
   */
  private checkGameState(): void {
    // 골 클리어 확인
    let allGoalsCleared = true;
    for (const count of this.state.goalsRemaining.values()) {
      if (count > 0) {
        allGoalsCleared = false;
        break;
      }
    }

    // 남은 타일 확인
    let remainingTiles = 0;
    for (const layer of this.state.tiles.values()) {
      for (const tile of layer.values()) {
        if (!tile.picked) remainingTiles++;
      }
    }

    // 승리 조건
    if (allGoalsCleared && remainingTiles === 0 && this.state.dockTiles.length === 0) {
      this.state.cleared = true;
      return;
    }

    // 덱 가득 참 확인 (매칭 후에도)
    if (this.isDockFull()) {
      this.state.failed = true;
      return;
    }

    // 폭탄 폭발 확인
    for (const remaining of this.state.bombTiles.values()) {
      if (remaining <= 0) {
        this.state.failed = true;
        return;
      }
    }

    // 최대 이동 횟수 초과
    if (this.state.movesUsed >= this.state.maxMoves) {
      this.state.failed = true;
      return;
    }
  }

  /**
   * 덱이 가득 찼는지 확인 (매칭 후 남은 타일 기준)
   */
  private isDockFull(): boolean {
    const typeCounts = new Map<string, number>();
    for (const tile of this.state.dockTiles) {
      typeCounts.set(tile.tileType, (typeCounts.get(tile.tileType) || 0) + 1);
    }

    // 매칭 후 남는 타일 수 계산
    let remainingCount = 0;
    for (const count of typeCounts.values()) {
      remainingCount += count % 3;
    }

    return remainingCount >= this.state.maxDockSlots;
  }

  // ==================== Getter 메서드들 ====================

  getState(): GameState {
    return this.state;
  }

  getDockTiles(): TileState[] {
    return this.state.dockTiles;
  }

  isCleared(): boolean {
    return this.state.cleared;
  }

  isFailed(): boolean {
    return this.state.failed;
  }

  isGameOver(): boolean {
    return this.state.cleared || this.state.failed;
  }

  getMovesUsed(): number {
    return this.state.movesUsed;
  }

  /**
   * UI용 타일 정보 변환
   */
  getTilesForUI(): Array<{
    id: string;
    type: string;
    attribute: string;
    layer: number;
    row: number;
    col: number;
    isSelectable: boolean;
    isMatched: boolean;
    isHidden: boolean;
    effectData: TileEffectData;
  }> {
    const result: Array<{
      id: string;
      type: string;
      attribute: string;
      layer: number;
      row: number;
      col: number;
      isSelectable: boolean;
      isMatched: boolean;
      isHidden: boolean;
      effectData: TileEffectData;
    }> = [];

    for (const [layerIdx, layerTiles] of this.state.tiles) {
      for (const [, tile] of layerTiles) {
        const isSelectable = !tile.picked &&
          this.canPickTile(tile) &&
          !this.isBlockedByUpper(tile) &&
          !(tile.isStackTile && this.isStackBlocked(tile));

        const isHidden = tile.effectType === TileEffectType.UNKNOWN ||
          (tile.effectType === TileEffectType.CURTAIN && !tile.effectData.isOpen);

        result.push({
          id: `${layerIdx}_${tile.xIdx}_${tile.yIdx}`,
          type: tile.tileType,
          attribute: tile.effectType,
          layer: layerIdx,
          row: tile.xIdx,
          col: tile.yIdx,
          isSelectable,
          isMatched: tile.picked,
          isHidden,
          effectData: tile.effectData,
        });
      }
    }

    return result;
  }

  /**
   * 덱 타일 UI용 변환
   */
  getDockTilesForUI(): Array<{
    id: string;
    type: string;
    attribute: string;
    sourceLayer: number;
    sourceRow: number;
    sourceCol: number;
  }> {
    return this.state.dockTiles.map(tile => ({
      id: getFullKey(tile),
      type: tile.tileType,
      attribute: tile.effectType,
      sourceLayer: tile.layerIdx,
      sourceRow: tile.xIdx,
      sourceCol: tile.yIdx,
    }));
  }
}

// 싱글톤 인스턴스
let engineInstance: GameEngine | null = null;

export function getGameEngine(): GameEngine {
  if (!engineInstance) {
    engineInstance = new GameEngine();
  }
  return engineInstance;
}

export function createGameEngine(): GameEngine {
  return new GameEngine();
}
