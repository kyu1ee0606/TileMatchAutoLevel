/**
 * A 목표 곡선 — 레벨별 "실유저 예상 클리어율 목표" (문서 31 §3-3 규칙 7·D13, 문서 38 §11).
 *
 * 구조(기존 곡선 재사용): leveling_config 의 "레벨 구간(level_range) + 10레벨 주기 위치(SAWTOOTH_PATTERN_10,
 * (L-1)%10)" 모양을 그대로 쓰되 값은 A 목표(ft_any)다. 기존 봇 척도 값(meta.target_clear_rate, td →
 * TARGET_CLEAR_CURVE)은 읽지도 변환하지도 않는다.
 *
 *   구간 segment  {from, to, target}            from ≤ L ≤ to (양 끝 포함)
 *   주기 cycle    {period, positions, target}    구간 안에서 ((L-1) % period) + 1 ∈ positions 이면 이 값
 *                                                (예: period 10, positions [10] = 10의 배수 레벨)
 *   개별 override {L: target}                    가장 우선
 *   우선순위: override > cycle > segment > (없음 = "목표 미설정", 기본값 없음)
 *
 * 구간끼리 겹치면 오류(중복). 목표 범위는 0 < t < 1 (백엔드 target 과 같음). 85% 미만 목표도 입력은 허용하고
 * 값을 바꾸지 않는다 — 판정 가능 여부는 별도(target-check)로 표시한다.
 * 런타임 import 는 같은 폴더 순수 모듈만(.ts 확장자) — frontend/tests 의 node 테스트가 그대로 불러 쓴다.
 */
import { parseTargetPercent } from './clearRateLabels.ts';

export const TARGET_CURVE_SCHEMA = 1;

export interface CurveCycle { period: number; positions: number[]; target: number }
export interface CurveSegment { from: number; to: number; target: number; cycle?: CurveCycle | null }

export interface TargetCurve {
  schema: number;
  /** A 전용. B(봇 가상 목표)는 별도 데이터로 저장한다 */
  mode: 'user_expected';
  segments: CurveSegment[];
  overrides: Record<string, number>;
  /** 적용할 때마다 +1 (해시와 함께 판정 기록에 남김) */
  version: number;
}

export type TargetSource = 'override' | 'cycle' | 'segment';
export interface ResolvedTarget { level: number; target: number | null; source: TargetSource | null }

export const emptyCurve = (): TargetCurve =>
  ({ schema: TARGET_CURVE_SCHEMA, mode: 'user_expected', segments: [], overrides: {}, version: 0 });

const validTarget = (t: unknown): t is number => typeof t === 'number' && Number.isFinite(t) && t > 0 && t < 1;
const posInt = (n: unknown): n is number => typeof n === 'number' && Number.isInteger(n) && n >= 1;

export function cyclePosition(level: number, period: number): number {
  return ((level - 1) % period) + 1;
}

export function resolveTarget(curve: TargetCurve | null | undefined, level: number): ResolvedTarget {
  if (!curve) return { level, target: null, source: null };
  const o = curve.overrides[String(level)];
  if (o != null) return { level, target: o, source: 'override' };
  const seg = curve.segments.find(s => s.from <= level && level <= s.to);
  if (!seg) return { level, target: null, source: null };
  if (seg.cycle && seg.cycle.positions.includes(cyclePosition(level, seg.cycle.period))) {
    return { level, target: seg.cycle.target, source: 'cycle' };
  }
  return { level, target: seg.target, source: 'segment' };
}

export const previewCurve = (curve: TargetCurve | null, levels: number[]): ResolvedTarget[] =>
  levels.map(l => resolveTarget(curve, l));

export interface CurveIssue { kind: 'range' | 'order' | 'overlap' | 'cycle' | 'override'; message: string }

