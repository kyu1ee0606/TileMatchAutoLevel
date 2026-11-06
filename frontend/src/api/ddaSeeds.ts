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

export type DdaExportSeedField = 'ddaEasy2Seeds' | 'ddaEasySeeds' | 'ddaHardSeeds' | 'ddaHard2Seeds';
export const DDA_EXPORT_SEED_FIELDS: DdaExportSeedField[] = ['ddaEasy2Seeds', 'ddaEasySeeds', 'ddaHardSeeds', 'ddaHard2Seeds'];

/** 실제 업로드가 보낼 시드 열. 키가 없는 열 = 전송 생략(서버 기존 값 유지). */
export interface DdaExportField extends Partial<Record<DdaExportSeedField, string>> {
  target_id: string;
  /** send:<열,..> | omitted | infinity_omitted | infinity_data | not_level_row | check_error:.. */
  reason: string;
  fieldReasons?: Partial<Record<DdaExportSeedField, string>>;
  /** 보낼 열의 클리어 가능 판정 근거: ok / none / binding_mismatch / partial:n/m.
   *  서버 값과 다른데 ok 가 아니면 실제 업로드에서 그 열을 보내지 않는다(서버 값 유지). */
  fieldEvidence?: Partial<Record<DdaExportSeedField, string>>;
  /** [무한 그림 치환 v1] infinity_N 행을 치환본으로 판정했을 때만 있음 */
  relabel?: InfinityRelabelInfo;
}

/** [무한 그림 치환 v1] 백엔드 app.core.infinity_relabel 결과. mapping = {"t3": "t7", ...} (K<2 면 빈 객체) */
export interface InfinityRelabelInfo {
  rule: string;
  slot: number;
  mapping: Record<string, string>;
}

export async function previewDdaSeeds(
  levels: Array<{ level_number: number; level_json: LevelJSON }>
): Promise<DdaPreviewResponse> {
  const r = await apiClient.post<DdaPreviewResponse>('/dda-seeds/preview', { levels }, { timeout: 120000 });
  return r.data;
}

/** 실제 업로드가 보낼 시드 열(같은 백엔드 판정). levels 보드가 아니면 results 가 비어 있다. */
export async function previewDdaExport(
  boardId: string,
  levels: Array<{ target_id: string; level_json: LevelJSON }>,
  /** [무한 그림 치환 v1] 업로드(saveToGBoost)와 같은 값을 넘겨야 binding 이 같은 맵을 본다 */
  infinityRelabel: boolean = true
): Promise<{ board_id: string; applies: boolean; results: DdaExportField[] }> {
  const r = await apiClient.post('/dda-seeds/export-preview',
    { board_id: boardId, levels, infinity_relabel: infinityRelabel }, { timeout: 120000 });
  return r.data;
}

/** [무한 그림 치환 v1] JSON 내보내기용 — infinity_N 행 level_json 을 업로드와 같은 백엔드 규칙으로 치환(다른 id 는 그대로). */
export async function relabelInfinityLevels(
  levels: Array<{ target_id: string; level_json: LevelJSON }>,
  infinityRelabel: boolean = true
): Promise<{ rule: string; enabled: boolean;
  results: Array<{ target_id: string; level_json: LevelJSON; relabel: InfinityRelabelInfo | null }> }> {
  const r = await apiClient.post('/dda-seeds/infinity-relabel',
    { levels, infinity_relabel: infinityRelabel }, { timeout: 120000 });
  return r.data;
}
