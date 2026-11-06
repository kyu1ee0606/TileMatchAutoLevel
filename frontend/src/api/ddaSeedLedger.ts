/**
 * DDA 시드 이력 장부 API (backend/app/api/routes/dda_seed_ledger.py, app/core/dda_seed_ledger.py).
 * 업로드 1회 = 스냅샷 1개(백엔드 파일 backend/data/dda_seed_ledger/, 추가만). 수정·삭제 API 없음.
 */
import apiClient from './client';
import type { LevelJSON } from '../types';

export const LEDGER_SEED_FIELDS = ['ddaEasy2Seeds', 'ddaEasySeeds', 'ddaHardSeeds', 'ddaHard2Seeds'] as const;
export type LedgerSeedField = typeof LEDGER_SEED_FIELDS[number];
export const LEDGER_FIELD_STEP: Record<LedgerSeedField, string> = {
  ddaEasy2Seeds: '−2', ddaEasySeeds: '−1', ddaHardSeeds: '+1', ddaHard2Seeds: '+2',
};

export type LedgerClass =
  | 'same' | 'reordered' | 'replaced' | 'added' | 'removed' | 'resized' | 'filled' | 'cleared' | 'unknown';

export interface LedgerSnapshotSummary {
  id: string;
  kind: 'upload' | 'baseline' | 'dryrun';
  status: 'open' | 'finalized' | 'virtual';
  createdAt?: string;
  finalizedAt?: string;
  board?: string;
  memo?: string;
  tag?: string;
  batchId?: string;
  batchName?: string;
  source?: string;
  auto?: boolean;
  counts?: Record<string, number>;
  rowsSha256?: string;
}

export interface LockModel {
  stores: 'value' | 'index';
  summary: string;
  notes: string[];
}

export interface LedgerFieldDiff {
  class: LedgerClass;
  from: string | null;
  to: string | null;
  bothUnknown?: boolean;
  positions?: { pos: number; from: string | null; to: string | null }[];
  addedTokens?: string[];
  removedTokens?: string[];
  orderChanged?: boolean;
  gameChanged?: boolean;
  gameSetChanged?: boolean;
}

export interface LedgerDiffItem {
  id: string;
  changed: boolean;
  rowAdded: boolean;
  rowRemoved: boolean;
  statusA: string | null;
  statusB: string | null;
  mapShaA: string | null;
  mapShaB: string | null;
  mapChanged: boolean;
  useTileCountA: unknown;
  useTileCountB: unknown;
  useTileCountChanged: boolean;
  fields: Record<LedgerSeedField, LedgerFieldDiff>;
  lockNotes: string[];
}

export interface LedgerDiffSummary {
  rows: number;
  changedRows: number;
  rowAdded: number;
  rowRemoved: number;
  mapChanged: number;
  useTileCountChanged: number;
  gameChanged: number;
  byField: Record<LedgerSeedField, Record<LedgerClass, number>>;
}

export interface LedgerDiffResponse {
  a: LedgerSnapshotSummary;
  b: LedgerSnapshotSummary;
  summary: LedgerDiffSummary;
  items: LedgerDiffItem[];
  truncated?: boolean;
  lockModel: LockModel;
  saved?: LedgerSnapshotSummary | null;
}

export interface LedgerTimelineEntry {
  snapshot: LedgerSnapshotSummary;
  status: string;
  seeds: Record<LedgerSeedField, string | null>;
  sent?: Record<string, string>;
  omitted?: Record<string, string>;
  mapSha256: string | null;
  useTileCount: unknown;
  relabel?: { rule: string; slot: number; mapping: Record<string, string> } | null;
  message?: string;
  changeFromPrev?: Record<LedgerSeedField, LedgerFieldDiff>;
  mapChangedFromPrev?: boolean;
}

const LONG = { timeout: 300000 };

export async function listLedgerSnapshots(includeDryrun = true): Promise<{ snapshots: LedgerSnapshotSummary[]; dir: string; lockModel: LockModel }> {
  const r = await apiClient.get('/dda-ledger/snapshots', { params: { include_dryrun: includeDryrun } });
  return r.data;
}

export async function openLedgerSession(req: {
  board: string; memo?: string; tag?: string; batch_id?: string; batch_name?: string; source?: string;
  options?: Record<string, unknown>;
}): Promise<LedgerSnapshotSummary> {
  const r = await apiClient.post('/dda-ledger/sessions', req);
  return r.data;
}

export async function addLedgerNote(sessionId: string, note: Record<string, unknown>): Promise<void> {
  await apiClient.post(`/dda-ledger/sessions/${sessionId}/notes`, { note });
}

export async function finalizeLedgerSession(sessionId: string, clientCounts: Record<string, unknown>, readback = true)
  : Promise<LedgerSnapshotSummary & { readbackResult?: { ok: boolean; method?: string; error?: string } }> {
  const r = await apiClient.post(`/dda-ledger/sessions/${sessionId}/finalize`,
    { client_counts: clientCounts, readback }, LONG);
  return r.data;
}

export async function diffLedger(a: string, b: string, opts: { q?: string; onlyChanged?: boolean; klass?: string; limit?: number } = {})
  : Promise<LedgerDiffResponse> {
  const r = await apiClient.get('/dda-ledger/diff', {
    params: { a, b, q: opts.q ?? '', only_changed: opts.onlyChanged ?? true, klass: opts.klass ?? '', limit: opts.limit ?? 0 },
    ...LONG,
  });
  return r.data;
}

export async function fetchLedgerDiffCsv(a: string, b: string, q = '', klass = ''): Promise<string> {
  const r = await apiClient.get('/dda-ledger/diff', {
    params: { a, b, q, klass, only_changed: true, format: 'csv' }, responseType: 'text', ...LONG,
  });
  return r.data as string;
}

export async function diffLedgerBatch(req: {
  base?: string; batch_id?: string; batch_name?: string;
  levels: { level_number: number; level_json: LevelJSON }[];
  infinity_mode: 'off' | 'append' | 'only'; infinity_relabel: boolean;
  infinity_source_start?: number; infinity_source_end?: number;
  persist?: boolean; memo?: string; q?: string; only_changed?: boolean; klass?: string;
}, format: 'json' | 'csv' = 'json', limit = 0): Promise<LedgerDiffResponse | string> {
  const r = await apiClient.post('/dda-ledger/diff-batch', req, {
    params: { format, limit }, ...LONG, responseType: format === 'csv' ? 'text' : 'json',
  });
  return r.data;
}

export async function getLedgerTimeline(rowId: string, includeDryrun = false)
  : Promise<{ id: string; entries: LedgerTimelineEntry[]; lockModel: LockModel }> {
  const r = await apiClient.get(`/dda-ledger/levels/${encodeURIComponent(rowId)}/timeline`, {
    params: { include_dryrun: includeDryrun }, ...LONG,
  });
  return r.data;
}

export async function createLedgerBaselineFromFile(path: string, tag = 'v0', memo = ''): Promise<LedgerSnapshotSummary> {
  const r = await apiClient.post('/dda-ledger/baseline/from-file', { path, tag, memo }, LONG);
  return r.data;
}

export async function createLedgerBaselineFromServer(tag = '', memo = ''): Promise<LedgerSnapshotSummary> {
  const r = await apiClient.post('/dda-ledger/baseline/from-server', { tag, memo }, LONG);
  return r.data;
}
