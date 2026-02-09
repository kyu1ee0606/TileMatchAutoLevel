import { useMemo } from 'react';
import type { LevelJSON } from '../../types';
import type { VisualBotResult, BotProfile } from '../../types/simulation';
import { BOT_PROFILES } from '../../types/simulation';
import { BotTileGrid } from './BotTileGrid';
import clsx from 'clsx';

// Tile image helper
const getTileImage = (tileType: string): string => {
  if (tileType.startsWith('t')) {
    return `/tiles/skin0/s0_${tileType}.png`;
  }
  // key 타일은 item_key.png 사용
  if (tileType === 'key') {
    return '/tiles/special/item_key.png';
  }
  return `/tiles/special/${tileType}.png`;
};

interface BotViewerProps {
  levelJson: LevelJSON;
  botResult: VisualBotResult;
  currentStep: number;
  initialFrogPositions?: string[];
  initialBombStates?: Record<string, number>;
  initialCurtainStates?: Record<string, boolean>;
  initialIceStates?: Record<string, number>;
  initialChainStates?: Record<string, boolean>;
  initialGrassStates?: Record<string, number>;
  initialLinkStates?: Record<string, string[]>;
  initialTeleportStates?: Record<string, string>;
  convertedTiles?: Record<string, Record<string, unknown>>; // Converted tiles from API (t0 -> actual types)
  className?: string;
}

