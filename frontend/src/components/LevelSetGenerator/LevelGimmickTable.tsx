import { useState, useMemo } from 'react';
import type { LevelGimmickOverride, DifficultyPoint } from '../../types/levelSet';
import { interpolateDifficulties, getGradeFromDifficulty } from '../../types/levelSet';

const OBSTACLE_TYPES = [
  { id: 'chain', label: '⛓️ Chain' },
  { id: 'frog', label: '🐸 Frog' },
  { id: 'link', label: '🔗 Link' },
  { id: 'grass', label: '🌿 Grass' },
  { id: 'ice', label: '❄️ Ice' },
  { id: 'bomb', label: '💣 Bomb' },
  { id: 'curtain', label: '🎭 Curtain' },
] as const;

// Grade-based gimmick recommendations (matching backend gimmick_profile.py)
const GRADE_GIMMICK_RECOMMENDATIONS: Record<string, string[]> = {
  S: [],
  A: ['chain'],
  B: ['chain', 'frog'],
  C: ['chain', 'frog', 'ice'],
  D: ['chain', 'frog', 'ice', 'bomb', 'curtain'],
};

interface LevelGimmickTableProps {
  levelCount: number;
  difficultyPoints: DifficultyPoint[];
  availableGimmicks: string[];
  overrides: LevelGimmickOverride[];
  onOverridesChange: (overrides: LevelGimmickOverride[]) => void;
  disabled?: boolean;
}

export function LevelGimmickTable({
  levelCount,
  difficultyPoints,
  availableGimmicks,
  overrides,
  onOverridesChange,
  disabled,
}: LevelGimmickTableProps) {
  const [expandedLevel, setExpandedLevel] = useState<number | null>(null);

  // Calculate difficulties and grades for each level
  const levelInfos = useMemo(() => {
    const difficulties = interpolateDifficulties(difficultyPoints, levelCount);
    return difficulties.map((diff, i) => ({
      levelIndex: i + 1,
      difficulty: diff,
      grade: getGradeFromDifficulty(diff),
    }));
  }, [difficultyPoints, levelCount]);

  const getOverrideForLevel = (levelIndex: number) => {
    return overrides.find(o => o.levelIndex === levelIndex);
  };

  const toggleOverride = (levelIndex: number) => {
    const existing = getOverrideForLevel(levelIndex);
    if (existing) {
      // Remove override
      onOverridesChange(overrides.filter(o => o.levelIndex !== levelIndex));
    } else {
      // Add override with recommended gimmicks for this grade
      const levelInfo = levelInfos.find(l => l.levelIndex === levelIndex);
      const recommendedGimmicks = levelInfo
        ? GRADE_GIMMICK_RECOMMENDATIONS[levelInfo.grade] || []
        : [];
      // Filter to only include available gimmicks
      const defaultGimmicks = recommendedGimmicks.filter(g => availableGimmicks.includes(g));
      onOverridesChange([...overrides, { levelIndex, gimmicks: defaultGimmicks }]);
    }
    setExpandedLevel(expandedLevel === levelIndex ? null : levelIndex);
  };

  const updateOverrideGimmicks = (levelIndex: number, gimmicks: string[]) => {
    onOverridesChange(
      overrides.map(o =>
        o.levelIndex === levelIndex ? { ...o, gimmicks } : o
      )
    );
  };

  const toggleGimmickInOverride = (levelIndex: number, gimmick: string) => {
    const override = getOverrideForLevel(levelIndex);
    if (!override) return;

    const updated = override.gimmicks.includes(gimmick)
      ? override.gimmicks.filter(g => g !== gimmick)
      : [...override.gimmicks, gimmick];

    updateOverrideGimmicks(levelIndex, updated);
  };

  const getGradeColor = (grade: string) => {
    switch (grade) {
      case 'S': return 'text-emerald-400';
      case 'A': return 'text-blue-400';
      case 'B': return 'text-yellow-400';
      case 'C': return 'text-orange-400';
      case 'D': return 'text-red-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className="bg-gray-800 rounded-lg overflow-hidden">
      <div className="bg-gray-750 px-3 py-2 border-b border-gray-600">
        <h4 className="text-sm font-medium text-gray-300">🔀 레벨별 기믹 오버라이드</h4>
        <p className="text-xs text-gray-500 mt-1">특정 레벨에 원하는 기믹을 직접 지정합니다. 체크하지 않은 레벨은 자동 배분됩니다.</p>
      </div>

      <div className="max-h-64 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-gray-750 sticky top-0">
            <tr>
              <th className="px-3 py-2 text-left text-gray-400 font-medium">레벨</th>
              <th className="px-3 py-2 text-center text-gray-400 font-medium">등급</th>
              <th className="px-3 py-2 text-center text-gray-400 font-medium">오버라이드</th>
              <th className="px-3 py-2 text-left text-gray-400 font-medium">기믹</th>
            </tr>
          </thead>
          <tbody>
            {levelInfos.map((info) => {
              const override = getOverrideForLevel(info.levelIndex);
              const recommendedGimmicks = GRADE_GIMMICK_RECOMMENDATIONS[info.grade] || [];

              return (
                <tr
                  key={info.levelIndex}
                  className={`border-b border-gray-700 hover:bg-gray-750 transition-colors ${
                    override ? 'bg-indigo-900/20' : ''
                  }`}
                >
                  <td className="px-3 py-2 text-gray-300">Level {info.levelIndex}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`font-bold ${getGradeColor(info.grade)}`}>
                      {info.grade}
                    </span>
                    <span className="text-gray-500 text-xs ml-1">
                      ({(info.difficulty * 100).toFixed(0)}%)
                    </span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <input
                      type="checkbox"
                      checked={!!override}
                      onChange={() => toggleOverride(info.levelIndex)}
                      disabled={disabled}
                      className="w-4 h-4 rounded border-gray-500 bg-gray-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-2">
                    {override ? (
                      <div className="flex flex-wrap gap-1">
                        {OBSTACLE_TYPES.map(obs => {
                          const isAvailable = availableGimmicks.includes(obs.id);
                          const isSelected = override.gimmicks.includes(obs.id);
                          if (!isAvailable) return null;
                          return (
                            <button
                              key={obs.id}
                              onClick={() => toggleGimmickInOverride(info.levelIndex, obs.id)}
                              disabled={disabled}
                              className={`px-1.5 py-0.5 text-xs rounded transition-colors ${
                                isSelected
                                  ? 'bg-indigo-600 text-white'
                                  : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                              }`}
                              title={obs.label}
                            >
                              {obs.label.split(' ')[0]}
                            </button>
                          );
                        })}
                        {override.gimmicks.length === 0 && (
                          <span className="text-gray-500 text-xs">없음</span>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-500 text-xs">
                        자동: {recommendedGimmicks.length > 0
                          ? recommendedGimmicks.filter(g => availableGimmicks.includes(g)).join(', ') || '없음'
                          : '없음'}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {overrides.length > 0 && (
        <div className="bg-gray-750 px-3 py-2 border-t border-gray-600 text-xs text-gray-400">
          {overrides.length}개 레벨 오버라이드됨
        </div>
      )}
    </div>
  );
}
