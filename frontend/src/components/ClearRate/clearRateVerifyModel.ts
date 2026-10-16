/**
 * 검증 탭 판정 기록·실행 상태·무효화 규칙 (문서 38 §10–§11) — 순수 함수만. 저장은 clearRateVerifyStore.ts.
 *
 * 측정 원자료(봇 판 결과)는 백엔드 측정 저장소에만 있고, 여기 기록은 참조(job_id·measurement_ref)와 요약만 든다.
 * 실행 상태(미측정/대기/측정 중/완료/실패/취소/결과 오래됨)와 판정(합격/불합격/근거 부족)은 서로 다른 값이다.
 *
 * 무효화 (assessRecord):
 *   맵(level_json 해시)·배치 위치·봇 버전/프로토콜이 바뀜     → measurement_invalid: 측정을 현재 결과로 쓰지 않음
 *   모델 버전·판정 기준 버전이 바뀜                          → evaluation_stale: 평가 결과 오래됨(측정은 유효할 수 있음)
 *   목표만 바뀜(값·곡선 해시)                               → needs_rejudge: 측정 재사용 + 재판정 필요
 *   목표 없음                                              → target_unset
 *   최신 맵 확인 전 · 현재 모델/기준 버전 조회 전·실패      → unconfirmed: 현재 유효로 보지 않음(회색, 집계 제외)
 * 현재(current)가 아닌 기록은 "과거 결과"로만 보이고 합격/불합격 색 배지를 쓰지 않는다.
 * 런타임 import 는 같은 폴더 순수 모듈만(.ts 확장자) — node 테스트가 그대로 불러 쓴다.
 */
import type { ConfirmJob, ConfirmJobStatus, MeasurementKind } from '../../api/clearRateVerify';
import type { BotVirtualResult, UserExpectedResult, UserExpectedVerdict } from '../../api/clearRateTarget';
import { A_VERDICT_LABEL, verdictReasonCodes } from './clearRateLabels.ts';
import { fnv1a, type TargetSource } from './targetCurve.ts';

export const RECORD_SCHEMA = 1;
export const MAX_CONCURRENT_C = 2;   // 백엔드 confirm.MAX_CONCURRENT 와 같음 (표시용)
export const C_NOTE = 'C 측정은 봇 측정 재현성 확인이며 실유저 클리어율 독립 검증이 아님';

export type RunState = 'not_measured' | 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'stale' | 'checking';
export type Validity = 'current' | 'measurement_invalid' | 'evaluation_stale' | 'needs_rejudge' | 'target_unset' | 'unconfirmed';

export const RUN_STATE_LABEL: Record<RunState, string> = {
  not_measured: '미측정', queued: '대기', running: '측정 중', done: '완료', failed: '실패', cancelled: '취소',
  stale: '결과 오래됨', checking: '맵 확인 중',
};
export const VALIDITY_LABEL: Record<Validity, string> = {
  current: '현재 유효', measurement_invalid: '측정 무효(맵·조건 변경)', evaluation_stale: '평가 오래됨(모델·기준 변경)',
  needs_rejudge: '재평가 필요(목표 변경)', target_unset: '목표 미설정',
  unconfirmed: '현재 상태 확인 불가(맵·버전 확인 전)',
};
export const KIND_LABEL: Record<MeasurementKind, string> = { exploration: '탐색', confirm: 'C 확인' };

/** level_json 의 안정 해시(키 정렬 JSON). 서버 cond_hash 와 별개 — 화면에서 맵 변경을 감지하는 용도 */
export function mapHash(levelJson: unknown): string {
  const canon = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(canon);
    if (v && typeof v === 'object') {
      return Object.keys(v as Record<string, unknown>).sort()
        .reduce((o, k) => { o[k] = canon((v as Record<string, unknown>)[k]); return o; }, {} as Record<string, unknown>);
    }
    return v;
  };
  return 'mh-' + fnv1a(JSON.stringify(canon(levelJson)));
}

/** 레벨당 C 작업 참조(로컬). 서버 작업 상태의 사본 + 요청 당시 맵 해시 */
export interface ConfirmJobRef {
  schema: number;
  key: string;                // `${batch_id}|${level_number}`
  batch_id: string;
  level_number: number;
  map_hash: string;
  job: ConfirmJob;
}

