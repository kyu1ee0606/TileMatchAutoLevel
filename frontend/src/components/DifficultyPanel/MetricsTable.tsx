import type { LevelMetrics } from '../../types';
import { TILE_TYPES } from '../../types';
import clsx from 'clsx';

interface MetricsTableProps {
  metrics: LevelMetrics;
  className?: string;
}

// Get tile image URL
const getTileImage = (tileType: string): string | null => {
  // Check if it's in TILE_TYPES
  if (TILE_TYPES[tileType]?.image) {
    return TILE_TYPES[tileType].image;
  }
  // Fallback for basic tiles
  if (tileType.startsWith('t')) {
    return `/tiles/skin0/s0_${tileType}.png`;
  }
  return null;
};

// Format tile type for display
const formatTileType = (tileType: string): string => {
  if (TILE_TYPES[tileType]) {
    return TILE_TYPES[tileType].name;
  }
  return tileType;
};

// Get goal display info
const getGoalInfo = (goalType: string): { icon: string; label: string; color: string } => {
  const goalMap: Record<string, { icon: string; label: string; color: string }> = {
    craft_s: { icon: '🎨', label: 'Craft ↓', color: 'bg-emerald-900/50 text-emerald-200' },
    craft_n: { icon: '🎨', label: 'Craft ↑', color: 'bg-emerald-900/50 text-emerald-200' },
    craft_e: { icon: '🎨', label: 'Craft →', color: 'bg-emerald-900/50 text-emerald-200' },
    craft_w: { icon: '🎨', label: 'Craft ←', color: 'bg-emerald-900/50 text-emerald-200' },
    stack_s: { icon: '📚', label: 'Stack ↓', color: 'bg-blue-900/50 text-blue-200' },
    stack_n: { icon: '📚', label: 'Stack ↑', color: 'bg-blue-900/50 text-blue-200' },
    stack_e: { icon: '📚', label: 'Stack →', color: 'bg-blue-900/50 text-blue-200' },
    stack_w: { icon: '📚', label: 'Stack ←', color: 'bg-blue-900/50 text-blue-200' },
  };
  return goalMap[goalType] || { icon: '🎯', label: goalType, color: 'bg-purple-900/50 text-purple-200' };
};

export function MetricsTable({ metrics, className }: MetricsTableProps) {
  const metricRows = [
    { label: '총 타일 수', value: metrics.total_tiles, icon: '🎯' },
    { label: '활성 레이어', value: metrics.active_layers, icon: '📚' },
    { label: '체인 타일', value: metrics.chain_count, icon: '⛓️' },
    { label: '개구리 장애물', value: metrics.frog_count, icon: '🐸' },
    { label: '링크 타일', value: metrics.link_count, icon: '🔗' },
    { label: '목표 수집량', value: metrics.goal_amount, icon: '🎁' },
    {
      label: '레이어 차단',
      value: metrics.layer_blocking.toFixed(1),
      icon: '🧱',
    },
  ];

  return (
    <div className={clsx('', className)}>
      <h3 className="text-sm font-medium text-gray-300 mb-2">📊 상세 메트릭스</h3>
      <div className="bg-gray-700/50 rounded-lg p-3">
        <table className="w-full text-sm">
          <tbody>
            {metricRows.map((row) => (
              <tr key={row.label} className="border-b border-gray-600 last:border-0">
                <td className="py-1.5 text-gray-300">
                  <span className="mr-2">{row.icon}</span>
                  {row.label}
                </td>
                <td className="py-1.5 text-right font-medium text-gray-200">{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Tile Types Distribution */}
      {Object.keys(metrics.tile_types).length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-gray-300 mb-2">타일 분포</h4>
          <div className="flex flex-wrap gap-2">
            {Object.entries(metrics.tile_types)
              .filter(([type]) => type.startsWith('t')) // Only show basic tiles
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([type, count]) => {
                const imageUrl = getTileImage(type);
                return (
                  <div
                    key={type}
                    className="flex items-center gap-1.5 px-2 py-1 bg-gray-700/80 rounded-lg"
                    title={formatTileType(type)}
                  >
                    {imageUrl ? (
                      <img
                        src={imageUrl}
                        alt={formatTileType(type)}
                        className="w-5 h-5 object-contain"
                      />
                    ) : (
                      <span className="text-xs text-gray-400">{type}</span>
                    )}
                    <span className="text-sm font-medium text-gray-200">
                      {count}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* Goals */}
      {metrics.goals.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-gray-300 mb-2">목표</h4>
          <div className="flex flex-wrap gap-2">
            {metrics.goals.map((goal, i) => {
              const goalInfo = getGoalInfo(goal.type);
              return (
                <div
                  key={i}
                  className={clsx(
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-sm',
                    goalInfo.color
                  )}
                >
                  <span>{goalInfo.icon}</span>
                  <span className="font-medium">{goalInfo.label}</span>
                  <span className="opacity-75">×{goal.count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
