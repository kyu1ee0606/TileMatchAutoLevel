/**
 * Browser localStorage-based Level Storage
 *
 * Provides persistent level storage that works in deployed environments
 * where backend filesystem is ephemeral (e.g., Render free tier)
 */

import type { LevelJSON, DifficultyGrade } from '../types';
import type { LevelSetListItem } from '../types/levelSet';

// Storage keys
const LEVEL_SETS_KEY = 'tilematch_level_sets';
const LOCAL_LEVELS_KEY = 'tilematch_local_levels';

// Types
export interface StoredLevelSet {
  id: string;
  name: string;
  created_at: string;
  level_count: number;
  difficulty_profile: number[];
  actual_difficulties: number[];
  grades: DifficultyGrade[];
  generation_config: Record<string, unknown>;
  levels: LevelJSON[];
}

export interface StoredLocalLevel {
  id: string;
  name: string;
  description?: string;
  tags?: string[];
  difficulty: number | string;
  grade?: string;
  created_at: string;
  saved_at: string;
  source: string;
  set_id?: string;
  set_name?: string;
  level_index?: number;
  level_data: LevelJSON;
  validation_status?: string;
}

// ==================== Level Sets ====================

/**
 * Get all stored level sets metadata
 */
export function getAllLevelSets(): StoredLevelSet[] {
  try {
    const stored = localStorage.getItem(LEVEL_SETS_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as StoredLevelSet[];
  } catch {
    return [];
  }
}

/**
 * Get level set list items (metadata only, without full level data)
 */
export function getLevelSetList(): LevelSetListItem[] {
  const sets = getAllLevelSets();
  return sets.map(set => ({
    id: set.id,
    name: set.name,
    created_at: set.created_at,
    level_count: set.level_count,
    difficulty_range: {
      min: set.actual_difficulties.length > 0 ? Math.min(...set.actual_difficulties) : 0,
      max: set.actual_difficulties.length > 0 ? Math.max(...set.actual_difficulties) : 0,
    },
  }));
}

/**
 * Get a specific level set by ID
 */
export function getLevelSetById(setId: string): StoredLevelSet | null {
  const sets = getAllLevelSets();
  return sets.find(s => s.id === setId) || null;
}

/**
 * Save a level set
 */
export function saveLevelSetToStorage(data: {
  name: string;
  levels: LevelJSON[];
  difficulty_profile: number[];
  actual_difficulties: number[];
  grades: DifficultyGrade[];
  generation_config: Record<string, unknown>;
}): { success: boolean; id: string; message: string } {
  try {
    const sets = getAllLevelSets();
    const now = new Date();
    const timestamp = now.toISOString();
    const id = `set_${now.getTime()}_${Math.random().toString(36).substr(2, 9)}`;

    const newSet: StoredLevelSet = {
      id,
      name: data.name || `Level Set ${now.toLocaleString()}`,
      created_at: timestamp,
      level_count: data.levels.length,
      difficulty_profile: data.difficulty_profile,
      actual_difficulties: data.actual_difficulties,
      grades: data.grades,
      generation_config: data.generation_config,
      levels: data.levels,
    };

    sets.unshift(newSet); // Add to beginning (newest first)
    localStorage.setItem(LEVEL_SETS_KEY, JSON.stringify(sets));

    // Also save individual levels to local levels
    data.levels.forEach((level, index) => {
      const levelId = `${id}_level_${String(index + 1).padStart(3, '0')}`;
      const difficulty = data.actual_difficulties[index] ?? 0.5;
      const grade = data.grades[index] ?? 'B';

      saveLocalLevelToStorage({
        id: levelId,
        name: `${data.name} - Level ${index + 1}`,
        difficulty,
        grade,
        source: 'level_set',
        set_id: id,
        set_name: data.name,
        level_index: index + 1,
        level_data: level,
      });
    });

    return {
      success: true,
      id,
      message: `Level set '${data.name}' saved successfully with ${data.levels.length} levels`,
    };
  } catch (error) {
    return {
      success: false,
      id: '',
      message: `Failed to save level set: ${error}`,
    };
  }
}

/**
 * Delete a level set by ID
 */
export function deleteLevelSetFromStorage(setId: string): { success: boolean; message: string } {
  try {
    const sets = getAllLevelSets();
    const filtered = sets.filter(s => s.id !== setId);

    if (filtered.length === sets.length) {
      return { success: false, message: `Level set ${setId} not found` };
    }

    localStorage.setItem(LEVEL_SETS_KEY, JSON.stringify(filtered));

    // Also delete associated local levels
    const localLevels = getAllLocalLevels();
    const filteredLevels = localLevels.filter(l => l.set_id !== setId);
    localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(filteredLevels));

    return { success: true, message: `Level set ${setId} deleted successfully` };
  } catch (error) {
    return { success: false, message: `Failed to delete level set: ${error}` };
  }
}

