/**
 * Local Levels API Service
 *
 * Uses browser localStorage for persistent storage that works in deployed environments.
 * Backend API is only used for simulation, not for storage.
 */

import apiClient from '../api/client';
import {
  getLocalLevelList,
  getLocalLevelById,
  saveLocalLevelToStorage,
  deleteLocalLevelFromStorage,
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
 * Get list of all locally saved levels from browser localStorage
 */
export async function listLocalLevels(): Promise<LocalLevelListResponse> {
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

/**
 * Get a specific local level by ID from browser localStorage
 */
export async function getLocalLevel(levelId: string): Promise<LocalLevel> {
  const level = getLocalLevelById(levelId);
  if (!level) {
    throw new Error(`Level ${levelId} not found`);
  }

  return {
    level_id: level.id,
    level_data: level.level_data,
    metadata: {
      name: level.name,
      description: level.description,
      tags: level.tags,
      difficulty: typeof level.difficulty === 'number' ? String(level.difficulty) : level.difficulty,
      created_at: level.created_at,
      saved_at: level.saved_at,
      source: level.source,
      validation_status: level.validation_status,
    },
  };
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
 * Delete a local level from browser localStorage
 */
export async function deleteLocalLevel(levelId: string): Promise<{ success: boolean; message: string }> {
  return deleteLocalLevelFromStorage(levelId);
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
