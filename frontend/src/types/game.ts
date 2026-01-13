/**
 * Game Player Types
 * 타일 매칭 게임 플레이어를 위한 타입 정의
 */

/** 게임 내 타일 상태 */
export interface GameTile {
  id: string;           // 고유 ID (layer_row_col)
  type: string;         // 타일 타입 (t0~t15, craft_*, stack_*)
  attribute: string;    // 속성 (chain, ice, frog, etc.)
  layer: number;        // 레이어 인덱스
  row: number;          // 행
  col: number;          // 열
  isSelectable: boolean; // 선택 가능 여부 (위에 다른 타일이 없음)
  isSelected: boolean;  // 현재 선택됨
  isMatched: boolean;   // 매치되어 제거 예정
  isHidden: boolean;    // 숨겨진 상태 (unknown, curtain 등)
  extra?: number[];     // 추가 데이터 (craft/stack의 타일 수 등)
}

/** 슬롯 영역의 타일 */
export interface SlotTile {
  id: string;
  type: string;
  attribute: string;
  sourceLayer: number;
  sourceRow: number;
  sourceCol: number;
}

/** 게임 상태 */
export type GameState = 'idle' | 'playing' | 'won' | 'lost' | 'paused';

/** 게임 통계 */
export interface GameStats {
  moves: number;        // 이동 횟수
  matches: number;      // 매치 횟수
  combos: number;       // 콤보 횟수
  score: number;        // 점수
  timeElapsed: number;  // 경과 시간 (초)
}

/** 게임 설정 */
export interface GameSettings {
  maxSlots: number;     // 최대 슬롯 수 (기본 7)
  enableUndo: boolean;  // 되돌리기 활성화
  enableHint: boolean;  // 힌트 활성화
  enableShuffle: boolean; // 셔플 활성화
  soundEnabled: boolean; // 사운드 활성화
}

/** 게임 액션 (되돌리기용) */
export interface GameAction {
  type: 'select' | 'match' | 'shuffle';
  tiles: GameTile[];
  slotState: SlotTile[];
  timestamp: number;
}

/** 레벨 정보 */
export interface LevelInfo {
  id: string;
  name: string;
  source: 'local' | 'gboost';
  difficulty?: number;
  totalTiles: number;
  layers: number;
}

/** 게임 컨텍스트 */
export interface GameContext {
  levelInfo: LevelInfo | null;
  tiles: GameTile[];
  slots: SlotTile[];
  state: GameState;
  stats: GameStats;
  settings: GameSettings;
  history: GameAction[];
}

/** 기본 게임 설정 */
export const DEFAULT_GAME_SETTINGS: GameSettings = {
  maxSlots: 7,
  enableUndo: true,
  enableHint: true,
  enableShuffle: true,
  soundEnabled: false,
};

/** 초기 게임 통계 */
export const INITIAL_GAME_STATS: GameStats = {
  moves: 0,
  matches: 0,
  combos: 0,
  score: 0,
  timeElapsed: 0,
};

/** 타일 타입별 색상 (폴백용) */
export const TILE_COLORS: Record<string, string> = {
  t0: '#94a3b8',   // slate
  t1: '#f87171',   // red
  t2: '#fb923c',   // orange
  t3: '#facc15',   // yellow
  t4: '#4ade80',   // green
  t5: '#60a5fa',   // blue
  t6: '#c084fc',   // purple
  t7: '#78716c',   // stone
  t8: '#a8a29e',   // stone light
  t9: '#57534e',   // stone dark
  t10: '#fbbf24',  // amber
  t11: '#f97316',  // orange dark
  t12: '#f472b6',  // pink
  t13: '#22d3ee',  // cyan
  t14: '#2dd4bf',  // teal
  t15: '#a78bfa',  // violet
};

/** 특수 타일인지 확인 */
export function isSpecialTile(type: string): boolean {
  return type.startsWith('craft_') || type.startsWith('stack_');
}

/** 타일이 매치 가능한지 확인 (같은 타입) */
export function canMatch(tile1: GameTile, tile2: GameTile): boolean {
  // 특수 타일은 매치 불가
  if (isSpecialTile(tile1.type) || isSpecialTile(tile2.type)) {
    return false;
  }
  return tile1.type === tile2.type;
}

