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
  target_difficulty?: number; // 0.0-1.0, for dynamic bot target rates
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
  options?: {
    iterations?: number;
    botProfiles?: string[];
    seed?: number;
    targetDifficulty?: number;  // 0.0-1.0, for dynamic bot target rates
  }
): Promise<AutoPlayResponse> {
  const iterations = options?.iterations ?? 100;
  // Calculate timeout based on iterations (base 60s + 0.5s per iteration per bot)
  // 5 bots, so iterations * 5 * 0.5s = iterations * 2.5s, plus base 60s
  const timeoutMs = Math.max(60000, 60000 + iterations * 2500);

  const response = await apiClient.post<AutoPlayResponse>(
    '/analyze/autoplay',
    {
      level_json: levelJson,
      iterations: iterations,
      bot_profiles: options?.botProfiles,
      seed: options?.seed,
      target_difficulty: options?.targetDifficulty,
    },
    {
      timeout: timeoutMs, // Override default timeout for heavy simulation
    }
  );
  return response.data;
}


// ============================================================
// Batch Verification Types & API (Post-generation validation)
// ============================================================

export interface BatchVerifyLevelItem {
  level_json: LevelJSON;
  level_id?: string;
  target_difficulty?: number;
}

export interface BatchVerifyRequest {
  levels: BatchVerifyLevelItem[];
  iterations?: number;      // Default: 20
  tolerance?: number;       // Default: 15.0
  use_core_bots_only?: boolean;  // Default: true
}

export interface BatchVerifyResultItem {
  level_id: string;
  passed: boolean;
  bot_clear_rates: Record<string, number>;
  target_clear_rates: Record<string, number>;
  avg_gap: number;
  max_gap: number;
  match_score: number;
  static_grade: string;
  issues: string[];
}

export interface BatchVerifyResponse {
  results: BatchVerifyResultItem[];
  total_levels: number;
  passed_count: number;
  failed_count: number;
  pass_rate: number;
  execution_time_ms: number;
}

/**
 * Batch verify multiple levels using bot simulation.
 * Use this for post-generation validation when levels are generated with fast mode.
 */
export async function batchVerifyLevels(
  levels: BatchVerifyLevelItem[],
  options?: {
    iterations?: number;
    tolerance?: number;
    useCoreBotOnly?: boolean;
  }
): Promise<BatchVerifyResponse> {
  const iterations = options?.iterations ?? 20;
  // Timeout: base 30s + 2s per level per iteration
  const timeoutMs = Math.max(60000, 30000 + levels.length * iterations * 2000);

  const response = await apiClient.post<BatchVerifyResponse>(
    '/analyze/batch-verify',
    {
      levels,
      iterations,
      tolerance: options?.tolerance ?? 15.0,
      use_core_bots_only: options?.useCoreBotOnly ?? true,
    },
    {
      timeout: timeoutMs,
    }
  );
  return response.data;
}
