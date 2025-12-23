import { create } from 'zustand';
import type { LevelJSON, TileData, DifficultyReport } from '../types';

// Check if a tile is clearable (no obstacle or only frog)
function isTileClearable(tileData: TileData | undefined): boolean {
  if (!tileData || !Array.isArray(tileData) || tileData.length < 2) return false;
  const attr = tileData[1];
  return !attr || attr === 'frog';
}

// Check if a chain tile has at least one clearable neighbor on LEFT or RIGHT
// Backend uses row_col format, frontend reads as x_y where x=row, y=col
// Chain LEFT/RIGHT in backend = row±1 = x±1 in frontend string (horizontal on screen)
function hasChainClearableNeighbor(
  tiles: Record<string, TileData>,
  x: number,
  y: number
): boolean {
  const leftPos = `${x - 1}_${y}`;  // x-1 = row-1 = LEFT on screen (horizontal)
  const rightPos = `${x + 1}_${y}`; // x+1 = row+1 = RIGHT on screen (horizontal)

  return isTileClearable(tiles[leftPos]) || isTileClearable(tiles[rightPos]);
}

// Check if removing a tile would break any chain's clearability
// Backend uses row_col format, frontend reads as x_y where x=row, y=col
// Chain LEFT/RIGHT in backend = row±1 = x±1 in frontend string (horizontal on screen)
function wouldBreakChainClearability(
  tiles: Record<string, TileData>,
  removeX: number,
  removeY: number
): { wouldBreak: boolean; chainPos?: string } {
  // Check if left neighbor (x-1 = row-1) is a chain
  const leftChainPos = `${removeX - 1}_${removeY}`;
  const leftTile = tiles[leftChainPos];
  if (leftTile && Array.isArray(leftTile) && leftTile[1] === 'chain') {
    // This tile is the RIGHT neighbor of the chain
    // Check if chain has any other clearable neighbor (only LEFT of chain = x-2)
    const chainLeftPos = `${removeX - 2}_${removeY}`;
    if (!isTileClearable(tiles[chainLeftPos])) {
      return { wouldBreak: true, chainPos: leftChainPos };
    }
  }

  // Check if right neighbor (x+1 = row+1) is a chain
  const rightChainPos = `${removeX + 1}_${removeY}`;
  const rightTile = tiles[rightChainPos];
  if (rightTile && Array.isArray(rightTile) && rightTile[1] === 'chain') {
    // This tile is the LEFT neighbor of the chain
    // Check if chain has any other clearable neighbor (only RIGHT of chain = x+2)
    const chainRightPos = `${removeX + 2}_${removeY}`;
    if (!isTileClearable(tiles[chainRightPos])) {
      return { wouldBreak: true, chainPos: rightChainPos };
    }
  }

  return { wouldBreak: false };
}

// Validation result type
export interface ValidationResult {
  valid: boolean;
  reason?: string;
}

// Create empty level structure
function createEmptyLevel(layers: number = 8, gridSize: [number, number] = [7, 7]): LevelJSON {
  const level: LevelJSON = { layer: layers };

  for (let i = 0; i < layers; i++) {
    const isOddLayer = i % 2 === 1;
    const [cols, rows] = gridSize;

    const layerKey = `layer_${i}` as `layer_${number}`;
    level[layerKey] = {
      col: String(isOddLayer ? cols : cols + 1),
      row: String(isOddLayer ? rows : rows + 1),
      tiles: {},
      num: '0',
    };
  }

  return level;
}

interface LevelState {
  // Current level data
  level: LevelJSON;
  selectedLayer: number;
  selectedTileType: string;
  selectedAttribute: string;

  // Analysis results
  analysisResult: DifficultyReport | null;
  isAnalyzing: boolean;

  // Actions
  setLevel: (level: LevelJSON) => void;
  resetLevel: (layers?: number, gridSize?: [number, number]) => void;
  setSelectedLayer: (layer: number) => void;
  setSelectedTileType: (tileType: string) => void;
  setSelectedAttribute: (attribute: string) => void;

  // Tile operations (with validation)
  setTile: (layer: number, x: number, y: number, tileData: TileData) => ValidationResult;
  removeTile: (layer: number, x: number, y: number) => ValidationResult;
  clearLayer: (layer: number) => void;
  fillLayer: (layer: number, tileData: TileData) => void;

  // Analysis
  setAnalysisResult: (result: DifficultyReport | null) => void;
  setIsAnalyzing: (isAnalyzing: boolean) => void;

  // Import/Export
  importJson: (json: string) => boolean;
  exportJson: () => string;
}

