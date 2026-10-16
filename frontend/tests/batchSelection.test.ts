// 생산 대시보드 배치 선택(동기화 후) — 순수 함수. 실행: node --experimental-strip-types --test frontend/tests/batchSelection.test.ts
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { latestBatchId, pickSelectedBatchId } from '../src/components/ProductionDashboard/batchSelection.ts';

const A = { id: 'a', created_at: '2026-10-16T20:00:00+09:00' };
const B = { id: 'b', created_at: '2026-10-16T21:00:00+09:00' };
const C = { id: 'c', created_at: '2026-10-15T09:00:00+09:00' };

test('latest by created_at regardless of list order; empty → null', () => {
  assert.equal(latestBatchId([C, B, A]), 'b');
  assert.equal(latestBatchId([A]), 'a');
  assert.equal(latestBatchId([]), null);
});

test('first pull on a fresh profile (no selection) → latest pulled batch', () => {
  assert.equal(pickSelectedBatchId(null, [A, B]), 'b');
});

test('current selection kept when still listed (late sync must not override the user)', () => {
  assert.equal(pickSelectedBatchId('a', [A, B, C]), 'a');
  assert.equal(pickSelectedBatchId('c', [A, B, C]), 'c');
});

test('current selection no longer listed → latest; nothing listed → null', () => {
  assert.equal(pickSelectedBatchId('gone', [A, C]), 'a');
  assert.equal(pickSelectedBatchId('gone', []), null);
  assert.equal(pickSelectedBatchId(null, []), null);
});
