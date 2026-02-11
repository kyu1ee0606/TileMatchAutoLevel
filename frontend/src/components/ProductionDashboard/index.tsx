/**
 * Production Dashboard
 * 1500개 레벨 프로덕션 관리 대시보드
 */

import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { generateLevel, enhanceLevel } from '../../api/generate';
import { analyzeAutoPlay } from '../../api/analyze';
import GamePlayer from '../GamePlayer';
import GameBoard from '../GamePlayer/GameBoard';
import { createGameEngine } from '../../engine/gameEngine';
import type { GameStats, LevelInfo, GameTile } from '../../types/game';
import type { GenerationParams, GenerationResult, DifficultyGrade, LevelJSON } from '../../types';
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
  updateProductionBatch,
  listProductionBatches,
  saveProductionLevels,
  getProductionLevelsByBatch,
  getPlaytestQueue,
  addPlaytestResult,
  approveLevel,
  rejectLevel,
  calculateProductionStats,
  deleteProductionBatch,
  renameProductionBatch,
  recalculateBatchCounts,
} from '../../storage/productionStorage';
import { ProductionExport } from './ProductionExport';
import { BatchApprovalPanel } from './BatchApprovalPanel';

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
  const [useValidatedGeneration, setUseValidatedGeneration] = useState(false); // 검증 기반 생성 (기본 OFF - 빠른 생성)
  const [useCoreBots, setUseCoreBots] = useState(true); // 3봇 코어 모드 (기본 ON - 40% 빠름)
  const [validationConfig, setValidationConfig] = useState({
    max_retries: 3,           // 최대 재시도 횟수
    tolerance: 20.0,          // 허용 오차 (%)
    simulation_iterations: 20, // 시뮬레이션 반복 횟수 (가볍게)
  });
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

  // Throttled progress updater: max 2 renders/sec instead of ~630 during generation
  const progressRef = useRef<ProductionGenerationProgress>(generationProgress);
  const progressTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushProgress = useCallback(() => {
    setGenerationProgress({ ...progressRef.current });
  }, []);

  const updateProgressThrottled = useCallback((
    updater: (prev: ProductionGenerationProgress) => ProductionGenerationProgress
  ) => {
    progressRef.current = updater(progressRef.current);
    if (!progressTimerRef.current) {
      progressTimerRef.current = setTimeout(() => {
        progressTimerRef.current = null;
        flushProgress();
      }, 500);
    }
  }, [flushProgress]);

  const flushProgressImmediate = useCallback(() => {
    if (progressTimerRef.current) {
      clearTimeout(progressTimerRef.current);
      progressTimerRef.current = null;
    }
    flushProgress();
  }, [flushProgress]);

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
    const initialProgress: ProductionGenerationProgress = {
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
    };
    progressRef.current = initialProgress;
    setGenerationProgress(initialProgress);

    const pendingLevels: ProductionLevel[] = [];
    let completedCount = 0;
    const failedLevels: number[] = [];

    // In-memory counters to avoid post-generation full IndexedDB scans
    const statusCounts = { generated_count: 0, playtest_count: 0, approved_count: 0, rejected_count: 0, exported_count: 0 };
    const gradeCounts: Record<string, number> = { S: 0, A: 0, B: 0, C: 0, D: 0 };
    let totalMatchScore = 0;
    let matchScoreCount = 0;

    try {
      for (let setIdx = 0; setIdx < batch.total_sets; setIdx++) {
        if (signal.aborted) throw new Error('cancelled');

        updateProgressThrottled(prev => ({
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

        // PARALLEL GENERATION: Generate all levels in this set concurrently
        // 비검증 모드: 10개 동시 (빠름, 요청당 ~3ms)
        // 검증 모드: 8개 동시 (ProcessPoolExecutor 병렬화 + 4 uvicorn workers)
        const CONCURRENCY = useValidatedGeneration ? 8 : 10;

        // Prepare level generation tasks for this set
        interface LevelTask {
          localIdx: number;
          levelNumber: number;
          targetDifficulty: number;
        }

        const levelTasks: LevelTask[] = [];
        for (let localIdx = 1; localIdx <= batch.levels_per_set; localIdx++) {
          const levelNumber = setIdx * batch.levels_per_set + localIdx;
          let targetDifficulty = baseDifficulty;
          if (batch.use_sawtooth) {
            const localProgress = (localIdx - 1) / (batch.levels_per_set - 1);
            const sawtoothBonus = localIdx === 10 ? 0.1 : localProgress * 0.05;
            targetDifficulty = Math.min(0.95, baseDifficulty + sawtoothBonus);
          }
          levelTasks.push({ localIdx, levelNumber, targetDifficulty });
        }

        // Helper: Generate a single level (returns ProductionLevel or null on failure)
        const generateOneLevel = async (task: LevelTask): Promise<ProductionLevel | null> => {
          const { localIdx, levelNumber, targetDifficulty } = task;

          // Local helper: Calculate match score from bot stats (asymmetric penalty)
          const calcMatchScore = (botStats: { clear_rate: number; target_clear_rate: number }[]) => {
            if (!botStats.length) return 0;
            const gaps = botStats.map(s => {
              const rawGap = (s.clear_rate - s.target_clear_rate) * 100;
              return rawGap > 0 ? rawGap * 0.5 : Math.abs(rawGap); // Too easy = 50% penalty
            });
            const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
            const maxGap = Math.max(...gaps);
            const weightedGap = (avgGap * 0.6 + maxGap * 0.4);
            return Math.max(0, 100 - weightedGap * 2);
          };

          try {
            const isEarlyLevel = levelNumber <= 30;
            const isSpecialShape = levelNumber % 10 === 9;
            const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

            // Pattern type selection
            const patternRoll = Math.random();
            let patternType: 'aesthetic' | 'geometric' | 'clustered';
            if (isEarlyLevel) {
              patternType = patternRoll < 0.50 ? 'geometric' : patternRoll < 0.90 ? 'aesthetic' : 'clustered';
            } else if (isBossLevel) {
              patternType = patternRoll < 0.75 ? 'aesthetic' : patternRoll < 0.95 ? 'geometric' : 'clustered';
            } else if (isSpecialShape) {
              patternType = patternRoll < 0.50 ? 'aesthetic' : patternRoll < 0.75 ? 'geometric' : 'clustered';
            } else {
              patternType = patternRoll < 0.60 ? 'aesthetic' : patternRoll < 0.85 ? 'geometric' : 'clustered';
            }

            // Symmetry mode selection
            const symmetryRoll = Math.random();
            let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
            if (isEarlyLevel) {
              symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
            } else if (isSpecialShape) {
              symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
            } else if (isBossLevel) {
              symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
            } else {
              symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
            }

            // Goal direction
            let goalDirections: Array<'s' | 'n' | 'e' | 'w'>;
            if (symmetryMode === 'both' || symmetryMode === 'vertical') {
              goalDirections = Math.random() < 0.7 ? ['s', 'n'] : ['e', 'w'];
            } else if (symmetryMode === 'horizontal') {
              goalDirections = Math.random() < 0.7 ? ['e', 'w'] : ['s', 'n'];
            } else {
              goalDirections = ['s', 'n', 'e', 'w'];
            }
            const goalDirection = goalDirections[Math.floor(Math.random() * goalDirections.length)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

            // Pattern index
            let patternIndex: number | undefined = undefined;
            if (patternType === 'aesthetic') {
              if (isBossLevel) {
                const bossPatterns = [8, 15, 16, 45, 46, 17, 18];
                patternIndex = bossPatterns[Math.floor(Math.random() * bossPatterns.length)];
              } else if (isSpecialShape) {
                const specialPatterns = [3, 4, 20, 23, 24, 30, 33];
                patternIndex = specialPatterns[Math.floor(Math.random() * specialPatterns.length)];
              }
            }

            // Grid size
            let gridSize: [number, number] = [7, 7];
            if (isBossLevel && targetDifficulty > 0.3) {
              gridSize = [8, 8];
            } else if (!isEarlyLevel && Math.random() < 0.3) {
              gridSize = [8, 8];
            }

            // Layers
            let minLayers = 2;
            let maxLayers = Math.min(7, 3 + Math.floor(targetDifficulty * 4));
            if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
            else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(7, 4 + Math.floor(targetDifficulty * 3)); }

            // Tile types: 백엔드에서 level_number 기반 자동 선택 (톱니바퀴 패턴 + t0)
            // - 사이클 첫 레벨 (1, 11, 21...): 특정 타일 세트 (t1-t5, t6-t10, t11-t15)
            // - 나머지 레벨: t0 (클라이언트에서 런타임 결정)

            const params: GenerationParams = {
              target_difficulty: targetDifficulty,
              grid_size: gridSize,
              min_layers: minLayers,
              max_layers: maxLayers,
              tile_types: undefined, // 백엔드에서 level_number 기반 자동 선택
              obstacle_types: [],
              goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
              symmetry_mode: symmetryMode,
              pattern_type: patternType,
              pattern_index: patternIndex,
            };

            const gimmickOptions = {
              auto_select_gimmicks: true,
              available_gimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
              gimmick_unlock_levels: batch.gimmick_unlock_levels,
              level_number: levelNumber,
            };

            let result;
            let validationPassed = true;
            let validationAttempts = 1;
            let matchScore: number | undefined = undefined;
            let botClearRates: { novice: number; casual: number; average: number; expert: number; optimal: number } | undefined = undefined;

            // === 공통: 허용 오차 다중 후보 방식으로 정적 난이도 오차 0.05 이내 달성 ===
            const DIFFICULTY_TOLERANCE = 5.0; // 0.05 in 0-1 scale = 5.0 in 0-100 scale
            const CANDIDATES_PER_ATTEMPT = 3;
            const MAX_ATTEMPTS = 5;
            const targetScore = targetDifficulty * 100;

            let bestResult: GenerationResult | null = null;
            let bestGap = Infinity;
            let actualAttempts = 0;

            for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
              actualAttempts = attempt + 1;
              const candidates = await Promise.all(
                Array.from({ length: CANDIDATES_PER_ATTEMPT }, () => {
                  // 미형 로직 유지: pattern_type, symmetry_mode, pattern_index는 기존 params 사용
                  // 난이도 다양성을 위해 goal direction/type만 변경
                  const candidateGoalDirection = (['s', 'n', 'e', 'w'] as const)[Math.floor(Math.random() * 4)];
                  const candidateGoalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

                  return generateLevel(
                    {
                      ...params,
                      goals: [{
                        type: candidateGoalType,
                        direction: candidateGoalDirection,
                        count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
                      }],
                    },
                    {
                      ...gimmickOptions,
                      gimmick_intensity: Math.min(1, levelNumber / 500),
                    }
                  ).catch(() => null);
                })
              );

              for (const c of candidates) {
                if (!c) continue;
                const gap = Math.abs(c.actual_difficulty - targetScore);
                if (gap < bestGap) {
                  bestGap = gap;
                  bestResult = c;
                }
              }

              if (bestGap <= DIFFICULTY_TOLERANCE) break; // 허용 오차 이내 → 즉시 채택
            }

            if (!bestResult) {
              throw new Error(`${MAX_ATTEMPTS * CANDIDATES_PER_ATTEMPT}개 후보 모두 실패`);
            }
            result = bestResult;
            validationAttempts = actualAttempts;

            // === 검증 활성화 시: 봇 시뮬레이션으로 match_score 측정 ===
            if (useValidatedGeneration && validationConfig.simulation_iterations > 0) {
              try {
                const botProfiles = useCoreBots
                  ? ['casual', 'average', 'expert']  // 코어 3봇
                  : ['novice', 'casual', 'average', 'expert', 'optimal'];  // 전체 5봇
                const simResult = await analyzeAutoPlay(result.level_json, {
                  iterations: validationConfig.simulation_iterations,
                  targetDifficulty: targetDifficulty,
                  botProfiles: botProfiles,
                });
                matchScore = calcMatchScore(simResult.bot_stats);
                botClearRates = {
                  novice: simResult.bot_stats.find(s => s.profile === 'novice')?.clear_rate || 0,
                  casual: simResult.bot_stats.find(s => s.profile === 'casual')?.clear_rate || 0,
                  average: simResult.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
                  expert: simResult.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
                  optimal: simResult.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
                };
                validationPassed = matchScore !== undefined && matchScore >= validationConfig.tolerance;
              } catch (simErr) {
                console.warn(`Bot simulation failed for level ${levelNumber}:`, simErr);
                // 시뮬레이션 실패 시 match_score 없이 진행
              }
            }

            const meta: ProductionLevelMeta = {
              level_number: levelNumber,
              set_index: setIdx,
              local_index: localIdx,
              generated_at: new Date().toISOString(),
              target_difficulty: targetDifficulty,
              actual_difficulty: result.actual_difficulty,
              grade: result.grade as DifficultyGrade,
              status: validationPassed ? 'generated' : 'playtest_queue',
              status_updated_at: new Date().toISOString(),
              playtest_required: !validationPassed || shouldRequirePlaytest(
                { level_number: levelNumber, grade: result.grade as DifficultyGrade, match_score: matchScore, target_difficulty: targetDifficulty },
                playtestConfig
              ),
              playtest_priority: validationPassed ? levelNumber : levelNumber - 10000,
              playtest_results: [],
              match_score: matchScore,
              bot_clear_rates: botClearRates,
              validation_attempts: validationAttempts,
            };

            if (meta.playtest_required) {
              meta.status = 'playtest_queue';
            }

            return { meta, level_json: result.level_json };
          } catch (err) {
            console.error(`Failed to generate level ${levelNumber}:`, err);
            return null;
          }
        };

        // Execute in parallel batches with concurrency limit
        for (let batchStart = 0; batchStart < levelTasks.length; batchStart += CONCURRENCY) {
          if (signal.aborted) throw new Error('cancelled');

          const batchSlice = levelTasks.slice(batchStart, batchStart + CONCURRENCY);

          // Update progress for current batch (throttled to reduce re-renders)
          const lastLevelNum = batchSlice[batchSlice.length - 1].levelNumber;
          updateProgressThrottled(prev => ({
            ...prev,
            current_level: lastLevelNum,
            elapsed_ms: Date.now() - startTime,
            estimated_remaining_ms: completedCount > 0
              ? ((Date.now() - startTime) / completedCount) * (batch.total_levels - completedCount)
              : 0,
          }));

          // Run batch in parallel
          const results = await Promise.allSettled(
            batchSlice.map(task => generateOneLevel(task))
          );

          // Process results and accumulate in-memory counters
          for (let i = 0; i < results.length; i++) {
            const r = results[i];
            const task = batchSlice[i];
            if (r.status === 'fulfilled' && r.value) {
              pendingLevels.push(r.value);
              completedCount++;
              // Accumulate stats in-memory
              const meta = r.value.meta;
              if (meta.status === 'generated') statusCounts.generated_count++;
              else if (meta.status === 'playtest_queue' || meta.status === 'playtesting') statusCounts.playtest_count++;
              if (meta.grade in gradeCounts) gradeCounts[meta.grade]++;
              if (meta.match_score !== undefined) {
                totalMatchScore += meta.match_score;
                matchScoreCount++;
              }
            } else {
              failedLevels.push(task.levelNumber);
              if (r.status === 'rejected') {
                console.error(`Failed to generate level ${task.levelNumber}:`, r.reason);
              }
            }
          }

          // Update completed_levels after every batch (throttled)
          updateProgressThrottled(prev => ({
            ...prev,
            completed_levels: completedCount,
            elapsed_ms: Date.now() - startTime,
            estimated_remaining_ms: completedCount > 0
              ? ((Date.now() - startTime) / completedCount) * (batch.total_levels - completedCount)
              : 0,
          }));

          // Checkpoint save every 50 levels — non-blocking fire-and-forget
          if (pendingLevels.length >= 50 || signal.aborted) {
            const levelsToSave = [...pendingLevels];
            pendingLevels.length = 0;
            saveProductionLevels(selectedBatchId, levelsToSave).catch(err => {
              console.error('[Checkpoint] Save failed, will retry:', err);
              pendingLevels.push(...levelsToSave);
            });
            updateProgressThrottled(prev => ({
              ...prev,
              last_checkpoint_at: new Date().toISOString(),
            }));
          }
        }

        updateProgressThrottled(prev => ({
          ...prev,
          completed_sets: setIdx + 1,
          completed_levels: completedCount,
        }));
      }

      // Save remaining levels
      if (pendingLevels.length > 0) {
        await saveProductionLevels(selectedBatchId, pendingLevels);
      }

      // Update batch counts using in-memory counters (avoids full IndexedDB scan)
      await updateProductionBatch(selectedBatchId, statusCounts);

      // Flush throttled progress, then set final state immediately
      flushProgressImmediate();
      setGenerationProgress(prev => ({
        ...prev,
        status: 'completed',
        completed_levels: completedCount,
        failed_levels: failedLevels,
      }));

      // Build stats from in-memory counters (avoids second full IndexedDB scan)
      const playtestRequired = statusCounts.playtest_count;
      const inMemoryStats: ProductionStats = {
        total_levels: completedCount,
        by_status: {
          generated: statusCounts.generated_count,
          playtest_queue: statusCounts.playtest_count,
          playtesting: 0,
          approved: 0,
          rejected: 0,
          needs_rework: 0,
          exported: 0,
        } as Record<LevelStatus, number>,
        by_grade: {
          S: gradeCounts['S'] || 0,
          A: gradeCounts['A'] || 0,
          B: gradeCounts['B'] || 0,
          C: gradeCounts['C'] || 0,
          D: gradeCounts['D'] || 0,
        } as Record<DifficultyGrade, number>,
        playtest_progress: {
          total_required: playtestRequired,
          completed: 0,
          pending: playtestRequired,
        },
        quality_metrics: {
          avg_match_score: matchScoreCount > 0 ? totalMatchScore / matchScoreCount : 0,
          avg_fun_rating: 0,
          avg_perceived_difficulty: 0,
          rejection_rate: 0,
        },
        estimated_completion: {
          remaining_playtest_hours: (playtestRequired * 3) / 60,
          ready_for_export: 0,
        },
      };
      setStats(inMemoryStats);

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
        flushProgressImmediate();
        setGenerationProgress(prev => ({
          ...prev,
          status: 'paused',
          completed_levels: completedCount,
        }));
        addNotification('info', `생성 일시 정지됨 (${completedCount}개 저장됨)`);
      } else {
        flushProgressImmediate();
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
  }, [selectedBatchId, addNotification, useValidatedGeneration, validationConfig, useCoreBots, updateProgressThrottled, flushProgressImmediate]);

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

  // Rename batch state
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState('');

  // Rename batch
  const handleRenameBatch = useCallback(async () => {
    if (!selectedBatchId || !renameValue.trim()) {
      return;
    }

    try {
      await renameProductionBatch(selectedBatchId, renameValue.trim());
      setBatches(prev => prev.map(b =>
        b.id === selectedBatchId ? { ...b, name: renameValue.trim() } : b
      ));
      setIsRenaming(false);
      addNotification('success', '배치 이름 변경됨');
    } catch (err) {
      addNotification('error', '배치 이름 변경 실패');
    }
  }, [selectedBatchId, renameValue, addNotification]);

  // Start rename mode
  const startRename = useCallback(() => {
    const batch = batches.find(b => b.id === selectedBatchId);
    if (batch) {
      setRenameValue(batch.name);
      setIsRenaming(true);
    }
  }, [batches, selectedBatchId]);

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
          {isRenaming ? (
            <>
              <input
                type="text"
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleRenameBatch();
                  if (e.key === 'Escape') setIsRenaming(false);
                }}
                className="flex-1 px-3 py-1 bg-gray-700 border border-indigo-500 rounded text-sm text-white focus:outline-none"
                autoFocus
              />
              <Button
                variant="primary"
                size="sm"
                onClick={handleRenameBatch}
              >
                확인
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setIsRenaming(false)}
              >
                취소
              </Button>
            </>
          ) : (
            <>
              <select
                value={selectedBatchId || ''}
                onChange={(e) => setSelectedBatchId(e.target.value)}
                className="flex-1 px-3 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
              >
                {batches.map((batch) => (
                  <option key={batch.id} value={batch.id}>
                    {batch.name} ({batch.generated_count + batch.playtest_count}/{batch.total_levels})
                  </option>
                ))}
              </select>
              {selectedBatch && (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={startRename}
                  >
                    이름변경
                  </Button>
                  <Button
                    variant="danger"
                    size="sm"
                    onClick={() => handleDeleteBatch(selectedBatch.id)}
                  >
                    삭제
                  </Button>
                </>
              )}
            </>
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
            useValidation={useValidatedGeneration}
            onUseValidationChange={setUseValidatedGeneration}
            validationConfig={validationConfig}
            onValidationConfigChange={setValidationConfig}
            useCoreBots={useCoreBots}
            onUseCoreBotsChange={setUseCoreBots}
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

        {activeTab === 'export' && selectedBatchId && stats && selectedBatch && (
          <ProductionExport
            batchId={selectedBatchId}
            batchName={selectedBatch.name}
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
        <StatCard label="생성 완료" value={batch.generated_count + batch.playtest_count} total={batch.total_levels} />
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
  useValidation,
  onUseValidationChange,
  validationConfig,
  onValidationConfigChange,
  useCoreBots,
  onUseCoreBotsChange,
}: {
  batch: ProductionBatch;
  progress: ProductionGenerationProgress;
  isGenerating: boolean;
  onStart: (config: PlaytestQueueConfig) => void;
  onCancel: () => void;
  useValidation: boolean;
  onUseValidationChange: (value: boolean) => void;
  validationConfig: { max_retries: number; tolerance: number; simulation_iterations: number };
  onValidationConfigChange: (config: { max_retries: number; tolerance: number; simulation_iterations: number }) => void;
  useCoreBots: boolean;
  onUseCoreBotsChange: (value: boolean) => void;
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

          {/* Validation Settings */}
          <div className="p-3 bg-gray-700/50 rounded-lg space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-sm text-white">난이도 검증 기반 생성</label>
              <button
                onClick={() => onUseValidationChange(!useValidation)}
                className={`w-12 h-6 rounded-full transition-colors ${
                  useValidation ? 'bg-green-500' : 'bg-gray-600'
                }`}
              >
                <div className={`w-5 h-5 bg-white rounded-full transition-transform ${
                  useValidation ? 'translate-x-6' : 'translate-x-0.5'
                }`} />
              </button>
            </div>
            {useValidation && (
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">최대 재시도</span>
                  <select
                    value={validationConfig.max_retries}
                    onChange={(e) => onValidationConfigChange({
                      ...validationConfig,
                      max_retries: parseInt(e.target.value)
                    })}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value={2}>2회</option>
                    <option value={3}>3회</option>
                    <option value={5}>5회</option>
                  </select>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">검증 속도</span>
                  <select
                    value={validationConfig.simulation_iterations}
                    onChange={(e) => onValidationConfigChange({
                      ...validationConfig,
                      simulation_iterations: parseInt(e.target.value)
                    })}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value={0}>🚫 안함 (즉시 생성)</option>
                    <option value={10}>⚡ 빠름 (10회)</option>
                    <option value={20}>⚖️ 보통 (20회)</option>
                    <option value={50}>🎯 정밀 (50회)</option>
                  </select>
                </div>
                <div className="flex items-center justify-between mt-2">
                  <span className="text-gray-400">봇 모드</span>
                  <select
                    value={useCoreBots ? 'core' : 'full'}
                    onChange={(e) => onUseCoreBotsChange(e.target.value === 'core')}
                    className="px-2 py-1 bg-gray-600 border border-gray-500 rounded text-white text-xs"
                  >
                    <option value="core">⚡ 코어 3봇 (빠름)</option>
                    <option value="full">🎯 전체 5봇 (정밀)</option>
                  </select>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  검증 실패시 자동 재생성하여 클리어 가능한 레벨만 생성합니다.
                  {validationConfig.simulation_iterations === 0 && (
                    <span className="block text-yellow-400 mt-1">시뮬레이션 없이 빠르게 생성합니다 (캘리브레이션만 적용).</span>
                  )}
                  {useCoreBots && validationConfig.simulation_iterations > 0 && (
                    <span className="block text-blue-400 mt-1">코어 3봇 (casual/average/expert)으로 ~40% 빠른 검증.</span>
                  )}
                </p>
              </div>
            )}
          </div>

          {/* Summary */}
          <div className="text-sm text-gray-400">
            <div>총 {batch.total_levels}개 레벨 생성</div>
            <div>난이도 범위: {(batch.difficulty_start * 100).toFixed(0)}% ~ {(batch.difficulty_end * 100).toFixed(0)}%</div>
            <div>패턴: {batch.use_sawtooth ? '톱니바퀴 (보스/휴식 사이클)' : '선형 증가'}</div>
            <div className="text-blue-400">⚡ 병렬 생성: 10개 동시 처리</div>
            {useValidation && (
              <div className="text-green-400">✓ 난이도 검증 활성화 (최대 {validationConfig.max_retries}회 재시도{validationConfig.simulation_iterations === 0 ? ', 시뮬레이션 없음' : ''}{useCoreBots ? ', 코어 3봇' : ', 전체 5봇'})</div>
            )}
          </div>

          <Button
            onClick={() => onStart({ strategy: playtestStrategy })}
            className="w-full"
          >
            {useValidation ? '검증 기반 생성 시작' : '생성 시작'} ({batch.total_levels}개)
          </Button>
        </div>
      )}

      {/* Progress - Enhanced Dashboard */}
      {(isGenerating || progress.status !== 'idle') && (() => {
        // 평균 속도 계산 (레벨/분)
        const avgSpeed = progress.elapsed_ms > 0
          ? (progress.completed_levels / (progress.elapsed_ms / 60000))
          : 0;

        // 세트별 진행률 계산 (현재 세트 주변 5개 표시)
        const SETS_TO_SHOW = 7;
        const currentSetIndex = progress.current_set_index;
        const startSetIndex = Math.max(0, currentSetIndex - 2);
        const setProgresses: { index: number; completed: boolean; active: boolean; percent: number }[] = [];

        for (let i = 0; i < SETS_TO_SHOW && startSetIndex + i < progress.total_sets; i++) {
          const setIndex = startSetIndex + i;
          const levelsPerSet = 10;
          const completedInSet = Math.max(0, Math.min(levelsPerSet,
            progress.completed_levels - (setIndex * levelsPerSet)));

          setProgresses.push({
            index: setIndex,
            completed: completedInSet >= levelsPerSet,
            active: setIndex === currentSetIndex,
            percent: (completedInSet / levelsPerSet) * 100,
          });
        }

        return (
          <div className="p-4 bg-gray-800 rounded-lg space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-sm font-medium text-white flex items-center gap-2">
                📊 생성 진행률
              </h3>
              <span className={`text-xs px-2 py-0.5 rounded ${
                progress.status === 'generating' ? 'bg-indigo-900/50 text-indigo-300' :
                progress.status === 'completed' ? 'bg-green-900/50 text-green-300' :
                progress.status === 'paused' ? 'bg-yellow-900/50 text-yellow-300' :
                progress.status === 'error' ? 'bg-red-900/50 text-red-300' : 'bg-gray-700 text-gray-300'
              }`}>
                {progress.status === 'generating' ? '생성 중...' :
                 progress.status === 'completed' ? '완료' :
                 progress.status === 'paused' ? '일시 정지' :
                 progress.status === 'error' ? '오류' : '대기'}
              </span>
            </div>

            {/* Main Progress Bar */}
            <div>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>완료: {progress.completed_levels} / {progress.total_levels} 레벨</span>
                <span className="font-mono">{progressPercent.toFixed(1)}%</span>
              </div>
              <div className="h-4 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className={`h-full transition-[width] duration-500 ease-linear ${
                    progress.status === 'error' ? 'bg-red-500' :
                    progress.status === 'completed' ? 'bg-green-500' :
                    'bg-gradient-to-r from-indigo-500 to-purple-500'
                  }`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-4 gap-2">
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">⏱️ 경과</div>
                <div className="text-sm font-medium text-white">{formatTime(progress.elapsed_ms)}</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">⏳ 남은 시간</div>
                <div className="text-sm font-medium text-white">{formatTime(progress.estimated_remaining_ms)}</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">📈 평균 속도</div>
                <div className="text-sm font-medium text-blue-300">{avgSpeed.toFixed(1)}/분</div>
              </div>
              <div className="p-2 bg-gray-700/50 rounded text-center">
                <div className="text-xs text-gray-400">📦 현재 세트</div>
                <div className="text-sm font-medium text-purple-300">{progress.current_set_index + 1}/{progress.total_sets}</div>
              </div>
            </div>

            {/* Set Progress Mini Bars */}
            <div>
              <div className="text-xs text-gray-400 mb-2">세트별 진행:</div>
              <div className="flex gap-1">
                {setProgresses.map((set) => (
                  <div key={set.index} className="flex-1">
                    <div
                      className={`h-6 rounded overflow-hidden ${
                        set.active ? 'ring-2 ring-indigo-400' : ''
                      }`}
                    >
                      <div
                        className={`h-full transition-all ${
                          set.completed ? 'bg-green-500' :
                          set.active ? 'bg-indigo-500' :
                          set.percent > 0 ? 'bg-indigo-700' : 'bg-gray-600'
                        }`}
                        style={{ width: set.completed ? '100%' : `${set.percent}%` }}
                      />
                    </div>
                    <div className={`text-[10px] text-center mt-0.5 ${
                      set.active ? 'text-indigo-300 font-medium' : 'text-gray-500'
                    }`}>
                      {set.index + 1}
                    </div>
                  </div>
                ))}
                {progress.total_sets > startSetIndex + SETS_TO_SHOW && (
                  <div className="text-xs text-gray-500 flex items-center ml-1">...</div>
                )}
              </div>
            </div>

            {/* Failed Levels Counter */}
            {progress.failed_levels && progress.failed_levels.length > 0 && (
              <div className="p-2 bg-red-900/20 border border-red-700/30 rounded-lg">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-red-300">
                    ⚠️ 실패 레벨: {progress.failed_levels.length}개
                  </span>
                  <span className="text-xs text-red-400">
                    (재생성 예정)
                  </span>
                </div>
              </div>
            )}

            {/* Error Message */}
            {progress.last_error && (
              <div className="p-2 bg-red-900/30 border border-red-700/30 rounded text-sm text-red-400">
                오류: {progress.last_error}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-2">
              {isGenerating && (
                <Button onClick={onCancel} variant="danger" className="flex-1">
                  ⏸️ 일시 정지
                </Button>
              )}
              {progress.status === 'paused' && (
                <Button onClick={() => onStart({ strategy: playtestStrategy })} className="flex-1">
                  ▶️ 계속 생성
                </Button>
              )}
              {progress.status === 'completed' && (
                <div className="w-full p-2 bg-green-900/30 border border-green-700/30 rounded text-center text-sm text-green-300">
                  ✅ 생성 완료! 테스트 탭으로 이동하세요.
                </div>
              )}
            </div>
          </div>
        );
      })()}
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

  // Sequential auto process state (test → regenerate if failed → repeat until pass)
  const [isSequentialProcessing, setIsSequentialProcessing] = useState(false);
  const [sequentialProgress, setSequentialProgress] = useState<{
    currentIndex: number;
    total: number;
    currentLevel: number;
    currentAttempt: number;
    maxAttempts: number;
    status: 'testing' | 'regenerating' | 'idle';
    results: { level_number: number; attempts: number; final_score: number; success: boolean }[];
  }>({ currentIndex: 0, total: 0, currentLevel: 0, currentAttempt: 0, maxAttempts: 5, status: 'idle', results: [] });
  const [selectedSequentialLevels, setSelectedSequentialLevels] = useState<Set<number>>(new Set());
  const sequentialAbortRef = useRef<AbortController | null>(null);

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

  // Sync selectedLevel with latest levels data (after regeneration, auto test save, etc.)
  useEffect(() => {
    if (selectedLevel) {
      const updated = levels.find(l => l.meta.level_number === selectedLevel.meta.level_number);
      if (updated && updated !== selectedLevel) {
        setSelectedLevel(updated);
      }
    }
  }, [levels]);

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

  // Sequential auto process: test → regenerate if failed → repeat until pass (70%+)
  const handleSequentialProcess = async (targetLevelNumbers: number[]) => {
    if (targetLevelNumbers.length === 0) {
      addNotification('info', '처리할 레벨이 없습니다.');
      return;
    }

    const MAX_ATTEMPTS = 5; // Maximum regeneration attempts per level
    const PASS_THRESHOLD = 70; // 70% match score to pass

    sequentialAbortRef.current = new AbortController();
    const signal = sequentialAbortRef.current.signal;

    setIsSequentialProcessing(true);
    setSequentialProgress({
      currentIndex: 0,
      total: targetLevelNumbers.length,
      currentLevel: targetLevelNumbers[0],
      currentAttempt: 0,
      maxAttempts: MAX_ATTEMPTS,
      status: 'testing',
      results: [],
    });

    const results: { level_number: number; attempts: number; final_score: number; success: boolean }[] = [];

    for (let i = 0; i < targetLevelNumbers.length; i++) {
      if (signal.aborted) break;

      const levelNumber = targetLevelNumbers[i];
      let currentLevel = levels.find(l => l.meta.level_number === levelNumber);
      if (!currentLevel) continue;

      let attempts = 0;
      let matchScore = 0;
      let passed = false;

      while (attempts < MAX_ATTEMPTS && !passed && !signal.aborted) {
        attempts++;

        // Update progress: testing
        setSequentialProgress(prev => ({
          ...prev,
          currentIndex: i,
          currentLevel: levelNumber,
          currentAttempt: attempts,
          status: 'testing',
        }));

        // Test the level
        try {
          const result = await analyzeAutoPlay(currentLevel.level_json, {
            iterations: autoTestIterations,
            targetDifficulty: currentLevel.meta.target_difficulty,
          });

          matchScore = calculateMatchScoreFromBots(result.bot_stats);

          // Save test result
          const botClearRates = {
            novice: result.bot_stats.find(s => s.profile === 'novice')?.clear_rate || 0,
            casual: result.bot_stats.find(s => s.profile === 'casual')?.clear_rate || 0,
            average: result.bot_stats.find(s => s.profile === 'average')?.clear_rate || 0,
            expert: result.bot_stats.find(s => s.profile === 'expert')?.clear_rate || 0,
            optimal: result.bot_stats.find(s => s.profile === 'optimal')?.clear_rate || 0,
          };

          await saveProductionLevels(batchId, [{
            meta: { ...currentLevel.meta, bot_clear_rates: botClearRates, match_score: matchScore },
            level_json: currentLevel.level_json,
          }]);

          // Update levels state
          setLevels(prev => prev.map(l =>
            l.meta.level_number === levelNumber
              ? { ...l, meta: { ...l.meta, match_score: matchScore, bot_clear_rates: botClearRates } }
              : l
          ));

          if (matchScore >= PASS_THRESHOLD) {
            passed = true;
          } else if (attempts < MAX_ATTEMPTS && !signal.aborted) {
            // Regenerate if not passed
            setSequentialProgress(prev => ({ ...prev, status: 'regenerating' }));

            // Use existing regeneration logic
            await handleRegenerateLevel(levelNumber);

            // Reload the level after regeneration from storage
            const reloadedLevels = await getProductionLevelsByBatch(batchId);
            currentLevel = reloadedLevels.find((l: ProductionLevel) => l.meta.level_number === levelNumber);
            if (!currentLevel) break;
          }
        } catch (err) {
          console.error(`Sequential process failed for level ${levelNumber}:`, err);
          break;
        }
      }

      results.push({ level_number: levelNumber, attempts, final_score: matchScore, success: passed });
      setSequentialProgress(prev => ({ ...prev, results: [...results] }));
    }

    setIsSequentialProcessing(false);
    setSequentialProgress(prev => ({ ...prev, status: 'idle' }));

    const successCount = results.filter(r => r.success).length;
    const failCount = results.filter(r => !r.success).length;
    addNotification(
      successCount > 0 ? 'success' : 'warning',
      `순차 처리 완료: ${successCount}개 통과, ${failCount}개 미통과`
    );

    loadLevels();
    onStatsUpdate();
  };

  const handleStopSequentialProcess = () => {
    sequentialAbortRef.current?.abort();
    addNotification('info', '순차 처리 중지됨');
  };

  // Calculate match score from bot stats (aligned with backend formula for consistency)
  // Uses asymmetric penalty: "too easy" (actual > target) gets 50% penalty, "too hard" gets full penalty
  const calculateMatchScoreFromBots = (botStats: { clear_rate: number; target_clear_rate: number }[]) => {
    if (!botStats.length) return 0;
    const gaps = botStats.map(s => {
      const rawGap = (s.clear_rate - s.target_clear_rate) * 100; // Positive = too easy
      // Asymmetric penalty: too easy = 50% penalty, too hard = full penalty
      return rawGap > 0 ? rawGap * 0.5 : Math.abs(rawGap);
    });
    const avgGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
    const maxGap = Math.max(...gaps);
    // Aligned with backend: avg_gap * 0.6 + max_gap * 0.4, penalty * 2
    const weightedGap = (avgGap * 0.6 + maxGap * 0.4);
    return Math.max(0, 100 - weightedGap * 2);
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
        filteredLevels = filteredLevels.filter(l => l.meta.match_score !== undefined && l.meta.match_score < 70);
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
    let completedCount = 0;

    // Process a single level's auto test
    const testOneLevel = async (level: typeof filteredLevels[0]) => {
      const result = await analyzeAutoPlay(level.level_json, {
        iterations: autoTestIterations,
        targetDifficulty: level.meta.target_difficulty,
      });

      const matchScore = calculateMatchScoreFromBots(result.bot_stats);

      const testResult = {
        level_number: level.meta.level_number,
        match_score: matchScore,
        grade: result.autoplay_grade,
        status: result.balance_status,
        target_difficulty: level.meta.target_difficulty,
        autoplay_score: result.autoplay_score,
        static_score: result.static_score,
      };

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

      return testResult;
    };

    // Execute in parallel batches of 10
    const TEST_CONCURRENCY = 10;
    for (let batchStart = 0; batchStart < filteredLevels.length; batchStart += TEST_CONCURRENCY) {
      if (signal.aborted) {
        setBatchTestProgress(prev => ({ ...prev, status: 'paused' }));
        break;
      }

      const batchSlice = filteredLevels.slice(batchStart, batchStart + TEST_CONCURRENCY);

      setBatchTestProgress(prev => ({
        ...prev,
        currentLevel: batchSlice[0].meta.level_number,
      }));

      const batchResults = await Promise.allSettled(
        batchSlice.map(level => testOneLevel(level))
      );

      // Collect successful results for this batch
      const batchSuccessResults: typeof results = [];
      for (let j = 0; j < batchResults.length; j++) {
        const r = batchResults[j];
        completedCount++;
        if (r.status === 'fulfilled') {
          results.push(r.value);
          batchSuccessResults.push(r.value);
        } else {
          console.error(`Auto test failed for level ${batchSlice[j].meta.level_number}:`, r.reason);
          failedLevels.push(batchSlice[j].meta.level_number);
        }
      }

      // Update levels state directly for immediate UI feedback
      if (batchSuccessResults.length > 0) {
        setLevels(prev => prev.map(level => {
          const result = batchSuccessResults.find(r => r.level_number === level.meta.level_number);
          if (result) {
            return {
              ...level,
              meta: {
                ...level.meta,
                match_score: result.match_score,
              },
            };
          }
          return level;
        }));
      }

      setBatchTestProgress(prev => ({
        ...prev,
        completed: completedCount,
        results: [...results],
        failedLevels: [...failedLevels],
      }));
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

  // 전체 자동 승인 상태
  const [isApprovingAll, setIsApprovingAll] = useState(false);
  const [approveAllProgress, setApproveAllProgress] = useState({ current: 0, total: 0 });

  // 전체 자동 승인 - 모든 generated 상태 레벨을 approved로 변경
  const handleApproveAllLevels = async () => {
    // 전체 레벨 로드 (generated 상태)
    const allLevels = await getProductionLevelsByBatch(batchId);
    const generatedLevels = allLevels.filter(l => l.meta.status === 'generated');

    if (generatedLevels.length === 0) {
      addNotification('info', '승인할 레벨이 없습니다');
      return;
    }

    setIsApprovingAll(true);
    setApproveAllProgress({ current: 0, total: generatedLevels.length });

    try {
      for (let i = 0; i < generatedLevels.length; i++) {
        await approveLevel(batchId, generatedLevels[i].meta.level_number, '자동승인(테스트완료)');
        setApproveAllProgress({ current: i + 1, total: generatedLevels.length });
      }

      addNotification('success', `${generatedLevels.length}개 레벨 자동 승인 완료 → 익스포트 탭에서 내보내기 가능`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Auto approve failed:', err);
      addNotification('error', '자동 승인 중 오류 발생');
    } finally {
      setIsApprovingAll(false);
    }
  };

  // Regeneration state
  const [regeneratingLevels, setRegeneratingLevels] = useState<Set<number>>(new Set());
  const [enhancingLevels, setEnhancingLevels] = useState<Set<number>>(new Set());
  const [isBatchRegenerating, setIsBatchRegenerating] = useState(false);
  const [regenerationThreshold, setRegenerationThreshold] = useState(70);
  const [selectedRegenLevels, setSelectedRegenLevels] = useState<Set<number>>(new Set());

  // Per-level regeneration progress tracking
  const [regenProgressMap, setRegenProgressMap] = useState<Map<number, {
    status: 'waiting' | 'generating' | 'saving' | 'done' | 'failed';
    matchScore?: number;
    error?: string;
  }>>(new Map());
  const [batchRegenTotal, setBatchRegenTotal] = useState(0);

  // Regenerate single level - pure generation without bot simulation
  // 봇 시뮬레이션 없이 목표 난이도에 근접한 레벨만 생성, match_score는 일괄 테스트에서 측정
  const handleRegenerateLevel = async (levelNumber: number) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level) return;

    setRegeneratingLevels(prev => new Set([...prev, levelNumber]));
    setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'generating' }));

    try {
      // Get current batch for gimmick unlock levels
      const currentBatch = await getProductionBatch(batchId);
      if (!currentBatch) {
        throw new Error('Batch not found');
      }

      const targetDifficulty = level.meta.target_difficulty;
      const targetScore = targetDifficulty * 100;
      const gimmickIntensity = Math.min(1, levelNumber / 500);
      const DIFFICULTY_TOLERANCE = 10.0; // 0.10 in 0-1 scale = 10.0 in 0-100 scale (허용 오차 증가)
      const CANDIDATES_PER_ATTEMPT = 3;
      const MAX_ATTEMPTS = 5; // 최대 15개 후보

      // === 미형 로직: 프로덕션 초기 생성과 동일한 레벨 타입 기반 패턴 선택 ===
      const isEarlyLevel = levelNumber <= 30;
      const isSpecialShape = levelNumber % 10 === 9;
      const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

      // Pattern type selection (프로덕션과 동일)
      const patternRoll = Math.random();
      let patternType: 'aesthetic' | 'geometric' | 'clustered';
      if (isEarlyLevel) {
        patternType = patternRoll < 0.50 ? 'geometric' : patternRoll < 0.90 ? 'aesthetic' : 'clustered';
      } else if (isBossLevel) {
        patternType = patternRoll < 0.75 ? 'aesthetic' : patternRoll < 0.95 ? 'geometric' : 'clustered';
      } else if (isSpecialShape) {
        patternType = patternRoll < 0.50 ? 'aesthetic' : patternRoll < 0.75 ? 'geometric' : 'clustered';
      } else {
        patternType = patternRoll < 0.60 ? 'aesthetic' : patternRoll < 0.85 ? 'geometric' : 'clustered';
      }

      // Symmetry mode selection (프로덕션과 동일)
      const symmetryRoll = Math.random();
      let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
      if (isEarlyLevel) {
        symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
      } else if (isSpecialShape) {
        symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
      } else if (isBossLevel) {
        symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
      } else {
        symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
      }

      // Pattern index for boss/special levels
      let patternIndex: number | undefined = undefined;
      if (patternType === 'aesthetic') {
        if (isBossLevel) {
          const bossPatterns = [8, 15, 16, 45, 46, 17, 18];
          patternIndex = bossPatterns[Math.floor(Math.random() * bossPatterns.length)];
        } else if (isSpecialShape) {
          const specialPatterns = [3, 4, 20, 23, 24, 30, 33];
          patternIndex = specialPatterns[Math.floor(Math.random() * specialPatterns.length)];
        }
      }

      // Grid size (프로덕션과 동일)
      let gridSize: [number, number] = [7, 7];
      if (isBossLevel && targetDifficulty > 0.3) {
        gridSize = [8, 8];
      } else if (!isEarlyLevel && Math.random() < 0.3) {
        gridSize = [8, 8];
      }

      // Layers (프로덕션과 동일)
      let minLayers = 2;
      let maxLayers = Math.min(7, 3 + Math.floor(targetDifficulty * 4));
      if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
      else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(7, 4 + Math.floor(targetDifficulty * 3)); }

      let bestResult: GenerationResult | null = null;
      let bestGap = Infinity;

      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        const candidates = await Promise.all(
          Array.from({ length: CANDIDATES_PER_ATTEMPT }, () => {
            // 미형 파라미터는 고정, goal direction/type만 랜덤
            const goalDirection = (['s', 'n', 'e', 'w'] as const)[Math.floor(Math.random() * 4)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

            return generateLevel(
              {
                target_difficulty: targetDifficulty,
                grid_size: gridSize,
                min_layers: minLayers,
                max_layers: maxLayers,
                tile_types: undefined, // 백엔드에서 level_number 기반 자동 선택
                obstacle_types: [],
                goals: [{
                  type: goalType,
                  direction: goalDirection,
                  count: Math.max(2, Math.floor(3 + targetDifficulty * 2))
                }],
                symmetry_mode: symmetryMode,
                pattern_type: patternType,
                pattern_index: patternIndex,
              },
              {
                auto_select_gimmicks: true,
                available_gimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
                gimmick_intensity: gimmickIntensity,
                gimmick_unlock_levels: currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
                level_number: levelNumber,
              }
            ).catch(() => null);
          })
        );

        for (const c of candidates) {
          if (!c) continue;
          const gap = Math.abs(c.actual_difficulty - targetScore);
          if (gap < bestGap) {
            bestGap = gap;
            bestResult = c;
          }
        }

        if (bestGap <= DIFFICULTY_TOLERANCE) break; // 허용 오차 이내 → 즉시 채택
      }

      if (!bestResult) {
        throw new Error(`${MAX_ATTEMPTS * CANDIDATES_PER_ATTEMPT}개 후보 모두 실패`);
      }
      const result = bestResult;

      // Save regenerated level - match_score/bot_clear_rates는 비워둠 (일괄 테스트에서 측정)
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'saving' }));
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          actual_difficulty: result.actual_difficulty,
          grade: result.grade as any,
          bot_clear_rates: undefined,
          match_score: undefined,
          status_updated_at: new Date().toISOString(),
          regen_attempts: (level.meta.regen_attempts || 0) + 1,
          regen_lower_bound: undefined,
          regen_upper_bound: undefined,
        },
        level_json: result.level_json,
      }]);

      // Update batch test results if exists (remove regenerated level from results - needs re-test)
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.filter(r => r.level_number !== levelNumber),
      }));

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'done' }));
      addNotification('success', `레벨 ${levelNumber} 재생성 완료 (정적 난이도: ${result.actual_difficulty.toFixed(1)})`);
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(`Regeneration failed for level ${levelNumber}:`, errMsg, err);
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'failed', error: errMsg }));
      addNotification('error', `레벨 ${levelNumber} 재생성 실패: ${errMsg}`);
    } finally {
      setRegeneratingLevels(prev => {
        const newSet = new Set(prev);
        newSet.delete(levelNumber);
        return newSet;
      });
    }
  };

  // Enhance existing level (incremental difficulty adjustment instead of full regeneration)
  const handleEnhanceLevel = async (levelNumber: number) => {
    const level = levels.find(l => l.meta.level_number === levelNumber);
    if (!level || !level.level_json) return;

    setEnhancingLevels(prev => new Set([...prev, levelNumber]));

    try {
      const result = await enhanceLevel({
        level_json: level.level_json,
        target_difficulty: level.meta.target_difficulty,
        max_iterations: 5,
        simulation_iterations: 50,
      });

      // Calculate match score for meta update
      const matchScore = result.match_score;

      // Save enhanced level
      const botRates = result.bot_clear_rates as { novice: number; casual: number; average: number; expert: number; optimal: number };
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          bot_clear_rates: botRates,
          match_score: matchScore,
          status_updated_at: new Date().toISOString(),
        },
        level_json: result.level_json,
      }]);

      // Update batch test results if exists
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.map(r =>
          r.level_number === levelNumber
            ? { ...r, match_score: matchScore }
            : r
        ),
      }));

      const modsText = result.modifications.length > 0
        ? result.modifications.join(', ')
        : '변경 없음';
      addNotification(
        result.enhanced ? 'success' : 'info',
        `레벨 ${levelNumber} 개선 ${result.enhanced ? '완료' : '미개선'}: ${modsText} (일치도: ${matchScore.toFixed(0)}%)`
      );
      loadLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Enhancement failed:', err);
      addNotification('error', `레벨 ${levelNumber} 개선 실패`);
    } finally {
      setEnhancingLevels(prev => {
        const newSet = new Set(prev);
        newSet.delete(levelNumber);
        return newSet;
      });
    }
  };

  // === 일괄 재생성 공통 로직 (프로덕션 초기 생성과 동일한 고속 패턴) ===
  // batch 조회 1회, generateLevel 직접 호출, 저장은 배치 단위로 묶어서 처리
  const batchRegenerateCore = async (targetLevelNumbers: number[]) => {
    if (targetLevelNumbers.length === 0) return;

    // 1. batch 정보 1회만 조회
    const currentBatch = await getProductionBatch(batchId);
    if (!currentBatch) {
      addNotification('error', 'Batch not found');
      return;
    }
    const gimmickUnlockLevels = currentBatch.gimmick_unlock_levels || PROFESSIONAL_GIMMICK_UNLOCK_LEVELS;

    // 2. Initialize progress tracking
    const initMap = new Map<number, { status: 'waiting' | 'generating' | 'saving' | 'done' | 'failed'; matchScore?: number; error?: string }>();
    targetLevelNumbers.forEach(n => initMap.set(n, { status: 'waiting' }));
    setRegenProgressMap(initMap);
    setBatchRegenTotal(targetLevelNumbers.length);
    setIsBatchRegenerating(true);

    let successCount = 0;
    let failCount = 0;
    const REGEN_CONCURRENCY = 20; // 동시성 증가로 속도 개선

    // 3. 레벨 1개 재생성: 반복 생성으로 오차 0.10 이내 달성
    const DIFFICULTY_TOLERANCE = 10.0; // 0.10 in 0-1 scale = 10.0 in 0-100 scale (허용 오차 증가)
    const CANDIDATES_PER_ATTEMPT = 3;
    const MAX_ATTEMPTS = 5; // 최대 15개 후보

    const regenerateOne = async (levelNumber: number): Promise<void> => {
      const level = levels.find(l => l.meta.level_number === levelNumber);
      if (!level) throw new Error(`Level ${levelNumber} not found`);

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'generating' }));

      const targetDifficulty = level.meta.target_difficulty;
      const targetScore = targetDifficulty * 100;
      const gimmickIntensity = Math.min(1, levelNumber / 500);

      // === 미형 로직: 프로덕션 초기 생성과 동일한 레벨 타입 기반 패턴 선택 ===
      const isEarlyLevel = levelNumber <= 30;
      const isSpecialShape = levelNumber % 10 === 9;
      const isBossLevel = levelNumber % 10 === 0 && levelNumber > 0;

      // Pattern type selection (프로덕션과 동일)
      const patternRoll = Math.random();
      let patternType: 'aesthetic' | 'geometric' | 'clustered';
      if (isEarlyLevel) {
        patternType = patternRoll < 0.50 ? 'geometric' : patternRoll < 0.90 ? 'aesthetic' : 'clustered';
      } else if (isBossLevel) {
        patternType = patternRoll < 0.75 ? 'aesthetic' : patternRoll < 0.95 ? 'geometric' : 'clustered';
      } else if (isSpecialShape) {
        patternType = patternRoll < 0.50 ? 'aesthetic' : patternRoll < 0.75 ? 'geometric' : 'clustered';
      } else {
        patternType = patternRoll < 0.60 ? 'aesthetic' : patternRoll < 0.85 ? 'geometric' : 'clustered';
      }

      // Symmetry mode selection (프로덕션과 동일)
      const symmetryRoll = Math.random();
      let symmetryMode: 'none' | 'horizontal' | 'vertical' | 'both';
      if (isEarlyLevel) {
        symmetryMode = symmetryRoll < 0.25 ? 'horizontal' : symmetryRoll < 0.50 ? 'vertical' : 'both';
      } else if (isSpecialShape) {
        symmetryMode = symmetryRoll < 0.30 ? 'none' : symmetryRoll < 0.65 ? 'horizontal' : 'vertical';
      } else if (isBossLevel) {
        symmetryMode = symmetryRoll < 0.20 ? 'horizontal' : symmetryRoll < 0.40 ? 'vertical' : 'both';
      } else {
        symmetryMode = symmetryRoll < 0.05 ? 'none' : symmetryRoll < 0.40 ? 'horizontal' : symmetryRoll < 0.75 ? 'vertical' : 'both';
      }

      // Pattern index for boss/special levels
      let patternIndex: number | undefined = undefined;
      if (patternType === 'aesthetic') {
        if (isBossLevel) {
          const bossPatterns = [8, 15, 16, 45, 46, 17, 18];
          patternIndex = bossPatterns[Math.floor(Math.random() * bossPatterns.length)];
        } else if (isSpecialShape) {
          const specialPatterns = [3, 4, 20, 23, 24, 30, 33];
          patternIndex = specialPatterns[Math.floor(Math.random() * specialPatterns.length)];
        }
      }

      // Grid size (프로덕션과 동일)
      let gridSize: [number, number] = [7, 7];
      if (isBossLevel && targetDifficulty > 0.3) {
        gridSize = [8, 8];
      } else if (!isEarlyLevel && Math.random() < 0.3) {
        gridSize = [8, 8];
      }

      // Layers (프로덕션과 동일)
      let minLayers = 2;
      let maxLayers = Math.min(7, 3 + Math.floor(targetDifficulty * 4));
      if (isEarlyLevel) { minLayers = 2; maxLayers = Math.min(4, maxLayers); }
      else if (isBossLevel) { minLayers = Math.max(3, Math.floor(2 + targetDifficulty * 2)); maxLayers = Math.min(7, 4 + Math.floor(targetDifficulty * 3)); }

      let bestResult: GenerationResult | null = null;
      let bestGap = Infinity;

      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        const candidates = await Promise.all(
          Array.from({ length: CANDIDATES_PER_ATTEMPT }, () => {
            // 미형 파라미터는 고정, goal direction/type만 랜덤
            const goalDirection = (['s', 'n', 'e', 'w'] as const)[Math.floor(Math.random() * 4)];
            const goalType = (['craft', 'stack'] as const)[Math.floor(Math.random() * 2)];

            return generateLevel(
              {
                target_difficulty: targetDifficulty,
                grid_size: gridSize,
                min_layers: minLayers,
                max_layers: maxLayers,
                tile_types: undefined, // 백엔드에서 level_number 기반 자동 선택
                obstacle_types: [],
                goals: [{ type: goalType, direction: goalDirection, count: Math.max(2, Math.floor(3 + targetDifficulty * 2)) }],
                symmetry_mode: symmetryMode,
                pattern_type: patternType,
                pattern_index: patternIndex,
              },
              {
                auto_select_gimmicks: true,
                available_gimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],
                gimmick_intensity: gimmickIntensity,
                gimmick_unlock_levels: gimmickUnlockLevels,
                level_number: levelNumber,
              }
            ).catch(() => null);
          })
        );

        for (const c of candidates) {
          if (!c) continue;
          const gap = Math.abs(c.actual_difficulty - targetScore);
          if (gap < bestGap) {
            bestGap = gap;
            bestResult = c;
          }
        }

        if (bestGap <= DIFFICULTY_TOLERANCE) break; // 허용 오차 이내 → 즉시 채택
      }

      if (!bestResult) throw new Error(`${MAX_ATTEMPTS * CANDIDATES_PER_ATTEMPT}개 후보 모두 실패`);

      // Save - match_score/bot_clear_rates는 비워둠 (일괄 테스트에서 측정)
      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'saving' }));
      await saveProductionLevels(batchId, [{
        meta: {
          ...level.meta,
          generated_at: new Date().toISOString(),
          actual_difficulty: bestResult.actual_difficulty,
          grade: bestResult.grade as any,
          bot_clear_rates: undefined,
          match_score: undefined,
          status_updated_at: new Date().toISOString(),
          regen_attempts: (level.meta.regen_attempts || 0) + 1,
          regen_lower_bound: undefined,
          regen_upper_bound: undefined,
        },
        level_json: bestResult.level_json,
      }]);

      setRegenProgressMap(prev => new Map(prev).set(levelNumber, { status: 'done' }));
    };

    // 4. Execute in parallel batches (프로덕션 초기 생성과 동일한 패턴)
    for (let batchStart = 0; batchStart < targetLevelNumbers.length; batchStart += REGEN_CONCURRENCY) {
      const batchSlice = targetLevelNumbers.slice(batchStart, batchStart + REGEN_CONCURRENCY);
      const results = await Promise.allSettled(
        batchSlice.map(num => regenerateOne(num))
      );
      for (const r of results) {
        if (r.status === 'fulfilled') successCount++;
        else {
          failCount++;
          const reason = r.reason instanceof Error ? r.reason.message : String(r.reason);
          const failedNum = batchSlice[results.indexOf(r)];
          setRegenProgressMap(prev => new Map(prev).set(failedNum, { status: 'failed', error: reason }));
        }
      }
    }

    // 5. 완료 후 1회만 리로드
    setIsBatchRegenerating(false);
    loadLevels();
    onStatsUpdate();
    return { successCount, failCount };
  };

  // Batch regenerate low match score levels from test results
  const handleBatchRegenerate = async () => {
    const lowMatchLevels = batchTestProgress.results
      .filter(r => r.match_score < regenerationThreshold)
      .sort((a, b) => a.match_score - b.match_score);
    if (lowMatchLevels.length === 0) {
      addNotification('info', `일치도 ${regenerationThreshold}% 미만 레벨이 없습니다.`);
      return;
    }
    const levelNumbers = lowMatchLevels.map(l => l.level_number);
    const result = await batchRegenerateCore(levelNumbers);
    if (result) {
      // Remove regenerated levels from results (needs re-test)
      setBatchTestProgress(prev => ({
        ...prev,
        results: prev.results.filter(r => !levelNumbers.includes(r.level_number)),
      }));
      addNotification('success', `일괄 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
    }
  };

  // Batch regenerate low match score levels from stored level data
  const handleBatchRegenerateFromStored = async () => {
    const storedLowMatch = levels
      .filter(l => l.meta.match_score !== undefined && l.meta.match_score > 0 && l.meta.match_score < regenerationThreshold)
      .sort((a, b) => (a.meta.match_score || 0) - (b.meta.match_score || 0));
    if (storedLowMatch.length === 0) {
      addNotification('info', `저장된 일치도 ${regenerationThreshold}% 미만 레벨이 없습니다.`);
      return;
    }
    const result = await batchRegenerateCore(storedLowMatch.map(l => l.meta.level_number));
    if (result) addNotification('success', `저장된 미달 레벨 일괄 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
  };

  // Batch regenerate selected levels only
  const handleRegenerateSelected = async () => {
    if (selectedRegenLevels.size === 0) {
      addNotification('info', '선택된 레벨이 없습니다.');
      return;
    }
    const targetLevels = [...selectedRegenLevels].sort((a, b) => {
      const aScore = levels.find(l => l.meta.level_number === a)?.meta.match_score || 0;
      const bScore = levels.find(l => l.meta.level_number === b)?.meta.match_score || 0;
      return aScore - bScore;
    });
    const result = await batchRegenerateCore(targetLevels);
    if (result) {
      setSelectedRegenLevels(new Set());
      addNotification('success', `선택 레벨 재생성 완료: ${result.successCount}개 성공, ${result.failCount}개 실패`);
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

      {/* Sequential Auto Process Panel - auto_single mode */}
      {testMode === 'auto_single' && (() => {
        const untestedLevels = levels.filter(l => !l.meta.match_score || l.meta.match_score === 0);
        const failedLevels = levels.filter(l => l.meta.match_score !== undefined && l.meta.match_score > 0 && l.meta.match_score < 70);
        const targetLevels = [...untestedLevels, ...failedLevels].sort((a, b) => a.meta.level_number - b.meta.level_number);
        const allSelected = targetLevels.length > 0 && targetLevels.every(l => selectedSequentialLevels.has(l.meta.level_number));

        return targetLevels.length > 0 || isSequentialProcessing ? (
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">🔄 순차 자동 처리</h3>
              <span className="text-xs text-gray-400">
                미측정: <span className="text-blue-400 font-medium">{untestedLevels.length}개</span>
                {' / '}미달: <span className="text-orange-400 font-medium">{failedLevels.length}개</span>
              </span>
            </div>

            <p className="text-xs text-gray-500">
              테스트 → 미달(70% 미만)시 재생성 → 재테스트 반복 (최대 5회)
            </p>

            {/* Progress Display */}
            {isSequentialProcessing && (
              <div className="bg-gray-900/60 border border-gray-600 rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-gray-300 font-medium">
                    Lv.{sequentialProgress.currentLevel} {sequentialProgress.status === 'testing' ? '테스트 중' : '재생성 중'}
                    {' '}(시도 {sequentialProgress.currentAttempt}/{sequentialProgress.maxAttempts})
                  </span>
                  <span className="text-gray-400">
                    {sequentialProgress.currentIndex + 1} / {sequentialProgress.total}
                  </span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all ${sequentialProgress.status === 'testing' ? 'bg-blue-500' : 'bg-orange-500'}`}
                    style={{ width: `${((sequentialProgress.currentIndex + 1) / sequentialProgress.total) * 100}%` }}
                  />
                </div>
                {sequentialProgress.results.length > 0 && (
                  <div className="flex gap-2 text-xs">
                    <span className="text-green-400">✓ 통과: {sequentialProgress.results.filter(r => r.success).length}</span>
                    <span className="text-red-400">✗ 실패: {sequentialProgress.results.filter(r => !r.success).length}</span>
                  </div>
                )}
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center gap-2">
              {isSequentialProcessing ? (
                <Button onClick={handleStopSequentialProcess} variant="danger" size="sm" className="flex-1">
                  ⏹️ 중지
                </Button>
              ) : (
                <>
                  <Button
                    onClick={() => handleSequentialProcess(targetLevels.map(l => l.meta.level_number))}
                    disabled={targetLevels.length === 0}
                    size="sm"
                    className="flex-1 bg-blue-600 hover:bg-blue-500"
                  >
                    🚀 전체 {targetLevels.length}개 순차 처리
                  </Button>
                  <Button
                    onClick={() => handleSequentialProcess([...selectedSequentialLevels])}
                    disabled={selectedSequentialLevels.size === 0}
                    size="sm"
                    className={`flex-1 ${selectedSequentialLevels.size > 0 ? 'bg-indigo-600 hover:bg-indigo-500' : 'bg-gray-600'}`}
                  >
                    🎯 선택 {selectedSequentialLevels.size}개 처리
                  </Button>
                </>
              )}
            </div>

            {/* Level Selection List */}
            {!isSequentialProcessing && targetLevels.length > 0 && (
              <div className="border border-gray-700 rounded-lg overflow-hidden">
                <div className="flex items-center px-3 py-2 bg-gray-700/50 text-xs text-gray-400">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedSequentialLevels(new Set(targetLevels.map(l => l.meta.level_number)));
                        } else {
                          setSelectedSequentialLevels(new Set());
                        }
                      }}
                      className="w-3 h-3"
                    />
                    전체 선택
                  </label>
                  <span className="ml-auto">레벨</span>
                  <span className="w-14 text-center">일치도</span>
                  <span className="w-12 text-center">등급</span>
                </div>
                <div className="max-h-[150px] overflow-y-auto">
                  {targetLevels.slice(0, 50).map(level => {
                    const isUntested = !level.meta.match_score || level.meta.match_score === 0;
                    return (
                      <label
                        key={level.meta.level_number}
                        className="flex items-center px-3 py-1.5 hover:bg-gray-700/30 cursor-pointer text-xs"
                      >
                        <input
                          type="checkbox"
                          checked={selectedSequentialLevels.has(level.meta.level_number)}
                          onChange={(e) => {
                            setSelectedSequentialLevels(prev => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(level.meta.level_number);
                              else next.delete(level.meta.level_number);
                              return next;
                            });
                          }}
                          className="w-3 h-3"
                        />
                        <span className="ml-2 flex-1 text-gray-300">Lv.{level.meta.level_number}</span>
                        <span className={`w-14 text-center font-medium ${
                          isUntested ? 'text-gray-500' :
                          (level.meta.match_score || 0) >= 70 ? 'text-green-400' : 'text-red-400'
                        }`}>
                          {isUntested ? '미측정' : `${level.meta.match_score?.toFixed(0)}%`}
                        </span>
                        <span className={`w-12 text-center font-bold ${
                          level.meta.grade === 'S' ? 'text-green-400' :
                          level.meta.grade === 'A' ? 'text-blue-400' :
                          level.meta.grade === 'B' ? 'text-yellow-400' :
                          level.meta.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                        }`}>{level.meta.grade}</span>
                      </label>
                    );
                  })}
                  {targetLevels.length > 50 && (
                    <div className="px-3 py-2 text-xs text-gray-500 text-center">
                      ...외 {targetLevels.length - 50}개 더
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Results Summary */}
            {!isSequentialProcessing && sequentialProgress.results.length > 0 && (
              <div className="border border-gray-700 rounded-lg p-3 space-y-2">
                <div className="text-xs text-gray-400">최근 처리 결과</div>
                <div className="max-h-[100px] overflow-y-auto space-y-1">
                  {sequentialProgress.results.slice(-10).map(r => (
                    <div key={r.level_number} className={`flex items-center justify-between text-xs px-2 py-1 rounded ${
                      r.success ? 'bg-green-900/30' : 'bg-red-900/30'
                    }`}>
                      <span className="text-gray-300">Lv.{r.level_number}</span>
                      <span className={r.success ? 'text-green-400' : 'text-red-400'}>
                        {r.final_score.toFixed(0)}% ({r.attempts}회 시도)
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null;
      })()}

      {/* Stored Low-Match Levels Regeneration */}
      {testMode === 'auto_batch' && (() => {
        const storedTestedLevels = levels.filter(l => l.meta.match_score !== undefined && l.meta.match_score > 0);
        const storedLowMatch = storedTestedLevels
          .filter(l => (l.meta.match_score || 0) < regenerationThreshold)
          .sort((a, b) => (a.meta.match_score || 0) - (b.meta.match_score || 0));
        const allSelected = storedLowMatch.length > 0 && storedLowMatch.every(l => selectedRegenLevels.has(l.meta.level_number));
        return storedTestedLevels.length > 0 ? (
          <div className="bg-gray-800 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-white">미달 레벨 재생성</h3>
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">
                  테스트 완료: {storedTestedLevels.length}개 / 미달: <span className={storedLowMatch.length > 0 ? 'text-orange-400 font-medium' : 'text-green-400'}>{storedLowMatch.length}개</span>
                </span>
                <select
                  value={regenerationThreshold}
                  onChange={(e) => { setRegenerationThreshold(Number(e.target.value)); setSelectedRegenLevels(new Set()); }}
                  className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-xs"
                  disabled={isBatchRegenerating}
                >
                  <option value={50}>50% 미만</option>
                  <option value={60}>60% 미만</option>
                  <option value={70}>70% 미만</option>
                  <option value={80}>80% 미만</option>
                </select>
              </div>
            </div>

            {/* Action Buttons */}
            {storedLowMatch.length > 0 && (
              <div className="flex items-center gap-2">
                <Button
                  onClick={handleBatchRegenerateFromStored}
                  disabled={isBatchRegenerating}
                  variant="danger"
                  size="sm"
                  className="flex-1"
                >
                  {isBatchRegenerating ? (
                    <><span className="animate-spin mr-1">⟳</span>재생성 중...</>
                  ) : (
                    `🔄 전체 ${storedLowMatch.length}개 일괄 재생성`
                  )}
                </Button>
                <Button
                  onClick={handleRegenerateSelected}
                  disabled={isBatchRegenerating || selectedRegenLevels.size === 0}
                  size="sm"
                  className={`flex-1 ${selectedRegenLevels.size > 0 ? 'bg-orange-600 hover:bg-orange-500' : 'bg-gray-600'}`}
                >
                  {isBatchRegenerating ? (
                    <><span className="animate-spin mr-1">⟳</span>재생성 중...</>
                  ) : (
                    `🎯 선택 ${selectedRegenLevels.size}개만 재생성`
                  )}
                </Button>
              </div>
            )}

            {/* Batch Regeneration Progress */}
            {/* Batch Regeneration Progress - show during and after batch regen */}
            {(isBatchRegenerating || regenProgressMap.size > 0) && batchRegenTotal > 0 && (() => {
              const entries = [...regenProgressMap.values()];
              const doneCount = entries.filter(p => p.status === 'done').length;
              const failCount = entries.filter(p => p.status === 'failed').length;
              const completedCount = doneCount + failCount;
              const generatingCount = entries.filter(p => p.status === 'generating').length;
              const savingCount = entries.filter(p => p.status === 'saving').length;
              const waitingCount = entries.filter(p => p.status === 'waiting').length;
              const progressPct = (completedCount / batchRegenTotal) * 100;
              const isFinished = !isBatchRegenerating && completedCount === batchRegenTotal;
              return (
                <div className={`border rounded-lg p-3 space-y-2 ${isFinished ? 'bg-gray-800/80 border-gray-600' : 'bg-gray-900/60 border-gray-600'}`}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-300 font-medium">
                      {isFinished ? '재생성 완료' : '재생성 진행도'}
                    </span>
                    <div className="flex items-center gap-2">
                      <span className="text-gray-400">
                        <span className="text-green-400 font-bold">{doneCount}</span>
                        {failCount > 0 && <> + <span className="text-red-400 font-bold">{failCount}</span></>}
                        <span className="text-gray-500"> / {batchRegenTotal}</span>
                      </span>
                      {isFinished && (
                        <button
                          onClick={() => { setRegenProgressMap(new Map()); setBatchRegenTotal(0); }}
                          className="text-gray-500 hover:text-gray-300 text-xs px-1"
                          title="닫기"
                        >✕</button>
                      )}
                    </div>
                  </div>
                  {/* Progress bar */}
                  <div className="w-full h-2 bg-gray-700 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-300 ease-out"
                      style={{
                        width: `${progressPct}%`,
                        background: failCount > 0
                          ? `linear-gradient(90deg, #22c55e ${completedCount > 0 ? (doneCount / completedCount) * 100 : 0}%, #ef4444 ${completedCount > 0 ? (doneCount / completedCount) * 100 : 0}%)`
                          : '#22c55e',
                      }}
                    />
                  </div>
                  {/* Status summary */}
                  <div className="flex items-center gap-3 text-xs text-gray-400 flex-wrap">
                    {isBatchRegenerating && (
                      <>
                        {generatingCount > 0 && <span className="flex items-center gap-1"><span className="animate-spin text-blue-400">⟳</span> 생성 {generatingCount}</span>}
                        {savingCount > 0 && <span className="flex items-center gap-1"><span className="animate-spin text-purple-400">⟳</span> 저장 {savingCount}</span>}
                        {waitingCount > 0 && <span className="text-gray-500">대기 {waitingCount}</span>}
                      </>
                    )}
                    {doneCount > 0 && (
                      <span className="text-green-400">완료 {doneCount}</span>
                    )}
                    {failCount > 0 && <span className="text-red-400">에러 {failCount}</span>}
                  </div>
                  {/* Show first error message for debugging */}
                  {failCount > 0 && (() => {
                    const firstError = entries.find(p => p.status === 'failed' && p.error);
                    return firstError?.error ? (
                      <div className="text-xs text-red-400/80 bg-red-900/20 rounded px-2 py-1 truncate" title={firstError.error}>
                        {firstError.error}
                      </div>
                    ) : null;
                  })()}
                </div>
              );
            })()}

            {/* Selectable Level List */}
            {storedLowMatch.length > 0 && (
              <div className="border border-gray-700 rounded-lg overflow-hidden">
                {/* Header with Select All */}
                <div className="flex items-center gap-2 px-3 py-2 bg-gray-700/60 border-b border-gray-600 text-xs">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => {
                      if (allSelected) {
                        setSelectedRegenLevels(new Set());
                      } else {
                        setSelectedRegenLevels(new Set(storedLowMatch.map(l => l.meta.level_number)));
                      }
                    }}
                    className="rounded border-gray-500 accent-orange-500"
                    disabled={isBatchRegenerating}
                  />
                  <span className="text-gray-400 flex-1">전체 선택</span>
                  <span className="w-12 text-center text-gray-500">레벨</span>
                  <span className="w-14 text-center text-gray-500">일치도</span>
                  <span className="w-14 text-center text-gray-500">등급</span>
                  <span className="w-14 text-center text-gray-500">목표</span>
                  {isBatchRegenerating && <span className="w-16 text-center text-gray-500">상태</span>}
                </div>
                {/* Scrollable List */}
                <div className="max-h-[200px] overflow-y-auto">
                  {storedLowMatch.map(level => {
                    const score = level.meta.match_score || 0;
                    const isSelected = selectedRegenLevels.has(level.meta.level_number);
                    const isRegen = regeneratingLevels.has(level.meta.level_number);
                    const levelProgress = regenProgressMap.get(level.meta.level_number);
                    const progressStatus = levelProgress?.status;
                    const isDone = progressStatus === 'done';
                    const isFailed = progressStatus === 'failed';
                    return (
                      <label
                        key={level.meta.level_number}
                        className={`flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer transition-colors ${
                          isDone ? 'bg-green-900/20' : isFailed ? 'bg-red-900/20' :
                          isSelected ? 'bg-orange-900/30' : 'hover:bg-gray-700/40'
                        } ${isRegen ? 'opacity-70' : ''}`}
                      >
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => {
                            setSelectedRegenLevels(prev => {
                              const next = new Set(prev);
                              if (next.has(level.meta.level_number)) next.delete(level.meta.level_number);
                              else next.add(level.meta.level_number);
                              return next;
                            });
                          }}
                          className="rounded border-gray-500 accent-orange-500"
                          disabled={isBatchRegenerating || isRegen}
                        />
                        <span className="flex-1 text-gray-300">
                        </span>
                        <span className="w-12 text-center text-gray-300 font-medium">Lv.{level.meta.level_number}</span>
                        <span className={`w-14 text-center font-bold ${
                          isDone && levelProgress?.matchScore !== undefined
                            ? (levelProgress.matchScore >= regenerationThreshold ? 'text-green-400' : 'text-yellow-400')
                            : score >= 50 ? 'text-yellow-400' : 'text-red-400'
                        }`}>
                          {isDone && levelProgress?.matchScore !== undefined
                            ? `${levelProgress.matchScore.toFixed(0)}%`
                            : `${score.toFixed(0)}%`
                          }
                        </span>
                        <span className={`w-14 text-center font-bold ${
                          level.meta.grade === 'S' ? 'text-green-400' :
                          level.meta.grade === 'A' ? 'text-blue-400' :
                          level.meta.grade === 'B' ? 'text-yellow-400' :
                          level.meta.grade === 'C' ? 'text-orange-400' : 'text-red-400'
                        }`}>{level.meta.grade}</span>
                        <span className="w-14 text-center text-gray-400">{(level.meta.target_difficulty * 100).toFixed(0)}%</span>
                        {isBatchRegenerating && (
                          <span className={`w-16 text-center font-medium ${
                            progressStatus === 'generating' ? 'text-blue-400' :
                            progressStatus === 'saving' ? 'text-purple-400' :
                            progressStatus === 'done' ? 'text-green-400' :
                            progressStatus === 'failed' ? 'text-red-400' :
                            'text-gray-500'
                          }`}>
                            {progressStatus === 'waiting' && '대기'}
                            {progressStatus === 'generating' && <><span className="animate-spin inline-block">⟳</span> 생성</>}
                            {progressStatus === 'saving' && <><span className="animate-spin inline-block">⟳</span> 저장</>}
                            {progressStatus === 'done' && '✓ 완료'}
                            {progressStatus === 'failed' && '✗ 실패'}
                            {!progressStatus && '-'}
                          </span>
                        )}
                      </label>
                    );
                  })}
                </div>
              </div>
            )}

            {storedLowMatch.length === 0 && (
              <div className="text-center text-xs text-green-400 py-2">✅ 미달 레벨 없음</div>
            )}
          </div>
        ) : null;
      })()}

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
              <label className="block text-xs text-gray-400 mb-1">검증 속도</label>
              <select
                value={autoTestIterations}
                onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                className="w-full px-2 py-1.5 text-sm bg-gray-700 border border-gray-600 rounded"
                disabled={batchTestProgress.status === 'running'}
              >
                <option value={30}>⚡ 빠름 (30회)</option>
                <option value={100}>⚖️ 보통 (100회)</option>
                <option value={200}>🎯 정밀 (200회)</option>
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
                  className={`h-full transition-[width] duration-500 ease-linear ${
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

          {/* 전체 자동 승인 버튼 - 테스트 완료 후 */}
          {batchTestProgress.status === 'completed' && (
            <div className="mt-3 p-3 bg-green-900/20 border border-green-700/50 rounded-lg">
              <div className="text-sm text-green-300 mb-2">
                ✅ 테스트 완료! 전체 레벨을 승인하고 익스포트하시겠습니까?
              </div>
              {isApprovingAll ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-green-200">
                    <div className="w-4 h-4 border-2 border-green-400 border-t-transparent rounded-full animate-spin" />
                    승인 중... {approveAllProgress.current}/{approveAllProgress.total}
                  </div>
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500 transition-all"
                      style={{ width: `${approveAllProgress.total > 0 ? (approveAllProgress.current / approveAllProgress.total) * 100 : 0}%` }}
                    />
                  </div>
                </div>
              ) : (
                <Button
                  onClick={handleApproveAllLevels}
                  className="w-full bg-green-600 hover:bg-green-700"
                >
                  ✅ 전체 자동 승인 → 익스포트
                </Button>
              )}
            </div>
          )}
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
                      {/* Regenerate button with status */}
                      {(() => {
                        const levelProgress = regenProgressMap.get(level.meta.level_number);
                        const isRegen = regeneratingLevels.has(level.meta.level_number);
                        const isDone = levelProgress?.status === 'done';
                        const isFailed = levelProgress?.status === 'failed';

                        return (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRegenerateLevel(level.meta.level_number);
                            }}
                            disabled={isRegen || isBatchRegenerating}
                            className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                              isRegen
                                ? 'bg-yellow-600 text-white cursor-not-allowed animate-pulse'
                                : isDone
                                  ? 'bg-green-600 hover:bg-green-500 text-white'
                                  : isFailed
                                    ? 'bg-red-600 hover:bg-red-500 text-white'
                                    : 'bg-blue-600 hover:bg-blue-500 text-white'
                            }`}
                            title={isRegen ? '재생성 중...' : isDone ? '재생성 완료 - 다시 재생성' : isFailed ? '재생성 실패 - 다시 시도' : '이 레벨만 재생성'}
                          >
                            {isRegen ? <span className="animate-spin inline-block">⟳</span> : isDone ? '✓' : isFailed ? '!' : '🔄'}
                          </button>
                        );
                      })()}
                      {/* Match score indicator or test button */}
                      {level.meta.match_score !== undefined && level.meta.match_score > 0 ? (
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          level.meta.match_score >= 70 ? 'bg-green-900/50 text-green-400' :
                          level.meta.match_score >= 50 ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'
                        }`}>
                          {level.meta.match_score.toFixed(0)}%
                        </span>
                      ) : (
                        <span className="text-xs px-1.5 py-0.5 rounded bg-gray-700 text-gray-400">
                          미측정
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

              {/* Bot Clear Rate Gauges - Horizontal compact layout */}
              {selectedLevel.meta.bot_clear_rates && (
                <div className="mt-3 p-2 bg-gray-700/30 rounded">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 shrink-0">봇 클리어율:</span>
                    <div className="flex-1 flex items-center gap-2">
                      {(['novice', 'casual', 'average', 'expert', 'optimal'] as const).map(bot => {
                        const rate = selectedLevel.meta.bot_clear_rates?.[bot] ?? 0;
                        const percentage = Math.round(rate * 100);
                        const botLabels: Record<string, string> = { novice: '초', casual: '캐', average: '보', expert: '전', optimal: '최' };
                        const botColors: Record<string, string> = {
                          novice: 'bg-red-500', casual: 'bg-orange-500', average: 'bg-yellow-500', expert: 'bg-green-500', optimal: 'bg-blue-500'
                        };
                        return (
                          <div key={bot} className="flex items-center gap-1" title={`${bot}: ${percentage}%`}>
                            <span className="text-[10px] text-gray-500 w-3">{botLabels[bot]}</span>
                            <div className="w-12 h-2 bg-gray-600 rounded-full overflow-hidden">
                              <div className={`h-full ${botColors[bot]}`} style={{ width: `${percentage}%` }} />
                            </div>
                            <span className="text-[10px] text-gray-300 w-7">{percentage}%</span>
                          </div>
                        );
                      })}
                    </div>
                    {selectedLevel.meta.match_score !== undefined && (
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                        selectedLevel.meta.match_score >= 70 ? 'bg-green-900/50 text-green-400' :
                        selectedLevel.meta.match_score >= 50 ? 'bg-yellow-900/50 text-yellow-400' : 'bg-red-900/50 text-red-400'
                      }`}>
                        일치: {selectedLevel.meta.match_score.toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              )}

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
                      <p className="text-sm text-gray-400">봇 프로필로 난이도 검증</p>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="text-sm text-gray-400">검증:</label>
                      <select
                        value={autoTestIterations}
                        onChange={(e) => setAutoTestIterations(Number(e.target.value))}
                        className="px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm"
                        disabled={isAutoTesting}
                      >
                        <option value={30}>⚡ 빠름</option>
                        <option value={100}>⚖️ 보통</option>
                        <option value={200}>🎯 정밀</option>
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

                        {/* Regenerate & Enhance buttons when match score is low */}
                        {autoTestResult.match_score < 70 && selectedLevel && (
                          <div className="flex flex-col gap-2">
                            <Button
                              onClick={() => {
                                const levelNum = selectedLevel.meta.level_number;
                                handleRegenerateLevel(levelNum).then(() => {
                                  setAutoTestResult(null);
                                  addNotification('success', `레벨 ${levelNum} 재생성 완료`);
                                });
                              }}
                              disabled={regeneratingLevels.has(selectedLevel.meta.level_number) || enhancingLevels.has(selectedLevel.meta.level_number)}
                              className="w-full py-2 bg-orange-600 hover:bg-orange-500"
                            >
                              {regeneratingLevels.has(selectedLevel.meta.level_number) ? (
                                <>
                                  <span className="animate-spin mr-2">⟳</span>
                                  재생성 중...
                                </>
                              ) : (
                                `🔄 미달 레벨 재생성 (${autoTestResult.match_score.toFixed(0)}%)`
                              )}
                            </Button>
                            <Button
                              onClick={() => {
                                const levelNum = selectedLevel.meta.level_number;
                                handleEnhanceLevel(levelNum).then(() => {
                                  setAutoTestResult(null);
                                });
                              }}
                              disabled={enhancingLevels.has(selectedLevel.meta.level_number) || regeneratingLevels.has(selectedLevel.meta.level_number)}
                              className="w-full py-2 bg-blue-600 hover:bg-blue-500"
                            >
                              {enhancingLevels.has(selectedLevel.meta.level_number) ? (
                                <>
                                  <span className="animate-spin mr-2">⟳</span>
                                  개선 중...
                                </>
                              ) : (
                                `🔧 레벨 개선 (${autoTestResult.match_score.toFixed(0)}%)`
                              )}
                            </Button>
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
                    {/* Bot Clear Rate Gauges */}
                    {selectedLevel?.meta.bot_clear_rates && (
                      <div className="w-full max-w-xs space-y-2 mt-2">
                        <div className="text-xs text-gray-400 text-center mb-2">봇별 클리어율</div>
                        {(['novice', 'casual', 'average', 'expert', 'optimal'] as const).map(bot => {
                          const rate = selectedLevel.meta.bot_clear_rates?.[bot] ?? 0;
                          const percentage = Math.round(rate * 100);
                          const botLabels: Record<string, string> = {
                            novice: '초보',
                            casual: '캐주얼',
                            average: '보통',
                            expert: '전문가',
                            optimal: '최적'
                          };
                          const botColors: Record<string, string> = {
                            novice: 'bg-red-500',
                            casual: 'bg-orange-500',
                            average: 'bg-yellow-500',
                            expert: 'bg-green-500',
                            optimal: 'bg-blue-500'
                          };
                          return (
                            <div key={bot} className="flex items-center gap-2">
                              <span className="text-xs text-gray-400 w-14 text-right">{botLabels[bot]}</span>
                              <div className="flex-1 h-3 bg-gray-700 rounded-full overflow-hidden">
                                <div
                                  className={`h-full ${botColors[bot]} transition-all duration-300`}
                                  style={{ width: `${percentage}%` }}
                                />
                              </div>
                              <span className="text-xs text-white w-10 text-right">{percentage}%</span>
                            </div>
                          );
                        })}
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
type ReviewFilter = LevelStatus | 'all' | 'needs_attention';

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
  const [allLevels, setAllLevels] = useState<ProductionLevel[]>([]);
  const [filter, setFilter] = useState<ReviewFilter>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [showBatchApproval, setShowBatchApproval] = useState(false);

  useEffect(() => {
    loadLevels();
  }, [batchId]);

  useEffect(() => {
    applyFilter();
  }, [allLevels, filter]);

  const loadLevels = async () => {
    setIsLoading(true);
    try {
      const loadedLevels = await getProductionLevelsByBatch(batchId, {
        limit: 500,
      });
      setAllLevels(loadedLevels);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const applyFilter = () => {
    let filtered = allLevels;

    if (filter === 'needs_attention') {
      // 주의 필요: 매치점수 60% 미만 OR D등급 OR 플레이테스트 이슈 있음
      filtered = allLevels.filter(l => {
        const matchScore = l.meta.match_score ?? 100;
        const hasIssues = l.meta.playtest_results?.some(r => r.issues.length > 0);
        return matchScore < 60 || l.meta.grade === 'D' || hasIssues;
      });
    } else if (filter !== 'all') {
      filtered = allLevels.filter(l => l.meta.status === filter);
    }

    setLevels(filtered);
  };

  // 주의 필요 레벨 수 계산
  const needsAttentionCount = useMemo(() => {
    return allLevels.filter(l => {
      const matchScore = l.meta.match_score ?? 100;
      const hasIssues = l.meta.playtest_results?.some(r => r.issues.length > 0);
      return matchScore < 60 || l.meta.grade === 'D' || hasIssues;
    }).length;
  }, [allLevels]);

  // 레벨 상태별 배경색 계산
  const getLevelBgColor = (level: ProductionLevel): string => {
    const matchScore = level.meta.match_score ?? 100;
    const grade = level.meta.grade;
    const hasIssues = level.meta.playtest_results?.some(r => r.issues.length > 0);

    // 빨강: 매치점수 60% 미만 OR D등급
    if (matchScore < 60 || grade === 'D') {
      return 'bg-red-900/30 border-l-4 border-red-500';
    }

    // 노랑: 매치점수 60-79% OR C등급 OR 이슈 있음
    if (matchScore < 80 || grade === 'C' || hasIssues) {
      return 'bg-yellow-900/20 border-l-4 border-yellow-500';
    }

    // 초록: 승인됨
    if (level.meta.status === 'approved' || level.meta.status === 'exported') {
      return 'bg-green-900/20 border-l-4 border-green-500';
    }

    // 기본
    return 'bg-gray-800';
  };

  // 이슈 아이콘 표시
  const getIssueIcon = (level: ProductionLevel): string | null => {
    const matchScore = level.meta.match_score ?? 100;
    const hasPlaytestIssues = level.meta.playtest_results?.some(r => r.issues.length > 0);
    const hasBug = level.meta.playtest_results?.some(r =>
      r.issues.some(i => i.toLowerCase().includes('bug') || i.toLowerCase().includes('버그'))
    );

    if (hasBug) return '🐛';
    if (hasPlaytestIssues) return '⚠️';
    if (matchScore < 60) return '⚠️';
    if (level.meta.status === 'approved') return '✓';
    return null;
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
      {/* Mode Toggle */}
      <div className="flex items-center justify-between">
        <div className="flex gap-2">
          <button
            onClick={() => setShowBatchApproval(false)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              !showBatchApproval
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            개별 검토
          </button>
          <button
            onClick={() => setShowBatchApproval(true)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              showBatchApproval
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            배치 승인
          </button>
        </div>
      </div>

      {/* Batch Approval Panel */}
      {showBatchApproval ? (
        <BatchApprovalPanel
          batchId={batchId}
          onComplete={() => setShowBatchApproval(false)}
          onStatsUpdate={() => {
            loadLevels();
            onStatsUpdate();
          }}
        />
      ) : (
        <>
          {/* Filter */}
          <div className="flex gap-2 flex-wrap">
            {[
              { value: 'all', label: '전체' },
              { value: 'needs_attention', label: `주의 필요 ⚠️ ${needsAttentionCount}`, highlight: needsAttentionCount > 0 },
              { value: 'generated', label: '생성됨' },
              { value: 'needs_rework', label: '수정필요' },
              { value: 'approved', label: '승인됨' },
              { value: 'rejected', label: '거부됨' },
            ].map((opt) => (
              <button
                key={opt.value}
                onClick={() => setFilter(opt.value as ReviewFilter)}
                className={`px-3 py-1 rounded text-sm transition-colors ${
                  filter === opt.value
                    ? 'bg-indigo-600 text-white'
                    : opt.highlight
                      ? 'bg-red-900/50 text-red-200 border border-red-700 hover:bg-red-900/70'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
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
              {levels.length === 0 ? (
                <div className="text-center text-gray-500 py-8">
                  {filter === 'needs_attention' ? '주의가 필요한 레벨이 없습니다' : '레벨이 없습니다'}
                </div>
              ) : (
                levels.map((level) => (
                  <div
                    key={level.meta.level_number}
                    className={`flex items-center justify-between p-3 rounded-lg transition-colors ${getLevelBgColor(level)}`}
                  >
                    <div className="flex items-center gap-4">
                      <button
                        onClick={() => onLevelSelect?.(level)}
                        className="text-indigo-400 hover:text-indigo-300 font-medium"
                      >
                        레벨 {level.meta.level_number}
                      </button>
                      <span className={getGradeColor(level.meta.grade)}>{level.meta.grade}</span>
                      <span className="text-xs text-gray-400">
                        매치 {level.meta.match_score?.toFixed(0) ?? '-'}%
                      </span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(level.meta.status)}`}>
                        {getStatusLabel(level.meta.status)}
                      </span>
                      {getIssueIcon(level) && (
                        <span className="text-sm">{getIssueIcon(level)}</span>
                      )}
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
                ))
              )}
            </div>
          )}
        </>
      )}
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
