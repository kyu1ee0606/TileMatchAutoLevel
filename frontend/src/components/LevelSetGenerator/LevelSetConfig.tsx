import { useState } from 'react';
import type { LevelSetGenerationConfig } from '../../types/levelSet';
import type { GoalConfig, SymmetryMode, PatternType } from '../../types';
import { Button } from '../ui';

export interface ValidationOptions {
  enabled: boolean;
  max_retries: number;
  tolerance: number;
}

interface LevelSetConfigProps {
  config: LevelSetGenerationConfig;
  onConfigChange: (config: LevelSetGenerationConfig) => void;
  validationOptions: ValidationOptions;
  onValidationOptionsChange: (options: ValidationOptions) => void;
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

export function LevelSetConfig({
  config,
  onConfigChange,
  validationOptions,
  onValidationOptionsChange,
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

      {/* Validation Options */}
      <div className="bg-gray-700/50 p-3 rounded-lg border border-gray-600">
        <div className="flex items-center justify-between mb-2">
          <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
            <span>🎯 시뮬레이션 검증</span>
            {validationOptions.enabled && (
              <span className="text-xs text-green-400 bg-green-900/40 px-2 py-0.5 rounded">활성</span>
            )}
          </label>
          <button
            onClick={() => onValidationOptionsChange({ ...validationOptions, enabled: !validationOptions.enabled })}
            className={`relative w-12 h-6 rounded-full transition-colors ${
              validationOptions.enabled ? 'bg-green-600' : 'bg-gray-600'
            }`}
            disabled={disabled}
          >
            <span
              className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                validationOptions.enabled ? 'translate-x-6' : 'translate-x-0.5'
              }`}
            />
          </button>
        </div>
        <p className="text-xs text-gray-500 mb-2">
          각 레벨 생성 후 봇 시뮬레이션으로 난이도 검증. 목표 클리어율과 맞지 않으면 재생성.
        </p>
        {validationOptions.enabled && (
          <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-gray-600">
            <div>
              <label className="block text-xs text-gray-400 mb-1">최대 재시도</label>
              <input
                type="number"
                value={validationOptions.max_retries}
                onChange={(e) => onValidationOptionsChange({
                  ...validationOptions,
                  max_retries: Math.max(1, Math.min(10, parseInt(e.target.value) || 5))
                })}
                min={1}
                max={10}
                className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-sm"
                disabled={disabled}
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">허용 오차 (%)</label>
              <input
                type="number"
                value={validationOptions.tolerance}
                onChange={(e) => onValidationOptionsChange({
                  ...validationOptions,
                  tolerance: Math.max(5, Math.min(30, parseInt(e.target.value) || 15))
                })}
                min={5}
                max={30}
                className="w-full px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-sm"
                disabled={disabled}
              />
            </div>
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

          {/* Obstacles */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">장애물</label>
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
          </div>
        </div>
      )}
    </div>
  );
}