export const useLevelStore = create<LevelState>((set, get) => ({
  // Initial state
  level: createEmptyLevel(),
  selectedLayer: 7,
  selectedTileType: 't0',
  selectedAttribute: '',
  analysisResult: null,
  isAnalyzing: false,

  // Level management
  setLevel: (level) => {
    // Adjust selectedLayer if current selection exceeds new level's layer count
    const currentSelectedLayer = get().selectedLayer;
    const maxLayer = level.layer - 1;
    const newSelectedLayer = currentSelectedLayer > maxLayer ? maxLayer : currentSelectedLayer;
    set({ level, analysisResult: null, selectedLayer: newSelectedLayer });
  },

  resetLevel: (layers = 8, gridSize = [7, 7]) =>
    set({
      level: createEmptyLevel(layers, gridSize),
      analysisResult: null,
    }),

  setSelectedLayer: (layer) => set({ selectedLayer: layer }),
  setSelectedTileType: (tileType) => set({ selectedTileType: tileType }),
  setSelectedAttribute: (attribute) => set({ selectedAttribute: attribute }),

  // Tile operations with validation
  setTile: (layer, x, y, tileData) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return { valid: false, reason: '레이어를 찾을 수 없습니다' };

    const position = `${x}_${y}`;
    const newTiles = { ...layerData.tiles, [position]: tileData };

    // Validate: If placing a chain, check if it has clearable neighbors
    const attr = tileData[1];
    if (attr === 'chain') {
      if (!hasChainClearableNeighbor(newTiles, x, y)) {
        return {
          valid: false,
          reason: 'Chain 타일은 좌우 중 최소 1개의 클리어 가능한 타일이 필요합니다',
        };
      }
    }

    // Validate: If placing an obstacle on a clearable tile, check if it breaks any chain
    if (attr && attr !== 'frog') {
      const breakCheck = wouldBreakChainClearability(layerData.tiles, x, y);
      if (breakCheck.wouldBreak) {
        return {
          valid: false,
          reason: `이 타일에 장애물을 배치하면 Chain(${breakCheck.chainPos})을 해제할 수 없게 됩니다`,
        };
      }
    }

    set({
      level: {
        ...level,
        [layerKey]: {
          ...layerData,
          tiles: newTiles,
          num: String(Object.keys(newTiles).length),
        },
      },
      analysisResult: null,
    });

    return { valid: true };
  },

  removeTile: (layer, x, y) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return { valid: false, reason: '레이어를 찾을 수 없습니다' };

    const position = `${x}_${y}`;

    // Validate: Check if removing this tile would break any chain's clearability
    const breakCheck = wouldBreakChainClearability(layerData.tiles, x, y);
    if (breakCheck.wouldBreak) {
      return {
        valid: false,
        reason: `이 타일을 삭제하면 Chain(${breakCheck.chainPos})을 해제할 수 없게 됩니다`,
      };
    }

    const newTiles = { ...layerData.tiles };
    delete newTiles[position];

    set({
      level: {
        ...level,
        [layerKey]: {
          ...layerData,
          tiles: newTiles,
          num: String(Object.keys(newTiles).length),
        },
      },
      analysisResult: null,
    });

    return { valid: true };
  },

  clearLayer: (layer) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return;

    set({
      level: {
        ...level,
        [layerKey]: {
          ...layerData,
          tiles: {},
          num: '0',
        },
      },
      analysisResult: null,
    });
  },

  fillLayer: (layer, tileData) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return;

    const cols = parseInt(layerData.col);
    const rows = parseInt(layerData.row);
    const newTiles: Record<string, TileData> = {};

    for (let x = 0; x < cols; x++) {
      for (let y = 0; y < rows; y++) {
        newTiles[`${x}_${y}`] = [...tileData] as TileData;
      }
    }

    set({
      level: {
        ...level,
        [layerKey]: {
          ...layerData,
          tiles: newTiles,
          num: String(Object.keys(newTiles).length),
        },
      },
      analysisResult: null,
    });
  },

  // Analysis
  setAnalysisResult: (result) => set({ analysisResult: result }),
  setIsAnalyzing: (isAnalyzing) => set({ isAnalyzing }),

  // Import/Export
  importJson: (json) => {
    try {
      const parsed = JSON.parse(json);

      // Validate basic structure
      if (typeof parsed.layer !== 'number') {
        console.error('Invalid level JSON: missing layer count');
        return false;
      }

      set({ level: parsed as LevelJSON, analysisResult: null });
      return true;
    } catch (e) {
      console.error('Failed to parse JSON:', e);
      return false;
    }
  },

  exportJson: () => {
    const { level } = get();
    return JSON.stringify(level, null, 2);
  },
}));
