/**
 * PlayTab - 게임 플레이 탭
 * 로컬 또는 GBoost에서 레벨을 선택하고 플레이
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import GamePlayer from '../GamePlayer';
import type { LevelInfo, GameStats } from '../../types/game';
import { listLocalLevels as listLocalLevelsBackend, loadLocalLevel as loadLocalLevelBackend, type LocalLevelListItem } from '../../api/simulate';
import { listLocalLevels as listLocalLevelsStorage, getLocalLevel } from '../../services/localLevelsApi';
import { listFromGBoost, loadFromGBoost, checkGBoostHealth } from '../../api/gboost';

type LevelSource = 'local' | 'gboost';

interface LevelListItem {
  id: string;
  name: string;
  source: LevelSource;
  difficulty?: number;
  createdAt?: string;
}

interface PlayTabProps {
  initialLevelId?: string | null;
  onLevelLoaded?: () => void;
}

// Extract set name from level ID or name (same logic as LocalLevelBrowser)
function extractSetName(levelId: string, levelName: string): string {
  // Pattern 1: "세트명 X - Level Y" format
  const dashLevelMatch = levelName.match(/^(.+?)\s*-\s*Level\s+\d+$/i);
  if (dashLevelMatch) {
    return dashLevelMatch[1].trim();
  }

  // Pattern 2: "세트명_stage_1" or "세트명_level_1"
  const stageMatch = levelName.match(/^(.+?)_(?:stage|level)_\d+$/i);
  if (stageMatch) {
    return stageMatch[1];
  }

  // Try ID pattern
  const idMatch = levelId.match(/^(.+?)_(?:stage|level)_\d+$/i);
  if (idMatch) {
    return idMatch[1];
  }

  // Fallback: extract everything before the last underscore+number
  const fallbackMatch = levelName.match(/^(.+?)_\d+$/);
  if (fallbackMatch) {
    return fallbackMatch[1];
  }

  return '기타';
}

// Natural sort helper
function extractLevelNumber(str: string): number {
  const levelMatch = str.match(/level\s*(\d+)/i);
  if (levelMatch) return parseInt(levelMatch[1]);
  const underscoreMatch = str.match(/_(\d+)$/);
  if (underscoreMatch) return parseInt(underscoreMatch[1]);
  const allNumbers = str.match(/\d+/g);
  if (allNumbers && allNumbers.length > 0) {
    return parseInt(allNumbers[allNumbers.length - 1]);
  }
  return 0;
}

// Group levels by set name
interface LevelSet {
  setName: string;
  levels: LevelListItem[];
  latestDate: string;
}

function groupLevelsBySet(levels: LevelListItem[]): LevelSet[] {
  const setMap = new Map<string, LevelListItem[]>();

  for (const level of levels) {
    const setName = extractSetName(level.id, level.name);
    if (!setMap.has(setName)) {
      setMap.set(setName, []);
    }
    setMap.get(setName)!.push(level);
  }

  const sets: LevelSet[] = [];
  for (const [setName, setLevels] of setMap) {
    // Sort levels within set by natural number order
    setLevels.sort((a, b) => {
      const aNum = extractLevelNumber(a.name);
      const bNum = extractLevelNumber(b.name);
      return aNum - bNum;
    });

    // Find latest date in set
    const latestDate = setLevels.reduce((latest, level) => {
      if (!level.createdAt) return latest;
      const levelDate = new Date(level.createdAt).getTime();
      if (isNaN(levelDate)) return latest;
      const latestTime = latest ? new Date(latest).getTime() : 0;
      return levelDate > latestTime ? level.createdAt : latest;
    }, '');

    sets.push({ setName, levels: setLevels, latestDate });
  }

  // Sort sets by latest date (most recent first)
  sets.sort((a, b) => {
    const aTime = a.latestDate ? new Date(a.latestDate).getTime() : 0;
    const bTime = b.latestDate ? new Date(b.latestDate).getTime() : 0;
    if (isNaN(aTime) && isNaN(bTime)) return 0;
    if (isNaN(aTime)) return 1;
    if (isNaN(bTime)) return -1;
    return bTime - aTime;
  });

  return sets;
}

export function PlayTab({ initialLevelId, onLevelLoaded }: PlayTabProps) {
  // State
  const [source, setSource] = useState<LevelSource>('local');
  const [levels, setLevels] = useState<LevelListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedLevel, setSelectedLevel] = useState<LevelListItem | null>(null);
  const [levelData, setLevelData] = useState<Record<string, unknown> | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [gboostAvailable, setGboostAvailable] = useState(false);
  const [boardId, setBoardId] = useState('levels');
  const [gameHistory, setGameHistory] = useState<Array<{ level: string; won: boolean; stats: GameStats }>>([]);
  const [expandedSets, setExpandedSets] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');

  // Check GBoost availability
  useEffect(() => {
    checkGBoostHealth()
      .then(res => setGboostAvailable(res.configured && res.healthy === true))
      .catch(() => setGboostAvailable(false));
  }, []);

  // Load levels when source changes
  useEffect(() => {
    loadLevels();
  }, [source, boardId]);

  // Handle initial level ID from props
  useEffect(() => {
    if (initialLevelId && levels.length > 0 && !isPlaying) {
      const levelToPlay = levels.find(l => l.id === initialLevelId);
      if (levelToPlay) {
        handleSelectLevel(levelToPlay);
        onLevelLoaded?.();
      }
    }
  }, [initialLevelId, levels, isPlaying]);

  // Load levels from source
  const loadLevels = useCallback(async () => {
    setLoading(true);
    try {
      if (source === 'local') {
        // Load from both localStorage and backend, then merge
        const [storageResult, backendResult] = await Promise.all([
          listLocalLevelsStorage().catch(() => ({ levels: [], count: 0, storage_path: '' })),
          listLocalLevelsBackend().catch(() => ({ levels: [], count: 0, storage_path: '' })),
        ]);

        // Map storage levels
        const storageLevels = storageResult.levels.map((l) => ({
          id: l.id,
          name: l.name || l.id,
          source: 'local' as LevelSource,
          difficulty: typeof l.difficulty === 'string' ? parseFloat(l.difficulty) : undefined,
          createdAt: l.created_at,
          fromStorage: true,
        }));

        // Map backend levels
        const backendLevels = backendResult.levels.map((l: LocalLevelListItem) => ({
          id: l.id,
          name: l.name || l.id,
          source: 'local' as LevelSource,
          difficulty: typeof l.difficulty === 'number' ? l.difficulty : undefined,
          createdAt: l.created_at,
          fromStorage: false,
        }));

        // Merge and deduplicate by ID (prefer storage version)
        const levelMap = new Map<string, LevelListItem & { fromStorage?: boolean }>();
        backendLevels.forEach(l => levelMap.set(l.id, l));
        storageLevels.forEach(l => levelMap.set(l.id, l)); // Storage overwrites backend

        const mergedLevels = Array.from(levelMap.values()).map(({ fromStorage, ...rest }) => rest);
        setLevels(mergedLevels);
      } else {
        const result = await listFromGBoost(boardId, 'level_', 200);
        setLevels(
          result.levels.map(l => ({
            id: l.id,
            name: l.id.replace('level_', ''),
            source: 'gboost' as LevelSource,
            difficulty: l.difficulty ?? undefined,
            createdAt: l.created_at,
          }))
        );
      }
    } catch (error) {
      console.error('Failed to load levels:', error);
      setLevels([]);
    } finally {
      setLoading(false);
    }
  }, [source, boardId]);

  // Group levels into sets
  const groupedLevelSets = useMemo(() => {
    if (searchQuery) return [];
    return groupLevelsBySet(levels);
  }, [levels, searchQuery]);

  // Filtered levels for search
  const filteredLevels = useMemo(() => {
    if (!searchQuery) return [];
    const query = searchQuery.toLowerCase();
    return levels.filter(l => l.name.toLowerCase().includes(query));
  }, [levels, searchQuery]);

  // Toggle set folder expansion
  const toggleSetExpansion = useCallback((setName: string) => {
    setExpandedSets(prev => {
      const newSet = new Set(prev);
      if (newSet.has(setName)) {
        newSet.delete(setName);
      } else {
        newSet.add(setName);
      }
      return newSet;
    });
  }, []);

  // Select and load a level
  const handleSelectLevel = useCallback(async (level: LevelListItem) => {
    setSelectedLevel(level);
    setLoading(true);

    try {
      if (level.source === 'local') {
        // Try localStorage first, then backend
        try {
          const storageResult = await getLocalLevel(level.id);
          if (storageResult.level_data) {
            setLevelData(storageResult.level_data as unknown as Record<string, unknown>);
            setIsPlaying(true);
            return;
          }
        } catch {
          // Fall through to backend
        }

        // Fallback to backend
        const result = await loadLocalLevelBackend(level.id);
        if (result.level_data) {
          setLevelData(result.level_data as unknown as Record<string, unknown>);
        } else {
          setLevelData(result as unknown as Record<string, unknown>);
        }
      } else {
        const result = await loadFromGBoost(boardId, level.id);
        setLevelData(result.level_json as unknown as Record<string, unknown>);
      }
      setIsPlaying(true);
    } catch (error) {
      console.error('Failed to load level:', error);
      alert('레벨을 불러올 수 없습니다');
    } finally {
      setLoading(false);
    }
  }, [boardId]);

  // Handle game end
  const handleGameEnd = useCallback((won: boolean, stats: GameStats) => {
    if (selectedLevel) {
      setGameHistory(prev => [
        { level: selectedLevel.name, won, stats },
        ...prev.slice(0, 9),
      ]);
    }
  }, [selectedLevel]);

  // Back to level selection
  const handleBack = useCallback(() => {
    setIsPlaying(false);
    setLevelData(null);
    setSelectedLevel(null);
  }, []);

  // Level info for game player
  const levelInfo: LevelInfo | undefined = selectedLevel
    ? {
        id: selectedLevel.id,
        name: selectedLevel.name,
        source: selectedLevel.source,
        difficulty: selectedLevel.difficulty,
        totalTiles: 0,
        layers: 0,
      }
    : undefined;

  // Format date
  const formatDate = (dateStr?: string): string => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '';
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}.${month}.${day}`;
  };

  // Playing view
  if (isPlaying && levelData) {
    return (
      <div className="h-full relative">
        <GamePlayer
          levelData={levelData}
          levelInfo={levelInfo}
          onGameEnd={handleGameEnd}
          onBack={handleBack}
        />
      </div>
    );
  }

  const showGroupedView = !searchQuery && groupedLevelSets.length > 0;

  // Level selection view
  return (
    <div className="h-full flex flex-col p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <span>🎮</span>
          <span>플레이</span>
        </h2>

        <div className="flex items-center gap-2">
          <button
            onClick={loadLevels}
            className="px-3 py-1 bg-gray-700 hover:bg-gray-600 rounded text-sm"
          >
            🔄 새로고침
          </button>
        </div>
      </div>

      {/* Source tabs */}
      <div className="flex items-center gap-4 mb-4">
        <div className="flex bg-gray-800 rounded-lg p-1">
          <button
            onClick={() => setSource('local')}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              source === 'local'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            📁 로컬 레벨
          </button>
          <button
            onClick={() => setSource('gboost')}
            disabled={!gboostAvailable}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
              source === 'gboost'
                ? 'bg-blue-600 text-white'
                : 'text-gray-400 hover:text-white'
            } ${!gboostAvailable ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            ☁️ GBoost
          </button>
        </div>

        {source === 'gboost' && (
          <div className="flex items-center gap-2">
            <label className="text-sm text-gray-400">Board:</label>
            <select
              value={boardId}
              onChange={e => setBoardId(e.target.value)}
              className="bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm"
            >
              <option value="levels">levels</option>
              <option value="level">level</option>
            </select>
          </div>
        )}
      </div>

      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="레벨 검색..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full max-w-md px-3 py-2 text-sm bg-gray-700 border border-gray-600 rounded-md text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
        />
      </div>

      {/* Main content */}
      <div className="flex-1 flex gap-4 overflow-hidden">
        {/* Level list */}
        <div className="flex-1 bg-gray-800/50 rounded-lg overflow-hidden flex flex-col">
          <div className="p-3 border-b border-gray-700 flex items-center justify-between">
            <span className="text-sm text-gray-400">
              {levels.length}개 레벨
            </span>
            {showGroupedView && (
              <span className="text-xs text-gray-500">
                {groupedLevelSets.length}개 세트
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center h-32">
                <div className="text-gray-400">로딩 중...</div>
              </div>
            ) : levels.length === 0 ? (
              <div className="flex items-center justify-center h-32">
                <div className="text-gray-400">레벨이 없습니다</div>
              </div>
            ) : showGroupedView ? (
              /* Grouped view by set */
              <div>
                {groupedLevelSets.map((levelSet) => {
                  const isSetExpanded = expandedSets.has(levelSet.setName);

                  return (
                    <div key={levelSet.setName} className="border-b border-gray-700">
                      {/* Set folder header */}
                      <div
                        onClick={() => toggleSetExpansion(levelSet.setName)}
                        className="flex items-center gap-2 px-3 py-2 cursor-pointer bg-gray-750 hover:bg-gray-700 transition-colors"
                      >
                        <span className="text-sm text-gray-300">
                          {isSetExpanded ? '📂' : '📁'}
                        </span>
                        <span className="flex-1 text-sm font-medium text-gray-200 truncate">
                          {levelSet.setName}
                        </span>
                        <span className="text-xs text-gray-400">
                          {levelSet.levels.length}개
                        </span>
                        <span className="text-xs text-gray-500">
                          {formatDate(levelSet.latestDate)}
                        </span>
                        <span className="text-gray-400 text-xs">
                          {isSetExpanded ? '▼' : '▶'}
                        </span>
                      </div>

                      {/* Levels in set */}
                      {isSetExpanded && (
                        <div className="bg-gray-800/50">
                          {levelSet.levels.map((level) => (
                            <div
                              key={level.id}
                              onClick={() => handleSelectLevel(level)}
                              className={`flex items-center gap-3 px-3 py-2 pl-6 border-b border-gray-800/50 cursor-pointer transition-colors ${
                                selectedLevel?.id === level.id
                                  ? 'bg-blue-900/30'
                                  : 'hover:bg-gray-700/50'
                              }`}
                            >
                              <div className="flex-1 min-w-0">
                                <div className="font-medium text-sm truncate">
                                  {level.name.replace(`${levelSet.setName}_`, '').replace(`${levelSet.setName} - `, '')}
                                </div>
                                {level.createdAt && (
                                  <div className="text-xs text-gray-500">
                                    {formatDate(level.createdAt)}
                                  </div>
                                )}
                              </div>
                              {level.difficulty !== undefined && (
                                <div className="text-xs px-2 py-0.5 bg-gray-700 rounded">
                                  D: {(level.difficulty * 100).toFixed(0)}
                                </div>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSelectLevel(level);
                                }}
                                className="px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-xs font-medium"
                              >
                                ▶ 플레이
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              /* Flat view (when searching) */
              <div className="divide-y divide-gray-700/50">
                {filteredLevels.map(level => (
                  <div
                    key={level.id}
                    onClick={() => handleSelectLevel(level)}
                    className={`p-3 cursor-pointer hover:bg-gray-700/50 transition-colors ${
                      selectedLevel?.id === level.id ? 'bg-blue-600/20' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="font-medium">{level.name}</div>
                        {level.createdAt && (
                          <div className="text-xs text-gray-500">
                            {formatDate(level.createdAt)}
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        {level.difficulty !== undefined && (
                          <div className="text-sm px-2 py-0.5 bg-gray-700 rounded">
                            D: {(level.difficulty * 100).toFixed(0)}
                          </div>
                        )}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleSelectLevel(level);
                          }}
                          className="px-3 py-1 bg-green-600 hover:bg-green-500 rounded text-xs font-medium"
                        >
                          ▶ 플레이
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Game history */}
        <div className="w-64 bg-gray-800/50 rounded-lg overflow-hidden flex flex-col">
          <div className="p-3 border-b border-gray-700">
            <span className="text-sm font-medium">최근 플레이</span>
          </div>

          <div className="flex-1 overflow-y-auto">
            {gameHistory.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
                플레이 기록 없음
              </div>
            ) : (
              <div className="divide-y divide-gray-700/50">
                {gameHistory.map((game, idx) => (
                  <div key={idx} className="p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-medium truncate flex-1">
                        {game.level}
                      </span>
                      <span className={game.won ? 'text-green-400' : 'text-red-400'}>
                        {game.won ? '✓' : '✗'}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 flex gap-3">
                      <span>
                        {Math.floor(game.stats.timeElapsed / 60)}:{(game.stats.timeElapsed % 60).toString().padStart(2, '0')}
                      </span>
                      <span>{game.stats.moves} 이동</span>
                      <span>{game.stats.score} 점</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default PlayTab;
