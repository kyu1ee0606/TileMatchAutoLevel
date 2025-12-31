import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useLevelStore } from '../../stores/levelStore';
import { analyzeAutoPlay, type AutoPlayResponse, type BotClearStats } from '../../api/analyze';
import { Button } from '../ui/Button';
import clsx from 'clsx';

interface AutoPlayPanelProps {
  className?: string;
  embedded?: boolean; // When true, removes outer container styling for embedding in other panels
}

// Bot profile colors
const BOT_COLORS: Record<string, string> = {
  novice: '#22c55e',   // green
  casual: '#3b82f6',   // blue
  average: '#eab308',  // yellow
  expert: '#f97316',   // orange
  optimal: '#ef4444',  // red
};

// Balance status display
const BALANCE_STATUS_DISPLAY: Record<string, { text: string; color: string; icon: string }> = {
  balanced: { text: '균형', color: 'text-green-400', icon: '✓' },
  too_easy: { text: '너무 쉬움', color: 'text-yellow-400', icon: '⚠' },
  too_hard: { text: '너무 어려움', color: 'text-orange-400', icon: '⚠' },
  unbalanced: { text: '불균형', color: 'text-red-400', icon: '✕' },
};

// Grade colors
const GRADE_COLORS: Record<string, string> = {
  S: 'text-green-400',
  A: 'text-blue-400',
  B: 'text-yellow-400',
  C: 'text-orange-400',
  D: 'text-red-400',
};

function ClearRateBar({ stats }: { stats: BotClearStats }) {
  const clearPercent = stats.clear_rate * 100;
  const targetPercent = stats.target_clear_rate * 100;
  const color = BOT_COLORS[stats.profile] || '#888';
  const gap = clearPercent - targetPercent;

  return (
    <div className="mb-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-sm font-medium text-gray-300">{stats.profile_display}</span>
        <span className={clsx(
          'text-sm font-medium',
          gap >= -5 && gap <= 5 ? 'text-green-400' :
          gap < -5 ? 'text-orange-400' : 'text-yellow-400'
        )}>
          {clearPercent.toFixed(0)}% <span className="text-gray-500">/ 목표 {targetPercent.toFixed(0)}%</span>
        </span>
      </div>
      <div className="relative h-4 bg-gray-700 rounded-full overflow-hidden">
        {/* Target indicator */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/50 z-10"
          style={{ left: `${targetPercent}%` }}
        />
        {/* Actual bar */}
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{
            width: `${clearPercent}%`,
            backgroundColor: color,
          }}
        />
      </div>
      <div className="flex justify-between mt-0.5 text-[10px] text-gray-500">
        <span>평균 {stats.avg_moves.toFixed(1)}턴</span>
        <span>콤보 {stats.avg_combo.toFixed(1)}</span>
      </div>
    </div>
  );
}

function ScoreComparison({ result }: { result: AutoPlayResponse }) {
  const autoplayGradeColor = GRADE_COLORS[result.autoplay_grade] || 'text-gray-400';
  const staticGradeColor = GRADE_COLORS[result.static_grade] || 'text-gray-400';
  const diffSign = result.score_difference >= 0 ? '+' : '';
  const diffColor = Math.abs(result.score_difference) <= 10 ? 'text-green-400' :
                    result.score_difference > 10 ? 'text-orange-400' : 'text-yellow-400';

  return (
    <div className="grid grid-cols-3 gap-4 p-4 bg-gray-700/50 rounded-lg">
      {/* AutoPlay Score */}
      <div className="text-center">
        <div className="text-xs text-gray-400 mb-1">자동플레이</div>
        <div className={clsx('text-2xl font-bold', autoplayGradeColor)}>
          {result.autoplay_grade}
        </div>
        <div className="text-sm text-gray-300">{result.autoplay_score.toFixed(0)}점</div>
      </div>

      {/* Difference */}
      <div className="text-center flex flex-col items-center justify-center">
        <div className="text-xs text-gray-400 mb-1">차이</div>
        <div className={clsx('text-lg font-medium', diffColor)}>
          {diffSign}{result.score_difference.toFixed(0)}점
        </div>
        <div className="text-[10px] text-gray-500">
          {result.score_difference > 10 ? '실제로 더 어려움' :
           result.score_difference < -10 ? '실제로 더 쉬움' : '거의 일치'}
        </div>
      </div>

      {/* Static Score */}
      <div className="text-center">
        <div className="text-xs text-gray-400 mb-1">정적분석</div>
        <div className={clsx('text-2xl font-bold', staticGradeColor)}>
          {result.static_grade}
        </div>
        <div className="text-sm text-gray-300">{result.static_score.toFixed(0)}점</div>
      </div>
    </div>
  );
}

