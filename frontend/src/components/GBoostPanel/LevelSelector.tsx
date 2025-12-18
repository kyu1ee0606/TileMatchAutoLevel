import { useState, useEffect, useMemo } from 'react';
import { listFromGBoost } from '../../api/gboost';
import type { LevelMetadata } from '../../types';
import { formatTimestamp, getGradeColor } from '../../utils/helpers';
import clsx from 'clsx';

interface LevelSelectorProps {
  boardId: string;
  onSelect: (levelId: string) => void;
  className?: string;
}

type SortOption = 'name_asc' | 'name_desc' | 'date_asc' | 'date_desc' | 'difficulty_asc' | 'difficulty_desc';

export function LevelSelector({ boardId, onSelect, className }: LevelSelectorProps) {
  const [levels, setLevels] = useState<LevelMetadata[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOption, setSortOption] = useState<SortOption>('name_asc');
  const [isExpanded, setIsExpanded] = useState(true);

  const loadLevels = async () => {
    if (!boardId) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await listFromGBoost(boardId);
      setLevels(response.levels);
    } catch (err) {
      console.error('Failed to load levels:', err);
      setError('레벨 목록을 불러올 수 없습니다');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadLevels();
  }, [boardId]);

  const handleSelect = (levelId: string) => {
    setSelectedId(levelId);
    onSelect(levelId);
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

  // Extract level number from ID for sorting
  const getLevelNumber = (id: string): number => {
    const match = id.match(/\d+/);
    return match ? parseInt(match[0], 10) : 0;
  };

  // Filtered and sorted levels
  const filteredLevels = useMemo(() => {
    let result = [...levels];

    // Filter by search query
    if (searchQuery) {
      const query = searchQuery.toLowerCase();
      result = result.filter((level) =>
        level.id.toLowerCase().includes(query)
      );
    }

    // Sort
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

  return (
    <div className={clsx('bg-gray-900 rounded-lg border border-gray-700', className)}>
      {/* Header */}
      <div
        className="flex justify-between items-center px-3 py-2 cursor-pointer hover:bg-gray-800 rounded-t-lg"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-gray-400">{isExpanded ? '▼' : '▶'}</span>
          <label className="text-sm font-bold text-gray-200">📋 레벨 목록</label>
          <span className="text-xs bg-gray-700 text-gray-400 px-2 py-0.5 rounded-full">
            {levels.length}개
          </span>
        </div>
        <button
          onClick={(e) => {
            e.stopPropagation();
            loadLevels();
          }}
          disabled={isLoading}
          className="px-2 py-1 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600 disabled:opacity-50"
        >
          {isLoading ? '⏳' : '🔄'} 새로고침
        </button>
      </div>

      {isExpanded && (
        <div className="border-t border-gray-700">
          {/* Search and Sort Controls */}
          <div className="p-2 space-y-2 border-b border-gray-700 bg-gray-800/50">
            {/* Search */}
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="레벨 검색..."
                className="w-full px-3 py-1.5 pl-8 text-sm bg-gray-700 border border-gray-600 rounded text-gray-100 placeholder-gray-500 focus:outline-none focus:border-sky-500"
              />
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-500 text-sm">
                🔍
              </span>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Sort */}
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">정렬:</span>
              <select
                value={sortOption}
                onChange={(e) => setSortOption(e.target.value as SortOption)}
                className="flex-1 px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded text-gray-200 focus:outline-none focus:border-sky-500"
              >
                <option value="name_asc">이름 ↑</option>
                <option value="name_desc">이름 ↓</option>
                <option value="date_desc">최신순</option>
                <option value="date_asc">오래된순</option>
                <option value="difficulty_asc">난이도 낮은순</option>
                <option value="difficulty_desc">난이도 높은순</option>
              </select>
            </div>
          </div>

          {/* Level List */}
          {error ? (
            <div className="text-sm text-red-400 p-3 bg-red-900/30 m-2 rounded">
              ⚠️ {error}
            </div>
          ) : isLoading ? (
            <div className="flex items-center justify-center gap-2 p-6 text-gray-400">
              <span className="animate-spin">⏳</span>
              <span className="text-sm">레벨 목록 로딩 중...</span>
            </div>
          ) : filteredLevels.length === 0 ? (
            <div className="text-sm text-gray-500 p-6 text-center">
              {searchQuery ? (
                <div>
                  <span className="text-2xl block mb-2">🔍</span>
                  검색 결과가 없습니다
                </div>
              ) : (
                <div>
                  <span className="text-2xl block mb-2">📭</span>
                  저장된 레벨이 없습니다
                </div>
              )}
            </div>
          ) : (
            <div className="max-h-64 overflow-y-auto">
              {filteredLevels.map((level) => {
                const grade = getGradeFromDifficulty(level.difficulty);
                const gradeColor = getGradeColor(grade as 'S' | 'A' | 'B' | 'C' | 'D');
                const levelNum = getLevelNumber(level.id);
                const isSelected = selectedId === level.id;

                return (
                  <div
                    key={level.id}
                    onClick={() => handleSelect(level.id)}
                    className={clsx(
                      'flex items-center gap-3 px-3 py-2.5 cursor-pointer transition-all border-b border-gray-800 last:border-b-0',
                      isSelected
                        ? 'bg-sky-900/40 border-l-2 border-l-sky-500'
                        : 'hover:bg-gray-800/70 border-l-2 border-l-transparent'
                    )}
                  >
                    {/* Level Number Badge */}
                    <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-gray-700 flex items-center justify-center">
                      <span className="text-sm font-bold text-gray-200">
                        {levelNum || '#'}
                      </span>
                    </div>

                    {/* Level Info */}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-gray-100 truncate">
                          {level.id}
                        </span>
                        {isSelected && (
                          <span className="text-xs text-sky-400">✓ 선택됨</span>
                        )}
                      </div>
                      {level.created_at && (
                        <div className="text-xs text-gray-500 mt-0.5">
                          📅 {formatTimestamp(level.created_at)}
                        </div>
                      )}
                    </div>

                    {/* Difficulty Grade */}
                    {level.difficulty !== undefined ? (
                      <div className="flex-shrink-0 flex flex-col items-center">
                        <span
                          className="text-sm font-bold w-8 h-8 rounded-full flex items-center justify-center"
                          style={{
                            backgroundColor: gradeColor,
                            color: 'white',
                            boxShadow: `0 0 8px ${gradeColor}50`,
                          }}
                        >
                          {grade}
                        </span>
                        <span className="text-[10px] text-gray-500 mt-0.5">
                          {Math.round(level.difficulty * 100)}%
                        </span>
                      </div>
                    ) : (
                      <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gray-700 flex items-center justify-center">
                        <span className="text-xs text-gray-500">?</span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Footer Stats */}
          {!isLoading && levels.length > 0 && (
            <div className="px-3 py-2 border-t border-gray-700 bg-gray-800/30 text-xs text-gray-500 flex justify-between">
              <span>
                {searchQuery
                  ? `검색: ${filteredLevels.length}/${levels.length}개`
                  : `총 ${levels.length}개 레벨`}
              </span>
              {selectedId && (
                <span className="text-sky-400">선택: {selectedId}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
