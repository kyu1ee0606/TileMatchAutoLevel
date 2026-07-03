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

// 서버→로컬 pull 진행 중 플래그. pull은 saveProductionLevels를 호출하는데, 그게 쓰기 리스너를
// 통해 자동 push를 트리거하면 'pull→write→push' 피드백이 생긴다. pull 중에는 push를 억제한다.
let _syncing = false;

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
  // 낙관적 동시성 기준: 메모리(knownVersions) → 영속(batch.__server_version) 순.
  // 리로드 직후에도 영속 버전으로 충돌 감지 가능(과거엔 null → 무조건 강제 덮어쓰기였음).
  const base_version = opts?.force ? null : (knownVersions.get(batchId) ?? batch.__server_version ?? null);
  try {
    const r = await apiClient.put<{ version: number; divisibility_flagged?: number; divisibility_levels?: number[] }>(`/production/batches/${batchId}`, {
      batch_id: batchId,
      batch,
      levels,
      base_version,
    });
    knownVersions.set(batchId, r.data.version);
    // 서버 버전 영속화 — 마운트 sync의 '서버가 더 최신' 비교 기준.
    try { await putBatchRaw({ ...batch, __server_version: r.data.version }); } catch { /* 버전 기록 실패는 무시 */ }
    // 서버 ÷3 게이트가 클리어 불가 레벨을 검출하면 경고(저장은 됐으나 해당 레벨은 verification_passed=false 강제됨).
    if (r.data.divisibility_flagged && r.data.divisibility_flagged > 0) {
      divisibilityWarningHandler?.(batchId, r.data.divisibility_flagged, r.data.divisibility_levels ?? []);
    }
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
  if (batch) await putBatchRaw({ ...batch, __server_version: version ?? 0 });
  if (levels && levels.length > 0) await saveProductionLevels(batchId, levels);
  knownVersions.set(batchId, version ?? 0);
}

/** 서버 파일 삭제. */
export async function deleteServerBatch(batchId: string): Promise<void> {
  await apiClient.delete(`/production/batches/${batchId}`);
}

/**
 * 서버 배치를 IndexedDB로 가져온다(버전 비교 pull). 앱/프로덕션 탭 로드 시 호출.
 *
 * pull 대상:
 *  1) 로컬에 없는 배치 (다른 브라우저에서 생성)
 *  2) 로컬 __server_version 미기록(레거시 사본) — 1회 pull 후 버전 기록되므로 이후 스킵
 *  3) 서버 버전 > 로컬 __server_version (다른 브라우저/서버측 수정) — stale 사본이
 *     서버 최신본을 덮어쓰는 사고 방지
 *
 * ⚠️ 메모리 안전: 버전 동일 배치는 pull 안 함 → 정상 상태에선 매 마운트 0회 pull.
 * 레거시(2) 케이스만 최초 1회 전체 pull이 발생하고 이후 버전 비교로 수렴한다.
 * 반환: 가져온 배치 수.
 */
export async function pullAllToLocal(): Promise<number> {
  let serverBatches: ServerBatchSummary[];
  try {
    serverBatches = await listServerBatches();
  } catch {
    return 0; // 서버 미가동 등 — 조용히 무시(로컬만 사용)
  }
  if (serverBatches.length === 0) return 0;
  const localMap = new Map((await listProductionBatches()).map(b => [b.id, b]));
  let pulled = 0;
  _syncing = true;
  try {
    for (const sb of serverBatches) {
      const local = localMap.get(sb.batch_id);
      const localVer = local?.__server_version;
      // 버전 기록이 있고 서버보다 같거나 최신이면 스킵(메모리 폭증 방지 — 대부분 여기서 끝)
      if (local && localVer !== undefined && localVer >= (sb.version ?? 0)) continue;
      try {
        await pullBatchToLocal(sb.batch_id);
        pulled++;
      } catch {
        // 개별 실패는 건너뜀
      }
    }
  } finally {
    _syncing = false;
  }
  return pulled;
}

/**
 * 로컬(IndexedDB)에만 있고 서버엔 없는 배치를 서버로 업로드.
 * 이 기능 추가 전에 만든 기존 배치를 처음 마운트 때 서버에 올려, 다른 브라우저에서도 보이게 함.
 * 반환: 업로드한 배치 수.
 */
export async function pushLocalMissingToServer(): Promise<number> {
  let serverIds: Set<string>;
  try {
    serverIds = new Set((await listServerBatches()).map(b => b.batch_id));
  } catch {
    return 0; // 서버 미가동 — 무시
  }
  const local = await listProductionBatches();
  let pushed = 0;
  for (const b of local) {
    if (serverIds.has(b.id)) continue; // 이미 서버에 있음
    try {
      await pushBatchToServer(b.id, { force: true }); // 서버에 없으므로 강제(=최초 저장)
      pushed++;
    } catch {
      // 개별 실패는 건너뜀
    }
  }
  return pushed;
}

/**
 * 마운트용 양방향 동기화: 로컬-only 배치는 서버로 올리고(push), 서버 배치는 로컬로 내림(pull).
 * → 같은 컴퓨터의 어느 브라우저든 모든 배치가 보인다.
 */
export async function syncBidirectional(): Promise<{ pushed: number; pulled: number }> {
  const pushed = await pushLocalMissingToServer();
  const pulled = await pullAllToLocal();
  return { pushed, pulled };
}

// ── 자동 push (디바운스) + 충돌 처리 ─────────────────────────────────────────
const PUSH_DEBOUNCE_MS = 4000;
const pushTimers = new Map<string, ReturnType<typeof setTimeout>>();
let conflictHandler: ((batchId: string, serverVersion: number) => void) | null = null;

/** 충돌(다른 브라우저 선수정) 발생 시 UI 알림 콜백 등록. */
export function setConflictHandler(cb: (batchId: string, serverVersion: number) => void): void {
  conflictHandler = cb;
}

let divisibilityWarningHandler: ((batchId: string, flagged: number, levels: number[]) => void) | null = null;

/** 저장 시 서버가 ÷3 위반(클리어 불가) 레벨을 검출하면 UI 경고 콜백 등록. */
export function setDivisibilityWarningHandler(cb: (batchId: string, flagged: number, levels: number[]) => void): void {
  divisibilityWarningHandler = cb;
}

/**
 * 디바운스 push — 레벨 편집이 잦을 때(순차처리·일괄재생성 등) 코얼레싱.
 * 마지막 편집 후 PUSH_DEBOUNCE_MS 뒤 1회만 서버에 올린다. 낙관적 동시성(force=false).
 */
export function schedulePush(batchId: string): void {
  if (!batchId || _syncing) return; // pull로 인한 쓰기는 push 트리거 금지(피드백 방지)
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
