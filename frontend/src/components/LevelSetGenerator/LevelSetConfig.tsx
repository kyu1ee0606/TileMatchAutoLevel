import { useState } from 'react';
import type { LevelSetGenerationConfig, GimmickMode, LevelGimmickOverride, DifficultyPoint, MultiSetConfig, LevelingMode, GenerationMode } from '../../types/levelSet';
import { createDefaultMultiSetConfig, calculateTotalLevels, STEP_10_PRESET, DEFAULT_GIMMICK_UNLOCK_LEVELS, SIMPLE_GIMMICK_UNLOCK_LEVELS, PROFESSIONAL_GIMMICK_UNLOCK_LEVELS } from '../../types/levelSet';
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
  { id: 'ice', label: '❄️ Ice' },
  { id: 'link', label: '🔗 Link' },
  { id: 'grass', label: '🌿 Grass' },
  { id: 'bomb', label: '💣 Bomb' },
  { id: 'curtain', label: '🎭 Curtain' },
  { id: 'teleport', label: '🌀 Teleport' },
  { id: 'unknown', label: '❓ Unknown' },
  { id: 'craft', label: '🔧 Craft' },
  { id: 'stack', label: '📚 Stack' },
] as const;

const SYMMETRY_OPTIONS: { id: SymmetryMode; label: string; icon: string }[] = [
  { id: 'none', label: '없음', icon: '⊗' },
  { id: 'horizontal', label: '좌우 대칭', icon: '↔' },
  { id: 'vertical', label: '상하 대칭', icon: '↕' },
  { id: 'both', label: '4방향 대칭', icon: '✛' },
];

const PATTERN_OPTIONS: { id: PatternType; label: string; icon: string }[] = [
  { id: 'aesthetic', label: '미관최적화', icon: '✨' },
  { id: 'geometric', label: '기하학적', icon: '◆' },
  { id: 'clustered', label: '군집형', icon: '⚬' },
  { id: 'random', label: '랜덤', icon: '🎲' },
];

const GIMMICK_MODE_OPTIONS: { id: GimmickMode; label: string; icon: string; description: string }[] = [
  { id: 'auto', label: '자동', icon: '🤖', description: '난이도에 따라 자동 배분' },
  { id: 'manual', label: '수동', icon: '✋', description: '모든 레벨에 동일 적용' },
  { id: 'hybrid', label: '하이브리드', icon: '🔀', description: '자동 + 레벨별 오버라이드' },
];

const LEVELING_MODE_OPTIONS: { id: LevelingMode; label: string; icon: string; description: string }[] = [
  {
    id: 'professional',
    label: '프로페셔널',
    icon: '🎮',
    description: 'Tile Buster/Explorer 스타일: 15레벨 간격, 충분한 연습 기간, 톱니바퀴 난이도'
  },
  {
    id: 'simple',
    label: '심플',
    icon: '📊',
    description: '기존 방식: 5레벨 간격, 빠른 기믹 언락'
  },
];

