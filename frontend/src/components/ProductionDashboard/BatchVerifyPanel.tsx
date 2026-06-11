/**
 * BatchVerifyPanel
 * 생성된 레벨의 사후 배치 검증
 * [v15.35] 검증 실패 시 자동 재생성 기능 추가
 */

import { useState, useEffect, useMemo } from 'react';
import { Button } from '../ui';
import { CheckCircle, XCircle, PlayCircle, AlertTriangle, Loader2, RefreshCw, Zap, AlignCenter } from 'lucide-react';
import { ProductionLevel } from '../../types/production';
import { LevelJSON } from '../../types';
import { getProductionLevelsByBatch, updateProductionLevel, saveProductionLevel } from '../../storage/productionStorage';
import {
  batchVerifyLevels,
  batchVerifyWithRegeneration,
  BatchVerifyResultItem,
  BatchVerifyRegenerateResultItem,
  fixCentering,
} from '../../api/analyze';

interface BatchVerifyPanelProps {
  batchId: string;
  onComplete: () => void;
  onStatsUpdate: () => void;
}

export function BatchVerifyPanel({ batchId, onComplete, onStatsUpdate }: BatchVerifyPanelProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [isVerifying, setIsVerifying] = useState(false);
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [results, setResults] = useState<Map<string, BatchVerifyResultItem | BatchVerifyRegenerateResultItem>>(new Map());
  const [verifyProgress, setVerifyProgress] = useState({ current: 0, total: 0, phase: 'verify' as 'verify' | 'regenerate' | 'centering' });
  // [v15.40] 중앙정렬 수정 상태
  const [centeringResult, setCenteringResult] = useState<{ total: number; modified: number; timeMs: number } | null>(null);

  // 검증 설정
  const [config, setConfig] = useState({
    iterations: 20,
    tolerance: 15.0,
    useCoreBotOnly: true,
    batchSize: 10, // 한 번에 검증할 레벨 수
    // [v15.35] 재생성 옵션
    enableRegeneration: true,
    maxRegenerationRetries: 3,
    regenerationIterations: 30,
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
    const regenerated = Array.from(results.values()).filter(
      r => 'regenerated' in r && r.regenerated
    ).length;
    return { total, verified, passed, failed, remaining: total - verified, regenerated };
  }, [levels, results]);

  // [v15.35] 재생성 지원 배치 검증 실행
  const runBatchVerifyWithRegeneration = async () => {
    if (levels.length === 0) return;

    setIsVerifying(true);
    setVerifyProgress({ current: 0, total: levels.length, phase: 'verify' });

    try {
      // 배치 단위로 처리
      for (let i = 0; i < levels.length; i += config.batchSize) {
        const batch = levels.slice(i, i + config.batchSize);

        const verifyItems = batch.map(level => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const json = level.level_json as any;
          return {
            level_json: level.level_json,
            level_id: `level_${level.meta.level_number}`,
            target_difficulty: level.meta.target_difficulty,
            level_number: level.meta.level_number,
            // 재생성에 필요한 원본 파라미터 (level_json에서 추출)
            grid_size: json.grid_size as [number, number] | undefined,
            max_layers: json.layer_count as number | undefined,
            symmetry_mode: level.meta.pattern_type ? undefined : json.symmetry_mode as string | undefined,
            pattern_type: level.meta.pattern_type as string | undefined,
            // [v15.40] 재생성 시 패턴 모양 보존
            pattern_index: (level.meta as unknown as Record<string, unknown>).pattern_index as number | undefined ?? json.pattern_index as number | undefined,
          };
        });

        // [v15.35] 재생성 지원 API 호출
        const response = await batchVerifyWithRegeneration(verifyItems, {
          iterations: config.iterations,
          tolerance: config.tolerance,
          useCoreBotOnly: config.useCoreBotOnly,
          enableRegeneration: config.enableRegeneration,
          maxRegenerationRetries: config.maxRegenerationRetries,
          regenerationTolerance: config.tolerance,
          regenerationIterations: config.regenerationIterations,
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

            // [v15.35] 재생성된 경우 새 레벨 JSON으로 교체
            const regenResult = result as BatchVerifyRegenerateResultItem;
            if (regenResult.regenerated && regenResult.new_level_json) {
              // 새 레벨로 완전히 교체
              await saveProductionLevel(batchId, {
                meta: {
                  ...level.meta,
                  bot_clear_rates: botRates,
                  target_clear_rates: result.target_clear_rates,
                  match_score: result.match_score,
                  verified: true,
                  verification_passed: result.passed,
                  // 재생성 정보 추가
                  regenerated: true,
                  regeneration_attempts: regenResult.regeneration_attempts,
                },
                level_json: regenResult.new_level_json,
              });
            } else {
              // 기존 레벨 메타 업데이트
              await updateProductionLevel(batchId, level.meta.level_number, {
                bot_clear_rates: botRates,
                target_clear_rates: result.target_clear_rates,
                match_score: result.match_score,
                verified: true,
                verification_passed: result.passed,
              });
            }
          }
        }
        setResults(newResults);
        setVerifyProgress({
          current: Math.min(i + config.batchSize, levels.length),
          total: levels.length,
          phase: response.regenerated_count > 0 ? 'regenerate' : 'verify',
        });
      }

      onStatsUpdate();
    } catch (err) {
      console.error('Batch verification failed:', err);
    } finally {
      setIsVerifying(false);
    }
  };

  // [v15.40] 중앙정렬만 수정 (재생성 없음)
  const runFixCentering = async () => {
    const allLevels = await getProductionLevelsByBatch(batchId);
    if (allLevels.length === 0) return;

    setIsVerifying(true);
    setCenteringResult(null);
    setVerifyProgress({ current: 0, total: allLevels.length, phase: 'centering' });

    let totalModified = 0;
    const batchSz = config.batchSize;

    try {
      for (let i = 0; i < allLevels.length; i += batchSz) {
        const batch = allLevels.slice(i, i + batchSz);
        const levelJsons = batch.map(l => ({
          ...(l.level_json as unknown as Record<string, unknown>),
          level_number: l.meta.level_number,
        }));

        const response = await fixCentering(levelJsons);

        for (const item of response.results) {
          if (item.was_modified) {
            const originalLevel = batch.find(l => l.meta.level_number === item.level_number);
            if (originalLevel) {
              await saveProductionLevel(batchId, {
                ...originalLevel,
                level_json: item.level_json as unknown as LevelJSON,
              });
              totalModified++;
            }
          }
        }

        setVerifyProgress({ current: Math.min(i + batchSz, allLevels.length), total: allLevels.length, phase: 'centering' });
      }

      setCenteringResult({ total: allLevels.length, modified: totalModified, timeMs: 0 });
      await onStatsUpdate();
    } catch (error) {
      console.error('[FixCentering] Error:', error);
    } finally {
      setIsVerifying(false);
    }
  };

  // 기존 검증 (재생성 없음)
  const runBatchVerify = async () => {
    if (levels.length === 0) return;

    setIsVerifying(true);
    setVerifyProgress({ current: 0, total: levels.length, phase: 'verify' });

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
        setVerifyProgress({ current: Math.min(i + config.batchSize, levels.length), total: levels.length, phase: 'verify' });
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
              className="w-full px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600"
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
              className="w-full px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600"
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
              className="w-full px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600"
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
            <label htmlFor="useCoreBots" className="text-sm">코어 봇만 사용</label>
          </div>
        </div>

        {/* [v15.35] 재생성 옵션 */}
        <div className="border-t border-gray-200 dark:border-gray-700 pt-3 mt-3">
          <div className="flex items-center mb-2">
            <input
              type="checkbox"
              id="enableRegeneration"
              checked={config.enableRegeneration}
              onChange={(e) => setConfig(c => ({ ...c, enableRegeneration: e.target.checked }))}
              className="mr-2"
            />
            <label htmlFor="enableRegeneration" className="text-sm font-medium flex items-center">
              <RefreshCw className="w-4 h-4 mr-1 text-blue-500" />
              실패 시 자동 재생성
            </label>
          </div>

          {config.enableRegeneration && (
            <div className="grid grid-cols-2 gap-4 mt-2">
              <div>
                <label className="block text-xs text-gray-500 mb-1">최대 재생성 횟수</label>
                <input
                  type="number"
                  value={config.maxRegenerationRetries}
                  onChange={(e) => setConfig(c => ({ ...c, maxRegenerationRetries: parseInt(e.target.value) || 3 }))}
                  className="w-full px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600"
                  min={1}
                  max={10}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">재검증 시뮬레이션</label>
                <input
                  type="number"
                  value={config.regenerationIterations}
                  onChange={(e) => setConfig(c => ({ ...c, regenerationIterations: parseInt(e.target.value) || 30 }))}
                  className="w-full px-2 py-1 text-sm border rounded dark:bg-gray-700 dark:border-gray-600"
                  min={10}
                  max={100}
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 진행률 */}
      {isVerifying && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span className="flex items-center">
              {verifyProgress.phase === 'regenerate' ? (
                <>
                  <RefreshCw className="w-4 h-4 mr-1 animate-spin text-blue-500" />
                  재생성 중...
                </>
              ) : (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  검증 중...
                </>
              )}
            </span>
            <span>{verifyProgress.current} / {verifyProgress.total}</span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${
                verifyProgress.phase === 'regenerate' ? 'bg-blue-500' : 'bg-green-500'
              }`}
              style={{ width: `${(verifyProgress.current / verifyProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* 통계 */}
      {stats.verified > 0 && (
        <div className="grid grid-cols-4 gap-3">
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
          <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3 text-center">
            <RefreshCw className="w-5 h-5 text-blue-500 mx-auto mb-1" />
            <div className="text-lg font-bold text-blue-600">{stats.regenerated}</div>
            <div className="text-xs text-gray-500">재생성</div>
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
          <h4 className="font-medium text-sm text-red-700 dark:text-red-400 mb-2">
            실패한 레벨 ({stats.failed}개)
          </h4>
          <div className="max-h-32 overflow-y-auto text-xs space-y-1">
            {Array.from(results.entries())
              .filter(([_, r]) => !r.passed)
              .map(([id, r]) => (
                <div key={id} className="flex justify-between">
                  <span>{id}</span>
                  <span className="text-red-600 dark:text-red-400">
                    {r.issues.join(', ') || `gap: ${r.max_gap.toFixed(1)}%`}
                  </span>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* 재생성된 레벨 목록 */}
      {stats.regenerated > 0 && (
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3">
          <h4 className="font-medium text-sm text-blue-700 dark:text-blue-400 mb-2">
            재생성된 레벨 ({stats.regenerated}개)
          </h4>
          <div className="max-h-32 overflow-y-auto text-xs space-y-1">
            {Array.from(results.entries())
              .filter(([_, r]) => 'regenerated' in r && r.regenerated)
              .map(([id, r]) => {
                const regenResult = r as BatchVerifyRegenerateResultItem;
                return (
                  <div key={id} className="flex justify-between">
                    <span>{id}</span>
                    <span className="text-blue-600 dark:text-blue-400">
                      {regenResult.regeneration_attempts}회 시도,
                      score: {regenResult.match_score.toFixed(1)}%
                      {regenResult.passed ? ' ✓' : ' ✗'}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* [v15.40] 중앙정렬 수정 결과 */}
      {centeringResult && (
        <div className="bg-blue-50 dark:bg-blue-900/20 rounded-lg p-3">
          <div className="flex items-center gap-2 mb-1">
            <AlignCenter className="w-4 h-4 text-blue-500" />
            <h4 className="font-medium text-sm text-blue-700 dark:text-blue-400">중앙정렬 완료</h4>
          </div>
          <div className="text-xs text-gray-600 dark:text-gray-400">
            전체 {centeringResult.total}개 중 {centeringResult.modified}개 수정됨
          </div>
        </div>
      )}

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        {/* [v15.40] 중앙정렬 수정 버튼 */}
        <Button
          onClick={runFixCentering}
          disabled={isVerifying}
          variant="secondary"
          className="shrink-0"
        >
          {isVerifying && verifyProgress.phase === 'centering' ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              정렬 중...
            </>
          ) : (
            <>
              <AlignCenter className="w-4 h-4 mr-2" />
              중앙정렬
            </>
          )}
        </Button>
        {config.enableRegeneration ? (
          <Button
            onClick={runBatchVerifyWithRegeneration}
            disabled={isVerifying || stats.remaining === 0}
            className="flex-1"
          >
            {isVerifying ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                처리 중...
              </>
            ) : (
              <>
                <Zap className="w-4 h-4 mr-2" />
                {stats.remaining > 0 ? `${stats.remaining}개 검증 + 재생성` : '검증 완료'}
              </>
            )}
          </Button>
        ) : (
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
        )}
        {stats.verified === stats.total && stats.total > 0 && (
          <Button onClick={onComplete} variant="primary">
            완료
          </Button>
        )}
      </div>
    </div>
  );
}
