import { useMemo } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import clsx from 'clsx';

interface LayerStackPreviewProps {
  className?: string;
}

export function LayerStackPreview({ className }: LayerStackPreviewProps) {
  const { level, selectedLayer, setSelectedLayer } = useLevelStore();

  const layerStats = useMemo(() => {
    const stats: Array<{
      index: number;
      tileCount: number;
      cols: number;
      rows: number;
      density: number; // 0-1 percentage of filled cells
      hasGimmicks: boolean;
    }> = [];

    for (let i = level.layer - 1; i >= 0; i--) {
      const layerKey = `layer_${i}` as `layer_${number}`;
      const layerData = level[layerKey];

      if (!layerData) {
        stats.push({ index: i, tileCount: 0, cols: 7, rows: 7, density: 0, hasGimmicks: false });
        continue;
      }

      const tileCount = layerData.tiles ? Object.keys(layerData.tiles).length : 0;
      const cols = parseInt(layerData.col) || 7;
      const rows = parseInt(layerData.row) || 7;
      const maxTiles = cols * rows;
      const density = maxTiles > 0 ? tileCount / maxTiles : 0;

      // Check for gimmicks
      let hasGimmicks = false;
      if (layerData.tiles) {
        for (const pos in layerData.tiles) {
          const tile = layerData.tiles[pos];
          if (Array.isArray(tile) && tile[1]) {
            hasGimmicks = true;
            break;
          }
        }
      }

      stats.push({ index: i, tileCount, cols, rows, density, hasGimmicks });
    }

    return stats;
  }, [level]);

  const totalTiles = layerStats.reduce((sum, s) => sum + s.tileCount, 0);

  return (
    <div className={clsx('bg-gray-800 rounded-lg p-3', className)}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-300">레이어 스택</h3>
        <span className="text-xs text-gray-500">총 {totalTiles}개 타일</span>
      </div>

      {/* 3D-style stacked layer visualization */}
      <div className="relative" style={{ perspective: '500px' }}>
        <div
          className="flex flex-col gap-1"
          style={{ transformStyle: 'preserve-3d' }}
        >
          {layerStats.map((stat, idx) => {
            const isSelected = stat.index === selectedLayer;
            const offset = idx * 2; // Visual offset for 3D effect

            return (
              <button
                key={stat.index}
                onClick={() => setSelectedLayer(stat.index)}
                className={clsx(
                  'relative flex items-center gap-2 px-2 py-1.5 rounded transition-all',
                  'hover:scale-[1.02]',
                  isSelected
                    ? 'bg-primary-600 text-white ring-2 ring-primary-400'
                    : stat.tileCount > 0
                      ? 'bg-gray-700 text-gray-200 hover:bg-gray-600'
                      : 'bg-gray-750 text-gray-500 hover:bg-gray-700'
                )}
                style={{
                  transform: `translateZ(${offset}px)`,
                }}
              >
                {/* Layer index */}
                <span className={clsx(
                  'w-6 text-xs font-mono',
                  isSelected ? 'text-white' : 'text-gray-400'
                )}>
                  L{stat.index}
                </span>

                {/* Mini density bar */}
                <div className="flex-1 h-3 bg-gray-800 rounded-sm overflow-hidden">
                  <div
                    className={clsx(
                      'h-full transition-all',
                      isSelected ? 'bg-primary-400' :
                      stat.hasGimmicks ? 'bg-orange-500' :
                      stat.tileCount > 0 ? 'bg-blue-500' : 'bg-gray-700'
                    )}
                    style={{ width: `${stat.density * 100}%` }}
                  />
                </div>

                {/* Tile count */}
                <span className={clsx(
                  'w-10 text-right text-xs',
                  isSelected ? 'text-white' : 'text-gray-400'
                )}>
                  {stat.tileCount > 0 ? stat.tileCount : '-'}
                </span>

                {/* Gimmick indicator */}
                {stat.hasGimmicks && (
                  <span className="text-xs" title="기믹 포함">⚡</span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="mt-3 pt-2 border-t border-gray-700 flex items-center gap-3 text-[10px] text-gray-500">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-blue-500" /> 일반
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-orange-500" /> 기믹
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-sm bg-primary-500" /> 편집중
        </span>
      </div>

      {/* Layer blocking info */}
      <div className="mt-2 text-[10px] text-gray-500">
        <div className="flex items-center gap-1">
          <span>📍</span>
          <span>Layer {selectedLayer} 편집 중</span>
        </div>
        {selectedLayer < level.layer - 1 && (
          <div className="flex items-center gap-1 text-yellow-500/70 mt-1">
            <span>⚠️</span>
            <span>상위 {level.layer - 1 - selectedLayer}개 레이어가 가림</span>
          </div>
        )}
      </div>
    </div>
  );
}