export function AutoPlayPanel({ className, embedded = false }: AutoPlayPanelProps) {
  const { level } = useLevelStore();
  const [iterations, setIterations] = useState(100);

  const mutation = useMutation({
    mutationFn: () => analyzeAutoPlay(level, { iterations }),
  });

  const handleAnalyze = () => {
    mutation.mutate();
  };

  const result = mutation.data;
  const balanceInfo = result ? BALANCE_STATUS_DISPLAY[result.balance_status] : null;

  return (
    <div className={clsx(!embedded && 'bg-gray-800 rounded-lg', className)}>
      {/* Header */}
      <div className={clsx(
        'flex items-center justify-between',
        embedded ? 'pb-3' : 'px-4 py-3 border-b border-gray-700'
      )}>
        <div className="flex items-center gap-2">
          <span className="text-lg">🤖</span>
          <h3 className={clsx('font-semibold text-gray-100', embedded && 'text-sm')}>자동 플레이 분석</h3>
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
            {mutation.isPending ? '분석 중...' : '분석 시작'}
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
            {/* Check if it's a timeout error */}
            {(mutation.error instanceof Error &&
              (mutation.error.message.includes('timeout') ||
               mutation.error.message.includes('ECONNABORTED') ||
               mutation.error.message.includes('Network Error'))) ? (
              <>
                <span className="text-3xl">⏱️</span>
                <p className="mt-2 text-yellow-400">
                  시뮬레이션 시간이 오래 걸리고 있습니다
                </p>
                <p className="mt-1 text-sm text-gray-400">
                  반복 횟수를 줄이거나 다시 시도해 주세요
                </p>
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
            {/* Score Comparison */}
            <ScoreComparison result={result} />

            {/* Balance Status */}
            {balanceInfo && (
              <div className={clsx(
                'flex items-center gap-2 px-3 py-2 rounded-lg',
                result.balance_status === 'balanced' ? 'bg-green-900/30' :
                result.balance_status === 'unbalanced' ? 'bg-red-900/30' : 'bg-yellow-900/30'
              )}>
                <span>{balanceInfo.icon}</span>
                <span className={clsx('font-medium', balanceInfo.color)}>{balanceInfo.text}</span>
              </div>
            )}

            {/* Bot Clear Rates */}
            <div>
              <h4 className="text-sm font-medium text-gray-400 mb-3">봇별 클리어율</h4>
              {result.bot_stats.map((stats) => (
                <ClearRateBar key={stats.profile} stats={stats} />
              ))}
            </div>

            {/* Recommendations */}
            {result.recommendations.length > 0 && (
              <div className="p-3 bg-gray-700/50 rounded-lg">
                <h4 className="text-sm font-medium text-gray-400 mb-2 flex items-center gap-1">
                  <span>💡</span> 권장 사항
                </h4>
                <ul className="space-y-1">
                  {result.recommendations.map((rec, i) => (
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
            <span className="text-3xl">🎮</span>
            <p className="mt-2 text-sm">
              분석 시작 버튼을 눌러 자동 플레이 난이도를 측정하세요
            </p>
            <p className="mt-1 text-xs text-gray-500">
              5개 봇 프로필로 반복 시뮬레이션을 실행합니다
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