const GENERATION_MODE_OPTIONS: { id: GenerationMode; label: string; icon: string; description: string }[] = [
  {
    id: 'quick',
    label: '빠른 생성',
    icon: '⚡',
    description: '각 레이어마다 다른 패턴으로 빠르게 생성'
  },
  {
    id: 'pattern',
    label: '패턴 생성',
    icon: '✨',
    description: '모든 레이어가 동일한 타일 위치를 공유 (미관 최적화)'
  },
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

  const updateMultiSetConfig = (updates: Partial<MultiSetConfig>) => {
    const currentMultiSet = config.multiSetConfig || createDefaultMultiSetConfig();
    onConfigChange({
      ...config,
      multiSetConfig: { ...currentMultiSet, ...updates },
    });
  };

  const toggleMultiSetMode = () => {
    const currentMultiSet = config.multiSetConfig || createDefaultMultiSetConfig();
    const newEnabled = !currentMultiSet.enabled;

    // When enabling multi-set mode with 10 levels, apply the step preset
    if (newEnabled && config.levelCount === 10) {
      onConfigChange({
        ...config,
        multiSetConfig: { ...currentMultiSet, enabled: newEnabled },
        difficultyPoints: STEP_10_PRESET,
      });
    } else {
      onConfigChange({
        ...config,
        multiSetConfig: { ...currentMultiSet, enabled: newEnabled },
      });
    }
  };

  const multiSetConfig = config.multiSetConfig || createDefaultMultiSetConfig();
  const totalLevels = multiSetConfig.enabled
    ? calculateTotalLevels(config.levelCount, multiSetConfig.setCount)
    : config.levelCount;

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
          placeholder={multiSetConfig.enabled ? "예: 캐주얼 매치" : "예: 초보자용 레벨 세트"}
          className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          disabled={disabled}
        />
        {multiSetConfig.enabled && (
          <p className="text-xs text-gray-500 mt-1">
            각 세트는 "{config.setName || '세트'} 1", "{config.setName || '세트'} 2" ... 형식으로 저장됩니다.
          </p>
        )}
      </div>

      {/* Generation Mode - Quick vs Pattern */}
      <div className="bg-gradient-to-r from-blue-900/50 to-cyan-900/50 rounded-lg p-4 border border-blue-500/30">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">🎨</span>
          <label className="text-sm font-medium text-white">생성 모드</label>
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          {GENERATION_MODE_OPTIONS.map((opt) => {
            const isSelected = (config.generationMode || 'pattern') === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => {
                  // When switching to quick mode, change pattern_type to random
                  // When switching to pattern mode, change pattern_type to aesthetic
                  const newPatternType = opt.id === 'quick' ? 'random' : 'aesthetic';
                  onConfigChange({
                    ...config,
                    generationMode: opt.id,
                    baseParams: { ...config.baseParams, pattern_type: newPatternType },
                  });
                }}
                className={`px-4 py-3 text-sm rounded-lg transition-colors flex items-center gap-2 flex-1 min-w-[140px] ${
                  isSelected
                    ? 'bg-blue-600 text-white ring-2 ring-blue-400'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
                disabled={disabled}
                title={opt.description}
              >
                <span className="text-xl">{opt.icon}</span>
                <div className="text-left">
                  <div className="font-medium">{opt.label}</div>
                  <div className="text-xs opacity-75">{opt.id === 'quick' ? '레이어별 다른 패턴' : '일관된 타일 배치'}</div>
                </div>
              </button>
            );
          })}
        </div>

        <p className="text-xs text-blue-300">
          {(config.generationMode || 'pattern') === 'quick'
            ? '⚡ 빠른 생성: 각 레이어가 독립적인 패턴으로 생성됩니다. 다양한 레이아웃을 원할 때 사용하세요.'
            : '✨ 패턴 생성: 모든 레이어가 동일한 타일 위치를 공유합니다. 시각적으로 일관된 레벨을 원할 때 사용하세요.'}
        </p>
      </div>

      {/* Multi-Set Mode Toggle */}
      <div className="bg-gradient-to-r from-indigo-900/50 to-purple-900/50 rounded-lg p-4 border border-indigo-500/30">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🔄</span>
            <label className="text-sm font-medium text-white">다중 세트 생성</label>
          </div>
          <button
            onClick={toggleMultiSetMode}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              multiSetConfig.enabled ? 'bg-indigo-600' : 'bg-gray-600'
            }`}
            disabled={disabled}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                multiSetConfig.enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {multiSetConfig.enabled && (
          <div className="space-y-3">
            <p className="text-xs text-indigo-300 mb-3">
              기본 패턴을 여러 세트로 반복하며, 각 세트마다 난이도가 조금씩 상승합니다.
            </p>

            {/* Set Count */}
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">
                세트 수: <span className="text-indigo-400 font-bold">{multiSetConfig.setCount}</span>개
                <span className="text-gray-500 ml-2">
                  (총 <span className="text-indigo-400">{totalLevels}</span>개 레벨)
                </span>
              </label>
              <input
                type="range"
                min={2}
                max={20}
                value={multiSetConfig.setCount}
                onChange={(e) => updateMultiSetConfig({ setCount: parseInt(e.target.value) })}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
                disabled={disabled}
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>2</span>
                <span>5</span>
                <span>10</span>
                <span>15</span>
                <span>20</span>
              </div>
            </div>

            {/* Difficulty Shift Per Set */}
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1">
                세트당 난이도 증가: <span className="text-indigo-400 font-bold">{(multiSetConfig.difficultyShiftPerSet * 100).toFixed(0)}%</span>
              </label>
              <input
                type="range"
                min={1}
                max={10}
                value={multiSetConfig.difficultyShiftPerSet * 100}
                onChange={(e) => updateMultiSetConfig({ difficultyShiftPerSet: parseInt(e.target.value) / 100 })}
                className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
                disabled={disabled}
              />
              <div className="flex justify-between text-xs text-gray-500 mt-1">
                <span>1%</span>
                <span>3%</span>
                <span>5%</span>
                <span>7%</span>
                <span>10%</span>
              </div>
            </div>

            {/* Preview */}
            <div className="bg-gray-800/50 rounded p-2 text-xs">
              <div className="text-gray-400 mb-1">📊 예상 난이도 범위:</div>
              <div className="grid grid-cols-3 gap-1 text-gray-300">
                <div>세트 1: 원본</div>
                <div>세트 {Math.ceil(multiSetConfig.setCount / 2)}: +{((Math.ceil(multiSetConfig.setCount / 2) - 1) * multiSetConfig.difficultyShiftPerSet * 100).toFixed(0)}%</div>
                <div>세트 {multiSetConfig.setCount}: +{((multiSetConfig.setCount - 1) * multiSetConfig.difficultyShiftPerSet * 100).toFixed(0)}%</div>
              </div>
            </div>
          </div>
        )}

        {!multiSetConfig.enabled && (
          <p className="text-xs text-gray-400">
            활성화하면 동일한 패턴의 세트를 여러 개 생성하면서 난이도를 점진적으로 상승시킬 수 있습니다.
          </p>
        )}
      </div>

      {/* Leveling Mode - Professional Leveling System */}
      <div className="bg-gradient-to-r from-emerald-900/50 to-teal-900/50 rounded-lg p-4 border border-emerald-500/30">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">🎯</span>
          <label className="text-sm font-medium text-white">레벨링 모드</label>
          <span className="text-xs text-emerald-400 ml-2">(Tile Buster/Explorer 스타일)</span>
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          {LEVELING_MODE_OPTIONS.map((opt) => {
            const isSelected = (config.levelingMode || 'professional') === opt.id;
            return (
              <button
                key={opt.id}
                onClick={() => {
                  const unlockLevels = opt.id === 'professional'
                    ? PROFESSIONAL_GIMMICK_UNLOCK_LEVELS
                    : SIMPLE_GIMMICK_UNLOCK_LEVELS;
                  onConfigChange({
                    ...config,
                    levelingMode: opt.id,
                    gimmickUnlockLevels: unlockLevels,
                    useSawtoothPattern: opt.id === 'professional',
                  });
                }}
                className={`px-3 py-2 text-sm rounded-lg transition-colors flex items-center gap-2 ${
                  isSelected
                    ? 'bg-emerald-600 text-white ring-2 ring-emerald-400'
                    : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
                }`}
                disabled={disabled}
                title={opt.description}
              >
                <span className="text-lg">{opt.icon}</span>
                <div className="text-left">
                  <div className="font-medium">{opt.label}</div>
                  <div className="text-xs opacity-75">{opt.id === 'professional' ? '15레벨 간격' : '5레벨 간격'}</div>
                </div>
              </button>
            );
          })}
        </div>

        <p className="text-xs text-emerald-300 mb-3">
          {(config.levelingMode || 'professional') === 'professional'
            ? '🎮 유명 타일 게임 패턴: 레벨 1-10 순수 학습 → 각 기믹 9레벨 연습 → 점진적 조합'
            : '📊 기존 방식: 5레벨마다 새 기믹 언락, 빠른 진행'}
        </p>

        {/* Sawtooth Pattern Toggle */}
        <div className="flex items-center justify-between bg-gray-800/50 rounded p-2">
          <div>
            <span className="text-sm text-gray-300">📈 톱니바퀴 난이도 패턴</span>
            <p className="text-xs text-gray-500">10레벨 단위로 쉬움→어려움→보스→휴식 순환</p>
          </div>
          <button
            onClick={() => onConfigChange({ ...config, useSawtoothPattern: !config.useSawtoothPattern })}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              config.useSawtoothPattern !== false ? 'bg-emerald-600' : 'bg-gray-600'
            }`}
            disabled={disabled}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                config.useSawtoothPattern !== false ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {/* Start Level Number */}
        <div className="mt-3">
          <label className="block text-xs font-medium text-gray-400 mb-1">
            시작 레벨 번호 (기믹 언락 기준)
          </label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={config.startLevelNumber || 1}
              onChange={(e) => onConfigChange({ ...config, startLevelNumber: parseInt(e.target.value) || 1 })}
              min={1}
              max={1000}
              className="w-24 px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white text-sm"
              disabled={disabled}
            />
            <span className="text-xs text-gray-400">
              예: 시작=51이면 레벨 51부터 기믹 언락 계산
            </span>
          </div>
        </div>
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

      {/* Layer Range */}
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            최소 레이어 (쉬운 난이도): <span className="text-blue-400">{config.baseParams.min_layers || 3}</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            value={config.baseParams.min_layers || 3}
            onChange={(e) => {
              const minVal = parseInt(e.target.value);
              const maxVal = config.baseParams.max_layers || 7;
              updateBaseParams({
                min_layers: minVal,
                max_layers: Math.max(minVal, maxVal)
              });
            }}
            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
            disabled={disabled}
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            최대 레이어 (어려운 난이도): <span className="text-blue-400">{config.baseParams.max_layers || 7}</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            value={config.baseParams.max_layers || 7}
            onChange={(e) => {
              const maxVal = parseInt(e.target.value);
              const minVal = config.baseParams.min_layers || 3;
              updateBaseParams({
                max_layers: maxVal,
                min_layers: Math.min(minVal, maxVal)
              });
            }}
            className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer"
            disabled={disabled}
          />
        </div>
        <p className="text-xs text-gray-500">
          난이도에 따라 레이어 수가 {config.baseParams.min_layers || 3}~{config.baseParams.max_layers || 7} 범위 내에서 자동 결정됩니다
        </p>
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

      {/* Gimmick Unlock System */}
      <div className="bg-gradient-to-r from-amber-900/50 to-orange-900/50 rounded-lg p-4 border border-amber-500/30">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">🔓</span>
            <label className="text-sm font-medium text-white">기믹 언락 시스템</label>
          </div>
          <button
            onClick={() => onConfigChange({ ...config, useGimmickUnlock: !config.useGimmickUnlock })}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
              config.useGimmickUnlock ? 'bg-amber-600' : 'bg-gray-600'
            }`}
            disabled={disabled}
          >
            <span
              className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                config.useGimmickUnlock ? 'translate-x-6' : 'translate-x-1'
              }`}
            />
          </button>
        </div>

        {config.useGimmickUnlock && (
          <div className="space-y-3">
            <p className="text-xs text-amber-300 mb-3">
              각 기믹이 특정 레벨에서 언락됩니다. 레벨 번호에 도달해야 해당 기믹이 사용됩니다.
            </p>

            {/* Quick Preset Buttons */}
            <div className="flex flex-wrap gap-2 mb-3">
              <button
                onClick={() => onConfigChange({
                  ...config,
                  gimmickUnlockLevels: { ...DEFAULT_GIMMICK_UNLOCK_LEVELS }
                })}
                className="px-2 py-1 text-xs bg-amber-700 hover:bg-amber-600 text-white rounded"
                disabled={disabled}
              >
                10단위 기본값
              </button>
              <button
                onClick={() => onConfigChange({
                  ...config,
                  gimmickUnlockLevels: {
                    craft: 20, stack: 40, ice: 60, link: 80, chain: 100,
                    key: 120, grass: 140, unknown: 160, curtain: 180,
                    bomb: 200, time_attack: 220, frog: 240, teleport: 260
                  }
                })}
                className="px-2 py-1 text-xs bg-amber-700 hover:bg-amber-600 text-white rounded"
                disabled={disabled}
              >
                20단위
              </button>
              <button
                onClick={() => onConfigChange({
                  ...config,
                  gimmickUnlockLevels: {
                    craft: 1, stack: 1, ice: 1, link: 1, chain: 1,
                    key: 1, grass: 1, unknown: 1, curtain: 1,
                    bomb: 1, time_attack: 1, frog: 1, teleport: 1
                  }
                })}
                className="px-2 py-1 text-xs bg-amber-700 hover:bg-amber-600 text-white rounded"
                disabled={disabled}
              >
                모두 시작부터
              </button>
            </div>

            {/* Unlock Level Inputs */}
            <div className="grid grid-cols-2 gap-2">
              {OBSTACLE_TYPES.map((obs) => {
                const currentUnlock = config.gimmickUnlockLevels?.[obs.id] ?? DEFAULT_GIMMICK_UNLOCK_LEVELS[obs.id] ?? 1;
                return (
                  <div key={obs.id} className="flex items-center gap-2 bg-gray-800/50 rounded p-2">
                    <span className="text-sm w-24">{obs.label}</span>
                    <input
                      type="number"
                      value={currentUnlock}
                      onChange={(e) => {
                        const newValue = parseInt(e.target.value) || 1;
                        onConfigChange({
                          ...config,
                          gimmickUnlockLevels: {
                            ...(config.gimmickUnlockLevels ?? DEFAULT_GIMMICK_UNLOCK_LEVELS),
                            [obs.id]: newValue
                          }
                        });
                      }}
                      min={1}
                      max={1000}
                      className="w-20 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-white text-sm"
                      disabled={disabled}
                    />
                    <span className="text-xs text-gray-400">레벨</span>
                  </div>
                );
              })}
            </div>

            {/* Preview */}
            <div className="bg-gray-800/50 rounded p-2 text-xs mt-3">
              <div className="text-gray-400 mb-1">📊 언락 순서:</div>
              <div className="text-amber-300">
                {Object.entries(config.gimmickUnlockLevels ?? DEFAULT_GIMMICK_UNLOCK_LEVELS)
                  .sort(([, a], [, b]) => a - b)
                  .map(([gimmick, level]) => `${gimmick}(${level})`)
                  .join(' → ')}
              </div>
            </div>
          </div>
        )}

        {!config.useGimmickUnlock && (
          <p className="text-xs text-gray-400">
            활성화하면 레벨 번호에 따라 기믹이 순차적으로 언락됩니다. 튜토리얼 → 고급 레벨 구성에 적합합니다.
          </p>
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
