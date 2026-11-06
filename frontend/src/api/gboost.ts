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
  levelJson: LevelJSON,
  /** [DDA 문서 47] levels 보드에서 서버의 비어 있지 않은 시드를 비우거나 바꾸는 것을 사용자가 미리보기로 확인함 */
  ddaConfirm: boolean = false,
  /** [무한 그림 치환 v1] levelId 가 infinity_N 이면 백엔드가 변환 전에 그림 번호를 치환(기본 켬) */
  infinityRelabel: boolean = true,
  /** [DDA 시드 이력] 장부 세션 id — 백엔드가 실제 전송 payload 를 이 세션에 기록(없으면 자동 세션) */
  ledgerSession?: string
): Promise<GBoostSaveResponse> {
  const response = await apiClient.post<GBoostSaveResponse>(
    `/gboost/${boardId}/${levelId}`,
    { level_json: levelJson, dda_confirm: ddaConfirm, infinity_relabel: infinityRelabel },
    ledgerSession ? { params: { ledger_session: ledgerSession } } : undefined
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
  limit: number = 100,
  /** [문서 47] true 면 서버 조회 실패를 빈 목록 대신 오류(502)로 받는다 — 업로드 전 검사용 */
  strict: boolean = false
): Promise<GBoostListResponse> {
  const response = await apiClient.get<GBoostListResponse>(
    `/gboost/${boardId}`,
    { params: strict ? { prefix, limit, strict: true } : { prefix, limit } }
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

// [DDA 시드만 v2 · 2026-11-03] levels 보드 기존 행의 시드 4열 중 '바뀌고 근거 있는' 열만 update(new=0).
// 값 출처 = 맵툴 배치 파일(백엔드가 직접 읽음). 탭은 행 id·원본 레벨 번호·자기가 아는 배치 버전만 보낸다.
export type DdaSeedField = 'ddaEasy2Seeds' | 'ddaEasySeeds' | 'ddaHardSeeds' | 'ddaHard2Seeds';
export type DdaSeedCellState = 'send' | 'same' | 'kept' | 'unverified' | 'blocked';
export interface DdaSeedCell {
  state: DdaSeedCellState;
  server?: string;
  value?: string;
  why?: string;
  kind?: 'fill' | 'change';
}
export interface DdaSeedExportResult {
  target_id: string;
  source_level?: number;
  blocked: boolean;
  status?: 'preview' | 'blocked' | 'saved' | 'failed' | 'unchanged';
  reason: string;
  detail?: string;
  change?: 'same' | 'fill' | 'change';
  cells?: Partial<Record<DdaSeedField, DdaSeedCell>>;
  serverDigest?: string;
  sent?: DdaSeedField[];
}
export interface DdaSeedExportResponse {
  dry_run: boolean;
  preview_id: string | null;
  gbTarget?: { base_url: string; project_id: string; board_id: string };
  trial: (Record<string, unknown> & { judge?: { passed?: boolean }; recordPath?: string }) | null;
  batchVersion: number;
  batchFileSha256: string;
  boardRawSha256?: string;
  partialUpdate: { allowed: boolean; by: string | null; codeHash: string; record?: string; target_id?: string };
  summary: { cells: Record<DdaSeedCellState, number>; rows: Record<string, number> };
  results: DdaSeedExportResult[];
}

export async function ddaSeedExport(request: {
  batch_id: string;
  expected_batch_version: number;
  expected_batch_sha256?: string;
  targets: Array<{ target_id: string; source_level: number; expected_server_digest?: string }>;
  dry_run: boolean;
  confirm?: boolean;
  trial?: boolean;
  infinity_relabel?: boolean;
  client_unsynced_edits?: number;
  preview_id?: string;
  selection?: Record<string, string | number | boolean | null>;
}, ledgerSession?: string): Promise<DdaSeedExportResponse> {
  const response = await apiClient.post('/gboost/dda-seed-export', request, {
    timeout: 600000,
    params: ledgerSession ? { ledger_session: ledgerSession } : undefined,
  });
  return response.data;
}
