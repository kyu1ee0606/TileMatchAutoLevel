/**
 * Local Levels API Service
 *
 * Hybrid storage: Uses backend API for listing/loading levels (from file system)
 * and localStorage as additional storage for deployed environments.
 */

import apiClient from '../api/client';
import {
  getLocalLevelList,
  getLocalLevelById,
  saveLocalLevelToStorage,
  deleteLocalLevelFromStorage,
  deleteBulkLocalLevelsFromStorage,
  deleteAllLocalLevelsFromStorage,
  getStorageInfo,
} from '../storage/levelStorage';

export interface LocalLevelMetadata {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  created_at: string;
  source: string;
  validation_status: string;
}

export interface LocalLevel {
  level_id: string;
  level_data: any;
  metadata: {
    name: string;
    description?: string;
    tags?: string[];
    difficulty: string;
    created_at?: string;
    saved_at?: string;
    source: string;
    validation_status?: string;
    actual_clear_rates?: Record<string, number>;
    suggestions?: string[];
    generation_config?: any;
  };
}

export interface LocalLevelListResponse {
  levels: LocalLevelMetadata[];
  count: number;
  storage_path: string;
}

export interface SaveLevelResponse {
  success: boolean;
  level_id: string;
  file_path?: string;
  message: string;
}

export interface ImportResponse {
  success: boolean;
  imported_count: number;
  error_count: number;
  imported_levels: string[];
  errors: any[] | null;
}

/**
 * Get list of all locally saved levels - combines backend storage and localStorage
 */
export async function listLocalLevels(): Promise<LocalLevelListResponse> {
  // Try backend API first
  try {
    const response = await apiClient.get('/simulate/local/list');
    const backendLevels = response.data.levels || [];

    // Also get localStorage levels
    const localStorageLevels = getLocalLevelList();
    const storageInfo = getStorageInfo();

    // Debug logging
    console.log('[listLocalLevels] Backend levels:', backendLevels.length);
    console.log('[listLocalLevels] LocalStorage levels:', localStorageLevels.length);

    // Merge levels (backend first, then localStorage, avoid duplicates by id)
    const seenIds = new Set<string>();
    const mergedLevels: LocalLevelMetadata[] = [];

    for (const l of backendLevels) {
      if (!seenIds.has(l.id)) {
        seenIds.add(l.id);
        mergedLevels.push({
          id: l.id,
          name: l.name || l.id,
          description: l.description || '',
          tags: l.tags || [],
          difficulty: l.difficulty || 'unknown',
          created_at: l.created_at || '',
          source: l.source || 'backend',
          validation_status: l.validation_status || 'unknown',
        });
      }
    }

    for (const l of localStorageLevels) {
      if (!seenIds.has(l.id)) {
        seenIds.add(l.id);
        mergedLevels.push({
          id: l.id,
          name: l.name,
          description: l.description,
          tags: l.tags,
          difficulty: l.difficulty,
          created_at: l.created_at,
          source: l.source || 'localStorage',
          validation_status: l.validation_status,
        });
      }
    }

    console.log('[listLocalLevels] Merged total:', mergedLevels.length);

    return {
      levels: mergedLevels,
      count: mergedLevels.length,
      storage_path: `backend + localStorage (${storageInfo.estimatedSize})`,
    };
  } catch (err) {
    // Fallback to localStorage only if backend is unavailable
    console.warn('Backend API unavailable, using localStorage only:', err);
    const levels = getLocalLevelList();
    const storageInfo = getStorageInfo();

    return {
      levels: levels.map(l => ({
        id: l.id,
        name: l.name,
        description: l.description,
        tags: l.tags,
        difficulty: l.difficulty,
        created_at: l.created_at,
        source: l.source,
        validation_status: l.validation_status,
      })),
      count: levels.length,
      storage_path: `localStorage (${storageInfo.estimatedSize})`,
    };
  }
}

/**
 * Get a specific local level by ID - tries localStorage first, then backend
 * This prevents unnecessary 404 errors for levels that exist only in localStorage
 */
