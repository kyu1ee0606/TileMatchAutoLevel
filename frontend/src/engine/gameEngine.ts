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

  // t0 타일 타입 할당 맵 (3의 배수 규칙 보장)
  // key: "layerIdx_x_y" 또는 "layerIdx_x_y_stackIdx" -> 할당된 타일 타입
  t0AssignmentMap: Map<string, string>;

  // 타이밍 (개구리 이동 딜레이용)
  lastMoveTime: number;

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

// 개구리 이동 딜레이 (밀리초) - 빠르게 타일을 선택하면 개구리가 이동하지 않음
const FROG_MOVE_DELAY_MS = 500;

const MATCHABLE_TYPES = new Set([
  't1', 't2', 't3', 't4', 't5', 't6', 't7', 't8',
  't9', 't10', 't11', 't12', 't13', 't14', 't15', 't16'
]);

// 랜덤 타일 풀 (t0 할당용)
const RANDOM_TILE_POOL = ['t1', 't2', 't3', 't4', 't5', 't6', 't7', 't8', 't9', 't10', 't11', 't12', 't13', 't14', 't15', 't16'];

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
      t0AssignmentMap: new Map(),
      lastMoveTime: 0,
      maxLayerIdx: -1,
    };
  }

  /**
   * t0 타일들을 3의 배수 규칙에 맞게 분배
   * 백엔드 _distribute_t0_tiles와 동일한 로직
   */
  private distributeT0Tiles(
    t0Count: number,
    existingTileCounts: Map<string, number>,
    seed: number = 42
  ): string[] {
    if (t0Count === 0) return [];

    // 사용 가능한 타일 타입 결정
    // 기존 타일이 있으면 그 타입들만 사용, 없으면 RANDOM_TILE_POOL 사용
    let availableTypes: string[];
    if (existingTileCounts.size > 0) {
      availableTypes = Array.from(existingTileCounts.keys())
        .filter(t => t.startsWith('t') && t.slice(1).match(/^\d+$/))
        .sort((a, b) => parseInt(a.slice(1)) - parseInt(b.slice(1)));
      if (availableTypes.length === 0) {
        availableTypes = RANDOM_TILE_POOL.slice(0, 8);
      }
    } else {
      availableTypes = RANDOM_TILE_POOL.slice(0, 8);
    }

    // 각 타입별로 3의 배수가 되기 위해 필요한 타일 수 계산
    const typeNeeds = new Map<string, number>();
    for (const tileType of availableTypes) {
      const existing = existingTileCounts.get(tileType) || 0;
      const remainder = existing % 3;
      if (remainder === 0) {
        typeNeeds.set(tileType, 0);
      } else {
        typeNeeds.set(tileType, 3 - remainder);
      }
    }

    const assignments: string[] = [];
    let remainingT0 = t0Count;

    // 1단계: 3의 배수를 완성하기 위해 필요한 타일 먼저 할당
    const typesNeeding = Array.from(typeNeeds.entries())
      .filter(([_, need]) => need > 0)
      .sort((a, b) => a[1] - b[1]);

    for (const [tileType, need] of typesNeeding) {
      if (remainingT0 >= need) {
        for (let i = 0; i < need; i++) {
          assignments.push(tileType);
        }
        remainingT0 -= need;
        typeNeeds.set(tileType, 0);
      }
    }

    // 2단계: 남은 t0 타일들을 3개씩 묶어서 분배
    if (remainingT0 > 0) {
      const completeSets = Math.floor(remainingT0 / 3);
      const finalRemainder = remainingT0 % 3;

      if (completeSets > 0) {
        const numTypes = availableTypes.length;
        const setsPerType = Math.floor(completeSets / numTypes);
        const extraSets = completeSets % numTypes;

        for (let i = 0; i < numTypes; i++) {
          const tileType = availableTypes[i];
          const setsForThisType = setsPerType + (i < extraSets ? 1 : 0);
          for (let j = 0; j < setsForThisType * 3; j++) {
            assignments.push(tileType);
          }
        }
      }

      // 3단계: 나머지 처리 (1~2개 남은 경우)
      // 기존 할당에서 빌려와서 3의 배수로 맞춤
      if (finalRemainder > 0 && assignments.length > 0) {
        const assignCounts = new Map<string, number>();
        for (const t of assignments) {
          assignCounts.set(t, (assignCounts.get(t) || 0) + 1);
        }

        const tilesToBorrow = 3 - finalRemainder;
        let borrowFromType: string | null = null;
        let borrowToType: string | null = null;

        for (const tileType of availableTypes) {
          const current = assignCounts.get(tileType) || 0;
          if (current >= tilesToBorrow) {
            borrowFromType = tileType;
            break;
          }
        }

        for (const tileType of availableTypes) {
          if (tileType !== borrowFromType) {
            borrowToType = tileType;
            break;
          }
        }

        if (borrowFromType && borrowToType) {
          // borrowFromType에서 tilesToBorrow개 제거
          let removed = 0;
          const newAssignments: string[] = [];
          for (const t of assignments) {
            if (t === borrowFromType && removed < tilesToBorrow) {
              removed++;
              continue;
            }
            newAssignments.push(t);
          }
          assignments.length = 0;
          assignments.push(...newAssignments);

          // borrowToType으로 3개 추가
          for (let i = 0; i < 3; i++) {
            assignments.push(borrowToType);
          }
        }
      }
    }

    // 4단계: 최종 검증 및 수정 - 모든 타입이 3의 배수인지 확인
    for (let iteration = 0; iteration < 10; iteration++) {
      const assignCounts = new Map<string, number>();
      for (const t of assignments) {
        assignCounts.set(t, (assignCounts.get(t) || 0) + 1);
      }

      const finalCounts = new Map<string, number>();
      for (const tileType of availableTypes) {
        const existing = existingTileCounts.get(tileType) || 0;
        const assigned = assignCounts.get(tileType) || 0;
        finalCounts.set(tileType, existing + assigned);
      }

      const brokenTypes: Array<[string, number]> = [];
      for (const [tileType, count] of finalCounts) {
        if (count % 3 !== 0) {
          brokenTypes.push([tileType, count % 3]);
        }
      }

      if (brokenTypes.length === 0) break;

      // 나머지가 1인 타입과 2인 타입 짝짓기
      const rem1Types = brokenTypes.filter(([_, r]) => r === 1).map(([t]) => t);
      const rem2Types = brokenTypes.filter(([_, r]) => r === 2).map(([t]) => t);

      let madeChange = false;
      while (rem1Types.length > 0 && rem2Types.length > 0) {
        const fromType = rem1Types.pop()!;
        const toType = rem2Types.pop()!;

        for (let i = 0; i < assignments.length; i++) {
          if (assignments[i] === fromType) {
            assignments[i] = toType;
            madeChange = true;
            break;
          }
        }
      }

      if (!madeChange) break;
    }

    // 셔플 (시드 기반 랜덤)
    const seededRandom = (s: number) => {
      const x = Math.sin(s) * 10000;
      return x - Math.floor(x);
    };
    for (let i = assignments.length - 1; i > 0; i--) {
      const j = Math.floor(seededRandom(seed + i) * (i + 1));
      [assignments[i], assignments[j]] = [assignments[j], assignments[i]];
    }

    return assignments;
  }

  /**
   * 레벨 JSON으로 게임 상태 초기화
   *
   * 2단계 방식으로 처리하여 3의 배수 규칙 보장:
   * 1단계: 모든 타일 카운트 및 t0 위치 수집
   * 2단계: t0 타일 타입 분배 후 실제 타일 생성
   */
  initializeFromLevel(levelJson: Record<string, unknown>): void {
    this.state = this.createEmptyState();

    const numLayers = typeof levelJson.layer === 'number'
      ? levelJson.layer
      : parseInt(String(levelJson.layer || '8'), 10);

    this.state.maxMoves = typeof levelJson.max_moves === 'number'
      ? levelJson.max_moves
      : 50;

    // ========== 1단계: 타일 카운트 및 t0 위치 수집 ==========
    const existingTileCounts = new Map<string, number>();
    const t0Positions: Array<{ layerIdx: number; pos: string; key: string }> = [];
    const craftStackInfo: Array<{
      layerIdx: number;
      pos: string;
      xIdx: number;
      yIdx: number;
      tileType: string;
      extraData: unknown;
      totalCount: number;
    }> = [];

    for (let layerIdx = 0; layerIdx < numLayers; layerIdx++) {
      const layerKey = `layer_${layerIdx}`;
      const layerData = levelJson[layerKey] as Record<string, unknown> | undefined;
      if (!layerData) continue;

      // 레이어 col 저장
      const layerCol = typeof layerData.col === 'number'
        ? layerData.col
        : typeof layerData.col === 'string'
          ? parseInt(layerData.col, 10)
          : 7;
      this.state.layerCols.set(layerIdx, layerCol);

      const tilesData = layerData.tiles as Record<string, unknown[]> | undefined;
      if (!tilesData) continue;

      for (const [pos, tileData] of Object.entries(tilesData)) {
        if (!Array.isArray(tileData) || tileData.length === 0) continue;

        const [firstStr, secondStr] = pos.split('_');
        const xIdx = parseInt(firstStr, 10);
        const yIdx = parseInt(secondStr, 10);
        const tileType = String(tileData[0] || 't0');
        const extraData = tileData[2];

        // Craft/Stack 타일 - 내부 타일 수 카운트
        if (tileType.startsWith('craft_') || tileType.startsWith('stack_')) {
          let totalCount = 1;
          if (Array.isArray(extraData) && extraData.length >= 1) {
            totalCount = typeof extraData[0] === 'number' ? extraData[0] : 1;
          } else if (typeof extraData === 'number') {
            totalCount = extraData;
          }

          // 모든 내부 타일은 t0으로 처리됨
          for (let stackIdx = 0; stackIdx < totalCount; stackIdx++) {
            const fullKey = `${layerIdx}_${xIdx}_${yIdx}_${stackIdx}`;
            t0Positions.push({ layerIdx, pos, key: fullKey });
          }

          craftStackInfo.push({
            layerIdx,
            pos,
            xIdx,
            yIdx,
            tileType,
            extraData,
            totalCount,
          });
          continue;
        }

        // 일반 타일 카운트
        if (tileType === 't0') {
          const key = `${layerIdx}_${pos}`;
          t0Positions.push({ layerIdx, pos, key });
        } else if (tileType.match(/^t\d+$/)) {
          existingTileCounts.set(tileType, (existingTileCounts.get(tileType) || 0) + 1);
        }
      }
    }

    // ========== t0 타일 타입 분배 (3의 배수 규칙 보장) ==========
    const t0Assignments = this.distributeT0Tiles(
      t0Positions.length,
      existingTileCounts,
      42 // seed
    );

    // 할당 맵 구성
    for (let i = 0; i < t0Positions.length && i < t0Assignments.length; i++) {
      this.state.t0AssignmentMap.set(t0Positions[i].key, t0Assignments[i]);
    }

    console.log(`[Init] Distributed ${t0Assignments.length} t0 tiles across types:`,
      t0Assignments.reduce((acc, t) => { acc[t] = (acc[t] || 0) + 1; return acc; }, {} as Record<string, number>));

    // ========== 2단계: 실제 타일 생성 ==========
    for (let layerIdx = 0; layerIdx < numLayers; layerIdx++) {
      const layerKey = `layer_${layerIdx}`;
      const layerData = levelJson[layerKey] as Record<string, unknown> | undefined;
      if (!layerData) continue;

      const tilesData = layerData.tiles as Record<string, unknown[]> | undefined;
      if (!tilesData) continue;

      if (!this.state.tiles.has(layerIdx)) {
        this.state.tiles.set(layerIdx, new Map());
      }
      const layerTiles = this.state.tiles.get(layerIdx)!;

      for (const [pos, tileData] of Object.entries(tilesData)) {
        if (!Array.isArray(tileData) || tileData.length === 0) continue;

        const [firstStr, secondStr] = pos.split('_');
        const xIdx = parseInt(firstStr, 10);
        const yIdx = parseInt(secondStr, 10);

        let tileType = String(tileData[0] || 't0');
        const effectStr = String(tileData[1] || '');
        const extraData = tileData[2];

        // t0 타일은 할당된 타입으로 변환
        if (tileType === 't0') {
          const assignmentKey = `${layerIdx}_${pos}`;
          tileType = this.state.t0AssignmentMap.get(assignmentKey) || 't1';
        }

        // 기믹 타입 파싱
        let effectType = TileEffectType.NONE;
        const effectData: TileEffectData = {};

        if (effectStr) {
          effectType = EFFECT_MAPPING[effectStr] || TileEffectType.NONE;

          switch (effectType) {
            case TileEffectType.ICE:
              effectData.remaining = 3;
              this.state.iceTiles.set(`${layerIdx}_${pos}`, 3);
              break;

            case TileEffectType.CHAIN:
              effectData.unlocked = false;
              break;

            case TileEffectType.GRASS:
              effectData.remaining = 2;
              break;

            case TileEffectType.LINK_EAST:
            case TileEffectType.LINK_WEST:
            case TileEffectType.LINK_SOUTH:
            case TileEffectType.LINK_NORTH:
              effectData.canPick = false;
              let linkedX = xIdx, linkedY = yIdx;
              if (effectType === TileEffectType.LINK_EAST) linkedX += 1;
              else if (effectType === TileEffectType.LINK_WEST) linkedX -= 1;
              else if (effectType === TileEffectType.LINK_SOUTH) linkedY += 1;
              else if (effectType === TileEffectType.LINK_NORTH) linkedY -= 1;
              effectData.linkedPos = getPositionKey(linkedX, linkedY);
              break;

            case TileEffectType.FROG:
              effectData.onFrog = true;
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

        // Craft/Stack 타일은 별도 처리
        if (tileType.startsWith('craft_') || tileType.startsWith('stack_')) {
          this.processStackCraftTile(layerIdx, pos, xIdx, yIdx, tileType, extraData);
          continue;
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
   * Craft/Stack 타일 처리 (백엔드 _process_stack_craft_tiles와 동일)
   */
  private processStackCraftTile(
    layerIdx: number,
    pos: string,
    xIdx: number,
    yIdx: number,
    tileTypeStr: string,
    extraData: unknown
  ): void {
    const isCraft = tileTypeStr.startsWith('craft_');
    const isStack = tileTypeStr.startsWith('stack_');

    if (!isCraft && !isStack) return;

    // 방향 파싱
    const direction = tileTypeStr.split('_')[1] || 's';

    console.log(`[Craft] Processing ${tileTypeStr} at pos=${pos}, xIdx=${xIdx}, yIdx=${yIdx}, dir=${direction}, extraData=`, extraData);

    // 스택 정보 파싱 - extraData는 [count] 형태
    const stackInfo = Array.isArray(extraData) ? extraData : null;
    const totalCount = stackInfo && stackInfo.length >= 1 && typeof stackInfo[0] === 'number' ? stackInfo[0] : 1;
    if (totalCount <= 0) return;

    // Craft/Stack 박스 자체를 타일 맵에 추가 (시각적으로 보이게 함)
    if (!this.state.tiles.has(layerIdx)) {
      this.state.tiles.set(layerIdx, new Map());
    }
    const layerTiles = this.state.tiles.get(layerIdx)!;

    // 박스 타일 생성 (선택 불가능, 배경으로만 표시)
    const boxTile = createTileState({
      tileType: tileTypeStr,  // craft_s, stack_e 등
      layerIdx,
      xIdx,
      yIdx,
      effectType: TileEffectType.NONE,
      effectData: { remaining: totalCount },  // 남은 타일 수 저장
      isCraftTile: isCraft,
      isStackTile: isStack,
      craftDirection: direction,
      stackMaxIndex: totalCount,
    });
    layerTiles.set(pos, boxTile);

    // 방향별 스폰 위치 오프셋
    let spawnOffsetX = 0, spawnOffsetY = 0;
    if (direction === 'e') spawnOffsetX = 1;
    else if (direction === 'w') spawnOffsetX = -1;
    else if (direction === 's') spawnOffsetY = 1;
    else if (direction === 'n') spawnOffsetY = -1;

    // 스폰 위치
    const spawnX = xIdx + spawnOffsetX;
    const spawnY = yIdx + spawnOffsetY;
    const spawnPos = getPositionKey(spawnX, spawnY);

    // 내부 타일 생성
    const stackTileKeys: string[] = [];

    for (let stackIdx = 0; stackIdx < totalCount; stackIdx++) {
      // t0 타입은 사전 계산된 할당 맵에서 가져옴 (3의 배수 규칙 보장)
      const fullKey = `${layerIdx}_${xIdx}_${yIdx}_${stackIdx}`;
      const actualTileType = this.state.t0AssignmentMap.get(fullKey) || RANDOM_TILE_POOL[stackIdx % RANDOM_TILE_POOL.length];

      // Effect type 결정
      let effectType = TileEffectType.NONE;
      if (isCraft) {
        effectType = TileEffectType.CRAFT;
      } else if (isStack) {
        if (direction === 'n') effectType = TileEffectType.STACK_NORTH;
        else if (direction === 's') effectType = TileEffectType.STACK_SOUTH;
        else if (direction === 'e') effectType = TileEffectType.STACK_EAST;
        else if (direction === 'w') effectType = TileEffectType.STACK_WEST;
      }

      // 첫 번째 타일만 crafted (스폰 위치에 배치)
      const isCrafted = stackIdx === 0;
      const tileX = isCrafted ? spawnX : xIdx;
      const tileY = isCrafted ? spawnY : yIdx;

      const tile = createTileState({
        tileType: actualTileType,
        layerIdx,
        xIdx: tileX,
        yIdx: tileY,
        effectType,
        effectData: {},
        isCraftTile: isCraft,
        isStackTile: isStack,
        isCrafted,
        stackIndex: stackIdx,
        stackMaxIndex: totalCount - 1,
        craftDirection: direction,
        originGoalType: tileTypeStr,
      });

      // 스택 연결 설정
      // underStackedTileKey: 이 타일이 선택된 후 스폰될 다음 타일 (stackIdx + 1)
      // upperStackedTileKey: 이 타일 위에 있던 타일 (stackIdx - 1, 이미 선택됨)
      if (stackIdx < totalCount - 1) {
        tile.underStackedTileKey = `${layerIdx}_${xIdx}_${yIdx}_${stackIdx + 1}`;
      }
      if (stackIdx > 0) {
        tile.upperStackedTileKey = `${layerIdx}_${xIdx}_${yIdx}_${stackIdx - 1}`;
      }
      tile.rootStackedTileKey = `${layerIdx}_${xIdx}_${yIdx}_0`;

      // stackedTiles에 저장
      this.state.stackedTiles.set(fullKey, tile);
      stackTileKeys.push(fullKey);

      // 첫 번째 타일(crafted)만 tiles 맵에 추가
      if (isCrafted) {
        if (!this.state.tiles.has(layerIdx)) {
          this.state.tiles.set(layerIdx, new Map());
        }
        const layerTiles = this.state.tiles.get(layerIdx)!;
        layerTiles.set(spawnPos, tile);
        console.log(`[Craft] Added crafted tile at spawnPos=${spawnPos}, layer=${layerIdx}, type=${actualTileType}, tileX=${tileX}, tileY=${tileY}`);
      }
    }

    // craftBoxes에 저장
    this.state.craftBoxes.set(`${layerIdx}_${pos}`, stackTileKeys);

    // Craft 타일은 목표에 추가
    if (isCraft) {
      const currentGoal = this.state.goalsRemaining.get(tileTypeStr) || 0;
      this.state.goalsRemaining.set(tileTypeStr, currentGoal + 1);
    }
  }

  /**
   * Craft 타일 선택 후 처리 (다음 타일 스폰)
   */
  private processCraftAfterPick(pickedTile: TileState): void {
    if (!pickedTile.isCraftTile && !pickedTile.isStackTile) return;

    // 박스 타일의 남은 카운트 감소
    const rootKey = pickedTile.rootStackedTileKey;
    if (rootKey) {
      // rootKey format: "layerIdx_xIdx_yIdx_0" -> extract box position
      const parts = rootKey.split('_');
      if (parts.length >= 3) {
        const boxLayerIdx = parseInt(parts[0], 10);
        const boxPos = `${parts[1]}_${parts[2]}`;
        const boxLayerTiles = this.state.tiles.get(boxLayerIdx);
        if (boxLayerTiles) {
          const boxTile = boxLayerTiles.get(boxPos);
          if (boxTile && (boxTile.tileType.startsWith('craft_') || boxTile.tileType.startsWith('stack_'))) {
            const remaining = (boxTile.effectData.remaining || 1) - 1;
            boxTile.effectData.remaining = remaining;
            // 모든 타일이 배출되면 박스 제거
            if (remaining <= 0) {
              boxTile.picked = true;
            }
          }
        }
      }
    }

    // 다음 타일 찾기
    if (!pickedTile.underStackedTileKey) return;

    const nextTile = this.state.stackedTiles.get(pickedTile.underStackedTileKey);
    if (!nextTile || nextTile.picked) return;

    // 스폰 위치는 선택된 타일 위치
    const spawnX = pickedTile.xIdx;
    const spawnY = pickedTile.yIdx;
    const spawnPos = getPositionKey(spawnX, spawnY);

    // 스폰 위치가 비어있는지 확인
    const layerTiles = this.state.tiles.get(nextTile.layerIdx);
    if (!layerTiles) return;

    const existingTile = layerTiles.get(spawnPos);
    if (existingTile && !existingTile.picked) return; // 위치가 차있음

    // 다음 타일을 스폰 위치로 이동
    nextTile.isCrafted = true;
    nextTile.upperStackedTileKey = null;
    nextTile.xIdx = spawnX;
    nextTile.yIdx = spawnY;

    // tiles 맵에 추가
    layerTiles.set(spawnPos, nextTile);
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

    // 선택 전 노출된 폭탄 수집 (백엔드 로직과 동일 - 이동 전에 노출된 폭탄만 카운트다운)
    const exposedBombsBeforeMove = new Set<string>();
    for (const [bombKey] of this.state.bombTiles) {
      const parts = bombKey.split('_');
      if (parts.length >= 3) {
        const lIdx = parseInt(parts[0], 10);
        const posKey = `${parts[1]}_${parts[2]}`;
        const layerTiles = this.state.tiles.get(lIdx);
        const bombTile = layerTiles?.get(posKey);
        if (bombTile && !bombTile.picked && !this.isBlockedByUpper(bombTile)) {
          exposedBombsBeforeMove.add(bombKey);
        }
      }
    }

    // 선택 전 노출된 커튼 수집 (백엔드 로직과 동일 - 이동 전에 노출된 커튼만 토글)
    const exposedCurtainsBeforeMove = new Set<string>();
    for (const [curtainKey] of this.state.curtainTiles) {
      const parts = curtainKey.split('_');
      if (parts.length >= 3) {
        const lIdx = parseInt(parts[0], 10);
        const posKey = `${parts[1]}_${parts[2]}`;
        const layerTiles = this.state.tiles.get(lIdx);
        const curtainTile = layerTiles?.get(posKey);
        if (curtainTile && !curtainTile.picked && !this.isBlockedByUpper(curtainTile)) {
          exposedCurtainsBeforeMove.add(curtainKey);
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

    // Craft/Stack 타일이면 다음 타일 스폰
    this.processCraftAfterPick(tile);

    // 덱에 추가 (같은 타입끼리 그룹화)
    this.addToDock(tile);

    // 링크된 타일도 선택
    if (linkedTile && !linkedTile.picked) {
      linkedTile.picked = true;
      this.processCraftAfterPick(linkedTile);
      this.addToDock(linkedTile);
      this.updateAdjacentEffects(linkedTile, unblockedIceBeforePick);
    }

    // 인접 타일 효과 업데이트
    this.updateAdjacentEffects(tile, unblockedIceBeforePick);

    // 덱 매칭 처리 (3개씩만 제거 - 백엔드와 동일)
    this.processDockMatches();

    // 이동 횟수 증가
    this.state.movesUsed++;

    // === POST-MOVE EFFECTS (백엔드 _process_move_effects와 동일) ===

    // 1. 노출된 폭탄 카운트다운 감소 (이동 전에 노출된 폭탄만)
    this.decreaseBombCountdowns(exposedBombsBeforeMove);

    // 2. 노출된 커튼 토글 (이동 전에 노출된 커튼만)
    this.toggleExposedCurtains(exposedCurtainsBeforeMove);

    // 3. 개구리 이동 (모든 개구리가 랜덤 위치로 이동)
    // 타운팝 규칙: 빠르게 타일을 선택하면 개구리가 이동하지 않음
    const currentTime = Date.now();
    const timeSinceLastMove = currentTime - this.state.lastMoveTime;
    if (timeSinceLastMove >= FROG_MOVE_DELAY_MS) {
      this.moveAllFrogs();
    }
    this.state.lastMoveTime = currentTime;

    // 4. 텔레포트 처리 (3턴마다 셔플)
    this.processTeleport();

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

    // 체인: 수평 인접만, 덮여있지 않은 경우에만 해제 (잔디와 동일한 규칙)
    const horizontalPositions: [number, number][] = [[x + 1, y], [x - 1, y]];

    for (const [adjX, adjY] of horizontalPositions) {
      const posKey = getPositionKey(adjX, adjY);
      const adjTile = layer.get(posKey);
      if (!adjTile || adjTile.picked) continue;

      if (adjTile.effectType === TileEffectType.CHAIN) {
        // 체인 타일이 덮여있으면 해제하지 않음 (잔디와 동일)
        if (!this.isBlockedByUpper(adjTile)) {
          adjTile.effectData.unlocked = true;
        }
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

    // 잔디 클리어 불가 확인 (인접 타일 부족)
    if (this.checkGrassImpossible()) {
      this.state.failed = true;
      return;
    }

    // 체인 클리어 불가 확인 (좌우 인접 타일 모두 제거됨)
    if (this.checkChainImpossible()) {
      this.state.failed = true;
      return;
    }

    // 선택 가능한 타일이 없으면 실패 (덮여있는 체인 등으로 인해 진행 불가)
    if (remainingTiles > 0 && this.getAvailableMoves().length === 0) {
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

  /**
   * 잔디 클리어 불가능 상태 확인
   * 잔디 레이어 수 > 인접 미선택 타일 수 → 불가능
   */
  private checkGrassImpossible(): boolean {
    for (const [_layerIdx, layerTiles] of this.state.tiles) {
      for (const [_posKey, tile] of layerTiles) {
        if (tile.picked) continue;
        if (tile.effectType !== TileEffectType.GRASS) continue;

        const grassRemaining = tile.effectData.remaining || 0;
        if (grassRemaining <= 0) continue;

        // 인접 타일(상하좌우) 카운트
        const x = tile.xIdx;
        const y = tile.yIdx;
        const adjacentPositions = [
          [x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]
        ];

        let adjacentUnpickedCount = 0;
        for (const [adjX, adjY] of adjacentPositions) {
          const adjPosKey = getPositionKey(adjX, adjY);
          const adjTile = layerTiles.get(adjPosKey);
          if (adjTile && !adjTile.picked) {
            adjacentUnpickedCount++;
          }
        }

        // 잔디 레이어 > 인접 타일 수 → 불가능
        if (grassRemaining > adjacentUnpickedCount) {
          return true;
        }
      }
    }
    return false;
  }

  /**
   * 체인 클리어 불가능 상태 확인
   * 체인이 잠겨있고 좌우 인접 타일이 모두 제거됨 → 불가능
   */
  private checkChainImpossible(): boolean {
    for (const [_layerIdx, layerTiles] of this.state.tiles) {
      for (const [_posKey, tile] of layerTiles) {
        if (tile.picked) continue;
        if (tile.effectType !== TileEffectType.CHAIN) continue;
        if (tile.effectData.unlocked) continue; // 이미 해제됨

        // 좌우 인접 타일 확인 (체인은 좌우로만 해제 가능)
        const x = tile.xIdx;
        const y = tile.yIdx;
        const horizontalPositions = [
          [x + 1, y], [x - 1, y]
        ];

        let hasClearableNeighbor = false;
        for (const [adjX, adjY] of horizontalPositions) {
          const adjPosKey = getPositionKey(adjX, adjY);
          const adjTile = layerTiles.get(adjPosKey);
          // 인접 타일이 있고, 선택 안됐고, 장애물이 없거나 frog만 있으면 clearable
          if (adjTile && !adjTile.picked) {
            const adjAttr = adjTile.effectType;
            if (adjAttr === TileEffectType.NONE || adjAttr === TileEffectType.FROG) {
              hasClearableNeighbor = true;
              break;
            }
          }
        }

        if (!hasClearableNeighbor) {
          return true;
        }
      }
    }
    return false;
  }

  // ==================== POST-MOVE EFFECTS ====================

  /**
   * 노출된 폭탄 카운트다운 감소
   * 백엔드 _process_move_effects와 동일
   * @param exposedBombsBeforeMove 이동 전에 노출된 폭탄 키 집합
   */
  private decreaseBombCountdowns(exposedBombsBeforeMove: Set<string>): void {
    for (const [bombKey, remaining] of this.state.bombTiles) {
      // 이동 전에 노출된 폭탄만 카운트다운 (백엔드와 동일)
      if (!exposedBombsBeforeMove.has(bombKey)) continue;

      // Parse layerIdx_x_y format
      const parts = bombKey.split('_');
      if (parts.length < 3) continue;

      const layerIdx = parseInt(parts[0], 10);
      const pos = `${parts[1]}_${parts[2]}`;

      const layer = this.state.tiles.get(layerIdx);
      const tile = layer?.get(pos);

      if (!tile || tile.picked) continue;

      const newRemaining = remaining - 1;
      this.state.bombTiles.set(bombKey, newRemaining);
      tile.effectData.remaining = newRemaining;
    }
  }

  /**
   * 노출된 커튼 토글
   * 백엔드 _process_move_effects와 동일
   * @param exposedCurtainsBeforeMove 이동 전에 노출된 커튼 키 집합
   */
  private toggleExposedCurtains(exposedCurtainsBeforeMove: Set<string>): void {
    for (const [curtainKey, isOpen] of this.state.curtainTiles) {
      // 이동 전에 노출된 커튼만 토글 (백엔드와 동일)
      if (!exposedCurtainsBeforeMove.has(curtainKey)) continue;

      const parts = curtainKey.split('_');
      if (parts.length < 3) continue;

      const layerIdx = parseInt(parts[0], 10);
      const pos = `${parts[1]}_${parts[2]}`;

      const layer = this.state.tiles.get(layerIdx);
      const tile = layer?.get(pos);

      if (!tile || tile.picked) continue;

      const newState = !isOpen;
      this.state.curtainTiles.set(curtainKey, newState);
      tile.effectData.isOpen = newState;
    }
  }

  /**
   * 개구리가 이동할 수 있는 타일 목록 반환
   */
  private getFrogMovableTiles(): Array<{ layerIdx: number; pos: string; tile: TileState }> {
    const available: Array<{ layerIdx: number; pos: string; tile: TileState }> = [];

    for (const [layerIdx, layer] of this.state.tiles) {
      for (const [pos, tile] of layer) {
        // 이미 선택된 타일 제외
        if (tile.picked) continue;

        // 매치 불가능한 타일 제외
        if (!MATCHABLE_TYPES.has(tile.tileType)) continue;

        // 이미 개구리가 있는 타일 제외
        if (tile.effectData.onFrog) continue;

        // 상위 레이어에 막힌 타일 제외
        if (this.isBlockedByUpper(tile)) continue;

        // 기믹으로 선택 불가능한 타일 제외
        if (!this.canPickTile(tile)) continue;

        available.push({ layerIdx, pos, tile });
      }
    }

    return available;
  }

  /**
   * 모든 개구리를 랜덤 위치로 이동
   * 백엔드 _move_all_frogs와 동일
   */
  private moveAllFrogs(): void {
    if (this.state.frogPositions.size === 0) return;

    // 이동 가능한 타일 목록
    const availableTiles = this.getFrogMovableTiles();

    // 랜덤 셔플
    for (let i = availableTiles.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [availableTiles[i], availableTiles[j]] = [availableTiles[j], availableTiles[i]];
    }

    // 현재 개구리 위치의 타일들 수집
    const currentFrogTiles: Array<{ layerIdx: number; pos: string; tile: TileState }> = [];
    for (const [layerIdx, layer] of this.state.tiles) {
      for (const [pos, tile] of layer) {
        if (tile.effectData.onFrog) {
          currentFrogTiles.push({ layerIdx, pos, tile });
        }
      }
    }

    // 모든 현재 개구리 위치 초기화
    for (const { tile } of currentFrogTiles) {
      tile.effectData.onFrog = false;
    }
    this.state.frogPositions.clear();

    // 새로운 위치로 개구리 이동
    const numFrogsToMove = Math.min(currentFrogTiles.length, availableTiles.length);
    for (let i = 0; i < numFrogsToMove; i++) {
      const { layerIdx, pos, tile } = availableTiles[i];
      tile.effectData.onFrog = true;
      this.state.frogPositions.add(`${layerIdx}_${pos}`);
    }
  }

  /**
   * 텔레포트 처리 (3턴마다 타일 타입 셔플)
   * 백엔드 _process_teleport와 동일
   */
  private processTeleport(): void {
    // 텔레포트 타일이 없으면 스킵
    if (this.state.teleportTiles.length < 2) return;

    // 클릭 카운트 증가
    this.state.teleportClickCount++;

    // 3턴마다 셔플
    if (this.state.teleportClickCount >= 3) {
      this.state.teleportClickCount = 0;

      // 유효한 텔레포트 타일 수집
      const validTeleportTiles: Array<{ layerIdx: number; pos: string; tile: TileState }> = [];
      for (const [layerIdx, pos] of this.state.teleportTiles) {
        const layer = this.state.tiles.get(layerIdx);
        const tile = layer?.get(pos);
        if (tile && !tile.picked) {
          validTeleportTiles.push({ layerIdx, pos, tile });
        }
      }

      // 2개 미만이면 텔레포트 효과 제거
      if (validTeleportTiles.length < 2) {
        // 텔레포트 효과 제거
        for (const { tile } of validTeleportTiles) {
          tile.effectType = TileEffectType.NONE;
        }
        this.state.teleportTiles = [];
        return;
      }

      // Sattolo 셔플 (모든 타일이 다른 위치로 이동)
      const tileTypes = validTeleportTiles.map(t => t.tile.tileType);
      for (let i = tileTypes.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * i); // 0 to i-1 (not including i)
        [tileTypes[i], tileTypes[j]] = [tileTypes[j], tileTypes[i]];
      }

      // 새로운 타일 타입 적용
      for (let i = 0; i < validTeleportTiles.length; i++) {
        validTeleportTiles[i].tile.tileType = tileTypes[i];
      }
    }
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
    extra?: number[];
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
      extra?: number[];
    }> = [];

    for (const [layerIdx, layerTiles] of this.state.tiles) {
      for (const [, tile] of layerTiles) {
        // Craft/Stack 박스는 선택 불가능
        const isCraftStackBox = tile.tileType.startsWith('craft_') || tile.tileType.startsWith('stack_');
        const isSelectable = !tile.picked &&
          !isCraftStackBox &&
          this.canPickTile(tile) &&
          !this.isBlockedByUpper(tile) &&
          !(tile.isStackTile && this.isStackBlocked(tile));

        // Unknown 타일은 위에 다른 타일이 있을 때만 숨김 (위 타일이 제거되면 공개)
        const isBlockedByUpperTile = this.isBlockedByUpper(tile);
        const isHidden = (tile.effectType === TileEffectType.UNKNOWN && isBlockedByUpperTile) ||
          (tile.effectType === TileEffectType.CURTAIN && !tile.effectData.isOpen);

        // Craft/Stack 박스의 경우 남은 타일 수를 extra에 포함
        const extra = isCraftStackBox && tile.effectData.remaining !== undefined
          ? [tile.effectData.remaining]
          : undefined;

        result.push({
          id: `${layerIdx}_${tile.xIdx}_${tile.yIdx}`,
          type: tile.tileType,
          attribute: tile.effectType,
          layer: layerIdx,
          row: tile.yIdx,  // yIdx = row = vertical position
          col: tile.xIdx,  // xIdx = col = horizontal position
          isSelectable,
          isMatched: tile.picked,
          isHidden,
          effectData: tile.effectData,
          extra,
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
      sourceRow: tile.yIdx,  // yIdx = row = vertical position
      sourceCol: tile.xIdx,  // xIdx = col = horizontal position
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
