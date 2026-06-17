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
} from './productionStorage';

export interface ServerBatchSummary {
  batch_id: string;
  name: string | null;
  level_count: number;
  saved_at: number;
  size_bytes: number;
}

interface ServerBatchPayload {
  batch_id: string;
  batch: ProductionBatch;
  levels: ProductionLevel[];
  saved_at: number;
}

/** 로컬 배치(메타+레벨)를 서버 파일에 저장. */
export async function pushBatchToServer(batchId: string): Promise<boolean> {
  const batch = await getProductionBatch(batchId);
  if (!batch) return false;
  const levels = await getProductionLevelsByBatch(batchId);
  await apiClient.put(`/production/batches/${batchId}`, {
    batch_id: batchId,
    batch,
    levels,
  });
  return true;
}

/** 서버에 저장된 배치 요약 목록. */
export async function listServerBatches(): Promise<ServerBatchSummary[]> {
  const r = await apiClient.get<ServerBatchSummary[]>('/production/batches');
  return r.data;
}

/** 서버 배치 1개를 IndexedDB로 가져오기(upsert). */
export async function pullBatchToLocal(batchId: string): Promise<void> {
  const r = await apiClient.get<ServerBatchPayload>(`/production/batches/${batchId}`);
  const { batch, levels } = r.data;
  if (batch) await putBatchRaw(batch);
  if (levels && levels.length > 0) await saveProductionLevels(batchId, levels);
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
