import type { VisualSimulationResponse, BotProfile } from '../../types/simulation';
import { BOT_PROFILES } from '../../types/simulation';
import clsx from 'clsx';

interface SimulationSummaryProps {
  results: VisualSimulationResponse;
  className?: string;
}

export function SimulationSummary({ results, className }: SimulationSummaryProps) {
  const sortedResults = [...results.bot_results].sort((a, b) => {
    // Cleared bots first
    if (a.cleared !== b.cleared) return a.cleared ? -1 : 1;
    // Then by moves (fewer is better)
    if (a.cleared && b.cleared) return a.total_moves - b.total_moves;
    // Non-cleared: by score (higher is better)
    return b.final_score - a.final_score;
  });

  const clearCount = results.bot_results.filter(r => r.cleared).length;
  const avgMoves = results.bot_results.reduce((sum, r) => sum + r.total_moves, 0) / results.bot_results.length;

  return (
    <div className={clsx('bg-gray-800 rounded-lg p-3', className)}>
      <h3 className="text-sm font-medium text-gray-300 mb-3">시뮬레이션 요약</h3>

      {/* Overall stats */}
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="bg-gray-700 rounded p-2 text-center">
          <div className="text-lg font-bold text-green-400">
            {clearCount}/{results.bot_results.length}
          </div>
          <div className="text-[10px] text-gray-400">클리어율</div>
        </div>
        <div className="bg-gray-700 rounded p-2 text-center">
          <div className="text-lg font-bold text-blue-400">
            {avgMoves.toFixed(1)}
          </div>
          <div className="text-[10px] text-gray-400">평균 이동</div>
        </div>
      </div>

      {/* Per-bot results */}
      <div className="space-y-1.5">
        {sortedResults.map((result, idx) => {
          const profile = BOT_PROFILES[result.profile as BotProfile];
          return (
            <div
              key={result.profile}
              className="flex items-center justify-between bg-gray-700/50 rounded px-2 py-1.5"
            >
              <div className="flex items-center gap-1.5">
                <span className="text-sm">{idx + 1}.</span>
                <span>{profile?.icon || '🤖'}</span>
                <span
                  className="text-xs font-medium"
                  style={{ color: profile?.color || '#fff' }}
                >
                  {profile?.name || result.profile_display}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  {result.total_moves} 이동
                </span>
                <span className={clsx(
                  'text-[10px] px-1.5 py-0.5 rounded',
                  result.cleared ? 'bg-green-600/30 text-green-400' : 'bg-red-600/30 text-red-400'
                )}>
                  {result.cleared ? '성공' : '실패'}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Metadata */}
      <div className="mt-3 pt-2 border-t border-gray-700 text-[10px] text-gray-500">
        {results.metadata.elapsed_ms !== undefined && (
          <div>시뮬레이션 시간: {Number(results.metadata.elapsed_ms).toFixed(0)}ms</div>
        )}
        {results.metadata.bot_count !== undefined && (
          <div>봇 수: {Number(results.metadata.bot_count)}</div>
        )}
      </div>
    </div>
  );
}
