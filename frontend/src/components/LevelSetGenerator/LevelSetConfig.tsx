import { useState } from 'react';
import type { LevelSetGenerationConfig, GimmickMode, LevelGimmickOverride, DifficultyPoint } from '../../types/levelSet';
import type { GoalConfig, SymmetryMode, PatternType } from '../../types';
import { Button } from '../ui';
import { LevelGimmickTable } from './LevelGimmickTable';

interface LevelSetConfigProps {
  config: LevelSetGenerationConfig;
  onConfigChange: (config: LevelSetGenerationConfig) => void;
  difficultyPoints: DifficultyPoint[];
  disabled?: boolean;
}

const OBSTACLE_TYPES = [
  { id: 'chain', label: '⛓️ Chain' },
  { id: 'frog', label: '🐸 Frog' },
  { id: 'link', label: '🔗 Link' },
  { id: 'grass', label: '🌿 Grass' },
  { id: 'ice', label: '❄️ Ice' },
  { id: 'bomb', label: '💣 Bomb' },
  { id: 'curtain', label: '🎭 Curtain' },
] as const;

const SYMMETRY_OPTIONS: { id: SymmetryMode; label: string; icon: string }[] = [
  { id: 'none', label: '없음', icon: '⊗' },
  { id: 'horizontal', label: '좌우 대칭', icon: '↔' },
  { id: 'vertical', label: '상하 대칭', icon: '↕' },
  { id: 'both', label: '4방향 대칭', icon: '✛' },
];

const PATTERN_OPTIONS: { id: PatternType; label: string; icon: string }[] = [
  { id: 'random', label: '랜덤', icon: '🎲' },
  { id: 'geometric', label: '기하학적', icon: '◆' },
  { id: 'clustered', label: '군집형', icon: '⚬' },
];

const GIMMICK_MODE_OPTIONS: { id: GimmickMode; label: string; icon: string; description: string }[] = [
  { id: 'auto', label: '자동', icon: '🤖', description: '난이도에 따라 자동 배분' },
  { id: 'manual', label: '수동', icon: '✋', description: '모든 레벨에 동일 적용' },
  { id: 'hybrid', label: '하이브리드', icon: '🔀', description: '자동 + 레벨별 오버라이드' },
];

