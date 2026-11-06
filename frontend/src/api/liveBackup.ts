/**
 * 라이브 levels 보드 전체 백업 · 복원 API (backend/app/api/routes/live_backup.py, app/core/live_backup.py).
 * 백업 = 보드 전체 읽기 1회(쓰기 없음) → backend/data/live_backup/*.json.gz (추가만, 삭제 없음).
 * 복원 = 미리보기(쓰기 없음) → 사람이 확인 문구 "복원" 입력 → 실행(행별 update new=0).
 */
import apiClient from './client';

export interface LiveBackupSummary {
  id: string;
  board: string;
  createdAt: string;
  memo: string;
  source: 'server_read' | 'file';
  rawSha256: string;
  rawBytes: number;
  rowCount: number;
  rawRowCount: number;
  rowKinds: Record<string, number>;
  complete: boolean;
  problemCount: number;
  file: string;
  fileSha256: string;
  readSeconds?: number;
  importedFrom?: string;
  fileMtime?: string;
}

export interface BackupStatus {
  last: LiveBackupSummary | null;
  ageHours?: number;
  warn: null | 'no_backup' | 'stale' | 'incomplete';
  message: string;
  dir: string;
  staleHours: number;
}

export interface JobView<T = unknown> {
  id: string;
  kind: 'backup' | 'restore';
  status: 'running' | 'done' | 'failed';
  phase: string;
  current: number;
  total: number;
  elapsed: number;
  result: T | null;
  error: string | null;
}

export interface RestoreChange {
  col: string;
  current: unknown;
  restore: unknown;
  verified: boolean;
  why: string;
}

export interface RestorePreview {
  planId: string;
  planDigest: string;
  createdAt: string;
  base: { type: 'backup' | 'snapshot'; id: string; createdAt?: string; memo?: string; source?: string; createdRows?: string[] };
  currentSource: { type: 'server' | 'backup'; id?: string };
  rowCount: number;
  columnCounts: Record<string, number>;
  unverifiedRows: number;
  missingOnServer: string[];
  missingCount: number;
  extraOnServer: string[];
  extraCount: number;
  createdByUpload: string[];
  sample: { id: string; unverified: string[]; changes: RestoreChange[] }[];
  warnings: string[];
  confirmText: string;
}

export interface RestoreResult {
  planId: string;
  ledgerSession: string;
  total: number;
  restored: number;
  verified: number;
  mismatch: number;
  failed: number;
  blocked: number;
  results: { id: string; status: string; reason?: string; mismatchCols?: string[] }[];
}

const LONG = { timeout: 300000 };

export async function getBackupStatus(): Promise<BackupStatus> {
  return (await apiClient.get('/live-backup/status')).data;
}

export async function listBackups(): Promise<{ backups: LiveBackupSummary[]; dir: string }> {
  return (await apiClient.get('/live-backup/backups')).data;
}

export async function startBackup(memo: string): Promise<JobView<LiveBackupSummary>> {
  return (await apiClient.post('/live-backup/backups/start', { memo })).data;
}

export async function getJob<T>(jobId: string): Promise<JobView<T>> {
  return (await apiClient.get(`/live-backup/jobs/${jobId}`)).data;
}

export async function previewRestore(req: {
  base: { type: 'backup' | 'snapshot'; id: string };
  scope_snapshot?: string; q?: string; columns?: string[]; current_backup?: string;
}): Promise<RestorePreview> {
  return (await apiClient.post('/live-backup/restore/preview', req, LONG)).data;
}

export async function executeRestore(req: {
  plan_id: string; plan_digest: string; confirm_text: string; allow_unverified?: boolean; sleep_ms?: number;
}): Promise<JobView<RestoreResult>> {
  return (await apiClient.post('/live-backup/restore/execute', req)).data;
}

/** 작업이 끝날 때까지 폴링. onTick 으로 진행률 표시. */
export async function waitJob<T>(jobId: string, onTick: (j: JobView<T>) => void, intervalMs = 1000): Promise<JobView<T>> {
  for (;;) {
    const j = await getJob<T>(jobId);
    onTick(j);
    if (j.status !== 'running') return j;
    await new Promise(r => setTimeout(r, intervalMs));
  }
}
