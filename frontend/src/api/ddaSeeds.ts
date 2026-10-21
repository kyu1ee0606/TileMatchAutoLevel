/**
 * DDA 시드 갱신 사전검사 / 익스포트 미리보기 (문서 47). 둘 다 읽기 전용 — GameBoost 호출 없음.
 * 백엔드: backend/app/api/routes/dda_seeds.py
 */
import apiClient from './client';
import type { LevelJSON } from '../types';

export type DdaSeedField = 'ddaEasySeeds' | 'ddaHardSeeds';
export type DdaSeedState = 'match' | 'missing' | 'invalid' | 'other';
export type DdaAction = 'update' | 'keep' | 'conflict' | 'skip';

export interface DdaFieldPlan {
  state: DdaSeedState;
  before: string | null;
  after: string | null;
}

export interface DdaLevelPlan {
  level: number;
  action: DdaAction;
  /** update:fill / keep:already_valid / conflict:conflict /
   *  skip: no_data | hold | partial_hold | excluded | map_mismatch | n_mismatch | catalog_error | check_error */
  reason: string;
  detail?: string;
  fields?: Record<DdaSeedField, DdaFieldPlan>;
}

export interface DdaCatalogInfo {
  ok: boolean;
  error?: string;
  catalogVersion?: string;
  settingsVersion?: string;
  sha256?: string;
  counts?: { levels: number; byStatus: Record<string, number> };
}

export interface DdaPreviewResponse {
  catalog: DdaCatalogInfo;
  summary: { total: number; byAction: Record<string, number>; byReason: Record<string, number> };
  results: DdaLevelPlan[];
}

export interface DdaExportField {
  target_id: string;
  ddaEasySeeds: string;
  ddaHardSeeds: string;
  reason: string;
}

export async function previewDdaSeeds(
  levels: Array<{ level_number: number; level_json: LevelJSON }>
): Promise<DdaPreviewResponse> {
  const r = await apiClient.post<DdaPreviewResponse>('/dda-seeds/preview', { levels }, { timeout: 120000 });
  return r.data;
}

/** 실제 업로드가 보낼 두 필드 값(같은 백엔드 판정). levels 보드가 아니면 results 가 비어 있다. */
export async function previewDdaExport(
  boardId: string,
  levels: Array<{ target_id: string; level_json: LevelJSON }>
): Promise<{ board_id: string; applies: boolean; results: DdaExportField[] }> {
  const r = await apiClient.post('/dda-seeds/export-preview', { board_id: boardId, levels }, { timeout: 120000 });
  return r.data;
}
