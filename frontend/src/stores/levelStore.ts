import { create } from 'zustand';
import type { LevelJSON, TileData, DifficultyReport } from '../types';

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

  // Tile operations
  setTile: (layer: number, x: number, y: number, tileData: TileData) => void;
  removeTile: (layer: number, x: number, y: number) => void;
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

  // Tile operations
  setTile: (layer, x, y, tileData) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return;

    const position = `${x}_${y}`;
    const newTiles = { ...layerData.tiles, [position]: tileData };

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

  removeTile: (layer, x, y) => {
    const { level } = get();
    const layerKey = `layer_${layer}` as `layer_${number}`;
    const layerData = level[layerKey];

    if (!layerData) return;

    const position = `${x}_${y}`;
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
