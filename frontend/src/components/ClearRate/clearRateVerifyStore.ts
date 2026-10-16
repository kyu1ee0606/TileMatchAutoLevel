/**
 * 검증 탭 실유저 클리어율 저장소 (문서 38 §10-2) — 별도 IndexedDB `TileMatchClearRateVerify`.
 * 생산 저장소(TileMatchProduction: productionStorage.ts)·레벨 메타·기존 검증 결과·업로드 메타는 읽지도 쓰지도 않는다
 * (다른 세션 파일 충돌 회피 + 덮어쓰기 금지). 측정 원자료는 백엔드(data/clear_rate_verify)에만 있다.
 *
 * stores
 *   targets  key `${batch}|A` (A 목표 곡선) · `${batch}|B` (B 봇 목표, 단일값) — A·B 별도 데이터
 *   records  key `${batch}|${level}|${mode}|${kind}` 최신 판정 기록 (EvaluationRecord)
 *   history  자동 증가 키 — 덮어쓴 이전 판정 기록 보존 (출처 포함, 현재 유효와 구분)
 *   jobs     key `${batch}|${level}` C 작업 참조 (ConfirmJobRef)
 * 모든 쓰기는 트랜잭션 완료(oncomplete)까지 기다린 뒤 resolve — 실패는 reject 로 올려 화면이 "저장 실패"를 표시한다.
 */
import type { TargetCurve } from './targetCurve';
import { normalizeCurve } from './targetCurve';
import type { ConfirmJobRef, EvaluationRecord } from './clearRateVerifyModel';
import { normalizeJobRef, normalizeRecord } from './clearRateVerifyModel';

const DB_NAME = 'TileMatchClearRateVerify';
const DB_VERSION = 1;
const S = { TARGETS: 'targets', RECORDS: 'records', HISTORY: 'history', JOBS: 'jobs' } as const;

let dbp: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbp) return dbp;
  dbp = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(S.TARGETS)) db.createObjectStore(S.TARGETS, { keyPath: 'key' });
      if (!db.objectStoreNames.contains(S.RECORDS)) {
        db.createObjectStore(S.RECORDS, { keyPath: 'key' }).createIndex('batch_id', 'batch_id', { unique: false });
      }
      if (!db.objectStoreNames.contains(S.HISTORY)) {
        db.createObjectStore(S.HISTORY, { autoIncrement: true }).createIndex('batch_id', 'batch_id', { unique: false });
      }
      if (!db.objectStoreNames.contains(S.JOBS)) {
        db.createObjectStore(S.JOBS, { keyPath: 'key' }).createIndex('batch_id', 'batch_id', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => { dbp = null; reject(req.error ?? new Error('IndexedDB open failed')); };
  });
  return dbp;
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('IndexedDB write failed'));
    tx.onabort = () => reject(tx.error ?? new Error('IndexedDB write aborted'));
  });
}

function byBatch<T>(db: IDBDatabase, store: string, batchId: string): Promise<T[]> {
  return new Promise((resolve, reject) => {
    const req = db.transaction(store, 'readonly').objectStore(store).index('batch_id').getAll(batchId);
    req.onsuccess = () => resolve(req.result as T[]);
    req.onerror = () => reject(req.error);
  });
}

function getOne<T>(db: IDBDatabase, store: string, key: string): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const req = db.transaction(store, 'readonly').objectStore(store).get(key);
    req.onsuccess = () => resolve(req.result as T | undefined);
    req.onerror = () => reject(req.error);
  });
}

export interface BatchVerifyState {
  curve: TargetCurve | null;
  bTarget: number | null;
  records: EvaluationRecord[];
  jobs: ConfirmJobRef[];
  /** 형식이 맞지 않아 무시한 이전 저장 항목 수 */
  skipped: number;
}

export async function loadBatchVerifyState(batchId: string): Promise<BatchVerifyState> {
  const db = await openDb();
  const [a, b, recs, jobs] = await Promise.all([
    getOne<{ key: string; curve: unknown }>(db, S.TARGETS, `${batchId}|A`),
    getOne<{ key: string; target: unknown }>(db, S.TARGETS, `${batchId}|B`),
    byBatch<unknown>(db, S.RECORDS, batchId),
    byBatch<unknown>(db, S.JOBS, batchId),
  ]);
  const records = recs.map(normalizeRecord).filter((r): r is EvaluationRecord => r != null);
  const jobRefs = jobs.map(normalizeJobRef).filter((r): r is ConfirmJobRef => r != null);
  const bt = typeof b?.target === 'number' && b.target > 0 && b.target < 1 ? b.target : null;
  return { curve: normalizeCurve(a?.curve), bTarget: bt, records, jobs: jobRefs,
           skipped: recs.length - records.length + jobs.length - jobRefs.length };
}

export async function saveCurve(batchId: string, curve: TargetCurve): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(S.TARGETS, 'readwrite');
  tx.objectStore(S.TARGETS).put({ key: `${batchId}|A`, batch_id: batchId, mode: 'user_expected', curve,
                                  saved_at: new Date().toISOString() });
  await done(tx);
}

export async function saveBTarget(batchId: string, target: number | null): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(S.TARGETS, 'readwrite');
  tx.objectStore(S.TARGETS).put({ key: `${batchId}|B`, batch_id: batchId, mode: 'bot_virtual', target,
                                  saved_at: new Date().toISOString() });
  await done(tx);
}

/** 최신 기록을 쓰고, 같은 키의 이전 기록은 history 로 옮겨 보존한다 */
export async function putRecord(rec: EvaluationRecord): Promise<void> {
  const db = await openDb();
  const tx = db.transaction([S.RECORDS, S.HISTORY], 'readwrite');
  const records = tx.objectStore(S.RECORDS);
  const prev = records.get(rec.key);
  prev.onsuccess = () => {
    if (prev.result) tx.objectStore(S.HISTORY).add({ ...prev.result, archived_at: new Date().toISOString() });
    records.put(rec);
  };
  await done(tx);
}

export async function putJobRef(ref: ConfirmJobRef): Promise<void> {
  const db = await openDb();
  const tx = db.transaction(S.JOBS, 'readwrite');
  tx.objectStore(S.JOBS).put(ref);
  await done(tx);
}
