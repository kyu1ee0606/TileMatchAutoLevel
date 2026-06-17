/**
 * 프로덕션 배치 서버(로컬 파일) 동기화.
 *
 * 프로덕션 레벨은 기본적으로 IndexedDB(브라우저-로컬)에 저장돼 다른 브라우저에선 안 보인다.
 * 백엔드(localhost)가 배치를 로컬 파일로 보관하면 같은 컴퓨터의 모든 브라우저가 동일 데이터에
 * 접근할 수 있다. 이 모듈이 IndexedDB ↔ 서버 파일 동기화를 담당한다.
 *
 * - push: 로컬 배치(메타+레벨) → 서버 파일 저장
 * - pullAllToLocal: 서버의 모든 배치 → IndexedDB upsert (앱 로드 시 호출 → 타 브라우저 데이터 표시)
 */
import apiClient from '../api/client';
import type { ProductionBatch, ProductionLevel } from '../types/production';
import {
  getProductionBatch,
  getProductionLevelsByBatch,
  saveProductionLevels,
  putBatchRaw,
  listProductionBatches,
  onLevelsWritten,
} from './productionStorage';

export interface ServerBatchSummary {
  batch_id: string;
  name: string | null;
  level_count: number;
  saved_at: number;
  size_bytes: number;
  version: number;
}

interface ServerBatchPayload {
  batch_id: string;
  batch: ProductionBatch;
  levels: ProductionLevel[];
  saved_at: number;
  version: number;
}

/** 충돌(다른 브라우저 선수정) 시 던지는 에러. */
export class SyncConflictError extends Error {
  serverVersion: number;
  constructor(batchId: string, serverVersion: number) {
    super(`sync conflict: ${batchId} (server v${serverVersion})`);
    this.name = 'SyncConflictError';
    this.serverVersion = serverVersion;
  }
}

// 배치별 마지막으로 알던 서버 버전(낙관적 동시성 기준).
const knownVersions = new Map<string, number>();

export function getKnownVersion(batchId: string): number | undefined {
  return knownVersions.get(batchId);
}

/**
 * 로컬 배치(메타+레벨)를 서버 파일에 저장.
 * @param force true면 버전 검사 없이 강제 덮어쓰기(수동 "서버 저장"·최초 저장).
 *              false면 낙관적 동시성 — 서버가 더 최신이면 SyncConflictError.
 */
export async function pushBatchToServer(batchId: string, opts?: { force?: boolean }): Promise<boolean> {
  const batch = await getProductionBatch(batchId);
  if (!batch) return false;
  const levels = await getProductionLevelsByBatch(batchId);
  const base_version = opts?.force ? null : (knownVersions.get(batchId) ?? null);
  try {
    const r = await apiClient.put<{ version: number }>(`/production/batches/${batchId}`, {
      batch_id: batchId,
      batch,
      levels,
      base_version,
    });
    knownVersions.set(batchId, r.data.version);
    return true;
  } catch (e: unknown) {
    const err = e as { response?: { status?: number; data?: { detail?: { server_version?: number } } } };
    if (err.response?.status === 409) {
      throw new SyncConflictError(batchId, err.response.data?.detail?.server_version ?? 0);
    }
    throw e;
  }
}

/** 서버에 저장된 배치 요약 목록. */
export async function listServerBatches(): Promise<ServerBatchSummary[]> {
  const r = await apiClient.get<ServerBatchSummary[]>('/production/batches');
  return r.data;
}

/** 서버 배치 1개를 IndexedDB로 가져오기(upsert) + 버전 기록. */
export async function pullBatchToLocal(batchId: string): Promise<void> {
  const r = await apiClient.get<ServerBatchPayload>(`/production/batches/${batchId}`);
  const { batch, levels, version } = r.data;
  if (batch) await putBatchRaw(batch);
  if (levels && levels.length > 0) await saveProductionLevels(batchId, levels);
  knownVersions.set(batchId, version ?? 0);
}

/** 서버 파일 삭제. */
export async function deleteServerBatch(batchId: string): Promise<void> {
  await apiClient.delete(`/production/batches/${batchId}`);
}

/**
 * 서버의 모든 배치를 IndexedDB로 동기화(upsert). 앱/프로덕션 탭 로드 시 호출하면
 * 다른 브라우저에서 만든 배치가 현재 브라우저에도 나타난다.
 * 반환: 새로 가져온(로컬에 없던) 배치 수.
 */
export async function pullAllToLocal(): Promise<number> {
  let serverBatches: ServerBatchSummary[];
  try {
    serverBatches = await listServerBatches();
  } catch {
    return 0; // 서버 미가동 등 — 조용히 무시(로컬만 사용)
  }
  if (serverBatches.length === 0) return 0;
  const localIds = new Set((await listProductionBatches()).map(b => b.id));
  let pulled = 0;
  for (const sb of serverBatches) {
    try {
      await pullBatchToLocal(sb.batch_id);
      if (!localIds.has(sb.batch_id)) pulled++;
    } catch {
      // 개별 실패는 건너뜀
    }
  }
  return pulled;
}

// ── 자동 push (디바운스) + 충돌 처리 ─────────────────────────────────────────
const PUSH_DEBOUNCE_MS = 4000;
const pushTimers = new Map<string, ReturnType<typeof setTimeout>>();
let conflictHandler: ((batchId: string, serverVersion: number) => void) | null = null;

/** 충돌(다른 브라우저 선수정) 발생 시 UI 알림 콜백 등록. */
export function setConflictHandler(cb: (batchId: string, serverVersion: number) => void): void {
  conflictHandler = cb;
}

/**
 * 디바운스 push — 레벨 편집이 잦을 때(순차처리·일괄재생성 등) 코얼레싱.
 * 마지막 편집 후 PUSH_DEBOUNCE_MS 뒤 1회만 서버에 올린다. 낙관적 동시성(force=false).
 */
export function schedulePush(batchId: string): void {
  if (!batchId) return;
  const existing = pushTimers.get(batchId);
  if (existing) clearTimeout(existing);
  pushTimers.set(batchId, setTimeout(async () => {
    pushTimers.delete(batchId);
    try {
      await pushBatchToServer(batchId);
    } catch (e) {
      if (e instanceof SyncConflictError) conflictHandler?.(batchId, e.serverVersion);
      // 그 외(서버 미가동 등)는 조용히 무시
    }
  }, PUSH_DEBOUNCE_MS));
}

let autoSyncRegistered = false;
/** productionStorage 레벨 쓰기마다 자동 디바운스 push 등록. 앱당 1회. */
export function registerAutoSync(): void {
  if (autoSyncRegistered) return;
  autoSyncRegistered = true;
  onLevelsWritten((batchId) => schedulePush(batchId));
}
