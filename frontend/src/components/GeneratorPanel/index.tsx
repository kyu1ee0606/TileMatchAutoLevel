import { useState, useEffect } from 'react';
import { DifficultySlider } from './DifficultySlider';
import { LevelSetGenerator } from '../LevelSetGenerator';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel, generateMultipleLevels } from '../../api/generate';
import { saveLocalLevel } from '../../services/localLevelsApi';
import { TILE_TYPES } from '../../types';
import type { GenerationParams, GoalConfig, ObstacleCountConfig, LayerTileConfig, LayerObstacleConfig } from '../../types';
import { Button, Tooltip, CollapsiblePanel } from '../ui';
import clsx from 'clsx';

// Obstacle type definitions for UI
const OBSTACLE_TYPES = [
  { id: 'chain', label: '⛓️ Chain', name: 'chain' },
  { id: 'frog', label: '🐸 Frog', name: 'frog' },
  { id: 'link', label: '🔗 Link', name: 'link' },
  { id: 'grass', label: '🌿 Grass', name: 'grass' },
  { id: 'ice', label: '❄️ Ice', name: 'ice' },
  { id: 'bomb', label: '💣 Bomb', name: 'bomb' },
  { id: 'curtain', label: '🎭 Curtain', name: 'curtain' },
  { id: 'teleport', label: '🌀 Teleport', name: 'teleport' },
  { id: 'crate', label: '📦 Crate', name: 'crate' },
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
  const [maxLayers, setMaxLayers] = useState(7);

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
    grass: { min: 0, max: 6 },
    ice: { min: 0, max: 8 },
    bomb: { min: 0, max: 3 },
    curtain: { min: 0, max: 6 },
    teleport: { min: 0, max: 4 },
    crate: { min: 0, max: 4 },
  });

  // Goals configuration (craft/stack with direction)
  const [goals, setGoals] = useState<GoalConfig[]>([
    { type: 'craft', direction: 's', count: 3 },
  ]);

  // Advanced layer settings (per-layer tile and obstacle configs only)
  const [showAdvancedSettings, setShowAdvancedSettings] = useState(false);
  const [layerTileConfigs, setLayerTileConfigs] = useState<LayerTileConfig[]>([]);
  const [layerObstacleConfigs, setLayerObstacleConfigs] = useState<LayerObstacleConfig[]>([]);

  // Clean up layer configs when maxLayers changes
  useEffect(() => {
    // Remove configs with layer index >= maxLayers
    setLayerTileConfigs(prev => prev.filter(c => c.layer < maxLayers));
    setLayerObstacleConfigs(prev => prev.filter(c => c.layer < maxLayers));
  }, [maxLayers]);

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
    setGoals((prev) => [...prev, { type: 'craft', direction: 's', count: 3 }]);
  };

  const removeGoal = (index: number) => {
    setGoals((prev) => prev.filter((_, i) => i !== index));
  };

  const updateGoal = (index: number, field: 'type' | 'direction' | 'count', value: string | number) => {
    setGoals((prev) =>
      prev.map((goal, i) =>
        i === index
          ? { ...goal, [field]: field === 'count' ? Number(value) : value }
          : goal
      )
    );
  };

  // Layer tile config management
  const addLayerTileConfig = () => {
    const usedLayers = new Set(layerTileConfigs.map(c => c.layer));
    // Find next available layer (from top)
    for (let i = maxLayers - 1; i >= 0; i--) {
      if (!usedLayers.has(i)) {
        setLayerTileConfigs(prev => [...prev, { layer: i, count: 20 }]);
        return;
      }
    }
  };

  const removeLayerTileConfig = (index: number) => {
    setLayerTileConfigs(prev => prev.filter((_, i) => i !== index));
  };

  const updateLayerTileConfig = (index: number, field: 'layer' | 'count', value: number) => {
    setLayerTileConfigs(prev =>
      prev.map((config, i) =>
        i === index ? { ...config, [field]: value } : config
      )
    );
  };

  // Layer obstacle config management
  const addLayerObstacleConfig = () => {
    const usedLayers = new Set(layerObstacleConfigs.map(c => c.layer));
    for (let i = maxLayers - 1; i >= 0; i--) {
      if (!usedLayers.has(i)) {
        setLayerObstacleConfigs(prev => [...prev, {
          layer: i,
          counts: {
            chain: { min: 0, max: 3 },
            frog: { min: 0, max: 2 },
            link: { min: 0, max: 2 },
          }
        }]);
        return;
      }
    }
  };

  const removeLayerObstacleConfig = (index: number) => {
    setLayerObstacleConfigs(prev => prev.filter((_, i) => i !== index));
  };

  const updateLayerObstacleConfig = (
    index: number,
    obstacleType: string,
    field: 'min' | 'max',
    value: number
  ) => {
    setLayerObstacleConfigs(prev =>
      prev.map((config, i) => {
        if (i !== index) return config;
        return {
          ...config,
          counts: {
            ...config.counts,
            [obstacleType]: {
              ...config.counts[obstacleType],
              [field]: Math.max(0, value),
            },
          },
        };
      })
    );
  };

  const updateLayerObstacleLayer = (index: number, layer: number) => {
    setLayerObstacleConfigs(prev =>
      prev.map((config, i) =>
        i === index ? { ...config, layer } : config
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
      // Check if advanced layer settings are being used
      const hasAdvancedLayerObstacles = layerObstacleConfigs.length > 0;

      // Build obstacle_counts for selected obstacles only
      // Skip if advanced layer obstacle configs are set (they take priority)
      let selectedObstacleCounts: Record<string, ObstacleCountConfig> | undefined = undefined;
      if (!hasAdvancedLayerObstacles) {
        const counts: Record<string, ObstacleCountConfig> = {};
        for (const obstacle of selectedObstacles) {
          if (obstacleCounts[obstacle]) {
            counts[obstacle] = obstacleCounts[obstacle];
          }
        }
        if (Object.keys(counts).length > 0) {
          selectedObstacleCounts = counts;
        }
      }

      // Convert goals to backend format (type_direction, e.g., craft_s, stack_e)
      const backendGoals = goals.map(goal => ({
        type: `${goal.type}_${goal.direction}` as 'craft_s' | 'stack_s',
        count: goal.count,
      }));

      const params: GenerationParams = {
        target_difficulty: targetDifficulty,
        grid_size: gridSize,
        max_layers: maxLayers,
        tile_types: selectedTileTypes,
        obstacle_types: selectedObstacles,
        // Send empty array explicitly when no goals (not undefined)
        goals: backendGoals as any,
        // Include obstacle count ranges (ignored if layer_obstacle_configs is set)
        obstacle_counts: selectedObstacleCounts,
        // Per-layer configs take priority over basic settings
        layer_tile_configs: layerTileConfigs.length > 0 ? layerTileConfigs : undefined,
        layer_obstacle_configs: hasAdvancedLayerObstacles ? layerObstacleConfigs : undefined,
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
              source: 'generated',
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
                  source: 'generated',
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

  // Filter out craft and stack tiles - they are configured separately in Goals section
  const matchingTileTypes = Object.entries(TILE_TYPES).filter(
    ([type]) => !type.startsWith('craft_') && !type.startsWith('stack_')
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
            {[1, 2, 3, 4, 5, 6, 7].map((n) => (
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

      {/* Obstacles with count settings - Button-based UI */}
      <div>
        <label className="text-sm font-medium text-gray-300 block mb-2">
          장애물 설정
          <span className="ml-2 text-xs text-gray-500">
            ({selectedObstacles.length}개 선택)
          </span>
        </label>
        <div className="space-y-1.5">
          {OBSTACLE_TYPES.map((obstacle) => {
            const isSelected = selectedObstacles.includes(obstacle.name);
            const counts = obstacleCounts[obstacle.name] || { min: 0, max: 5 };

            return (
              <div
                key={obstacle.id}
                className={clsx(
                  'flex items-center gap-2 p-1.5 rounded-lg transition-colors',
                  isSelected ? 'bg-orange-900/30 border border-orange-600' : 'bg-gray-700/30 border border-gray-600'
                )}
              >
                {/* Toggle button */}
                <button
                  onClick={() => toggleObstacle(obstacle.name)}
                  className={clsx(
                    'px-2 py-1 text-xs rounded-md transition-colors min-w-[80px] font-medium',
                    isSelected
                      ? 'bg-orange-500 text-white'
                      : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                  )}
                >
                  {obstacle.label}
                </button>

                {/* Count range controls - only show when selected */}
                {isSelected && (
                  <div className="flex items-center gap-1 ml-auto">
                    {/* Min controls */}
                    <div className="flex items-center">
                      <button
                        onClick={() => updateObstacleCount(obstacle.name, 'min', counts.min - 1)}
                        className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-l-md border border-gray-600 text-sm font-bold"
                      >
                        -
                      </button>
                      <div className="w-8 h-6 flex items-center justify-center bg-gray-800 border-y border-gray-600 text-xs text-gray-100">
                        {counts.min}
                      </div>
                      <button
                        onClick={() => updateObstacleCount(obstacle.name, 'min', counts.min + 1)}
                        className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-r-md border border-gray-600 text-sm font-bold"
                      >
                        +
                      </button>
                    </div>

                    <span className="text-xs text-gray-500 px-1">~</span>

                    {/* Max controls */}
                    <div className="flex items-center">
                      <button
                        onClick={() => updateObstacleCount(obstacle.name, 'max', counts.max - 1)}
                        className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-l-md border border-gray-600 text-sm font-bold"
                      >
                        -
                      </button>
                      <div className="w-8 h-6 flex items-center justify-center bg-gray-800 border-y border-gray-600 text-xs text-gray-100">
                        {counts.max}
                      </div>
                      <button
                        onClick={() => updateObstacleCount(obstacle.name, 'max', counts.max + 1)}
                        className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-r-md border border-gray-600 text-sm font-bold"
                      >
                        +
                      </button>
                    </div>

                    {/* Quick preset buttons */}
                    <div className="flex items-center gap-0.5 ml-1">
                      {[
                        { label: '0', min: 0, max: 0 },
                        { label: '少', min: 1, max: 3 },
                        { label: '中', min: 3, max: 6 },
                        { label: '多', min: 5, max: 10 },
                      ].map((preset) => (
                        <button
                          key={preset.label}
                          onClick={() => {
                            updateObstacleCount(obstacle.name, 'min', preset.min);
                            updateObstacleCount(obstacle.name, 'max', preset.max);
                          }}
                          className={clsx(
                            'w-6 h-6 text-xs rounded transition-colors',
                            counts.min === preset.min && counts.max === preset.max
                              ? 'bg-orange-500 text-white'
                              : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                          )}
                          title={`${preset.min}~${preset.max}개`}
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Goals - Button-based UI */}
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
              <div key={index} className="flex flex-wrap gap-2 items-center bg-gray-700/30 p-2 rounded-md">
                {/* Goal type buttons */}
                <div className="flex">
                  {[
                    { type: 'craft' as const, label: '🎁 Craft' },
                    { type: 'stack' as const, label: '📚 Stack' },
                  ].map((opt) => (
                    <button
                      key={opt.type}
                      onClick={() => updateGoal(index, 'type', opt.type)}
                      className={clsx(
                        'px-2 py-1 text-xs transition-colors first:rounded-l-md last:rounded-r-md border',
                        goal.type === opt.type
                          ? 'bg-blue-600 text-white border-blue-500'
                          : 'bg-gray-700 text-gray-400 hover:bg-gray-600 border-gray-600'
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>

                {/* Direction buttons */}
                <div className="flex">
                  {[
                    { dir: 's' as const, label: '↓S' },
                    { dir: 'n' as const, label: '↑N' },
                    { dir: 'e' as const, label: '→E' },
                    { dir: 'w' as const, label: '←W' },
                  ].map((opt) => (
                    <button
                      key={opt.dir}
                      onClick={() => updateGoal(index, 'direction', opt.dir)}
                      className={clsx(
                        'px-1.5 py-1 text-xs transition-colors first:rounded-l-md last:rounded-r-md border',
                        goal.direction === opt.dir
                          ? 'bg-green-600 text-white border-green-500'
                          : 'bg-gray-700 text-gray-400 hover:bg-gray-600 border-gray-600'
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>

                {/* Count controls */}
                <div className="flex items-center ml-auto">
                  <button
                    onClick={() => updateGoal(index, 'count', Math.max(1, goal.count - 1))}
                    className="w-7 h-7 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-l-md border border-gray-600 text-sm font-bold"
                  >
                    -
                  </button>
                  <div className="w-10 h-7 flex items-center justify-center bg-gray-800 border-y border-gray-600 text-sm text-gray-100 font-medium">
                    {goal.count}
                  </div>
                  <button
                    onClick={() => updateGoal(index, 'count', Math.min(20, goal.count + 1))}
                    className="w-7 h-7 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-r-md border border-gray-600 text-sm font-bold"
                  >
                    +
                  </button>
                </div>

                {/* Quick preset buttons for count */}
                <div className="flex items-center gap-0.5">
                  {[3, 6, 9].map((preset) => (
                    <button
                      key={preset}
                      onClick={() => updateGoal(index, 'count', preset)}
                      className={clsx(
                        'w-7 h-7 text-xs rounded transition-colors',
                        goal.count === preset
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                      )}
                    >
                      {preset}
                    </button>
                  ))}
                </div>

                {/* Delete button */}
                <Tooltip content="목표 삭제">
                  <button
                    onClick={() => removeGoal(index)}
                    className="p-1.5 text-red-400 hover:bg-red-900/50 rounded-md transition-colors"
                  >
                    ✕
                  </button>
                </Tooltip>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Advanced Layer Settings */}
      <div className="border-t border-gray-700 pt-4">
        <button
          onClick={() => setShowAdvancedSettings(!showAdvancedSettings)}
          className="flex items-center gap-2 text-sm font-medium text-gray-300 hover:text-gray-100 transition-colors"
        >
          <span className={clsx('transition-transform', showAdvancedSettings && 'rotate-90')}>▶</span>
          🔧 고급 레이어 설정
          {(layerTileConfigs.length > 0 || layerObstacleConfigs.length > 0) && (
            <span className="px-1.5 py-0.5 bg-blue-600 text-xs rounded">활성</span>
          )}
        </button>

        {showAdvancedSettings && (
          <div className="mt-3 space-y-4 pl-2 border-l-2 border-gray-600">
            {/* Per-Layer Tile Configs - Button-based UI */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-gray-300">레이어별 타일 수</span>
                <Button onClick={addLayerTileConfig} variant="success" size="sm" icon="+">
                  추가
                </Button>
              </div>
              {layerTileConfigs.length > 0 ? (
                <div className="space-y-2">
                  {layerTileConfigs.map((config, index) => (
                    <div key={index} className="flex items-center gap-2 bg-gray-700/30 p-2 rounded-md">
                      {/* Layer selector as buttons */}
                      <div className="flex items-center gap-1">
                        <span className="text-xs text-gray-400 mr-1">L</span>
                        {Array.from({ length: maxLayers }, (_, i) => maxLayers - 1 - i).map((layer) => (
                          <button
                            key={layer}
                            onClick={() => updateLayerTileConfig(index, 'layer', layer)}
                            className={clsx(
                              'w-6 h-6 text-xs rounded transition-colors',
                              config.layer === layer
                                ? 'bg-blue-600 text-white'
                                : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                            )}
                          >
                            {layer}
                          </button>
                        ))}
                      </div>

                      {/* Tile count with +/- buttons */}
                      <div className="flex items-center ml-auto">
                        <button
                          onClick={() => updateLayerTileConfig(index, 'count', Math.max(0, config.count - 3))}
                          className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-l-md border border-gray-600 text-xs"
                        >
                          -3
                        </button>
                        <button
                          onClick={() => updateLayerTileConfig(index, 'count', Math.max(0, config.count - 1))}
                          className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 border-y border-gray-600 text-sm font-bold"
                        >
                          -
                        </button>
                        <div className="w-10 h-6 flex items-center justify-center bg-gray-800 border-y border-gray-600 text-xs text-gray-100 font-medium">
                          {config.count}
                        </div>
                        <button
                          onClick={() => updateLayerTileConfig(index, 'count', config.count + 1)}
                          className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 border-y border-gray-600 text-sm font-bold"
                        >
                          +
                        </button>
                        <button
                          onClick={() => updateLayerTileConfig(index, 'count', config.count + 3)}
                          className="w-6 h-6 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-r-md border border-gray-600 text-xs"
                        >
                          +3
                        </button>
                      </div>

                      {/* Quick presets */}
                      <div className="flex items-center gap-0.5">
                        {[15, 21, 27].map((preset) => (
                          <button
                            key={preset}
                            onClick={() => updateLayerTileConfig(index, 'count', preset)}
                            className={clsx(
                              'w-7 h-6 text-xs rounded transition-colors',
                              config.count === preset
                                ? 'bg-blue-600 text-white'
                                : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                            )}
                          >
                            {preset}
                          </button>
                        ))}
                      </div>

                      <button
                        onClick={() => removeLayerTileConfig(index)}
                        className="p-1 text-red-400 hover:bg-red-900/50 rounded transition-colors"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-500">설정하지 않으면 자동 배분됩니다</p>
              )}
            </div>

            {/* Per-Layer Obstacle Configs - Button-based UI */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-gray-300">레이어별 기믹 설정</span>
                <Button onClick={addLayerObstacleConfig} variant="success" size="sm" icon="+">
                  추가
                </Button>
              </div>
              {layerObstacleConfigs.length > 0 ? (
                <div className="space-y-3">
                  {layerObstacleConfigs.map((config, index) => (
                    <div key={index} className="bg-gray-700/30 p-3 rounded-md">
                      <div className="flex items-center justify-between mb-2">
                        {/* Layer selector as buttons */}
                        <div className="flex items-center gap-1">
                          <span className="text-xs text-gray-400 mr-1">레이어</span>
                          {Array.from({ length: maxLayers }, (_, i) => maxLayers - 1 - i).map((layer) => (
                            <button
                              key={layer}
                              onClick={() => updateLayerObstacleLayer(index, layer)}
                              className={clsx(
                                'w-6 h-6 text-xs rounded transition-colors',
                                config.layer === layer
                                  ? 'bg-blue-600 text-white'
                                  : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                              )}
                            >
                              {layer}
                            </button>
                          ))}
                        </div>
                        <button
                          onClick={() => removeLayerObstacleConfig(index)}
                          className="p-1 text-red-400 hover:bg-red-900/50 rounded transition-colors"
                        >
                          ✕
                        </button>
                      </div>
                      <div className="grid grid-cols-3 gap-2">
                        {OBSTACLE_TYPES.map((obs) => {
                          const obsMin = config.counts[obs.name]?.min ?? 0;
                          const obsMax = config.counts[obs.name]?.max ?? 0;
                          return (
                            <div key={obs.id} className="bg-gray-800/50 p-1.5 rounded">
                              <div className="text-xs text-gray-400 mb-1 text-center">{obs.label}</div>
                              <div className="flex items-center justify-center gap-0.5">
                                {/* Min/Max combined control */}
                                <button
                                  onClick={() => {
                                    updateLayerObstacleConfig(index, obs.name, 'min', Math.max(0, obsMin - 1));
                                    updateLayerObstacleConfig(index, obs.name, 'max', Math.max(0, obsMax - 1));
                                  }}
                                  className="w-5 h-5 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-l text-xs"
                                >
                                  -
                                </button>
                                <div className="px-1.5 h-5 flex items-center justify-center bg-gray-700 text-xs text-gray-100 min-w-[36px]">
                                  {obsMin}~{obsMax}
                                </div>
                                <button
                                  onClick={() => {
                                    updateLayerObstacleConfig(index, obs.name, 'min', obsMin + 1);
                                    updateLayerObstacleConfig(index, obs.name, 'max', obsMax + 1);
                                  }}
                                  className="w-5 h-5 flex items-center justify-center bg-gray-700 hover:bg-gray-600 text-gray-300 rounded-r text-xs"
                                >
                                  +
                                </button>
                              </div>
                              {/* Quick presets for this obstacle */}
                              <div className="flex justify-center gap-0.5 mt-1">
                                {[
                                  { label: '0', min: 0, max: 0 },
                                  { label: '少', min: 1, max: 2 },
                                  { label: '多', min: 3, max: 5 },
                                ].map((preset) => (
                                  <button
                                    key={preset.label}
                                    onClick={() => {
                                      updateLayerObstacleConfig(index, obs.name, 'min', preset.min);
                                      updateLayerObstacleConfig(index, obs.name, 'max', preset.max);
                                    }}
                                    className={clsx(
                                      'w-5 h-4 text-[10px] rounded transition-colors',
                                      obsMin === preset.min && obsMax === preset.max
                                        ? 'bg-orange-500 text-white'
                                        : 'bg-gray-600 hover:bg-gray-500 text-gray-400'
                                    )}
                                    title={`${preset.min}~${preset.max}개`}
                                  >
                                    {preset.label}
                                  </button>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-gray-500">설정하지 않으면 전체 기믹 설정 기준으로 자동 배분됩니다</p>
              )}
            </div>
          </div>
        )}
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

      {/* Level Set Generator */}
      <CollapsiblePanel
        title="레벨 세트 생성기"
        icon="📊"
        defaultCollapsed={true}
        className="mt-4"
      >
        <LevelSetGenerator />
      </CollapsiblePanel>
    </div>
  );
}

export { DifficultySlider } from './DifficultySlider';
