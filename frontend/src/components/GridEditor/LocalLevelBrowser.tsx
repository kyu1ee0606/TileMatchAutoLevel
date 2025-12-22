import { useState, useEffect, useMemo } from 'react';
import { listLocalLevels, getLocalLevel, deleteLocalLevel } from '../../services/localLevelsApi';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { Skeleton } from '../common/Skeleton';
import type { LevelJSON, LevelLayer, TileData } from '../../types';
import { TILE_TYPES, SPECIAL_IMAGES } from '../../types';
import clsx from 'clsx';

// Skeleton for level list loading
function LevelListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="animate-pulse">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="flex items-center gap-2 px-2 py-2 border-b border-gray-800">
          <Skeleton variant="rectangular" width={32} height={32} className="rounded" />
          <div className="flex-1 space-y-1">
            <Skeleton variant="text" height={14} className="w-2/3" />
            <Skeleton variant="text" height={10} className="w-1/3" />
          </div>
          <Skeleton variant="circular" width={24} height={24} />
        </div>
      ))}
    </div>
  );
}

interface LocalLevelBrowserProps {
  className?: string;
}

type SortOption = 'name_asc' | 'name_desc' | 'date_asc' | 'date_desc' | 'difficulty_asc' | 'difficulty_desc';

interface LocalLevelMetadata {
  id: string;
  name: string;
  description: string;
  tags: string[];
  difficulty: string;
  created_at: string;
  source: string;
  validation_status: string;
}

// Mini thumbnail component for level preview
interface LevelThumbnailProps {
  levelData?: LevelJSON;
  size?: number;
  className?: string;
}

