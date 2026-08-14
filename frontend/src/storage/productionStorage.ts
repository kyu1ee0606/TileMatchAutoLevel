/**
 * Production Level Storage
 * 1500개 레벨 프로덕션 데이터 저장/로드
 *
 * IndexedDB를 사용하여 대용량 데이터 처리
 * localStorage 한계(5MB)를 넘어 수백 MB까지 저장 가능
 */

import {
  ProductionBatch,
  ProductionLevel,
  ProductionLevelMeta,
  ProductionStats,
  LevelStatus,
  PlaytestResult,
  ProductionExportConfig,
} from '../types/production';
import { LevelJSON, DifficultyGrade } from '../types';

const DB_NAME = 'TileMatchProduction';
const DB_VERSION = 1;

// Store names
const STORES = {
  BATCHES: 'batches',
  LEVELS: 'levels',
  PLAYTEST_QUEUE: 'playtest_queue',
} as const;

let db: IDBDatabase | null = null;

/**
 * IndexedDB 초기화
 */
export async function initProductionDB(): Promise<IDBDatabase> {
  if (db) return db;

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      db = request.result;
      resolve(db);
    };

    request.onupgradeneeded = (event) => {
      const database = (event.target as IDBOpenDBRequest).result;

      // Batches store
      if (!database.objectStoreNames.contains(STORES.BATCHES)) {
        database.createObjectStore(STORES.BATCHES, { keyPath: 'id' });
      }

      // Levels store (keyed by batch_id + level_number)
      if (!database.objectStoreNames.contains(STORES.LEVELS)) {
        const levelStore = database.createObjectStore(STORES.LEVELS, {
          keyPath: ['batch_id', 'meta.level_number'],
        });
        levelStore.createIndex('batch_id', 'batch_id', { unique: false });
        levelStore.createIndex('status', 'meta.status', { unique: false });
        levelStore.createIndex('level_number', 'meta.level_number', { unique: false });
        levelStore.createIndex('grade', 'meta.grade', { unique: false });
        levelStore.createIndex('playtest_required', 'meta.playtest_required', { unique: false });
      }

      // Playtest queue store (for quick access to pending playtests)
      if (!database.objectStoreNames.contains(STORES.PLAYTEST_QUEUE)) {
        const queueStore = database.createObjectStore(STORES.PLAYTEST_QUEUE, {
          keyPath: ['batch_id', 'level_number'],
        });
        queueStore.createIndex('priority', 'priority', { unique: false });
      }
    };
  });
}

/**
 * 배치 생성
 */
