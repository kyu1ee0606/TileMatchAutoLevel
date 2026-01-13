import { useState, useEffect, useMemo, useCallback } from 'react';
import { listLocalLevels, getLocalLevel, deleteLocalLevel } from '../../services/localLevelsApi';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { Skeleton } from '../common/Skeleton';
import type { LevelJSON, LevelLayer, TileData } from '../../types';
import { TILE_TYPES, SPECIAL_IMAGES } from '../../types';
import { GBoostUploadModal } from './GBoostUploadModal';
import clsx from 'clsx';

// Extract set name from level ID or name
// Patterns: "세트명_stage_1", "세트명_level_1", or just extract prefix before last underscore+number
function extractSetName(levelId: string, levelName: string): string {
  // Try to extract from name first (more human-readable)
  
  // Pattern 1: "세트명 X - Level Y" format (from auto-generation)
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

  // No set detected - group as "기타"
  return '기타';
}

// Group levels by set name
interface LevelSet {
  setName: string;
  levels: LocalLevelMetadata[];
  latestDate: string;
}

function groupLevelsBySet(levels: LocalLevelMetadata[]): LevelSet[] {
  const setMap = new Map<string, LocalLevelMetadata[]>();

  for (const level of levels) {
    const setName = extractSetName(level.id, level.name);
    if (!setMap.has(setName)) {
      setMap.set(setName, []);
    }
    setMap.get(setName)!.push(level);
  }

  // Natural sort helper - extracts number from anywhere in string
  const extractLevelNumber = (str: string): number => {
    // Try patterns in order of specificity:
    // 1. "Level N" or "level N" pattern
    const levelMatch = str.match(/level\s*(\d+)/i);
    if (levelMatch) return parseInt(levelMatch[1]);
    // 2. "_NNN" at end (e.g., level_001)
    const underscoreMatch = str.match(/_(\d+)$/);
    if (underscoreMatch) return parseInt(underscoreMatch[1]);
    // 3. Any number in the string (use last one)
    const allNumbers = str.match(/\d+/g);
    if (allNumbers && allNumbers.length > 0) {
      return parseInt(allNumbers[allNumbers.length - 1]);
    }
    return 0;
  };

  // Convert to array and sort sets by latest level date
  const sets: LevelSet[] = [];
  for (const [setName, setLevels] of setMap) {
    // Sort levels within set by natural number order
    setLevels.sort((a, b) => {
      const aNum = extractLevelNumber(a.name);
      const bNum = extractLevelNumber(b.name);
      return aNum - bNum;
    });

    // Find latest date in set (handle empty/invalid dates)
    const latestDate = setLevels.reduce((latest, level) => {
      if (!level.created_at) return latest;
      const levelDate = new Date(level.created_at).getTime();
      if (isNaN(levelDate)) return latest;
      const latestTime = latest ? new Date(latest).getTime() : 0;
      return levelDate > latestTime ? level.created_at : latest;
    }, '');

    sets.push({ setName, levels: setLevels, latestDate });
  }

  // Sort sets by latest date (most recent first), empty dates go last
  sets.sort((a, b) => {
    const aTime = a.latestDate ? new Date(a.latestDate).getTime() : 0;
    const bTime = b.latestDate ? new Date(b.latestDate).getTime() : 0;
    if (isNaN(aTime) && isNaN(bTime)) return 0;
    if (isNaN(aTime)) return 1;  // a goes last
    if (isNaN(bTime)) return -1; // b goes last
    return bTime - aTime;
  });

  return sets;
}

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
  onPlay?: (levelId: string) => void;
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

// Gimmick count helper
interface GimmickCounts {
  chain: number;
  frog: number;
  ice: number;
  grass: number;
  link: number;
  bomb: number;
  unknown: number;
  teleport: number;
  curtain: number;
  craft: number;
  stack: number;
}

