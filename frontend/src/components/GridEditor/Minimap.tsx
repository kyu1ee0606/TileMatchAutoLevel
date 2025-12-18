import { useMemo } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import { TILE_TYPES } from '../../types';

interface MinimapProps {
  className?: string;
}

const MINIMAP_TILE_SIZE = 4; // px per tile in minimap
const MAX_MINIMAP_SIZE = 120; // max width/height

export function Minimap({ className }: MinimapProps) {
  const { level, selectedLayer } = useLevelStore();

  const layerKey = `layer_${selectedLayer}` as `layer_${number}`;
  const layerData = level[layerKey];

  const { cols, rows, tiles, scale } = useMemo(() => {
    if (!layerData) {
      return { cols: 0, rows: 0, tiles: {}, scale: 1 };
    }

    const c = parseInt(layerData.col) || 8;
    const r = parseInt(layerData.row) || 8;
    const t = layerData.tiles || {};

    // Calculate scale to fit within max size
    const naturalWidth = c * MINIMAP_TILE_SIZE;
    const naturalHeight = r * MINIMAP_TILE_SIZE;
    const s = Math.min(1, MAX_MINIMAP_SIZE / Math.max(naturalWidth, naturalHeight));

    return { cols: c, rows: r, tiles: t, scale: s };
  }, [layerData]);

  if (!layerData || cols === 0 || rows === 0) {
    return null;
  }

  const tileSize = MINIMAP_TILE_SIZE * scale;
  const width = cols * tileSize;
  const height = rows * tileSize;

  return (
    <div
      className={`bg-gray-900/90 rounded-lg p-1.5 shadow-lg border border-gray-600 ${className || ''}`}
      style={{ width: width + 12, height: height + 28 }}
    >
      <div className="text-[9px] text-gray-400 mb-1 text-center">
        L{selectedLayer} ({cols}x{rows})
      </div>
      <div
        className="grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, ${tileSize}px)`,
          gridTemplateRows: `repeat(${rows}, ${tileSize}px)`,
          gap: '0px',
        }}
      >
        {Array.from({ length: rows }, (_, y) =>
          Array.from({ length: cols }, (_, x) => {
            const pos = `${x}_${y}`;
            const tileData = tiles[pos];
            const tileType = tileData?.[0];
            const tileInfo = tileType ? TILE_TYPES[tileType] : null;
            const color = tileInfo?.color || '#374151'; // gray-700 for empty

            return (
              <div
                key={pos}
                style={{
                  width: tileSize,
                  height: tileSize,
                  backgroundColor: color,
                }}
              />
            );
          })
        )}
      </div>
    </div>
  );
}
