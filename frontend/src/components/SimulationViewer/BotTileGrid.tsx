import { useMemo, useCallback } from 'react';
import { TILE_TYPES, SPECIAL_IMAGES, GIMMICK_EFFECTS, type TileData, type LevelJSON } from '../../types';
import type { VisualBotResult, VisualBotMove } from '../../types/simulation';
import clsx from 'clsx';

interface BotTileGridProps {
  levelJson: LevelJSON;
  botResult: VisualBotResult;
  currentStep: number;
  initialFrogPositions?: string[]; // Initial frog positions (layerIdx_x_y format)
  initialBombStates?: Record<string, number>; // Initial bomb states (layerIdx_x_y -> count)
  initialCurtainStates?: Record<string, boolean>; // Initial curtain states (layerIdx_x_y -> is_open)
  initialIceStates?: Record<string, number>; // Initial ice states (layerIdx_x_y -> layers 1-3)
  initialChainStates?: Record<string, boolean>; // Initial chain states (layerIdx_x_y -> locked=false)
  initialGrassStates?: Record<string, number>; // Initial grass states (layerIdx_x_y -> layers 1-2)
  initialLinkStates?: Record<string, string[]>; // Initial link states (layerIdx_x_y -> connected positions)
  convertedTiles?: Record<string, Record<string, unknown>>; // Converted tiles from API (t0 -> actual types)
  className?: string;
}

const TILE_SIZE = 40; // Larger for tab view (was 24 for popup)
const GAP_SIZE = 2;
const STACK_TILE_SCALE = 0.75; // Scale for top tile indicator on stack

// Layer brightness: higher layers are brighter, lower layers are dimmer
// Using brightness filter like editor for consistent z-stack display
const getLayerBrightness = (layerIdx: number, totalLayers: number): number => {
  // Bottom layer = 50% brightness, top layer = 100% brightness
  const minBrightness = 0.50;
  const maxBrightness = 1.0;
  if (totalLayers <= 1) return maxBrightness;
  return minBrightness + (maxBrightness - minBrightness) * (layerIdx / (totalLayers - 1));
};

// Stack/Craft tile info for visualization
interface StackTileInfo {
  isStack: boolean;
  isCraft: boolean;
  direction: string; // e/w/s/n
  totalCount: number;
  tileTypes: string[];
  remainingCount: number; // After current step
  originalTileType: string; // Original tile type (e.g., "stack_e", "craft_s")
  spawnOffsetX: number; // Offset for craft spawned tile
  spawnOffsetY: number;
}

// Parse stack/craft info from tile data
const parseStackCraftInfo = (tileData: TileData): StackTileInfo | null => {
  const tileType = tileData[0];
  if (!tileType.startsWith('stack_') && !tileType.startsWith('craft_')) {
    return null;
  }

  const isStack = tileType.startsWith('stack_');
  const isCraft = tileType.startsWith('craft_');
  const direction = tileType.split('_')[1] || 's';

  // Calculate spawn offset for craft tiles
  let spawnOffsetX = 0, spawnOffsetY = 0;
  if (direction === 'e') spawnOffsetX = 1;
  else if (direction === 'w') spawnOffsetX = -1;
  else if (direction === 's') spawnOffsetY = 1;
  else if (direction === 'n') spawnOffsetY = -1;

  // Stack info is in tileData[2] with format [count] - single element array
  // All tiles in stack/craft are "t0" (random) by default
  const stackInfo = tileData[2];
  let totalCount = 1;
  let tileTypes: string[] = ['t0'];

  if (stackInfo && Array.isArray(stackInfo) && stackInfo.length >= 1) {
    totalCount = typeof stackInfo[0] === 'number' ? stackInfo[0] : parseInt(String(stackInfo[0]), 10) || 1;
    // All tiles are t0 (random) - sp_template GetTileIDArr() sets all to "t0"
    tileTypes = Array(totalCount).fill('t0');
  }

  return {
    isStack,
    isCraft,
    direction,
    totalCount,
    tileTypes,
    remainingCount: totalCount,
    originalTileType: tileType,
    spawnOffsetX,
    spawnOffsetY,
  };
};

