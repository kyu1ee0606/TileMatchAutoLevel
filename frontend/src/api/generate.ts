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
}

export interface SimulateRequest {
  level_json: LevelJSON;
  iterations?: number;
  strategy?: 'random' | 'greedy' | 'optimal';
}

/**
 * Generate a new level with target difficulty.
 */
export async function generateLevel(params: GenerationParams): Promise<GenerationResult> {
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
  };

  const response = await apiClient.post<GenerationResult>('/generate', request);
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
  };

  const response = await apiClient.post<ValidatedGenerateResult>('/generate/validated', request);
  return response.data;
}