/** 레이어 데이터에서 GameTile 배열 생성 */
export function parseLevelToTiles(levelData: Record<string, unknown>): GameTile[] {
  const tiles: GameTile[] = [];
  const numLayers = typeof levelData.layer === 'number'
    ? levelData.layer
    : parseInt(String(levelData.layer || '8'), 10);

  for (let layerIdx = 0; layerIdx < numLayers; layerIdx++) {
    const layerKey = `layer_${layerIdx}`;
    const layerData = levelData[layerKey] as Record<string, unknown> | undefined;

    if (!layerData) continue;

    const tilesData = layerData.tiles as Record<string, unknown[]> | undefined;
    if (!tilesData) continue;

    for (const [pos, tileData] of Object.entries(tilesData)) {
      if (!Array.isArray(tileData) || tileData.length === 0) continue;

      const [rowStr, colStr] = pos.split('_');
      const row = parseInt(rowStr, 10);
      const col = parseInt(colStr, 10);

      const tile: GameTile = {
        id: `${layerIdx}_${row}_${col}`,
        type: String(tileData[0] || 't0'),
        attribute: String(tileData[1] || ''),
        layer: layerIdx,
        row,
        col,
        isSelectable: false, // Will be calculated later
        isSelected: false,
        isMatched: false,
        isHidden: false,
        extra: Array.isArray(tileData[2]) ? tileData[2] : undefined,
      };

      // Check for hidden attributes
      if (tile.attribute === 'unknown' || tile.attribute.startsWith('curtain')) {
        tile.isHidden = true;
      }

      tiles.push(tile);
    }
  }

  return tiles;
}

/**
 * Blocking offsets based on layer parity (same as backend bot_simulator.py)
 * - Same parity (layer 0→2, 1→3): only check same position
 * - Different parity: check 4 positions based on layer col comparison
 *   Since we don't have layer_cols in frontend, we use a combined approach
 *   that checks all potentially blocking positions
 */
const BLOCKING_OFFSETS_SAME_PARITY = [[0, 0]];
// Combined offsets from both UPPER_BIGGER and UPPER_SMALLER for safety
// This ensures we catch all blocking scenarios regardless of layer_cols
const BLOCKING_OFFSETS_DIFF_PARITY = [
  [-1, -1], [0, -1], [-1, 0], [0, 0],
  [1, 0], [0, 1], [1, 1]
];

/** 타일 선택 가능 여부 계산 (위에 다른 타일이 없는지) */
export function calculateSelectability(tiles: GameTile[]): GameTile[] {
  // Build a map of tiles by layer and position for fast lookup
  const tilesByLayerAndPos = new Map<string, GameTile>();

  for (const tile of tiles) {
    if (tile.isMatched) continue;
    const key = `${tile.layer}_${tile.row}_${tile.col}`;
    tilesByLayerAndPos.set(key, tile);
  }

  // Find max layer
  let maxLayer = 0;
  for (const tile of tiles) {
    if (!tile.isMatched && tile.layer > maxLayer) {
      maxLayer = tile.layer;
    }
  }

  /**
   * Check if a tile is blocked by tiles in upper layers
   * Based on sp_template TileGroup.FindAllUpperTiles logic
   */
  const isBlockedByUpper = (tile: GameTile): boolean => {
    if (tile.layer >= maxLayer) return false;

    const tileParity = tile.layer % 2;

    for (let upperLayerIdx = tile.layer + 1; upperLayerIdx <= maxLayer; upperLayerIdx++) {
      const upperParity = upperLayerIdx % 2;

      // Determine blocking offsets based on parity
      const blockingOffsets = tileParity === upperParity
        ? BLOCKING_OFFSETS_SAME_PARITY
        : BLOCKING_OFFSETS_DIFF_PARITY;

      for (const [dx, dy] of blockingOffsets) {
        const bx = tile.row + dx;
        const by = tile.col + dy;
        const key = `${upperLayerIdx}_${bx}_${by}`;

        const upperTile = tilesByLayerAndPos.get(key);
        if (upperTile && !upperTile.isMatched) {
          return true; // Blocked by this upper tile
        }
      }
    }

    return false;
  };

  // Calculate selectability for each tile
  const result = tiles.map(tile => {
    if (tile.isMatched) {
      return { ...tile, isSelectable: false };
    }

    const isBlocked = isBlockedByUpper(tile);

    return {
      ...tile,
      isSelectable: !isBlocked && !tile.isHidden,
    };
  });

  return result;
}