export interface EvaluationRecord {
  schema: number;
  key: string;                // `${batch_id}|${level_number}|${mode}|${measurement_kind}`
  batch_id: string;
  level_number: number;
  map_id: string;
  map_hash: string;
  cond_hash: string | null;
  mode: 'A' | 'B';
  target: number;
  target_source: TargetSource | 'batch_single' | null;
  target_curve_hash: string | null;
  target_curve_version: number | null;
  measurement_kind: MeasurementKind;
  measurement_source: string;          // cache | store | none
  seed_band: string | null;
  games_completed: number | null;
  job_id: string | null;
  measurement_ref: string | null;
  bot_version: string | null;
  bot_protocol: string | null;
  bot_config_hash: string | null;
  model_version: string | null;
  judge_version: string | null;
  // 요약 (A)
  expected: number | null;
  range80: [number, number] | null;
  confidence: string | null;
  proximity: number | null;            // p_in_band — "목표 근접 지표(참고)"
  verdict: UserExpectedVerdict | string | null;
  reason_codes: string[];
  raw_reason: string;
  measured_at: string | null;
  evaluated_at: string;
  /** 표시 재현용 응답 원본(모드 A user_expected / 모드 B bot_virtual). 봇 판 원자료는 없음 */
  user_expected?: UserExpectedResult | null;
  bot_virtual?: BotVirtualResult | null;
}

export const recordKey = (batchId: string, level: number, mode: 'A' | 'B', kind: MeasurementKind): string =>
  `${batchId}|${level}|${mode}|${kind}`;
export const jobRefKey = (batchId: string, level: number): string => `${batchId}|${level}`;

export interface TargetContext { target: number | null; source: TargetSource | 'batch_single' | null; curveHash: string | null; curveVersion: number | null }

export function recordFromUserExpected(args: {
  batchId: string; level: number; levelJson: unknown; kind: MeasurementKind; result: UserExpectedResult;
  target: TargetContext; judgeVersion: string | null; job?: ConfirmJob | null; provenance?: {
    measurement_ref?: string; games_completed?: number; bot_config_hash?: string; measured_at?: string | null;
    evaluated_at?: string; judge_version?: string; cond_hash?: string;
  } | null; now: string;
}): EvaluationRecord {
  const { result: r, provenance: pv } = args;
  const p = r.prediction;
  return {
    schema: RECORD_SCHEMA, key: recordKey(args.batchId, args.level, 'A', args.kind),
    batch_id: args.batchId, level_number: args.level, map_id: `${args.batchId}:${args.level}`,
    map_hash: mapHash(args.levelJson), cond_hash: pv?.cond_hash ?? p.cond_hash ?? null, mode: 'A',
    target: r.target, target_source: args.target.source, target_curve_hash: args.target.curveHash,
    target_curve_version: args.target.curveVersion, measurement_kind: args.kind,
    measurement_source: p.measurement?.source ?? 'none', seed_band: p.measurement?.seed_band ?? null,
    games_completed: pv?.games_completed ?? null, job_id: args.job?.job_id ?? null,
    measurement_ref: pv?.measurement_ref ?? null, bot_version: p.measurement?.bot_version ?? p.bot_version ?? null,
    bot_protocol: p.measurement?.protocol ?? p.bot_protocol ?? null, bot_config_hash: pv?.bot_config_hash ?? null,
    model_version: p.model_version ?? null, judge_version: pv?.judge_version ?? args.judgeVersion,
    expected: p.expected_ft_any ?? null, range80: p.range80_ft_any ?? null,
    confidence: p.confidence ?? null, proximity: r.verdict.p_in_band, verdict: r.verdict.verdict,
    reason_codes: verdictReasonCodes(r.verdict), raw_reason: r.verdict.reason,
    measured_at: pv?.measured_at ?? null, evaluated_at: pv?.evaluated_at ?? args.now, user_expected: r,
  };
}

export function recordFromBotVirtual(args: {
  batchId: string; level: number; levelJson: unknown; result: BotVirtualResult; now: string;
}): EvaluationRecord {
  const b = args.result;
  return {
    schema: RECORD_SCHEMA, key: recordKey(args.batchId, args.level, 'B', 'exploration'),
    batch_id: args.batchId, level_number: args.level, map_id: `${args.batchId}:${args.level}`,
    map_hash: mapHash(args.levelJson), cond_hash: b.cond_hash, mode: 'B', target: b.bot_virtual_target,
    target_source: 'batch_single', target_curve_hash: null, target_curve_version: null,
    measurement_kind: 'exploration', measurement_source: b.bot_virtual_games_c ? 'request' : 'none',
    seed_band: b.bot_virtual_c?.seed_band ?? null, games_completed: b.bot_virtual_games_c || null, job_id: null,
    measurement_ref: null, bot_version: null, bot_protocol: b.bot_virtual_c?.protocol ?? null,
    bot_config_hash: null, model_version: null, judge_version: b.bot_virtual_def_id, expected: null, range80: null,
    confidence: null, proximity: null, verdict: b.bot_virtual_verdict, reason_codes: [], raw_reason: b.reason,
    measured_at: null, evaluated_at: args.now, bot_virtual: b,
  };
}

