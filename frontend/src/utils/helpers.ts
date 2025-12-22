import type { LevelJSON, DifficultyGrade, TileData } from '../types';
import { GRADE_COLORS, GRADE_DESCRIPTIONS } from '../types';

/**
 * Get color for a difficulty grade.
 */
export function getGradeColor(grade: DifficultyGrade): string {
  return GRADE_COLORS[grade] || '#888888';
}

/**
 * Get description for a difficulty grade.
 */
export function getGradeDescription(grade: DifficultyGrade): string {
  return GRADE_DESCRIPTIONS[grade] || '알 수 없음';
}

/**
 * Format a score as percentage string.
 */
export function formatScore(score: number): string {
  return `${score.toFixed(1)}`;
}

/**
 * Format difficulty as percentage.
 */
export function formatDifficulty(difficulty: number): string {
  return `${(difficulty * 100).toFixed(0)}%`;
}

/**
 * Get tile count from a level.
 */
export function getTileCount(level: LevelJSON): number {
  let count = 0;
  for (let i = 0; i < level.layer; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layer = level[layerKey];
    if (layer?.tiles) {
      count += Object.keys(layer.tiles).length;
    }
  }
  return count;
}

/**
 * Tile validation result type.
 */
export interface TileValidationResult {
  totalTiles: number;
  isValid: boolean;
  remainder: number;
  message: string;
}

/**
 * Check if level has a valid tile count (multiple of 3).
 * Includes tiles inside stack/craft boxes.
 * @param level Level JSON to validate
 * @returns Validation result with total count, validity, and message
 */
export function validateTileCount(level: LevelJSON): TileValidationResult {
  let totalTiles = 0;

  for (let i = 0; i < level.layer; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layer = level[layerKey];
    if (!layer?.tiles) continue;

    for (const [_pos, tileData] of Object.entries(layer.tiles)) {
      const tileType = tileData[0];
      const extra = tileData[2];

      // Check if this is a stack/craft tile with hidden tiles
      if (tileType.startsWith('stack_') || tileType.startsWith('craft_')) {
        // stack/craft tile extra format: [count] or [count, "t1_t2_t3"]
        if (extra && Array.isArray(extra) && extra.length >= 1) {
          const tileCount = typeof extra[0] === 'number' ? extra[0] : 1;
          totalTiles += tileCount;
        } else {
          // Default to 1 if no extra info
          totalTiles += 1;
        }
      } else {
        // Regular tile counts as 1
        totalTiles += 1;
      }
    }
  }

  const remainder = totalTiles % 3;
  const isValid = remainder === 0;

  let message = '';
  if (!isValid) {
    if (remainder === 1) {
      message = `타일 ${totalTiles}개 (3의 배수가 아님 - 1개 초과 또는 2개 부족)`;
    } else {
      message = `타일 ${totalTiles}개 (3의 배수가 아님 - 2개 초과 또는 1개 부족)`;
    }
  } else {
    message = `타일 ${totalTiles}개 (${totalTiles / 3}세트)`;
  }

  return {
    totalTiles,
    isValid,
    remainder,
    message,
  };
}

/**
 * Get active layer count from a level.
 */
export function getActiveLayerCount(level: LevelJSON): number {
  let count = 0;
  for (let i = 0; i < level.layer; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layer = level[layerKey];
    if (layer?.tiles && Object.keys(layer.tiles).length > 0) {
      count++;
    }
  }
  return count;
}

/**
 * Parse position string to coordinates.
 */
export function parsePosition(pos: string): [number, number] {
  const [x, y] = pos.split('_').map(Number);
  return [x, y];
}

/**
 * Create position string from coordinates.
 */
export function createPosition(x: number, y: number): string {
  return `${x}_${y}`;
}

/**
 * Validate level JSON structure.
 */
export function validateLevelJson(level: unknown): level is LevelJSON {
  if (typeof level !== 'object' || level === null) {
    return false;
  }

  const obj = level as Record<string, unknown>;

  if (typeof obj.layer !== 'number' || obj.layer < 1) {
    return false;
  }

  for (let i = 0; i < obj.layer; i++) {
    const layerKey = `layer_${i}`;
    const layer = obj[layerKey];

    if (typeof layer !== 'object' || layer === null) {
      return false;
    }

    const layerObj = layer as Record<string, unknown>;

    if (
      typeof layerObj.col !== 'string' ||
      typeof layerObj.row !== 'string' ||
      typeof layerObj.tiles !== 'object' ||
      typeof layerObj.num !== 'string'
    ) {
      return false;
    }
  }

  return true;
}