function LevelThumbnail({ levelData, size = 48, className }: LevelThumbnailProps) {
  if (!levelData) {
    return (
      <div
        className={clsx('bg-gray-700 rounded flex items-center justify-center', className)}
        style={{ width: size, height: size }}
      >
        <span className="text-gray-500 text-xs">?</span>
      </div>
    );
  }

  // Get layer 0 data for thumbnail
  const layer0 = levelData.layer_0 as LevelLayer | undefined;
  if (!layer0 || !layer0.tiles) {
    return (
      <div
        className={clsx('bg-gray-700 rounded flex items-center justify-center', className)}
        style={{ width: size, height: size }}
      >
        <span className="text-gray-500 text-xs">Empty</span>
      </div>
    );
  }

  const cols = parseInt(layer0.col) || 8;
  const rows = parseInt(layer0.row) || 8;
  const tileSize = Math.max(3, Math.floor(size / Math.max(cols, rows)));
  const tiles = layer0.tiles;

  return (
    <div
      className={clsx('bg-gray-800 rounded overflow-hidden flex items-center justify-center', className)}
      style={{ width: size, height: size }}
    >
      <div
        className="grid"
        style={{
          gridTemplateColumns: `repeat(${cols}, ${tileSize}px)`,
          gap: '0px',
        }}
      >
        {Array.from({ length: rows }, (_, y) =>
          Array.from({ length: cols }, (_, x) => {
            const pos = `${y + 1}_${x + 1}`;
            const tileData = tiles[pos] as TileData | undefined;

            if (!tileData) {
              return (
                <div
                  key={pos}
                  style={{
                    width: tileSize,
                    height: tileSize,
                    backgroundColor: '#374151'
                  }}
                />
              );
            }

            const [tileType, attribute] = tileData;
            const tileInfo = TILE_TYPES[tileType];
            const attrImage = attribute ? SPECIAL_IMAGES[attribute] : null;

            return (
              <div
                key={pos}
                className="relative"
                style={{
                  width: tileSize,
                  height: tileSize,
                  backgroundColor: tileInfo?.color || '#888',
                }}
              >
                {tileInfo?.image && tileSize >= 8 && (
                  <img
                    src={tileInfo.image}
                    alt=""
                    className="w-full h-full object-cover"
                    draggable={false}
                  />
                )}
                {attrImage && tileSize >= 8 && (
                  <img
                    src={attrImage}
                    alt=""
                    className="absolute inset-0 w-full h-full object-cover opacity-70"
                    draggable={false}
                  />
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export function LocalLevelBrowser({ className }: LocalLevelBrowserProps) {
  const { setLevel } = useLevelStore();
  const { addNotification } = useUIStore();

  const [levels, setLevels] = useState<LocalLevelMetadata[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('date_desc');
  const [isExpanded, setIsExpanded] = useState(true);
  const [selectedLevelId, setSelectedLevelId] = useState<string | null>(null);
  const [thumbnailCache, setThumbnailCache] = useState<Record<string, LevelJSON>>({});

  // Load levels on mount
  const loadLevels = async () => {
    setIsLoadingList(true);
    try {
      const response = await listLocalLevels();
      setLevels(response.levels);
    } catch (err) {
      console.error('Failed to load local levels:', err);
      addNotification('error', '로컬 레벨 목록을 불러올 수 없습니다');
    } finally {
      setIsLoadingList(false);
    }
  };

  useEffect(() => {
    loadLevels();
  }, []);

  // Load level data when clicked
  const handleLevelClick = async (levelId: string) => {
    try {
      setSelectedLevelId(levelId);
      const level = await getLocalLevel(levelId);
      setLevel(level.level_data);
      addNotification('success', `레벨 "${level.metadata.name}"을(를) 불러왔습니다`);

      // Cache thumbnail data
      if (!thumbnailCache[levelId]) {
        setThumbnailCache(prev => ({ ...prev, [levelId]: level.level_data }));
      }
    } catch (err) {
      console.error('Failed to load level:', err);
      addNotification('error', '레벨을 불러올 수 없습니다');
    }
  };

  // Delete level
  const handleDelete = async (levelId: string, e: React.MouseEvent) => {
    e.stopPropagation();

    if (!confirm(`레벨을 삭제하시겠습니까?`)) return;

    try {
      await deleteLocalLevel(levelId);
      setLevels(prev => prev.filter(l => l.id !== levelId));
      if (selectedLevelId === levelId) {
        setSelectedLevelId(null);
      }
      addNotification('success', '레벨이 삭제되었습니다');
    } catch (err) {
      console.error('Failed to delete level:', err);
      addNotification('error', '레벨 삭제에 실패했습니다');
    }
  };

  // Filter and sort levels
  const filteredAndSortedLevels = useMemo(() => {
    let filtered = levels;

    // Search filter
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (level) =>
          level.name.toLowerCase().includes(query) ||
          level.description.toLowerCase().includes(query) ||
          level.tags.some(tag => tag.toLowerCase().includes(query))
      );
    }

    // Sort
    const sorted = [...filtered].sort((a, b) => {
      switch (sortOption) {
        case 'name_asc':
          return a.name.localeCompare(b.name);
        case 'name_desc':
          return b.name.localeCompare(a.name);
        case 'date_asc':
          return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        case 'date_desc':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'difficulty_asc':
          return a.difficulty.localeCompare(b.difficulty);
        case 'difficulty_desc':
          return b.difficulty.localeCompare(a.difficulty);
        default:
          return 0;
      }
    });

    return sorted;
  }, [levels, searchQuery, sortOption]);

  const getDifficultyColor = (difficulty: string): string => {
    const colors: Record<string, string> = {
      easy: '#4CAF50',
      medium: '#FF9800',
      hard: '#F44336',
      expert: '#9C27B0',
      impossible: '#000000',
      custom: '#2196F3',
    };
    return colors[difficulty.toLowerCase()] || '#757575';
  };

  const getStatusIcon = (status: string): string => {
    const icons: Record<string, string> = {
      pass: '✅',
      warn: '⚠️',
      fail: '❌',
      unknown: '❓',
    };
    return icons[status] || '❓';
  };

  return (
    <div className={clsx('flex flex-col bg-gray-800 rounded-xl shadow-lg border border-gray-700', className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-gray-700">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-100 hover:text-gray-300"
        >
          <span className="text-base">{isExpanded ? '▼' : '▶'}</span>
          <span>💾 로컬 레벨</span>
          <span className="text-xs text-gray-400">({levels.length})</span>
        </button>
        <div className="flex items-center gap-2">
          <button
            onClick={loadLevels}
            className="p-1.5 hover:bg-gray-700 rounded-md transition-colors"
            title="새로고침"
          >
            🔄
          </button>
        </div>
      </div>

      {isExpanded && (
        <>
          {/* Search and Sort */}
          <div className="p-3 space-y-2 border-b border-gray-700">
            <input
              type="text"
              placeholder="레벨 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded-md text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
            <select
              value={sortOption}
              onChange={(e) => setSortOption(e.target.value as SortOption)}
              className="w-full px-2 py-1.5 text-xs bg-gray-700 border border-gray-600 rounded-md text-gray-100"
            >
              <option value="date_desc">최신순</option>
              <option value="date_asc">오래된순</option>
              <option value="name_asc">이름 (A-Z)</option>
              <option value="name_desc">이름 (Z-A)</option>
              <option value="difficulty_asc">난이도 (쉬움→어려움)</option>
              <option value="difficulty_desc">난이도 (어려움→쉬움)</option>
            </select>
          </div>

          {/* Level List */}
          <div className="flex-1 overflow-y-auto max-h-[600px]">
            {isLoadingList ? (
              <LevelListSkeleton />
            ) : filteredAndSortedLevels.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400">
                <p className="mb-2">로컬 레벨이 없습니다</p>
                <p className="text-xs">자동 생성 탭에서 레벨을 생성하세요</p>
              </div>
            ) : (
              <div>
                {filteredAndSortedLevels.map((level) => (
                  <div
                    key={level.id}
                    onClick={() => handleLevelClick(level.id)}
                    className={clsx(
                      'flex items-center gap-3 px-3 py-2 border-b border-gray-800 cursor-pointer transition-colors',
                      selectedLevelId === level.id
                        ? 'bg-primary-900/30 border-primary-700'
                        : 'hover:bg-gray-700/50'
                    )}
                  >
                    {/* Thumbnail */}
                    <LevelThumbnail
                      levelData={thumbnailCache[level.id]}
                      size={48}
                      className="flex-shrink-0"
                    />

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-medium text-gray-100 truncate">
                          {level.name}
                        </span>
                        <span
                          className="px-1.5 py-0.5 text-xs font-semibold rounded"
                          style={{
                            backgroundColor: getDifficultyColor(level.difficulty),
                            color: 'white',
                          }}
                        >
                          {level.difficulty.toUpperCase()}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        <span>{getStatusIcon(level.validation_status)}</span>
                        <span>{new Date(level.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>

                    {/* Delete Button */}
                    <button
                      onClick={(e) => handleDelete(level.id, e)}
                      className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-md transition-colors"
                      title="삭제"
                    >
                      🗑️
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
