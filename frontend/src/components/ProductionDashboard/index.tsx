/**
 * Production Dashboard
 * 1500개 레벨 프로덕션 관리 대시보드
 */

import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel, generateValidatedLevel } from '../../api/generate';
import { analyzeAutoPlay } from '../../api/analyze';
import GamePlayer from '../GamePlayer';
import GameBoard from '../GamePlayer/GameBoard';
import { createGameEngine } from '../../engine/gameEngine';
import type { GameStats, LevelInfo, GameTile } from '../../types/game';
import type { GenerationParams, DifficultyGrade, LevelJSON } from '../../types';
import {
  ProductionBatch,
  ProductionLevel,
  ProductionLevelMeta,
  ProductionStats,
  PlaytestResult,
  PlaytestQueueConfig,
  PlaytestStrategy,
  LevelStatus,
  ProductionGenerationProgress,
  PRODUCTION_1500_PRESETS,
  shouldRequirePlaytest,
} from '../../types/production';
import {
  PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
} from '../../types/levelSet';
import {
  initProductionDB,
  createProductionBatch,
  getProductionBatch,
  listProductionBatches,
  saveProductionLevels,
  getProductionLevelsByBatch,
  getPlaytestQueue,
  addPlaytestResult,
  approveLevel,
  rejectLevel,
  calculateProductionStats,
  exportProductionLevels,
  deleteProductionBatch,
  recalculateBatchCounts,
} from '../../storage/productionStorage';

type DashboardTab = 'overview' | 'generate' | 'test' | 'playtest' | 'review' | 'export';

interface ProductionDashboardProps {
  onLevelSelect?: (level: ProductionLevel) => void;
}