/**
 * Deep clone a level JSON.
 */
export function cloneLevel(level: LevelJSON): LevelJSON {
  return JSON.parse(JSON.stringify(level));
}

/**
 * Download content as a file.
 */
export function downloadFile(content: string, filename: string, type: string = 'application/json'): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Read file content as string.
 */
export function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsText(file);
  });
}

/**
 * Debounce function.
 */
export function debounce<T extends (...args: unknown[]) => unknown>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout> | null = null;

  return (...args: Parameters<T>) => {
    if (timeout) {
      clearTimeout(timeout);
    }
    timeout = setTimeout(() => {
      func(...args);
    }, wait);
  };
}

/**
 * Format timestamp to locale string.
 */
export function formatTimestamp(timestamp: string): string {
  if (!timestamp) return '';
  try {
    return new Date(timestamp).toLocaleString('ko-KR');
  } catch {
    return timestamp;
  }
}

/**
 * Generate a unique ID.
 */
export function generateId(): string {
  return `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

/**
 * Convert server level JSON format to frontend format.
 * Server format has layers inside 'map' object.
 * Frontend format has layers at root level.
 */
export function convertServerLevelToFrontend(serverLevel: Record<string, unknown>): LevelJSON {
  // Get layer count
  const layerCount = typeof serverLevel.layer === 'number' ? serverLevel.layer : 8;

  // Initialize result with layer count
  const result: LevelJSON = { layer: layerCount };

  // Get map object containing layers
  const map = serverLevel.map as Record<string, unknown> | undefined;

  for (let i = 0; i < layerCount; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;

    // Try to get layer from map first, then from root
    let sourceLayer = map?.[layerKey] as Record<string, unknown> | undefined;
    if (!sourceLayer) {
      sourceLayer = serverLevel[layerKey] as Record<string, unknown> | undefined;
    }

    if (sourceLayer) {
      // Convert tiles - handle both array (empty) and object formats
      let tiles: Record<string, TileData> = {};
      const sourceTiles = sourceLayer.tiles;

      if (sourceTiles && typeof sourceTiles === 'object' && !Array.isArray(sourceTiles)) {
        // Convert tile format: server uses [type, attr] or [type, null], frontend uses [type, attr, extra?]
        const tilesObj = sourceTiles as Record<string, unknown[]>;
        for (const [pos, tileArr] of Object.entries(tilesObj)) {
          if (Array.isArray(tileArr) && tileArr.length >= 1) {
            const type = String(tileArr[0] || 't0');
            const attr = tileArr[1] ? String(tileArr[1]) : '';
            const extra = tileArr[2] as number[] | undefined;
            tiles[pos] = extra ? [type, attr, extra] : [type, attr];
          }
        }
      }

      result[layerKey] = {
        col: String(sourceLayer.col || '8'),
        row: String(sourceLayer.row || '8'),
        tiles,
        num: String(Object.keys(tiles).length),
      };
    } else {
      // Create empty layer with default size
      const isOddLayer = i % 2 === 1;
      result[layerKey] = {
        col: isOddLayer ? '7' : '8',
        row: isOddLayer ? '7' : '8',
        tiles: {},
        num: '0',
      };
    }
  }

  return result;
}

/**
 * Convert frontend level JSON format to server format.
 * For saving back to server.
 */
export function convertFrontendLevelToServer(frontendLevel: LevelJSON): Record<string, unknown> {
  const result: Record<string, unknown> = {
    layer: frontendLevel.layer,
    map: {} as Record<string, unknown>,
  };

  const map = result.map as Record<string, unknown>;

  for (let i = 0; i < frontendLevel.layer; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layer = frontendLevel[layerKey];

    if (layer) {
      // Convert tiles back to server format
      const serverTiles: Record<string, unknown[]> = {};
      for (const [pos, tileData] of Object.entries(layer.tiles)) {
        if (tileData[2]) {
          serverTiles[pos] = [tileData[0], tileData[1] || null, tileData[2]];
        } else {
          serverTiles[pos] = [tileData[0], tileData[1] || null];
        }
      }

      map[layerKey] = {
        col: layer.col,
        row: layer.row,
        tiles: serverTiles,
        num: layer.num,
      };
    }
  }

  return result;
}
