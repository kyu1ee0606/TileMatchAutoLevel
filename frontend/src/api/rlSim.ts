import apiClient from './client';
import type { LevelJSON } from '../types';

export interface SkillCurvePoint {
  theta: number;
  clear_rate: number;
  iterations: number;
  ci_half_width: number;
  avg_moves: number;
  avg_tiles_cleared: number;
}

export type RLSimClassification =
  | 'very_easy'
  | 'easy'
  | 'normal'
  | 'hard'
  | 'very_hard'
  | 'unclearable_suspect';

export interface RLSimResult {
  theta_star: number | null;
  /** 메인 연속 난이도 지표 = 1 - AUC */
  difficulty_score: number | null;
  auc: number | null;
  /** 로지스틱 중간점 (정제된 50% 스킬 지점) */
  theta0: number | null;
  /** 로지스틱 기울기 (실력 민감도 — 낮으면 운빨 레벨) */
  k: number | null;
  /** P(θ=0.9) - P(θ=0.15) */
  delta_p: number | null;
  luck_suspect: boolean;
  classification: RLSimClassification;
  max_clear_rate: number;
  min_clear_rate: number;
  /** 예측 유저 클리어율 (검증 주력 지표) — 캐주얼 실력분포 가중, 0~1 */
  predicted_clear_rate: number;
  /** 목표곡선 기대 클리어율 0~1 (요청에 target_difficulty 준 경우만 채워짐) */
  target_clear_rate: number | null;
  /** predicted - target (양수=목표보다 쉬움) */
  clear_rate_gap: number | null;
  /** |gap|<=tol AND not unclearable_suspect */
  verification_passed: boolean | null;
  skill_curve: SkillCurvePoint[];
  total_rollouts: number;
  elapsed_ms: number;
  config: {
    skill_grid: number[];
    rollouts_per_point: number;
    seed: number;
  };
}

export interface RLSimBatchResultItem extends RLSimResult {
  level_number: number;
  error: string | null;
}

export interface RLSimBatchResponse {
  results: RLSimBatchResultItem[];
  elapsed_ms: number;
  workers: number;
}

export interface RLSimConfig {
  default_skill_grid: number[];
  default_rollouts_per_point: number;
  default_seed: number;
  max_batch_size: number;
  workers: number;
}

export interface RLSimRequest {
  level_json: LevelJSON;
  skill_grid?: number[];
  rollouts_per_point?: number;
  seed?: number;
  max_moves?: number;
  /** 목표난이도. 지정 시 예측클리어율을 목표곡선과 비교해 통과여부 산출 */
  target_difficulty?: number;
}

export interface RLSimBatchRequest {
  levels: { level_number: number; level_json: LevelJSON }[];
  skill_grid?: number[];
  rollouts_per_point?: number;
  seed?: number;
  max_moves?: number;
}

export async function getRLSimConfig(): Promise<RLSimConfig> {
  const response = await apiClient.get<RLSimConfig>('/rl-sim/config');
  return response.data;
}

export async function simulateLevelSkillSweep(request: RLSimRequest): Promise<RLSimResult> {
  // 스킬 스윕은 레벨에 따라 수십 초 걸릴 수 있어 기본 30s 타임아웃을 늘림
  const response = await apiClient.post<RLSimResult>('/rl-sim/level', request, {
    timeout: 300000,
  });
  return response.data;
}

export interface RLSearchRequest {
  level_number: number;
  target_theta0: number;
  target_k?: number;
  target_difficulty_score?: number;
  candidates?: number;
  finalists?: number;
  rollouts_per_point?: number;
  seed?: number;
}

export interface RLSearchCandidate {
  index: number;
  gen_params: Record<string, string | number>;
  static_ok: boolean;
  reject_reason: string | null;
  screen_distance: number | null;
  finalist: boolean;
  score: number | null;
  theta0: number | null;
  k: number | null;
  difficulty_score: number | null;
  classification: string | null;
}

export interface RLSearchBest {
  candidate_index: number;
  score: number;
  gen_params: Record<string, string | number>;
  level_json: LevelJSON;
  measurement: Omit<RLSimResult, 'elapsed_ms'> & { skill_curve: SkillCurvePoint[] };
}

export interface RLSearchResponse {
  accepted: boolean;
  tolerance: number;
  best: RLSearchBest | null;
  candidates: RLSearchCandidate[];
  elapsed_ms: number;
  config: Record<string, unknown>;
}

export async function searchCurveTarget(request: RLSearchRequest): Promise<RLSearchResponse> {
  const response = await apiClient.post<RLSearchResponse>('/rl-sim/search', request, {
    timeout: 600000,
  });
  return response.data;
}

export async function simulateBatchSkillSweep(request: RLSimBatchRequest): Promise<RLSimBatchResponse> {
  // 청크(워커 수 단위) 병렬 처리 — 가장 느린 레벨 기준이므로 여유 있게
  const response = await apiClient.post<RLSimBatchResponse>('/rl-sim/batch', request, {
    timeout: 600000,
  });
  return response.data;
}
