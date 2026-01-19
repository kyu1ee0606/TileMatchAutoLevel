import type { LevelJSON, DifficultyGrade } from '../types';
import type { LevelSetMetadata, LevelSetListItem, LevelSet, DifficultyPreset, DifficultyPoint } from '../types/levelSet';
import { BUILT_IN_PRESETS } from '../types/levelSet';
import {
  saveLevelSetToStorage,
  getLevelSetList,
  getLevelSetById,
  deleteLevelSetFromStorage,
} from '../storage/levelStorage';
import apiClient from './client';

const PRESETS_STORAGE_KEY = 'difficulty_presets';

export interface SaveLevelSetRequest {
  name: string;
  levels: LevelJSON[];
  difficulty_profile: number[];
  actual_difficulties: number[];
  grades: DifficultyGrade[];
  generation_config: Record<string, unknown>;
}

export interface SaveLevelSetResponse {
  success: boolean;
  id: string;
  message: string;
}

export interface ListLevelSetsResponse {
  level_sets: LevelSetListItem[];
}

export interface GetLevelSetResponse {
  metadata: LevelSetMetadata;
  levels: LevelJSON[];
}

export interface DeleteLevelSetResponse {
  success: boolean;
  message: string;
}

/**
 * Save a level set to browser localStorage AND backend storage.
 * This ensures data persists in both localStorage and backend file system.
 */
export async function saveLevelSet(data: SaveLevelSetRequest): Promise<SaveLevelSetResponse> {
  // First save to localStorage
  const localResult = saveLevelSetToStorage(data);

  if (!localResult.success) {
    return localResult;
  }

  // Also save individual levels to backend for persistence
  try {
    const setId = localResult.id;

    // Save each level to backend in parallel (batch of 10 to avoid overwhelming server)
    const batchSize = 10;
    for (let i = 0; i < data.levels.length; i += batchSize) {
      const batch = data.levels.slice(i, i + batchSize);
      const promises = batch.map((level, batchIndex) => {
        const index = i + batchIndex;
        const levelId = `${setId}_level_${String(index + 1).padStart(3, '0')}`;
        const difficulty = data.actual_difficulties[index] ?? 0.5;
        const grade = data.grades[index] ?? 'B';

        return apiClient.post('/simulate/local/save', {
          level_id: levelId,
          metadata: {
            name: `${data.name} - Level ${index + 1}`,
            difficulty: typeof difficulty === 'number' ? difficulty.toFixed(2) : difficulty,
            grade,
            source: 'level_set',
            set_id: setId,
            set_name: data.name,
            level_index: index + 1,
          },
          level_data: level,
        }).catch((err: unknown) => {
          console.warn(`Failed to save level ${levelId} to backend:`, err);
          return null; // Continue with other levels even if one fails
        });
      });

      await Promise.all(promises);
    }

    console.log(`[saveLevelSet] Saved ${data.levels.length} levels to backend`);
  } catch (err) {
    console.warn('[saveLevelSet] Backend save failed (localStorage save succeeded):', err);
    // Don't fail the operation - localStorage save succeeded
  }

  return localResult;
}

/**
 * List all saved level sets from browser localStorage.
 */
export async function listLevelSets(): Promise<ListLevelSetsResponse> {
  return { level_sets: getLevelSetList() };
}

/**
 * Get a specific level set by ID from browser localStorage.
 */
export async function getLevelSet(setId: string): Promise<GetLevelSetResponse> {
  const levelSet = getLevelSetById(setId);
  if (!levelSet) {
    throw new Error(`Level set ${setId} not found`);
  }

  return {
    metadata: {
      id: levelSet.id,
      name: levelSet.name,
      created_at: levelSet.created_at,
      level_count: levelSet.level_count,
      difficulty_profile: levelSet.difficulty_profile,
      actual_difficulties: levelSet.actual_difficulties,
      grades: levelSet.grades,
      generation_config: levelSet.generation_config,
    },
    levels: levelSet.levels,
  };
}

/**
 * Delete a level set from browser localStorage.
 */
export async function deleteLevelSet(setId: string): Promise<DeleteLevelSetResponse> {
  return deleteLevelSetFromStorage(setId);
}

/**
 * Export level set as a downloadable file.
 */
export function exportLevelSetAsFile(levelSet: LevelSet): void {
  const jsonStr = JSON.stringify(levelSet, null, 2);
  const blob = new Blob([jsonStr], { type: 'application/json' });
  const url = URL.createObjectURL(blob);

  const link = document.createElement('a');
  link.href = url;
  link.download = `${levelSet.metadata.name}_${levelSet.metadata.id}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Import level set from a file.
 */
export async function importLevelSetFromFile(file: File): Promise<LevelSet> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string;
        const levelSet = JSON.parse(content) as LevelSet;

        // Basic validation
        if (!levelSet.metadata || !levelSet.levels || !Array.isArray(levelSet.levels)) {
          throw new Error('Invalid level set format');
        }

        resolve(levelSet);
      } catch (error) {
        reject(new Error(`Failed to parse level set file: ${error}`));
      }
    };
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsText(file);
  });
}

// ==================== 난이도 프리셋 API ====================

/**
 * 저장된 커스텀 프리셋 불러오기
 */
export function getCustomPresets(): DifficultyPreset[] {
  try {
    const stored = localStorage.getItem(PRESETS_STORAGE_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as DifficultyPreset[];
  } catch {
    return [];
  }
}

/**
 * 모든 프리셋 가져오기 (내장 + 커스텀)
 */
export function getAllPresets(): DifficultyPreset[] {
  const customPresets = getCustomPresets();
  return [...BUILT_IN_PRESETS, ...customPresets];
}

/**
 * 커스텀 프리셋 저장
 */
export function saveCustomPreset(preset: Omit<DifficultyPreset, 'id' | 'created_at'>): DifficultyPreset {
  const customPresets = getCustomPresets();

  const newPreset: DifficultyPreset = {
    ...preset,
    id: `custom_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    isBuiltIn: false,
    created_at: new Date().toISOString(),
  };

  customPresets.push(newPreset);
  localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(customPresets));

  return newPreset;
}

/**
 * 커스텀 프리셋 삭제
 */
export function deleteCustomPreset(presetId: string): boolean {
  const customPresets = getCustomPresets();
  const filtered = customPresets.filter(p => p.id !== presetId);

  if (filtered.length === customPresets.length) {
    return false; // 삭제할 프리셋을 찾지 못함
  }

  localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(filtered));
  return true;
}

/**
 * 커스텀 프리셋 업데이트
 */
export function updateCustomPreset(presetId: string, updates: Partial<DifficultyPreset>): boolean {
  const customPresets = getCustomPresets();
  const index = customPresets.findIndex(p => p.id === presetId);

  if (index === -1) {
    return false;
  }

  customPresets[index] = { ...customPresets[index], ...updates };
  localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(customPresets));
  return true;
}

/**
 * 현재 포인트를 프리셋으로 변환 (100 레벨 기준으로 정규화)
 */
export function pointsToPreset(
  points: DifficultyPoint[],
  levelCount: number,
  name: string,
  description?: string
): Omit<DifficultyPreset, 'id' | 'created_at'> {
  // 레벨 인덱스를 100 기준으로 정규화
  const normalizedPoints = points.map(p => ({
    levelIndex: Math.round((p.levelIndex / levelCount) * 100),
    difficulty: p.difficulty,
  }));

  return {
    name,
    description,
    points: normalizedPoints,
    isBuiltIn: false,
  };
}
