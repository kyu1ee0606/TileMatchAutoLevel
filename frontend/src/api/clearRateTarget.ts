/**
 * 실험 경로: 두 모드 목표 평가 (문서 35 §9) — POST /api/clear-rate/target-eval.
 * 백엔드 스키마: backend/app/models/schemas.py ClearRateTargetEval* 와 1:1.
 * A(user_expected) = 예상 유저 클리어율(ft_any_v1, 보정 모델). B(bot_virtual) = 봇 가상 클리어율(봇 v2.4 규칙만·θ0.85·무도움).
 * 모드는 반드시 지정(기본값 없음). A 실패 시 B 로 자동 전환하지 않는다. B 값은 실측 미검증이며
 * predicted_clear_rate·A 필드·게임 표시 난이도·업로드에 연결하지 않는다. 생성·검증·업로드 경로는 이 API 를 부르지 않는다.
 */
import apiClient from './client';
import type { LevelJSON } from '../types';
import type { ClearRateBotMeasurement, ClearRatePredictResponse } from './clearRate';

export type TargetMode = 'user_expected' | 'bot_virtual';

export interface ClearRateTargetEvalRequest {
  target_mode: TargetMode;
  /** A: 목표 ft_any / B: θ0.85 봇 목표 성공률 — 두 값은 서로 비교하지 않는다 */
  target: number;
  level_json: LevelJSON | Record<string, unknown>;
  placement_level?: number | null;
  /** 탐색 시드 묶음 S 측정 (선별용) */
  bot_measurement_search?: ClearRateBotMeasurement | null;
  /** 확인 시드 묶음 C 측정 (판정용 — 봇 측정 안정성 확인일 뿐 실유저 검증 아님) */
  bot_measurement_confirm?: ClearRateBotMeasurement | null;
  upload_opts?: { auto_collect_mode: 'multiples10' | 'preserve'; auto_collect_value: number } | null;
  /** A 전용 opt-in(검증 탭, 문서 38): S/C 측정이 없으면 /predict 와 같은 모델 측정 캐시 사용.
   *  캐시는 확인 시드(C)가 아니므로 판정은 근거 부족으로 남는다. B 는 무시 */
  use_cached_measurement?: boolean;
}

export type UserExpectedVerdict = 'PASS' | 'FAIL' | 'INSUFFICIENT_EVIDENCE';
export type BotVirtualVerdict = 'BOT_TARGET_MET' | 'BOT_TARGET_NOT_MET' | 'BOT_MEASUREMENT_INSUFFICIENT';

export interface UserExpectedResult {
  target_mode: 'user_expected';
  target_metric: string;
  target: number;
  prediction: ClearRatePredictResponse;
  verdict: {
    verdict: UserExpectedVerdict;
    reason: string;
    target: number;
    band: [number, number];
    p_in_band: number | null;
    in_range80_reference: boolean | null;
    bot_seed_confirmed: boolean;
    confidence: string | null;
    support_reasons?: string[];
    target_flags?: { code: string; severity: 'hard' | 'soft'; detail: string }[];
    [k: string]: unknown;
  };
  criteria: string;
}

export interface BotVirtualRate {
  theta: number;
  wins: number;
  games: number;
  rate: number;
  ci95: [number, number];
  half_width: number;
  seed_band: string;
  cond_hash: string;
  protocol: string;
}

export interface BotVirtualResult {
  target_mode: 'bot_virtual';
  bot_virtual_def: Record<string, unknown>;
  bot_virtual_def_id: string;
  cond_hash: string;
  bot_virtual_target: number;
  bot_virtual_tolerance: number;
  bot_virtual_s: BotVirtualRate | null;
  bot_virtual_c: BotVirtualRate | null;
  bot_virtual_verdict: BotVirtualVerdict;
  reason: string;
  bot_virtual_rate_c: number | null;
  bot_virtual_ci95_c: [number, number] | null;
  bot_virtual_half_width_c: number | null;
  bot_virtual_games_c: number;
  bot_virtual_gap: number | null;
  /** 항상 'unverified' — 봇 결과는 실유저 검증이 아니다 */
  real_user_status: 'unverified';
  notes: string[];
}

export interface ClearRateTargetEvalResponse {
  target_mode: TargetMode;
  user_expected: UserExpectedResult | null;
  bot_virtual: BotVirtualResult | null;
}

export async function evaluateClearRateTarget(req: ClearRateTargetEvalRequest): Promise<ClearRateTargetEvalResponse> {
  const res = await apiClient.post<ClearRateTargetEvalResponse>('/clear-rate/target-eval', req);
  return res.data;
}