export function ProductionDashboard({ onLevelSelect }: ProductionDashboardProps) {
  const { addNotification } = useUIStore();
  const [activeTab, setActiveTab] = useState<DashboardTab>('overview');
  const [batches, setBatches] = useState<ProductionBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [stats, setStats] = useState<ProductionStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Generation state
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationProgress, setGenerationProgress] = useState<ProductionGenerationProgress>({
    status: 'idle',
    total_sets: 0,
    completed_sets: 0,
    current_set_index: 0,
    total_levels: 0,
    completed_levels: 0,
    current_level: 0,
    elapsed_ms: 0,
    estimated_remaining_ms: 0,
    failed_levels: [],
    checkpoint_interval_levels: 50,
  });

  const abortControllerRef = useRef<AbortController | null>(null);

  // Initialize DB and load batches
  useEffect(() => {
    async function init() {
      try {
        await initProductionDB();
        const loadedBatches = await listProductionBatches();
        setBatches(loadedBatches);

        // Auto-select latest batch
        if (loadedBatches.length > 0) {
          const latest = loadedBatches.sort((a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
          )[0];
          setSelectedBatchId(latest.id);
        }
      } catch (err) {
        console.error('Failed to initialize production DB:', err);
        addNotification('error', '프로덕션 DB 초기화 실패');
      } finally {
        setIsLoading(false);
      }
    }
    init();
  }, [addNotification]);

  // Load stats when batch changes
  useEffect(() => {
    async function loadStats() {
      if (!selectedBatchId) {
        setStats(null);
        return;
      }
      try {
        const batchStats = await calculateProductionStats(selectedBatchId);
        setStats(batchStats);
      } catch (err) {
        console.error('Failed to load stats:', err);
      }
    }
    loadStats();
  }, [selectedBatchId]);

  // Create new 1500 level batch
  const handleCreateBatch = useCallback(async (preset: keyof typeof PRODUCTION_1500_PRESETS) => {
    const presetConfig = PRODUCTION_1500_PRESETS[preset];

    try {
      const batch = await createProductionBatch({
        name: `${presetConfig.name} - ${new Date().toLocaleDateString()}`,
        total_levels: 1500,
        levels_per_set: 10,
        total_sets: 150,
        generated_count: 0,
        playtest_count: 0,
        approved_count: 0,
        rejected_count: 0,
        exported_count: 0,
        difficulty_start: presetConfig.difficulty_start,
        difficulty_end: presetConfig.difficulty_end,
        use_sawtooth: presetConfig.use_sawtooth,
        gimmick_unlock_levels: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
      });

      setBatches(prev => [batch, ...prev]);
      setSelectedBatchId(batch.id);
      addNotification('success', `배치 "${batch.name}" 생성됨`);
      setActiveTab('generate');
    } catch (err) {
      addNotification('error', '배치 생성 실패');
    }
  }, [addNotification]);

  // Generate levels for batch
  const handleStartGeneration = useCallback(async (
    playtestConfig: PlaytestQueueConfig
  ) => {
    if (!selectedBatchId) return;

    const batch = await getProductionBatch(selectedBatchId);
    if (!batch) return;

    setIsGenerating(true);
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const startTime = Date.now();
    setGenerationProgress({
      status: 'generating',
      total_sets: batch.total_sets,
      completed_sets: 0,
      current_set_index: 0,
      total_levels: batch.total_levels,
      completed_levels: 0,
      current_level: 0,
      elapsed_ms: 0,
      estimated_remaining_ms: 0,
      started_at: new Date().toISOString(),
      failed_levels: [],
      checkpoint_interval_levels: 50,
    });

    const pendingLevels: ProductionLevel[] = [];
    let completedCount = 0;
    const failedLevels: number[] = [];

    try {
      for (let setIdx = 0; setIdx < batch.total_sets; setIdx++) {
        if (signal.aborted) throw new Error('cancelled');

        setGenerationProgress(prev => ({
          ...prev,
          current_set_index: setIdx,
        }));

        // Calculate difficulty for this set
        const setProgress = setIdx / (batch.total_sets - 1);
        let baseDifficulty: number;

        if (batch.use_sawtooth) {
          // Sawtooth pattern: increase within set, reset at new set
          const overallDifficulty =
            batch.difficulty_start +
            setProgress * (batch.difficulty_end - batch.difficulty_start);

          baseDifficulty = overallDifficulty;
        } else {
          baseDifficulty =
            batch.difficulty_start +
            setProgress * (batch.difficulty_end - batch.difficulty_start);
        }

        for (let localIdx = 1; localIdx <= batch.levels_per_set; localIdx++) {
          if (signal.aborted) throw new Error('cancelled');

          const levelNumber = setIdx * batch.levels_per_set + localIdx;

          // Calculate level-specific difficulty
          let targetDifficulty = baseDifficulty;

          if (batch.use_sawtooth) {
            // Sawtooth within set: gradual increase, spike at level 10
            const localProgress = (localIdx - 1) / (batch.levels_per_set - 1);
            const sawtoothBonus = localIdx === 10 ? 0.1 : localProgress * 0.05;
            targetDifficulty = Math.min(0.95, baseDifficulty + sawtoothBonus);
          }

          setGenerationProgress(prev => ({
            ...prev,
            current_level: levelNumber,
            elapsed_ms: Date.now() - startTime,
            estimated_remaining_ms: completedCount > 0
              ? ((Date.now() - startTime) / completedCount) * (batch.total_levels - completedCount)
              : 0,
          }));

          try {
            // Generate level with randomized variety
            // Randomize pattern type for visual diversity
            const patternTypes: Array<'aesthetic' | 'geometric' | 'clustered'> = ['aesthetic', 'geometric', 'clustered'];
            const patternType = patternTypes[Math.floor(Math.random() * patternTypes.length)];

            // Let backend handle symmetry randomly (removed fixed 'both')
            // This allows horizontal, vertical, none, or both symmetry for variety

            // Randomize symmetry mode
            const symmetryModes: Array<'none' | 'horizontal' | 'vertical'> = ['none', 'horizontal', 'vertical'];
            const symmetryMode = symmetryModes[Math.floor(Math.random() * symmetryModes.length)];

            // All goal directions are now supported - backend handles mirroring for symmetry
            const goalDirections: Array<'s' | 'n' | 'e' | 'w'> = ['s', 'n', 'e', 'w'];
            const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];

            // Randomize goal types between craft and stack
            const goalTypes: Array<'craft' | 'stack'> = ['craft', 'stack'];
            const goalType = goalTypes[Math.floor(Math.random() * goalTypes.length)];

            const params: GenerationParams = {
              target_difficulty: targetDifficulty,
              grid_size: [7, 7],
              max_layers: Math.min(7, 3 + Math.floor(targetDifficulty * 4)),
              tile_types: ['t1', 't2', 't3', 't4', 't5', 't6'].slice(0, 3 + Math.floor(targetDifficulty * 3)),
              obstacle_types: [],
              goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
              symmetry_mode: symmetryMode,
              pattern_type: patternType,
            };

            const result = await generateLevel(params, {
              auto_select_gimmicks: true,
              available_gimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
              gimmick_unlock_levels: batch.gimmick_unlock_levels,
              level_number: levelNumber,
              gimmick_intensity: Math.min(1, levelNumber / 500),
            });

            // Create production level
            const meta: ProductionLevelMeta = {
              level_number: levelNumber,
              set_index: setIdx,
              local_index: localIdx,
              generated_at: new Date().toISOString(),
              target_difficulty: targetDifficulty,
              actual_difficulty: result.actual_difficulty,
              grade: result.grade as DifficultyGrade,
              status: 'generated',
              status_updated_at: new Date().toISOString(),
              playtest_required: shouldRequirePlaytest(
                { level_number: levelNumber, grade: result.grade as DifficultyGrade, match_score: 80, target_difficulty: targetDifficulty },
                playtestConfig
              ),
              playtest_priority: levelNumber,  // Lower = higher priority
              playtest_results: [],
            };

            if (meta.playtest_required) {
              meta.status = 'playtest_queue';
            }

            const prodLevel: ProductionLevel = {
              meta,
              level_json: result.level_json,
            };

            pendingLevels.push(prodLevel);
            completedCount++;

            // Checkpoint save every N levels
            if (pendingLevels.length >= 50) {
              await saveProductionLevels(selectedBatchId, pendingLevels);
              await recalculateBatchCounts(selectedBatchId);  // Update batch counts
              pendingLevels.length = 0;
              setGenerationProgress(prev => ({
                ...prev,
                last_checkpoint_at: new Date().toISOString(),
                completed_levels: completedCount,
              }));
            }
          } catch (err) {
            console.error(`Failed to generate level ${levelNumber}:`, err);
            failedLevels.push(levelNumber);
          }
        }

        setGenerationProgress(prev => ({
          ...prev,
          completed_sets: setIdx + 1,
          completed_levels: completedCount,
        }));
      }

      // Save remaining levels
      if (pendingLevels.length > 0) {
        await saveProductionLevels(selectedBatchId, pendingLevels);
      }

      // Update batch counts after all levels are saved
      await recalculateBatchCounts(selectedBatchId);

      setGenerationProgress(prev => ({
        ...prev,
        status: 'completed',
        completed_levels: completedCount,
        failed_levels: failedLevels,
      }));

      // Refresh stats and batch list
      const newStats = await calculateProductionStats(selectedBatchId);
      setStats(newStats);

      // Refresh batches list to show updated generated_count
      const updatedBatches = await listProductionBatches();
      setBatches(updatedBatches);

      addNotification(
        'success',
        `${completedCount}개 레벨 생성 완료! (실패: ${failedLevels.length}개)`
      );
    } catch (err) {
      if ((err as Error).message === 'cancelled') {
        // Save any pending levels before cancelling
        if (pendingLevels.length > 0) {
          await saveProductionLevels(selectedBatchId, pendingLevels);
        }
        // Update batch counts after pause
        await recalculateBatchCounts(selectedBatchId);
        setGenerationProgress(prev => ({
          ...prev,
          status: 'paused',
          completed_levels: completedCount,
        }));
        addNotification('info', `생성 일시 정지됨 (${completedCount}개 저장됨)`);
      } else {
        setGenerationProgress(prev => ({
          ...prev,
          status: 'error',
          last_error: (err as Error).message,
        }));
        addNotification('error', `생성 오류: ${(err as Error).message}`);
      }
    } finally {
      setIsGenerating(false);
    }
  }, [selectedBatchId, addNotification]);

  // Cancel generation
  const handleCancelGeneration = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  // Delete batch
  const handleDeleteBatch = useCallback(async (batchId: string) => {
    if (!confirm('이 배치를 삭제하시겠습니까? 모든 레벨이 삭제됩니다.')) {
      return;
    }

    try {
      await deleteProductionBatch(batchId);
      setBatches(prev => prev.filter(b => b.id !== batchId));
      if (selectedBatchId === batchId) {
        setSelectedBatchId(batches.find(b => b.id !== batchId)?.id || null);
      }
      addNotification('success', '배치 삭제됨');
    } catch (err) {
      addNotification('error', '배치 삭제 실패');
    }
  }, [selectedBatchId, batches, addNotification]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        로딩 중...
      </div>
    );
  }

  const selectedBatch = batches.find(b => b.id === selectedBatchId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white">
          프로덕션 레벨 관리
        </h2>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleCreateBatch('sawtooth')}
          >
            + 새 1500 배치 (톱니바퀴)
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => handleCreateBatch('linear')}
          >
            + 새 1500 배치 (선형)
          </Button>
        </div>
      </div>

      {/* Batch Selector */}
      {batches.length > 0 && (
        <div className="flex items-center gap-2 p-2 bg-gray-800 rounded-lg">
          <label className="text-sm text-gray-400">배치:</label>
          <select
            value={selectedBatchId || ''}
            onChange={(e) => setSelectedBatchId(e.target.value)}
            className="flex-1 px-3 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
          >
            {batches.map((batch) => (
              <option key={batch.id} value={batch.id}>
                {batch.name} ({batch.generated_count}/{batch.total_levels})
              </option>
            ))}
          </select>
          {selectedBatch && (
            <Button
              variant="danger"
              size="sm"
              onClick={() => handleDeleteBatch(selectedBatch.id)}
            >
              삭제
            </Button>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-700">
        {[
          { id: 'overview', label: '개요' },
          { id: 'generate', label: '생성' },
          { id: 'test', label: '테스트' },
          { id: 'playtest', label: '플레이테스트' },
          { id: 'review', label: '검토' },
          { id: 'export', label: '내보내기' },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as DashboardTab)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-indigo-400 border-b-2 border-indigo-400'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === 'overview' && stats && selectedBatch && (
          <OverviewTab stats={stats} batch={selectedBatch} />
        )}

        {activeTab === 'generate' && selectedBatch && (
          <GenerateTab
            batch={selectedBatch}
            progress={generationProgress}
            isGenerating={isGenerating}
            onStart={handleStartGeneration}
            onCancel={handleCancelGeneration}
          />
        )}

        {activeTab === 'test' && selectedBatchId && (
          <TestTab
            batchId={selectedBatchId}
            onStatsUpdate={async () => {
              const newStats = await calculateProductionStats(selectedBatchId);
              setStats(newStats);
            }}
          />
        )}

        {activeTab === 'playtest' && selectedBatchId && (
          <PlaytestTab
            batchId={selectedBatchId}
            onLevelSelect={onLevelSelect}
          />
        )}

        {activeTab === 'review' && selectedBatchId && (
          <ReviewTab
            batchId={selectedBatchId}
            onLevelSelect={onLevelSelect}
            onStatsUpdate={async () => {
              const newStats = await calculateProductionStats(selectedBatchId);
              setStats(newStats);
            }}
          />
        )}

        {activeTab === 'export' && selectedBatchId && stats && (
          <ExportTab
            batchId={selectedBatchId}
            stats={stats}
          />
        )}

        {!selectedBatch && !isLoading && (
          <div className="flex flex-col items-center justify-center h-64 text-gray-500">
            <p>배치가 없습니다.</p>
            <p className="text-sm mt-2">위의 버튼으로 새 1500 레벨 배치를 생성하세요.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// Overview Tab Component
function OverviewTab({ stats, batch }: { stats: ProductionStats; batch: ProductionBatch }) {
  return (
    <div className="space-y-6">
      {/* Progress Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="생성됨" value={batch.generated_count} total={batch.total_levels} />
        <StatCard label="플레이테스트" value={stats.playtest_progress.completed} total={stats.playtest_progress.total_required} />
        <StatCard label="승인됨" value={stats.by_status.approved} total={batch.total_levels} color="green" />
        <StatCard label="거부/수정필요" value={stats.by_status.rejected + stats.by_status.needs_rework} color="red" />
      </div>

      {/* Grade Distribution */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">등급 분포</h3>
        <div className="flex gap-2">
          {(['S', 'A', 'B', 'C', 'D'] as const).map((grade) => (
            <div key={grade} className="flex-1 text-center">
              <div className={`text-lg font-bold ${getGradeColor(grade)}`}>
                {stats.by_grade[grade]}
              </div>
              <div className="text-xs text-gray-400">{grade}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Quality Metrics */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">품질 지표</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-gray-400">평균 매치 점수</div>
            <div className="text-white font-medium">{stats.quality_metrics.avg_match_score.toFixed(1)}%</div>
          </div>
          <div>
            <div className="text-gray-400">평균 재미 점수</div>
            <div className="text-white font-medium">{stats.quality_metrics.avg_fun_rating.toFixed(1)}/5</div>
          </div>
          <div>
            <div className="text-gray-400">거부율</div>
            <div className="text-white font-medium">{(stats.quality_metrics.rejection_rate * 100).toFixed(1)}%</div>
          </div>
          <div>
            <div className="text-gray-400">출시 대기</div>
            <div className="text-white font-medium">{stats.estimated_completion.ready_for_export}개</div>
          </div>
        </div>
      </div>

      {/* Status Timeline */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">상태별 현황</h3>
        <div className="space-y-2">
          <StatusBar label="생성됨" count={stats.by_status.generated} total={batch.total_levels} color="blue" />
          <StatusBar label="플레이테스트 대기" count={stats.by_status.playtest_queue} total={batch.total_levels} color="yellow" />
          <StatusBar label="승인됨" count={stats.by_status.approved} total={batch.total_levels} color="green" />
          <StatusBar label="내보내기 완료" count={stats.by_status.exported} total={batch.total_levels} color="purple" />
        </div>
      </div>
    </div>
  );
}

// Generate Tab Component
function GenerateTab({
  batch,
  progress,
  isGenerating,
  onStart,
  onCancel,
}: {
  batch: ProductionBatch;
  progress: ProductionGenerationProgress;
  isGenerating: boolean;
  onStart: (config: PlaytestQueueConfig) => void;
  onCancel: () => void;
}) {
  const [playtestStrategy, setPlaytestStrategy] = useState<PlaytestStrategy>('sample_boss');

  const progressPercent = progress.total_levels > 0
    ? (progress.completed_levels / progress.total_levels) * 100
    : 0;

  const formatTime = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    if (hours > 0) {
      return `${hours}시간 ${minutes % 60}분`;
    }
    return `${minutes}분 ${seconds % 60}초`;
  };

  return (
    <div className="space-y-4">
      {/* Configuration */}
      {!isGenerating && progress.status !== 'generating' && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-4">
          <h3 className="text-sm font-medium text-white">생성 설정</h3>

          {/* Playtest Strategy */}
          <div>
            <label className="block text-sm text-gray-400 mb-1">플레이테스트 샘플링</label>
            <select
              value={playtestStrategy}
              onChange={(e) => setPlaytestStrategy(e.target.value as PlaytestStrategy)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            >
              <option value="sample_boss">보스 레벨만 (10의 배수, ~150개)</option>
              <option value="sample_10">10개당 1개 (~150개)</option>
              <option value="tutorial">튜토리얼 레벨만 (11개)</option>
              <option value="grade_sample">등급별 샘플 (~300개)</option>
              <option value="low_match">매치 점수 낮은 레벨 (~300개)</option>
              <option value="all">전체 (1500개)</option>
            </select>
          </div>

          {/* Summary */}
          <div className="text-sm text-gray-400">
            <div>총 {batch.total_levels}개 레벨 생성</div>
            <div>난이도 범위: {(batch.difficulty_start * 100).toFixed(0)}% ~ {(batch.difficulty_end * 100).toFixed(0)}%</div>
            <div>패턴: {batch.use_sawtooth ? '톱니바퀴 (보스/휴식 사이클)' : '선형 증가'}</div>
          </div>

          <Button
            onClick={() => onStart({ strategy: playtestStrategy })}
            className="w-full"
          >
            생성 시작 ({batch.total_levels}개)
          </Button>
        </div>
      )}

      {/* Progress */}
      {(isGenerating || progress.status !== 'idle') && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-4">
          <div className="flex justify-between items-center">
            <h3 className="text-sm font-medium text-white">생성 진행</h3>
            <span className="text-xs text-gray-400">
              {progress.status === 'generating' ? '생성 중...' :
               progress.status === 'completed' ? '완료' :
               progress.status === 'paused' ? '일시 정지' :
               progress.status === 'error' ? '오류' : ''}
            </span>
          </div>

          {/* Progress Bar */}
          <div>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>레벨 {progress.completed_levels}/{progress.total_levels}</span>
              <span>{progressPercent.toFixed(1)}%</span>
            </div>
            <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${
                  progress.status === 'error' ? 'bg-red-500' :
                  progress.status === 'completed' ? 'bg-green-500' :
                  'bg-indigo-500'
                }`}
                style={{ width: `${progressPercent}%` }}
              />
            </div>
          </div>

          {/* Time Info */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-gray-400">경과 시간</div>
              <div className="text-white">{formatTime(progress.elapsed_ms)}</div>
            </div>
            <div>
              <div className="text-gray-400">예상 남은 시간</div>
              <div className="text-white">{formatTime(progress.estimated_remaining_ms)}</div>
            </div>
          </div>

          {/* Current Status */}
          <div className="text-sm text-gray-400">
            세트 {progress.current_set_index + 1}/{progress.total_sets} - 레벨 {progress.current_level}
          </div>

          {/* Error Message */}
          {progress.last_error && (
            <div className="text-sm text-red-400">
              오류: {progress.last_error}
            </div>
          )}

          {/* Actions */}
          {isGenerating && (
            <Button onClick={onCancel} variant="danger" className="w-full">
              일시 정지
            </Button>
          )}

          {progress.status === 'paused' && (
            <Button onClick={() => onStart({ strategy: playtestStrategy })} className="w-full">
              계속 생성
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

// Helper function to extract gimmicks from level_json
function extractGimmicksFromLevel(levelJson: LevelJSON): string[] {
  const gimmicks = new Set<string>();

  // Handle nested structure: level_json might have .map wrapper
  let data = levelJson as unknown as Record<string, unknown>;
  if (data.map && typeof data.map === 'object') {
    data = data.map as Record<string, unknown>;
  }

  const numLayers = (data.layer as number) || 8;

  // Extract gimmicks from tile types and attributes
  for (let i = 0; i < numLayers; i++) {
    const layerKey = `layer_${i}`;
    const layerData = data[layerKey] as { tiles?: Record<string, unknown[]> } | undefined;
    if (!layerData || !layerData.tiles) continue;

    for (const pos in layerData.tiles) {
      const tileData = layerData.tiles[pos];
      if (!tileData || !Array.isArray(tileData) || tileData.length === 0) continue;

      // Check tile type (tileData[0]) for craft/stack goals
      const tileType = tileData[0];
      if (typeof tileType === 'string') {
        if (tileType.startsWith('craft')) {
          gimmicks.add('craft');
        } else if (tileType.startsWith('stack')) {
          gimmicks.add('stack');
        }
      }

      // Check attribute (tileData[1]) for other gimmicks
      if (tileData.length > 1) {
        const attr = tileData[1];
        // Filter out tile types (t0, t1, t2, etc.) - only match exact patterns like t0, t1, t2...
        // Don't filter 'teleport' which also starts with 't'
        if (attr && typeof attr === 'string' && !attr.match(/^t\d+$/)) {
          // Normalize gimmick names:
          // - link_e, link_w, link_n, link_s → link
          // - ice_1, ice_2, ice_3 → ice
          // - curtain_open, curtain_close → curtain
          // - grass_1, grass_2 → grass
          let baseName = attr;
          if (attr.startsWith('link_')) {
            baseName = 'link';
          } else if (attr.startsWith('curtain_')) {
            baseName = 'curtain';
          } else {
            // Remove numeric suffixes like ice_1, grass_2
            baseName = attr.replace(/_\d+$/, '');
          }
          gimmicks.add(baseName);
        }
      }
    }
  }

  return Array.from(gimmicks);
}

// Gimmick display names in Korean
const GIMMICK_NAMES: Record<string, string> = {
  chain: '체인',
  ice: '얼음',
  frog: '개구리',
  grass: '잔디',
  link: '링크',
  bomb: '폭탄',
  curtain: '커튼',
  teleport: '텔레포트',
  unknown: '???',
  craft: '생성기',
  stack: '스택',
};

// Gimmick colors for display
const GIMMICK_COLORS: Record<string, string> = {
  chain: 'bg-yellow-600',
  ice: 'bg-blue-400',
  frog: 'bg-green-500',
  grass: 'bg-green-700',
  link: 'bg-purple-500',
  bomb: 'bg-red-500',
  curtain: 'bg-gray-500',
  teleport: 'bg-indigo-500',
  unknown: 'bg-gray-600',
  craft: 'bg-orange-500',
  stack: 'bg-pink-500',
};

// Test Tab Component - 레벨 테스트 (수동/자동)
function TestTab({
  batchId,
  onStatsUpdate,
}: {
  batchId: string;
  onStatsUpdate: () => void;
}) {
  const { addNotification } = useUIStore();
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedLevel, setSelectedLevel] = useState<ProductionLevel | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [filter, setFilter] = useState<LevelStatus | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Test mode: manual (play), auto_single (bot sim for selected), auto_batch (batch bot sim)
  const [testMode, setTestMode] = useState<'manual' | 'auto_single' | 'auto_batch'>('manual');

  // Auto test state
  const [isAutoTesting, setIsAutoTesting] = useState(false);
  const [autoTestResult, setAutoTestResult] = useState<{
    match_score: number;
    autoplay_grade: string;
    balance_status: string;
    bot_stats: { profile: string; clear_rate: number; target_clear_rate: number }[];
    recommendations: string[];
  } | null>(null);
  const [autoTestIterations, setAutoTestIterations] = useState(100);

  // Batch auto test state
  const [batchTestProgress, setBatchTestProgress] = useState<{
    status: 'idle' | 'running' | 'paused' | 'completed' | 'error';
    total: number;
    completed: number;
    currentLevel: number;
    results: {
      level_number: number;
      match_score: number;
      grade: string;
      status: string;
      target_difficulty: number;
      autoplay_score: number;
      static_score: number;
    }[];
    failedLevels: number[];
  }>({
    status: 'idle',
    total: 0,
    completed: 0,
    currentLevel: 0,
    results: [],
    failedLevels: [],
  });
  const [batchTestFilter, setBatchTestFilter] = useState<'all' | 'untested' | 'boss' | 'tutorial' | 'low_match' | 'range'>('untested');
  const [batchTestRange, setBatchTestRange] = useState({ min: 1, max: 100 });
  const [batchTestMaxLevels, setBatchTestMaxLevels] = useState(50);
  const batchAbortRef = useRef<AbortController | null>(null);

  // Preview tiles for selected level
  const [previewTiles, setPreviewTiles] = useState<GameTile[]>([]);
  const [previewScale, setPreviewScale] = useState(1);
  const previewContainerRef = useRef<HTMLDivElement>(null);

  // Playtest result state (after game ends)
  const [showResultForm, setShowResultForm] = useState(false);
  const [showLevelJson, setShowLevelJson] = useState(false);
  const [gameResult, setGameResult] = useState<{ won: boolean; stats: GameStats } | null>(null);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    loadLevels();
  }, [batchId, filter]);

  // Generate preview tiles when selected level changes
  useEffect(() => {
    if (!selectedLevel) {
      setPreviewTiles([]);
      return;
    }

    try {
      // Parse level data
      let levelToUse = selectedLevel.level_json as unknown as Record<string, unknown>;
      if (levelToUse.map && typeof levelToUse.map === 'object') {
        levelToUse = levelToUse.map as Record<string, unknown>;
      }

      // Create game engine to extract tiles
      // previewMode: true - 맵툴에서는 첫 타일 스폰 안 함, 원래 카운트(*3) 표시
      const engine = createGameEngine();
      engine.initializeFromLevel(levelToUse, { previewMode: true });
      const tiles = engine.getTilesForUI();

      // Convert to GameTile format
      const gameTiles: GameTile[] = tiles.map(t => ({
        id: t.id,
        type: t.type,
        attribute: t.attribute,
        layer: t.layer,
        row: t.row,
        col: t.col,
        isSelectable: t.isSelectable,
        isSelected: false,
        isMatched: false,
        isHidden: t.isHidden,
        effectData: t.effectData,
        extra: t.extra,
        // Stack visual info
        isStackTile: t.isStackTile,
        stackIndex: t.stackIndex,
        stackMaxIndex: t.stackMaxIndex,
      }));

      // Calculate scale based on fixed 7x7 grid and container size
      // Fixed board size: 7 tiles + 1 extra tile + 0.5 tile for odd layer offset
      const fixedTileSize = 48;
      const fixedGridSize = 7;
      const fixedBoardWidth = (fixedGridSize) * fixedTileSize + fixedTileSize + fixedTileSize * 0.5;
      const fixedBoardHeight = fixedBoardWidth;

      if (previewContainerRef.current) {
        const containerWidth = previewContainerRef.current.clientWidth;
        const containerHeight = previewContainerRef.current.clientHeight;
        const scaleX = containerWidth / fixedBoardWidth;
        const scaleY = containerHeight / fixedBoardHeight;
        const scale = Math.min(scaleX, scaleY) * 0.95; // Fit container with slight padding
        setPreviewScale(scale);
      } else {
        setPreviewScale(1.0);
      }
      setPreviewTiles(gameTiles);
    } catch (err) {
      console.error('Failed to generate preview tiles:', err);
      setPreviewTiles([]);
    }
  }, [selectedLevel]);

  const loadLevels = async () => {
    setIsLoading(true);
    try {
      const options = filter !== 'all' ? { status: filter, limit: 200 } : { limit: 200 };
      const loadedLevels = await getProductionLevelsByBatch(batchId, options);
      setLevels(loadedLevels);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // Auto test single level
  const handleAutoTestSingle = async () => {
    if (!selectedLevel) return;
    setIsAutoTesting(true);
    setAutoTestResult(null);

    try {
      const result = await analyzeAutoPlay(selectedLevel.level_json, {
        iterations: autoTestIterations,
        targetDifficulty: selectedLevel.meta.target_difficulty,
      });

      setAutoTestResult({
        match_score: calculateMatchScoreFromBots(result.bot_stats),
        autoplay_grade: result.autoplay_grade,
        balance_status: result.balance_status,
        bot_stats: result.bot_stats.map(s => ({
          profile: s.profile,
          clear_rate: s.clear_rate,
          target_clear_rate: s.target_clear_rate,
        })),
        recommendations: result.recommendations,
      });

      // Update level meta with bot test result
      const botClearRates = {
        novice: result.bot_stats.find(s => s.profile === 'novice')?.clear_rate || 0,
        casual: result.bot_stats.find(s => s.profile === 'casual')?.clear_rate || 0,
        average: result.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
        expert: result.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
        optimal: result.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
      };

      // Save to production storage
      const updatedMeta = {
        ...selectedLevel.meta,
        bot_clear_rates: botClearRates,
        match_score: calculateMatchScoreFromBots(result.bot_stats),
      };

      await saveProductionLevels(batchId, [{
        meta: updatedMeta,
        level_json: selectedLevel.level_json,
      }]);

      addNotification('success', `레벨 ${selectedLevel.meta.level_number} 자동 테스트 완료 (일치도: ${calculateMatchScoreFromBots(result.bot_stats).toFixed(0)}%)`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Auto test failed:', err);
      addNotification('error', '자동 테스트 실패: ' + (err instanceof Error ? err.message : '알 수 없는 오류'));
    } finally {
      setIsAutoTesting(false);
    }
  };

  // Calculate match score from bot stats
  const calculateMatchScoreFromBots = (botStats: { clear_rate: number; target_clear_rate: number }[]) => {
    if (!botStats.length) return 0;
    const gaps = botStats.map(s => Math.abs((s.clear_rate - s.target_clear_rate) * 100));
    const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const maxGap = Math.max(...gaps);
    // Improved formula: reduced maxGap weight (0.25 vs 0.4) and gentler penalty (1.5x vs 2x)
    const weightedGap = (avgGap * 0.75 + maxGap * 0.25);
    return Math.max(0, 100 - weightedGap * 1.5);
  };

  // Batch auto test
  const handleBatchAutoTest = async () => {
    batchAbortRef.current = new AbortController();
    const signal = batchAbortRef.current.signal;

    // Filter levels based on selected filter
    let filteredLevels = [...levels];

    switch (batchTestFilter) {
      case 'untested':
        filteredLevels = filteredLevels.filter(l => !l.meta.match_score && !l.meta.bot_clear_rates);
        break;
      case 'boss':
        filteredLevels = filteredLevels.filter(l => l.meta.level_number % 10 === 0);
        break;
      case 'tutorial':
        const tutorialLevels = [11, 21, 36, 51, 66, 81, 96, 111, 126, 141, 156];
        filteredLevels = filteredLevels.filter(l => tutorialLevels.includes(l.meta.level_number));
        break;
      case 'low_match':
        filteredLevels = filteredLevels.filter(l => (l.meta.match_score || 0) < 70);
        break;
      case 'range':
        filteredLevels = filteredLevels.filter(l =>
          l.meta.level_number >= batchTestRange.min &&
          l.meta.level_number <= batchTestRange.max
        );
        break;
    }

    // Apply max levels limit
    if (filteredLevels.length > batchTestMaxLevels) {
      filteredLevels = filteredLevels.slice(0, batchTestMaxLevels);
    }

    if (filteredLevels.length === 0) {
      addNotification('warning', '테스트할 레벨이 없습니다.');
      return;
    }

    setBatchTestProgress({
      status: 'running',
      total: filteredLevels.length,
      completed: 0,
      currentLevel: 0,
      results: [],
      failedLevels: [],
    });

    const results: { level_number: number; match_score: number; grade: string; status: string; target_difficulty: number; autoplay_score: number; static_score: number }[] = [];
    const failedLevels: number[] = [];

    for (let i = 0; i < filteredLevels.length; i++) {
      if (signal.aborted) {
        setBatchTestProgress(prev => ({ ...prev, status: 'paused' }));
        break;
      }

      const level = filteredLevels[i];
      setBatchTestProgress(prev => ({
        ...prev,
        currentLevel: level.meta.level_number,
        completed: i,
      }));

      try {
        const result = await analyzeAutoPlay(level.level_json, {
          iterations: autoTestIterations,
          targetDifficulty: level.meta.target_difficulty,
        });

        const matchScore = calculateMatchScoreFromBots(result.bot_stats);

        results.push({
          level_number: level.meta.level_number,
          match_score: matchScore,
          grade: result.autoplay_grade,
          status: result.balance_status,
          target_difficulty: level.meta.target_difficulty,
          autoplay_score: result.autoplay_score,
          static_score: result.static_score,
        });

        // Save result to level meta
        const botClearRates = {
          novice: result.bot_stats.find(s => s.profile === 'novice')?.clear_rate || 0,
          casual: result.bot_stats.find(s => s.profile === 'casual')?.clear_rate || 0,
          average: result.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
          expert: result.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
          optimal: result.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
        };

        await saveProductionLevels(batchId, [{
          meta: {
            ...level.meta,
            bot_clear_rates: botClearRates,
            match_score: matchScore,
          },
          level_json: level.level_json,
        }]);

        setBatchTestProgress(prev => ({
          ...prev,
          completed: i + 1,
          results: [...prev.results, results[results.length - 1]],
        }));
      } catch (err) {
        console.error(`Auto test failed for level ${level.meta.level_number}:`, err);
        failedLevels.push(level.meta.level_number);
        setBatchTestProgress(prev => ({
          ...prev,
          failedLevels: [...prev.failedLevels, level.meta.level_number],
        }));
      }
    }

    if (!signal.aborted) {
      setBatchTestProgress(prev => ({ ...prev, status: 'completed' }));
      addNotification('success', `일괄 자동 테스트 완료: ${results.length}개 성공, ${failedLevels.length}개 실패`);
      loadLevels();
      onStatsUpdate();
    }
  };

  const handleStopBatchTest = () => {
    batchAbortRef.current?.abort();
    addNotification('info', '일괄 테스트 중지됨');
  };

  // Regeneration state
  const [regeneratingLevels, setRegeneratingLevels] = useState<Set<number>>(new Set());
  const [isBatchRegenerating, setIsBatchRegenerating] = useState(false);
  const [regenerationThreshold, setRegenerationThreshold] = useState(70);

  // Regenerate single level - follows same rules as Production generation
  const handleRegenerateLevel = async (levelNumber: number) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level) return;

    setRegeneratingLevels(prev => new Set([...prev, levelNumber]));

    try {
      // Get current batch for gimmick unlock levels and difficulty settings
      const currentBatch = await getProductionBatch(batchId);
      if (!currentBatch) {
        throw new Error('Batch not found');
      }

      const targetDifficulty = level.meta.target_difficulty;

      // === FOLLOW PRODUCTION GENERATION RULES ===
      // Randomize pattern type for visual diversity (same as Production)
      const patternTypes: Array<'aesthetic' | 'geometric' | 'clustered'> = ['aesthetic', 'geometric', 'clustered'];
      const patternType = patternTypes[Math.floor(Math.random() * patternTypes.length)];

      // Randomize symmetry mode (same as Production)
      const symmetryModes: Array<'none' | 'horizontal' | 'vertical'> = ['none', 'horizontal', 'vertical'];
      const symmetryMode = symmetryModes[Math.floor(Math.random() * symmetryModes.length)];

      // Randomize goal direction (same as Production)
      const goalDirections: Array<'s' | 'n' | 'e' | 'w'> = ['s', 'n', 'e', 'w'];
      const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];

      // Randomize goal type (same as Production)
      const goalTypes: Array<'craft' | 'stack'> = ['craft', 'stack'];
      const goalType = goalTypes[Math.floor(Math.random() * goalTypes.length)];

      // Calculate tile_types based on difficulty (same as Production)
      const tileTypeCount = 3 + Math.floor(targetDifficulty * 3);
      const tileTypes = ['t1', 't2', 't3', 't4', 't5', 't6'].slice(0, tileTypeCount);

      // Calculate max_layers based on difficulty (same as Production)
      const maxLayers = Math.min(7, 3 + Math.floor(targetDifficulty * 4));

      // Calculate gimmick_intensity based on level number (same as Production)
      const gimmickIntensity = Math.min(1, levelNumber / 500);

      // Generate new level with Production rules
      const validatedResult = await generateValidatedLevel(
        {
          target_difficulty: targetDifficulty,
          grid_size: [7, 7],
          max_layers: maxLayers,
          tile_types: tileTypes,
          obstacle_types: [],
          goals: [{
            type: goalType,
            direction: goalDirection,
            count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
          }],
          symmetry_mode: symmetryMode,
          pattern_type: patternType,
          gimmick_intensity: gimmickIntensity,  // Include in params (API signature)
        },
        {
          max_retries: 5,
          tolerance: 15.0,
          simulation_iterations: 50,
          use_best_match: true,
        },
        {
          auto_select_gimmicks: true,
          available_gimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
          gimmick_unlock_levels: currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
          level_number: levelNumber,
        }
      );

      // Use the validation results directly
      const matchScore = validatedResult.match_score;
      const botClearRates = validatedResult.bot_clear_rates as {
        novice: number;
        casual: number;
        average: number;
        expert: number;
        optimal: number;
      };

      // Get autoplay analysis for additional metrics
      const autoplayResult = await analyzeAutoPlay(validatedResult.level_json, {
        iterations: 100,
        targetDifficulty: level.meta.target_difficulty,
      });

      // Save regenerated level
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          actual_difficulty: validatedResult.actual_difficulty,
          grade: validatedResult.grade as any,
          bot_clear_rates: botClearRates,
          match_score: matchScore,
          status_updated_at: new Date().toISOString(),
        },
        level_json: validatedResult.level_json,
      }]);

      // Update batch test results if exists
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.map(r =>
          r.level_number === levelNumber
            ? {
                ...r,
                match_score: matchScore,
                grade: autoplayResult.autoplay_grade,
                status: autoplayResult.balance_status,
                autoplay_score: autoplayResult.autoplay_score,
                static_score: autoplayResult.static_score,
              }
            : r
        ),
      }));

      addNotification('success', `레벨 ${levelNumber} 재생성 완료 (일치도: ${matchScore.toFixed(0)}%)`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Regeneration failed:', err);
      addNotification('error', `레벨 ${levelNumber} 재생성 실패`);
    } finally {
      setRegeneratingLevels(prev => {
        const newSet = new Set(prev);
        newSet.delete(levelNumber);
        return newSet;
      });
    }
  };

  // Batch regenerate low match score levels
  const handleBatchRegenerate = async () => {
    const lowMatchLevels = batchTestProgress.results.filter(r => r.match_score < regenerationThreshold);
    if (lowMatchLevels.length === 0) {
      addNotification('info', `일치도 ${regenerationThreshold}% 미만 레벨이 없습니다.`);
      return;
    }

    setIsBatchRegenerating(true);
    let successCount = 0;
    let failCount = 0;

    for (const result of lowMatchLevels) {
      try {
        await handleRegenerateLevel(result.level_number);
        successCount++;
      } catch {
        failCount++;
      }
    }

    setIsBatchRegenerating(false);
    addNotification('success', `일괄 재생성 완료: ${successCount}개 성공, ${failCount}개 실패`);
  };

  // Filtered levels based on search
  const filteredLevels = useMemo(() => {
    if (!searchQuery) return levels;
    const query = searchQuery.toLowerCase();
    return levels.filter(l =>
      l.meta.level_number.toString().includes(query) ||
      l.meta.grade.toLowerCase().includes(query)
    );
  }, [levels, searchQuery]);

  const handleSelectLevel = (level: ProductionLevel) => {
    setSelectedLevel(level);
  };

  const handlePlayLevel = () => {
    if (!selectedLevel) return;
    setIsPlaying(true);
    setShowResultForm(false);
    setGameResult(null);
  };

  const handleGameEnd = (won: boolean, stats: GameStats) => {
    setGameResult({ won, stats });
    setShowResultForm(true);
    setIsPlaying(false);

    // Pre-fill perceived difficulty based on game result
    if (!won) {
      setPerceivedDifficulty(5);
    } else if (stats.moves > 50) {
      setPerceivedDifficulty(4);
    } else if (stats.moves > 30) {
      setPerceivedDifficulty(3);
    } else if (stats.moves > 15) {
      setPerceivedDifficulty(2);
    } else {
      setPerceivedDifficulty(1);
    }
  };

  const handleBack = () => {
    setIsPlaying(false);
  };

  const handleSubmitResult = async () => {
    if (!selectedLevel || !gameResult) return;

    const result: PlaytestResult = {
      tester_id: 'production_tester',
      tester_name: '프로덕션 테스터',
      tested_at: new Date().toISOString(),
      cleared: gameResult.won,
      attempts: 1,
      time_seconds: gameResult.stats.timeElapsed,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues,
    };

    try {
      await addPlaytestResult(batchId, selectedLevel.meta.level_number, result);
      addNotification('success', `레벨 ${selectedLevel.meta.level_number} 테스트 결과 저장됨`);

      // Reset form
      setShowResultForm(false);
      setGameResult(null);
      setPerceivedDifficulty(3);
      setFunRating(3);
      setComments('');
      setIssues([]);

      // Reload levels and update stats
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '결과 저장 실패');
    }
  };

  const handleSkipResult = () => {
    setShowResultForm(false);
    setGameResult(null);
    setPerceivedDifficulty(3);
    setFunRating(3);
    setComments('');
    setIssues([]);
  };

  // Level info for game player
  const levelInfo: LevelInfo | undefined = selectedLevel
    ? {
        id: `production_${selectedLevel.meta.level_number}`,
        name: `레벨 ${selectedLevel.meta.level_number}`,
        source: 'local' as const,
        difficulty: selectedLevel.meta.actual_difficulty,
        totalTiles: 0,
        layers: 0,
      }
    : undefined;

  // Playing view
  if (isPlaying && selectedLevel) {
    return (
      <div className="h-[calc(100vh-200px)] min-h-[700px] relative">
        <GamePlayer
          levelData={selectedLevel.level_json as unknown as Record<string, unknown>}
          levelInfo={levelInfo}
          onGameEnd={handleGameEnd}
          onBack={handleBack}
        />
      </div>
    );
  }

  // Result form view
  if (showResultForm && selectedLevel && gameResult) {
    return (
      <div className="p-4 space-y-4">
        <div className="p-4 bg-gray-800 rounded-lg">
          <h3 className="text-lg font-medium text-white mb-4">
            레벨 {selectedLevel.meta.level_number} 테스트 결과
          </h3>

          {/* Game result summary */}
          <div className={`p-4 rounded-lg mb-4 ${gameResult.won ? 'bg-green-900/30' : 'bg-red-900/30'}`}>
            <div className="flex items-center justify-between">
              <span className={`text-lg font-bold ${gameResult.won ? 'text-green-400' : 'text-red-400'}`}>
                {gameResult.won ? '클리어 성공!' : '클리어 실패'}
              </span>
              <div className="text-sm text-gray-300">
                <span className="mr-4">시간: {Math.floor(gameResult.stats.timeElapsed / 60)}분 {gameResult.stats.timeElapsed % 60}초</span>
                <span className="mr-4">이동: {gameResult.stats.moves}회</span>
                <span>점수: {gameResult.stats.score}</span>
              </div>
            </div>
          </div>

          {/* Rating form */}
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">체감 난이도</label>
              <select
                value={perceivedDifficulty}
                onChange={(e) => setPerceivedDifficulty(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 매우 쉬움</option>
                <option value={2}>2 - 쉬움</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 어려움</option>
                <option value={5}>5 - 매우 어려움</option>
              </select>
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">재미 점수</label>
              <select
                value={funRating}
                onChange={(e) => setFunRating(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 지루함</option>
                <option value={2}>2 - 별로</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 재미있음</option>
                <option value={5}>5 - 매우 재미있음</option>
              </select>
            </div>
          </div>

          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-1">코멘트</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="레벨에 대한 의견을 작성하세요..."
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
              rows={3}
            />
          </div>

          <div className="mb-4">
            <label className="block text-sm text-gray-400 mb-1">발견된 문제점</label>
            <div className="flex flex-wrap gap-2 mb-2">
              {['불공정', '너무 쉬움', '너무 어려움', '막힘', '버그', '밸런스'].map((issue) => (
                <button
                  key={issue}
                  onClick={() => {
                    if (issues.includes(issue)) {
                      setIssues(issues.filter(i => i !== issue));
                    } else {
                      setIssues([...issues, issue]);
                    }
                  }}
                  className={`px-2 py-1 text-xs rounded ${
                    issues.includes(issue)
                      ? 'bg-red-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {issue}
                </button>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <Button onClick={handleSubmitResult} className="flex-1">
              결과 저장
            </Button>
            <Button onClick={handleSkipResult} variant="secondary">
              건너뛰기
            </Button>
            <Button onClick={handlePlayLevel} variant="secondary">
              다시 플레이
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Level selection view
  return (
    <div className="flex flex-col gap-4 h-[calc(100vh-250px)] min-h-[600px]">
      {/* Test Mode Tabs */}
      <div className="flex gap-2 bg-gray-800 p-2 rounded-lg">
        <button
          onClick={() => setTestMode('manual')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'manual'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🎮 수동 플레이
        </button>
        <button
          onClick={() => setTestMode('auto_single')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'auto_single'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🤖 자동 (개별)
        </button>
        <button
          onClick={() => setTestMode('auto_batch')}
          className={`flex-1 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            testMode === 'auto_batch'
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          🚀 자동 (일괄)
        </button>
      </div>

      {/* Batch Auto Test Panel */}
      {testMode === 'auto_batch' && (
        <div className="bg-gray-800 rounded-lg p-4 space-y-4">
          <h3 className="text-sm font-medium text-white">일괄 자동 테스트 설정</h3>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">필터</label>
              <select
                value={batchTestFilter}
                onChange={(e) => setBatchTestFilter(e.target.value as typeof batchTestFilter)}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              >
                <option value="all">전체 레벨</option>
                <option value="untested">미테스트 레벨</option>
                <option value="boss">보스 레벨 (10배수)</option>
                <option value="tutorial">튜토리얼 레벨</option>
                <option value="low_match">낮은 일치도 (&lt;70%)</option>
                <option value="range">레벨 범위</option>
              </select>
            </div>

            {batchTestFilter === 'range' && (
              <>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">시작 레벨</label>
                  <input
                    type="number"
                    value={batchTestRange.min}
                    onChange={(e) => setBatchTestRange(prev => ({ ...prev, min: Number(e.target.value) }))}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    disabled={batchTestProgress.status === 'running'}
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-400 mb-1">종료 레벨</label>
                  <input
                    type="number"
                    value={batchTestRange.max}
                    onChange={(e) => setBatchTestRange(prev => ({ ...prev, max: Number(e.target.value) }))}
                    className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                    disabled={batchTestProgress.status === 'running'}
                  />
                </div>
              </>
            )}

            <div>
              <label className="block text-xs text-gray-400 mb-1">최대 레벨 수</label>
              <input
                type="number"
                value={batchTestMaxLevels}
                onChange={(e) => setBatchTestMaxLevels(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 mb-1">반복 횟수</label>
              <select
                value={autoTestIterations}
                onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              >
                <option value={50}>50회 (빠름)</option>
                <option value={100}>100회 (기본)</option>
                <option value={200}>200회 (정밀)</option>
              </select>
            </div>
          </div>

          {/* Batch Test Progress */}
          {batchTestProgress.status !== 'idle' && (
            <div className="space-y-2">
              <div className="flex justify-between text-xs text-gray-400">
                <span>진행: {batchTestProgress.completed}/{batchTestProgress.total}</span>
                <span>현재: 레벨 {batchTestProgress.currentLevel}</span>
              </div>
              <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    batchTestProgress.status === 'completed' ? 'bg-green-500' :
                    batchTestProgress.status === 'error' ? 'bg-red-500' : 'bg-indigo-500'
                  }`}
                  style={{ width: `${batchTestProgress.total > 0 ? (batchTestProgress.completed / batchTestProgress.total) * 100 : 0}%` }}
                />
              </div>
              {batchTestProgress.failedLevels.length > 0 && (
                <div className="text-xs text-red-400">
                  실패: {batchTestProgress.failedLevels.join(', ')}
                </div>
              )}
            </div>
          )}

          {/* Batch Test Results Summary - Enhanced */}
          {batchTestProgress.status === 'completed' && batchTestProgress.results.length > 0 && (() => {
            const results = batchTestProgress.results;
            const passCount = results.filter(r => r.match_score >= 70).length;
            const warnCount = results.filter(r => r.match_score >= 50 && r.match_score < 70).length;
            const failCount = results.filter(r => r.match_score < 50).length;
            const avgScore = results.reduce((sum, r) => sum + r.match_score, 0) / results.length;
            const minScore = Math.min(...results.map(r => r.match_score));
            const maxScore = Math.max(...results.map(r => r.match_score));
            const minLevel = results.find(r => r.match_score === minScore);
            const maxLevel = results.find(r => r.match_score === maxScore);

            // Grade distribution
            const gradeCount: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
            results.forEach(r => { gradeCount[r.grade] = (gradeCount[r.grade] || 0) + 1; });

            // Balance distribution
            const balanceCount: Record<string, number> = {};
            results.forEach(r => { balanceCount[r.status] = (balanceCount[r.status] || 0) + 1; });

            return (
              <div className="space-y-3">
                {/* Overall Summary */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-3">📊 전체 결과 요약</h4>

                  {/* Pass/Warn/Fail Bar */}
                  <div className="mb-3">
                    <div className="flex h-4 rounded-full overflow-hidden bg-gray-600">
                      {passCount > 0 && (
                        <div
                          className="bg-green-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(passCount / results.length) * 100}%` }}
                        >
                          {passCount > 2 && `${passCount}`}
                        </div>
                      )}
                      {warnCount > 0 && (
                        <div
                          className="bg-yellow-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(warnCount / results.length) * 100}%` }}
                        >
                          {warnCount > 2 && `${warnCount}`}
                        </div>
                      )}
                      {failCount > 0 && (
                        <div
                          className="bg-red-500 flex items-center justify-center text-[10px] text-white font-medium"
                          style={{ width: `${(failCount / results.length) * 100}%` }}
                        >
                          {failCount > 2 && `${failCount}`}
                        </div>
                      )}
                    </div>
                    <div className="flex justify-between mt-1 text-[10px] text-gray-400">
                      <span>✅ 통과 {passCount}개 ({((passCount / results.length) * 100).toFixed(0)}%)</span>
                      <span>⚠️ 보통 {warnCount}개 ({((warnCount / results.length) * 100).toFixed(0)}%)</span>
                      <span>❌ 미달 {failCount}개 ({((failCount / results.length) * 100).toFixed(0)}%)</span>
                    </div>
                  </div>

                  {/* Score Statistics */}
                  <div className="grid grid-cols-4 gap-2 text-sm mb-3">
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-white">{avgScore.toFixed(1)}%</div>
                      <div className="text-[10px] text-gray-500">평균 일치도</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-green-400">{maxScore.toFixed(0)}%</div>
                      <div className="text-[10px] text-gray-500">최고 (Lv.{maxLevel?.level_number})</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-red-400">{minScore.toFixed(0)}%</div>
                      <div className="text-[10px] text-gray-500">최저 (Lv.{minLevel?.level_number})</div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-lg font-bold text-blue-400">{results.length}</div>
                      <div className="text-[10px] text-gray-500">테스트 완료</div>
                    </div>
                  </div>

                  {/* Grade Distribution */}
                  <div className="mb-3">
                    <div className="text-[10px] text-gray-400 mb-1">등급 분포</div>
                    <div className="flex gap-1">
                      {(['S', 'A', 'B', 'C', 'D'] as const).map(grade => (
                        <div key={grade} className="flex-1 text-center">
                          <div className={`text-xs font-bold ${
                            grade === 'S' ? 'text-green-400' :
                            grade === 'A' ? 'text-blue-400' :
                            grade === 'B' ? 'text-yellow-400' :
                            grade === 'C' ? 'text-orange-400' : 'text-red-400'
                          }`}>
                            {gradeCount[grade] || 0}
                          </div>
                          <div className="text-[10px] text-gray-500">{grade}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Balance Distribution */}
                  <div>
                    <div className="text-[10px] text-gray-400 mb-1">밸런스 상태</div>
                    <div className="flex flex-wrap gap-1">
                      {balanceCount.balanced && (
                        <span className="px-2 py-0.5 bg-green-900/50 text-green-400 text-[10px] rounded">
                          ✅ 균형 {balanceCount.balanced}
                        </span>
                      )}
                      {balanceCount.too_easy && (
                        <span className="px-2 py-0.5 bg-yellow-900/50 text-yellow-400 text-[10px] rounded">
                          📉 너무쉬움 {balanceCount.too_easy}
                        </span>
                      )}
                      {balanceCount.too_hard && (
                        <span className="px-2 py-0.5 bg-orange-900/50 text-orange-400 text-[10px] rounded">
                          📈 너무어려움 {balanceCount.too_hard}
                        </span>
                      )}
                      {balanceCount.unbalanced && (
                        <span className="px-2 py-0.5 bg-red-900/50 text-red-400 text-[10px] rounded">
                          ⚠️ 불균형 {balanceCount.unbalanced}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Difficulty Comparison */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-2">🎯 난이도 비교 (목표 vs 실제)</h4>
                  <div className="grid grid-cols-3 gap-2 text-sm mb-2">
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 목표 난이도</div>
                      <div className="text-white font-bold">
                        {(results.reduce((sum, r) => sum + r.target_difficulty, 0) / results.length * 100).toFixed(0)}%
                      </div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 자동플레이 점수</div>
                      <div className="text-indigo-400 font-bold">
                        {(results.reduce((sum, r) => sum + r.autoplay_score, 0) / results.length).toFixed(0)}점
                      </div>
                    </div>
                    <div className="text-center p-2 bg-gray-800 rounded">
                      <div className="text-[10px] text-gray-500 mb-1">평균 정적분석 점수</div>
                      <div className="text-purple-400 font-bold">
                        {(results.reduce((sum, r) => sum + r.static_score, 0) / results.length).toFixed(0)}점
                      </div>
                    </div>
                  </div>
                  <div className="text-[10px] text-gray-500 text-center">
                    자동플레이 - 정적분석 평균 차이: {' '}
                    <span className={(() => {
                      const diff = (results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length);
                      return diff > 10 ? 'text-orange-400' : diff < -10 ? 'text-yellow-400' : 'text-green-400';
                    })()}>
                      {((results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length) >= 0 ? '+' : '')}
                      {(results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length).toFixed(1)}점
                    </span>
                    {' '}
                    ({(() => {
                      const diff = (results.reduce((sum, r) => sum + (r.autoplay_score - r.static_score), 0) / results.length);
                      return diff > 10 ? '실제 더 어려움' : diff < -10 ? '실제 더 쉬움' : '일치';
                    })()})
                  </div>
                </div>

                {/* Batch Regeneration Controls */}
                {results.filter(r => r.match_score < 70).length > 0 && (
                  <div className="p-3 bg-orange-900/30 rounded-lg border border-orange-700/50">
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs text-orange-400 font-medium">🔄 낮은 일치도 레벨 재생성</h4>
                      <span className="text-xs text-orange-300">
                        {results.filter(r => r.match_score < regenerationThreshold).length}개 대상
                      </span>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="text-xs text-gray-400">기준:</label>
                      <select
                        value={regenerationThreshold}
                        onChange={(e) => setRegenerationThreshold(Number(e.target.value))}
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs"
                        disabled={isBatchRegenerating}
                      >
                        <option value={50}>50% 미만</option>
                        <option value={60}>60% 미만</option>
                        <option value={70}>70% 미만</option>
                        <option value={80}>80% 미만</option>
                      </select>
                      <Button
                        onClick={handleBatchRegenerate}
                        disabled={isBatchRegenerating || results.filter(r => r.match_score < regenerationThreshold).length === 0}
                        variant="danger"
                        size="sm"
                        className="flex-1"
                      >
                        {isBatchRegenerating ? (
                          <>
                            <span className="animate-spin mr-1">⟳</span>
                            재생성 중...
                          </>
                        ) : (
                          <>
                            🔄 {results.filter(r => r.match_score < regenerationThreshold).length}개 일괄 재생성
                          </>
                        )}
                      </Button>
                    </div>
                  </div>
                )}

                {/* Individual Results List - Enhanced */}
                <div className="p-3 bg-gray-700/50 rounded-lg">
                  <h4 className="text-xs text-gray-400 mb-2">📋 개별 레벨 결과 (일치도 낮은 순)</h4>
                  {/* Header */}
                  <div className="flex items-center text-[10px] text-gray-500 px-2 py-1 border-b border-gray-600 mb-1">
                    <span className="w-14">레벨</span>
                    <span className="w-12 text-center">등급</span>
                    <span className="w-14 text-center">일치도</span>
                    <span className="w-16 text-center">목표</span>
                    <span className="w-20 text-center">자동/정적</span>
                    <span className="w-10 text-center">상태</span>
                    <span className="w-16 text-center">액션</span>
                  </div>
                  <div className="max-h-[250px] overflow-y-auto space-y-1">
                    {[...results].sort((a, b) => a.match_score - b.match_score).map(r => {
                      const scoreDiff = r.autoplay_score - r.static_score;
                      const isRegenerating = regeneratingLevels.has(r.level_number);
                      return (
                        <div
                          key={r.level_number}
                          className={`flex items-center px-2 py-1.5 rounded text-xs ${
                            r.match_score >= 70 ? 'bg-green-900/20 hover:bg-green-900/40' :
                            r.match_score >= 50 ? 'bg-yellow-900/20 hover:bg-yellow-900/40' : 'bg-red-900/20 hover:bg-red-900/40'
                          } transition-colors`}
                        >
                          <span className="w-14 text-gray-300 font-medium">Lv.{r.level_number}</span>
                          <span className={`w-12 text-center font-bold ${
                            r.grade === 'S' ? 'text-green-400' :
                            r.grade === 'A' ? 'text-blue-400' :
                            r.grade === 'B' ? 'text-yellow-400' :
                            r.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                          }`}>{r.grade}</span>
                          <span className={`w-14 text-center font-bold ${
                            r.match_score >= 70 ? 'text-green-400' :
                            r.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {r.match_score.toFixed(0)}%
                          </span>
                          <span className="w-16 text-center text-gray-400">
                            {(r.target_difficulty * 100).toFixed(0)}%
                          </span>
                          <span className="w-20 text-center">
                            <span className="text-indigo-400">{r.autoplay_score.toFixed(0)}</span>
                            <span className="text-gray-500">/</span>
                            <span className="text-purple-400">{r.static_score.toFixed(0)}</span>
                            <span className={`ml-0.5 text-[9px] ${
                              Math.abs(scoreDiff) <= 10 ? 'text-green-400' :
                              scoreDiff > 10 ? 'text-orange-400' : 'text-yellow-400'
                            }`}>
                              ({scoreDiff >= 0 ? '+' : ''}{scoreDiff.toFixed(0)})
                            </span>
                          </span>
                          <span className="w-10 text-center">
                            {r.status === 'balanced' ? '✅' :
                             r.status === 'too_easy' ? '📉' :
                             r.status === 'too_hard' ? '📈' : '⚠️'}
                          </span>
                          <span className="w-16 text-center">
                            <button
                              onClick={() => handleRegenerateLevel(r.level_number)}
                              disabled={isRegenerating || isBatchRegenerating}
                              className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                                isRegenerating
                                  ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                                  : r.match_score < 70
                                    ? 'bg-orange-600 hover:bg-orange-500 text-white'
                                    : 'bg-gray-600 hover:bg-gray-500 text-gray-300'
                              }`}
                            >
                              {isRegenerating ? '⟳' : '🔄 재생성'}
                            </button>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="mt-2 pt-2 border-t border-gray-600 text-[10px] text-gray-500 flex justify-between">
                    <span>🟣 자동플레이 = 봇 시뮬레이션</span>
                    <span>🟣 정적분석 = 레벨 구조</span>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Batch Test Actions */}
          <div className="flex gap-2">
            {batchTestProgress.status === 'running' ? (
              <Button onClick={handleStopBatchTest} variant="danger" className="flex-1">
                ⏹️ 테스트 중지
              </Button>
            ) : (
              <Button onClick={handleBatchAutoTest} className="flex-1" disabled={levels.length === 0}>
                🚀 일괄 테스트 시작
              </Button>
            )}
            {batchTestProgress.status === 'completed' && (
              <Button
                onClick={() => setBatchTestProgress({ status: 'idle', total: 0, completed: 0, currentLevel: 0, results: [], failedLevels: [] })}
                variant="secondary"
              >
                초기화
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex gap-4 flex-1 min-h-0">
      {/* Level list */}
      <div className="w-80 flex flex-col bg-gray-800 rounded-lg overflow-hidden">
        {/* Filters */}
        <div className="p-3 border-b border-gray-700 space-y-2">
          <input
            type="text"
            placeholder="레벨 번호 검색..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full px-3 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
          />
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as LevelStatus | 'all')}
            className="w-full px-3 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
          >
            <option value="all">전체 레벨</option>
            <option value="generated">생성됨</option>
            <option value="playtest_queue">테스트 대기</option>
            <option value="approved">승인됨</option>
            <option value="needs_rework">수정필요</option>
          </select>
        </div>

        {/* Level list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-32 text-gray-400">
              로딩 중...
            </div>
          ) : filteredLevels.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-gray-400">
              레벨이 없습니다
            </div>
          ) : (
            <div className="divide-y divide-gray-700">
              {filteredLevels.map((level) => (
                <div
                  key={level.meta.level_number}
                  onClick={() => handleSelectLevel(level)}
                  className={`p-3 cursor-pointer transition-colors ${
                    selectedLevel?.meta.level_number === level.meta.level_number
                      ? 'bg-indigo-900/50'
                      : 'hover:bg-gray-700/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-white">
                        레벨 {level.meta.level_number}
                      </div>
                      <div className="text-xs text-gray-400">
                        난이도: {level.meta.actual_difficulty.toFixed(3)} ({(level.meta.actual_difficulty * 100).toFixed(0)}%)
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {/* Match score indicator */}
                      {level.meta.match_score !== undefined && (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          level.meta.match_score >= 70 ? 'bg-green-900/50 text-green-400' :
                          level.meta.match_score >= 50 ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'
                        }`}>
                          {level.meta.match_score.toFixed(0)}%
                        </span>
                      )}
                      <span className={`text-sm font-bold ${getGradeColor(level.meta.grade)}`}>
                        {level.meta.grade}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                        {getStatusLabel(level.meta.status)}
                      </span>
                    </div>
                  </div>
                  {/* Gimmicks indicator */}
                  {(() => {
                    const gimmicks = extractGimmicksFromLevel(level.level_json);
                    if (gimmicks.length === 0) return null;
                    return (
                      <div className="mt-1 flex gap-1">
                        {gimmicks.slice(0, 3).map(gimmick => (
                          <span
                            key={gimmick}
                            className={`px-1.5 py-0.5 rounded text-[10px] text-white ${GIMMICK_COLORS[gimmick] || 'bg-gray-600'}`}
                          >
                            {GIMMICK_NAMES[gimmick] || gimmick}
                          </span>
                        ))}
                        {gimmicks.length > 3 && (
                          <span className="text-[10px] text-gray-500">+{gimmicks.length - 3}</span>
                        )}
                      </div>
                    );
                  })()}
                  {level.meta.playtest_results && level.meta.playtest_results.length > 0 && (
                    <div className="mt-1 text-xs text-gray-500">
                      테스트 {level.meta.playtest_results.length}회
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="p-3 border-t border-gray-700 text-xs text-gray-400">
          {filteredLevels.length}개 레벨
        </div>
      </div>

      {/* Level preview & play */}
      <div className="flex-1 flex flex-col bg-gray-800 rounded-lg">
        {selectedLevel ? (
          <>
            {/* Level info */}
            <div className="p-4 border-b border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-medium text-white">
                    레벨 {selectedLevel.meta.level_number}
                  </h3>
                  <button
                    onClick={() => setShowLevelJson(!showLevelJson)}
                    className={`px-2 py-0.5 text-xs rounded ${showLevelJson ? 'bg-indigo-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
                  >
                    JSON
                  </button>
                </div>
                <span className={`text-xl font-bold ${getGradeColor(selectedLevel.meta.grade)}`}>
                  {selectedLevel.meta.grade}
                </span>
              </div>

              <div className="grid grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-400">목표 난이도:</span>
                  <span className="text-white ml-2">{selectedLevel.meta.target_difficulty.toFixed(3)} ({(selectedLevel.meta.target_difficulty * 100).toFixed(0)}%)</span>
                </div>
                <div>
                  <span className="text-gray-400">실제 난이도:</span>
                  <span className="text-white ml-2">{selectedLevel.meta.actual_difficulty.toFixed(3)} ({(selectedLevel.meta.actual_difficulty * 100).toFixed(0)}%)</span>
                </div>
                <div>
                  <span className="text-gray-400">타일:</span>
                  <span className="text-white ml-2">{previewTiles.filter(t => !t.type.startsWith('craft_') && !t.type.startsWith('stack_')).length}개</span>
                  <span className="text-gray-500 ml-1">({previewTiles.filter(t => t.isSelectable && !t.type.startsWith('craft_') && !t.type.startsWith('stack_')).length} 선택가능)</span>
                </div>
                <div>
                  <span className="text-gray-400">상태:</span>
                  <span className={`ml-2 px-2 py-0.5 rounded text-xs ${getStatusColor(selectedLevel.meta.status)}`}>
                    {getStatusLabel(selectedLevel.meta.status)}
                  </span>
                </div>
              </div>

              {/* Gimmicks used in level */}
              {(() => {
                const gimmicks = extractGimmicksFromLevel(selectedLevel.level_json);
                if (gimmicks.length === 0) return null;
                return (
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-sm text-gray-400">기믹:</span>
                    <div className="flex flex-wrap gap-1">
                      {gimmicks.map(gimmick => (
                        <span
                          key={gimmick}
                          className={`px-2 py-0.5 rounded text-xs text-white ${GIMMICK_COLORS[gimmick] || 'bg-gray-600'}`}
                        >
                          {GIMMICK_NAMES[gimmick] || gimmick}
                        </span>
                      ))}
                    </div>
                  </div>
                );
              })()}

              {/* Previous playtest results */}
              {selectedLevel.meta.playtest_results && selectedLevel.meta.playtest_results.length > 0 && (
                <div className="mt-3 p-2 bg-gray-700/50 rounded">
                  <div className="text-xs text-gray-400 mb-1">
                    이전 테스트 결과 ({selectedLevel.meta.playtest_results.length}회)
                  </div>
                  <div className="flex gap-4 text-xs">
                    <span>
                      클리어율: {((selectedLevel.meta.playtest_results.filter(r => r.cleared).length / selectedLevel.meta.playtest_results.length) * 100).toFixed(0)}%
                    </span>
                    <span>
                      평균 재미: {(selectedLevel.meta.playtest_results.reduce((sum, r) => sum + r.fun_rating, 0) / selectedLevel.meta.playtest_results.length).toFixed(1)}
                    </span>
                  </div>
                </div>
              )}

              {/* Level JSON viewer */}
              {showLevelJson && (
                <div className="mt-3 p-2 bg-gray-900 rounded border border-gray-700">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-gray-400">Level JSON</span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(JSON.stringify(selectedLevel.level_json, null, 2));
                        addNotification('success', 'JSON 복사됨');
                      }}
                      className="px-2 py-0.5 text-xs bg-gray-700 text-gray-300 rounded hover:bg-gray-600"
                    >
                      복사
                    </button>
                  </div>
                  <pre className="text-xs text-gray-300 overflow-auto max-h-[300px] whitespace-pre-wrap font-mono">
                    {JSON.stringify(selectedLevel.level_json, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            {/* Level preview with test controls overlay */}
            <div ref={previewContainerRef} className="flex-1 relative min-h-[400px] overflow-hidden">
              {/* Background preview - dimmed, no animations */}
              {previewTiles.length > 0 && selectedLevel && (
                <div
                  key={`preview-${selectedLevel.meta.level_number}`}
                  className="absolute inset-0 flex items-center justify-center opacity-50 pointer-events-none [&_*]:!transition-none"
                  style={{
                    transform: `scale(${previewScale})`,
                    transformOrigin: 'center center'
                  }}
                >
                  <GameBoard
                    key={`board-${selectedLevel.meta.level_number}`}
                    tiles={previewTiles}
                    onTileClick={() => {}}
                    tileSize={48}
                    showStats={false}
                    fixedGridSize={7}
                  />
                </div>
              )}

              {/* Controls overlay based on test mode */}
              <div className="absolute inset-0 flex items-center justify-center z-10">
                {testMode === 'manual' && (
                  <Button onClick={handlePlayLevel} className="px-8 py-4 text-lg shadow-2xl bg-indigo-600 hover:bg-indigo-500">
                    ▶ 플레이 시작
                  </Button>
                )}

                {testMode === 'auto_single' && (
                  <div className="flex flex-col items-center gap-4 p-6 bg-gray-900/90 rounded-xl">
                    <div className="text-center">
                      <span className="text-4xl">🤖</span>
                      <h3 className="text-white font-medium mt-2">봇 자동 테스트</h3>
                      <p className="text-sm text-gray-400">5개 봇 프로필로 난이도 검증</p>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="text-sm text-gray-400">반복:</label>
                      <select
                        value={autoTestIterations}
                        onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
                        disabled={isAutoTesting}
                      >
                        <option value={50}>50회</option>
                        <option value={100}>100회</option>
                        <option value={200}>200회</option>
                      </select>
                    </div>

                    <Button
                      onClick={handleAutoTestSingle}
                      disabled={isAutoTesting}
                      className="px-6 py-3 bg-green-600 hover:bg-green-500"
                    >
                      {isAutoTesting ? (
                        <>
                          <span className="animate-spin mr-2">⟳</span>
                          테스트 중...
                        </>
                      ) : (
                        '🎯 자동 테스트 시작'
                      )}
                    </Button>

                    {/* Auto test result */}
                    {autoTestResult && (
                      <div className="w-full max-w-sm space-y-3">
                        {/* Match Score */}
                        <div className={`p-3 rounded-lg text-center ${
                          autoTestResult.match_score >= 70 ? 'bg-green-900/50' :
                          autoTestResult.match_score >= 50 ? 'bg-yellow-900/50' : 'bg-red-900/50'
                        }`}>
                          <div className="text-xs text-gray-400">난이도 일치도</div>
                          <div className={`text-3xl font-bold ${
                            autoTestResult.match_score >= 70 ? 'text-green-400' :
                            autoTestResult.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {autoTestResult.match_score.toFixed(0)}%
                          </div>
                          <div className="text-xs text-gray-500 mt-1">
                            {autoTestResult.balance_status === 'balanced' ? '✅ 균형' :
                             autoTestResult.balance_status === 'too_easy' ? '📉 너무 쉬움' :
                             autoTestResult.balance_status === 'too_hard' ? '📈 너무 어려움' : '⚠️ 불균형'}
                          </div>
                        </div>

                        {/* Bot Stats */}
                        <div className="space-y-1">
                          {autoTestResult.bot_stats.map(bot => {
                            const gap = (bot.clear_rate - bot.target_clear_rate) * 100;
                            const isGood = Math.abs(gap) <= 10;
                            return (
                              <div key={bot.profile} className="flex items-center justify-between text-sm px-2 py-1 bg-gray-700/50 rounded">
                                <span className="text-gray-300">
                                  {bot.profile === 'novice' ? '🌱 초보자' :
                                   bot.profile === 'casual' ? '🎮 캐주얼' :
                                   bot.profile === 'average' ? '👤 일반' :
                                   bot.profile === 'expert' ? '⭐ 숙련자' : '🏆 최적'}
                                </span>
                                <span className="text-white font-medium">
                                  {(bot.clear_rate * 100).toFixed(0)}%
                                </span>
                                <span className={`text-xs ${isGood ? 'text-green-400' : 'text-yellow-400'}`}>
                                  ({gap >= 0 ? '+' : ''}{gap.toFixed(0)}%p)
                                </span>
                              </div>
                            );
                          })}
                        </div>

                        {/* Recommendations */}
                        {autoTestResult.recommendations.length > 0 && (
                          <div className="text-xs text-gray-400">
                            💡 {autoTestResult.recommendations[0]}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {testMode === 'auto_batch' && (
                  <div className="flex flex-col items-center gap-4 p-6 bg-gray-900/90 rounded-xl">
                    <span className="text-4xl">📋</span>
                    <p className="text-sm text-gray-400">상단의 일괄 테스트 설정을 사용하세요</p>
                    {selectedLevel?.meta.match_score !== undefined && (
                      <div className={`px-4 py-2 rounded-lg ${
                        selectedLevel.meta.match_score >= 70 ? 'bg-green-900/50' :
                        selectedLevel.meta.match_score >= 50 ? 'bg-yellow-900/50' : 'bg-red-900/50'
                      }`}>
                        <span className="text-xs text-gray-400">저장된 일치도: </span>
                        <span className={`font-bold ${
                          selectedLevel.meta.match_score >= 70 ? 'text-green-400' :
                          selectedLevel.meta.match_score >= 50 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {selectedLevel.meta.match_score.toFixed(0)}%
                        </span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            왼쪽에서 테스트할 레벨을 선택하세요
          </div>
        )}
      </div>
      </div>
    </div>
  );
}

// Playtest Tab Component
function PlaytestTab({
  batchId,
  onLevelSelect,
}: {
  batchId: string;
  onLevelSelect?: (level: ProductionLevel) => void;
}) {
  const { addNotification } = useUIStore();
  const [queue, setQueue] = useState<ProductionLevel[]>([]);
  const [currentLevel, setCurrentLevel] = useState<ProductionLevel | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Playtest form state
  const [cleared, setCleared] = useState(true);
  const [attempts, setAttempts] = useState(1);
  const [timeSeconds, setTimeSeconds] = useState(60);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    loadQueue();
  }, [batchId]);

  const loadQueue = async () => {
    setIsLoading(true);
    try {
      const queueLevels = await getPlaytestQueue(batchId, 50);
      setQueue(queueLevels);
      if (queueLevels.length > 0 && !currentLevel) {
        setCurrentLevel(queueLevels[0]);
        onLevelSelect?.(queueLevels[0]);
      }
    } catch (err) {
      console.error('Failed to load playtest queue:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmitResult = async () => {
    if (!currentLevel) return;

    const result: PlaytestResult = {
      tester_id: 'default',
      tester_name: '테스터',
      tested_at: new Date().toISOString(),
      cleared,
      attempts,
      time_seconds: timeSeconds,
      perceived_difficulty: perceivedDifficulty,
      fun_rating: funRating,
      comments,
      issues,
    };

    try {
      await addPlaytestResult(batchId, currentLevel.meta.level_number, result);
      addNotification('success', `레벨 ${currentLevel.meta.level_number} 테스트 완료`);

      // Move to next level
      const nextLevel = queue.find(l => l.meta.level_number > currentLevel.meta.level_number);
      if (nextLevel) {
        setCurrentLevel(nextLevel);
        onLevelSelect?.(nextLevel);
      } else {
        setCurrentLevel(null);
      }

      // Reset form
      setCleared(true);
      setAttempts(1);
      setTimeSeconds(60);
      setPerceivedDifficulty(3);
      setFunRating(3);
      setComments('');
      setIssues([]);

      // Reload queue
      loadQueue();
    } catch (err) {
      addNotification('error', '결과 저장 실패');
    }
  };

  if (isLoading) {
    return <div className="text-center text-gray-400 py-8">로딩 중...</div>;
  }

  if (queue.length === 0) {
    return (
      <div className="text-center text-gray-400 py-8">
        플레이테스트 대기열이 비어있습니다.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4">
      {/* Queue List */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">
          대기열 ({queue.length}개)
        </h3>
        <div className="space-y-1 max-h-96 overflow-y-auto">
          {queue.map((level) => (
            <button
              key={level.meta.level_number}
              onClick={() => {
                setCurrentLevel(level);
                onLevelSelect?.(level);
              }}
              className={`w-full text-left px-3 py-2 rounded text-sm transition-colors ${
                currentLevel?.meta.level_number === level.meta.level_number
                  ? 'bg-indigo-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              }`}
            >
              <div className="flex justify-between">
                <span>레벨 {level.meta.level_number}</span>
                <span className={getGradeColor(level.meta.grade)}>{level.meta.grade}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Playtest Form */}
      {currentLevel && (
        <div className="p-4 bg-gray-800 rounded-lg space-y-4">
          <h3 className="text-sm font-medium text-white">
            레벨 {currentLevel.meta.level_number} 테스트
          </h3>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">클리어 여부</label>
              <select
                value={cleared ? 'yes' : 'no'}
                onChange={(e) => setCleared(e.target.value === 'yes')}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value="yes">클리어</option>
                <option value="no">실패</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">시도 횟수</label>
              <input
                type="number"
                value={attempts}
                onChange={(e) => setAttempts(Number(e.target.value))}
                min={1}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">체감 난이도</label>
              <select
                value={perceivedDifficulty}
                onChange={(e) => setPerceivedDifficulty(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 매우 쉬움</option>
                <option value={2}>2 - 쉬움</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 어려움</option>
                <option value={5}>5 - 매우 어려움</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">재미 점수</label>
              <select
                value={funRating}
                onChange={(e) => setFunRating(Number(e.target.value) as 1|2|3|4|5)}
                className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              >
                <option value={1}>1 - 지루함</option>
                <option value={2}>2 - 별로</option>
                <option value={3}>3 - 보통</option>
                <option value={4}>4 - 재미있음</option>
                <option value={5}>5 - 매우 재미있음</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">코멘트</label>
            <textarea
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              className="w-full px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
              rows={2}
            />
          </div>

          <Button onClick={handleSubmitResult} className="w-full">
            결과 저장 & 다음 레벨
          </Button>
        </div>
      )}
    </div>
  );
}

// Review Tab Component
function ReviewTab({
  batchId,
  onLevelSelect,
  onStatsUpdate,
}: {
  batchId: string;
  onLevelSelect?: (level: ProductionLevel) => void;
  onStatsUpdate: () => void;
}) {
  const { addNotification } = useUIStore();
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [filter, setFilter] = useState<LevelStatus | 'all'>('all');
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadLevels();
  }, [batchId, filter]);

  const loadLevels = async () => {
    setIsLoading(true);
    try {
      const options = filter !== 'all' ? { status: filter } : undefined;
      const loadedLevels = await getProductionLevelsByBatch(batchId, {
        ...options,
        limit: 100,
      });
      setLevels(loadedLevels);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleApprove = async (levelNumber: number) => {
    try {
      await approveLevel(batchId, levelNumber, '관리자');
      addNotification('success', `레벨 ${levelNumber} 승인됨`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '승인 실패');
    }
  };

  const handleReject = async (levelNumber: number, reason: string) => {
    try {
      await rejectLevel(batchId, levelNumber, reason);
      addNotification('info', `레벨 ${levelNumber} 거부됨`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      addNotification('error', '거부 실패');
    }
  };

  return (
    <div className="space-y-4">
      {/* Filter */}
      <div className="flex gap-2">
        {[
          { value: 'all', label: '전체' },
          { value: 'generated', label: '생성됨' },
          { value: 'needs_rework', label: '수정필요' },
          { value: 'approved', label: '승인됨' },
          { value: 'rejected', label: '거부됨' },
        ].map((opt) => (
          <button
            key={opt.value}
            onClick={() => setFilter(opt.value as LevelStatus | 'all')}
            className={`px-3 py-1 rounded text-sm ${
              filter === opt.value
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Level List */}
      {isLoading ? (
        <div className="text-center text-gray-400 py-8">로딩 중...</div>
      ) : (
        <div className="space-y-2 max-h-[500px] overflow-y-auto">
          {levels.map((level) => (
            <div
              key={level.meta.level_number}
              className="flex items-center justify-between p-3 bg-gray-800 rounded-lg"
            >
              <div className="flex items-center gap-4">
                <button
                  onClick={() => onLevelSelect?.(level)}
                  className="text-indigo-400 hover:text-indigo-300"
                >
                  레벨 {level.meta.level_number}
                </button>
                <span className={getGradeColor(level.meta.grade)}>{level.meta.grade}</span>
                <span className="text-xs text-gray-400">
                  {level.meta.actual_difficulty.toFixed(3)}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                  {getStatusLabel(level.meta.status)}
                </span>
              </div>
              <div className="flex gap-2">
                {level.meta.status !== 'approved' && level.meta.status !== 'exported' && (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleApprove(level.meta.level_number)}
                  >
                    승인
                  </Button>
                )}
                {level.meta.status !== 'rejected' && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      const reason = prompt('거부 사유:');
                      if (reason) handleReject(level.meta.level_number, reason);
                    }}
                  >
                    거부
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Export Tab Component
function ExportTab({
  batchId,
  stats,
}: {
  batchId: string;
  stats: ProductionStats;
}) {
  const { addNotification } = useUIStore();
  const [format, setFormat] = useState<'json' | 'json_minified' | 'json_split'>('json');
  const [includeMeta, setIncludeMeta] = useState(false);
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = async () => {
    setIsExporting(true);
    try {
      const result = await exportProductionLevels(batchId, {
        format,
        include_meta: includeMeta,
        filename_pattern: 'level_{number:04d}.json',
        output_dir: '',
      });

      if ('files' in result) {
        // Multiple files - create zip (simplified: just download first few)
        addNotification('info', `${result.files.length}개 파일 생성됨 (zip 다운로드는 추후 지원)`);
      } else {
        // Single file
        const url = URL.createObjectURL(result);
        const a = document.createElement('a');
        a.href = url;
        a.download = `production_levels_${batchId}.json`;
        a.click();
        URL.revokeObjectURL(url);
        addNotification('success', '내보내기 완료');
      }
    } catch (err) {
      addNotification('error', '내보내기 실패');
    } finally {
      setIsExporting(false);
    }
  };

  const readyCount = stats.by_status.approved;

  return (
    <div className="space-y-4">
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-4">내보내기 설정</h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm text-gray-400 mb-1">포맷</label>
            <select
              value={format}
              onChange={(e) => setFormat(e.target.value as typeof format)}
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
            >
              <option value="json">JSON (포맷팅)</option>
              <option value="json_minified">JSON (압축)</option>
              <option value="json_split">개별 파일</option>
            </select>
          </div>

          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={includeMeta}
              onChange={(e) => setIncludeMeta(e.target.checked)}
            />
            <span className="text-sm text-gray-300">메타데이터 포함</span>
          </label>

          <div className="text-sm text-gray-400">
            내보내기 가능: <span className="text-green-400 font-medium">{readyCount}개</span> / {stats.total_levels}개
          </div>

          <Button
            onClick={handleExport}
            disabled={isExporting || readyCount === 0}
            className="w-full"
          >
            {isExporting ? '내보내는 중...' : `내보내기 (${readyCount}개)`}
          </Button>
        </div>
      </div>
    </div>
  );
}

// Helper Components
function StatCard({ label, value, total, color = 'blue' }: {
  label: string;
  value: number;
  total?: number;
  color?: 'blue' | 'green' | 'red' | 'yellow';
}) {
  const colorClasses = {
    blue: 'text-blue-400',
    green: 'text-green-400',
    red: 'text-red-400',
    yellow: 'text-yellow-400',
  };

  return (
    <div className="p-3 bg-gray-800 rounded-lg">
      <div className="text-xs text-gray-400">{label}</div>
      <div className={`text-xl font-bold ${colorClasses[color]}`}>
        {value}
        {total && <span className="text-sm text-gray-500">/{total}</span>}
      </div>
    </div>
  );
}

function StatusBar({ label, count, total, color }: {
  label: string;
  count: number;
  total: number;
  color: 'blue' | 'green' | 'yellow' | 'purple';
}) {
  const percent = total > 0 ? (count / total) * 100 : 0;
  const colorClasses = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    purple: 'bg-purple-500',
  };

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-gray-400">{label}</span>
        <span className="text-gray-300">{count}</span>
      </div>
      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClasses[color]}`}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function getGradeColor(grade: DifficultyGrade): string {
  switch (grade) {
    case 'S': return 'text-green-400';
    case 'A': return 'text-blue-400';
    case 'B': return 'text-yellow-400';
    case 'C': return 'text-orange-400';
    case 'D': return 'text-red-400';
    default: return 'text-gray-400';
  }
}

function getStatusColor(status: LevelStatus): string {
  switch (status) {
    case 'generated': return 'bg-blue-900 text-blue-300';
    case 'playtest_queue': return 'bg-yellow-900 text-yellow-300';
    case 'playtesting': return 'bg-orange-900 text-orange-300';
    case 'approved': return 'bg-green-900 text-green-300';
    case 'rejected': return 'bg-red-900 text-red-300';
    case 'needs_rework': return 'bg-purple-900 text-purple-300';
    case 'exported': return 'bg-indigo-900 text-indigo-300';
    default: return 'bg-gray-700 text-gray-300';
  }
}

function getStatusLabel(status: LevelStatus): string {
  switch (status) {
    case 'generated': return '생성됨';
    case 'playtest_queue': return '테스트 대기';
    case 'playtesting': return '테스트 중';
    case 'approved': return '승인됨';
    case 'rejected': return '거부됨';
    case 'needs_rework': return '수정필요';
    case 'exported': return '출시됨';
    default: return status;
  }
}

// Export sub-components
export { ProductionBatchList } from './ProductionBatchList';
export { ProductionProgress } from './ProductionProgress';
export { PlaytestPanel } from './PlaytestPanel';
export { LevelReviewPanel } from './LevelReviewPanel';
export { ProductionExport } from './ProductionExport';
