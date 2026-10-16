/**
 * 새 실유저 클리어율 예측 (첫 시도·도움 포함, ft_any_v1) — 기존 predicted_clear_rate 옆 병행 표시용.
 * 판정·업로드 값과 무관한 참고 지표다 (claudedocs/difficulty_personalization/31·33). 판정 함수(clear_rate.judge)는 API 에 노출하지 않음.
 * 백엔드 스키마: backend/app/models/schemas.py ClearRatePredict* 와 1:1.
 */
import apiClient from './client';
import type { LevelJSON } from '../types';
import type { ProductionLevelMeta } from '../types/production';

export type ClearRateStatus = 'ok' | 'insufficient_evidence' | 'measurement_required';
export type ClearRateConfidence = 'high' | 'medium' | 'low';

export interface ClearRateEvidenceFlag {
  /** 문서 31 §3-2 코드 + 측정 조건 코드.
   *  hard(예측 대신 사유): PLACEMENT_MISSING, LEVEL_OUT_OF_RANGE, GIMMICK_UNSEEN, GIMMICK_LOW_TRAIN, FEATURE_OOD,
   *  BOT_PROTOCOL_MISMATCH, MEASUREMENT_MISSING, MEASUREMENT_CONDITION_MISMATCH, UNSOLVED
   *  soft: LOW_CONFIDENCE, NEAR_CEILING, GIMMICK_FIRST, NOVELTY_HIGH, GIMMICK_BOT_WEAK */
  code: string;
  severity: 'hard' | 'soft';
  detail: string;
}

/** 봇 측정 1행 — 봇은 도움 없이 플레이한다(무도움 봇 성공률 = 입력, 클리어율 아님) */
export interface ClearRateBotRow {
  theta: number;
  games: number;
  wins: number;
  fail_reasons?: Record<string, number>;
  fail_tiles_left_board?: number[] | null;
  fail_tiles_left?: number[] | null;
}

export interface ClearRateBotMeasurement {
  bot_version: string;
  protocol: string;
  /** 측정한 최종 게임 조건 해시 — 현재 조건 해시와 다르면 MEASUREMENT_CONDITION_MISMATCH */
  condition_hash: string;
  seed_set?: string;
  rows: ClearRateBotRow[];
}

export interface ClearRatePredictRequest {
  level_json: LevelJSON | Record<string, unknown>;
  /** 이 맵을 놓을 레벨 번호 — 없으면 예측하지 않고 PLACEMENT_MISSING 사유만 돌려준다 */
  placement_level?: number | null;
  /** 생략하면 모델의 라이브 빌드 봇 측정 캐시(조건 해시로 조회)를 쓴다 */
  bot_measurement?: ClearRateBotMeasurement | null;
}

export interface ClearRateMeasurementMeta {
  source: 'cache' | 'request';
  bot_version: string;
  protocol: string;
  seed_set: string;
  condition_hash: string;
}

export interface ClearRatePredictResponse {
  model_version: string;
  /** ft_any_v1 = 실유저 첫 시도 클리어율(도움 포함, 종료된 판) */
  target_metric: string;
  bot_version: string;
  bot_protocol: string;
  placement_level: number | null;
  /** 이 요청의 최종 게임 조건(업로드 변환 기준) 해시 */
  condition_hash: string;
  status: ClearRateStatus;
  /** false 면 숫자 없음 — 사유는 insufficient_reasons */
  in_support: boolean;
  insufficient_reasons: string[];
  evidence_flags: ClearRateEvidenceFlag[];
  /** 주 목표 예측 0~1 (실유저 첫 시도·도움 포함) */
  expected_ft_any: number | null;
  range80_ft_any: [number, number] | null;
  /** 보조: 실유저 무도움 첫 시도 클리어 비율(LB) 예측 */
  expected_unaided_lb: number | null;
  /** 보조: 실유저 첫 시도 도움 사용률 예측 (출력만, 입력 아님) */
  expected_help_rate: number | null;
  confidence: ClearRateConfidence | null;
  measurement: ClearRateMeasurementMeta | null;
  /** 봇(무도움) 승률 θ별 — 모델 입력, 클리어율 아님 */
  bot_unaided_win_rate: Record<string, number>;
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
    expected_clear_rate_v1: res.expected_ft_any,
    clear_rate_range80: res.range80_ft_any,
    clear_rate_confidence: res.confidence,
    clear_rate_evidence_flags: res.evidence_flags,
    unaided_lb_expected: res.expected_unaided_lb,
    help_rate_expected: res.expected_help_rate,
    clear_rate_model_version: res.model_version,
    clear_rate_status: res.status,
    clear_rate_placement_level: res.placement_level,
  };
}
