import apiClient from './client';
import type { LevelJSON, DifficultyReport } from '../types';

export interface AnalyzeRequest {
  level_json: LevelJSON;
}

export interface BatchAnalyzeRequest {
  levels?: LevelJSON[];
  level_ids?: string[];
  board_id?: string;
}

export interface BatchAnalyzeResult {
  level_id: string;
  score: number;
  grade: string;
  metrics: Record<string, unknown>;
}

export interface BatchAnalyzeResponse {
  results: BatchAnalyzeResult[];
}

/**
 * Analyze a single level and get difficulty metrics.
 */
export async function analyzeLevel(levelJson: LevelJSON): Promise<DifficultyReport> {
  const response = await apiClient.post<DifficultyReport>('/analyze', {
    level_json: levelJson,
  });
  return response.data;
}

/**
 * Analyze multiple levels in batch.
 */
export async function batchAnalyzeLevels(
  request: BatchAnalyzeRequest
): Promise<BatchAnalyzeResponse> {
  const response = await apiClient.post<BatchAnalyzeResponse>(
    '/levels/batch-analyze',
    request
  );
  return response.data;
}

// ============================================================
// AutoPlay Analysis Types & API
// ============================================================

export interface AutoPlayRequest {
  level_json: LevelJSON;
  iterations?: number; // Default: 100
  bot_profiles?: string[]; // Default: all 5
  seed?: number;
}

export interface BotClearStats {
  profile: string;
  profile_display: string;
  clear_rate: number; // 0.0-1.0
  target_clear_rate: number;
  avg_moves: number;
  min_moves: number;
  max_moves: number;
  std_moves: number;
  avg_combo: number;
  iterations: number;
}

export interface AutoPlayResponse {
  bot_stats: BotClearStats[];
  autoplay_score: number;
  autoplay_grade: string;
  static_score: number;
  static_grade: string;
  score_difference: number;
  balance_status: 'balanced' | 'too_easy' | 'too_hard' | 'unbalanced';
  recommendations: string[];
  total_simulations: number;
  execution_time_ms: number;
}

/**
 * Analyze level difficulty using auto-play bot simulations.
 * Runs multiple bot profiles with repeated simulations to measure actual clear rates.
 */
export async function analyzeAutoPlay(
  levelJson: LevelJSON,
  options?: { iterations?: number; botProfiles?: string[]; seed?: number }
): Promise<AutoPlayResponse> {
  const response = await apiClient.post<AutoPlayResponse>('/analyze/autoplay', {
    level_json: levelJson,
    iterations: options?.iterations ?? 100,
    bot_profiles: options?.botProfiles,
    seed: options?.seed,
  });
  return response.data;
}
