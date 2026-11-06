/**
 * 허들 구간 추천 API (backend/app/api/routes/hurdle_rec.py, app/core/hurdle_range_rec.py).
 * 게임 레포 tools/dda_hurdle_mix/range_rec/run.sh 를 별도 프로세스로 실행 → 결과를 정규화해 반환.
 * 게임부스트 접속·쓰기 없음. 결과 문자열은 사람이 실시간 설정 hurdleActiveLevels 에 복붙.
 */
import apiClient from './client';

export type Preset = 'hard' | 'harder' | string;
export type PlanName = 'conservative' | 'aggressive';

export interface ToolInfo {
  gameRepo: string;
  toolDir: string;
  runSh: string;
  exists: boolean;
  defaultVersions: string[];
  platform: string | null;
  afDir: string;
  running: JobView | null;
}

export interface JobView {
  id: string;
  status: 'running' | 'done' | 'failed' | 'stopped' | 'idle';
  pid?: number;
  startedAt?: string;
  finishedAt?: string | null;
  params?: { since: string | null; until: string | null; versions: string[]; keepDdaVar: boolean };
  memo?: string;
  outDir?: string;
  exitCode?: number | null;
  phase?: string;
  pct?: number | null;
  toolState?: string | null;
  toolStatus?: Record<string, unknown> | null;
  logTail?: string[];
  elapsedSec?: number;
}

export interface PlanString {
  grouped: string;
  legacy: string;
  groupedSource: 'tool' | 'maptool';
  items: number | null;
  legacyItems?: number | null;
  chars: number;
  legacyChars: number;
  levels: number;
  byPreset: Record<string, number>;
  withData: number | null;
  missing: number[];
  ranges: [number, number][];
  valid: boolean | null;
  groupedLegacySame: boolean | null;
  equivalent?: boolean | null;
  groupedMethod?: string | null;
  check?: StringCheck;
}

export interface StringCheck {
  pass: boolean;
  parse: { ok: boolean; parser: 'backend' | 'csharp'; parserSrc: string; format: string; bad: string[]; nBad: number;
    tokens: number; maxTokens: number; length: number; maxLength: number };
  intent: { ok: boolean; range: [number, number]; levels: number; intentLevels: number; nMismatch: number; mismatch: string;
    beyondMax: string; byPreset: Record<string, number> };
  data: { ok: boolean | null; path: string; created?: string; n?: number; nMissing?: number; missing?: string;
    unknownPresets?: string[]; note?: string; error?: string; sameAsRun?: boolean | null };
  equivalent: { ok: boolean; value: boolean | null | undefined };
}

export interface LevelRow {
  level: number;
  difficulty: number | null;
  ftRuns: number;
  actual: number | null;
  ciLo: number | null;
  ciHi: number | null;
  expDesign: number | null;
  expBot: number | null;
  expNeighbor: number | null;
  gapDesign?: number | null;
  judge?: string;
  candidate?: boolean;
  mapChanged?: boolean;
  plan: Partial<Record<PlanName, Preset | null>>;
  bandCons?: [number, number] | null;
  bandAggr?: [number, number] | null;
  single?: boolean;
  reason: string;
  excluded: string;
  excludedCodes?: string[];
}

export interface BandRow {
  start: number;
  end: number;
  actual: number | null;
  ciLo?: number | null;
  ciHi?: number | null;
  surround: number | null;
  gap: number | null;
  ftRuns: number;
  verRel?: Record<string, number>;
  passCons?: boolean;
  passAggr?: boolean;
  pass: boolean;
  reason: string;
}

export interface HurdleLevelRow {
  level: number;
  strength: string;
  runs: number;
  ftc: number | null;
  abandon: number | null;
  baseFtc: number | null;
  baseAbandon: number | null;
  removeCandidate: string;
}

export interface DiffView {
  same: boolean;
  added: string;
  removed: string;
  changed: string;
  nAdd: number;
  nRem: number;
  nChg: number;
}

export interface RecResult {
  id: string;
  source: 'maptool' | 'game';
  dir: string;
  schema: string;
  runAt: string | null;
  dataSources: {
    platform?: string;
    versions?: string[];
    since?: string | null;
    until?: string | null;
    tmin?: string;
    tmax?: string;
    runs?: number;
    files?: string[];
    skip?: Record<string, number>;
    byVersion?: Record<string, [number, number]>;
    [k: string]: unknown;
  };
  strings: Record<PlanName, PlanString>;
  levels: LevelRow[];
  bands: BandRow[];
  hurdleLevels: HurdleLevelRow[];
  diffFromPrev: { prevRunId: string | null; tool: unknown } & Partial<Record<PlanName, DiffView>>;
  reportPath: string | null;
  notes?: string[];
  removalCandidates?: unknown[];
}

export interface RunListItem {
  id: string;
  source: 'maptool' | 'game';
  dir: string;
  runAt: string | null;
  schema: string;
}

export interface RunParams {
  since?: string;
  until?: string;
  versions?: string[];
  keep_dda_var?: boolean;
  memo?: string;
}

export const hurdleRecApi = {
  info: () => apiClient.get<ToolInfo>('/hurdle-rec/info').then(r => r.data),
  run: (p: RunParams) => apiClient.post<JobView>('/hurdle-rec/run', p).then(r => r.data),
  status: (jobId?: string) => apiClient.get<JobView>('/hurdle-rec/status', { params: jobId ? { job_id: jobId } : {} }).then(r => r.data),
  stop: (jobId: string) => apiClient.post<JobView>(`/hurdle-rec/stop/${encodeURIComponent(jobId)}`).then(r => r.data),
  runs: () => apiClient.get<{ runs: RunListItem[] }>('/hurdle-rec/runs').then(r => r.data.runs),
  result: (runId?: string) => apiClient.get<RecResult>('/hurdle-rec/result', { params: runId ? { run_id: runId } : {} }).then(r => r.data),
};
