import apiClient from './client';
import type { LevelJSON, GenerationParams, GenerationResult, SimulationResult, ObstacleCountConfig, LayerTileConfig, LayerObstacleConfig, SymmetryMode, PatternType } from '../types';

export interface GenerateRequest {
  target_difficulty: number;
  grid_size?: [number, number];
  max_layers?: number;
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: Array<{ type: string; direction?: string; count: number }>;
  obstacle_counts?: Record<string, ObstacleCountConfig>;
  // Per-layer configurations
  layer_tile_configs?: LayerTileConfig[];
  layer_obstacle_configs?: LayerObstacleConfig[];
  // Symmetry and pattern options
  symmetry_mode?: SymmetryMode;
  pattern_type?: PatternType;
  // Auto gimmick selection parameters
  auto_select_gimmicks?: boolean;
  available_gimmicks?: string[];
}

export interface SimulateRequest {
  level_json: LevelJSON;
  iterations?: number;
  strategy?: 'random' | 'greedy' | 'optimal';
}

/**
 * Generate a new level with target difficulty.
 */
export async function generateLevel(
  params: GenerationParams,
  gimmickOptions?: {
    auto_select_gimmicks?: boolean;
    available_gimmicks?: string[];
  }
): Promise<GenerationResult> {
  const request: GenerateRequest = {
    target_difficulty: params.target_difficulty,
    grid_size: params.grid_size,
    max_layers: params.max_layers,
    tile_types: params.tile_types,
    obstacle_types: params.obstacle_types,
    goals: params.goals,
    obstacle_counts: params.obstacle_counts,
    layer_tile_configs: params.layer_tile_configs,
    layer_obstacle_configs: params.layer_obstacle_configs,
    symmetry_mode: params.symmetry_mode,
    pattern_type: params.pattern_type,
    // Auto gimmick selection
    auto_select_gimmicks: gimmickOptions?.auto_select_gimmicks,
    available_gimmicks: gimmickOptions?.available_gimmicks,
  };

  // Increase timeout when using auto gimmick selection (requires additional processing)
  const timeoutMs = gimmickOptions?.auto_select_gimmicks ? 60000 : 30000;

  const response = await apiClient.post<GenerationResult>('/generate', request, {
    timeout: timeoutMs,
  });
  return response.data;
}

/**
 * Generate multiple levels at once.
 */
export async function generateMultipleLevels(
  params: GenerationParams,
  count: number
): Promise<GenerationResult[]> {
  const promises = Array.from({ length: count }, () => generateLevel(params));
  return Promise.all(promises);
}

/**
 * Run simulation on a level.
 */
export async function simulateLevel(
  levelJson: LevelJSON,
  iterations: number = 500,
  strategy: 'random' | 'greedy' | 'optimal' = 'greedy'
): Promise<SimulationResult> {
  const request: SimulateRequest = {
    level_json: levelJson,
    iterations,
    strategy,
  };

  const response = await apiClient.post<SimulationResult>('/simulate', request);
  return response.data;
}

// ==================== Validated Generation ====================

export interface ValidatedGenerateRequest {
  target_difficulty: number;
  grid_size?: [number, number];
  max_layers?: number;
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: Array<{ type: string; direction?: string; count: number }>;
  symmetry_mode?: SymmetryMode;
  pattern_type?: PatternType;
  // Validation parameters
  max_retries?: number;          // Default: 5
  tolerance?: number;            // Default: 15.0 (percentage)
  simulation_iterations?: number; // Default: 30
  use_best_match?: boolean;      // Default: true - always return best result after max_retries
  // Auto gimmick selection parameters
  auto_select_gimmicks?: boolean;   // Enable auto gimmick selection based on difficulty
  available_gimmicks?: string[];    // Pool of available gimmicks for auto-selection
}

export interface ValidatedGenerateResult {
  level_json: LevelJSON;
  actual_difficulty: number;
  grade: string;
  generation_time_ms: number;
  // Validation results
  validation_passed: boolean;
  attempts: number;
  bot_clear_rates: Record<string, number>;
  target_clear_rates: Record<string, number>;
  avg_gap: number;
  max_gap: number;
  match_score: number;
}

/**
 * Generate a level with simulation-based validation.
 * This API generates levels and validates them against target clear rates
 * using bot simulation. Returns the best level found within max_retries attempts.
 */
export async function generateValidatedLevel(
  params: Omit<GenerationParams, 'obstacle_counts' | 'layer_tile_configs' | 'layer_obstacle_configs'>,
  validationOptions?: {
    max_retries?: number;
    tolerance?: number;
    simulation_iterations?: number;
    use_best_match?: boolean;
  },
  gimmickOptions?: {
    auto_select_gimmicks?: boolean;
    available_gimmicks?: string[];
  }
): Promise<ValidatedGenerateResult> {
  const request: ValidatedGenerateRequest = {
    target_difficulty: params.target_difficulty,
    grid_size: params.grid_size,
    max_layers: params.max_layers,
    tile_types: params.tile_types,
    obstacle_types: params.obstacle_types,
    goals: params.goals,
    symmetry_mode: params.symmetry_mode,
    pattern_type: params.pattern_type,
    max_retries: validationOptions?.max_retries ?? 5,
    tolerance: validationOptions?.tolerance ?? 15.0,
    simulation_iterations: validationOptions?.simulation_iterations ?? 30,
    use_best_match: validationOptions?.use_best_match ?? true,  // Default: use best match strategy
    // Auto gimmick selection
    auto_select_gimmicks: gimmickOptions?.auto_select_gimmicks,
    available_gimmicks: gimmickOptions?.available_gimmicks,
  };

  // Calculate timeout: base 60s + extra time for retries and simulations
  // Each retry with 30 iterations takes ~5-10 seconds
  const maxRetries = request.max_retries ?? 5;
  const timeoutMs = 60000 + (maxRetries * 15000); // 60s base + 15s per retry

  const response = await apiClient.post<ValidatedGenerateResult>('/generate/validated', request, {
    timeout: timeoutMs,
  });
  return response.data;
}
