/**
 * 검증 탭 C 확인 측정 작업 API (문서 38 §10) — backend/app/models/schemas.py ClearRateVerify* · ClearRateTargetCheck* 와 1:1.
 * - 모드 A 전용. 탐색 측정(모델 캐시 seed11M·파일럿 대역)은 C 가 아니다 — C 는 서버가 CV 대역으로 잰 기록만.
 * - 판정용 측정 원자료는 요청에 싣지 않는다(서버 저장소에서 job_id 로 읽음).
 * - 사용자가 명시적으로 누를 때만 호출한다(탭 진입·복원·목표 수정으로 측정 요청 금지). 상태 조회는 측정이 아니다.
 * - C 측정은 봇 측정 재현성 확인이며 실유저 클리어율 독립 검증이 아니다.
 */
import apiClient from './client';
import type { LevelJSON } from '../types';
import type { UserExpectedResult } from './clearRateTarget';

export type ConfirmJobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
export type MeasurementKind = 'exploration' | 'confirm';

export interface ConfirmJob {
  schema: number;
  job_id: string;
  job_key: string;
  measurement_kind: 'confirm';
  target_mode: 'user_expected';
  status: ConfirmJobStatus;
  map_id: string;
  batch_id: string;
  placement_level: number;
  cond_hash: string;
  bot_config_hash: string;
  protocol: string;
  seed_band: string;
  seed_base: number;
  bot_version: string;
  model_version_at_submit: string;
  games_planned: number;
  /** 진행 표시용. 실패·취소·중단 작업의 값은 부분 결과이며 완료 C 가 아니다 */
  games_done: number;
  cancel_requested: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  measurement_ref: string | null;
  /** 서버 재시작으로 중단된 작업 */
  interrupted?: boolean;
}

export interface VerifyItem {
  level_json: LevelJSON | Record<string, unknown>;
  placement_level: number;
  map_id?: string;
  batch_id?: string;
  upload_opts?: { auto_collect_mode: 'multiples10' | 'preserve'; auto_collect_value: number } | null;
}

export interface VerifyPlanItem {
  map_id: string;
  placement_level: number;
  cond_hash?: string;
  bot_config_hash?: string;
  protocol?: string;
  seed_band?: string;
  bot_version?: string;
  games_planned?: number;
  job_key?: string;
  /** 측정해도 판정 불가(학습 지원 밖) — 요청 시 서버가 거부 */
  blocking?: string[];
  warnings?: string[];
  protocol_problems?: string[];
  model_version?: string;
  existing?: ConfirmJob | null;
  error?: string;
}

export interface VerifyPlanResponse {
  items: VerifyPlanItem[];
  seed_band: string;
  max_concurrent: number;
  judge_version: string;
  note: string;
}

export interface VerifySubmitResponse {
  job: ConfirmJob;
  created: boolean;
  /** active = 중복 요청이 진행 중 작업에 합류 / done = 완료 C 재사용(재측정 없음) */
  reused: 'active' | 'done' | null;
}

export interface ConfirmProvenance {
  measurement_kind: 'confirm';
  job_id: string;
  measurement_ref: string;
  seed_band: string;
  seed_base: number;
  protocol: string;
  bot_version: string;
  bot_config_hash: string;
  cond_hash: string;
  games_completed: number;
  measured_at: string | null;
  model_version: string;
  judge_version: string;
  evaluated_at: string;
}

export interface VerifyEvaluateResponse {
  target_mode: 'user_expected';
  measurement_kind: 'confirm';
  user_expected: UserExpectedResult;
  provenance: ConfirmProvenance;
}

export interface TargetCheckItem {
  placement_level: number;
  target: number;
  /** user_expected_precheck 코드 — 비어 있으면 현 모델로 판정 가능 */
  codes: string[];
  judgeable: boolean;
}

export async function planConfirm(items: VerifyItem[]): Promise<VerifyPlanResponse> {
  return (await apiClient.post<VerifyPlanResponse>('/clear-rate/verify/plan', { items })).data;
}

export async function submitConfirm(item: VerifyItem & { expected_cond_hash: string }): Promise<VerifySubmitResponse> {
  return (await apiClient.post<VerifySubmitResponse>('/clear-rate/verify/jobs',
    { ...item, target_mode: 'user_expected' })).data;
}

export async function queryConfirmJobs(jobIds: string[]): Promise<Record<string, ConfirmJob | null>> {
  return (await apiClient.post<{ jobs: Record<string, ConfirmJob | null> }>('/clear-rate/verify/jobs/query',
    { job_ids: jobIds })).data.jobs;
}

export async function cancelConfirm(jobId: string): Promise<ConfirmJob> {
  return (await apiClient.post<ConfirmJob>(`/clear-rate/verify/jobs/${encodeURIComponent(jobId)}/cancel`)).data;
}

export async function evaluateConfirm(req: {
  job_id: string; target: number; level_json: VerifyItem['level_json']; placement_level: number;
}): Promise<VerifyEvaluateResponse> {
  return (await apiClient.post<VerifyEvaluateResponse>('/clear-rate/verify/evaluate', req)).data;
}

export async function checkTargets(items: { placement_level: number; target: number }[]):
  Promise<{ model_version: string; items: TargetCheckItem[] }> {
  return (await apiClient.post<{ model_version: string; items: TargetCheckItem[] }>(
    '/clear-rate/verify/target-check', { items })).data;
}

export interface VerifyInfo {
  model_version: string;
  judge_version: string;
  seed_band: string;
  max_concurrent: number;
  bot_version: string;
  bot_protocol: string;
  games_per_map: number;
  protocol_problems: string[];
  note: string;
}

/** 현재 모델·판정 기준 버전 (복원한 결과의 "오래됨" 판단용). 봇을 돌리지 않는다 */
export async function getVerifyInfo(): Promise<VerifyInfo> {
  return (await apiClient.get<VerifyInfo>('/clear-rate/verify/info')).data;
}
