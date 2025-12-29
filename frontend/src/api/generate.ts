import apiClient from './client';
import type { LevelJSON, GenerationParams, GenerationResult, SimulationResult, ObstacleCountConfig, LayerTileConfig, LayerObstacleConfig } from '../types';

export interface GenerateRequest {
  target_difficulty: number;
  grid_size?: [number, number];
  max_layers?: number;
  tile_types?: string[];
  obstacle_types?: string[];
  goals?: Array<{ type: string; count: number }>;
  obstacle_counts?: Record<string, ObstacleCountConfig>;
  // Per-layer configurations
  layer_tile_configs?: LayerTileConfig[];
  layer_obstacle_configs?: LayerObstacleConfig[];
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
