/**
 * WorkScopeFilter
 * 작업 범위 필터링 - 레벨 범위 및 담당자별 필터
 * P2: 외부 계약자의 협업 효율 향상
 */

import { useState, useEffect } from 'react';
import { getProductionLevelsByBatch } from '../../storage/productionStorage';
import { Target, Users, BarChart3, Filter } from 'lucide-react';

interface WorkScopeStats {
  total: number;
  generated: number;
  playtestRequired: number;
  reviewing: number;
  approved: number;
}

interface WorkScopeFilterProps {
  batchId: string;
  onFilterChange: (range: { min: number; max: number } | null) => void;
  totalLevels?: number;
}

export function WorkScopeFilter({ batchId, onFilterChange, totalLevels = 1500 }: WorkScopeFilterProps) {
  const [rangeStart, setRangeStart] = useState(1);
  const [rangeEnd, setRangeEnd] = useState(500);
  const [isActive, setIsActive] = useState(false);
  const [assignee, setAssignee] = useState('');
  const [stats, setStats] = useState<WorkScopeStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  // 담당자 프리셋 목록 (실제 사용시 동적으로 관리 가능)
  const assigneePresets = [
    { id: 'all', name: '전체', range: { min: 1, max: totalLevels } },
    { id: 'designer_a', name: '디자이너 A', range: { min: 1, max: 500 } },
    { id: 'designer_b', name: '디자이너 B', range: { min: 501, max: 1000 } },
    { id: 'designer_c', name: '디자이너 C', range: { min: 1001, max: 1500 } },
  ];

  // 범위별 통계 계산
  useEffect(() => {
    if (!isActive) {
      setStats(null);
      return;
    }
    calculateStats();
  }, [batchId, rangeStart, rangeEnd, isActive]);

  const calculateStats = async () => {
    setIsLoading(true);
    try {
      const allLevels = await getProductionLevelsByBatch(batchId);
      const filteredLevels = allLevels.filter(
        l => l.meta.level_number >= rangeStart && l.meta.level_number <= rangeEnd
      );

      const newStats: WorkScopeStats = {
        total: filteredLevels.length,
        generated: filteredLevels.filter(l => l.meta.status === 'generated').length,
        playtestRequired: filteredLevels.filter(l => l.meta.playtest_required && l.meta.status !== 'approved').length,
        reviewing: filteredLevels.filter(l => l.meta.status === 'needs_rework').length,
        approved: filteredLevels.filter(l => l.meta.status === 'approved' || l.meta.status === 'exported').length,
      };

      setStats(newStats);
    } catch (err) {
      console.error('Failed to calculate stats:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleApplyFilter = () => {
    setIsActive(true);
    onFilterChange({ min: rangeStart, max: rangeEnd });
  };

  const handleClearFilter = () => {
    setIsActive(false);
    setAssignee('');
    onFilterChange(null);
  };

  const handleAssigneeChange = (assigneeId: string) => {
    setAssignee(assigneeId);
    const preset = assigneePresets.find(p => p.id === assigneeId);
    if (preset && preset.id !== 'all') {
      setRangeStart(preset.range.min);
      setRangeEnd(preset.range.max);
      setIsActive(true);
      onFilterChange(preset.range);
    } else if (assigneeId === 'all') {
      handleClearFilter();
    }
  };

  const handleQuickRange = (start: number, end: number) => {
    setRangeStart(start);
    setRangeEnd(end);
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-white flex items-center gap-2">
          <Target className="w-4 h-4 text-indigo-400" />
          작업 범위 설정
        </h3>
        {isActive && (
          <button
            onClick={handleClearFilter}
            className="text-xs text-gray-400 hover:text-white"
          >
            필터 해제
          </button>
        )}
      </div>

      {/* Assignee Selector */}
      <div>
        <label className="block text-xs text-gray-400 mb-2 flex items-center gap-1">
          <Users className="w-3 h-3" />
          담당자
        </label>
        <select
          value={assignee}
          onChange={(e) => handleAssigneeChange(e.target.value)}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
        >
          <option value="">담당자 선택...</option>
          {assigneePresets.map(preset => (
            <option key={preset.id} value={preset.id}>
              {preset.name} ({preset.range.min}~{preset.range.max})
            </option>
          ))}
        </select>
      </div>

      {/* Range Input */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">레벨 범위</label>
        <div className="flex items-center gap-2">
          <input
            type="number"
            value={rangeStart}
            onChange={(e) => setRangeStart(Math.max(1, Math.min(totalLevels, Number(e.target.value))))}
            min={1}
            max={totalLevels}
            className="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white text-center"
          />
          <span className="text-gray-400">~</span>
          <input
            type="number"
            value={rangeEnd}
            onChange={(e) => setRangeEnd(Math.max(1, Math.min(totalLevels, Number(e.target.value))))}
            min={1}
            max={totalLevels}
            className="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white text-center"
          />
        </div>
      </div>

      {/* Quick Range Buttons */}
      <div className="flex gap-1 flex-wrap">
        <button
          onClick={() => handleQuickRange(1, 500)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
        >
          1~500
        </button>
        <button
          onClick={() => handleQuickRange(501, 1000)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
        >
          501~1000
        </button>
        <button
          onClick={() => handleQuickRange(1001, 1500)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
        >
          1001~1500
        </button>
        <button
          onClick={() => handleQuickRange(1, 100)}
          className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded text-gray-300"
        >
          튜토리얼 (1~100)
        </button>
      </div>

      {/* Apply Button */}
      <button
        onClick={handleApplyFilter}
        className={`w-full py-2 rounded text-sm font-medium transition-colors ${
          isActive
            ? 'bg-indigo-600 text-white'
            : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
        }`}
      >
        <Filter className="w-4 h-4 inline mr-1" />
        {isActive ? `필터 적용 중 (${rangeStart}~${rangeEnd})` : '내 범위만 보기'}
      </button>

      {/* Stats Display */}
      {isActive && stats && (
        <div className="p-3 bg-gray-700/50 rounded-lg space-y-2">
          <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
            <BarChart3 className="w-3 h-3" />
            내 작업 현황
          </div>
          {isLoading ? (
            <div className="text-center text-gray-400 text-xs py-2">계산 중...</div>
          ) : (
            <div className="space-y-1.5">
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">전체</span>
                <span className="text-white font-medium">{stats.total}개</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">생성 완료</span>
                <span className="text-blue-300">{stats.generated}개</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">플레이테스트 필요</span>
                <span className="text-yellow-300">{stats.playtestRequired}개</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">검토 대기</span>
                <span className="text-orange-300">{stats.reviewing}개</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-400">승인됨</span>
                <span className="text-green-300">{stats.approved}개</span>
              </div>

              {/* Progress Bar */}
              <div className="mt-2 pt-2 border-t border-gray-600">
                <div className="flex justify-between text-xs text-gray-400 mb-1">
                  <span>완료율</span>
                  <span>{stats.total > 0 ? ((stats.approved / stats.total) * 100).toFixed(0) : 0}%</span>
                </div>
                <div className="h-2 bg-gray-600 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-500 transition-all"
                    style={{ width: `${stats.total > 0 ? (stats.approved / stats.total) * 100 : 0}%` }}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