export interface CurrentContext {
  mapHash: string | null;          // null = 최신 맵 확인 전(다시 읽는 중·기존 검증이 맵을 바꾸는 중) → unconfirmed
  level: number;
  target: number | null;
  curveHash: string | null;
  modelVersion: string | null;     // null = 현재 버전 모름(/verify/info 조회 전·실패) → 모드 A 는 unconfirmed(현재 유효 아님)
  judgeVersion: string | null;
  botVersion?: string | null;
  botProtocol?: string | null;
}

export function assessRecord(rec: EvaluationRecord, ctx: CurrentContext): { validity: Validity; reasons: string[] } {
  if (ctx.mapHash == null) return { validity: 'unconfirmed', reasons: ['최신 맵 확인 전'] };
  const inv: string[] = [];
  if (rec.map_hash !== ctx.mapHash) inv.push('맵 변경');
  if (rec.level_number !== ctx.level) inv.push('배치 위치 변경');
  if (ctx.botVersion && rec.bot_version && rec.bot_version !== ctx.botVersion) inv.push('봇 버전 변경');
  if (ctx.botProtocol && rec.bot_protocol && rec.bot_protocol !== ctx.botProtocol) inv.push('봇 프로토콜 변경');
  if (inv.length) return { validity: 'measurement_invalid', reasons: inv };
  if (rec.mode === 'A') {
    // 버전 확인 전·조회 실패에는 과거 합격을 현재 합격으로 보지 않는다 (수치·기준 변경 아님 — 확인 전 과신 차단)
    if (ctx.modelVersion == null || ctx.judgeVersion == null) {
      return { validity: 'unconfirmed', reasons: ['현재 모델·판정 기준 버전 확인 불가'] };
    }
    const st: string[] = [];
    if (rec.model_version !== ctx.modelVersion) st.push(`모델 ${rec.model_version ?? '?'} → ${ctx.modelVersion}`);
    if (rec.judge_version !== ctx.judgeVersion) st.push('판정 기준 변경');
    if (st.length) return { validity: 'evaluation_stale', reasons: st };
  }
  if (ctx.target == null) return { validity: 'target_unset', reasons: ['목표 미설정'] };
  const rj: string[] = [];
  if (Math.abs(rec.target - ctx.target) > 1e-9) rj.push(`목표 ${pctText(rec.target)} → ${pctText(ctx.target)}`);
  if (rec.mode === 'A' && rec.target_curve_hash !== ctx.curveHash) rj.push('목표 곡선 변경');
  if (rj.length) return { validity: 'needs_rejudge', reasons: rj };
  return { validity: 'current', reasons: [] };
}

const pctText = (t: number): string => `${Math.round(t * 1000) / 10}%`;

/** 판정 표시: 현재 유효할 때만 합격/불합격 색. 그 밖에는 "과거:"(확인 전이면 "확인 불가:") + 회색 (과거 합격 배지 금지) */
export function displayVerdict(rec: EvaluationRecord, validity: Validity): { label: string; cls: string; past: boolean } {
  const label = rec.mode === 'A' ? (A_VERDICT_LABEL[rec.verdict as UserExpectedVerdict] ?? String(rec.verdict)) : String(rec.verdict);
  if (validity !== 'current') return { label: `${validity === 'unconfirmed' ? '확인 불가' : '과거'}: ${label}`, cls: 'bg-gray-800 text-gray-400 border-gray-600', past: true };
  const cls = rec.verdict === 'PASS' ? 'bg-emerald-900/60 text-emerald-200 border-emerald-700'
    : rec.verdict === 'FAIL' ? 'bg-red-900/60 text-red-200 border-red-700' : 'bg-gray-700 text-gray-200 border-gray-500';
  return { label, cls, past: false };
}

/** C 실행 상태 — 판정과 별개. 완료 작업이라도 요청 당시 맵과 지금 맵이 다르면 "결과 오래됨".
 *  currentMapHash=null(최신 맵 확인 전)이면 완료 작업은 "맵 확인 중"(판정·재사용 대상 아님) */
export function runState(ref: ConfirmJobRef | null | undefined, currentMapHash: string | null, currentLevel: number): RunState {
  if (!ref) return 'not_measured';
  const s: ConfirmJobStatus = ref.job.status;
  if (s === 'done' && currentMapHash == null) return 'checking';
  if (s === 'done' && (ref.map_hash !== currentMapHash || ref.job.placement_level !== currentLevel)) return 'stale';
  return s;
}

