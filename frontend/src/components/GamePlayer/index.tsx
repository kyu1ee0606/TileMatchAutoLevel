/**
 * GamePlayer - 타일 매칭 게임 플레이어 메인 컴포넌트
 *
 * 백엔드 bot_simulator와 동일한 게임 규칙 사용
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { createGameEngine, type GameEngine, type TileEffectData } from '../../engine/gameEngine';
import GameBoard from './GameBoard';
import SlotArea from './SlotArea';

// UI용 타입 정의
interface GameTile {
  id: string;
  type: string;
  attribute: string;
  layer: number;
  row: number;
  col: number;
  isSelectable: boolean;
  isSelected: boolean;
  isMatched: boolean;
  isHidden: boolean;
  effectData?: TileEffectData;
}

interface SlotTile {
  id: string;
  type: string;
  attribute: string;
  sourceLayer: number;
  sourceRow: number;
  sourceCol: number;
}

interface GameStats {
  moves: number;
  matches: number;
  combos: number;
  score: number;
  timeElapsed: number;
}

interface LevelInfo {
  id: string;
  name: string;
  source: 'local' | 'gboost';
  difficulty?: number;
  totalTiles: number;
  layers: number;
}

type GameState = 'idle' | 'playing' | 'won' | 'lost' | 'paused';

const INITIAL_GAME_STATS: GameStats = {
  moves: 0,
  matches: 0,
  combos: 0,
  score: 0,
  timeElapsed: 0,
};

const DEFAULT_GAME_SETTINGS = {
  maxSlots: 7,
  enableUndo: false, // 새 엔진에서는 undo 미지원
};

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

  // Game engine reference
  const engineRef = useRef<GameEngine | null>(null);

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

    // Create new game engine
    const engine = createGameEngine();
    engine.initializeFromLevel(levelToUse);
    engineRef.current = engine;

    // Update UI state from engine
    updateUIFromEngine(engine);

    setStats(INITIAL_GAME_STATS);
    setGameState('playing');
  }, []);

  // Update UI state from engine
  const updateUIFromEngine = useCallback((engine: GameEngine) => {
    // Get tiles for UI
    const engineTiles = engine.getTilesForUI();
    const uiTiles: GameTile[] = engineTiles.map(t => ({
      id: t.id,
      type: t.type,
      attribute: t.attribute,
      layer: t.layer,
      row: t.row,
      col: t.col,
      isSelectable: t.isSelectable,
      isSelected: false,
      isMatched: t.isMatched,
      isHidden: t.isHidden,
      effectData: t.effectData,
    }));
    setTiles(uiTiles);

    // Get dock tiles for UI
    const engineDockTiles = engine.getDockTilesForUI();
    const uiSlots: SlotTile[] = engineDockTiles.map(t => ({
      id: t.id,
      type: t.type,
      attribute: t.attribute,
      sourceLayer: t.sourceLayer,
      sourceRow: t.sourceRow,
      sourceCol: t.sourceCol,
    }));
    setSlots(uiSlots);
  }, []);

  // Handle tile click
  const handleTileClick = useCallback((tile: GameTile) => {
    if (gameState !== 'playing') return;
    if (!tile.isSelectable) return;

    const engine = engineRef.current;
    if (!engine) return;

    // Parse tile ID to get layer and position
    const parts = tile.id.split('_');
    if (parts.length < 3) return;

    const layerIdx = parseInt(parts[0], 10);
    const position = `${parts[1]}_${parts[2]}`;

    // Try to select tile
    const success = engine.selectTile(layerIdx, position);
    if (!success) return;

    // Update stats
    setStats(prev => ({ ...prev, moves: prev.moves + 1 }));

    // Update UI from engine
    updateUIFromEngine(engine);

    // Check game state
    if (engine.isCleared()) {
      setGameState('won');
      onGameEnd?.(true, { ...stats, moves: stats.moves + 1 });
    } else if (engine.isFailed()) {
      setGameState('lost');
      onGameEnd?.(false, { ...stats, moves: stats.moves + 1 });
    }
  }, [gameState, stats, onGameEnd, updateUIFromEngine]);

  // Restart game
  const handleRestart = useCallback(() => {
    if (levelData) {
      initGame(levelData);
    }
  }, [levelData, initGame]);

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
