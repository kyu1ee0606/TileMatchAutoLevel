/**
 * Local Levels API Service
 *
 * Handles all communication with local level storage endpoints
 */

const API_BASE = 'http://localhost:8000/api/simulate';

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
    description: string;
    tags: string[];
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
  file_path: string;
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
 * Get list of all locally saved levels
 */
export async function listLocalLevels(): Promise<LocalLevelListResponse> {
  const response = await fetch(`${API_BASE}/local/list`);
  if (!response.ok) {
    throw new Error(`Failed to list local levels: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get a specific local level by ID
 */
export async function getLocalLevel(levelId: string): Promise<LocalLevel> {
  const response = await fetch(`${API_BASE}/local/${levelId}`);
  if (!response.ok) {
    throw new Error(`Failed to get level ${levelId}: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Save a level to local storage
 */
export async function saveLocalLevel(levelData: LocalLevel): Promise<SaveLevelResponse> {
  const response = await fetch(`${API_BASE}/local/save`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(levelData),
  });

  if (!response.ok) {
    throw new Error(`Failed to save level: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete a local level
 */
export async function deleteLocalLevel(levelId: string): Promise<{ success: boolean; message: string }> {
  const response = await fetch(`${API_BASE}/local/${levelId}`, {
    method: 'DELETE',
  });

  if (!response.ok) {
    throw new Error(`Failed to delete level ${levelId}: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Import generated levels from generator output file
 */
export async function importGeneratedLevels(fileContent: any): Promise<ImportResponse> {
  const response = await fetch(`${API_BASE}/local/import-generated`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(fileContent),
  });

  if (!response.ok) {
    throw new Error(`Failed to import levels: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Simulate a local level with bots
 */
export async function simulateLocalLevel(
  levelData: any,
  botTypes: string[] = ['optimal'],
  maxMoves: number = 50,
  seed: number = 42
): Promise<any> {
  const response = await fetch(`${API_BASE}/visual`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      level_json: levelData,
      bot_types: botTypes,
      max_moves: maxMoves,
      seed: seed,
    }),
  });

  if (!response.ok) {
    throw new Error(`Failed to simulate level: ${response.statusText}`);
  }
  return response.json();
}
