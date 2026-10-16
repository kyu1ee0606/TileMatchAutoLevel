/**
 * 새 실유저 클리어율 예측 (첫 시도·도움 포함, ft_any_v1) — 기존 predicted_clear_rate 옆 병행 표시용.
 * 판정·업로드 값과 무관한 참고 지표다 (claudedocs/difficulty_personalization/31·33).
 * 백엔드 스키마: backend/app/models/schemas.py ClearRatePredict* 와 1:1.
 */
import apiClient from './client';
import type { LevelJSON } from '../types';
import type { ProductionLevelMeta } from '../types/production';

export type ClearRateStatus = 'ok' | 'insufficient_evidence' | 'measurement_required';
export type ClearRateConfidence = 'high' | 'medium' | 'low';

export interface ClearRateEvidenceFlag {
  /** 문서 31 §3-2 코드 — PLACEMENT_MISSING, LEVEL_OUT_OF_RANGE, GIMMICK_UNSEEN, GIMMICK_LOW_TRAIN,
   *  FEATURE_OOD, BOT_PROTOCOL_MISMATCH, UNSOLVED, TARGET_OUT_OF_SUPPORT (hard) /
   *  LOW_CONFIDENCE, NEAR_CEILING, GIMMICK_FIRST, NOVELTY_HIGH, GIMMICK_BOT_WEAK (soft) */
  code: string;
  severity: 'hard' | 'soft';
  detail: string;
}

export interface ClearRateBotRow {
  theta: number;
  games: number;
  wins: number;
  fail_reasons?: Record<string, number>;
  fail_tiles_left_board?: number[] | null;
  fail_tiles_left?: number[] | null;
}

export interface ClearRatePredictRequest {
  level_json: LevelJSON | Record<string, unknown>;
  /** 이 맵을 놓을 레벨 번호 — 없으면 예측하지 않고 PLACEMENT_MISSING 사유만 돌려준다 */
  placement_level?: number | null;
  target?: { metric?: string; value: number } | null;
  /** 생략하면 모델의 봇 측정 캐시(라이브 맵)를 쓴다 */
  bot_measurement?: { bot_version: string; protocol: string; rows: ClearRateBotRow[] } | null;
}

export interface ClearRatePredictResponse {
  model_version: string;
  target_metric: string;
  bot_version: string;
  status: ClearRateStatus;
  placement_level: number | null;
  map_hash: string;
  /** 예상 첫 시도 클리어율(도움 포함) 0~1. 근거 부족·측정 필요면 null */
  expected: number | null;
  range80: [number, number] | null;
  confidence: ClearRateConfidence | null;
  evidence_flags: ClearRateEvidenceFlag[];
  aux: { unaided_lb: number | null; help_rate: number | null };
  /** 목표를 줬을 때만 — 80% 범위 포함 여부(정보용, 판정 아님) */
  target: { value: number; in_range80: boolean } | null;
  bot_source: 'cache' | 'request' | null;
  /** 봇 승률(참고) — 클리어율 아님 */
  bot_success_reference: Record<string, number>;
}

export async function predictClearRate(req: ClearRatePredictRequest): Promise<ClearRatePredictResponse> {
  const res = await apiClient.post<ClearRatePredictResponse>('/clear-rate/predict', req);
  return res.data;
}

/** 응답 → 레벨 메타 새 필드 (기존 predicted_clear_rate·verification_passed 는 건드리지 않음) */
export function toClearRateMeta(res: ClearRatePredictResponse): Pick<ProductionLevelMeta,
  'expected_clear_rate_v1' | 'clear_rate_range80' | 'clear_rate_confidence' | 'clear_rate_evidence_flags' |
  'unaided_lb_expected' | 'help_rate_expected' | 'clear_rate_model_version' | 'clear_rate_status' |
  'clear_rate_placement_level'> {
  return {
    expected_clear_rate_v1: res.expected,
    clear_rate_range80: res.range80,
    clear_rate_confidence: res.confidence,
    clear_rate_evidence_flags: res.evidence_flags,
    unaided_lb_expected: res.aux.unaided_lb,
    help_rate_expected: res.aux.help_rate,
    clear_rate_model_version: res.model_version,
    clear_rate_status: res.status,
    clear_rate_placement_level: res.placement_level,
  };
}
