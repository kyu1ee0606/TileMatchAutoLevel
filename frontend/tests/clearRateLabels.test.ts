// 검증 탭 실유저 클리어율 표시 라벨 (문서 38 §4). 실행: node --experimental-strip-types --test frontend/tests/clearRateLabels.test.ts
// (tsconfig include 는 src 만 — 이 파일은 tsc 대상 아님. 의존성 추가 없이 node 내장 test 러너 사용)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  A_VERDICT_LABEL, FLAG_LABEL, TARGET_PROXIMITY_LABEL, TARGET_PROXIMITY_TOOLTIP,
  formatProximity, parseTargetPercent, provenanceView, verdictReasonCodes, verdictView,
} from '../src/components/ClearRate/clearRateLabels.ts';

const base = {
  verdict: 'INSUFFICIENT_EVIDENCE' as const, reason: 'r', target: 0.9, band: [0.8, 0.95] as [number, number],
  p_in_band: null as number | null, in_range80_reference: null, bot_seed_confirmed: false, confidence: 'high' as string | null,
};

const result = (verdict: Record<string, unknown>, measurement: Record<string, unknown> | null = null) => ({
  target_mode: 'user_expected' as const, target_metric: 'ft_any_v1', target: 0.9, criteria: 'x',
  verdict: { ...base, ...verdict },
  prediction: { model_version: 'cr-ftany-v24r-20261016', bot_version: 'v2.4', bot_protocol: 'theta4x128_v1', measurement },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any;

test('display label only — never "확률"', () => {
  assert.equal(TARGET_PROXIMITY_LABEL, '목표 근접 지표(참고)');
  assert.ok(!TARGET_PROXIMITY_LABEL.includes('확률'));
  assert.ok(TARGET_PROXIMITY_TOOLTIP.includes('검증된 확률이 아님') && TARGET_PROXIMITY_TOOLTIP.includes('문서 36'));
});

test('proximity is shown as a 0~1 score, not a percent', () => {
  assert.equal(formatProximity(0.925), '0.93');
  assert.equal(formatProximity(null), '—');
  assert.ok(!formatProximity(0.5).includes('%'));
});

test('target input: no default, percent 0<v<100 only', () => {
  assert.equal(parseTargetPercent(''), null);
  assert.equal(parseTargetPercent('  '), null);
  assert.equal(parseTargetPercent('0'), null);
  assert.equal(parseTargetPercent('100'), null);
  assert.equal(parseTargetPercent('-5'), null);
  assert.equal(parseTargetPercent('abc'), null);
  assert.equal(parseTargetPercent('90'), 0.9);
  assert.equal(parseTargetPercent('85.5'), 0.855);
});

test('verdict labels', () => {
  assert.deepEqual(A_VERDICT_LABEL, { PASS: '합격', FAIL: '불합격', INSUFFICIENT_EVIDENCE: '근거 부족' });
});

test('insufficient reasons: support → hard target flags, soft flags ignored, dedup', () => {
  const codes = verdictReasonCodes({
    ...base, support_reasons: ['MEASUREMENT_MISSING'],
    target_flags: [
      { code: 'NEAR_CEILING', severity: 'soft', detail: '' },
      { code: 'SELECTION_UNCONFIRMED', severity: 'hard', detail: '' },
      { code: 'SELECTION_UNCONFIRMED', severity: 'hard', detail: '' },
    ],
  });
  assert.deepEqual(codes, ['MEASUREMENT_MISSING', 'SELECTION_UNCONFIRMED']);
  assert.equal(FLAG_LABEL.SELECTION_UNCONFIRMED, '확인 측정(C 시드) 없음');
});

test('low confidence without a code still gets a readable reason', () => {
  assert.deepEqual(verdictReasonCodes({ ...base, confidence: 'low' }), ['LOW_CONFIDENCE']);
  assert.deepEqual(verdictReasonCodes({ ...base, target_flags: [{ code: 'LOW_CONFIDENCE', severity: 'soft', detail: '' }] }),
    ['LOW_CONFIDENCE']);
});

test('PASS / FAIL carry no reasons; unknown code falls back to the code', () => {
  assert.deepEqual(verdictReasonCodes({ ...base, verdict: 'PASS', support_reasons: ['X'] }), []);
  const v = verdictView(result({ support_reasons: ['NEW_CODE'] }));
  assert.equal(v.label, '근거 부족');
  assert.deepEqual(v.reasons, ['NEW_CODE']);
  assert.ok(!v.cls.includes('emerald'));
});

test('provenance: cache measurement is never a C confirmation', () => {
  const p = provenanceView(result({}, { source: 'cache', bot_version: 'v2.4', protocol: 'theta4x128_v1', seed_band: 'seed11M' }));
  assert.equal(p.model, 'cr-ftany-v24r-20261016');
  assert.equal(p.source, 'cache');
  assert.equal(p.seedBand, 'seed11M');
  assert.equal(p.confirmed, false);
  const none = provenanceView(result({}));
  assert.equal(none.source, '측정 없음');
  assert.equal(none.bot, 'v2.4');
});

test('backend reason text shows the new proximity name (display only)', () => {
  const v = verdictView(result({ verdict: 'FAIL', p_in_band: 0.31, reason: '목표 범위 안 확률 0.31 < 0.5 (제안 임계)' }));
  assert.equal(v.rawReason, '목표 근접 지표 0.31 < 0.5 (제안 임계)');
  assert.equal(v.proximity, '0.31');
  assert.equal(v.label, '불합격');
});
