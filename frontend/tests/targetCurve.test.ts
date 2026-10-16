// A 목표 곡선 (문서 38 §11). 실행: node --experimental-strip-types --test frontend/tests/targetCurve.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  curveHash, curveToDraft, cyclePosition, draftToCurve, emptyCurve, normalizeCurve, previewCurve, resolveTarget,
  validateCurve, type TargetCurve,
} from '../src/components/ClearRate/targetCurve.ts';

const curve = (over: Partial<TargetCurve> = {}): TargetCurve => ({
  ...emptyCurve(), version: 1,
  segments: [
    { from: 32, to: 100, target: 0.95 },
    { from: 101, to: 300, target: 0.95, cycle: { period: 10, positions: [10], target: 0.8 } },
  ],
  overrides: { '237': 0.88 },
  ...over,
});

test('no curve / no segment → 목표 미설정 (no default)', () => {
  assert.deepEqual(resolveTarget(null, 50), { level: 50, target: null, source: null });
  assert.deepEqual(resolveTarget(emptyCurve(), 50), { level: 50, target: null, source: null });
  assert.equal(resolveTarget(curve(), 31).target, null);
  assert.equal(resolveTarget(curve(), 301).target, null);
});

test('boundaries are inclusive', () => {
  assert.equal(resolveTarget(curve(), 32).target, 0.95);
  assert.equal(resolveTarget(curve(), 100).target, 0.95);
  assert.equal(resolveTarget(curve(), 101).source, 'segment');
  assert.equal(resolveTarget(curve(), 300).source, 'cycle');   // 300 = 10의 배수
});

test('priority: override > cycle > segment', () => {
  assert.deepEqual(resolveTarget(curve(), 110), { level: 110, target: 0.8, source: 'cycle' });
  assert.deepEqual(resolveTarget(curve(), 111), { level: 111, target: 0.95, source: 'segment' });
  assert.deepEqual(resolveTarget(curve(), 237), { level: 237, target: 0.88, source: 'override' });
  assert.deepEqual(resolveTarget(curve({ overrides: { '240': 0.9 } }), 240), { level: 240, target: 0.9, source: 'override' });
});

test('cycle position follows the existing sawtooth index ((L-1) % period) + 1', () => {
  assert.equal(cyclePosition(10, 10), 10);
  assert.equal(cyclePosition(11, 10), 1);
  assert.equal(cyclePosition(1, 10), 1);
});

test('targets below 85% are kept as entered (never raised)', () => {
  const c = curve({ segments: [{ from: 101, to: 110, target: 0.7 }], overrides: {} });
  assert.equal(resolveTarget(c, 105).target, 0.7);
  assert.deepEqual(validateCurve(c).errors, []);
});

test('validation: range, order, overlap, cycle, override', () => {
  const bad = validateCurve({
    ...emptyCurve(),
    segments: [
      { from: 10, to: 5, target: 0.9 },
      { from: 1, to: 50, target: 1 },
      { from: 40, to: 60, target: 0.9, cycle: { period: 10, positions: [11, 11], target: 0 } },
    ],
    overrides: { x: 0.9, '7': 1.5 },
  });
  const kinds = bad.errors.map(e => e.kind);
  for (const k of ['order', 'range', 'overlap', 'cycle', 'override']) assert.ok(kinds.includes(k as never), k);
});

test('unset levels are reported, not errors', () => {
  const v = validateCurve(curve(), [31, 32, 301]);
  assert.deepEqual(v.errors, []);
  assert.deepEqual(v.unset, [31, 301]);
  assert.deepEqual(previewCurve(curve(), [31, 110]).map(r => r.source), [null, 'cycle']);
});

test('hash: order-independent, value-sensitive, version-independent', () => {
  const a = curve();
  const b = curve({ segments: [...curve().segments].reverse(), version: 9 });
  assert.equal(curveHash(a), curveHash(b));
  assert.notEqual(curveHash(a), curveHash(curve({ overrides: { '237': 0.89 } })));
  assert.equal(curveHash(null), null);
});

test('draft → curve: missing values and duplicate overrides are errors; empty rows ignored', () => {
  const { curve: c, errors } = draftToCurve(
    [{ from: '101', to: '300', target: '95', period: '10', positions: '10', cycleTarget: '80' },
     { from: '', to: '', target: '', period: '', positions: '', cycleTarget: '' },
     { from: '301', to: '', target: '90', period: '', positions: '', cycleTarget: '' },
     { from: '1', to: '5', target: '90', period: '10', positions: '', cycleTarget: '' }],
    [{ level: '237', target: '88' }, { level: '237', target: '87' }, { level: '', target: '' }], 2);
  assert.equal(c.segments.length, 2);
  assert.deepEqual(c.segments[0], { from: 101, to: 300, target: 0.95, cycle: { period: 10, positions: [10], target: 0.8 } });
  assert.equal(c.segments[1].cycle, null);
  assert.deepEqual(c.overrides, { '237': 0.88 });
  assert.equal(c.version, 2);
  assert.equal(errors.length, 3);   // 구간3 끝 누락, 구간4 주기 일부 누락, 개별 237 중복
});

test('draft round trip', () => {
  const d = curveToDraft(curve());
  const { curve: c, errors } = draftToCurve(d.segments, d.overrides, 1);
  assert.deepEqual(errors, []);
  assert.equal(curveHash(c), curveHash(curve()));
});

test('normalize: old / foreign data → null or safe copy, values unchanged', () => {
  assert.equal(normalizeCurve(undefined), null);
  assert.equal(normalizeCurve({ mode: 'bot_virtual', segments: [] }), null);    // B 데이터는 A 곡선이 아님
  assert.equal(normalizeCurve({ segments: [] }), null);
  const n = normalizeCurve({ mode: 'user_expected', segments: [{ from: 1, to: 2, target: 0.7 }] })!;
  assert.equal(n.version, 0);
  assert.deepEqual(n.overrides, {});
  assert.equal(n.segments[0].target, 0.7);
});