// ==================== Local Levels ====================

/**
 * Get all stored local levels
 */
export function getAllLocalLevels(): StoredLocalLevel[] {
  try {
    const stored = localStorage.getItem(LOCAL_LEVELS_KEY);
    if (!stored) return [];
    return JSON.parse(stored) as StoredLocalLevel[];
  } catch {
    return [];
  }
}

/**
 * Get local level list (for display)
 */
export function getLocalLevelList(): Array<{
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  created_at: string;
  created_at_display: string;
  saved_at: string;
  saved_at_display: string;
  source: string;
  validation_status: string;
  set_id: string;
  set_name: string;
  level_index: number;
  grade: string;
}> {
  const levels = getAllLocalLevels();

  return levels.map(level => {
    // Format datetime for display
    let created_at_display = '';
    let saved_at_display = '';

    if (level.created_at) {
      try {
        const parsed = new Date(level.created_at);
        created_at_display = parsed.toLocaleString('ko-KR');
      } catch {
        created_at_display = level.created_at.substring(0, 19).replace('T', ' ');
      }
    }

    if (level.saved_at) {
      try {
        const parsed = new Date(level.saved_at);
        saved_at_display = parsed.toLocaleString('ko-KR');
      } catch {
        saved_at_display = level.saved_at.substring(0, 19).replace('T', ' ');
      }
    }

    // Format difficulty string
    let difficultyStr: string;
    if (typeof level.difficulty === 'number') {
      difficultyStr = level.grade
        ? `${level.grade} (${level.difficulty.toFixed(2)})`
        : level.difficulty.toFixed(2);
    } else {
      difficultyStr = String(level.difficulty);
    }

    return {
      id: level.id,
      name: level.name,
      description: level.description || (level.set_name ? `[${level.set_name}]` : ''),
      tags: level.tags || [],
      difficulty: difficultyStr,
      created_at: level.created_at,
      created_at_display,
      saved_at: level.saved_at,
      saved_at_display,
      source: level.source || 'local',
      validation_status: level.validation_status || 'unknown',
      set_id: level.set_id || '',
      set_name: level.set_name || '',
      level_index: level.level_index || 0,
      grade: level.grade || '',
    };
  });
}

/**
 * Get a specific local level by ID
 */
export function getLocalLevelById(levelId: string): StoredLocalLevel | null {
  const levels = getAllLocalLevels();
  return levels.find(l => l.id === levelId) || null;
}

/**
 * Save a local level
 */
export function saveLocalLevelToStorage(data: {
  id?: string;
  name?: string;
  description?: string;
  tags?: string[];
  difficulty?: number | string;
  grade?: string;
  source?: string;
  set_id?: string;
  set_name?: string;
  level_index?: number;
  level_data: LevelJSON;
  validation_status?: string;
}): { success: boolean; level_id: string; message: string } {
  try {
    const levels = getAllLocalLevels();
    const now = new Date();
    const timestamp = now.toISOString();

    // Generate ID if not provided
    const id = data.id || `level_${now.getTime()}_${Math.random().toString(36).substr(2, 9)}`;

    // Check if level already exists
    const existingIndex = levels.findIndex(l => l.id === id);

    const levelData: StoredLocalLevel = {
      id,
      name: data.name || `Generated Level ${now.toLocaleString('ko-KR')}`,
      description: data.description,
      tags: data.tags,
      difficulty: data.difficulty ?? 0.5,
      grade: data.grade,
      created_at: existingIndex >= 0 ? levels[existingIndex].created_at : timestamp,
      saved_at: timestamp,
      source: data.source || 'local',
      set_id: data.set_id,
      set_name: data.set_name,
      level_index: data.level_index,
      level_data: data.level_data,
      validation_status: data.validation_status,
    };

    if (existingIndex >= 0) {
      // Update existing level
      levels[existingIndex] = levelData;
    } else {
      // Add new level at beginning
      levels.unshift(levelData);
    }

    localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(levels));

    return {
      success: true,
      level_id: id,
      message: `Level saved: ${levelData.name}`,
    };
  } catch (error) {
    return {
      success: false,
      level_id: '',
      message: `Failed to save level: ${error}`,
    };
  }
}