/** 완료 C 로 인정되는 작업만 true — 실패·취소·중단·부분 결과는 false */
export const isCompletedC = (job: ConfirmJob | null | undefined): boolean =>
  !!job && job.status === 'done' && job.seed_band === 'CV' && job.measurement_kind === 'confirm'
  && !!job.measurement_ref && job.games_done === job.games_planned;

export const isActiveJob = (job: ConfirmJob | null | undefined): boolean =>
  !!job && (job.status === 'queued' || job.status === 'running');

/** 실행 전 확인 요약 (대상 맵 수·예상 판수·동시 실행 상한) */
export interface PlanLike { cond_hash?: string; games_planned?: number; blocking?: string[]; existing?: ConfirmJob | null; error?: string; protocol_problems?: string[] }
export function planSummary(items: PlanLike[]) {
  const runnable = items.filter(i => !i.error && !(i.blocking?.length) && !(i.protocol_problems?.length)
    && !isActiveJob(i.existing) && !isCompletedC(i.existing));
  return {
    maps: items.length,
    runnable: runnable.length,
    games: runnable.reduce((s, i) => s + (i.games_planned ?? 0), 0),
    blocked: items.filter(i => i.blocking?.length || i.protocol_problems?.length).length,
    errors: items.filter(i => i.error).length,
    reuseDone: items.filter(i => isCompletedC(i.existing)).length,
    active: items.filter(i => isActiveJob(i.existing)).length,
    maxConcurrent: MAX_CONCURRENT_C,
  };
}

/** 중복 클릭·요청 방지용 잠금 키 (같은 맵·조건 = 같은 키) */
export const confirmLockKey = (batchId: string, level: number, condHash: string): string => `${batchId}|${level}|${condHash}`;

// ── 이전 저장 데이터 안전 처리 ─────────────────────────────────────────────────────────────────────────────
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** 필수 필드(키·배치·레벨·맵 해시·모드·종류·목표)가 없으면 null(무시). 나머지는 안전한 기본값.
 *  measurement_kind 가 없거나 모르는 값이면 탐색으로 본다 — 과거 기록이 C 로 승격되는 일은 없다. */
export function normalizeRecord(raw: unknown): EvaluationRecord | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const level = num(r.level_number), target = num(r.target);
  if (!str(r.key) || !str(r.batch_id) || level == null || !str(r.map_hash) || target == null) return null;
  const mode = r.mode;
  if (mode !== 'A' && mode !== 'B') return null;
  const kind: MeasurementKind = r.measurement_kind === 'confirm' && r.seed_band === 'CV' && str(r.job_id) ? 'confirm' : 'exploration';
  return {
    schema: num(r.schema) ?? 0, key: r.key as string, batch_id: r.batch_id as string, level_number: level,
    map_id: str(r.map_id) ?? `${r.batch_id}:${level}`, map_hash: r.map_hash as string, cond_hash: str(r.cond_hash),
    mode, target, target_source: (str(r.target_source) as EvaluationRecord['target_source']) ?? null,
    target_curve_hash: str(r.target_curve_hash), target_curve_version: num(r.target_curve_version),
    measurement_kind: kind, measurement_source: str(r.measurement_source) ?? 'none', seed_band: str(r.seed_band),
    games_completed: num(r.games_completed), job_id: str(r.job_id), measurement_ref: str(r.measurement_ref),
    bot_version: str(r.bot_version), bot_protocol: str(r.bot_protocol), bot_config_hash: str(r.bot_config_hash),
    model_version: str(r.model_version), judge_version: str(r.judge_version), expected: num(r.expected),
    range80: Array.isArray(r.range80) && r.range80.length === 2 ? r.range80 as [number, number] : null,
    confidence: str(r.confidence), proximity: num(r.proximity), verdict: str(r.verdict),
    reason_codes: Array.isArray(r.reason_codes) ? r.reason_codes.filter((c): c is string => typeof c === 'string') : [],
    raw_reason: str(r.raw_reason) ?? '', measured_at: str(r.measured_at), evaluated_at: str(r.evaluated_at) ?? '',
    user_expected: (r.user_expected as UserExpectedResult) ?? null, bot_virtual: (r.bot_virtual as BotVirtualResult) ?? null,
  };
}

export function normalizeJobRef(raw: unknown): ConfirmJobRef | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  const job = r.job as ConfirmJob | undefined;
  const level = num(r.level_number);
  if (!str(r.key) || !str(r.batch_id) || level == null || !str(r.map_hash) || !job || !str(job.job_id)) return null;
  return { schema: num(r.schema) ?? 0, key: r.key as string, batch_id: r.batch_id as string, level_number: level,
           map_hash: r.map_hash as string, job };
}