const GIMMICK_INFO: Record<string, { icon: string; name: string }> = {
  chain: { icon: '⛓️', name: 'Chain' },
  frog: { icon: '🐸', name: 'Frog' },
  ice: { icon: '❄️', name: 'Ice' },
  grass: { icon: '🌿', name: 'Grass' },
  link: { icon: '🔗', name: 'Link' },
  bomb: { icon: '💣', name: 'Bomb' },
  unknown: { icon: '❓', name: 'Unknown' },
  teleport: { icon: '🌀', name: 'Teleport' },
  curtain: { icon: '🎭', name: 'Curtain' },
  craft: { icon: '🎁', name: 'Craft' },
  stack: { icon: '📚', name: 'Stack' },
};

function countGimmicks(levelData?: LevelJSON): GimmickCounts {
  const counts: GimmickCounts = {
    chain: 0, frog: 0, ice: 0, grass: 0, link: 0,
    bomb: 0, unknown: 0, teleport: 0, curtain: 0,
    craft: 0, stack: 0,
  };

  if (!levelData) return counts;

  // Scan all layers (0-7)
  for (let i = 0; i < 8; i++) {
    const layer = (levelData as any)[`layer_${i}`] as LevelLayer | undefined;
    if (!layer?.tiles) continue;

    for (const pos in layer.tiles) {
      const tileData = layer.tiles[pos] as TileData;
      if (!tileData || !Array.isArray(tileData)) continue;

      const [tileType, attribute] = tileData;

      // Count tile type gimmicks (craft, stack)
      if (tileType && typeof tileType === 'string') {
        if (tileType.startsWith('craft_')) counts.craft++;
        else if (tileType.startsWith('stack_')) counts.stack++;
      }

      // Count attribute gimmicks
      if (!attribute) continue;
      if (attribute === 'chain') counts.chain++;
      else if (attribute === 'frog') counts.frog++;
      else if (attribute.startsWith('ice')) counts.ice++;
      else if (attribute.startsWith('grass')) counts.grass++;
      else if (attribute.startsWith('link')) counts.link++;
      else if (attribute === 'bomb') counts.bomb++;
      else if (attribute === 'unknown') counts.unknown++;
      else if (attribute.startsWith('teleport')) counts.teleport++;
      else if (attribute === 'curtain') counts.curtain++;
    }
  }

  return counts;
}

// Gimmick badges component
function GimmickBadges({ levelData, compact = false }: { levelData?: LevelJSON; compact?: boolean }) {
  const counts = countGimmicks(levelData);
  const activeGimmicks = Object.entries(counts).filter(([_, count]) => count > 0);

  if (activeGimmicks.length === 0) return null;

  return (
    <div className={clsx('flex flex-wrap gap-1', compact ? 'max-w-[120px]' : '')}>
      {activeGimmicks.map(([gimmick, count]) => (
        <span
          key={gimmick}
          className="inline-flex items-center gap-0.5 px-1 py-0.5 text-xs bg-gray-700/80 rounded"
          title={`${GIMMICK_INFO[gimmick]?.name}: ${count}개`}
        >
          <span>{GIMMICK_INFO[gimmick]?.icon}</span>
          <span className="text-gray-300">{count}</span>
        </span>
      ))}
    </div>
  );
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
        className={clsx('bg-gradient-to-br from-gray-700 to-gray-800 rounded-lg flex items-center justify-center border border-gray-600', className)}
        style={{ width: size, height: size }}
      >
        <span className="text-gray-400 text-lg">📄</span>
      </div>
    );
  }

  // Find the first non-empty layer for thumbnail (check layers 0-7)
  let displayLayer: LevelLayer | undefined;
  let cols = 8;
  let rows = 8;

  for (let i = 0; i < 8; i++) {
    const layer = (levelData as any)[`layer_${i}`] as LevelLayer | undefined;
    if (layer && layer.tiles && Object.keys(layer.tiles).length > 0) {
      displayLayer = layer;
      cols = parseInt(layer.col) || 8;
      rows = parseInt(layer.row) || 8;
      break;
    }
  }

  if (!displayLayer || !displayLayer.tiles) {
    return (
      <div
        className={clsx('bg-gray-700 rounded flex items-center justify-center', className)}
        style={{ width: size, height: size }}
      >
        <span className="text-gray-500 text-xs">Empty</span>
      </div>
    );
  }

  const tileSize = Math.max(3, Math.floor(size / Math.max(cols, rows)));
  const tiles = displayLayer.tiles;

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