export function BotTileGrid({
  levelJson,
  botResult,
  currentStep,
  initialFrogPositions = [],
  initialBombStates = {},
  initialCurtainStates = {},
  initialIceStates = {},
  initialChainStates = {},
  initialGrassStates = {},
  initialLinkStates = {},
  convertedTiles,
  className
}: BotTileGridProps) {
  // Helper function to get converted tile type from backend response
  // convertedTiles format: { "layerIdx": { "x_y": [tileType, attribute, ...] } }
  const getConvertedTileType = useCallback((layerIdx: number, pos: string, originalType: string): string => {
    if (!convertedTiles || originalType !== 't0') return originalType;
    const layerData = convertedTiles[String(layerIdx)];
    if (!layerData) return originalType;
    const tileData = layerData[pos] as unknown[];
    if (!tileData || !Array.isArray(tileData) || tileData.length === 0) return originalType;
    return String(tileData[0]) || originalType;
  }, [convertedTiles]);

  // Helper function to get converted stack/craft tile types from backend response
  // Stack/craft tiles have format: [tileType, attribute, [count, "t1_t2_t3..."]]
  // Note: The types array is in bottom-to-top order (index 0 = bottom, index n-1 = top)
  const getConvertedStackTileTypes = useCallback((layerIdx: number, pos: string): string[] | null => {
    if (!convertedTiles) return null;
    const layerData = convertedTiles[String(layerIdx)];
    if (!layerData) return null;
    const tileData = layerData[pos] as unknown[];
    if (!tileData || !Array.isArray(tileData) || tileData.length < 3) return null;
    const stackInfo = tileData[2] as unknown[];
    if (!stackInfo || !Array.isArray(stackInfo) || stackInfo.length < 2) return null;
    const typesStr = String(stackInfo[1] || '');
    if (!typesStr) return null;
    return typesStr.split('_');
  }, [convertedTiles]);
  // Initialize stack/craft tiles info (without move replay - just initial state)
  // This stores the initial configuration of each stack/craft
  const stackCraftInitialInfo = useMemo(() => {
    // Map: layerIdx_pos -> StackTileInfo with initial totalCount
    const stacks = new Map<string, StackTileInfo>();

    for (let layerIdx = 0; layerIdx < levelJson.layer; layerIdx++) {
      const layerKey = `layer_${layerIdx}` as `layer_${number}`;
      const layerData = levelJson[layerKey];
      if (layerData?.tiles) {
        Object.entries(layerData.tiles).forEach(([pos, tileData]) => {
          const info = parseStackCraftInfo(tileData as TileData);
          if (info) {
            stacks.set(`${layerIdx}_${pos}`, info);
          }
        });
      }
    }

    return stacks;
  }, [levelJson]);

  // Extended tile data for stack/craft visualization
  interface ExtendedTileData {
    tileData: TileData;
    stackInfo?: StackTileInfo;
    topTileType?: string; // For stack: the topmost available tile type
    wasT0?: boolean; // Track if this tile was originally t0 (converted from backend)
  }

  // Build the current tile state by replaying moves up to currentStep
  // Now returns tiles organized by layer for proper stacking display
  const { tilesByLayer, spawnedTiles, currentMove, topLayerIdx } = useMemo(() => {
    // Start with initial tiles from level, organized by layer
    // Now stores ExtendedTileData for stack/craft visualization
    const initialTilesByLayer: Map<number, Map<string, ExtendedTileData>> = new Map();
    // Spawned tiles from craft (at offset positions)
    const craftSpawnedTiles: Map<string, { layerIdx: number; pos: string; tileType: string }> = new Map();

    let maxLayer = 0;
    for (let layerIdx = 0; layerIdx < levelJson.layer; layerIdx++) {
      const layerKey = `layer_${layerIdx}` as `layer_${number}`;
      const layerData = levelJson[layerKey];
      if (layerData?.tiles) {
        const layerTiles = new Map<string, ExtendedTileData>();
        Object.entries(layerData.tiles).forEach(([pos, tileData]) => {
          const td = tileData as TileData;
          const key = `${layerIdx}_${pos}`;
          const initialStackInfo = stackCraftInitialInfo.get(key);

          if (initialStackInfo) {
            // Get converted tile types from backend (t0 tiles already converted)
            const convertedTypes = getConvertedStackTileTypes(layerIdx, pos) || initialStackInfo.tileTypes;

            // Calculate topmost tile type for display (use converted types)
            // Initial state: totalCount tiles, topmost is at index totalCount - 1
            const visIdx = initialStackInfo.totalCount - 1;
            const topTileType = convertedTypes[visIdx] || convertedTypes[convertedTypes.length - 1] || 't0';

            console.log(`[DEBUG] Craft/Stack init at ${layerIdx}_${pos}:`);
            console.log(`  isCraft: ${initialStackInfo.isCraft}, totalCount: ${initialStackInfo.totalCount}`);
            console.log(`  convertedTypes: ${convertedTypes}`);
            console.log(`  visIdx: ${visIdx}, topTileType: ${topTileType}`);

            // Store original stack/craft tile with metadata (using converted types)
            // Start with full count - will be decremented during move replay
            layerTiles.set(pos, {
              tileData: td,
              stackInfo: { ...initialStackInfo, tileTypes: convertedTypes, remainingCount: initialStackInfo.totalCount },
              topTileType,
            });

            // For craft tiles, also add the spawned tile at offset position
            // BUT only if the spawn position is not occupied by another tile
            if (initialStackInfo.isCraft) {
              const [x, y] = pos.split('_').map(Number);
              const spawnX = x + initialStackInfo.spawnOffsetX;
              const spawnY = y + initialStackInfo.spawnOffsetY;
              const spawnPos = `${spawnX}_${spawnY}`;
              const spawnKey = `${layerIdx}_${spawnX}_${spawnY}`;

              // Check if spawn position is occupied by another tile in the same layer
              // Get raw level data to check for tile at spawn position
              const spawnOccupied = layerData?.tiles?.[spawnPos] !== undefined;
              console.log(`  spawnPos: ${spawnPos}, spawnOccupied: ${spawnOccupied}`);

              if (!spawnOccupied) {
                craftSpawnedTiles.set(spawnKey, {
                  layerIdx,
                  pos: spawnPos,
                  tileType: topTileType,
                });
                console.log(`  Spawned tile added at ${spawnKey} with type ${topTileType}`);
              }
              // If spawn position is occupied, the craft spawned tile will be added
              // when the occupying tile is removed during move replay
            }
          } else {
            // For regular tiles, apply t0 conversion from backend
            const originalType = td[0];
            const convertedType = getConvertedTileType(layerIdx, pos, originalType);
            // Create new tileData with converted type
            const convertedTileData: TileData = [convertedType, td[1], td[2]];
            // Track if this was originally a t0 tile (now converted)
            const wasT0 = originalType === 't0' && convertedType !== 't0';
            layerTiles.set(pos, { tileData: convertedTileData, wasT0 });
          }
        });
        if (layerTiles.size > 0) {
          initialTilesByLayer.set(layerIdx, layerTiles);
          maxLayer = Math.max(maxLayer, layerIdx);
        }
      }
    }

    // Clone to working state (deep clone stackInfo objects)
    const workingTilesByLayer = new Map<number, Map<string, ExtendedTileData>>();
    initialTilesByLayer.forEach((tiles, layerIdx) => {
      const clonedLayer = new Map<string, ExtendedTileData>();
      tiles.forEach((extData, pos) => {
        clonedLayer.set(pos, {
          ...extData,
          stackInfo: extData.stackInfo ? { ...extData.stackInfo } : undefined,
        });
      });
      workingTilesByLayer.set(layerIdx, clonedLayer);
    });
    const workingSpawnedTiles = new Map(craftSpawnedTiles);

    // Replay moves up to currentStep
    let currentMoveData: VisualBotMove | null = null;
    const justRemoved = new Set<string>();

    for (let i = 0; i < Math.min(currentStep, botResult.moves.length); i++) {
      const move = botResult.moves[i];
      currentMoveData = move;

      // Check if this move is from a craft's spawned tile
      const spawnedKey = `${move.layer_idx}_${move.position}`;
      if (workingSpawnedTiles.has(spawnedKey)) {
        // Find the craft box that spawned this tile by checking all layer tiles
        for (const [layerIdx, layerTiles] of workingTilesByLayer.entries()) {
          if (layerIdx !== move.layer_idx) continue;

          for (const [pos, extData] of layerTiles.entries()) {
            if (extData.stackInfo?.isCraft) {
              const [sx, sy] = pos.split('_').map(Number);
              const spawnX = sx + extData.stackInfo.spawnOffsetX;
              const spawnY = sy + extData.stackInfo.spawnOffsetY;

              if (move.position === `${spawnX}_${spawnY}`) {
                // This craft box spawned the picked tile
                const currentRemaining = extData.stackInfo.remainingCount || 1;
                const newRemaining = currentRemaining - 1;

                console.log(`[DEBUG] Craft pick from ${pos} -> ${move.position}:`);
                console.log(`  Backend move.tile_type: ${move.tile_type}`);
                console.log(`  Current displayed: ${workingSpawnedTiles.get(spawnedKey)?.tileType}`);
                console.log(`  tileTypes array: ${extData.stackInfo.tileTypes}`);
                console.log(`  remaining: ${currentRemaining} -> ${newRemaining}`);

                if (newRemaining > 0) {
                  // Update spawned tile to next type
                  const nextVisIdx = newRemaining - 1;
                  const nextTileType = extData.stackInfo.tileTypes[nextVisIdx] || 't0';
                  console.log(`  nextVisIdx: ${nextVisIdx}, nextTileType: ${nextTileType}`);
                  workingSpawnedTiles.set(spawnedKey, {
                    layerIdx: move.layer_idx,
                    pos: move.position,
                    tileType: nextTileType,
                  });

                  // Update the craft box tile display
                  extData.topTileType = nextTileType;
                  extData.stackInfo.remainingCount = newRemaining;
                } else {
                  console.log(`  Craft exhausted`);
                  // Craft box is empty - remove both craft box and spawned tile
                  workingSpawnedTiles.delete(spawnedKey);
                  layerTiles.delete(pos);
                }
                break;
              }
            }
          }
        }
      } else {
        // Regular tile or stack tile removal
        const layerTiles = workingTilesByLayer.get(move.layer_idx);
        if (layerTiles) {
          const existingTile = layerTiles.get(move.position);

          if (existingTile?.stackInfo?.isStack) {
            // Stack tile - update remaining count
            const currentRemaining = existingTile.stackInfo.remainingCount || 1;
            const newRemaining = currentRemaining - 1;
            if (newRemaining > 0) {
              const nextVisIdx = newRemaining - 1;
              const nextTileType = existingTile.stackInfo.tileTypes[nextVisIdx] || 't0';
              existingTile.topTileType = nextTileType;
              existingTile.stackInfo.remainingCount = newRemaining;
            } else {
              // Stack is empty - remove it
              layerTiles.delete(move.position);
            }
          } else {
            // Regular tile - remove it
            layerTiles.delete(move.position);
          }
        }
      }

      // Remove matched tiles (tiles that completed a 3-match in dock)
      move.matched_positions.forEach((matchedKey) => {
        const parts = matchedKey.split('_');
        if (parts.length >= 3) {
          const matchedLayerIdx = parseInt(parts[0], 10);
          const matchedPos = parts.slice(1).join('_');

          const matchedLayerTiles = workingTilesByLayer.get(matchedLayerIdx);
          if (matchedLayerTiles?.has(matchedPos)) {
            matchedLayerTiles.delete(matchedPos);
            if (i === currentStep - 1) {
              justRemoved.add(`${matchedLayerIdx}_${matchedPos}`);
            }
          }
        }
      });

      // Mark the selected tile as just removed if it's the current move
      if (i === currentStep - 1) {
        justRemoved.add(`${move.layer_idx}_${move.position}`);
      }

      // After each move, check if any blocked craft tiles can now emit
      // A craft is blocked if its spawn position is occupied by another tile
      for (const [layerIdx, layerTiles] of workingTilesByLayer.entries()) {
        for (const [pos, extData] of layerTiles.entries()) {
          if (extData.stackInfo?.isCraft && (extData.stackInfo.remainingCount || 0) > 0) {
            const [sx, sy] = pos.split('_').map(Number);
            const spawnX = sx + extData.stackInfo.spawnOffsetX;
            const spawnY = sy + extData.stackInfo.spawnOffsetY;
            const spawnKey = `${layerIdx}_${spawnX}_${spawnY}`;
            const spawnPos = `${spawnX}_${spawnY}`;

            // Skip if already spawned
            if (workingSpawnedTiles.has(spawnKey)) continue;

            // Check if spawn position is now empty (no tile at that position in same layer)
            const spawnOccupied = layerTiles.has(spawnPos);

            if (!spawnOccupied) {
              // Spawn position is now empty - add the craft spawned tile
              if (extData.topTileType) {
                workingSpawnedTiles.set(spawnKey, {
                  layerIdx,
                  pos: spawnPos,
                  tileType: extData.topTileType,
                });
              }
            }
          }
        }
      }
    }

    return {
      tilesByLayer: workingTilesByLayer,
      spawnedTiles: workingSpawnedTiles,
      currentMove: currentMoveData,
      // removedTiles: justRemoved, // No longer used with layer-based rendering
      topLayerIdx: maxLayer,
    };
  }, [levelJson, botResult.moves, currentStep, stackCraftInitialInfo, getConvertedTileType, getConvertedStackTileTypes]);

  // Get grid dimensions from the top layer (usually the largest)
  const gridInfo = useMemo(() => {
    let maxCols = 0;
    let maxRows = 0;

    for (let i = 0; i < levelJson.layer; i++) {
      const layerKey = `layer_${i}` as `layer_${number}`;
      const layerData = levelJson[layerKey];
      if (layerData) {
        maxCols = Math.max(maxCols, parseInt(layerData.col) || 0);
        maxRows = Math.max(maxRows, parseInt(layerData.row) || 0);
      }
    }

    return { cols: maxCols, rows: maxRows };
  }, [levelJson]);

  // Find the tile being selected in the current move (before it's removed)
  const highlightedTile = useMemo(() => {
    if (currentStep > 0 && currentStep <= botResult.moves.length) {
      const move = botResult.moves[currentStep - 1];
      return `${move.layer_idx}_${move.position}`;
    }
    return null;
  }, [currentStep, botResult.moves]);

  // Get current frog positions based on step
  // When game is over, keep the last state
  const currentFrogPositions = useMemo(() => {
    if (currentStep === 0) {
      // At step 0, use initial frog positions
      return new Set(initialFrogPositions);
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      // Use frog positions from the current move (or last move if game over)
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return new Set(move.frog_positions_after || []);
    }
    return new Set<string>();
  }, [currentStep, botResult.moves, initialFrogPositions]);

  // Get current bomb states based on step
  // When game is over, keep the last state
  const currentBombStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialBombStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.bomb_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialBombStates]);

  // Get current curtain states based on step
  // When game is over, keep the last state
  const currentCurtainStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialCurtainStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.curtain_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialCurtainStates]);

  // Get current ice states based on step
  // When game is over, keep the last state
  const currentIceStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialIceStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.ice_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialIceStates]);

  // Get current chain states based on step
  // When game is over, keep the last state
  const currentChainStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialChainStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.chain_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialChainStates]);

  // Get current grass states based on step
  // When game is over, keep the last state
  const currentGrassStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialGrassStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.grass_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialGrassStates]);

  // Get current link states based on step
  // When game is over, keep the last state
  const currentLinkStates = useMemo(() => {
    if (currentStep === 0) {
      return { ...initialLinkStates };
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      const move = botResult.moves[moveIdx];
      return move.link_states_after || {};
    }
    return {};
  }, [currentStep, botResult.moves, initialLinkStates]);

  // Get layer cols for blocking calculation (sp_template uses col comparison)
  const layerCols = useMemo(() => {
    const cols: Record<number, number> = {};
    for (let i = 0; i < levelJson.layer; i++) {
      const layerKey = `layer_${i}` as `layer_${number}`;
      const layerData = levelJson[layerKey];
      cols[i] = layerData ? parseInt(layerData.col) || 7 : 7;
    }
    return cols;
  }, [levelJson]);

  // Check if a tile is blocked by upper layer tiles
  // Based on sp_template TileGroup.FindAllUpperTiles logic
  const isBlockedByUpper = useCallback((
    layerIdx: number,
    x: number,
    y: number,
    currentTilesByLayer: Map<number, Map<string, ExtendedTileData>>
  ): boolean => {
    const tileParity = layerIdx % 2;
    const curLayerCol = layerCols[layerIdx] || 7;
    const maxLayer = Math.max(...Array.from(currentTilesByLayer.keys()));

    for (let upperLayerIdx = layerIdx + 1; upperLayerIdx <= maxLayer; upperLayerIdx++) {
      const upperLayer = currentTilesByLayer.get(upperLayerIdx);
      if (!upperLayer || upperLayer.size === 0) continue;

      const upperParity = upperLayerIdx % 2;
      const upperLayerCol = layerCols[upperLayerIdx] || 7;

      // Determine blocking offsets based on parity and layer size
      let blockingOffsets: [number, number][];
      if (tileParity === upperParity) {
        // Same parity: only check same position
        blockingOffsets = [[0, 0]];
      } else {
        // Different parity: compare layer col sizes
        if (upperLayerCol > curLayerCol) {
          // Upper layer is bigger
          blockingOffsets = [[0, 0], [1, 0], [0, 1], [1, 1]];
        } else {
          // Upper layer is smaller or same size
          blockingOffsets = [[-1, -1], [0, -1], [-1, 0], [0, 0]];
        }
      }

      for (const [dx, dy] of blockingOffsets) {
        const bx = x + dx;
        const by = y + dy;
        const posKey = `${bx}_${by}`;
        if (upperLayer.has(posKey)) {
          return true;
        }
      }
    }
    return false;
  }, [layerCols]);

  // Check if a tile can be picked based on its gimmick state
  const canTileBePicked = useCallback((
    tileKey: string,  // layerIdx_x_y format
    attribute: string
  ): boolean => {
    // Check frog (blocks any tile)
    if (currentFrogPositions.has(tileKey)) {
      return false;
    }

    // Check ice (remaining layers > 0 means blocked)
    const iceLevel = currentIceStates[tileKey];
    if (typeof iceLevel === 'number' && iceLevel > 0) {
      return false;
    }

    // Check chain (unlocked = true means can pick, locked = false means blocked)
    const chainUnlocked = currentChainStates[tileKey];
    if (typeof chainUnlocked === 'boolean' && !chainUnlocked) {
      return false;
    }

    // Check grass (remaining layers > 0 means blocked)
    const grassLevel = currentGrassStates[tileKey];
    if (typeof grassLevel === 'number' && grassLevel > 0) {
      return false;
    }

    // Check curtain (is_open = false means blocked)
    const curtainOpen = currentCurtainStates[tileKey];
    if (typeof curtainOpen === 'boolean' && !curtainOpen) {
      return false;
    }

    // Check link (need to verify both tiles can be picked)
    // For now, simplified check - if attribute contains link, check link states
    if (attribute.includes('link')) {
      const linkedPositions = currentLinkStates[tileKey];
      if (linkedPositions && linkedPositions.length > 0) {
        // Link tiles need special handling - for now assume pickable if link exists
        // A more complete implementation would check if the linked tile is also available
      }
    }

    return true;
  }, [currentFrogPositions, currentIceStates, currentChainStates, currentGrassStates, currentCurtainStates, currentLinkStates]);

  // Calculate pickable tiles (not blocked by upper layers AND gimmick allows)
  const pickableTiles = useMemo(() => {
    const pickable = new Set<string>();

    tilesByLayer.forEach((layerTiles, layerIdx) => {
      layerTiles.forEach((extData, pos) => {
        const [x, y] = pos.split('_').map(Number);
        const tileKey = `${layerIdx}_${pos}`;

        // First check: not blocked by upper layers
        if (isBlockedByUpper(layerIdx, x, y, tilesByLayer)) {
          return;
        }

        // Second check: gimmick allows picking
        const attribute = extData.tileData[1] || '';
        if (!canTileBePicked(tileKey, attribute)) {
          return;
        }

        pickable.add(tileKey);
      });
    });

    // Also check spawned tiles (from craft)
    spawnedTiles.forEach((_, spawnedKey) => {
      const parts = spawnedKey.split('_');
      if (parts.length >= 3) {
        const layerIdx = parseInt(parts[0], 10);
        const x = parseInt(parts[1], 10);
        const y = parseInt(parts[2], 10);

        // Check if blocked by upper layers
        if (!isBlockedByUpper(layerIdx, x, y, tilesByLayer)) {
          // Check frog
          if (!currentFrogPositions.has(spawnedKey)) {
            pickable.add(spawnedKey);
          }
        }
      }
    });

    return pickable;
  }, [tilesByLayer, spawnedTiles, isBlockedByUpper, canTileBePicked, currentFrogPositions]);

  // Total number of layers for opacity calculation
  const totalLayers = topLayerIdx + 1;

  // Get stack/craft gimmick image path
  const getStackCraftImage = (stackInfo: StackTileInfo): string | null => {
    if (stackInfo.isStack) {
      // Stack uses direction-specific icon
      return SPECIAL_IMAGES[`stack_${stackInfo.direction}`] || SPECIAL_IMAGES['stack_s'];
    } else if (stackInfo.isCraft) {
      // Craft uses craft icon
      return SPECIAL_IMAGES['craft'];
    }
    return null;
  };

  // Render a stack/craft tile with gimmick icon and top tile indicator
  const renderStackCraftTile = (
    layerIdx: number,
    pos: string,
    extData: { tileData: TileData; stackInfo: StackTileInfo; topTileType?: string },
    isHighlighted: boolean,
    hasFrog: boolean,
    brightness: number
  ) => {
    const { stackInfo, topTileType } = extData;
    const gimmickImage = getStackCraftImage(stackInfo);
    const topTileInfo = topTileType ? TILE_TYPES[topTileType] : null;
    const brightnessPercent = Math.round(brightness * 100);

    return (
      <div
        key={`${layerIdx}_${pos}_gimmick`}
        className={clsx(
          'relative flex items-center justify-center overflow-hidden transition-all duration-200',
          isHighlighted && 'ring-2 ring-yellow-400 scale-110',
          hasFrog && 'ring-2 ring-green-400'
        )}
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          filter: `brightness(${brightnessPercent}%)`,
        }}
      >
        {/* Gimmick icon (stack/craft) as base */}
        {gimmickImage ? (
          <img
            src={gimmickImage}
            alt={stackInfo.isStack ? 'Stack' : 'Craft'}
            className="w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-[6px] font-bold bg-purple-600"
          >
            <span className="text-white">{stackInfo.isStack ? 'STK' : 'CRF'}</span>
          </div>
        )}

        {/* Top tile indicator (0.75 scale) - only for stack tiles */}
        {stackInfo.isStack && topTileInfo && (
          <div
            className="absolute flex items-center justify-center rounded-sm overflow-hidden"
            style={{
              width: TILE_SIZE * STACK_TILE_SCALE,
              height: TILE_SIZE * STACK_TILE_SCALE,
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
            }}
          >
            {topTileInfo.image ? (
              <img
                src={topTileInfo.image}
                alt={topTileInfo.name}
                className="w-full h-full object-cover"
                draggable={false}
              />
            ) : (
              <div
                className="w-full h-full flex items-center justify-center text-[6px] font-bold"
                style={{ backgroundColor: topTileInfo.color || '#888' }}
              >
                <span className="text-white">{topTileType}</span>
              </div>
            )}
          </div>
        )}

        {/* Remaining count badge */}
        <div
          className="absolute bottom-0 right-0 w-4 h-3 text-[7px] bg-black/70 text-white flex items-center justify-center rounded-tl"
          title={`남은 타일: ${stackInfo.remainingCount}`}
        >
          {stackInfo.remainingCount}
        </div>

        {/* Layer indicator badge */}
        {layerIdx > 0 && (
          <div
            className="absolute top-0 right-0 w-3 h-3 text-[6px] bg-black/50 text-white flex items-center justify-center rounded-bl"
          >
            {layerIdx}
          </div>
        )}
      </div>
    );
  };

  // Render a spawned tile from craft (at offset position)
  const renderSpawnedTile = (
    layerIdx: number,
    pos: string,
    tileType: string,
    isHighlighted: boolean,
    hasFrog: boolean,
    brightness: number
  ) => {
    const tileInfo = TILE_TYPES[tileType];
    const brightnessPercent = Math.round(brightness * 100);

    return (
      <div
        key={`${layerIdx}_${pos}_spawned`}
        className={clsx(
          'relative flex items-center justify-center overflow-hidden transition-all duration-200',
          isHighlighted && 'ring-2 ring-yellow-400 scale-110',
          hasFrog && 'ring-2 ring-green-400'
        )}
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          filter: `brightness(${brightnessPercent}%)`,
        }}
      >
        {tileInfo?.image ? (
          <img
            src={tileInfo.image}
            alt={tileInfo.name}
            className="w-full h-full object-cover"
            draggable={false}
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-[8px] font-bold"
            style={{ backgroundColor: tileInfo?.color || '#888' }}
          >
            <span className="text-white">{tileType}</span>
          </div>
        )}
        {/* Frog indicator */}
        {hasFrog && (
          <div
            className="absolute bottom-0 left-0 w-3 h-3 text-[8px] flex items-center justify-center"
            title="개구리"
          >
            🐸
          </div>
        )}
        {/* Layer indicator badge */}
        {layerIdx > 0 && (
          <div
            className="absolute top-0 right-0 w-3 h-3 text-[6px] bg-black/50 text-white flex items-center justify-center rounded-bl"
          >
            {layerIdx}
          </div>
        )}
      </div>
    );
  };

  // Render a regular tile at a specific layer
  const renderRegularTile = (
    layerIdx: number,
    pos: string,
    tileData: TileData,
    isHighlighted: boolean,
    hasFrog: boolean,
    brightness: number,
    wasT0?: boolean
  ) => {
    const [tileType, attribute] = tileData;
    const tileInfo = TILE_TYPES[tileType];
    const tileKey = `${layerIdx}_${pos}`;
    const brightnessPercent = Math.round(brightness * 100);

    // Get gimmick states from backend tracking (more accurate than attribute parsing)
    const bombRemaining = currentBombStates[tileKey];
    const isBomb = attribute === 'bomb' || typeof bombRemaining === 'number';

    const isCurtain = attribute?.startsWith('curtain') || tileKey in currentCurtainStates;
    const isCurtainOpen = isCurtain ? (currentCurtainStates[tileKey] ?? attribute === 'curtain_open') : false;

    const isTeleport = attribute === 'teleport';

    // Ice: use backend state for level tracking (handles melting)
    const backendIceLevel = currentIceStates[tileKey];
    const isIce = attribute?.startsWith('ice') || typeof backendIceLevel === 'number';
    const iceLevel = backendIceLevel ?? (isIce && attribute ? parseInt(attribute.split('_')[1] || '1', 10) : 0);

    // Chain: use backend state for unlock tracking
    const backendChainUnlocked = currentChainStates[tileKey];
    const isChain = attribute === 'chain' || typeof backendChainUnlocked === 'boolean';
    const isChainUnlocked = backendChainUnlocked ?? false;

    // Grass: use backend state for layer tracking
    const backendGrassLevel = currentGrassStates[tileKey];
    const isGrass = attribute?.startsWith('grass') || typeof backendGrassLevel === 'number';
    const grassLevel = backendGrassLevel ?? (isGrass && attribute ? parseInt(attribute.split('_')[1] || '1', 10) : 0);

    // Link: use backend state for connection tracking
    const linkedPositions = currentLinkStates[tileKey];
    const isLink = attribute?.startsWith('link_') || (linkedPositions && linkedPositions.length > 0);

    // Get gimmick effect info for display
    const gimmickEffect = attribute ? GIMMICK_EFFECTS[attribute] : null;

    // Check if any gimmick is active (for border styling)
    const hasActiveGimmick = (isIce && iceLevel > 0) || isChain || (isGrass && grassLevel > 0) || isLink || isBomb || isCurtain || isTeleport;

    // Get gimmick border color
    const getGimmickBorderColor = () => {
      if (isIce && iceLevel > 0) return `rgba(96, 165, 250, ${0.5 + iceLevel * 0.15})`;
      if (isChain) return isChainUnlocked ? 'rgba(74, 222, 128, 0.6)' : 'rgba(161, 161, 170, 0.6)';
      if (isGrass && grassLevel > 0) return `rgba(34, 197, 94, ${0.5 + grassLevel * 0.15})`;
      if (isLink) return 'rgba(234, 179, 8, 0.6)';
      if (isBomb) return bombRemaining !== undefined && bombRemaining <= 3 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(239, 68, 68, 0.5)';
      if (isCurtain) return isCurtainOpen ? 'rgba(168, 85, 247, 0.4)' : 'rgba(124, 58, 237, 0.6)';
      if (isTeleport) return 'rgba(6, 182, 212, 0.6)';
      return 'transparent';
    };

    return (
      <div
        key={tileKey}
        className={clsx(
          'relative flex items-center justify-center transition-all duration-200',
          isHighlighted && 'ring-2 ring-yellow-400 scale-110',
          isCurtain && !isCurtainOpen && 'grayscale',
          isBomb && bombRemaining !== undefined && bombRemaining <= 3 && 'animate-pulse'
        )}
        style={{
          width: TILE_SIZE,
          height: TILE_SIZE,
          filter: `brightness(${brightnessPercent}%)`,
          border: hasActiveGimmick ? `2px solid ${getGimmickBorderColor()}` : undefined,
        }}
        title={gimmickEffect?.description}
      >
        {/* t0 (random tile) indicator - shows border frame BEHIND tile image (same size as tile) */}
        {wasT0 && (
          <div
            className="absolute inset-0 flex items-center justify-center pointer-events-none"
            style={{ zIndex: 0 }}
            title="랜덤 타일 (t0)"
          >
            <img
              src="/tiles/skin0/s0_t0.png"
              alt="t0"
              className="w-full h-full object-contain"
            />
          </div>
        )}

        {/* Base tile image - ALWAYS displayed ON TOP of t0 indicator */}
        {tileInfo?.image ? (
          <img
            src={tileInfo.image}
            alt={tileInfo.name}
            className="w-full h-full object-cover overflow-hidden relative"
            style={{ zIndex: 1 }}
            draggable={false}
          />
        ) : (
          <div
            className="w-full h-full flex items-center justify-center text-[8px] font-bold relative"
            style={{ backgroundColor: tileInfo?.color || '#888', zIndex: 1 }}
          >
            <span className="text-white">{tileType.replace('_s', '')}</span>
          </div>
        )}

        {/* Gimmick indicator - small icon at bottom left (like frog) */}
        {/* Ice gimmick */}
        {isIce && iceLevel > 0 && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 flex items-center justify-center rounded-tr',
              'bg-blue-500/80 text-white',
              iceLevel === 1 && 'animate-pulse'
            )}
            style={{ width: 18, height: 14 }}
            title={`얼음 ${iceLevel}단계 - 타일 제거 시 녹음`}
          >
            <span className="text-[9px]">❄️{iceLevel}</span>
          </div>
        )}

        {/* Chain gimmick */}
        {isChain && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 flex items-center justify-center rounded-tr',
              isChainUnlocked ? 'bg-green-500/80' : 'bg-gray-600/80',
              'text-white'
            )}
            style={{ width: 16, height: 14 }}
            title={isChainUnlocked ? '체인 해제됨' : '체인 잠김'}
          >
            <span className="text-[9px]">{isChainUnlocked ? '🔓' : '⛓️'}</span>
          </div>
        )}

        {/* Grass gimmick */}
        {isGrass && grassLevel > 0 && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 flex items-center justify-center rounded-tr',
              'bg-green-600/80 text-white',
              grassLevel === 1 && 'animate-pulse'
            )}
            style={{ width: 18, height: 14 }}
            title={`풀 ${grassLevel}단계`}
          >
            <span className="text-[9px]">{grassLevel === 1 ? '🌱' : '🌿'}{grassLevel}</span>
          </div>
        )}

        {/* Link gimmick */}
        {isLink && (
          <div
            className="absolute bottom-0 left-0 flex items-center justify-center rounded-tr bg-yellow-500/80 text-white"
            style={{ width: 16, height: 14 }}
            title={`링크 연결: ${linkedPositions?.join(', ') || '없음'}`}
          >
            <span className="text-[9px]">🔗</span>
          </div>
        )}

        {/* Bomb gimmick */}
        {isBomb && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 flex items-center justify-center rounded-tr text-white',
              bombRemaining !== undefined && bombRemaining <= 2 ? 'bg-red-600/90 animate-pulse' :
              bombRemaining !== undefined && bombRemaining <= 5 ? 'bg-orange-500/80' :
              'bg-gray-700/80'
            )}
            style={{ width: 18, height: 14 }}
            title={`폭탄 ${bombRemaining ?? '?'}턴`}
          >
            <span className="text-[9px]">💣{bombRemaining ?? ''}</span>
          </div>
        )}

        {/* Curtain gimmick */}
        {isCurtain && (
          <div
            className={clsx(
              'absolute bottom-0 left-0 flex items-center justify-center rounded-tr text-white',
              isCurtainOpen ? 'bg-purple-400/80' : 'bg-purple-700/80'
            )}
            style={{ width: 16, height: 14 }}
            title={isCurtainOpen ? '커튼 열림' : '커튼 닫힘'}
          >
            <span className="text-[9px]">{isCurtainOpen ? '🎭' : '🎪'}</span>
          </div>
        )}

        {/* Teleport gimmick */}
        {isTeleport && (
          <div
            className="absolute bottom-0 left-0 flex items-center justify-center rounded-tr bg-cyan-500/80 text-white"
            style={{ width: 16, height: 14 }}
            title="텔레포트"
          >
            <span className="text-[9px]">🌀</span>
          </div>
        )}

        {/* Frog indicator - shows when frog is on this tile (bottom right to avoid overlap) */}
        {hasFrog && (
          <div
            className="absolute bottom-0 right-0 flex items-center justify-center rounded-tl bg-green-600/80"
            style={{ width: 16, height: 14 }}
            title="개구리"
          >
            <span className="text-[9px]">🐸</span>
          </div>
        )}

        {/* Layer indicator badge */}
        {layerIdx > 0 && (
          <div
            className="absolute top-0 right-0 w-4 h-4 text-[8px] bg-black/50 text-white flex items-center justify-center rounded-bl"
            style={{ zIndex: 2 }}
          >
            {layerIdx}
          </div>
        )}
      </div>
    );
  };

  const gridWidth = gridInfo.cols * TILE_SIZE + (gridInfo.cols - 1) * GAP_SIZE;
  const gridHeight = gridInfo.rows * TILE_SIZE + (gridInfo.rows - 1) * GAP_SIZE;

  // Render a single tile at a specific layer (for layer-based rendering)
  const renderTileAtLayer = (layerIdx: number, x: number, y: number) => {
    const pos = `${x}_${y}`;
    const layerTiles = tilesByLayer.get(layerIdx);
    const extData = layerTiles?.get(pos);

    // Check for spawned tiles from craft at this position
    const spawnedKey = `${layerIdx}_${pos}`;
    const spawnedTile = spawnedTiles.get(spawnedKey);

    // Empty cell at this layer
    if (!extData && !spawnedTile) {
      return (
        <div
          key={`${layerIdx}_${pos}`}
          style={{ width: TILE_SIZE, height: TILE_SIZE }}
        />
      );
    }

    const tileKey = `${layerIdx}_${pos}`;
    const isHighlighted = highlightedTile === tileKey;
    const hasFrog = currentFrogPositions.has(tileKey);
    const isPickable = pickableTiles.has(tileKey);

    // Pickable tiles get full brightness (100%), non-pickable get layer-based dimming
    const brightness = isPickable ? 1.0 : getLayerBrightness(layerIdx, totalLayers);

    if (spawnedTile) {
      return renderSpawnedTile(layerIdx, pos, spawnedTile.tileType, isHighlighted, hasFrog, brightness);
    } else if (extData?.stackInfo) {
      return renderStackCraftTile(
        layerIdx,
        pos,
        extData as { tileData: TileData; stackInfo: StackTileInfo; topTileType?: string },
        isHighlighted,
        hasFrog,
        brightness
      );
    } else if (extData) {
      return renderRegularTile(layerIdx, pos, extData.tileData, isHighlighted, hasFrog, brightness, extData.wasT0);
    }

    return (
      <div
        key={`${layerIdx}_${pos}`}
        style={{ width: TILE_SIZE, height: TILE_SIZE }}
      />
    );
  };

  // Render a layer grid as an overlay
  // Odd/even layers alternate offset: layer 0, 2, 4... have same pivot, layer 1, 3, 5... offset by 0.5, 0.5
  const renderLayerGrid = (layerIdx: number) => {
    // Calculate offset based on odd/even layer index
    // Even layers (0, 2, 4...) - no offset (same pivot)
    // Odd layers (1, 3, 5...) - offset by 0.5 tile
    const isOddLayer = layerIdx % 2 === 1;
    const offsetX = isOddLayer ? (TILE_SIZE * 0.5) : 0;
    const offsetY = isOddLayer ? (TILE_SIZE * 0.5) : 0;

    // Note: brightness is now applied per-tile based on pickability, not per-layer
    return (
      <div
        key={`layer-${layerIdx}`}
        className="absolute pointer-events-none"
        style={{
          zIndex: layerIdx,
          left: offsetX,
          top: offsetY,
        }}
      >
        <div
          className="grid"
          style={{
            gridTemplateColumns: `repeat(${gridInfo.cols}, ${TILE_SIZE}px)`,
            gap: `${GAP_SIZE}px`,
          }}
        >
          {Array.from({ length: gridInfo.rows }, (_, y) =>
            Array.from({ length: gridInfo.cols }, (_, x) =>
              renderTileAtLayer(layerIdx, x, y)
            )
          )}
        </div>
      </div>
    );
  };

  // Calculate extra space needed for layer offsets (only 0.5 tile max for odd layers)
  const maxLayerOffset = TILE_SIZE * 0.5;

  return (
    <div className={clsx('flex flex-col items-center', className)}>
      {/* Grid with stacked layers */}
      <div
        className="bg-gray-900 rounded p-2"
        style={{
          width: gridWidth + 16 + maxLayerOffset,
          height: gridHeight + 16 + maxLayerOffset
        }}
      >
        <div
          className="relative"
          style={{
            width: gridWidth + maxLayerOffset,
            height: gridHeight + maxLayerOffset,
          }}
        >
          {/* Base grid for empty cells - positioned at layer 0 (even layer, no offset) */}
          <div
            className="absolute grid"
            style={{
              gridTemplateColumns: `repeat(${gridInfo.cols}, ${TILE_SIZE}px)`,
              gap: `${GAP_SIZE}px`,
              left: 0,
              top: 0,
            }}
          >
            {Array.from({ length: gridInfo.rows }, (_, y) =>
              Array.from({ length: gridInfo.cols }, (_, x) => (
                <div
                  key={`base_${x}_${y}`}
                  style={{
                    width: TILE_SIZE,
                    height: TILE_SIZE,
                    backgroundColor: '#1f2937',
                    border: '1px solid #374151',
                  }}
                />
              ))
            )}
          </div>

          {/* Render each layer as overlay (bottom to top) */}
          {Array.from({ length: topLayerIdx + 1 }, (_, layerIdx) =>
            renderLayerGrid(layerIdx)
          )}
        </div>
      </div>

      {/* Current move info */}
      {currentMove && currentStep > 0 && (
        <div className="mt-1 text-[10px] text-gray-400 text-center">
          {currentMove.decision_reason}
        </div>
      )}
    </div>
  );
}
