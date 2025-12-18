import type { LevelMetrics } from '../../types';
import clsx from 'clsx';

interface MetricsTableProps {
  metrics: LevelMetrics;
  className?: string;
}

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
          <div className="flex flex-wrap gap-1">
            {Object.entries(metrics.tile_types)
              .sort((a, b) => b[1] - a[1])
              .slice(0, 8)
              .map(([type, count]) => (
                <span
                  key={type}
                  className="px-2 py-0.5 bg-gray-700 text-gray-300 rounded text-xs"
                >
                  {type}: {count}
                </span>
              ))}
          </div>
        </div>
      )}

      {/* Goals */}
      {metrics.goals.length > 0 && (
        <div className="mt-4">
          <h4 className="text-sm font-medium text-gray-300 mb-2">목표</h4>
          <div className="flex flex-wrap gap-2">
            {metrics.goals.map((goal, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-purple-900/50 text-purple-200 rounded text-sm"
              >
                {goal.type === 'craft_s' ? '🎨' : '📦'} {goal.count}개
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
