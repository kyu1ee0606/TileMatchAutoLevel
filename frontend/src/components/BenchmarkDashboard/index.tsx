/**
 * Benchmark Dashboard
 * 티어별 벤치마크 레벨 현황 및 검증 대시보드
 */

import { useState, useEffect, useCallback } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { useLevelStore } from '../../stores/levelStore';
import clsx from 'clsx';

type DifficultyTier = 'easy' | 'medium' | 'hard' | 'expert' | 'impossible';

interface BenchmarkLevel {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: DifficultyTier;
}

interface ValidationResult {
  level_id: string;
  level_name: string;
  iterations: number;
  tolerance: number;
  bot_results: {
    bot_type: string;
    expected_rate: number;
    actual_rate: number;
    deviation: number;
    status: 'PASS' | 'WARN' | 'FAIL';
    within_tolerance: boolean;
  }[];
  overall_pass: boolean;
  warnings: number;
  failures: number;
}

interface TierStats {
  tier: DifficultyTier;
  total: number;
  validated: number;
  passed: number;
  warnings: number;
  failed: number;
}

const TIER_COLORS: Record<DifficultyTier, string> = {
  easy: 'bg-green-500',
  medium: 'bg-yellow-500',
  hard: 'bg-orange-500',
  expert: 'bg-red-500',
  impossible: 'bg-purple-500',
};

const TIER_LABELS: Record<DifficultyTier, string> = {
  easy: '쉬움',
  medium: '보통',
  hard: '어려움',
  expert: '전문가',
  impossible: '불가능',
};

const BOT_LABELS: Record<string, string> = {
  novice: '스튜디',
  casual: '겸손',
  average: '보통',
  expert: '선수',
  optimal: '진행',
};