/** 오류(적용 불가)와 목표 미설정 레벨(적용 가능, 표시만)을 따로 돌려준다 */
export function validateCurve(curve: TargetCurve, levels: number[] = []): { errors: CurveIssue[]; unset: number[] } {
  const errors: CurveIssue[] = [];
  curve.segments.forEach((s, i) => {
    const tag = `구간 ${i + 1}`;
    if (!posInt(s.from) || !posInt(s.to)) errors.push({ kind: 'order', message: `${tag}: 시작·끝은 1 이상 정수` });
    else if (s.from > s.to) errors.push({ kind: 'order', message: `${tag}: 시작 ${s.from} > 끝 ${s.to}` });
    if (!validTarget(s.target)) errors.push({ kind: 'range', message: `${tag}: 목표는 0% 초과 100% 미만` });
    if (s.cycle) {
      const c = s.cycle;
      if (!posInt(c.period) || c.period < 2) errors.push({ kind: 'cycle', message: `${tag}: 주기는 2 이상 정수` });
      else if (c.positions.length === 0 || c.positions.some(p => !posInt(p) || p > c.period)) {
        errors.push({ kind: 'cycle', message: `${tag}: 주기 위치는 1~${c.period}` });
      } else if (new Set(c.positions).size !== c.positions.length) {
        errors.push({ kind: 'cycle', message: `${tag}: 주기 위치 중복` });
      }
      if (!validTarget(c.target)) errors.push({ kind: 'range', message: `${tag}: 주기 목표는 0% 초과 100% 미만` });
    }
  });
  const sorted = curve.segments.map((s, i) => ({ ...s, i })).filter(s => posInt(s.from) && posInt(s.to))
    .sort((a, b) => a.from - b.from);
  for (let k = 1; k < sorted.length; k++) {
    const a = sorted[k - 1], b = sorted[k];
    if (b.from <= a.to) {
      errors.push({ kind: 'overlap', message: `구간 ${a.i + 1}(${a.from}-${a.to})과 구간 ${b.i + 1}(${b.from}-${b.to}) 중복` });
    }
  }
  for (const [k, v] of Object.entries(curve.overrides)) {
    if (!/^\d+$/.test(k) || Number(k) < 1) errors.push({ kind: 'override', message: `개별 레벨 "${k}": 1 이상 정수` });
    if (!validTarget(v)) errors.push({ kind: 'override', message: `개별 레벨 ${k}: 목표는 0% 초과 100% 미만` });
  }
  const unset = levels.filter(l => resolveTarget(curve, l).target == null);
  return { errors, unset };
}

/** 저장 형식에 무관한 정규 JSON → FNV-1a 32비트. version 은 해시에서 뺀다(같은 값이면 같은 해시) */
export function curveHash(curve: TargetCurve | null | undefined): string | null {
  if (!curve) return null;
  const canon = {
    mode: curve.mode,
    segments: [...curve.segments].sort((a, b) => a.from - b.from || a.to - b.to).map(s => ({
      from: s.from, to: s.to, target: s.target,
      cycle: s.cycle ? { period: s.cycle.period, positions: [...s.cycle.positions].sort((x, y) => x - y), target: s.cycle.target } : null,
    })),
    overrides: Object.keys(curve.overrides).sort((a, b) => Number(a) - Number(b)).map(k => [Number(k), curve.overrides[k]]),
  };
  return 'tc-' + fnv1a(JSON.stringify(canon));
}