export function BotViewer({
  levelJson,
  botResult,
  currentStep,
  initialFrogPositions = [],
  initialBombStates = {},
  initialCurtainStates = {},
  initialIceStates = {},
  initialChainStates = {},
  initialGrassStates = {},
  initialLinkStates = {},
  initialTeleportStates = {},
  convertedTiles,
  className
}: BotViewerProps) {
  const profile = BOT_PROFILES[botResult.profile as BotProfile];

  const progress = botResult.total_moves > 0
    ? Math.min(currentStep, botResult.total_moves)
    : 0;

  // Calculate current goals from moves
  // When game is over, keep the last goals state
  const currentGoals = useMemo(() => {
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      return botResult.moves[moveIdx].goals_after || {};
    }
    return {};
  }, [botResult.moves, currentStep]);

  // Get current dock state (7 slots)
  // When game is over (dock full or cleared), keep the last dock state
  const currentDock = useMemo(() => {
    if (currentStep > 0 && botResult.moves.length > 0) {
      // If currentStep exceeds moves, show the last dock state (game over state)
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      return botResult.moves[moveIdx].dock_after || [];
    }
    return [];
  }, [botResult.moves, currentStep]);

  // Get current frog positions for debug display
  // When game is over, keep the last frog positions
  const currentFrogPositionsList = useMemo(() => {
    if (currentStep === 0) {
      return initialFrogPositions;
    }
    if (currentStep > 0 && botResult.moves.length > 0) {
      const moveIdx = Math.min(currentStep - 1, botResult.moves.length - 1);
      return botResult.moves[moveIdx].frog_positions_after || [];
    }
    return [];
  }, [currentStep, botResult.moves, initialFrogPositions]);

  // Calculate remaining tiles and layers info
  // NOTE: Count actual matchable tiles, including stack/craft internal tiles
  const { totalTiles, remainingTiles, layerStats } = useMemo(() => {
    // Count initial tiles per layer (including stack/craft internal tiles)
    const layerCounts: Record<number, number> = {};
    let total = 0;

    for (let layerIdx = 0; layerIdx < levelJson.layer; layerIdx++) {
      const layerKey = `layer_${layerIdx}` as `layer_${number}`;
      const layerData = levelJson[layerKey];
      if (layerData?.tiles) {
        let layerTotal = 0;
        Object.values(layerData.tiles).forEach((tileData: unknown) => {
          const td = tileData as [string, string?, unknown[]?];
          if (!td || !td[0]) return;

          const tileType = td[0];
          // Check if this is a stack/craft tile with internal tiles
          if (tileType.startsWith('stack_') || tileType.startsWith('craft_')) {
            // Stack/craft info is in td[2] with format [count] or [count, types_string]
            const stackInfo = td[2];
            if (stackInfo && Array.isArray(stackInfo) && stackInfo.length >= 1) {
              const internalCount = typeof stackInfo[0] === 'number'
                ? stackInfo[0]
                : parseInt(String(stackInfo[0]), 10) || 1;
              layerTotal += internalCount;
            } else {
              layerTotal += 1; // Default: 1 internal tile
            }
          } else {
            // Regular tile
            layerTotal += 1;
          }
        });
        layerCounts[layerIdx] = layerTotal;
        total += layerTotal;
      }
    }

    // Count removed tiles up to current step
    let removed = 0;
    const removedPerLayer: Record<number, number> = {};

    for (let i = 0; i < Math.min(currentStep, botResult.moves.length); i++) {
      const move = botResult.moves[i];
      // Selected tile removed
      removed += 1;
      removedPerLayer[move.layer_idx] = (removedPerLayer[move.layer_idx] || 0) + 1;

      // Matched tiles removed (parse layer from matched_positions)
      move.matched_positions.forEach((mp) => {
        const parts = mp.split('_');
        if (parts.length >= 3) {
          const layer = parseInt(parts[0], 10);
          removed += 1;
          removedPerLayer[layer] = (removedPerLayer[layer] || 0) + 1;
        }
      });
    }

    // Calculate remaining per layer
    const stats: { layer: number; total: number; remaining: number }[] = [];
    for (const [layerStr, count] of Object.entries(layerCounts)) {
      const layer = parseInt(layerStr, 10);
      const removedInLayer = removedPerLayer[layer] || 0;
      if (count > 0) {
        stats.push({
          layer,
          total: count,
          remaining: Math.max(0, count - removedInLayer),
        });
      }
    }

    // Sort by layer descending (highest first)
    stats.sort((a, b) => b.layer - a.layer);

    return {
      totalTiles: total,
      remainingTiles: Math.max(0, total - removed),
      layerStats: stats,
    };
  }, [levelJson, botResult.moves, currentStep]);

  return (
    <div className={clsx('bg-gray-800 rounded-lg p-3 flex flex-col', className)}>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-lg">{profile?.icon || '🤖'}</span>
          <span
            className="text-sm font-medium"
            style={{ color: profile?.color || '#fff' }}
          >
            {profile?.name || botResult.profile_display}
          </span>
        </div>
        <div className={clsx(
          'text-xs px-2 py-0.5 rounded',
          botResult.cleared ? 'bg-green-600 text-white' : 'bg-red-600 text-white'
        )}>
          {botResult.cleared ? '클리어' : '실패'}
        </div>
      </div>

      {/* Tile Grid */}
      <BotTileGrid
        levelJson={levelJson}
        botResult={botResult}
        currentStep={currentStep}
        initialFrogPositions={initialFrogPositions}
        initialBombStates={initialBombStates}
        initialCurtainStates={initialCurtainStates}
        initialIceStates={initialIceStates}
        initialChainStates={initialChainStates}
        initialGrassStates={initialGrassStates}
        initialLinkStates={initialLinkStates}
        initialTeleportStates={initialTeleportStates}
        convertedTiles={convertedTiles}
      />

      {/* Dock Buffer (7 slots with locked slots support) */}
      {(() => {
        const maxSlots = 7;
        const lockedSlots = typeof levelJson.unlockTile === 'number' ? levelJson.unlockTile : 0;
        const availableSlots = maxSlots - lockedSlots;
        const isDanger = currentDock.length >= availableSlots - 1;

        return (
          <div className="mt-2 flex items-center gap-0.5">
            <span className="text-[9px] text-gray-500 mr-1">독:</span>
            <div className="flex gap-0.5">
              {Array.from({ length: maxSlots }).map((_, idx) => {
                const tileType = currentDock[idx];
                const isFilled = !!tileType;
                const isLocked = idx >= availableSlots;

                return (
                  <div
                    key={idx}
                    className={clsx(
                      'w-5 h-5 rounded border flex items-center justify-center',
                      isLocked
                        ? 'border-amber-600 bg-amber-900/40'
                        : isFilled
                          ? isDanger
                            ? 'border-red-500 bg-red-900/30'
                            : 'border-gray-500 bg-gray-700'
                          : 'border-gray-600 bg-gray-800/50'
                    )}
                  >
                    {isLocked ? (
                      <span className="text-[8px] text-amber-400">🔒</span>
                    ) : tileType ? (
                      <img
                        src={getTileImage(tileType)}
                        alt={tileType}
                        className="w-4 h-4 object-contain"
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
            <span className={clsx(
              'text-[9px] ml-1',
              currentDock.length >= availableSlots - 1 ? 'text-red-400' : 'text-gray-500'
            )}>
              {currentDock.length}/{availableSlots}
              {lockedSlots > 0 && <span className="text-amber-400 ml-0.5">🔒{lockedSlots}</span>}
            </span>
          </div>
        );
      })()}

      {/* Progress bar */}
      <div className="mt-2">
        <div className="flex justify-between text-[10px] text-gray-400 mb-0.5">
          <span>Move {Math.min(currentStep, botResult.total_moves)}/{botResult.total_moves}</span>
          <span>타일: {remainingTiles}/{totalTiles}</span>
        </div>
        <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full transition-all duration-200"
            style={{
              width: `${(progress / Math.max(1, botResult.total_moves)) * 100}%`,
              backgroundColor: profile?.color || '#3b82f6',
            }}
          />
        </div>
      </div>

      {/* Layer stats - show remaining tiles per layer */}
      {layerStats.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {layerStats.slice(0, 4).map(({ layer, remaining, total }) => (
            <div
              key={layer}
              className={clsx(
                'text-[9px] px-1.5 py-0.5 rounded',
                remaining === 0 ? 'bg-green-600/30 text-green-400' : 'bg-gray-700 text-gray-300'
              )}
            >
              L{layer}: {remaining}/{total}
            </div>
          ))}
          {layerStats.length > 4 && (
            <div className="text-[9px] px-1.5 py-0.5 text-gray-500">
              +{layerStats.length - 4} layers
            </div>
          )}
        </div>
      )}

      {/* Goals progress */}
      {Object.keys(currentGoals).length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {Object.entries(currentGoals).map(([goalType, remaining]) => (
            <div
              key={goalType}
              className="flex items-center gap-1 text-[10px] bg-gray-700 rounded px-1.5 py-0.5"
            >
              <span className="text-gray-400">{goalType}:</span>
              <span className={remaining === 0 ? 'text-green-400' : 'text-yellow-400'}>
                {remaining}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Frog positions indicator */}
      {currentFrogPositionsList.length > 0 && (
        <div className="mt-2 flex items-center gap-1">
          <span className="text-[9px] text-gray-500">🐸:</span>
          <div className="flex flex-wrap gap-0.5">
            {currentFrogPositionsList.map((pos) => (
              <div
                key={pos}
                className="text-[8px] px-1 py-0.5 bg-green-800/50 text-green-300 rounded"
              >
                {pos}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
