import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { listFromGBoost, loadFromGBoost, checkGBoostHealth } from '../../api/gboost';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { Skeleton } from '../common/Skeleton';
import type { LevelMetadata, LevelJSON, LevelLayer, TileData } from '../../types';
import { formatTimestamp, getGradeColor, convertServerLevelToFrontend } from '../../utils/helpers';
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

interface LevelBrowserProps {
  className?: string;
}

type SortOption = 'name_asc' | 'name_desc' | 'date_asc' | 'date_desc' | 'difficulty_asc' | 'difficulty_desc';
type ViewMode = 'list' | 'grid';

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
            const pos = `${x}_${y}`;
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

export function LevelBrowser({ className }: LevelBrowserProps) {
  const { setLevel } = useLevelStore();
  const {
    gboostBoardId,
    gboostLevelId,
    setGboostBoardId,
    setGboostLevelId,
    addNotification,
    isLoading,
    setIsLoading,
  } = useUIStore();

  const [levels, setLevels] = useState<LevelMetadata[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('name_asc');
  const [isExpanded, setIsExpanded] = useState(true);
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [thumbnailCache, setThumbnailCache] = useState<Record<string, LevelJSON>>({});
  const [loadingThumbnails, setLoadingThumbnails] = useState<Set<string>>(new Set());

  // Virtualization
  const parentRef = useRef<HTMLDivElement>(null);

  // Check GBoost health on mount
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const health = await checkGBoostHealth();
        setIsConfigured(health.configured && health.healthy !== false);
      } catch {
        setIsConfigured(false);
      }
    };
    checkHealth();
  }, []);

  // Load levels when boardId changes
  const loadLevels = async () => {
    if (!gboostBoardId || !isConfigured) return;

    setIsLoadingList(true);
    try {
      const response = await listFromGBoost(gboostBoardId);
      setLevels(response.levels);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoadingList(false);
    }
  };

  useEffect(() => {
    if (isConfigured) {
      loadLevels();
    }
  }, [gboostBoardId, isConfigured]);

  // Load thumbnail for a level
  const loadThumbnail = useCallback(async (levelId: string) => {
    if (!gboostBoardId || thumbnailCache[levelId] || loadingThumbnails.has(levelId)) {
      return;
    }

    setLoadingThumbnails(prev => new Set(prev).add(levelId));

    try {
      const result = await loadFromGBoost(gboostBoardId, levelId);
      const convertedLevel = convertServerLevelToFrontend(result.level_json as unknown as Record<string, unknown>);
      setThumbnailCache(prev => ({ ...prev, [levelId]: convertedLevel }));
    } catch (error) {
      console.error('Failed to load thumbnail:', error);
    } finally {
      setLoadingThumbnails(prev => {
        const next = new Set(prev);
        next.delete(levelId);
        return next;
      });
    }
  }, [gboostBoardId, thumbnailCache, loadingThumbnails]);

  const handleLoadLevel = async (levelId: string) => {
    if (!gboostBoardId) return;

    setIsLoading(true);
    try {
      // Use cached data if available
      if (thumbnailCache[levelId]) {
        setLevel(thumbnailCache[levelId]);
        setGboostLevelId(levelId);
        addNotification('success', `레벨 ${levelId} 불러오기 완료`);
      } else {
        const result = await loadFromGBoost(gboostBoardId, levelId);
        const convertedLevel = convertServerLevelToFrontend(result.level_json as unknown as Record<string, unknown>);
        setLevel(convertedLevel);
        setGboostLevelId(levelId);
        setThumbnailCache(prev => ({ ...prev, [levelId]: convertedLevel }));
        addNotification('success', `레벨 ${levelId} 불러오기 완료`);
      }
    } catch (error) {
      console.error('Load failed:', error);
      addNotification('error', '레벨을 불러올 수 없습니다');
    } finally {
      setIsLoading(false);
    }
  };

  const getGradeFromDifficulty = (difficulty?: number): string => {
    if (difficulty === undefined) return '?';
    const score = difficulty * 100;
    if (score <= 20) return 'S';
    if (score <= 40) return 'A';
    if (score <= 60) return 'B';
    if (score <= 80) return 'C';
    return 'D';
  };

  const getLevelNumber = (id: string): number => {
    const match = id.match(/\d+/);
    return match ? parseInt(match[0], 10) : 0;
  };

  const filteredLevels = useMemo(() => {
    let result = [...levels];

    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter((level) =>
        level.id.toLowerCase().includes(query)
      );
    }

    result.sort((a, b) => {
      switch (sortOption) {
        case 'name_asc':
          return getLevelNumber(a.id) - getLevelNumber(b.id);
        case 'name_desc':
          return getLevelNumber(b.id) - getLevelNumber(a.id);
        case 'date_asc':
          return (a.created_at || '').localeCompare(b.created_at || '');
        case 'date_desc':
          return (b.created_at || '').localeCompare(a.created_at || '');
        case 'difficulty_asc':
          return (a.difficulty ?? 999) - (b.difficulty ?? 999);
        case 'difficulty_desc':
          return (b.difficulty ?? -1) - (a.difficulty ?? -1);
        default:
          return 0;
      }
    });

    return result;
  }, [levels, searchQuery, sortOption]);

  // Virtual list configuration
  const rowVirtualizer = useVirtualizer({
    count: filteredLevels.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => viewMode === 'list' ? 52 : 80,
    overscan: 5,
  });

  // Load thumbnails for visible items
  useEffect(() => {
    if (viewMode !== 'grid') return;

    const visibleItems = rowVirtualizer.getVirtualItems();
    visibleItems.forEach(virtualItem => {
      const level = filteredLevels[virtualItem.index];
      if (level && !thumbnailCache[level.id] && !loadingThumbnails.has(level.id)) {
        loadThumbnail(level.id);
      }
    });
  }, [rowVirtualizer.getVirtualItems(), viewMode, filteredLevels, thumbnailCache, loadingThumbnails, loadThumbnail]);

  if (isConfigured === false) {
    return (
      <div className={clsx('bg-gray-900 rounded-lg border border-gray-700 p-4', className)}>
        <div className="text-center text-gray-400">
          <span className="text-2xl block mb-2">⚠️</span>
          <p className="text-sm">GBoost 설정이 필요합니다</p>
          <p className="text-xs mt-1 text-gray-500">게임부스트 탭에서 설정하세요</p>
        </div>
      </div>
    );
  }

  const renderListItem = (levelItem: LevelMetadata) => {
    const grade = getGradeFromDifficulty(levelItem.difficulty);
    const gradeColor = getGradeColor(grade as 'S' | 'A' | 'B' | 'C' | 'D');
    const levelNum = getLevelNumber(levelItem.id);
    const isSelected = gboostLevelId === levelItem.id;

    return (
      <div
        onClick={() => handleLoadLevel(levelItem.id)}
        className={clsx(
          'flex items-center gap-2 px-2 py-2 cursor-pointer transition-all border-b border-gray-800 last:border-b-0',
          isSelected
            ? 'bg-sky-900/40 border-l-2 border-l-sky-500'
            : 'hover:bg-gray-800/70 border-l-2 border-l-transparent',
          isLoading && 'opacity-50 pointer-events-none'
        )}
      >
        {/* Level Number */}
        <div className="flex-shrink-0 w-8 h-8 rounded bg-gray-700 flex items-center justify-center">
          <span className="text-xs font-bold text-gray-200">
            {levelNum || '#'}
          </span>
        </div>

        {/* Level Info */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-100 truncate">
            {levelItem.id}
          </div>
          {levelItem.created_at && (
            <div className="text-[10px] text-gray-500">
              {formatTimestamp(levelItem.created_at)}
            </div>
          )}
        </div>

        {/* Grade */}
        {levelItem.difficulty !== undefined ? (
          <div className="flex-shrink-0">
            <span
              className="text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center"
              style={{
                backgroundColor: gradeColor,
                color: 'white',
              }}
            >
              {grade}
            </span>
          </div>
        ) : (
          <div className="w-6 h-6 rounded-full bg-gray-700 flex items-center justify-center">
            <span className="text-[10px] text-gray-500">?</span>
          </div>
        )}

        {/* Selected indicator */}
        {isSelected && (
          <span className="text-[10px] text-sky-400 flex-shrink-0">✓</span>
        )}
      </div>
    );
  };

  const renderGridItem = (levelItem: LevelMetadata) => {
    const grade = getGradeFromDifficulty(levelItem.difficulty);
    const gradeColor = getGradeColor(grade as 'S' | 'A' | 'B' | 'C' | 'D');
    const levelNum = getLevelNumber(levelItem.id);
    const isSelected = gboostLevelId === levelItem.id;
    const thumbnailData = thumbnailCache[levelItem.id];
    const isLoadingThumb = loadingThumbnails.has(levelItem.id);

    return (
      <div
        onClick={() => handleLoadLevel(levelItem.id)}
        className={clsx(
          'flex items-center gap-3 px-2 py-2 cursor-pointer transition-all border-b border-gray-800',
          isSelected
            ? 'bg-sky-900/40 border-l-2 border-l-sky-500'
            : 'hover:bg-gray-800/70 border-l-2 border-l-transparent',
          isLoading && 'opacity-50 pointer-events-none'
        )}
      >
        {/* Thumbnail */}
        <div className="flex-shrink-0 relative">
          {isLoadingThumb ? (
            <div className="w-12 h-12 bg-gray-700 rounded flex items-center justify-center">
              <span className="animate-spin text-xs">⏳</span>
            </div>
          ) : (
            <LevelThumbnail levelData={thumbnailData} size={48} />
          )}
          {/* Level number badge */}
          <div className="absolute -top-1 -left-1 bg-gray-900 border border-gray-600 rounded px-1">
            <span className="text-[10px] font-bold text-gray-200">
              {levelNum || '#'}
            </span>
          </div>
        </div>

        {/* Level Info */}
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-gray-100 truncate">
            {levelItem.id}
          </div>
          {levelItem.created_at && (
            <div className="text-[10px] text-gray-500">
              {formatTimestamp(levelItem.created_at)}
            </div>
          )}
          {/* Grade inline */}
          <div className="flex items-center gap-1 mt-1">
            <span
              className="text-[10px] font-bold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: gradeColor,
                color: 'white',
              }}
            >
              {grade}
            </span>
            {isSelected && (
              <span className="text-[10px] text-sky-400">✓ 선택됨</span>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className={clsx('bg-gray-900 rounded-lg border border-gray-700', className)}>
      {/* Header */}
      <div
        className="flex justify-between items-center px-3 py-2 cursor-pointer hover:bg-gray-800 rounded-t-lg"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-gray-400">{isExpanded ? '▼' : '▶'}</span>
          <label className="text-sm font-bold text-gray-200">☁️ 서버 레벨</label>
          <span className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">
            {levels.length}개
          </span>
        </div>
        <div className="flex items-center gap-1">
          {/* View mode toggle */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              setViewMode(viewMode === 'list' ? 'grid' : 'list');
            }}
            className="px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600"
            title={viewMode === 'list' ? '썸네일 보기' : '리스트 보기'}
          >
            {viewMode === 'list' ? '🖼️' : '📝'}
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              loadLevels();
            }}
            disabled={isLoadingList}
            className="px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-50"
          >
            {isLoadingList ? '⏳' : '🔄'}
          </button>
        </div>
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700">
          {/* Board ID Input */}
          <div className="p-2 border-b border-gray-700 bg-gray-800/50">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-14">보드:</span>
              <input
                type="text"
                value={gboostBoardId}
                onChange={(e) => setGboostBoardId(e.target.value)}
                placeholder="levels"
                className="flex-1 px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded text-gray-200 placeholder-gray-500"
              />
            </div>
          </div>

          {/* Current Level Info (Save disabled) */}
          <div className="p-2 border-b border-gray-700 bg-gray-800/30 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500 w-14">현재:</span>
              <input
                type="text"
                value={gboostLevelId}
                onChange={(e) => setGboostLevelId(e.target.value)}
                placeholder="level_001"
                className="flex-1 px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded text-gray-200 placeholder-gray-500"
                readOnly
              />
              <span className="px-3 py-1 text-xs font-medium rounded bg-gray-700 text-gray-500 cursor-not-allowed" title="저장 기능이 비활성화되었습니다">
                🔒 저장
              </span>
            </div>

            {/* Save disabled notice */}
            <div className="text-[10px] text-yellow-500 bg-yellow-900/20 px-2 py-1 rounded">
              ⚠️ 저장 기능이 비활성화되었습니다 (읽기 전용)
            </div>
          </div>

          {/* Search and Sort */}
          <div className="p-2 space-y-2 border-b border-gray-700 bg-gray-800/50">
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="레벨 검색..."
                className="w-full px-3 py-1.5 pl-8 text-xs bg-gray-700 border border-gray-600 rounded text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500"
              />
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 text-xs">
                🔍
              </span>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-xs"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">정렬:</span>
              <select
                value={sortOption}
                onChange={(e) => setSortOption(e.target.value as SortOption)}
                className="flex-1 px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded text-gray-200 focus:outline-none focus:border-sky-500"
              >
                <option value="name_asc">번호 ↑</option>
                <option value="name_desc">번호 ↓</option>
                <option value="date_desc">최신순</option>
                <option value="date_asc">오래된순</option>
                <option value="difficulty_asc">난이도 낮은순</option>
                <option value="difficulty_desc">난이도 높은순</option>
              </select>
            </div>
          </div>

          {/* Level List with Virtualization */}
          {isLoadingList ? (
            <LevelListSkeleton count={6} />
          ) : filteredLevels.length === 0 ? (
            <div className="text-xs text-gray-500 p-4 text-center">
              {searchQuery ? '검색 결과 없음' : '레벨 없음'}
            </div>
          ) : (
            <div
              ref={parentRef}
              className="overflow-auto"
              style={{ maxHeight: '400px' }}
            >
              <div
                style={{
                  height: `${rowVirtualizer.getTotalSize()}px`,
                  width: '100%',
                  position: 'relative',
                }}
              >
                {rowVirtualizer.getVirtualItems().map((virtualItem) => {
                  const levelItem = filteredLevels[virtualItem.index];
                  return (
                    <div
                      key={levelItem.id}
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: `${virtualItem.size}px`,
                        transform: `translateY(${virtualItem.start}px)`,
                      }}
                    >
                      {viewMode === 'list'
                        ? renderListItem(levelItem)
                        : renderGridItem(levelItem)
                      }
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Footer Stats */}
          {!isLoadingList && levels.length > 0 && (
            <div className="px-2 py-1.5 border-t border-gray-700 bg-gray-800/30 text-[10px] text-gray-500 flex justify-between">
              <span>
                {searchQuery
                  ? `${filteredLevels.length}/${levels.length}개`
                  : `총 ${levels.length}개`}
              </span>
              <div className="flex items-center gap-2">
                {Object.keys(thumbnailCache).length > 0 && (
                  <span className="text-gray-600">
                    캐시: {Object.keys(thumbnailCache).length}
                  </span>
                )}
                {gboostLevelId && (
                  <span className="text-sky-400">현재: {gboostLevelId}</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