export function LevelSetConfig({
  config,
  onConfigChange,
  difficultyPoints,
  disabled
}: LevelSetConfigProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const updateConfig = (updates: Partial<LevelSetGenerationConfig>) => {
    onConfigChange({ ...config, ...updates });
  };

  const updateBaseParams = (updates: Partial<typeof config.baseParams>) => {
    onConfigChange({
      ...config,
      baseParams: { ...config.baseParams, ...updates },
    });
  };

  const toggleObstacle = (obstacle: string) => {
    const current = config.baseParams.obstacle_types || [];
    const updated = current.includes(obstacle)
      ? current.filter((o) => o !== obstacle)
      : [...current, obstacle];
    updateBaseParams({ obstacle_types: updated });
  };

  const toggleAvailableGimmick = (gimmick: string) => {
    const current = config.availableGimmicks || [];
    const updated = current.includes(gimmick)
      ? current.filter((g) => g !== gimmick)
      : [...current, gimmick];
    onConfigChange({ ...config, availableGimmicks: updated });
  };

  const setGimmickMode = (mode: GimmickMode) => {
    onConfigChange({ ...config, gimmickMode: mode });
  };

  const updateLevelGimmickOverrides = (overrides: LevelGimmickOverride[]) => {
    onConfigChange({ ...config, levelGimmickOverrides: overrides });
  };

  const updateGoal = (index: number, updates: Partial<GoalConfig>) => {
    const newGoals = [...(config.baseParams.goals || [])];
    newGoals[index] = { ...newGoals[index], ...updates };
    updateBaseParams({ goals: newGoals });
  };

  const addGoal = () => {
    const goals = config.baseParams.goals || [];
    updateBaseParams({ goals: [...goals, { type: 'craft', direction: 's', count: 3 }] });
  };

  const removeGoal = (index: number) => {
    const goals = config.baseParams.goals || [];
    updateBaseParams({ goals: goals.filter((_, i) => i !== index) });
  };

  return (
    <div className="space-y-4">
      {/* Set Name */}
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1">세트 이름</label>
        <input
          type="text"
          value={config.setName}
          onChange={(e) => updateConfig({ setName: e.target.value })}
          placeholder="예: 초보자용 레벨 세트"
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={disabled}
        />
      </div>

      {/* Level Count */}
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1">
          레벨 수: <span className="text-blue-400 font-bold">{config.levelCount}</span>
        </label>
        <input
          type="range"
          min={5}
          max={50}
          value={config.levelCount}
          onChange={(e) => updateConfig({ levelCount: parseInt(e.target.value) })}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
          disabled={disabled}
        />
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>5</span>
          <span>15</span>
          <span>30</span>
          <span>50</span>
        </div>
      </div>

      {/* Grid Size */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1">가로</label>
          <input
            type="number"
            value={config.baseParams.grid_size?.[0] || 7}
            onChange={(e) => {
              const cols = parseInt(e.target.value) || 7;
              const rows = config.baseParams.grid_size?.[1] || 7;
              updateBaseParams({ grid_size: [cols, rows] });
            }}
            min={5}
            max={15}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white text-sm"
            disabled={disabled}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-400 mb-1">세로</label>
          <input
            type="number"
            value={config.baseParams.grid_size?.[1] || 7}
            onChange={(e) => {
              const cols = config.baseParams.grid_size?.[0] || 7;
              const rows = parseInt(e.target.value) || 7;
              updateBaseParams({ grid_size: [cols, rows] });
            }}
            min={5}
            max={15}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white text-sm"
            disabled={disabled}
          />
        </div>
      </div>

      {/* Max Layers */}
      <div>
        <label className="block text-sm font-medium text-gray-300 mb-1">
          최대 레이어: <span className="text-blue-400">{config.baseParams.max_layers || 7}</span>
        </label>
        <input
          type="range"
          min={1}
          max={10}
          value={config.baseParams.max_layers || 7}
          onChange={(e) => updateBaseParams({ max_layers: parseInt(e.target.value) })}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
          disabled={disabled}
        />
      </div>

      {/* Goals */}
      <div>
        <div className="flex justify-between items-center mb-2">
          <label className="text-sm font-medium text-gray-300">골</label>
          <Button
            size="sm"
            variant="secondary"
            onClick={addGoal}
            disabled={disabled}
          >
            + 추가
          </Button>
        </div>
        <div className="space-y-2">
          {(config.baseParams.goals || []).map((goal, index) => (
            <div key={index} className="flex items-center gap-2 bg-gray-700 p-2 rounded">
              <select
                value={goal.type}
                onChange={(e) => updateGoal(index, { type: e.target.value as 'craft' | 'stack' })}
                className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-sm"
                disabled={disabled}
              >
                <option value="craft">Craft</option>
                <option value="stack">Stack</option>
              </select>
              <select
                value={goal.direction}
                onChange={(e) => updateGoal(index, { direction: e.target.value as 's' | 'n' | 'e' | 'w' })}
                className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-sm"
                disabled={disabled}
              >
                <option value="s">↓ South</option>
                <option value="n">↑ North</option>
                <option value="e">→ East</option>
                <option value="w">← West</option>
              </select>
              <input
                type="number"
                value={goal.count}
                onChange={(e) => updateGoal(index, { count: parseInt(e.target.value) || 1 })}
                min={1}
                max={10}
                className="w-16 px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-sm"
                disabled={disabled}
              />
              <button
                onClick={() => removeGoal(index)}
                className="text-red-400 hover:text-red-300 px-2"
                disabled={disabled}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Gimmick Mode Selection */}
      <div className="bg-gray-750 rounded-lg p-3 border border-gray-600">
        <label className="block text-sm font-medium text-gray-300 mb-2">🎮 기믹 배분 모드</label>
        <div className="flex flex-wrap gap-2 mb-3">
          {GIMMICK_MODE_OPTIONS.map((opt) => {
            const isSelected = config.gimmickMode === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => setGimmickMode(opt.id)}
                className={`px-3 py-1.5 text-sm rounded transition-colors flex items-center gap-1.5 ${
                  isSelected
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
                disabled={disabled}
                title={opt.description}
              >
                <span>{opt.icon}</span>
                <span>{opt.label}</span>
              </button>
            );
          })}
        </div>
        <p className="text-xs text-gray-500 mb-3">
          {config.gimmickMode === 'auto' && '🤖 난이도에 따라 자동으로 기믹이 배분됩니다. (S등급: 기믹 없음 → D등급: 다양한 기믹)'}
          {config.gimmickMode === 'manual' && '✋ 선택한 기믹이 모든 레벨에 동일하게 적용됩니다.'}
          {config.gimmickMode === 'hybrid' && '🔀 자동 배분 기반 + 특정 레벨에 원하는 기믹을 지정할 수 있습니다.'}
        </p>

        {/* Available Gimmicks for Auto/Hybrid Mode */}
        {(config.gimmickMode === 'auto' || config.gimmickMode === 'hybrid') && (
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-2">사용 가능한 기믹 풀 (자동 선택에 사용)</label>
            <div className="flex flex-wrap gap-2">
              {OBSTACLE_TYPES.map((obs) => {
                const isSelected = (config.availableGimmicks || []).includes(obs.id);
                return (
                  <button
                    key={obs.id}
                    onClick={() => toggleAvailableGimmick(obs.id)}
                    className={`px-2 py-1 text-xs rounded transition-colors ${
                      isSelected
                        ? 'bg-indigo-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                    }`}
                    disabled={disabled}
                  >
                    {obs.label}
                  </button>
                );
              })}
            </div>
            {(config.availableGimmicks || []).length === 0 && (
              <p className="text-xs text-yellow-500 mt-2">⚠️ 기믹 풀이 비어있으면 모든 레벨이 기믹 없이 생성됩니다.</p>
            )}
          </div>
        )}

        {/* Hybrid Mode: Level Override Table */}
        {config.gimmickMode === 'hybrid' && (config.availableGimmicks || []).length > 0 && (
          <div className="mt-3">
            <LevelGimmickTable
              levelCount={config.levelCount}
              difficultyPoints={difficultyPoints}
              availableGimmicks={config.availableGimmicks || []}
              overrides={config.levelGimmickOverrides || []}
              onOverridesChange={updateLevelGimmickOverrides}
              disabled={disabled}
            />
          </div>
        )}
      </div>

      {/* Advanced Settings Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-sm text-blue-400 hover:text-blue-300"
        disabled={disabled}
      >
        {showAdvanced ? '▼ 상세 설정 숨기기' : '▶ 상세 설정'}
      </button>

      {showAdvanced && (
        <div className="space-y-4 pl-2 border-l-2 border-gray-600">
          {/* Pattern Type */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">패턴 타입</label>
            <div className="flex flex-wrap gap-2">
              {PATTERN_OPTIONS.map((opt) => {
                const isSelected = (config.baseParams.pattern_type || 'geometric') === opt.id;
                return (
                  <button
                    key={opt.id}
                    onClick={() => updateBaseParams({ pattern_type: opt.id })}
                    className={`px-3 py-1.5 text-sm rounded transition-colors flex items-center gap-1 ${
                      isSelected
                        ? 'bg-green-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                    }`}
                    disabled={disabled}
                  >
                    <span>{opt.icon}</span>
                    <span>{opt.label}</span>
                  </button>
                );
              })}
            </div>
            <p className="text-xs text-gray-500 mt-1">
              기하학적: 규칙적인 도형 / 군집형: 그룹화된 타일 / 랜덤: 무작위 배치
            </p>
          </div>

          {/* Symmetry Mode */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">대칭 모드</label>
            <div className="flex flex-wrap gap-2">
              {SYMMETRY_OPTIONS.map((opt) => {
                const isSelected = (config.baseParams.symmetry_mode || 'none') === opt.id;
                return (
                  <button
                    key={opt.id}
                    onClick={() => updateBaseParams({ symmetry_mode: opt.id })}
                    className={`px-3 py-1.5 text-sm rounded transition-colors flex items-center gap-1 ${
                      isSelected
                        ? 'bg-purple-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                    }`}
                    disabled={disabled}
                  >
                    <span>{opt.icon}</span>
                    <span>{opt.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Obstacles - Only shown in manual mode */}
          {config.gimmickMode === 'manual' && (
            <div>
              <label className="block text-sm font-medium text-gray-300 mb-2">장애물 (모든 레벨에 적용)</label>
              <div className="flex flex-wrap gap-2">
                {OBSTACLE_TYPES.map((obs) => {
                  const isSelected = (config.baseParams.obstacle_types || []).includes(obs.id);
                  return (
                    <button
                      key={obs.id}
                      onClick={() => toggleObstacle(obs.id)}
                      className={`px-2 py-1 text-xs rounded transition-colors ${
                        isSelected
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                      }`}
                      disabled={disabled}
                    >
                      {obs.label}
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-gray-500 mt-1">선택한 장애물이 모든 레벨에 동일하게 적용됩니다.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
