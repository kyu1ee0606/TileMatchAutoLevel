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
  getProductionLevelsByNumbers,
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
 * 배치별 '아직 서버에 안 올린 레벨 번호'.
 *
 * 이게 델타 동기화의 전부다. 쓰기 알림이 올 때 번호를 모아두고, push 때 그 번호만
 * 조회해 보낸다. push 성공 시 **보낸 번호만** 지운다 — 전송 중에 새로 들어온 변경이
 * 함께 지워지면 그 편집이 영영 안 올라간다.
 */
const dirtyLevels = new Map<string, Set<number>>();

function markDirty(batchId: string, nums: number[]): void {
  if (nums.length === 0) return;
  let s = dirtyLevels.get(batchId);
  if (!s) { s = new Set(); dirtyLevels.set(batchId, s); }
  for (const n of nums) if (Number.isFinite(n)) s.add(n);
}

/** 미전송 변경 수(디버그·수동 동기화 판단용). */
export function getDirtyCount(batchId: string): number {
  return dirtyLevels.get(batchId)?.size ?? 0;
}

/**
 * 로컬 배치를 서버 파일에 저장.
 *
 * 기본은 **델타**: 마지막 push 이후 바뀐 레벨만 보낸다(서버가 level_number 로 병합).
 * 예전엔 무조건 1500레벨(4.9MB) 전량이라, 순차검증 12시간에 약 5GB를 직렬화·전송했고
 * 브라우저 힙이 그 주기로 쌓여 탭이 죽었다.
 *
 * @param force true면 버전 검사 없이 강제 덮어쓰기. **force 는 항상 전량**이다 —
 *              덮어쓸 상태에 델타를 병합하는 건 의미가 모순된다.
 * @param full  true면 델타를 쓰지 않고 전량 전송(최초 업로드·수동 복구용).
 */
export async function pushBatchToServer(
  batchId: string,
  opts?: { force?: boolean; full?: boolean },
): Promise<boolean> {
  const batch = await getProductionBatch(batchId);
  if (!batch) return false;

  const dirty = dirtyLevels.get(batchId);
  const isAuto = !opts?.force && !opts?.full;

  // [전량 폴백 차단] 자동 경로인데 보낼 변경이 없으면 **아무것도 하지 않는다**.
  //
  // 예전엔 이 경우 전량(4.9MB)으로 떨어졌다. runSerializedPush 의 pendingPush 재실행이
  // 대표적인데 — push 가 나가는 동안 들어온 요청을 완료 후 한 번 더 돌리는 구조라,
  // 앞선 push 가 dirty 를 비운 뒤엔 보낼 게 없는데도 전량이 나갔다.
  // 실측: PUT 32건 중 8건(25%)이 이 경로였다.
  // 자동 push 는 '레벨 쓰기'로만 예약되므로, dirty 가 비었으면 동기화할 것도 없다.
  if (isAuto && (!dirty || dirty.size === 0)) return true;

  // force ⇒ full. 서버에 아직 없을 수도 있는 상황이라 병합 대상 자체가 없다.
  const usePartial = isAuto && !!dirty && dirty.size > 0;
  const sending = usePartial ? [...dirty!] : null;

  const levels = sending
    ? await getProductionLevelsByNumbers(batchId, sending)
    : await getProductionLevelsByBatch(batchId);

  // 낙관적 동시성 기준: 메모리(knownVersions) → 영속(batch.__server_version) 순.
  // 리로드 직후에도 영속 버전으로 충돌 감지 가능(과거엔 null → 무조건 강제 덮어쓰기였음).
  const base_version = opts?.force ? null : (knownVersions.get(batchId) ?? batch.__server_version ?? null);
  try {
    const r = await apiClient.put<{ version: number; divisibility_flagged?: number; divisibility_levels?: number[] }>(`/production/batches/${batchId}`, {
      batch_id: batchId,
      batch,
      levels,
      base_version,
      partial: usePartial,
    });
    knownVersions.set(batchId, r.data.version);
    // 보낸 번호만 제거 — 전송 중 들어온 변경은 다음 push 로 넘긴다.
    if (sending) {
      const cur = dirtyLevels.get(batchId);
      if (cur) { for (const n of sending) cur.delete(n); if (cur.size === 0) dirtyLevels.delete(batchId); }
    } else {
      dirtyLevels.delete(batchId);   // 전량 전송했으니 미전송분 없음
    }
    // 서버 버전 영속화 — 마운트 sync의 '서버가 더 최신' 비교 기준.
    try { await putBatchRaw({ ...batch, __server_version: r.data.version }); } catch { /* 버전 기록 실패는 무시 */ }
    // 서버 ÷3 게이트가 클리어 불가 레벨을 검출하면 경고(저장은 됐으나 해당 레벨은 verification_passed=false 강제됨).
    if (r.data.divisibility_flagged && r.data.divisibility_flagged > 0) {
      divisibilityWarningHandler?.(batchId, r.data.divisibility_flagged, r.data.divisibility_levels ?? []);
    }
    return true;
  } catch (e: unknown) {
    // 실패 시 dirty 를 **그대로 둔다** → 다음 push 에서 재시도된다.
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
  // silent: pull 로 받은 건 서버와 이미 같다 → 쓰기 알림을 내면 1500개가 dirty 로 찍혀
  // 곧장 전량 push 가 되돌아 나간다(에코 루프).
  if (levels && levels.length > 0) await saveProductionLevels(batchId, levels, { silent: true });
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
const inFlightPush = new Set<string>();   // 배치당 push 진행중 여부(직렬화)
const pendingPush = new Set<string>();    // 진행중에 들어온 재요청 → 완료 후 1회 실행
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
  pushTimers.set(batchId, setTimeout(() => {
    pushTimers.delete(batchId);
    void runSerializedPush(batchId);
  }, PUSH_DEBOUNCE_MS));
}

/**
 * [직렬화] 배치당 push는 한 번에 하나만. in-flight 중 새 요청은 pending 플래그만 세우고 완료 후 1회
 * 재실행 → base_version이 항상 '직전 push가 올린 서버버전'을 반영하므로 자기 push끼리 레이스로 인한
 * 409 오탐("다른 브라우저에서 수정됨")이 사라진다. (직렬화 후에도 409면 진짜 외부 수정 → 경고 유지.)
 * 순차검증처럼 레벨 저장이 잦아 push가 겹치던 상황(v99 등)을 해소.
 */
async function runSerializedPush(batchId: string): Promise<void> {
  if (inFlightPush.has(batchId)) { pendingPush.add(batchId); return; }
  inFlightPush.add(batchId);
  try {
    await pushBatchToServer(batchId);
  } catch (e) {
    if (e instanceof SyncConflictError) conflictHandler?.(batchId, e.serverVersion);
    // 그 외(서버 미가동 등)는 조용히 무시
  } finally {
    inFlightPush.delete(batchId);
    if (pendingPush.has(batchId)) { pendingPush.delete(batchId); void runSerializedPush(batchId); }
  }
}

let autoSyncRegistered = false;
/** productionStorage 레벨 쓰기마다 자동 디바운스 push 등록. 앱당 1회. */
export function registerAutoSync(): void {
  if (autoSyncRegistered) return;
  autoSyncRegistered = true;
  onLevelsWritten((batchId, levelNumbers) => {
    markDirty(batchId, levelNumbers);
    schedulePush(batchId);
  });
}
