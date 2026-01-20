/**
 * GameBoard - 게임 보드 컴포넌트 (모든 레이어의 타일 렌더링)
 */
import { useMemo, useRef, useEffect } from 'react';
import type { GameTile } from '../../types/game';
import TileRenderer from './TileRenderer';

interface BoardBounds {
  minRow: number;
  maxRow: number;
  minCol: number;
  maxCol: number;
  maxLayer: number;
}

interface GameBoardProps {
  tiles: GameTile[];
  onTileClick: (tile: GameTile, event?: React.MouseEvent) => void;
  tileSize?: number;
  showDebug?: boolean;
  showStats?: boolean;
  fixedGridSize?: number; // If set, use fixed NxN grid instead of dynamic bounds
}

export function GameBoard({
  tiles,
  onTileClick,
  tileSize = 48,
  showDebug = false,
  showStats = true,
  fixedGridSize,
}: GameBoardProps) {
  // Store initial bounds and tile count (to detect new level)
  const initialBoundsRef = useRef<BoardBounds | null>(null);
  const initialTileCountRef = useRef<number>(0);

  // Calculate initial bounds from ALL tiles
  // Reset when a new level is loaded (detected by tile count change or all unmatched)
  useEffect(() => {
    if (tiles.length === 0) return;

    // Detect new level: all tiles unmatched AND different tile count
    const allUnmatched = tiles.every(t => !t.isMatched);
    const tileCountChanged = tiles.length !== initialTileCountRef.current;

    if (allUnmatched && (tileCountChanged || initialBoundsRef.current === null)) {
      let minRow = Infinity, maxRow = -Infinity;
      let minCol = Infinity, maxCol = -Infinity;
      let maxLayer = 0;

      // Calculate from ALL tiles
      for (const tile of tiles) {
        minRow = Math.min(minRow, tile.row);
        maxRow = Math.max(maxRow, tile.row);
        minCol = Math.min(minCol, tile.col);
        maxCol = Math.max(maxCol, tile.col);
        maxLayer = Math.max(maxLayer, tile.layer);
      }

      initialBoundsRef.current = {
        minRow: minRow === Infinity ? 0 : minRow,
        maxRow: maxRow === -Infinity ? 7 : maxRow,
        minCol: minCol === Infinity ? 0 : minCol,
        maxCol: maxCol === -Infinity ? 7 : maxCol,
        maxLayer,
      };
      initialTileCountRef.current = tiles.length;
    }
  }, [tiles]);

  // Use initial bounds or calculate temporary bounds for first render
  const bounds = useMemo(() => {
    // If fixedGridSize is provided, use fixed bounds
    if (fixedGridSize) {
      // Calculate maxLayer from tiles
      let maxLayer = 0;
      for (const tile of tiles) {
        maxLayer = Math.max(maxLayer, tile.layer);
      }
      return {
        minRow: 0,
        maxRow: fixedGridSize - 1,
        minCol: 0,
        maxCol: fixedGridSize - 1,
        maxLayer,
      };
    }

    if (initialBoundsRef.current) {
      return initialBoundsRef.current;
    }

    // Fallback for first render before useEffect runs
    if (tiles.length === 0) {
      return { minRow: 0, maxRow: 7, minCol: 0, maxCol: 7, maxLayer: 0 };
    }

    let minRow = Infinity, maxRow = -Infinity;
    let minCol = Infinity, maxCol = -Infinity;
    let maxLayer = 0;

    for (const tile of tiles) {
      minRow = Math.min(minRow, tile.row);
      maxRow = Math.max(maxRow, tile.row);
      minCol = Math.min(minCol, tile.col);
      maxCol = Math.max(maxCol, tile.col);
      maxLayer = Math.max(maxLayer, tile.layer);
    }

    return {
      minRow: minRow === Infinity ? 0 : minRow,
      maxRow: maxRow === -Infinity ? 7 : maxRow,
      minCol: minCol === Infinity ? 0 : minCol,
      maxCol: maxCol === -Infinity ? 7 : maxCol,
      maxLayer,
    };
  }, [tiles, fixedGridSize]);

  // Calculate board dimensions (fixed size based on initial bounds)
  // Add extra 0.5 tile space for odd layer offset
  const hasOddLayers = bounds.maxLayer >= 1;
  const extraOffset = hasOddLayers ? tileSize * 0.5 : 0;
  const boardWidth = (bounds.maxCol - bounds.minCol + 1) * tileSize + tileSize + extraOffset;
  const boardHeight = (bounds.maxRow - bounds.minRow + 1) * tileSize + tileSize + extraOffset;

  // Sort tiles by layer (lower layers first for proper z-ordering)
  const sortedTiles = useMemo(() => {
    return [...tiles]
      .filter(t => !t.isMatched)
      .sort((a, b) => a.layer - b.layer);
  }, [tiles]);

  // Calculate tile position with layer offset
  // Even layers (0, 2, 4...) - no offset
  // Odd layers (1, 3, 5...) - offset by 0.5 tile (same as simulation viewer)
  const getTilePosition = (tile: GameTile) => {
    const isOddLayer = tile.layer % 2 === 1;
    const layerOffset = isOddLayer ? tileSize * 0.5 : 0;

    return {
      left: (tile.col - bounds.minCol) * tileSize + tileSize / 2 + layerOffset,
      top: (tile.row - bounds.minRow) * tileSize + tileSize / 2 + layerOffset,
    };
  };

  // Count remaining tiles
  const remainingTiles = tiles.filter(t => !t.isMatched).length;
  const selectableTiles = tiles.filter(t => t.isSelectable && !t.isMatched).length;

  return (
    <div className="game-board-container">
      {/* Stats bar */}
      {showStats && (
        <div className="flex justify-between items-center mb-2 px-2 text-sm text-gray-400">
          <span>Tiles: {remainingTiles}</span>
          <span>Selectable: {selectableTiles}</span>
        </div>
      )}

      {/* Game board */}
      <div
        className="game-board relative bg-gray-800 rounded-lg overflow-hidden"
        style={{
          width: boardWidth,
          height: boardHeight,
          minWidth: 300,
          minHeight: 300,
        }}
      >
        {/* Background grid pattern */}
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: `
              linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
              linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)
            `,
            backgroundSize: `${tileSize}px ${tileSize}px`,
          }}
        />

        {/* Tiles */}
        {sortedTiles.map(tile => {
          const pos = getTilePosition(tile);
          return (
            <div
              key={tile.id}
              className="absolute transition-all duration-150"
              style={{
                left: pos.left,
                top: pos.top,
                transform: 'translate(-50%, -50%)',
                zIndex: tile.layer, // Higher layer = higher z-index (on top)
              }}
              onClick={(e) => onTileClick(tile, e)}
            >
              <TileRenderer
                tile={tile}
                size={tileSize}
                showDebug={showDebug}
              />
            </div>
          );
        })}

        {/* Empty state */}
        {remainingTiles === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <div className="text-4xl mb-2">🎉</div>
              <div className="text-xl font-bold text-green-400">Clear!</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default GameBoard;