export function BenchmarkDashboard() {
  const { addNotification, setActiveTab } = useUIStore();
  const { setLevel } = useLevelStore();

  const [levels, setLevels] = useState<Record<DifficultyTier, BenchmarkLevel[]>>({
    easy: [],
    medium: [],
    hard: [],
    expert: [],
    impossible: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [selectedTier, setSelectedTier] = useState<DifficultyTier>('easy');
  const [selectedLevel, setSelectedLevel] = useState<BenchmarkLevel | null>(null);
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [tierStats, setTierStats] = useState<TierStats[]>([]);

  // Fetch benchmark levels
  const fetchLevels = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/simulate/benchmark/list');
      const data = await response.json();
      setLevels(data);

      // Calculate tier stats
      const stats: TierStats[] = (['easy', 'medium', 'hard', 'expert', 'impossible'] as DifficultyTier[]).map(tier => ({
        tier,
        total: data[tier]?.length || 0,
        validated: 0,
        passed: 0,
        warnings: 0,
        failed: 0,
      }));
      setTierStats(stats);
    } catch (error) {
      addNotification('error', '벤치마크 레벨 로드 실패');
      console.error(error);
    } finally {
      setIsLoading(false);
    }
  }, [addNotification]);

  useEffect(() => {
    fetchLevels();
  }, [fetchLevels]);

  // Validate selected level
  const handleValidate = async (levelId: string) => {
    setIsValidating(true);
    setValidationResult(null);
    try {
      const response = await fetch(`http://localhost:8000/api/simulate/benchmark/validate/${levelId}`, {
        method: 'POST',
      });
      const result = await response.json();
      setValidationResult(result);

      if (result.overall_pass) {
        addNotification('success', `${levelId} 검증 통과`);
      } else if (result.warnings > 0 && result.failures === 0) {
        addNotification('warning', `${levelId} 경고 ${result.warnings}개`);
      } else {
        addNotification('error', `${levelId} 검증 실패 (${result.failures}개 실패)`);
      }
    } catch (error) {
      addNotification('error', '검증 실행 실패');
      console.error(error);
    } finally {
      setIsValidating(false);
    }
  };

  // Load level to editor
  const handleLoadToEditor = async (levelId: string) => {
    try {
      const response = await fetch(`http://localhost:8000/api/simulate/benchmark/${levelId}`);
      const data = await response.json();
      if (data.level_json) {
        setLevel(data.level_json);
        setActiveTab('editor');
        addNotification('success', `${levelId} 에디터에 로드됨`);
      }
    } catch (error) {
      addNotification('error', '레벨 로드 실패');
      console.error(error);
    }
  };

  // Validate all levels in tier
  const handleValidateAll = async (tier: DifficultyTier) => {
    const tierLevels = levels[tier];
    if (tierLevels.length === 0) return;

    let passed = 0, warnings = 0, failed = 0;

    for (const level of tierLevels) {
      try {
        const response = await fetch(`http://localhost:8000/api/simulate/benchmark/validate/${level.id}`, {
          method: 'POST',
        });
        const result = await response.json();
        if (result.overall_pass) passed++;
        else if (result.warnings > 0 && result.failures === 0) warnings++;
        else failed++;
      } catch (error) {
        failed++;
      }
    }

    // Update stats
    setTierStats(prev => prev.map(s =>
      s.tier === tier ? { ...s, validated: tierLevels.length, passed, warnings, failed } : s
    ));

    addNotification('info', `${TIER_LABELS[tier]} 검증 완료: ${passed}/${tierLevels.length} 통과`);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-2xl">📊</span>
            <h2 className="text-xl font-bold text-white">벤치마크 대시보드</h2>
          </div>
          <Button variant="secondary" size="sm" onClick={fetchLevels}>
            🔄 새로고침
          </Button>
        </div>
      </div>

      {/* Tier Overview */}
      <div className="grid grid-cols-5 gap-3">
        {(['easy', 'medium', 'hard', 'expert', 'impossible'] as DifficultyTier[]).map(tier => {
          const tierLevel = levels[tier] || [];
          const stats = tierStats.find(s => s.tier === tier);
          return (
            <div
              key={tier}
              className={clsx(
                'bg-gray-800 rounded-lg p-4 cursor-pointer border-2 transition-all',
                selectedTier === tier ? 'border-blue-500' : 'border-transparent hover:border-gray-600'
              )}
              onClick={() => setSelectedTier(tier)}
            >
              <div className="flex items-center gap-2 mb-2">
                <div className={clsx('w-3 h-3 rounded-full', TIER_COLORS[tier])} />
                <span className="font-bold text-white">{TIER_LABELS[tier]}</span>
              </div>
              <div className="text-3xl font-bold text-white mb-1">{tierLevel.length}</div>
              <div className="text-xs text-gray-400">레벨</div>
              {stats && stats.validated > 0 && (
                <div className="mt-2 flex items-center gap-1 text-xs">
                  <span className="text-green-400">{stats.passed}✓</span>
                  <span className="text-yellow-400">{stats.warnings}⚠</span>
                  <span className="text-red-400">{stats.failed}✗</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Selected Tier Levels */}
      <div className="bg-gray-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-white">
            {TIER_LABELS[selectedTier]} 레벨 ({levels[selectedTier]?.length || 0}개)
          </h3>
          <Button
            variant="primary"
            size="sm"
            onClick={() => handleValidateAll(selectedTier)}
            disabled={isValidating || (levels[selectedTier]?.length || 0) === 0}
          >
            전체 검증
          </Button>
        </div>

        {levels[selectedTier]?.length === 0 ? (
          <div className="text-center text-gray-400 py-8">
            이 티어에 레벨이 없습니다
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3">
            {levels[selectedTier]?.map(level => (
              <div
                key={level.id}
                className={clsx(
                  'bg-gray-700 rounded-lg p-3 cursor-pointer border-2 transition-all',
                  selectedLevel?.id === level.id ? 'border-blue-500' : 'border-transparent hover:border-gray-500'
                )}
                onClick={() => setSelectedLevel(level)}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-bold text-white">{level.id}</span>
                  <div className="flex gap-1">
                    {level.tags.slice(0, 2).map(tag => (
                      <span key={tag} className="px-2 py-0.5 bg-gray-600 rounded text-xs text-gray-300">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="text-sm text-gray-300">{level.name}</div>
                <div className="text-xs text-gray-500 mt-1">{level.description}</div>
                <div className="flex gap-2 mt-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={(e) => { e.stopPropagation(); handleValidate(level.id); }}
                    disabled={isValidating}
                  >
                    검증
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={(e) => { e.stopPropagation(); handleLoadToEditor(level.id); }}
                  >
                    에디터
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Validation Result */}
      {validationResult && (
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-bold text-white">
              검증 결과: {validationResult.level_name}
            </h3>
            <div className={clsx(
              'px-3 py-1 rounded-full text-sm font-bold',
              validationResult.overall_pass
                ? 'bg-green-500 text-white'
                : validationResult.warnings > 0 && validationResult.failures === 0
                  ? 'bg-yellow-500 text-black'
                  : 'bg-red-500 text-white'
            )}>
              {validationResult.overall_pass ? 'PASS' : validationResult.failures > 0 ? 'FAIL' : 'WARN'}
            </div>
          </div>

          <div className="text-xs text-gray-400 mb-3">
            {validationResult.iterations}회 반복 | 허용 오차: {validationResult.tolerance}%
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-700">
                  <th className="text-left py-2 text-gray-400">봇</th>
                  <th className="text-right py-2 text-gray-400">목표</th>
                  <th className="text-right py-2 text-gray-400">실제</th>
                  <th className="text-right py-2 text-gray-400">편차</th>
                  <th className="text-center py-2 text-gray-400">상태</th>
                </tr>
              </thead>
              <tbody>
                {validationResult.bot_results.map(bot => (
                  <tr key={bot.bot_type} className="border-b border-gray-700/50">
                    <td className="py-2 text-white">{BOT_LABELS[bot.bot_type] || bot.bot_type}</td>
                    <td className="text-right py-2 text-gray-300">{(bot.expected_rate * 100).toFixed(0)}%</td>
                    <td className="text-right py-2 text-white font-bold">{(bot.actual_rate * 100).toFixed(0)}%</td>
                    <td className={clsx(
                      'text-right py-2 font-bold',
                      bot.deviation <= 15 ? 'text-green-400' : bot.deviation <= 22.5 ? 'text-yellow-400' : 'text-red-400'
                    )}>
                      {bot.deviation.toFixed(1)}%
                    </td>
                    <td className="text-center py-2">
                      <span className={clsx(
                        'px-2 py-0.5 rounded text-xs font-bold',
                        bot.status === 'PASS' ? 'bg-green-500/20 text-green-400' :
                        bot.status === 'WARN' ? 'bg-yellow-500/20 text-yellow-400' :
                        'bg-red-500/20 text-red-400'
                      )}>
                        {bot.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Loading overlay for validation */}
      {isValidating && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 flex flex-col items-center">
            <div className="animate-spin w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full mb-4" />
            <div className="text-white">검증 중... (100회 시뮬레이션)</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default BenchmarkDashboard;
