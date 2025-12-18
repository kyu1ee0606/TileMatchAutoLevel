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
