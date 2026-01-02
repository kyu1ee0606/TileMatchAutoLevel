import { useState, useMemo } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useLevelStore } from '../../stores/levelStore';
import { analyzeAutoPlay, type AutoPlayResponse, type BotClearStats } from '../../api/analyze';
import { Button } from '../ui/Button';
import clsx from 'clsx';

interface AutoPlayPanelProps {
  className?: string;
  embedded?: boolean;
  targetDifficulty?: number; // Optional: target difficulty from generation
}

// Bot profile colors and Korean display names
const BOT_CONFIG: Record<string, { color: string; name: string; icon: string }> = {
  novice: { color: '#22c55e', name: '초보자', icon: '🌱' },
  casual: { color: '#3b82f6', name: '캐주얼', icon: '🎮' },
  average: { color: '#eab308', name: '일반', icon: '👤' },
  expert: { color: '#f97316', name: '숙련자', icon: '⭐' },
  optimal: { color: '#ef4444', name: '최적', icon: '🏆' },
};

// Grade colors
const GRADE_COLORS: Record<string, string> = {
  S: 'text-green-400',
  A: 'text-blue-400',
  B: 'text-yellow-400',
  C: 'text-orange-400',
  D: 'text-red-400',
};

// Calculate difficulty match score (0-100%)
function calculateMatchScore(botStats: BotClearStats[]): { score: number; avgGap: number; maxGap: number } {
  if (!botStats.length) return { score: 0, avgGap: 0, maxGap: 0 };

  const gaps = botStats.map(s => Math.abs((s.clear_rate - s.target_clear_rate) * 100));
  const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
  const maxGap = Math.max(...gaps);

  // Score: 100 - weighted average gap (max gap has more weight)
  const weightedGap = (avgGap * 0.6 + maxGap * 0.4);
  const score = Math.max(0, 100 - weightedGap * 2);

  return { score, avgGap, maxGap };
}

// Get match status based on score
function getMatchStatus(score: number): { label: string; color: string; bgColor: string; icon: string } {
  if (score >= 85) return { label: '우수', color: 'text-green-400', bgColor: 'bg-green-900/40', icon: '✅' };
  if (score >= 70) return { label: '양호', color: 'text-blue-400', bgColor: 'bg-blue-900/40', icon: '👍' };
  if (score >= 50) return { label: '보통', color: 'text-yellow-400', bgColor: 'bg-yellow-900/40', icon: '⚠️' };
  if (score >= 30) return { label: '미흡', color: 'text-orange-400', bgColor: 'bg-orange-900/40', icon: '⚡' };
  return { label: '조정필요', color: 'text-red-400', bgColor: 'bg-red-900/40', icon: '❌' };
}

