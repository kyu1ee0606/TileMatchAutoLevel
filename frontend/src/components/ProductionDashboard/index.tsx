/**
 * Production Dashboard
 * 1500개 레벨 프로덕션 관리 대시보드
 */

import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel } from '../../api/generate';
import GamePlayer from '../GamePlayer';
import type { GameStats, LevelInfo } from '../../types/game';
import type { GenerationParams, DifficultyGrade } from '../../types';
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
            // Generate level
            const params: GenerationParams = {
              target_difficulty: targetDifficulty,
              grid_size: [7, 7],
              max_layers: Math.min(7, 3 + Math.floor(targetDifficulty * 4)),
              tile_types: ['t1', 't2', 't3', 't4', 't5', 't6'].slice(0, 3 + Math.floor(targetDifficulty * 3)),
              obstacle_types: [],
              goals: [{ type: 'craft', direction: 's', count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
              symmetry_mode: 'both',
              pattern_type: 'aesthetic',
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

      setGenerationProgress(prev => ({
        ...prev,
        status: 'completed',
        completed_levels: completedCount,
        failed_levels: failedLevels,
      }));

      // Refresh stats
      const newStats = await calculateProductionStats(selectedBatchId);
      setStats(newStats);

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

// Test Tab Component - 레벨 직접 플레이 테스트
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

  // Playtest result state (after game ends)
  const [showResultForm, setShowResultForm] = useState(false);
  const [gameResult, setGameResult] = useState<{ won: boolean; stats: GameStats } | null>(null);
  const [perceivedDifficulty, setPerceivedDifficulty] = useState<1|2|3|4|5>(3);
  const [funRating, setFunRating] = useState<1|2|3|4|5>(3);
  const [comments, setComments] = useState('');
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    loadLevels();
  }, [batchId, filter]);

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
    <div className="flex gap-4 h-[calc(100vh-250px)] min-h-[600px]">
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
                        난이도: {(level.meta.actual_difficulty * 100).toFixed(0)}%
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-sm font-bold ${getGradeColor(level.meta.grade)}`}>
                        {level.meta.grade}
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                        {getStatusLabel(level.meta.status)}
                      </span>
                    </div>
                  </div>
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
      <div className="flex-1 flex flex-col bg-gray-800 rounded-lg overflow-hidden">
        {selectedLevel ? (
          <>
            {/* Level info */}
            <div className="p-4 border-b border-gray-700">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-lg font-medium text-white">
                  레벨 {selectedLevel.meta.level_number}
                </h3>
                <span className={`text-xl font-bold ${getGradeColor(selectedLevel.meta.grade)}`}>
                  {selectedLevel.meta.grade}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-gray-400">목표 난이도:</span>
                  <span className="text-white ml-2">{(selectedLevel.meta.target_difficulty * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span className="text-gray-400">실제 난이도:</span>
                  <span className="text-white ml-2">{(selectedLevel.meta.actual_difficulty * 100).toFixed(0)}%</span>
                </div>
                <div>
                  <span className="text-gray-400">상태:</span>
                  <span className={`ml-2 px-2 py-0.5 rounded text-xs ${getStatusColor(selectedLevel.meta.status)}`}>
                    {getStatusLabel(selectedLevel.meta.status)}
                  </span>
                </div>
              </div>

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
            </div>

            {/* Play button */}
            <div className="flex-1 flex items-center justify-center">
              <Button onClick={handlePlayLevel} className="px-8 py-4 text-lg">
                ▶ 플레이 시작
              </Button>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            왼쪽에서 테스트할 레벨을 선택하세요
          </div>
        )}
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
                  {(level.meta.actual_difficulty * 100).toFixed(0)}%
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