export function LocalLevelBrowser({ className, onPlay }: LocalLevelBrowserProps) {
  const { setLevel } = useLevelStore();
  const { addNotification } = useUIStore();

  const [levels, setLevels] = useState<LocalLevelMetadata[]>([]);
  const [isLoadingList, setIsLoadingList] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('date_desc');
  const [isExpanded, setIsExpanded] = useState(true);
  const [selectedLevelId, setSelectedLevelId] = useState<string | null>(null);
  const [thumbnailCache, setThumbnailCache] = useState<Record<string, LevelJSON>>({});

  // Bulk selection state
  const [isSelectMode, setIsSelectMode] = useState(false);
  const [checkedLevelIds, setCheckedLevelIds] = useState<Set<string>>(new Set());
  const [isDeleting, setIsDeleting] = useState(false);
  const [isGBoostModalOpen, setIsGBoostModalOpen] = useState(false);

  // Folder expansion state (set name -> expanded)
  const [expandedSets, setExpandedSets] = useState<Set<string>>(new Set());

  // Load thumbnail data for levels
  const loadThumbnails = async (levelIds: string[]) => {
    const newCache: Record<string, LevelJSON> = {};

    // Load in parallel with a limit of 5 concurrent requests
    const batchSize = 5;
    for (let i = 0; i < levelIds.length; i += batchSize) {
      const batch = levelIds.slice(i, i + batchSize);
      const results = await Promise.allSettled(
        batch.map(async (id) => {
          if (thumbnailCache[id]) return { id, data: thumbnailCache[id] };
          const level = await getLocalLevel(id);
          return { id, data: level.level_data };
        })
      );

      results.forEach((result) => {
        if (result.status === 'fulfilled') {
          newCache[result.value.id] = result.value.data;
        }
      });
    }

    setThumbnailCache(prev => ({ ...prev, ...newCache }));
  };

  // Load levels on mount
  const loadLevels = async () => {
    setIsLoadingList(true);
    try {
      const response = await listLocalLevels();
      setLevels(response.levels);

      // Load thumbnails for all levels
      if (response.levels.length > 0) {
        const levelIds = response.levels.map(l => l.id);
        loadThumbnails(levelIds);
      }
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

  // Toggle select mode
  const toggleSelectMode = () => {
    setIsSelectMode(!isSelectMode);
    setCheckedLevelIds(new Set());
  };

  // Toggle individual level check
  const toggleLevelCheck = (levelId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setCheckedLevelIds(prev => {
      const newSet = new Set(prev);
      if (newSet.has(levelId)) {
        newSet.delete(levelId);
      } else {
        newSet.add(levelId);
      }
      return newSet;
    });
  };

  // Select all visible levels
  const selectAll = () => {
    const allIds = filteredAndSortedLevels.map(l => l.id);
    setCheckedLevelIds(new Set(allIds));
  };

  // Deselect all
  const deselectAll = () => {
    setCheckedLevelIds(new Set());
  };

  // Bulk delete
  const handleBulkDelete = async () => {
    if (checkedLevelIds.size === 0) return;

    if (!confirm(`선택한 ${checkedLevelIds.size}개의 레벨을 삭제하시겠습니까?`)) return;

    setIsDeleting(true);
    let successCount = 0;
    let failCount = 0;

    for (const levelId of checkedLevelIds) {
      try {
        await deleteLocalLevel(levelId);
        successCount++;
      } catch (err) {
        console.error(`Failed to delete level ${levelId}:`, err);
        failCount++;
      }
    }

    // Update state
    setLevels(prev => prev.filter(l => !checkedLevelIds.has(l.id)));
    if (selectedLevelId && checkedLevelIds.has(selectedLevelId)) {
      setSelectedLevelId(null);
    }
    setCheckedLevelIds(new Set());
    setIsDeleting(false);

    if (failCount === 0) {
      addNotification('success', `${successCount}개의 레벨이 삭제되었습니다`);
    } else {
      addNotification('warning', `${successCount}개 삭제, ${failCount}개 실패`);
    }
  };

  // GBoost upload modal handlers
  const handleGBoostUpload = () => {
    if (checkedLevelIds.size === 0) return;
    setIsGBoostModalOpen(true);
  };

  const handleGBoostUploadComplete = (successCount: number, failCount: number) => {
    if (failCount === 0) {
      addNotification('success', `${successCount}개 레벨 GBoost 업로드 완료`);
    } else {
      addNotification('warning', `${successCount}개 업로드, ${failCount}개 실패`);
    }
    setCheckedLevelIds(new Set());
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

  // Group levels into sets (only when not searching)
  const groupedLevelSets = useMemo(() => {
    // When searching, show flat list instead of grouped
    if (searchQuery) {
      return [];
    }
    return groupLevelsBySet(levels);
  }, [levels, searchQuery]);

  // Check if we should show grouped view
  const showGroupedView = !searchQuery && groupedLevelSets.length > 0;

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

  // Expand all sets
  const expandAllSets = useCallback(() => {
    const allSetNames = groupedLevelSets.map(s => s.setName);
    setExpandedSets(new Set(allSetNames));
  }, [groupedLevelSets]);

  // Collapse all sets
  const collapseAllSets = useCallback(() => {
    setExpandedSets(new Set());
  }, []);

  const getDifficultyColor = (difficulty: string): string => {
    const colors: Record<string, string> = {
      // Grade system colors
      s: '#10B981', // emerald
      a: '#3B82F6', // blue
      b: '#F59E0B', // amber
      c: '#F97316', // orange
      d: '#EF4444', // red
      // Legacy colors
      easy: '#10B981',
      medium: '#F59E0B',
      hard: '#F97316',
      expert: '#EF4444',
      impossible: '#7C3AED',
      custom: '#6366F1',
    };
    return colors[difficulty.toLowerCase()] || '#6B7280';
  };

  const getStatusIcon = (status: string): string => {
    const icons: Record<string, string> = {
      pass: '✅',
      warn: '⚠️',
      fail: '❌',
      unknown: '',
    };
    return icons[status] || '';
  };

  const formatDate = (dateStr: string): string => {
    if (!dateStr) return '';
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return '';
    // Format: 2026.01.09 14:35
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}.${month}.${day} ${hours}:${minutes}`;
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
        <div className="flex items-center gap-1">
          {showGroupedView && (
            <>
              <button
                onClick={expandAllSets}
                className="p-1.5 hover:bg-gray-700 rounded-md transition-colors text-xs"
                title="모두 펼치기"
              >
                ⬇️
              </button>
              <button
                onClick={collapseAllSets}
                className="p-1.5 hover:bg-gray-700 rounded-md transition-colors text-xs"
                title="모두 접기"
              >
                ⬆️
              </button>
            </>
          )}
          <button
            onClick={toggleSelectMode}
            className={clsx(
              'px-2 py-1 text-xs rounded-md transition-colors',
              isSelectMode
                ? 'bg-primary-600 text-white'
                : 'hover:bg-gray-700 text-gray-400'
            )}
            title={isSelectMode ? '선택 모드 종료' : '일괄 선택'}
          >
            ☑️
          </button>
          <button
            onClick={loadLevels}
            className="p-1.5 hover:bg-gray-700 rounded-md transition-colors"
            title="새로고침"
          >
            🔄
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {isSelectMode && isExpanded && (
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/50 border-b border-gray-700">
          <button
            onClick={selectAll}
            className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 rounded transition-colors"
          >
            전체 선택
          </button>
          <button
            onClick={deselectAll}
            className="px-2 py-1 text-xs bg-gray-600 hover:bg-gray-500 rounded transition-colors"
          >
            선택 해제
          </button>
          <div className="flex-1" />
          <span className="text-xs text-gray-400">
            {checkedLevelIds.size}개 선택
          </span>
          <button
            onClick={handleGBoostUpload}
            disabled={checkedLevelIds.size === 0}
            className={clsx(
              'px-3 py-1 text-xs rounded transition-colors',
              checkedLevelIds.size === 0
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            )}
          >
            ☁️ GBoost 업로드
          </button>
          <button
            onClick={handleBulkDelete}
            disabled={checkedLevelIds.size === 0 || isDeleting}
            className={clsx(
              'px-3 py-1 text-xs rounded transition-colors',
              checkedLevelIds.size === 0 || isDeleting
                ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-500 text-white'
            )}
          >
            {isDeleting ? '삭제 중...' : '🗑️ 일괄 삭제'}
          </button>
        </div>
      )}

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
            ) : levels.length === 0 ? (
              <div className="p-8 text-center text-sm text-gray-400">
                <p className="mb-2">로컬 레벨이 없습니다</p>
                <p className="text-xs">자동 생성 탭에서 레벨을 생성하세요</p>
              </div>
            ) : showGroupedView ? (
              /* Grouped view by set */
              <div>
                {groupedLevelSets.map((levelSet) => {
                  const isSetExpanded = expandedSets.has(levelSet.setName);
                  const setLevelIds = levelSet.levels.map(l => l.id);
                  const checkedInSet = setLevelIds.filter(id => checkedLevelIds.has(id)).length;

                  return (
                    <div key={levelSet.setName} className="border-b border-gray-700">
                      {/* Set folder header */}
                      <div
                        onClick={() => toggleSetExpansion(levelSet.setName)}
                        className={clsx(
                          'flex items-center gap-2 px-3 py-2 cursor-pointer transition-colors',
                          'bg-gray-750 hover:bg-gray-700'
                        )}
                      >
                        <span className="text-sm text-gray-300">
                          {isSetExpanded ? '📂' : '📁'}
                        </span>
                        <span className="flex-1 text-sm font-medium text-gray-200 truncate">
                          {levelSet.setName}
                        </span>
                        <span className="text-xs text-gray-400">
                          {levelSet.levels.length}개
                          {checkedInSet > 0 && isSelectMode && (
                            <span className="ml-1 text-blue-400">({checkedInSet} 선택)</span>
                          )}
                        </span>
                        <span className="text-xs text-gray-300 bg-gray-700/50 px-1.5 py-0.5 rounded">
                          📅 {formatDate(levelSet.latestDate) || '날짜 없음'}
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
                              onClick={() => isSelectMode ? toggleLevelCheck(level.id, { stopPropagation: () => {} } as React.MouseEvent) : handleLevelClick(level.id)}
                              className={clsx(
                                'flex items-center gap-3 px-3 py-2 pl-6 border-b border-gray-800/50 cursor-pointer transition-colors',
                                checkedLevelIds.has(level.id)
                                  ? 'bg-blue-900/30 border-blue-700'
                                  : selectedLevelId === level.id
                                  ? 'bg-primary-900/30 border-primary-700'
                                  : 'hover:bg-gray-700/50'
                              )}
                            >
                              {/* Checkbox in select mode */}
                              {isSelectMode && (
                                <input
                                  type="checkbox"
                                  checked={checkedLevelIds.has(level.id)}
                                  onChange={(e) => toggleLevelCheck(level.id, e as unknown as React.MouseEvent)}
                                  onClick={(e) => e.stopPropagation()}
                                  className="w-4 h-4 rounded border-gray-500 text-primary-600 focus:ring-primary-500 bg-gray-700"
                                />
                              )}

                              {/* Thumbnail */}
                              <LevelThumbnail
                                levelData={thumbnailCache[level.id]}
                                size={40}
                                className="flex-shrink-0"
                              />

                              {/* Info */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-0.5">
                                  <span className="text-sm font-medium text-gray-100 truncate">
                                    {level.name.replace(`${levelSet.setName}_`, '')}
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
                                  {getStatusIcon(level.validation_status) && (
                                    <span>{getStatusIcon(level.validation_status)}</span>
                                  )}
                                  <span>{formatDate(level.created_at) || '방금 생성'}</span>
                                </div>
                                {/* Gimmick badges */}
                                <GimmickBadges levelData={thumbnailCache[level.id]} compact />
                              </div>

                              {/* Action Buttons */}
                              <div className="flex items-center gap-1">
                                {onPlay && (
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      onPlay(level.id);
                                    }}
                                    className="p-1.5 text-gray-400 hover:text-green-400 hover:bg-green-900/20 rounded-md transition-colors"
                                    title="플레이"
                                  >
                                    ▶️
                                  </button>
                                )}
                                <button
                                  onClick={(e) => handleDelete(level.id, e)}
                                  className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-md transition-colors"
                                  title="삭제"
                                >
                                  🗑️
                                </button>
                              </div>
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
              <div>
                {filteredAndSortedLevels.map((level) => (
                  <div
                    key={level.id}
                    onClick={() => isSelectMode ? toggleLevelCheck(level.id, { stopPropagation: () => {} } as React.MouseEvent) : handleLevelClick(level.id)}
                    className={clsx(
                      'flex items-center gap-3 px-3 py-2 border-b border-gray-800 cursor-pointer transition-colors',
                      checkedLevelIds.has(level.id)
                        ? 'bg-blue-900/30 border-blue-700'
                        : selectedLevelId === level.id
                        ? 'bg-primary-900/30 border-primary-700'
                        : 'hover:bg-gray-700/50'
                    )}
                  >
                    {/* Checkbox in select mode */}
                    {isSelectMode && (
                      <input
                        type="checkbox"
                        checked={checkedLevelIds.has(level.id)}
                        onChange={(e) => toggleLevelCheck(level.id, e as unknown as React.MouseEvent)}
                        onClick={(e) => e.stopPropagation()}
                        className="w-4 h-4 rounded border-gray-500 text-primary-600 focus:ring-primary-500 bg-gray-700"
                      />
                    )}

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
                        {getStatusIcon(level.validation_status) && (
                          <span>{getStatusIcon(level.validation_status)}</span>
                        )}
                        <span>{formatDate(level.created_at) || '방금 생성'}</span>
                      </div>
                      {/* Gimmick badges */}
                      <GimmickBadges levelData={thumbnailCache[level.id]} compact />
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center gap-1">
                      {onPlay && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onPlay(level.id);
                          }}
                          className="p-1.5 text-gray-400 hover:text-green-400 hover:bg-green-900/20 rounded-md transition-colors"
                          title="플레이"
                        >
                          ▶️
                        </button>
                      )}
                      <button
                        onClick={(e) => handleDelete(level.id, e)}
                        className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-red-900/20 rounded-md transition-colors"
                        title="삭제"
                      >
                        🗑️
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {/* GBoost Upload Modal */}
      <GBoostUploadModal
        isOpen={isGBoostModalOpen}
        onClose={() => setIsGBoostModalOpen(false)}
        levelIds={Array.from(checkedLevelIds)}
        onComplete={handleGBoostUploadComplete}
      />
    </div>
  );
}