export async function createProductionBatch(
  batch: Omit<ProductionBatch, 'id' | 'created_at' | 'updated_at'>
): Promise<ProductionBatch> {
  const database = await initProductionDB();

  const newBatch: ProductionBatch = {
    ...batch,
    id: `batch_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readwrite');
    const store = tx.objectStore(STORES.BATCHES);
    const request = store.add(newBatch);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(newBatch);
  });
}

/**
 * 배치 직접 upsert (id 보존) — 서버 동기화 pull 용.
 */
export async function putBatchRaw(batch: ProductionBatch): Promise<void> {
  const database = await initProductionDB();
  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readwrite');
    const request = tx.objectStore(STORES.BATCHES).put(batch);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

/**
 * 배치 조회
 */
export async function getProductionBatch(batchId: string): Promise<ProductionBatch | null> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readonly');
    const store = tx.objectStore(STORES.BATCHES);
    const request = store.get(batchId);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || null);
  });
}

/**
 * 모든 배치 목록 조회
 */
export async function listProductionBatches(): Promise<ProductionBatch[]> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readonly');
    const store = tx.objectStore(STORES.BATCHES);
    const request = store.getAll();

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result || []);
  });
}

/**
 * 배치 업데이트
 */
export async function updateProductionBatch(
  batchId: string,
  updates: Partial<ProductionBatch>
): Promise<void> {
  const database = await initProductionDB();
  const existing = await getProductionBatch(batchId);

  if (!existing) {
    throw new Error(`Batch ${batchId} not found`);
  }

  const updated: ProductionBatch = {
    ...existing,
    ...updates,
    id: batchId,  // Preserve ID
    updated_at: new Date().toISOString(),
  };

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readwrite');
    const store = tx.objectStore(STORES.BATCHES);
    const request = store.put(updated);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}

// 레벨 쓰기 리스너 — 서버 자동 동기화(디바운스 push)용. productionServerSync가 등록한다.
const _writeListeners = new Set<(batchId: string) => void>();
export function onLevelsWritten(cb: (batchId: string) => void): void {
  _writeListeners.add(cb);
}
function _notifyWritten(batchId: string): void {
  for (const cb of _writeListeners) {
    try { cb(batchId); } catch { /* 리스너 오류 무시 */ }
  }
}

/**
 * 레벨 저장 (단일)
 */
export async function saveProductionLevel(
  batchId: string,
  level: ProductionLevel
): Promise<void> {
  const database = await initProductionDB();

  const record = {
    batch_id: batchId,
    ...level,
  };

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readwrite');
    const store = tx.objectStore(STORES.LEVELS);
    const request = store.put(record);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => { _notifyWritten(batchId); resolve(); };
  });
}

/**
 * 레벨 저장 (배치 - 여러 개 한번에)
 */
export async function saveProductionLevels(
  batchId: string,
  levels: ProductionLevel[]
): Promise<void> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readwrite');
    const store = tx.objectStore(STORES.LEVELS);

    let completed = 0;
    let hasError = false;

    for (const level of levels) {
      const record = {
        batch_id: batchId,
        ...level,
      };
      const request = store.put(record);

      request.onerror = () => {
        if (!hasError) {
          hasError = true;
          reject(request.error);
        }
      };

      request.onsuccess = () => {
        completed++;
        if (completed === levels.length && !hasError) {
          _notifyWritten(batchId);
          resolve();
        }
      };
    }

    if (levels.length === 0) {
      resolve();
    }
  });
}

/**
 * 레벨 조회 (단일)
 */
export async function getProductionLevel(
  batchId: string,
  levelNumber: number
): Promise<ProductionLevel | null> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readonly');
    const store = tx.objectStore(STORES.LEVELS);
    const request = store.get([batchId, levelNumber]);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      if (request.result) {
        const { batch_id, ...level } = request.result;
        resolve(level as ProductionLevel);
      } else {
        resolve(null);
      }
    };
  });
}

/**
 * 배치 레벨 수만 조회 (레벨 데이터 로드 없이 IndexedDB index.count 사용 — 메모리/속도 최적).
 * getProductionLevelsByBatch(...).length는 1500개 level_json을 전부 로드하므로 카운트엔 부적합.
 */
export async function countLevelsByBatch(batchId: string): Promise<number> {
  const database = await initProductionDB();
  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readonly');
    const request = tx.objectStore(STORES.LEVELS).index('batch_id').count(batchId);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

/**
 * 배치에 이미 존재하는 레벨번호 집합 (level_json 미로드 — key cursor로 경량 조회).
 * "이어서 생성" 재개 시 기존 레벨 스킵 판정용. (compound key [batchId, level_number])
 */
export async function getProductionLevelNumbersByBatch(batchId: string): Promise<Set<number>> {
  const database = await initProductionDB();
  return new Promise((resolve, reject) => {
    const out = new Set<number>();
    const tx = database.transaction(STORES.LEVELS, 'readonly');
    const req = tx.objectStore(STORES.LEVELS).index('batch_id').openKeyCursor(batchId);
    req.onerror = () => reject(req.error);
    req.onsuccess = () => {
      const cur = req.result;
      if (cur) {
        const pk = cur.primaryKey as [string, number] | number;
        const ln = Array.isArray(pk) ? pk[1] : pk;
        if (typeof ln === 'number') out.add(ln);
        cur.continue();
      } else {
        resolve(out);
      }
    };
  });
}

/**
 * 배치의 모든 레벨 조회
 */
export async function getProductionLevelsByBatch(
  batchId: string,
  options?: {
    offset?: number;
    limit?: number;
    status?: LevelStatus;
    grade?: DifficultyGrade;
  }
): Promise<ProductionLevel[]> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readonly');
    const store = tx.objectStore(STORES.LEVELS);
    const index = store.index('batch_id');
    const request = index.getAll(batchId);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      let results = request.result.map((r: { batch_id: string; meta: ProductionLevelMeta; level_json: LevelJSON }) => ({
        meta: r.meta,
        level_json: r.level_json,
      }));

      // Filter by status
      if (options?.status) {
        results = results.filter(l => l.meta.status === options.status);
      }

      // Filter by grade
      if (options?.grade) {
        results = results.filter(l => l.meta.grade === options.grade);
      }

      // Sort by level number
      results.sort((a, b) => a.meta.level_number - b.meta.level_number);

      // Apply pagination
      if (options?.offset !== undefined || options?.limit !== undefined) {
        const start = options?.offset || 0;
        const end = options?.limit ? start + options.limit : undefined;
        results = results.slice(start, end);
      }

      resolve(results);
    };
  });
}

/**
 * 플레이테스트 대기 레벨 조회
 */
export async function getPlaytestQueue(
  batchId: string,
  limit?: number
): Promise<ProductionLevel[]> {
  const database = await initProductionDB();

  return new Promise((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readonly');
    const store = tx.objectStore(STORES.LEVELS);
    const index = store.index('batch_id');
    const request = index.getAll(batchId);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      let results = request.result
        .filter((r: { meta: ProductionLevelMeta }) =>
          r.meta.playtest_required &&
          (r.meta.status === 'playtest_queue' || r.meta.status === 'playtesting')
        )
        .map((r: { meta: ProductionLevelMeta; level_json: LevelJSON }) => ({
          meta: r.meta,
          level_json: r.level_json,
        }));

      // Sort by priority (lower = higher priority)
      results.sort((a, b) => a.meta.playtest_priority - b.meta.playtest_priority);

      if (limit) {
        results = results.slice(0, limit);
      }

      resolve(results);
    };
  });
}

/**
 * 레벨 메타 업데이트 (상태 변경 없이)
 * 배치 검증 결과 저장 등에 사용
 */
export async function updateProductionLevel(
  batchId: string,
  levelNumber: number,
  metaUpdate: Partial<ProductionLevelMeta>
): Promise<void> {
  const level = await getProductionLevel(batchId, levelNumber);

  if (!level) {
    throw new Error(`Level ${levelNumber} not found in batch ${batchId}`);
  }

  level.meta = {
    ...level.meta,
    ...metaUpdate,
  };

  await saveProductionLevel(batchId, level);
}

/**
 * 레벨 상태 업데이트
 */
export async function updateLevelStatus(
  batchId: string,
  levelNumber: number,
  status: LevelStatus,
  additionalData?: Partial<ProductionLevelMeta>
): Promise<void> {
  const level = await getProductionLevel(batchId, levelNumber);

  if (!level) {
    throw new Error(`Level ${levelNumber} not found in batch ${batchId}`);
  }

  level.meta = {
    ...level.meta,
    ...additionalData,
    status,
    status_updated_at: new Date().toISOString(),
  };

  await saveProductionLevel(batchId, level);

  // Update batch counts
  await recalculateBatchCounts(batchId);
}

/**
 * 플레이테스트 결과 추가
 */
export async function addPlaytestResult(
  batchId: string,
  levelNumber: number,
  result: PlaytestResult
): Promise<void> {
  const level = await getProductionLevel(batchId, levelNumber);

  if (!level) {
    throw new Error(`Level ${levelNumber} not found in batch ${batchId}`);
  }

  level.meta.playtest_results = [...(level.meta.playtest_results || []), result];

  // 자동 승인 로직: 클리어 성공 + 재미 점수 3 이상
  const shouldAutoApprove =
    result.cleared &&
    result.fun_rating >= 3 &&
    result.issues.length === 0;

  if (shouldAutoApprove) {
    level.meta.status = 'approved';
    level.meta.approved_at = new Date().toISOString();
    level.meta.approved_by = result.tester_name;
  } else if (!result.cleared || result.fun_rating < 2) {
    level.meta.status = 'needs_rework';
  }

  level.meta.status_updated_at = new Date().toISOString();

  await saveProductionLevel(batchId, level);
  await recalculateBatchCounts(batchId);
}

/**
 * 레벨 승인
 */
export async function approveLevel(
  batchId: string,
  levelNumber: number,
  approvedBy: string
): Promise<void> {
  await updateLevelStatus(batchId, levelNumber, 'approved', {
    approved_by: approvedBy,
    approved_at: new Date().toISOString(),
  });
}

/**
 * 레벨 거부
 */
export async function rejectLevel(
  batchId: string,
  levelNumber: number,
  reason: string
): Promise<void> {
  await updateLevelStatus(batchId, levelNumber, 'rejected', {
    rejection_reason: reason,
  });
}

/**
 * 배치 카운트 재계산 (레벨 저장 후 호출해야 함)
 */
export async function recalculateBatchCounts(batchId: string): Promise<void> {
  const levels = await getProductionLevelsByBatch(batchId);

  const counts = {
    generated_count: 0,
    playtest_count: 0,
    approved_count: 0,
    rejected_count: 0,
    exported_count: 0,
  };

  for (const level of levels) {
    switch (level.meta.status) {
      case 'generated':
        counts.generated_count++;
        break;
      case 'playtest_queue':
      case 'playtesting':
        counts.playtest_count++;
        break;
      case 'approved':
        counts.approved_count++;
        break;
      case 'rejected':
      case 'needs_rework':
        counts.rejected_count++;
        break;
      case 'exported':
        counts.exported_count++;
        break;
    }
  }

  // [이어서 생성 판정용] '실제 저장된 레벨 수'. generated_count 는 status==='generated' 인 것만
  // 세므로 검증을 거쳐 playtest_queue/approved 로 바뀌면 줄어든다 → 생성 진척도로 쓰면 안 된다.
  // (실측: 950개 저장됐는데 generated_count=672 → 재개 판정이 어긋남)
  await updateProductionBatch(batchId, { ...counts, saved_level_count: levels.length });
}

/**
 * 배치 통계 계산
 */
export async function calculateProductionStats(batchId: string): Promise<ProductionStats> {
  const levels = await getProductionLevelsByBatch(batchId);

  const stats: ProductionStats = {
    total_levels: levels.length,
    by_status: {
      generated: 0,
      playtest_queue: 0,
      playtesting: 0,
      approved: 0,
      rejected: 0,
      needs_rework: 0,
      exported: 0,
    },
    by_grade: {
      S: 0,
      A: 0,
      B: 0,
      C: 0,
      D: 0,
    },
    playtest_progress: {
      total_required: 0,
      completed: 0,
      pending: 0,
    },
    quality_metrics: {
      avg_match_score: 0,
      avg_fun_rating: 0,
      avg_perceived_difficulty: 0,
      rejection_rate: 0,
    },
    estimated_completion: {
      remaining_playtest_hours: 0,
      ready_for_export: 0,
    },
  };

  let totalMatchScore = 0;
  let matchScoreCount = 0;
  let totalFunRating = 0;
  let totalPerceivedDifficulty = 0;
  let playtestResultCount = 0;

  for (const level of levels) {
    // Status count
    stats.by_status[level.meta.status]++;

    // Grade count
    stats.by_grade[level.meta.grade]++;

    // Playtest progress
    if (level.meta.playtest_required) {
      stats.playtest_progress.total_required++;
      if (level.meta.playtest_results && level.meta.playtest_results.length > 0) {
        stats.playtest_progress.completed++;
      } else {
        stats.playtest_progress.pending++;
      }
    }

    // Match score
    if (level.meta.match_score !== undefined) {
      totalMatchScore += level.meta.match_score;
      matchScoreCount++;
    }

    // Playtest results
    for (const result of level.meta.playtest_results || []) {
      totalFunRating += result.fun_rating;
      totalPerceivedDifficulty += result.perceived_difficulty;
      playtestResultCount++;
    }

    // Ready for export (approved + not yet exported)
    if (level.meta.status === 'approved') {
      stats.estimated_completion.ready_for_export++;
    }
  }

  // Calculate averages
  if (matchScoreCount > 0) {
    stats.quality_metrics.avg_match_score = totalMatchScore / matchScoreCount;
  }
  if (playtestResultCount > 0) {
    stats.quality_metrics.avg_fun_rating = totalFunRating / playtestResultCount;
    stats.quality_metrics.avg_perceived_difficulty = totalPerceivedDifficulty / playtestResultCount;
  }
  if (stats.by_status.rejected + stats.by_status.needs_rework > 0) {
    stats.quality_metrics.rejection_rate =
      (stats.by_status.rejected + stats.by_status.needs_rework) / levels.length;
  }

  // Estimate remaining time (assuming 3 minutes per playtest)
  stats.estimated_completion.remaining_playtest_hours =
    (stats.playtest_progress.pending * 3) / 60;

  return stats;
}

/**
 * 프로덕션 레벨 내보내기
 */
export async function exportProductionLevels(
  batchId: string,
  config: ProductionExportConfig
): Promise<Blob | { files: Array<{ name: string; data: Blob }> }> {
  // Get all levels and filter to approved/exported
  const allLevels = await getProductionLevelsByBatch(batchId);
  let exportableLevels = allLevels.filter(
    l => l.meta.status === 'approved' || l.meta.status === 'exported'
  );

  // [무한 레벨] 원본은 그대로 두고 사본을 **뒤에 덧붙인다**.
  //   infinity_{index} = 원본 (sourceStart + index - 1)
  // 사본은 원본과 동일한 level_json 을 쓰되 meta 에 출처를 남긴다(추적·재현용).
  // 원본이 배포 게이트를 통과한 것만 대상이므로 사본도 자동으로 통과 상태다.
  if (config.infinity?.enabled) {
    const { prefix, sourceStart, sourceEnd, only } = config.infinity;
    const src = exportableLevels
      .filter(l => l.meta.level_number >= sourceStart && l.meta.level_number <= sourceEnd)
      .sort((a, b) => a.meta.level_number - b.meta.level_number);
    const copies = src.map((l, i) => ({
      ...l,
      meta: {
        ...l.meta,
        infinity_id: `${prefix}${i + 1}`,
        infinity_index: i + 1,
        infinity_source_level: l.meta.level_number,
      },
    }));
    // only=true 면 원본을 빼고 사본만 내보낸다(무한 레벨 단독 배포용).
    exportableLevels = only ? copies : exportableLevels.concat(copies);
  }

  if (config.format === 'json_split') {
    // Split into individual files
    const files = exportableLevels.map(level => {
      // 무한 사본은 원본 레벨번호가 아니라 infinity id 로 파일명을 만든다(원본과 충돌 방지)
      const infId = level.meta.infinity_id;
      const idx = level.meta.infinity_index;
      const filename = infId
        ? config.filename_pattern
            .replace('{number}', infId)
            .replace('{number:04d}', String(idx ?? 0).padStart(4, '0'))
            .replace('{grade}', level.meta.grade)
            .replace(/^level_/, `${infId.replace(/\d+$/, '')}`)
        : config.filename_pattern
            .replace('{number}', String(level.meta.level_number))
            .replace('{number:04d}', String(level.meta.level_number).padStart(4, '0'))
            .replace('{grade}', level.meta.grade);

      const data = config.include_meta
        ? { meta: level.meta, level: level.level_json }
        : level.level_json;

      return {
        name: filename,
        data: new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
      };
    });

    return { files };
  }

  // Single JSON file (array of levels)
  const exportData = exportableLevels.map(level =>
    config.include_meta
      ? { meta: level.meta, level: level.level_json }
      : level.level_json
  );

  const jsonStr = config.format === 'json_minified'
    ? JSON.stringify(exportData)
    : JSON.stringify(exportData, null, 2);

  return new Blob([jsonStr], { type: 'application/json' });
}

/**
 * 배치 이름 변경
 */
export async function renameProductionBatch(
  batchId: string,
  newName: string
): Promise<void> {
  await updateProductionBatch(batchId, { name: newName });
}

/**
 * 배치 삭제
 */
export async function deleteProductionBatch(batchId: string): Promise<void> {
  const database = await initProductionDB();

  // Delete all levels first
  const levels = await getProductionLevelsByBatch(batchId);

  await new Promise<void>((resolve, reject) => {
    const tx = database.transaction(STORES.LEVELS, 'readwrite');
    const store = tx.objectStore(STORES.LEVELS);

    for (const level of levels) {
      store.delete([batchId, level.meta.level_number]);
    }

    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });

  // Delete batch
  await new Promise<void>((resolve, reject) => {
    const tx = database.transaction(STORES.BATCHES, 'readwrite');
    const store = tx.objectStore(STORES.BATCHES);
    const request = store.delete(batchId);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve();
  });
}