export async function getLocalLevel(levelId: string): Promise<LocalLevel> {
  // Try localStorage first (faster, no network request, no 404 errors)
  const localLevel = getLocalLevelById(levelId);
  if (localLevel) {
    return {
      level_id: localLevel.id,
      level_data: localLevel.level_data,
      metadata: {
        name: localLevel.name,
        description: localLevel.description,
        tags: localLevel.tags,
        difficulty: typeof localLevel.difficulty === 'number' ? String(localLevel.difficulty) : localLevel.difficulty,
        created_at: localLevel.created_at,
        saved_at: localLevel.saved_at,
        source: localLevel.source || 'localStorage',
        validation_status: localLevel.validation_status,
      },
    };
  }

  // Fallback to backend API if not in localStorage
  try {
    const response = await apiClient.get(`/simulate/local/${levelId}`);
    const data = response.data;

    return {
      level_id: data.level_id || levelId,
      level_data: data.level_data,
      metadata: {
        name: data.name || data.metadata?.name || levelId,
        description: data.description || data.metadata?.description,
        tags: data.tags || data.metadata?.tags,
        difficulty: data.difficulty || data.metadata?.difficulty || 'unknown',
        created_at: data.created_at || data.metadata?.created_at,
        saved_at: data.saved_at || data.metadata?.saved_at,
        source: data.source || data.metadata?.source || 'backend',
        validation_status: data.validation_status || data.metadata?.validation_status,
      },
    };
  } catch (err) {
    throw new Error(`Level ${levelId} not found`);
  }
}

/**
 * Save a level to browser localStorage
 */
export async function saveLocalLevel(levelData: LocalLevel): Promise<SaveLevelResponse> {
  const result = saveLocalLevelToStorage({
    id: levelData.level_id,
    name: levelData.metadata?.name,
    description: levelData.metadata?.description,
    tags: levelData.metadata?.tags,
    difficulty: levelData.metadata?.difficulty,
    source: levelData.metadata?.source || 'local',
    level_data: levelData.level_data,
    validation_status: levelData.metadata?.validation_status,
  });

  return {
    success: result.success,
    level_id: result.level_id,
    message: result.message,
  };
}

/**
 * Delete a local level - checks localStorage first, only calls backend if needed
 */
export async function deleteLocalLevel(levelId: string): Promise<{ success: boolean; message: string }> {
  // Check if level exists in localStorage
  const localLevel = getLocalLevelById(levelId);

  if (localLevel) {
    // Level is in localStorage - delete directly without API call
    return deleteLocalLevelFromStorage(levelId);
  }

  // Level not in localStorage - try backend API
  try {
    await apiClient.delete(`/simulate/local/${levelId}`);
    return { success: true, message: `Level ${levelId} deleted successfully` };
  } catch (err) {
    return { success: false, message: `Level ${levelId} not found` };
  }
}

/**
 * Delete multiple local levels by IDs (bulk operation - instant, no API calls)
 */
export function deleteBulkLocalLevels(levelIds: string[]): { success: boolean; deleted_count: number; message: string } {
  return deleteBulkLocalLevelsFromStorage(levelIds);
}

/**
 * Delete all local levels from browser localStorage
 */
export async function deleteAllLocalLevels(): Promise<{ success: boolean; deleted_count: number; message: string }> {
  return deleteAllLocalLevelsFromStorage();
}

/**
 * Import generated levels from generator output file
 * (Saves to browser localStorage)
 */
export async function importGeneratedLevels(fileContent: any): Promise<ImportResponse> {
  const levels = fileContent.levels || [];
  if (!levels.length) {
    return {
      success: false,
      imported_count: 0,
      error_count: 1,
      imported_levels: [],
      errors: [{ error: 'No levels found in file' }],
    };
  }

  const imported: string[] = [];
  const errors: any[] = [];

  for (const level of levels) {
    try {
      const config = level.config || {};
      const levelId = config.level_id;

      if (!levelId) {
        errors.push({ error: 'Missing level_id', data: config });
        continue;
      }

      const result = saveLocalLevelToStorage({
        id: levelId,
        name: config.name || levelId,
        description: config.description,
        tags: [...(config.tags || []), 'generated'],
        difficulty: config.tier || 'custom',
        source: 'generated',
        level_data: level.level_json || {},
        validation_status: level.validation_status || 'unknown',
      });

      if (result.success) {
        imported.push(levelId);
      } else {
        errors.push({ level_id: levelId, error: result.message });
      }
    } catch (error) {
      errors.push({ error: String(error) });
    }
  }

  return {
    success: imported.length > 0,
    imported_count: imported.length,
    error_count: errors.length,
    imported_levels: imported,
    errors: errors.length > 0 ? errors : null,
  };
}

/**
 * Simulate a local level with bots
 * (This still uses the backend API for simulation logic)
 */
export async function simulateLocalLevel(
  levelData: any,
  botTypes: string[] = ['optimal'],
  maxMoves: number = 50,
  seed: number = 42
): Promise<any> {
  const response = await apiClient.post('/simulate/visual', {
    level_json: levelData,
    bot_types: botTypes,
    max_moves: maxMoves,
    seed: seed,
  });

  return response.data;
}
