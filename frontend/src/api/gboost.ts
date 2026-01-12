import apiClient from './client';
import type { LevelJSON, LevelMetadata } from '../types';

export interface GBoostSaveResponse {
  success: boolean;
  saved_at: string;
  message: string;
}

export interface GBoostLoadResponse {
  level_json: LevelJSON;
  metadata: {
    id: string;
    created_at: string;
    updated_at?: string;
    version?: string;
  };
}

export interface GBoostListResponse {
  levels: LevelMetadata[];
}

export interface GBoostHealthResponse {
  configured: boolean;
  healthy?: boolean;
  project_id?: string;
  message?: string;
  error?: string;
}

export interface GBoostConfigResponse {
  configured: boolean;
  url?: string;
  project_id?: string;
  message: string;
}

export interface GBoostConfigRequest {
  url: string;
  api_key: string;
  project_id: string;
}

/**
 * Get GBoost configuration.
 */
export async function getGBoostConfig(): Promise<GBoostConfigResponse> {
  const response = await apiClient.get<GBoostConfigResponse>('/gboost/config');
  return response.data;
}

/**
 * Update GBoost configuration.
 */
export async function setGBoostConfig(config: GBoostConfigRequest): Promise<GBoostConfigResponse> {
  const response = await apiClient.post<GBoostConfigResponse>('/gboost/config', config);
  return response.data;
}

/**
 * Check GBoost health and configuration.
 */
export async function checkGBoostHealth(): Promise<GBoostHealthResponse> {
  const response = await apiClient.get<GBoostHealthResponse>('/gboost/health');
  return response.data;
}

/**
 * Save a level to GBoost.
 */
export async function saveToGBoost(
  boardId: string,
  levelId: string,
  levelJson: LevelJSON
): Promise<GBoostSaveResponse> {
  const response = await apiClient.post<GBoostSaveResponse>(
    `/gboost/${boardId}/${levelId}`,
    { level_json: levelJson }
  );
  return response.data;
}

/**
 * Load a level from GBoost.
 */
export async function loadFromGBoost(
  boardId: string,
  levelId: string
): Promise<GBoostLoadResponse> {
  const response = await apiClient.get<GBoostLoadResponse>(
    `/gboost/${boardId}/${levelId}`
  );
  return response.data;
}

/**
 * List levels from GBoost.
 */
export async function listFromGBoost(
  boardId: string,
  prefix: string = 'level_',
  limit: number = 100
): Promise<GBoostListResponse> {
  const response = await apiClient.get<GBoostListResponse>(
    `/gboost/${boardId}`,
    { params: { prefix, limit } }
  );
  return response.data;
}

/**
 * Delete a level from GBoost.
 */
export async function deleteFromGBoost(
  boardId: string,
  levelId: string
): Promise<{ success: boolean; message: string }> {
  const response = await apiClient.delete(`/gboost/${boardId}/${levelId}`);
  return response.data;
}

// Upload local levels to GBoost
export interface UploadLocalRequest {
  board_id: string;
  level_ids: string[];
  target_prefix?: string;
  rename_strategy?: 'keep' | 'sequential' | 'custom';
  custom_names?: Record<string, string>;
  overwrite?: boolean;
  start_index?: number;
}

export interface UploadProgressItem {
  level_id: string;
  target_id: string;
  status: 'pending' | 'uploading' | 'success' | 'failed' | 'skipped';
  message: string;
}

export interface UploadLocalResponse {
  success: boolean;
  total: number;
  uploaded: number;
  failed: number;
  skipped: number;
  results: UploadProgressItem[];
}

/**
 * Upload local levels to GBoost server.
 */
export async function uploadLocalToGBoost(
  request: UploadLocalRequest
): Promise<UploadLocalResponse> {
  const response = await apiClient.post<UploadLocalResponse>(
    '/gboost/upload-local',
    request
  );
  return response.data;
}

// Thumbnail upload
export interface ThumbnailUploadRequest {
  board_id: string;
  level_id: string;
  png_base64: string;
  size?: number;
}

export interface ThumbnailUploadResponse {
  success: boolean;
  message: string;
}

/**
 * Upload a thumbnail image for a level.
 */
export async function uploadThumbnail(
  request: ThumbnailUploadRequest
): Promise<ThumbnailUploadResponse> {
  const response = await apiClient.post<ThumbnailUploadResponse>(
    '/gboost/thumbnail',
    request
  );
  return response.data;
}