export function fnv1a(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

// ── 화면 입력(문자열) → 곡선 ──────────────────────────────────────────────────────────────────────────────
export interface SegmentDraft { from: string; to: string; target: string; period: string; positions: string; cycleTarget: string }
export interface OverrideDraft { level: string; target: string }

export const emptySegmentDraft = (): SegmentDraft =>
  ({ from: '', to: '', target: '', period: '', positions: '', cycleTarget: '' });

const intOrNaN = (s: string): number => (/^\s*\d+\s*$/.test(s) ? Number(s.trim()) : NaN);

/** 누락·형식 오류는 errors 로, 값 범위·중복은 validateCurve 가 본다. 빈 행은 무시. 주기는 3칸 모두 비면 없음 */
export function draftToCurve(segments: SegmentDraft[], overrides: OverrideDraft[], version: number):
  { curve: TargetCurve; errors: string[] } {
  const errors: string[] = [];
  const segs: CurveSegment[] = [];
  segments.forEach((d, i) => {
    const vals = [d.from, d.to, d.target, d.period, d.positions, d.cycleTarget];
    if (vals.every(v => v.trim() === '')) return;
    const tag = `구간 ${i + 1}`;
    const from = intOrNaN(d.from), to = intOrNaN(d.to);
    const target = parseTargetPercent(d.target);
    if (Number.isNaN(from) || Number.isNaN(to)) errors.push(`${tag}: 시작·끝 레벨 누락/형식 오류`);
    if (target == null) errors.push(`${tag}: 목표(%) 누락/형식 오류`);
    let cycle: CurveCycle | null = null;
    const cyc = [d.period, d.positions, d.cycleTarget];
    if (cyc.some(v => v.trim() !== '')) {
      const period = intOrNaN(d.period);
      const positions = d.positions.split(/[,\s]+/).filter(Boolean).map(intOrNaN);
      const ct = parseTargetPercent(d.cycleTarget);
      if (Number.isNaN(period) || positions.length === 0 || positions.some(Number.isNaN) || ct == null) {
        errors.push(`${tag}: 주기(주기·위치·목표) 일부 누락/형식 오류`);
      } else {
        cycle = { period, positions, target: ct };
      }
    }
    if (!Number.isNaN(from) && !Number.isNaN(to) && target != null) segs.push({ from, to, target, cycle });
  });
  const ov: Record<string, number> = {};
  overrides.forEach((d, i) => {
    if (d.level.trim() === '' && d.target.trim() === '') return;
    const l = intOrNaN(d.level);
    const t = parseTargetPercent(d.target);
    if (Number.isNaN(l) || l < 1 || t == null) { errors.push(`개별 ${i + 1}: 레벨·목표(%) 누락/형식 오류`); return; }
    if (ov[String(l)] != null) { errors.push(`개별 레벨 ${l} 중복`); return; }
    ov[String(l)] = t;
  });
  return { curve: { schema: TARGET_CURVE_SCHEMA, mode: 'user_expected', segments: segs, overrides: ov, version }, errors };
}

const pct = (t: number): string => String(Math.round(t * 1000) / 10);

export function curveToDraft(curve: TargetCurve | null): { segments: SegmentDraft[]; overrides: OverrideDraft[] } {
  if (!curve) return { segments: [emptySegmentDraft()], overrides: [] };
  return {
    segments: curve.segments.length ? curve.segments.map(s => ({
      from: String(s.from), to: String(s.to), target: pct(s.target),
      period: s.cycle ? String(s.cycle.period) : '', positions: s.cycle ? s.cycle.positions.join(',') : '',
      cycleTarget: s.cycle ? pct(s.cycle.target) : '',
    })) : [emptySegmentDraft()],
    overrides: Object.entries(curve.overrides).map(([level, t]) => ({ level, target: pct(t) })),
  };
}

/** 이전 저장 데이터 → 안전한 곡선(형식이 다르면 null = 목표 미설정). 값은 고치지 않는다 */
export function normalizeCurve(raw: unknown): TargetCurve | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Partial<TargetCurve>;
  if (r.mode !== 'user_expected' || !Array.isArray(r.segments)) return null;
  return {
    schema: TARGET_CURVE_SCHEMA, mode: 'user_expected',
    segments: r.segments.filter(s => s && typeof s === 'object').map(s => ({
      from: s.from, to: s.to, target: s.target,
      cycle: s.cycle && Array.isArray(s.cycle.positions) ? { period: s.cycle.period, positions: [...s.cycle.positions], target: s.cycle.target } : null,
    })),
    overrides: r.overrides && typeof r.overrides === 'object' ? { ...r.overrides } : {},
    version: typeof r.version === 'number' ? r.version : 0,
  };
}
