import apiClient from './client';
import type { LevelJSON } from '../types';
import type { VisualSimulationResponse, BotProfile } from '../types/simulation';

/**
 * Run visual simulation for a level with multiple bots.
 * Returns detailed move history for playback visualization.
 */
export async function simulateVisual(
  levelJson: LevelJSON,
  botTypes?: BotProfile[],
  maxMoves?: number,
  seed?: number
): Promise<VisualSimulationResponse> {
  const response = await apiClient.post<VisualSimulationResponse>(
    '/simulate/visual',
    {
      level_json: levelJson,
      bot_types: botTypes,
      max_moves: maxMoves,
      seed: seed,
    }
  );
  return response.data;
}

/**
 * List all locally saved levels.
 */
export interface LocalLevelListItem {
  id: string;
  name: string;
  description?: string;
  tags?: string[];
  difficulty?: string | number;
  created_at?: string;
  source?: string;
  grade?: string;
}

export interface LocalLevelListResponse {
  levels: LocalLevelListItem[];
  count: number;
  storage_path: string;
}

export async function listLocalLevels(): Promise<LocalLevelListResponse> {
  const response = await apiClient.get<LocalLevelListResponse>('/simulate/local/list');
  return response.data;
}

/**
 * Load a specific local level.
 */
export interface LocalLevelResponse {
  level_data: LevelJSON;
  metadata: {
    id: string;
    name: string;
    difficulty?: string | number;
    grade?: string;
    [key: string]: unknown;
  };
}

export async function loadLocalLevel(levelId: string): Promise<LocalLevelResponse> {
  const response = await apiClient.get<LocalLevelResponse>(`/simulate/local/${levelId}`);
  return response.data;
}
