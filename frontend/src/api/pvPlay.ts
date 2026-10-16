/**
 * PV 시드 변형 수동 플레이 API (backend/app/api/routes/pv_play.py)
 *
 * 샌드박스(pv_sandbox) 레벨을 서버가 cs_shuffle(클라 비트 일치 포트)로 풀어 쓴 명시 맵으로 받는다.
 * 프론트에서 재배색/재분배하지 않는다. production 배치 저장·동기화와 무관.
 */
import apiClient from './client';

/** easy/hard = DDA reference_baked 구운 참고 행(selection=dda 보조), 나머지 = 시드 변형 / seedvar 토큰 칸 */
export type PvTier = 'orig' | 'e2' | 'e1' | 'b' | 'h1' | 'h2' | 'easy' | 'hard';

/** selection 버전. v4(기본) = 5단계/3단계/고정맵, v3 = utc±1 정책안(relaxed 우선), v2 = utc0 단일 5칸,
 *  dda = DDA 세트(원본 + seedvar_N 토큰 e2|e1|h1|h2 를 cs_shuffle 배정, reference_baked easy/hard 보조) */
export type PvSelection = 'v2' | 'v3' | 'v4' | 'dda';

export type PvLevelStatus = '5tier' | '3tier' | 'fixed_map' | 'bidirectional_unmet' | 'unevaluable' | 'not_finished' | string;

/** 07 독립 검증 판정. warn = 방향 신뢰 실패 또는 바깥 칸 |Δ|<0.08, stale = 검증 후 시드가 바뀜 */
export type PvVerdict = 'pass' | 'warn' | 'stale';

export interface PvTierVerification {
  verdict: PvVerdict;
  reasons: string[];
  delta: number | null;
  kept: number | null;
  n: number | null;
}

export interface PvLevelVerification {
  verdict: PvVerdict;
  tiers: Partial<Record<PvTier, PvTierVerification>>;
  innerUnstable: string[];
}

export interface PvLevelSummary {
  level: number;
  status: PvLevelStatus;
  utc: number | null;
  reason: string | null;
  wOrig: number | null;
  seeds: Partial<Record<PvTier, number>>;
  /** tier 별 useTileCount (seed@utc 면 utc0±1) */
  tierUtc: Partial<Record<PvTier, number>>;
  /** b: deltaVsOrig, 나머지: deltaVsBase (봇 승률 차) */
  deltas: Partial<Record<PvTier, number>>;
  availableTiers: PvTier[];
  /** 독립 검증 결과 (없으면 null — 검증 대상 아님/미실시) */
  verification: PvLevelVerification | null;
}

export interface PvLevelsResponse {
  copyId: string;
  selection: PvSelection;
  selections: PvSelection[];
  tiers: PvTier[];
  levels: PvLevelSummary[];
}

export interface PvTierMapResponse {
  level: number;
  tier: PvTier;
  selection: PvSelection;
  status: PvLevelStatus;
  seed: number | null;
  /** 이 판 배정에 쓴 종류 수 */
  utc: number;
  /** 원맵 실제 종류 수 */
  utc0: number;
  verification: { level: PvVerdict; tier: PvTierVerification | null } | null;
  structHash: string;
  typesHash: string;
  tileCount: number;
  levelJson: Record<string, unknown>;
}

export interface PvManualPlayResult {
  level: number;
  tier: PvTier;
  seed: number | null;
  typesHash: string | null;
  won: boolean;
  /** abandoned = 끝나기 전 Restart·Back·탭 이탈 (1수 이상 둔 판만 기록) */
  outcome: 'won' | 'lost' | 'abandoned';
  moves: number;
  /** 보드 잔여 근사 = 총 타일 - 이동 수. 트레이에 남은 타일 미포함 */
  boardRemainingApprox: number | null;
  trayMaxOccupancy: number | null;
  blind: boolean;
  playedAt: string;
  selection: PvSelection;
  utc: number;
}

export type PvResultsSummary = Record<string, Partial<Record<PvTier, { attempts: number; wins: number; abandoned: number }>>>;

export async function fetchPvLevels(selection: PvSelection): Promise<PvLevelsResponse> {
  return (await apiClient.get<PvLevelsResponse>('/pv-play/levels', { params: { selection } })).data;
}

export async function fetchPvTierMap(level: number, tier: PvTier, selection: PvSelection): Promise<PvTierMapResponse> {
  return (await apiClient.get<PvTierMapResponse>(`/pv-play/levels/${level}/${tier}`, { params: { selection } })).data;
}

export async function postPvResult(result: PvManualPlayResult): Promise<void> {
  await apiClient.post('/pv-play/results', result);
}

/** selection 별 요약 (selection 필드 없는 옛 기록 = v2) */
export async function fetchPvResultsSummary(selection: PvSelection): Promise<PvResultsSummary> {
  return (await apiClient.get<{ summary: PvResultsSummary }>('/pv-play/results/summary', { params: { selection } })).data.summary;
}
