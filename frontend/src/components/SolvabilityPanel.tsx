/**
 * 솔버블 검증 탭 — A* 완전탐색 솔버로 프로덕션 배치의 '클리어 가능성'을 독립 감사.
 *
 * 봇 난이도 검증(BatchVerifyPanel)과 달리 "풀 수 있는 구조인가"를 양방향 확정한다:
 *   PROVEN_SOLVABLE   클리어 경로 발견 (확실히 풀림)
 *   PROVEN_IMPOSSIBLE ÷3 위반 즉시 / 완전탐색이 경로 없음 확정 (구조 데드락)
 *   UNCERTAIN         노드·시간 예산 초과 (큰 레벨 — 휴리스틱 참조)
 *
 * 백엔드: /api/analyze/solvability/batch (프로세스풀 병렬). 프론트는 청크 단위로 호출해 진행도 표시.
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  listProductionBatches,
  getProductionLevelsByBatch,
} from '../storage/productionStorage';
import type { ProductionBatch, ProductionLevel } from '../types/production';
import {
  batchAnalyzeSolvability,
  type SolvabilityVerdict,
} from '../api/analyze';
import { useUIStore } from '../stores/uiStore';

interface SolvRow {
  level_number: number;
  grade: string;
  target_difficulty: number | null;
  verdict: SolvabilityVerdict;
  reason: string;
  moves_to_clear: number | null;
  nodes_expanded: number;
  divisibility_violation: Record<string, number> | null;
  unsupported_gimmicks?: string[] | null;
  error?: string;
}

const VERDICT_STYLE: Record<SolvabilityVerdict, { label: string; color: string; bg: string }> = {
  PROVEN_SOLVABLE: { label: '✅ 풀림', color: 'text-green-400', bg: 'bg-green-900/30' },
  PROVEN_IMPOSSIBLE: { label: '❌ 불가능', color: 'text-red-400', bg: 'bg-red-900/30' },
  UNCERTAIN: { label: '❔ 미확정', color: 'text-yellow-400', bg: 'bg-yellow-900/20' },
};

export function SolvabilityPanel() {
  const { addNotification } = useUIStore();

  const [batches, setBatches] = useState<ProductionBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState('');
  const [batchLevelCount, setBatchLevelCount] = useState(0);

  const [useRange, setUseRange] = useState(true);
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(50);

  const [timeBudget, setTimeBudget] = useState(3);
  const [nodeBudget, setNodeBudget] = useState(40000);

  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [avgMsPerLevel, setAvgMsPerLevel] = useState(0);
  const cancelRef = useRef(false);

  const [rows, setRows] = useState<SolvRow[]>([]);
  const [onlyImpossible, setOnlyImpossible] = useState(false);

  // 배치 목록 로드
  useEffect(() => {
    listProductionBatches()
      .then(list => {
        setBatches(list);
        if (list.length > 0 && !selectedBatchId) setSelectedBatchId(list[0].id);
      })
      .catch(() => addNotification('error', '프로덕션 배치 목록을 불러올 수 없습니다'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 배치 변경 시 레벨 수 갱신
  useEffect(() => {
    if (!selectedBatchId) return;
    getProductionLevelsByBatch(selectedBatchId)
      .then(levels => setBatchLevelCount(levels.length))
      .catch(() => setBatchLevelCount(0));
  }, [selectedBatchId]);

  const handleRun = useCallback(async () => {
    if (!selectedBatchId || isRunning) return;

    let levels: ProductionLevel[];
    try {
      levels = await getProductionLevelsByBatch(selectedBatchId);
    } catch {
      addNotification('error', '배치 레벨을 불러올 수 없습니다');
      return;
    }

    const targets = useRange
      ? levels.filter(l => l.meta.level_number >= rangeStart && l.meta.level_number <= rangeEnd)
      : levels;

    if (targets.length === 0) {
      addNotification('warning', '검증할 레벨이 없습니다 (범위 확인)');
      return;
    }

    setIsRunning(true);
    cancelRef.current = false;
    setRows([]);
    setProgress({ current: 0, total: targets.length });
    setAvgMsPerLevel(0);

    const chunkSize = 16; // 진행도 + 타임아웃 관리용
    const chunks: ProductionLevel[][] = [];
    for (let i = 0; i < targets.length; i += chunkSize) {
      chunks.push(targets.slice(i, i + chunkSize));
    }

    let elapsedSum = 0;
    let done = 0;
    const newRows: SolvRow[] = [];

    for (const chunk of chunks) {
      if (cancelRef.current) break;
      const metaByLevel = new Map(chunk.map(l => [l.meta.level_number, l.meta]));
      try {
        const response = await batchAnalyzeSolvability(
          chunk.map(l => ({ level_number: l.meta.level_number, level_json: l.level_json })),
          { timeBudgetS: timeBudget, nodeBudget },
        );
        elapsedSum += response.elapsed_ms;
        for (const r of response.results) {
          const meta = metaByLevel.get(r.level_number);
          newRows.push({
            level_number: r.level_number,
            grade: meta?.grade || '-',
            target_difficulty: meta?.target_difficulty ?? null,
            verdict: r.verdict,
            reason: r.reason,
            moves_to_clear: r.moves_to_clear,
            nodes_expanded: r.nodes_expanded,
            divisibility_violation: r.divisibility_violation,
            unsupported_gimmicks: r.unsupported_gimmicks,
            error: r.error || undefined,
          });
        }
      } catch (err) {
        for (const l of chunk) {
          newRows.push({
            level_number: l.meta.level_number,
            grade: l.meta.grade,
            target_difficulty: l.meta.target_difficulty ?? null,
            verdict: 'UNCERTAIN',
            reason: '요청 오류',
            moves_to_clear: null,
            nodes_expanded: 0,
            divisibility_violation: null,
            error: (err as Error).message,
          });
        }
      }
      done += chunk.length;
      setProgress({ current: done, total: targets.length });
      setAvgMsPerLevel(done > 0 ? elapsedSum / done : 0);
      newRows.sort((a, b) => a.level_number - b.level_number);
      setRows([...newRows]);
    }

    setIsRunning(false);
    if (cancelRef.current) addNotification('warning', `중단됨: ${done}/${targets.length}개 완료`);
    else addNotification('success', `솔버블 검증 완료: ${done}개 레벨`);
  }, [selectedBatchId, isRunning, useRange, rangeStart, rangeEnd, timeBudget, nodeBudget, addNotification]);

  const summary = useMemo(() => {
    const s = { solvable: 0, impossible: 0, uncertain: 0 };
    for (const r of rows) {
      if (r.verdict === 'PROVEN_SOLVABLE') s.solvable++;
      else if (r.verdict === 'PROVEN_IMPOSSIBLE') s.impossible++;
      else s.uncertain++;
    }
    return s;
  }, [rows]);

  const impossibleLevels = useMemo(
    () => rows.filter(r => r.verdict === 'PROVEN_IMPOSSIBLE').map(r => r.level_number),
    [rows],
  );

  const gimmickUncertain = useMemo(
    () => rows.filter(r => r.verdict === 'UNCERTAIN' && r.unsupported_gimmicks && r.unsupported_gimmicks.length > 0)
      .map(r => r.level_number),
    [rows],
  );

  const visibleRows = onlyImpossible ? rows.filter(r => r.verdict === 'PROVEN_IMPOSSIBLE') : rows;

  const etaSec = isRunning && avgMsPerLevel > 0
    ? Math.round(((progress.total - progress.current) * avgMsPerLevel) / 1000)
    : 0;

  return (
    <div className="space-y-4">
      <div className="bg-gray-800 rounded-lg p-4">
        <h2 className="text-lg font-semibold text-white mb-1">🧩 솔버블 검증 (A* 완전탐색)</h2>
        <p className="text-xs text-gray-400 mb-4">
          프로덕션 배치의 각 레벨이 <span className="text-green-400">실제로 풀 수 있는 구조</span>인지 양방향 확정 판정합니다.
          봇 난이도 검증과 독립적인 구조 감사입니다. <span className="text-red-400">불가능</span> 레벨은 재생성 대상입니다.
        </p>

        {/* 배치 선택 + 범위 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">프로덕션 배치</label>
            <select
              className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5"
              value={selectedBatchId}
              onChange={e => setSelectedBatchId(e.target.value)}
              disabled={isRunning}
            >
              {batches.length === 0 && <option value="">배치 없음</option>}
              {batches.map(b => (
                <option key={b.id} value={b.id}>{b.name} ({b.id.slice(0, 12)})</option>
              ))}
            </select>
            <div className="text-[11px] text-gray-500 mt-1">총 {batchLevelCount}개 레벨</div>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              <input type="checkbox" className="mr-1 align-middle" checked={useRange}
                onChange={e => setUseRange(e.target.checked)} disabled={isRunning} />
              레벨 범위 지정
            </label>
            <div className="flex items-center gap-2">
              <input type="number" min={1} className="w-20 bg-gray-700 text-white text-sm rounded px-2 py-1.5 disabled:opacity-40"
                value={rangeStart} onChange={e => setRangeStart(Number(e.target.value))} disabled={isRunning || !useRange} />
              <span className="text-gray-500 text-xs">~</span>
              <input type="number" min={1} className="w-20 bg-gray-700 text-white text-sm rounded px-2 py-1.5 disabled:opacity-40"
                value={rangeEnd} onChange={e => setRangeEnd(Number(e.target.value))} disabled={isRunning || !useRange} />
              <span className="text-[11px] text-gray-500">큰 배치는 범위 지정 권장</span>
            </div>
          </div>
        </div>

        {/* 예산 */}
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <label className="block text-xs text-gray-400 mb-1">레벨당 시간 예산 (초)</label>
            <input type="number" min={0.5} max={60} step={0.5}
              className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5"
              value={timeBudget} onChange={e => setTimeBudget(Number(e.target.value))} disabled={isRunning} />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">노드 예산</label>
            <input type="number" min={1000} max={2000000} step={10000}
              className="w-full bg-gray-700 text-white text-sm rounded px-2 py-1.5"
              value={nodeBudget} onChange={e => setNodeBudget(Number(e.target.value))} disabled={isRunning} />
          </div>
        </div>

        {/* 실행 */}
        <div className="flex items-center gap-2">
          {!isRunning ? (
            <button onClick={handleRun} disabled={!selectedBatchId}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm rounded font-medium">
              ▶ 솔버블 검증 시작
            </button>
          ) : (
            <button onClick={() => { cancelRef.current = true; }}
              className="px-4 py-2 bg-red-600 hover:bg-red-500 text-white text-sm rounded font-medium">
              ■ 중단
            </button>
          )}
          {isRunning && (
            <span className="text-xs text-gray-400">
              {progress.current}/{progress.total}
              {etaSec > 0 && ` · 남은 시간 ~${etaSec}s`}
            </span>
          )}
        </div>
        {isRunning && (
          <div className="mt-2 h-1.5 bg-gray-700 rounded overflow-hidden">
            <div className="h-full bg-blue-500 transition-all"
              style={{ width: `${progress.total ? (progress.current / progress.total) * 100 : 0}%` }} />
          </div>
        )}
      </div>

      {/* 요약 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-green-900/30 rounded p-3">
              <div className="text-2xl font-bold text-green-400">{summary.solvable}</div>
              <div className="text-xs text-gray-400">✅ 풀림</div>
            </div>
            <div className="bg-red-900/30 rounded p-3">
              <div className="text-2xl font-bold text-red-400">{summary.impossible}</div>
              <div className="text-xs text-gray-400">❌ 불가능 (재생성 대상)</div>
            </div>
            <div className="bg-yellow-900/20 rounded p-3">
              <div className="text-2xl font-bold text-yellow-400">{summary.uncertain}</div>
              <div className="text-xs text-gray-400">❔ 미확정 (예산 초과)</div>
            </div>
          </div>
          {impossibleLevels.length > 0 && (
            <div className="mt-3 text-xs text-red-300 bg-red-900/20 rounded p-2">
              <span className="font-medium">불가능 레벨:</span> {impossibleLevels.join(', ')}
              <div className="text-[11px] text-gray-500 mt-1">
                프로덕션 탭에서 해당 레벨을 재생성하세요. (÷3 위반은 생성기 수정으로 신규 생성분은 발생하지 않음 — 저장된 구버전 레벨일 수 있음)
              </div>
            </div>
          )}
          {summary.uncertain > 0 && (
            <div className="mt-2 text-[11px] text-gray-500">
              ❔ 미확정 = 불가능이 아님. ① 상태공간이 커 예산 초과(시간/노드 예산 ↑ 시 일부 확정)
              {gimmickUncertain.length > 0 && (
                <span className="text-yellow-500">
                  {' '}② 솔버 미지원 기믹 포함({gimmickUncertain.length}개) — frog/teleport/bomb 등은 솔버가 완전 모델링 못 해
                  불가능 단정을 보류합니다(실제론 풀릴 수 있음). 해당 레벨: {gimmickUncertain.join(', ')}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* 결과 테이블 */}
      {rows.length > 0 && (
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-white">결과 ({visibleRows.length})</h3>
            <label className="text-xs text-gray-400">
              <input type="checkbox" className="mr-1 align-middle" checked={onlyImpossible}
                onChange={e => setOnlyImpossible(e.target.checked)} />
              불가능만 보기
            </label>
          </div>
          <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="text-gray-400 sticky top-0 bg-gray-800">
                <tr className="border-b border-gray-700">
                  <th className="text-left py-1.5 px-2">레벨</th>
                  <th className="text-left py-1.5 px-2">등급</th>
                  <th className="text-left py-1.5 px-2">판정</th>
                  <th className="text-right py-1.5 px-2">수순</th>
                  <th className="text-right py-1.5 px-2">노드</th>
                  <th className="text-left py-1.5 px-2">사유</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map(r => {
                  const vs = VERDICT_STYLE[r.verdict];
                  return (
                    <tr key={r.level_number} className={`border-b border-gray-700/50 ${vs.bg}`}>
                      <td className="py-1.5 px-2 text-white font-medium">{r.level_number}</td>
                      <td className="py-1.5 px-2 text-gray-300">{r.grade}</td>
                      <td className={`py-1.5 px-2 font-medium ${vs.color}`}>{vs.label}</td>
                      <td className="py-1.5 px-2 text-right text-gray-400">{r.moves_to_clear ?? '-'}</td>
                      <td className="py-1.5 px-2 text-right text-gray-500">{r.nodes_expanded.toLocaleString()}</td>
                      <td className="py-1.5 px-2 text-gray-400 max-w-[360px] truncate" title={r.reason}>{r.reason}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
