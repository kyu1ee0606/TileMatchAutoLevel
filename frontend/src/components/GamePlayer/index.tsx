/**
 * GamePlayer - 타일 매칭 게임 플레이어 메인 컴포넌트
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import type { GameTile, SlotTile, GameState, GameStats, LevelInfo } from '../../types/game';
import {
  parseLevelToTiles,
  calculateSelectability,
  DEFAULT_GAME_SETTINGS,
  INITIAL_GAME_STATS,
  isSpecialTile,
} from '../../types/game';
import GameBoard from './GameBoard';
import SlotArea from './SlotArea';

interface GamePlayerProps {
  levelData: Record<string, unknown> | null;
  levelInfo?: LevelInfo;
  onGameEnd?: (won: boolean, stats: GameStats) => void;
  onBack?: () => void;
}

export function GamePlayer({ levelData, levelInfo, onGameEnd, onBack }: GamePlayerProps) {
  // Game state
  const [tiles, setTiles] = useState<GameTile[]>([]);
  const [slots, setSlots] = useState<SlotTile[]>([]);
  const [gameState, setGameState] = useState<GameState>('idle');
  const [stats, setStats] = useState<GameStats>(INITIAL_GAME_STATS);
  const [settings] = useState(DEFAULT_GAME_SETTINGS);

  // Timer
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initialize game when level data changes
  useEffect(() => {
    if (levelData) {
      initGame(levelData);
    }
  }, [levelData]);

  // Timer effect
  useEffect(() => {
    if (gameState === 'playing') {
      timerRef.current = setInterval(() => {
        setStats(prev => ({ ...prev, timeElapsed: prev.timeElapsed + 1 }));
      }, 1000);
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [gameState]);

  // Initialize game
  const initGame = useCallback((data: Record<string, unknown>) => {
    // Parse level data - check if it's in map format or layer format
    let levelToUse = data;

    // If data has a 'map' field (GBoost format), extract it
    if (data.map && typeof data.map === 'object') {
      levelToUse = data.map as Record<string, unknown>;
    }

    const parsedTiles = parseLevelToTiles(levelToUse);
    const selectableTiles = calculateSelectability(parsedTiles);

    setTiles(selectableTiles);
    setSlots([]);
    setStats(INITIAL_GAME_STATS);
    setGameState('playing');
  }, []);

  // Handle tile click
  const handleTileClick = useCallback((tile: GameTile) => {
    if (gameState !== 'playing') return;
    if (!tile.isSelectable) return;

    // Don't allow selection if slots are full
    if (slots.length >= settings.maxSlots) return;

    // Add tile to slots
    const newSlotTile: SlotTile = {
      id: tile.id,
      type: tile.type,
      attribute: tile.attribute,
      sourceLayer: tile.layer,
      sourceRow: tile.row,
      sourceCol: tile.col,
    };

    // Find position to insert (group same types together)
    let insertIndex = slots.length;
    for (let i = 0; i < slots.length; i++) {
      if (slots[i].type === tile.type) {
        // Find the end of this group
        let endOfGroup = i;
        while (endOfGroup < slots.length && slots[endOfGroup].type === tile.type) {
          endOfGroup++;
        }
        insertIndex = endOfGroup;
        break;
      }
    }

    const newSlots = [
      ...slots.slice(0, insertIndex),
      newSlotTile,
      ...slots.slice(insertIndex),
    ];

    // Mark tile as matched (removed from board)
    setTiles(prev => {
      const updated = prev.map(t =>
        t.id === tile.id ? { ...t, isMatched: true, isSelectable: false } : t
      );
      // Recalculate selectability
      return calculateSelectability(updated);
    });

    // Update stats
    setStats(prev => ({ ...prev, moves: prev.moves + 1 }));

    // Check for matches (3 or more consecutive same-type tiles)
    setTimeout(() => {
      checkAndRemoveMatches(newSlots);
    }, 100);

    setSlots(newSlots);
  }, [gameState, slots, settings.maxSlots]);

  // Check for matches and remove them
  const checkAndRemoveMatches = useCallback((currentSlots: SlotTile[]) => {
    let slotsToProcess = [...currentSlots];
    let matchFound = false;
    let totalMatchedSets = 0;

    // Keep checking until no more matches
    while (true) {
      let matchStart = -1;
      let matchCount = 0;

      // Find consecutive same-type tiles (3 or more)
      for (let i = 0; i < slotsToProcess.length; i++) {
        if (i === 0 || slotsToProcess[i].type !== slotsToProcess[i - 1].type) {
          // Start of a new group
          if (matchCount >= 3) {
            // Previous group was a match
            break;
          }
          matchStart = i;
          matchCount = 1;
        } else {
          matchCount++;
        }
      }

      // Check if last group was a match
      if (matchCount >= 3) {
        matchFound = true;
        totalMatchedSets++;

        // Remove matched tiles
        slotsToProcess = [
          ...slotsToProcess.slice(0, matchStart),
          ...slotsToProcess.slice(matchStart + matchCount),
        ];
      } else if (matchStart >= 0 && matchCount >= 3) {
        matchFound = true;
        totalMatchedSets++;

        slotsToProcess = [
          ...slotsToProcess.slice(0, matchStart),
          ...slotsToProcess.slice(matchStart + matchCount),
        ];
      } else {
        // No more matches
        break;
      }
    }

    if (matchFound) {
      setSlots(slotsToProcess);
      setStats(prev => ({
        ...prev,
        matches: prev.matches + totalMatchedSets,
        score: prev.score + totalMatchedSets * 100,
      }));

      // Check win condition
      setTimeout(() => {
        checkWinCondition(slotsToProcess);
      }, 100);
    } else {
      // Check lose condition (slots full)
      if (currentSlots.length >= settings.maxSlots) {
        setGameState('lost');
        onGameEnd?.(false, stats);
      }
    }
  }, [settings.maxSlots, stats, onGameEnd]);

  // Check win condition
  const checkWinCondition = useCallback((currentSlots: SlotTile[]) => {
    setTiles(prev => {
      const remaining = prev.filter(t => !t.isMatched && !isSpecialTile(t.type));
      if (remaining.length === 0 && currentSlots.length === 0) {
        setGameState('won');
        onGameEnd?.(true, stats);
      }
      return prev;
    });
  }, [stats, onGameEnd]);

  // Restart game
  const handleRestart = useCallback(() => {
    if (levelData) {
      initGame(levelData);
    }
  }, [levelData, initGame]);

  // Undo last move (simplified - just removes last slot tile)
  const handleUndo = useCallback(() => {
    if (slots.length === 0) return;

    const lastSlot = slots[slots.length - 1];

    // Restore tile to board
    setTiles(prev => {
      const updated = prev.map(t =>
        t.id === lastSlot.id ? { ...t, isMatched: false } : t
      );
      return calculateSelectability(updated);
    });

    // Remove from slots
    setSlots(prev => prev.slice(0, -1));

    // Update stats
    setStats(prev => ({ ...prev, moves: Math.max(0, prev.moves - 1) }));
  }, [slots]);

  // Format time
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  if (!levelData) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center text-gray-400">
          <div className="text-6xl mb-4">🎮</div>
          <div className="text-xl">Select a level to play</div>
        </div>
      </div>
    );
  }

  return (
    <div className="game-player flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-4 bg-gray-800/50 rounded-t-lg">
        <div className="flex items-center gap-4">
          {onBack && (
            <button
              onClick={onBack}
              className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
            >
              ← Back
            </button>
          )}
          <div className="text-lg font-bold">
            {levelInfo?.name || 'Level'}
          </div>
        </div>

        <div className="flex items-center gap-6 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-gray-400">Time:</span>
            <span className="font-mono text-lg">{formatTime(stats.timeElapsed)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-400">Moves:</span>
            <span className="font-mono text-lg">{stats.moves}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-gray-400">Score:</span>
            <span className="font-mono text-lg text-yellow-400">{stats.score}</span>
          </div>
        </div>
      </div>

      {/* Game area */}
      <div className="flex-1 flex flex-col items-center justify-center p-4 gap-6 overflow-auto">
        {/* Game board */}
        <GameBoard
          tiles={tiles}
          onTileClick={handleTileClick}
          tileSize={48}
        />

        {/* Slot area */}
        <SlotArea
          slots={slots}
          maxSlots={settings.maxSlots}
          tileSize={48}
        />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-center gap-4 p-4 bg-gray-800/50 rounded-b-lg">
        <button
          onClick={handleRestart}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded font-medium"
        >
          🔄 Restart
        </button>

        {settings.enableUndo && (
          <button
            onClick={handleUndo}
            disabled={slots.length === 0}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed rounded font-medium"
          >
            ↩️ Undo
          </button>
        )}
      </div>

      {/* Game over overlay */}
      {(gameState === 'won' || gameState === 'lost') && (
        <div className="absolute inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-xl p-8 text-center max-w-sm">
            <div className="text-6xl mb-4">
              {gameState === 'won' ? '🎉' : '😢'}
            </div>
            <div className="text-2xl font-bold mb-2">
              {gameState === 'won' ? 'You Win!' : 'Game Over'}
            </div>
            <div className="text-gray-400 mb-6">
              {gameState === 'won'
                ? `Cleared in ${formatTime(stats.timeElapsed)} with ${stats.moves} moves!`
                : 'Slots are full. Better luck next time!'}
            </div>
            <div className="flex gap-4 justify-center">
              <button
                onClick={handleRestart}
                className="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded font-medium"
              >
                Play Again
              </button>
              {onBack && (
                <button
                  onClick={onBack}
                  className="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded font-medium"
                >
                  Back
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default GamePlayer;
