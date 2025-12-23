import { useState } from 'react';
import { DifficultySlider } from './DifficultySlider';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel, generateMultipleLevels } from '../../api/generate';
import { saveLocalLevel } from '../../services/localLevelsApi';
import { TILE_TYPES } from '../../types';
import type { GenerationParams, GoalConfig, ObstacleCountConfig } from '../../types';
import { Button, Tooltip } from '../ui';
import clsx from 'clsx';

// Obstacle type definitions for UI
const OBSTACLE_TYPES = [
  { id: 'chain', label: '⛓️ Chain', name: 'chain' },
  { id: 'frog', label: '🐸 Frog', name: 'frog' },
  { id: 'link', label: '🔗 Link', name: 'link' },
] as const;

interface GeneratorPanelProps {
  className?: string;
}

export function GeneratorPanel({ className }: GeneratorPanelProps) {
  const { setLevel } = useLevelStore();
  const { isGenerating, setIsGenerating, addNotification } = useUIStore();

  // Generation parameters
  const [targetDifficulty, setTargetDifficulty] = useState(0.5);
  const [gridSize, setGridSize] = useState<[number, number]>([7, 7]);
  const [maxLayers, setMaxLayers] = useState(8);

  // Tile types selection
  const [selectedTileTypes, setSelectedTileTypes] = useState<string[]>([
    't0', 't2', 't4', 't5', 't6',
  ]);

  // Obstacle types selection with count ranges
  const [selectedObstacles, setSelectedObstacles] = useState<string[]>(['chain', 'frog']);
  const [obstacleCounts, setObstacleCounts] = useState<Record<string, ObstacleCountConfig>>({
    chain: { min: 3, max: 8 },
    frog: { min: 2, max: 5 },
    link: { min: 0, max: 4 },
  });

  // Goals configuration
  const [goals, setGoals] = useState<GoalConfig[]>([
    { type: 'craft_s', count: 3 },
  ]);

  const toggleTileType = (type: string) => {
    setSelectedTileTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  };

  const toggleObstacle = (obstacle: string) => {
    setSelectedObstacles((prev) =>
      prev.includes(obstacle)
        ? prev.filter((o) => o !== obstacle)
        : [...prev, obstacle]
    );
  };

  const updateObstacleCount = (obstacle: string, field: 'min' | 'max', value: number) => {
    setObstacleCounts((prev) => ({
      ...prev,
      [obstacle]: {
        ...prev[obstacle],
        [field]: Math.max(0, value),
      },
    }));
  };

  const addGoal = () => {
    setGoals((prev) => [...prev, { type: 'craft_s', count: 3 }]);
  };

  const removeGoal = (index: number) => {
    setGoals((prev) => prev.filter((_, i) => i !== index));
  };

  const updateGoal = (index: number, field: 'type' | 'count', value: string | number) => {
    setGoals((prev) =>
      prev.map((goal, i) =>
        i === index
          ? { ...goal, [field]: field === 'count' ? Number(value) : value }
          : goal
      )
    );
  };

  const handleGenerate = async (count: number = 1) => {
    if (selectedTileTypes.length === 0) {
      addNotification('warning', '최소 하나의 타일 타입을 선택하세요');
      return;
    }

    setIsGenerating(true);

    try {
      // Build obstacle_counts for selected obstacles only
      const selectedObstacleCounts: Record<string, ObstacleCountConfig> = {};
      for (const obstacle of selectedObstacles) {
        if (obstacleCounts[obstacle]) {
          selectedObstacleCounts[obstacle] = obstacleCounts[obstacle];
        }
      }

      const params: GenerationParams = {
        target_difficulty: targetDifficulty,
        grid_size: gridSize,
        max_layers: maxLayers,
        tile_types: selectedTileTypes,
        obstacle_types: selectedObstacles,
        // Send empty array explicitly when no goals (not undefined)
        goals: goals,
        // Include obstacle count ranges
        obstacle_counts: Object.keys(selectedObstacleCounts).length > 0 ? selectedObstacleCounts : undefined,
      };

      if (count === 1) {
        const result = await generateLevel(params);
        setLevel(result.level_json);

        // Save to local storage
        try {
          const timestamp = Date.now();
          const levelId = `generated_${timestamp}`;
          await saveLocalLevel({
            level_id: levelId,
            level_data: result.level_json,
            metadata: {
              name: `Generated Level (${result.grade})`,
              description: `Target difficulty: ${(targetDifficulty * 100).toFixed(0)}%, Actual: ${(result.actual_difficulty * 100).toFixed(0)}%`,
              tags: ['generated', result.grade.toLowerCase(), `${gridSize[0]}x${gridSize[1]}`],
              difficulty: result.grade.toLowerCase(),
            }
          });
          addNotification(
            'success',
            `레벨 생성 완료! (난이도: ${(result.actual_difficulty * 100).toFixed(0)}%, 등급: ${result.grade}) - 로컬 레벨에 저장됨`
          );
        } catch (saveError) {
          console.error('Failed to save to local storage:', saveError);
          addNotification(
            'warning',
            `레벨은 생성되었으나 로컬 저장 실패 (난이도: ${(result.actual_difficulty * 100).toFixed(0)}%, 등급: ${result.grade})`
          );
        }
      } else {
        const results = await generateMultipleLevels(params, count);
        // Use the first generated level
        if (results.length > 0) {
          setLevel(results[0].level_json);

          // Save all generated levels to local storage
          let savedCount = 0;
          for (let i = 0; i < results.length; i++) {
            try {
              const timestamp = Date.now() + i;
              const levelId = `generated_${timestamp}`;
              await saveLocalLevel({
                level_id: levelId,
                level_data: results[i].level_json,
                metadata: {
                  name: `Generated Level #${i + 1} (${results[i].grade})`,
                  description: `Batch generation - Actual difficulty: ${(results[i].actual_difficulty * 100).toFixed(0)}%`,
                  tags: ['generated', 'batch', results[i].grade.toLowerCase(), `${gridSize[0]}x${gridSize[1]}`],
                  difficulty: results[i].grade.toLowerCase(),
                }
              });
              savedCount++;
            } catch (saveError) {
              console.error(`Failed to save level ${i + 1}:`, saveError);
            }
          }

          addNotification('success', `${results.length}개 레벨 생성 완료 - ${savedCount}개 로컬 레벨에 저장됨`);
        }
      }
    } catch (error) {
      console.error('Generation failed:', error);
      addNotification('error', '레벨 생성에 실패했습니다');
    } finally {
      setIsGenerating(false);
    }
  };

  const matchingTileTypes = Object.entries(TILE_TYPES).filter(
    ([type]) => !type.endsWith('_s')
  );

  return (
    <div className={clsx('flex flex-col gap-4 p-4 bg-gray-800 rounded-xl shadow-lg border border-gray-700', className)}>
      <h2 className="text-lg font-bold text-gray-100">🎲 레벨 자동 생성</h2>

      {/* Difficulty Slider */}
      <DifficultySlider value={targetDifficulty} onChange={setTargetDifficulty} />

      {/* Grid Settings */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="text-sm font-medium text-gray-300 block mb-1">그리드 크기</label>
          <select
            value={`${gridSize[0]}x${gridSize[1]}`}
            onChange={(e) => {
              const [cols, rows] = e.target.value.split('x').map(Number);
              setGridSize([cols, rows]);
            }}
            className="w-full px-3 py-2 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm"
          >
            <option value="5x5">5 x 5</option>
            <option value="6x6">6 x 6</option>
            <option value="7x7">7 x 7</option>
            <option value="8x8">8 x 8</option>
          </select>
        </div>
        <div>
          <label className="text-sm font-medium text-gray-300 block mb-1">레이어 수</label>
          <select
            value={maxLayers}
            onChange={(e) => setMaxLayers(Number(e.target.value))}
            className="w-full px-3 py-2 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm"
          >
            {[4, 5, 6, 7, 8, 9, 10].map((n) => (
              <option key={n} value={n}>
                {n} 레이어
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Tile Types */}
      <div>
        <label className="text-sm font-medium text-gray-300 block mb-2">
          타일 타입
          <span className="ml-2 text-xs text-gray-500">
            ({selectedTileTypes.length}개 선택)
          </span>
        </label>
        <div className="grid grid-cols-8 gap-1">
          {matchingTileTypes.map(([type, info]) => (
            <button
              key={type}
              onClick={() => toggleTileType(type)}
              title={info.name}
              className={clsx(
                'w-8 h-8 rounded-md border-2 flex items-center justify-center text-xs font-bold text-white transition-all hover:scale-105 overflow-hidden',
                selectedTileTypes.includes(type)
                  ? 'border-primary-500 ring-2 ring-primary-300'
                  : 'border-gray-600 opacity-40 hover:opacity-70'
              )}
              style={{ backgroundColor: info.color }}
            >
              {info.image ? (
                <img
                  src={info.image}
                  alt={info.name}
                  className="w-full h-full object-cover"
                  draggable={false}
                />
              ) : (
                type
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Obstacles with count settings */}
      <div>
        <label className="text-sm font-medium text-gray-300 block mb-2">
          장애물 설정
          <span className="ml-2 text-xs text-gray-500">
            ({selectedObstacles.length}개 선택)
          </span>
        </label>
        <div className="space-y-2">
          {OBSTACLE_TYPES.map((obstacle) => {
            const isSelected = selectedObstacles.includes(obstacle.name);
            const counts = obstacleCounts[obstacle.name] || { min: 0, max: 5 };

            return (
              <div
                key={obstacle.id}
                className={clsx(
                  'flex items-center gap-3 p-2 rounded-lg transition-colors',
                  isSelected ? 'bg-orange-900/30 border border-orange-600' : 'bg-gray-700/30 border border-gray-600'
                )}
              >
                {/* Toggle button */}
                <button
                  onClick={() => toggleObstacle(obstacle.name)}
                  className={clsx(
                    'px-3 py-1 text-sm rounded-md transition-colors min-w-[90px]',
                    isSelected
                      ? 'bg-orange-500 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  {obstacle.label}
                </button>

                {/* Count range inputs - only show when selected */}
                {isSelected && (
                  <div className="flex items-center gap-2 ml-auto">
                    <span className="text-xs text-gray-400">최소</span>
                    <input
                      type="number"
                      min="0"
                      max="30"
                      value={counts.min}
                      onChange={(e) => updateObstacleCount(obstacle.name, 'min', Number(e.target.value))}
                      className="w-14 px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm text-center"
                    />
                    <span className="text-xs text-gray-400">~</span>
                    <span className="text-xs text-gray-400">최대</span>
                    <input
                      type="number"
                      min="0"
                      max="30"
                      value={counts.max}
                      onChange={(e) => updateObstacleCount(obstacle.name, 'max', Number(e.target.value))}
                      className="w-14 px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm text-center"
                    />
                    <span className="text-xs text-gray-500">개</span>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Goals */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <label className="text-sm font-medium text-gray-300">
            목표 설정
            <span className="ml-2 text-xs text-gray-500">
              ({goals.length}개)
            </span>
          </label>
          <Button
            onClick={addGoal}
            variant="success"
            size="sm"
            icon="+"
          >
            추가
          </Button>
        </div>
        <div className="space-y-2">
          {goals.length === 0 ? (
            <div className="text-sm text-gray-500 py-2 px-3 bg-gray-700/30 rounded-md">
              목표 없이 생성됩니다 (일반 타일만)
            </div>
          ) : (
            goals.map((goal, index) => (
              <div key={index} className="flex gap-2 items-center">
                <select
                  value={goal.type}
                  onChange={(e) => updateGoal(index, 'type', e.target.value)}
                  className="flex-1 px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm"
                >
                  <option value="craft_s">Craft</option>
                  <option value="stack_s">Stack</option>
                </select>
                <input
                  type="number"
                  min="1"
                  max="20"
                  value={goal.count}
                  onChange={(e) => updateGoal(index, 'count', e.target.value)}
                  className="w-16 px-2 py-1 border border-gray-600 bg-gray-700 text-gray-100 rounded-md text-sm"
                />
                <span className="text-sm text-gray-400">개</span>
                <Tooltip content="목표 삭제">
                  <button
                    onClick={() => removeGoal(index)}
                    className="p-1.5 text-red-400 hover:bg-red-900/50 rounded-md transition-colors"
                  >
                    🗑️
                  </button>
                </Tooltip>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Generate Buttons */}
      <div className="flex gap-2 pt-4 border-t border-gray-700">
        <Button
          onClick={() => handleGenerate(1)}
          disabled={isGenerating}
          isLoading={isGenerating}
          variant="primary"
          size="lg"
          icon="🎯"
          className="flex-1"
        >
          레벨 1개 생성
        </Button>
        <Button
          onClick={() => handleGenerate(10)}
          disabled={isGenerating}
          isLoading={isGenerating}
          variant="secondary"
          size="lg"
          icon="📦"
        >
          10개 일괄
        </Button>
      </div>
    </div>
  );
}

export { DifficultySlider } from './DifficultySlider';