// Difficulty Match Summary Component
function DifficultyMatchSummary({ result, targetDifficulty }: { result: AutoPlayResponse; targetDifficulty?: number }) {
  const { score, avgGap, maxGap } = useMemo(() => calculateMatchScore(result.bot_stats), [result.bot_stats]);
  const status = getMatchStatus(score);

  // Check if level is too easy or too hard
  const overallGap = result.bot_stats.reduce((sum, s) => sum + (s.clear_rate - s.target_clear_rate) * 100, 0) / result.bot_stats.length;
  const isTooEasy = overallGap > 10;
  const isTooHard = overallGap < -10;

  return (
    <div className={clsx('p-4 rounded-lg border-2', status.bgColor,
      score >= 70 ? 'border-green-600/50' : score >= 50 ? 'border-yellow-600/50' : 'border-red-600/50'
    )}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{status.icon}</span>
          <div>
            <div className="text-sm text-gray-400">난이도 일치도</div>
            <div className={clsx('text-2xl font-bold', status.color)}>{score.toFixed(0)}%</div>
          </div>
        </div>
        <div className={clsx('px-3 py-1 rounded-full text-sm font-medium', status.bgColor, status.color)}>
          {status.label}
        </div>
      </div>

      {/* Target Difficulty Info */}
      {targetDifficulty !== undefined && (
        <div className="mb-3 p-2 bg-gray-800/50 rounded text-sm">
          <span className="text-gray-400">목표 난이도: </span>
          <span className="text-white font-medium">{(targetDifficulty * 100).toFixed(0)}%</span>
        </div>
      )}

      {/* Gap Stats */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div className="p-2 bg-gray-800/50 rounded">
          <div className="text-gray-500 text-xs">평균 편차</div>
          <div className={clsx('font-medium', avgGap <= 10 ? 'text-green-400' : avgGap <= 20 ? 'text-yellow-400' : 'text-red-400')}>
            {avgGap.toFixed(1)}%p
          </div>
        </div>
        <div className="p-2 bg-gray-800/50 rounded">
          <div className="text-gray-500 text-xs">최대 편차</div>
          <div className={clsx('font-medium', maxGap <= 15 ? 'text-green-400' : maxGap <= 25 ? 'text-yellow-400' : 'text-red-400')}>
            {maxGap.toFixed(1)}%p
          </div>
        </div>
      </div>

      {/* Quick Diagnosis */}
      <div className="mt-3 pt-3 border-t border-gray-700">
        {isTooEasy && (
          <div className="flex items-center gap-2 text-yellow-400 text-sm">
            <span>📉</span>
            <span>전체적으로 <strong>너무 쉬움</strong> - 난이도 상향 권장</span>
          </div>
        )}
        {isTooHard && (
          <div className="flex items-center gap-2 text-orange-400 text-sm">
            <span>📈</span>
            <span>전체적으로 <strong>너무 어려움</strong> - 난이도 하향 권장</span>
          </div>
        )}
        {!isTooEasy && !isTooHard && score >= 70 && (
          <div className="flex items-center gap-2 text-green-400 text-sm">
            <span>✨</span>
            <span>목표 난이도에 <strong>적절히 부합</strong>합니다</span>
          </div>
        )}
        {!isTooEasy && !isTooHard && score < 70 && (
          <div className="flex items-center gap-2 text-yellow-400 text-sm">
            <span>⚖️</span>
            <span>일부 봇에서 편차가 큼 - 세부 조정 권장</span>
          </div>
        )}
      </div>
    </div>
  );
}

// Bot Clear Rate Compact Row
function BotClearRateRow({ stats }: { stats: BotClearStats }) {
  const config = BOT_CONFIG[stats.profile] || { color: '#888', name: stats.profile_display, icon: '🤖' };
  const clearPercent = stats.clear_rate * 100;
  const targetPercent = stats.target_clear_rate * 100;
  const gap = clearPercent - targetPercent;
  const absGap = Math.abs(gap);

  // Status determination
  const isGood = absGap <= 5;
  const isAcceptable = absGap <= 15;

  return (
    <div className={clsx(
      'flex items-center gap-3 p-2 rounded-lg transition-colors',
      isGood ? 'bg-green-900/20' : isAcceptable ? 'bg-yellow-900/20' : 'bg-red-900/20'
    )}>
      {/* Bot Icon & Name */}
      <div className="flex items-center gap-2 w-20">
        <span className="text-sm">{config.icon}</span>
        <span className="text-sm font-medium text-gray-300">{config.name}</span>
      </div>

      {/* Progress Bar */}
      <div className="flex-1 relative">
        <div className="h-6 bg-gray-700 rounded-full overflow-hidden relative">
          {/* Target line */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-white/70 z-20"
            style={{ left: `${targetPercent}%`, transform: 'translateX(-50%)' }}
          />
          {/* Actual bar */}
          <div
            className="h-full rounded-full transition-all duration-500 flex items-center justify-end pr-2"
            style={{
              width: `${clearPercent}%`,
              backgroundColor: config.color,
            }}
          >
            <span className="text-xs font-bold text-white drop-shadow-lg">
              {clearPercent.toFixed(0)}%
            </span>
          </div>
        </div>
        {/* Target label below */}
        <div className="absolute text-[10px] text-gray-400" style={{ left: `${targetPercent}%`, transform: 'translateX(-50%)', top: '100%' }}>
          목표 {targetPercent.toFixed(0)}%
        </div>
      </div>

      {/* Gap Badge */}
      <div className={clsx(
        'w-16 text-center py-1 px-2 rounded text-xs font-medium',
        isGood ? 'bg-green-600/30 text-green-400' :
        isAcceptable ? 'bg-yellow-600/30 text-yellow-400' : 'bg-red-600/30 text-red-400'
      )}>
        {gap >= 0 ? '+' : ''}{gap.toFixed(0)}%p
      </div>

      {/* Status Icon */}
      <div className="w-6 text-center">
        {isGood ? '✅' : isAcceptable ? '⚠️' : '❌'}
      </div>
    </div>
  );
}

// Score Comparison (Simplified)
function ScoreComparison({ result }: { result: AutoPlayResponse }) {
  const autoplayGradeColor = GRADE_COLORS[result.autoplay_grade] || 'text-gray-400';
  const staticGradeColor = GRADE_COLORS[result.static_grade] || 'text-gray-400';
  const diffSign = result.score_difference >= 0 ? '+' : '';
  const diffColor = Math.abs(result.score_difference) <= 10 ? 'text-green-400' :
                    result.score_difference > 10 ? 'text-orange-400' : 'text-yellow-400';

  return (
    <div className="grid grid-cols-3 gap-3 p-3 bg-gray-700/30 rounded-lg">
      <div className="text-center">
        <div className="text-[10px] text-gray-500 mb-0.5">자동플레이</div>
        <div className={clsx('text-xl font-bold', autoplayGradeColor)}>{result.autoplay_grade}</div>
        <div className="text-xs text-gray-400">{result.autoplay_score.toFixed(0)}점</div>
      </div>
      <div className="text-center flex flex-col items-center justify-center">
        <div className="text-[10px] text-gray-500 mb-0.5">차이</div>
        <div className={clsx('text-sm font-medium', diffColor)}>
          {diffSign}{result.score_difference.toFixed(0)}점
        </div>
        <div className="text-[9px] text-gray-500">
          {result.score_difference > 10 ? '실제 더 어려움' :
           result.score_difference < -10 ? '실제 더 쉬움' : '일치'}
        </div>
      </div>
      <div className="text-center">
        <div className="text-[10px] text-gray-500 mb-0.5">정적분석</div>
        <div className={clsx('text-xl font-bold', staticGradeColor)}>{result.static_grade}</div>
        <div className="text-xs text-gray-400">{result.static_score.toFixed(0)}점</div>
      </div>
    </div>
  );
}

// Gap Summary Table
function GapSummaryTable({ botStats }: { botStats: BotClearStats[] }) {
  // Sort by gap (descending - most problematic first)
  const sorted = [...botStats].sort((a, b) => {
    const gapA = Math.abs((a.clear_rate - a.target_clear_rate) * 100);
    const gapB = Math.abs((b.clear_rate - b.target_clear_rate) * 100);
    return gapB - gapA;
  });

  const problemBots = sorted.filter(s => Math.abs(s.clear_rate - s.target_clear_rate) * 100 > 15);
  const goodBots = sorted.filter(s => Math.abs(s.clear_rate - s.target_clear_rate) * 100 <= 5);

  if (problemBots.length === 0 && goodBots.length === botStats.length) {
    return (
      <div className="p-3 bg-green-900/20 rounded-lg text-center">
        <span className="text-green-400 text-sm">🎉 모든 봇이 목표 범위 내입니다!</span>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {problemBots.length > 0 && (
        <div className="p-2 bg-red-900/20 rounded">
          <div className="text-xs text-red-400 mb-1">⚠️ 조정 필요 ({problemBots.length}개 봇)</div>
          <div className="text-sm text-gray-300">
            {problemBots.map(s => {
              const config = BOT_CONFIG[s.profile];
              const gap = (s.clear_rate - s.target_clear_rate) * 100;
              return (
                <span key={s.profile} className="inline-flex items-center gap-1 mr-3">
                  <span>{config?.icon}</span>
                  <span>{config?.name || s.profile_display}</span>
                  <span className={gap > 0 ? 'text-yellow-400' : 'text-orange-400'}>
                    ({gap > 0 ? '+' : ''}{gap.toFixed(0)}%p)
                  </span>
                </span>
              );
            })}
          </div>
        </div>
      )}
      {goodBots.length > 0 && goodBots.length < botStats.length && (
        <div className="p-2 bg-green-900/20 rounded">
          <div className="text-xs text-green-400 mb-1">✅ 정상 범위 ({goodBots.length}개 봇)</div>
          <div className="text-sm text-gray-300">
            {goodBots.map(s => {
              const config = BOT_CONFIG[s.profile];
              return (
                <span key={s.profile} className="inline-flex items-center gap-1 mr-3">
                  <span>{config?.icon}</span>
                  <span>{config?.name || s.profile_display}</span>
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function AutoPlayPanel({ className, embedded = false, targetDifficulty }: AutoPlayPanelProps) {
  const { level } = useLevelStore();
  const [iterations, setIterations] = useState(100);
  const [showDetails, setShowDetails] = useState(false);

  const mutation = useMutation({
    mutationFn: () => analyzeAutoPlay(level, { iterations }),
  });

  const handleAnalyze = () => {
    mutation.mutate();
  };

  const result = mutation.data;

  return (
    <div className={clsx(!embedded && 'bg-gray-800 rounded-lg', className)}>
      {/* Header */}
      <div className={clsx(
        'flex items-center justify-between',
        embedded ? 'pb-3' : 'px-4 py-3 border-b border-gray-700'
      )}>
        <div className="flex items-center gap-2">
          <span className="text-lg">🎯</span>
          <h3 className={clsx('font-semibold text-gray-100', embedded && 'text-sm')}>난이도 검증</h3>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={iterations}
            onChange={(e) => setIterations(Number(e.target.value))}
            className="bg-gray-700 text-gray-200 text-sm rounded px-2 py-1 border border-gray-600"
            disabled={mutation.isPending}
          >
            <option value={50}>50회</option>
            <option value={100}>100회</option>
            <option value={200}>200회</option>
            <option value={500}>500회</option>
          </select>
          <Button
            variant="primary"
            size="sm"
            onClick={handleAnalyze}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? '분석 중...' : '검증 시작'}
          </Button>
        </div>
      </div>

      {/* Content */}
      <div className={clsx(!embedded && 'p-4')}>
        {/* Loading State */}
        {mutation.isPending && (
          <div className="flex flex-col items-center justify-center py-8">
            <div className="animate-spin w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full" />
            <p className="mt-3 text-sm text-gray-400">
              {iterations * 5}회 시뮬레이션 실행 중...
            </p>
          </div>
        )}

        {/* Error State */}
        {mutation.isError && (
          <div className="text-center py-8">
            {(mutation.error instanceof Error &&
              (mutation.error.message.includes('timeout') ||
               mutation.error.message.includes('ECONNABORTED') ||
               mutation.error.message.includes('Network Error'))) ? (
              <>
                <span className="text-3xl">⏱️</span>
                <p className="mt-2 text-yellow-400">시뮬레이션 시간 초과</p>
                <p className="mt-1 text-sm text-gray-400">반복 횟수를 줄이거나 다시 시도하세요</p>
                <Button variant="secondary" size="sm" onClick={handleAnalyze} className="mt-3">
                  다시 시도
                </Button>
              </>
            ) : (
              <>
                <span className="text-3xl">⚠️</span>
                <p className="mt-2 text-red-400">
                  {mutation.error instanceof Error ? mutation.error.message : '분석 실패'}
                </p>
                <Button variant="secondary" size="sm" onClick={handleAnalyze} className="mt-3">
                  다시 시도
                </Button>
              </>
            )}
          </div>
        )}

        {/* Results */}
        {result && !mutation.isPending && (
          <div className="space-y-4">
            {/* Difficulty Match Summary - NEW! */}
            <DifficultyMatchSummary result={result} targetDifficulty={targetDifficulty} />

            {/* Score Comparison */}
            <ScoreComparison result={result} />

            {/* Gap Summary */}
            <GapSummaryTable botStats={result.bot_stats} />

            {/* Bot Clear Rates (collapsible) */}
            <div>
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-200 transition-colors w-full"
              >
                <span className={clsx('transition-transform', showDetails && 'rotate-90')}>▶</span>
                <span>봇별 상세 클리어율</span>
              </button>
              {showDetails && (
                <div className="mt-3 space-y-2">
                  {result.bot_stats.map((stats) => (
                    <BotClearRateRow key={stats.profile} stats={stats} />
                  ))}
                </div>
              )}
            </div>

            {/* Recommendations */}
            {result.recommendations.length > 0 && (
              <div className="p-3 bg-gray-700/30 rounded-lg">
                <h4 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-1">
                  <span>💡</span> 개선 제안
                </h4>
                <ul className="space-y-1">
                  {result.recommendations.slice(0, 3).map((rec, i) => (
                    <li key={i} className="text-sm text-gray-300 flex items-start gap-2">
                      <span className="text-gray-500">•</span>
                      {rec}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Metadata */}
            <div className="flex justify-between text-xs text-gray-500 pt-2 border-t border-gray-700">
              <span>총 {result.total_simulations}회 시뮬레이션</span>
              <span>실행 시간: {(result.execution_time_ms / 1000).toFixed(1)}초</span>
            </div>
          </div>
        )}

        {/* Initial State */}
        {!result && !mutation.isPending && !mutation.isError && (
          <div className="text-center py-8 text-gray-400">
            <span className="text-3xl">🎯</span>
            <p className="mt-2 text-sm">
              검증 시작 버튼을 눌러 생성된 레벨이 목표 난이도에 맞는지 확인하세요
            </p>
            <p className="mt-1 text-xs text-gray-500">
              5개 봇 프로필로 반복 시뮬레이션 후 일치도를 분석합니다
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
