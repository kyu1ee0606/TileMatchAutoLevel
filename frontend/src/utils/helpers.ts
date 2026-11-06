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
 * IMPORTANT: Only counts NORMAL tiles (excludes goal tiles like craft_s, stack_s).
 * Goal tiles are collected, not matched, so they don't need to be divisible by 3.
 * @param level Level JSON to validate
 * @returns Validation result with total count, validity, and message
 */
export function validateTileCount(level: LevelJSON): TileValidationResult {
  // Goal tile types that should be excluded from the count
  const GOAL_TYPES = ['craft_s', 'stack_s'];

  let totalTiles = 0;

  for (let i = 0; i < level.layer; i++) {
    const layerKey = `layer_${i}` as `layer_${number}`;
    const layer = level[layerKey];
    if (!layer?.tiles) continue;

    for (const [_pos, tileData] of Object.entries(layer.tiles)) {
      const tileType = tileData[0];
      const extra = tileData[2];

      // Skip goal tiles - they are collected, not matched
      if (GOAL_TYPES.includes(tileType)) {
        continue;
      }

      // Check if this is a stack/craft box tile with hidden tiles
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
 * 타일 수 하한: 3 × ceil(1.5 × min(K+2, 15)), K = 쓰는 타일 종류 수(useTileCount).
 * 백엔드 backend/app/utils/tile_floor.py 와 같은 값이어야 한다. (K=8→45, 9→51, 10→54, 11→60, 12→63, 13+→69)
 */
export function getMinTileCount(kinds: number): number {
  const k = Math.max(0, Math.floor(kinds));
  return 3 * Math.ceil(1.5 * Math.min(k + 2, 15));
}

export interface TileFloorResult {
  kinds: number;
  minTiles: number;
  totalTiles: number;
  isBelow: boolean;
  message: string;
}

/**
 * 타일 수 하한 검사 (경고용). 총 장수는 validateTileCount 와 동일 방식.
 * K = level.useTileCount(>0) 우선, 없으면 레이어에 실제 쓰인 t1~t15 종류 수.
 */
export function checkTileFloor(level: LevelJSON): TileFloorResult {
  const totalTiles = validateTileCount(level).totalTiles;
  let kinds = typeof level.useTileCount === 'number' && level.useTileCount > 0 ? level.useTileCount : 0;
  if (kinds === 0) {
    const used = new Set<string>();
    for (let i = 0; i < level.layer; i++) {
      const layer = level[`layer_${i}` as `layer_${number}`];
      if (!layer?.tiles) continue;
      for (const tileData of Object.values(layer.tiles)) {
        const t = tileData[0];
        if (/^t\d+$/.test(t) && t !== 't0') used.add(t);
      }
    }
    kinds = used.size;
  }
  const minTiles = getMinTileCount(kinds);
  const isBelow = totalTiles > 0 && totalTiles < minTiles;
  return {
    kinds,
    minTiles,
    totalTiles,
    isBelow,
    message: `타일 수 하한 미달: 종류 K=${kinds}, 최소 타일 수 ${minTiles}개, 현재 ${totalTiles}개`,
  };
}

/** axios 오류에서 백엔드 detail 문자열을 꺼낸다 (없으면 err.message). */
export function getApiErrorDetail(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return err instanceof Error ? err.message : '알 수 없는 오류';
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
