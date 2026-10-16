// 검증 탭 판정 기록·실행 상태·무효화 (문서 38 §10). 실행: node --experimental-strip-types --test frontend/tests/clearRateVerifyModel.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  assessRecord, confirmLockKey, displayVerdict, isCompletedC, mapHash, normalizeJobRef, normalizeRecord, planSummary,
  recordFromUserExpected, runState, type ConfirmJobRef, type CurrentContext,
} from '../src/components/ClearRate/clearRateVerifyModel.ts';

const LJ = { layer: 2, layer_0: { col: '7', row: '7', tiles: { '1_1': ['t0', ''] } }, randSeed: 3 };
const MODEL = 'cr-ftany-v24r-20261016';

const job = (over: Record<string, unknown> = {}) => ({
  schema: 1, job_id: 'j1', job_key: 'k', measurement_kind: 'confirm', target_mode: 'user_expected', status: 'done',
  map_id: 'b:237', batch_id: 'b', placement_level: 237, cond_hash: 'h', bot_config_hash: 'c', protocol: 'theta4x128_v1',
  seed_band: 'CV', seed_base: 22000000, bot_version: 'v2.4', model_version_at_submit: MODEL, games_planned: 512,
  games_done: 512, cancel_requested: false, created_at: '', started_at: '', finished_at: '', error: null,
  measurement_ref: 'h|theta4x128_v1|CV|c', ...over,
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any;

const result = (verdict: string, seed = 'CV', source = 'store') => ({
  target_mode: 'user_expected', target_metric: 'ft_any_v1', target: 0.9, criteria: 'x',
  verdict: { verdict, reason: 'r', target: 0.9, band: [0.8, 0.95], p_in_band: 0.62, in_range80_reference: true,
             bot_seed_confirmed: seed === 'CV', confidence: 'high', support_reasons: [], target_flags: [] },
  prediction: { model_version: MODEL, bot_version: 'v2.4', bot_protocol: 'theta4x128_v1', cond_hash: 'h',
                expected_ft_any: 0.91, range80_ft_any: [0.85, 1], confidence: 'high',
                measurement: { source, bot_version: 'v2.4', protocol: 'theta4x128_v1', seed_band: seed, cond_hash: 'h' } },
// eslint-disable-next-line @typescript-eslint/no-explicit-any
}) as any;

const confirmRec = (verdict = 'PASS') => recordFromUserExpected({
  batchId: 'b', level: 237, levelJson: LJ, kind: 'confirm', result: result(verdict),
  target: { target: 0.9, source: 'segment', curveHash: 'tc-1', curveVersion: 1 }, judgeVersion: 'judge-a', job: job(),
  provenance: { measurement_ref: 'h|theta4x128_v1|CV|c', games_completed: 512, bot_config_hash: 'c', judge_version: 'judge-a',
                measured_at: 't0', evaluated_at: 't1', cond_hash: 'h' }, now: 'now',
});

const ctx = (over: Partial<CurrentContext> = {}): CurrentContext => ({
  mapHash: mapHash(LJ), level: 237, target: 0.9, curveHash: 'tc-1', modelVersion: MODEL, judgeVersion: 'judge-a',
  botVersion: 'v2.4', botProtocol: 'theta4x128_v1', ...over,
});

test('map hash is key-order independent and change-sensitive', () => {
  assert.equal(mapHash({ b: 1, a: { y: 2, x: 1 } }), mapHash({ a: { x: 1, y: 2 }, b: 1 }));
  assert.notEqual(mapHash(LJ), mapHash({ ...LJ, randSeed: 4 }));
});

test('record keeps provenance and separates kinds', () => {
  const r = confirmRec();
  assert.equal(r.key, 'b|237|A|confirm');
  assert.equal(r.measurement_kind, 'confirm');
  assert.equal(r.seed_band, 'CV');
  assert.equal(r.games_completed, 512);
  assert.equal(r.job_id, 'j1');
  assert.equal(r.target_curve_hash, 'tc-1');
  assert.equal(r.model_version, MODEL);
  assert.equal(r.judge_version, 'judge-a');
  assert.equal(r.proximity, 0.62);
  const ex = recordFromUserExpected({ batchId: 'b', level: 237, levelJson: LJ, kind: 'exploration',
    result: result('INSUFFICIENT_EVIDENCE', 'seed11M', 'cache'), target: { target: 0.9, source: 'segment', curveHash: 'tc-1', curveVersion: 1 },
    judgeVersion: 'judge-a', now: 'now' });
  assert.equal(ex.key, 'b|237|A|exploration');
  assert.equal(ex.measurement_kind, 'exploration');
  assert.equal(ex.measurement_source, 'cache');
});

test('current only when map, conditions, versions and target all match', () => {
  assert.equal(assessRecord(confirmRec(), ctx()).validity, 'current');
});

test('map / placement / bot protocol change → measurement invalid', () => {
  assert.equal(assessRecord(confirmRec(), ctx({ mapHash: mapHash({ ...LJ, randSeed: 9 }) })).validity, 'measurement_invalid');
  assert.equal(assessRecord(confirmRec(), ctx({ level: 238 })).validity, 'measurement_invalid');
  assert.equal(assessRecord(confirmRec(), ctx({ botProtocol: 'theta085x512_v1' })).validity, 'measurement_invalid');
  assert.equal(assessRecord(confirmRec(), ctx({ botVersion: 'v2.5' })).validity, 'measurement_invalid');
});

test('model or judgment criteria change → evaluation stale (unknown versions are not compared)', () => {
  assert.equal(assessRecord(confirmRec(), ctx({ modelVersion: 'cr-next' })).validity, 'evaluation_stale');
  assert.equal(assessRecord(confirmRec(), ctx({ judgeVersion: 'judge-b' })).validity, 'evaluation_stale');
  assert.equal(assessRecord(confirmRec(), ctx({ modelVersion: null, judgeVersion: null })).validity, 'current');
});

test('target-only change → needs rejudge (measurement kept); no target → target_unset', () => {
  const a = assessRecord(confirmRec(), ctx({ target: 0.92 }));
  assert.equal(a.validity, 'needs_rejudge');
  assert.ok(a.reasons[0].includes('90%') && a.reasons[0].includes('92%'));
  assert.equal(assessRecord(confirmRec(), ctx({ curveHash: 'tc-2' })).validity, 'needs_rejudge');
  assert.equal(assessRecord(confirmRec(), ctx({ target: null })).validity, 'target_unset');
});

test('no PASS badge under new conditions', () => {
  const r = confirmRec('PASS');
  assert.ok(displayVerdict(r, 'current').cls.includes('emerald'));
  for (const v of ['measurement_invalid', 'evaluation_stale', 'needs_rejudge', 'target_unset'] as const) {
    const d = displayVerdict(r, v);
    assert.ok(!d.cls.includes('emerald') && d.past && d.label.startsWith('과거:'), v);
  }
});

test('run state is separate from verdict; done job on a changed map is stale', () => {
  const ref: ConfirmJobRef = { schema: 1, key: 'b|237', batch_id: 'b', level_number: 237, map_hash: mapHash(LJ), job: job() };
  assert.equal(runState(null, mapHash(LJ), 237), 'not_measured');
  assert.equal(runState(ref, mapHash(LJ), 237), 'done');
  assert.equal(runState(ref, mapHash({ ...LJ, randSeed: 9 }), 237), 'stale');
  for (const s of ['queued', 'running', 'failed', 'cancelled']) {
    assert.equal(runState({ ...ref, job: job({ status: s }) }, mapHash(LJ), 237), s);
  }
});

test('only a full CV confirm job counts as completed C', () => {
  assert.equal(isCompletedC(job()), true);
  assert.equal(isCompletedC(job({ status: 'failed', games_done: 256 })), false);    // partial
  assert.equal(isCompletedC(job({ status: 'cancelled' })), false);
  assert.equal(isCompletedC(job({ seed_band: 'seed11M' })), false);                // training cache
  assert.equal(isCompletedC(job({ seed_band: 'C' })), false);                      // pilot confirmation band
  assert.equal(isCompletedC(job({ games_done: 384 })), false);
  assert.equal(isCompletedC(job({ measurement_ref: null })), false);
});

test('plan summary: maps, games, concurrency; done/active/blocked are not re-measured', () => {
  const s = planSummary([
    { cond_hash: 'a', games_planned: 512 },
    { cond_hash: 'b', games_planned: 512, existing: job() },
    { cond_hash: 'c', games_planned: 512, existing: job({ status: 'running' }) },
    { cond_hash: 'd', games_planned: 512, blocking: ['LEVEL_OUT_OF_RANGE'] },
    { error: 'bad' },
    { cond_hash: 'e', games_planned: 512, existing: job({ status: 'failed' }) },
  ]);
  assert.deepEqual(s, { maps: 6, runnable: 2, games: 1024, blocked: 1, errors: 1, reuseDone: 1, active: 1, maxConcurrent: 2 });
});

test('lock key depends on batch, level and condition hash', () => {
  assert.equal(confirmLockKey('b', 237, 'h'), 'b|237|h');
  assert.notEqual(confirmLockKey('b', 237, 'h'), confirmLockKey('b', 237, 'h2'));
});

test('old saved data: missing fields are safe, never promoted to C', () => {
  assert.equal(normalizeRecord(null), null);
  assert.equal(normalizeRecord({ key: 'k', batch_id: 'b', level_number: 1, map_hash: 'm' }), null);   // no target / mode
  const legacy = normalizeRecord({ key: 'k', batch_id: 'b', level_number: 1, map_hash: 'm', mode: 'A', target: 0.9,
                                   measurement_kind: 'confirm', seed_band: 'seed11M', verdict: 'PASS' })!;
  assert.equal(legacy.measurement_kind, 'exploration');
  assert.deepEqual(legacy.reason_codes, []);
  assert.equal(legacy.model_version, null);
  assert.equal(assessRecord(legacy, { ...ctx(), mapHash: 'm', level: 1 }).validity, 'evaluation_stale');   // model unknown ≠ current
  const roundTrip = normalizeRecord(JSON.parse(JSON.stringify(confirmRec())))!;
  assert.equal(roundTrip.measurement_kind, 'confirm');
  assert.equal(normalizeJobRef({ key: 'k', batch_id: 'b', level_number: 1, map_hash: 'm' }), null);
});
