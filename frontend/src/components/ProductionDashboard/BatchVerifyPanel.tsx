/**
 * BatchVerifyPanel
 * 생성된 레벨의 사후 배치 검증
 * 시뮬레이션 스킵(빠른 생성) 후 검증용
 */

import { useState, useEffect, useMemo } from 'react';
import { Button } from '../ui';
import { CheckCircle, XCircle, PlayCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { ProductionLevel } from '../../types/production';
import { getProductionLevelsByBatch, updateProductionLevel } from '../../storage/productionStorage';
import { batchVerifyLevels, BatchVerifyResultItem } from '../../api/analyze';

interface BatchVerifyPanelProps {
  batchId: string;
  onComplete: () => void;
  onStatsUpdate: () => void;
}

export function BatchVerifyPanel({ batchId, onComplete, onStatsUpdate }: BatchVerifyPanelProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [results, setResults] = useState<Map<string, BatchVerifyResultItem>>(new Map());
  const [verifyProgress, setVerifyProgress] = useState({ current: 0, total: 0 });

  // 검증 설정
  const [config, setConfig] = useState({
    iterations: 20,
    tolerance: 15.0,
    useCoreBotOnly: true,
    batchSize: 10, // 한 번에 검증할 레벨 수
  });

  // 미검증 레벨만 로드
  useEffect(() => {
    loadUnverifiedLevels();
  }, [batchId]);

  const loadUnverifiedLevels = async () => {
    setIsLoading(true);
    try {
      const allLevels = await getProductionLevelsByBatch(batchId);
      // 아직 검증되지 않은 레벨 (bot_clear_rates가 없거나 비어있는 레벨)
      const unverified = allLevels.filter(
        l => !l.meta.bot_clear_rates || Object.keys(l.meta.bot_clear_rates).length === 0
      );
      setLevels(unverified);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 검증 통계
  const stats = useMemo(() => {
    const total = levels.length;
    const verified = results.size;
    const passed = Array.from(results.values()).filter(r => r.passed).length;
    const failed = verified - passed;
    return { total, verified, passed, failed, remaining: total - verified };
  }, [levels, results]);

  // 배치 검증 실행
  const runBatchVerify = async () => {
    if (levels.length === 0) return;

    setIsVerifying(true);
    setVerifyProgress({ current: 0, total: levels.length });

    try {
      // 배치 단위로 처리
      for (let i = 0; i < levels.length; i += config.batchSize) {
        const batch = levels.slice(i, i + config.batchSize);

        const verifyItems = batch.map(level => ({
          level_json: level.level_json,
          level_id: `level_${level.meta.level_number}`,
          target_difficulty: level.meta.target_difficulty,
        }));

        const response = await batchVerifyLevels(verifyItems, {
          iterations: config.iterations,
          tolerance: config.tolerance,
          useCoreBotOnly: config.useCoreBotOnly,
        });

        // 결과 저장
        const newResults = new Map(results);
        for (const result of response.results) {
          newResults.set(result.level_id, result);

          // DB 업데이트 - 검증 결과 저장
          const levelNum = parseInt(result.level_id.replace('level_', ''));
          const level = batch.find(l => l.meta.level_number === levelNum);
          if (level) {
            // [v15.14] bot_clear_rates - novice/casual은 optional
            const botRates = {
              average: result.bot_clear_rates['average'] ?? 0,
              expert: result.bot_clear_rates['expert'] ?? 0,
              optimal: result.bot_clear_rates['optimal'] ?? 0,
            };
            await updateProductionLevel(batchId, level.meta.level_number, {
              bot_clear_rates: botRates,
              target_clear_rates: result.target_clear_rates,
              match_score: result.match_score,
              verified: true,
              verification_passed: result.passed,
            });
          }
        }
        setResults(newResults);
        setVerifyProgress({ current: Math.min(i + config.batchSize, levels.length), total: levels.length });
      }

      onStatsUpdate();
    } catch (err) {
      console.error('Batch verification failed:', err);
    } finally {
      setIsVerifying(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
        <span className="ml-2">레벨 로딩 중...</span>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">배치 검증</h3>
        <div className="text-sm text-gray-500">
          미검증: {stats.remaining}개 / 전체: {stats.total}개
        </div>
      </div>

      {/* 설정 */}
      <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-4 space-y-3">
        <h4 className="font-medium text-sm">검증 설정</h4>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">시뮬레이션 횟수</label>
            <input
              type="number"
              value={config.iterations}
              onChange={(e) => setConfig(c => ({ ...c, iterations: parseInt(e.target.value) || 20 }))}
              className="w-full px-2 py-1 text-sm border rounded"
              min={3}
              max={100}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">허용 오차 (%)</label>
            <input
              type="number"
              value={config.tolerance}
              onChange={(e) => setConfig(c => ({ ...c, tolerance: parseFloat(e.target.value) || 15 }))}
              className="w-full px-2 py-1 text-sm border rounded"
              min={1}
              max={50}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">배치 크기</label>
            <input
              type="number"
              value={config.batchSize}
              onChange={(e) => setConfig(c => ({ ...c, batchSize: parseInt(e.target.value) || 10 }))}
              className="w-full px-2 py-1 text-sm border rounded"
              min={1}
              max={50}
            />
          </div>
          <div className="flex items-center">
            <input
              type="checkbox"
              id="useCoreBots"
              checked={config.useCoreBotOnly}
              onChange={(e) => setConfig(c => ({ ...c, useCoreBotOnly: e.target.checked }))}
              className="mr-2"
            />
            <label htmlFor="useCoreBots" className="text-sm">코어 봇만 사용 (빠름)</label>
          </div>
        </div>
      </div>

      {/* 진행률 */}
      {isVerifying && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>검증 진행 중...</span>
            <span>{verifyProgress.current} / {verifyProgress.total}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className="bg-blue-500 h-2 rounded-full transition-all"
              style={{ width: `${(verifyProgress.current / verifyProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* 통계 */}
      {stats.verified > 0 && (
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 text-center">
            <CheckCircle className="w-5 h-5 text-green-500 mx-auto mb-1" />
            <div className="text-lg font-bold text-green-600">{stats.passed}</div>
            <div className="text-xs text-gray-500">통과</div>
          </div>
          <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3 text-center">
            <XCircle className="w-5 h-5 text-red-500 mx-auto mb-1" />
            <div className="text-lg font-bold text-red-600">{stats.failed}</div>
            <div className="text-xs text-gray-500">실패</div>
          </div>
          <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 text-center">
            <AlertTriangle className="w-5 h-5 text-gray-400 mx-auto mb-1" />
            <div className="text-lg font-bold text-gray-600">{stats.remaining}</div>
            <div className="text-xs text-gray-500">미검증</div>
          </div>
        </div>
      )}

      {/* 실패 레벨 목록 */}
      {stats.failed > 0 && (
        <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3">
          <h4 className="font-medium text-sm text-red-700 mb-2">실패한 레벨 ({stats.failed}개)</h4>
          <div className="max-h-32 overflow-y-auto text-xs space-y-1">
            {Array.from(results.entries())
              .filter(([_, r]) => !r.passed)
              .map(([id, r]) => (
                <div key={id} className="flex justify-between">
                  <span>{id}</span>
                  <span className="text-red-600">{r.issues.join(', ') || `gap: ${r.max_gap.toFixed(1)}%`}</span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <Button
          onClick={runBatchVerify}
          disabled={isVerifying || stats.remaining === 0}
          className="flex-1"
        >
          {isVerifying ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              검증 중...
            </>
          ) : (
            <>
              <PlayCircle className="w-4 h-4 mr-2" />
              {stats.remaining > 0 ? `${stats.remaining}개 레벨 검증` : '검증 완료'}
            </>
          )}
        </Button>
        {stats.verified === stats.total && stats.total > 0 && (
          <Button onClick={onComplete} variant="primary">
            완료
          </Button>
        )}
      </div>
    </div>
  );
}