/**
 * Delete a local level by ID
 */
export function deleteLocalLevelFromStorage(levelId: string): { success: boolean; message: string } {
  try {
    const levels = getAllLocalLevels();
    const filtered = levels.filter(l => l.id !== levelId);

    if (filtered.length === levels.length) {
      return { success: false, message: `Level ${levelId} not found` };
    }

    localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(filtered));
    return { success: true, message: `Level ${levelId} deleted successfully` };
  } catch (error) {
    return { success: false, message: `Failed to delete level: ${error}` };
  }
}

/**
 * Delete all local levels
 */
export function deleteAllLocalLevelsFromStorage(): { success: boolean; deleted_count: number; message: string } {
  try {
    const levels = getAllLocalLevels();
    const count = levels.length;

    localStorage.removeItem(LOCAL_LEVELS_KEY);

    return {
      success: true,
      deleted_count: count,
      message: `Deleted ${count} levels`,
    };
  } catch (error) {
    return {
      success: false,
      deleted_count: 0,
      message: `Failed to delete levels: ${error}`,
    };
  }
}

// ==================== Utility Functions ====================

/**
 * Get storage usage info
 */
export function getStorageInfo(): {
  levelSetsCount: number;
  localLevelsCount: number;
  estimatedSize: string;
} {
  const levelSets = getAllLevelSets();
  const localLevels = getAllLocalLevels();

  // Estimate storage size
  const levelSetsSize = localStorage.getItem(LEVEL_SETS_KEY)?.length || 0;
  const localLevelsSize = localStorage.getItem(LOCAL_LEVELS_KEY)?.length || 0;
  const totalBytes = levelSetsSize + localLevelsSize;

  let estimatedSize: string;
  if (totalBytes < 1024) {
    estimatedSize = `${totalBytes} B`;
  } else if (totalBytes < 1024 * 1024) {
    estimatedSize = `${(totalBytes / 1024).toFixed(1)} KB`;
  } else {
    estimatedSize = `${(totalBytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  return {
    levelSetsCount: levelSets.length,
    localLevelsCount: localLevels.length,
    estimatedSize,
  };
}

/**
 * Clear all level storage (use with caution)
 */
export function clearAllLevelStorage(): void {
  localStorage.removeItem(LEVEL_SETS_KEY);
  localStorage.removeItem(LOCAL_LEVELS_KEY);
}

/**
 * Export all data as JSON (for backup)
 */
export function exportAllData(): {
  levelSets: StoredLevelSet[];
  localLevels: StoredLocalLevel[];
  exportedAt: string;
} {
  return {
    levelSets: getAllLevelSets(),
    localLevels: getAllLocalLevels(),
    exportedAt: new Date().toISOString(),
  };
}

/**
 * Import data from backup
 */
export function importAllData(data: {
  levelSets?: StoredLevelSet[];
  localLevels?: StoredLocalLevel[];
}): { success: boolean; message: string } {
  try {
    if (data.levelSets) {
      const existing = getAllLevelSets();
      const merged = [...data.levelSets, ...existing];
      // Remove duplicates by ID
      const unique = merged.filter((set, index, self) =>
        index === self.findIndex(s => s.id === set.id)
      );
      localStorage.setItem(LEVEL_SETS_KEY, JSON.stringify(unique));
    }

    if (data.localLevels) {
      const existing = getAllLocalLevels();
      const merged = [...data.localLevels, ...existing];
      // Remove duplicates by ID
      const unique = merged.filter((level, index, self) =>
        index === self.findIndex(l => l.id === level.id)
      );
      localStorage.setItem(LOCAL_LEVELS_KEY, JSON.stringify(unique));
    }

    return { success: true, message: 'Data imported successfully' };
  } catch (error) {
    return { success: false, message: `Failed to import data: ${error}` };
  }
}
