/**
 * 생산 대시보드 배치 선택 결정 — 순수 함수(테스트: frontend/tests/batchSelection.test.ts).
 * 서버 동기화로 배치 목록이 바뀐 뒤: 현재 선택이 목록에 있으면 보존, 없을 때만 created_at 최신 배치(없으면 null).
 * (새 프로필 첫 진입 시 로컬 0개 → 선택 null 로 남아 셀렉터만 첫 항목을 보여 주던 문제 — 문서 38b)
 */
export interface BatchLike { id: string; created_at: string }

export function latestBatchId(batches: readonly BatchLike[]): string | null {
  let best: BatchLike | null = null;
  for (const b of batches) {
    if (!best || new Date(b.created_at).getTime() > new Date(best.created_at).getTime()) best = b;
  }
  return best ? best.id : null;
}

export function pickSelectedBatchId(current: string | null, batches: readonly BatchLike[]): string | null {
  if (current && batches.some(b => b.id === current)) return current;
  return latestBatchId(batches);
}
