import { useState, useCallback, useRef } from 'react';
import { DifficultyGraph } from './DifficultyGraph';
import { LevelSetConfig } from './LevelSetConfig';
import { GenerationProgress } from './GenerationProgress';
import { generateLevel } from '../../api/generate';
import { saveLevelSet, exportLevelSetAsFile } from '../../api/levelSet';
import {
  interpolateDifficulties,
  createDefaultDifficultyPoints,
  reorderLevelsByDifficulty,
  calculateGradeDistribution,
  createGenerationPlan,
  getGradeFromDifficulty,
  shiftDifficultyPoints,
  createDefaultMultiSetConfig,
  DEFAULT_GIMMICK_UNLOCK_LEVELS,
  PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
  type DifficultyPoint,
  type LevelSetGenerationConfig,
  type GenerationProgressState,
  type GenerationResultItem,
  type LevelSet,
  type MultiSetProgressState,
} from '../../types/levelSet';
import type { LevelJSON, DifficultyGrade, GenerationParams } from '../../types';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';

interface LevelSetGeneratorProps {
  onLevelSetCreated?: (levelSet: LevelSet) => void;
}

/**
 * Calculate gimmick intensity based on global level position
 *
 * @param globalLevelIndex - 0-based index of this level across ALL generated levels
 * @param totalLevels - Total number of levels being generated
 * @returns intensity value from 0.0 to 1.0
 *
 * Progression curve:
 * - Linear increase from 0 to 1.0 across all levels
 *
 * Examples for 10 total levels:
 * - Level 1 (0%): intensity = 0.0
 * - Level 5 (50%): intensity ≈ 0.44
 * - Level 10 (100%): intensity = 1.0
 */
function calculateGimmickIntensity(globalLevelIndex: number, totalLevels: number): number {
  if (totalLevels <= 1) return 1.0;

  // Linear increase from 0 to 1.0
  const intensity = globalLevelIndex / (totalLevels - 1);

  // Round to 2 decimal places for cleaner values
  return Math.round(intensity * 100) / 100;
}

const DEFAULT_CONFIG: LevelSetGenerationConfig = {
  setName: '',
  levelCount: 10,
  difficultyPoints: createDefaultDifficultyPoints(10),
  baseParams: {
    grid_size: [7, 7],
    min_layers: 3,  // 최소 레이어 (쉬운 난이도용)
    max_layers: 7,  // 최대 레이어 (어려운 난이도용)
    tile_types: ['t1', 't2', 't3', 't4', 't5'],
    obstacle_types: [],  // 수동 모드일 때 사용
    goals: [{ type: 'craft', direction: 's', count: 3 }],
    symmetry_mode: 'both',  // 기본값: 양방향 대칭
    pattern_type: 'aesthetic',  // 기본값: 미관 최적화 패턴 (Tile Explorer/Tile Buster 스타일)
  },
  // 생성 모드 - 기본값: 패턴 생성 (미관 최적화)
  generationMode: 'pattern',
  // 기믹 자동 선택 관련 - 기본값: 자동 모드
  gimmickMode: 'auto',
  availableGimmicks: ['chain', 'frog', 'ice', 'grass', 'link', 'bomb', 'curtain', 'teleport', 'unknown'],  // 기본 기믹 풀 (전체)
  levelGimmickOverrides: [],
  // 프로페셔널 레벨링 모드 - Tile Buster/Explorer 스타일
  levelingMode: 'professional',
  gimmickUnlockLevels: PROFESSIONAL_GIMMICK_UNLOCK_LEVELS,
  useGimmickUnlock: true,  // 기본으로 활성화
  useSawtoothPattern: true,  // 톱니바퀴 난이도 패턴 활성화
  startLevelNumber: 1,  // 시작 레벨 번호
};

export function LevelSetGenerator({ onLevelSetCreated }: LevelSetGeneratorProps) {
  const { addNotification } = useUIStore();
  const [config, setConfig] = useState<LevelSetGenerationConfig>(DEFAULT_CONFIG);
  const [difficultyPoints, setDifficultyPoints] = useState<DifficultyPoint[]>(
    createDefaultDifficultyPoints(DEFAULT_CONFIG.levelCount)
  );
  const [progress, setProgress] = useState<GenerationProgressState>({
    status: 'idle',
    total: 0,
    current: 0,
    results: [],
  });
  const [generatedLevelSet, setGeneratedLevelSet] = useState<LevelSet | null>(null);

  // Multi-set generation state
  const [multiSetProgress, setMultiSetProgress] = useState<MultiSetProgressState>({
    status: 'idle',
    totalSets: 0,
    currentSetIndex: 0,
    totalLevels: 0,
    currentLevelIndex: 0,
    completedSets: 0,
    setResults: [],
  });
  const [generatedLevelSets, setGeneratedLevelSets] = useState<LevelSet[]>([]);

  const abortControllerRef = useRef<AbortController | null>(null);

  // Update difficulty points when level count changes
  const handleConfigChange = useCallback((newConfig: LevelSetGenerationConfig) => {
    if (newConfig.levelCount !== config.levelCount) {
      // Update default points if user hasn't customized them
      const defaultPoints = createDefaultDifficultyPoints(newConfig.levelCount);
      setDifficultyPoints(defaultPoints);
    }
    setConfig(newConfig);
  }, [config.levelCount]);

  // Generate a single level set (used by both single and multi-set modes)
  // globalLevelStart: Starting global level index (for multi-set generation)
  // totalGlobalLevels: Total levels being generated across all sets (for intensity calculation)
  const generateSingleSet = useCallback(async (
    setName: string,
    setIndex: number,
    baseDifficultyPoints: DifficultyPoint[],
    signal: AbortSignal,
    onProgress?: (levelIndex: number, total: number) => void,
    globalLevelStart: number = 0,
    totalGlobalLevels?: number
  ): Promise<LevelSet | null> => {
    const difficulties = interpolateDifficulties(baseDifficultyPoints, config.levelCount);
    const gradeDistribution = calculateGradeDistribution(difficulties);
    const generationPlan = createGenerationPlan(gradeDistribution);

    console.log(`📊 Set ${setIndex + 1} "${setName}" - Grade distribution:`, gradeDistribution);

    // PARALLEL GENERATION: Flatten all level tasks and run in batches
    const CONCURRENCY = 10; // 10개 동시 처리

    // Build flat list of all level tasks from generation plan
    interface LevelTask {
      levelIndex: number;
      plan: typeof generationPlan[0];
    }
    const levelTasks: LevelTask[] = [];
    let flatIdx = 0;
    for (const plan of generationPlan) {
      for (let j = 0; j < plan.count; j++) {
        levelTasks.push({ levelIndex: flatIdx, plan });
        flatIdx++;
      }
    }

    // Results storage (indexed by levelIndex for correct ordering)
    const generatedLevels: (LevelJSON | null)[] = new Array(levelTasks.length).fill(null);
    const actualDifficulties: number[] = new Array(levelTasks.length).fill(0);
    const grades: DifficultyGrade[] = new Array(levelTasks.length).fill('D' as DifficultyGrade);

    // Helper: Generate one level with full retry logic (per-level retries are sequential)
    const generateOneLevelWithRetries = async (task: LevelTask): Promise<{
      levelJson: LevelJSON | null;
      difficulty: number;
      grade: DifficultyGrade;
    }> => {
      const { levelIndex, plan } = task;
      const globalLevelIndex = globalLevelStart + levelIndex;
      const totalLevels = totalGlobalLevels ?? config.levelCount;
      const gimmickIntensity = calculateGimmickIntensity(globalLevelIndex, totalLevels);

      const effectiveGoals = (config.baseParams.goals && config.baseParams.goals.length > 0)
        ? config.baseParams.goals
        : [{ type: 'craft' as const, direction: 's' as const, count: 3 }];

      const baseParams: GenerationParams = {
        ...config.baseParams,
        // level_number가 제공되면 tile_types를 제거하여 백엔드에서 자동 선택 (t0/톱니바퀴 패턴)
        tile_types: config.useGimmickUnlock ? undefined : config.baseParams.tile_types,
        goals: effectiveGoals,
        target_difficulty: plan.targetDifficulty,
        // 패턴 생성 모드: 세트별로 다른 패턴 인덱스 할당, 빠른 생성 모드: 패턴 없음
        pattern_index: config.generationMode === 'pattern' ? (setIndex % 50) : undefined,
      };

      let useAutoGimmicks = false;
      let autoGimmickPool: string[] | undefined;

      if (config.gimmickMode === 'auto') {
        useAutoGimmicks = true;
        autoGimmickPool = config.availableGimmicks;
        baseParams.obstacle_types = [];
      } else if (config.gimmickMode === 'hybrid') {
        const override = config.levelGimmickOverrides?.find(o => o.levelIndex === levelIndex + 1);
        if (override) {
          baseParams.obstacle_types = override.gimmicks;
        } else {
          useAutoGimmicks = true;
          autoGimmickPool = config.availableGimmicks;
          baseParams.obstacle_types = [];
        }
      }

      try {
        const gimmickOpts = {
          gimmick_intensity: gimmickIntensity,
          ...(useAutoGimmicks && {
            auto_select_gimmicks: true,
            available_gimmicks: autoGimmickPool,
          }),
          ...(config.useGimmickUnlock && {
            gimmick_unlock_levels: config.gimmickUnlockLevels ?? DEFAULT_GIMMICK_UNLOCK_LEVELS,
            level_number: globalLevelIndex + 1,
          }),
        };

        const MAX_RETRIES = 30;
        const API_ERROR_RETRIES = 10;
        let retryCount = 0;
        let difficultyAdjustment = 0;

        const generateWithRetry = async (params: typeof baseParams, opts: typeof gimmickOpts) => {
          let lastError: Error | null = null;
          for (let apiRetry = 0; apiRetry < API_ERROR_RETRIES; apiRetry++) {
            try {
              let variationRange = 0.1;
              if (apiRetry >= 7) variationRange = 0.5;
              else if (apiRetry >= 4) variationRange = 0.3;

              const diffVariation = apiRetry > 0 ? (Math.random() - 0.5) * variationRange : 0;
              const adjustedDiff = Math.max(0.05, Math.min(0.95, params.target_difficulty + diffVariation));

              const adjustedOpts = { ...opts };
              if (apiRetry >= 7 && adjustedOpts.gimmick_intensity !== undefined) {
                adjustedOpts.gimmick_intensity = Math.max(0, adjustedOpts.gimmick_intensity - 0.3);
              }

              const adjustedParams = { ...params, target_difficulty: adjustedDiff };
              if (apiRetry >= 4 && adjustedOpts.available_gimmicks && adjustedOpts.available_gimmicks.length > 3) {
                const shuffled = [...adjustedOpts.available_gimmicks].sort(() => Math.random() - 0.5);
                adjustedOpts.available_gimmicks = shuffled.slice(0, Math.max(3, shuffled.length - apiRetry + 3));
              }

              return await generateLevel(adjustedParams, adjustedOpts);
            } catch (err) {
              lastError = err as Error;
              await new Promise(resolve => setTimeout(resolve, 100 * Math.pow(1.5, apiRetry)));
            }
          }
          throw lastError;
        };

        let result = await generateWithRetry(baseParams, gimmickOpts);

        const gradeOrder = ['S', 'A', 'B', 'C', 'D'];
        const targetGradeIdx = gradeOrder.indexOf(plan.grade);

        const isAcceptableGrade = (grade: string, retry: number): boolean => {
          const actualIdx = gradeOrder.indexOf(grade);
          if (retry >= 20 && Math.abs(actualIdx - targetGradeIdx) <= 1) return true;
          return grade === plan.grade;
        };

        while (!isAcceptableGrade(result.grade, retryCount) && retryCount < MAX_RETRIES) {
          retryCount++;
          const actualGradeIdx = gradeOrder.indexOf(result.grade);

          let stepSize: number;
          let maxCap: number;
          if (retryCount <= 10) { stepSize = 0.03; maxCap = 0.15; }
          else if (retryCount <= 20) { stepSize = 0.05; maxCap = 0.30; }
          else { stepSize = 0.08; maxCap = 0.45; }

          if (actualGradeIdx < targetGradeIdx) difficultyAdjustment += stepSize;
          else difficultyAdjustment -= stepSize;

          difficultyAdjustment = Math.max(-maxCap, Math.min(maxCap, difficultyAdjustment));

          const adjustedParams = {
            ...baseParams,
            target_difficulty: Math.max(0.05, Math.min(0.95, plan.targetDifficulty + difficultyAdjustment)),
          };

          result = await generateWithRetry(adjustedParams, gimmickOpts);
        }

        return { levelJson: result.level_json, difficulty: result.actual_difficulty, grade: result.grade };
      } catch (err) {
        console.error(`Set ${setIndex + 1} Level ${levelIndex + 1}: Generation failed:`, err);
        return { levelJson: null, difficulty: 0, grade: 'D' as DifficultyGrade };
      }
    };

    // Execute in parallel batches with concurrency limit
    let completedCount = 0;
    for (let batchStart = 0; batchStart < levelTasks.length; batchStart += CONCURRENCY) {
      if (signal.aborted) throw new Error('cancelled');

      const batchSlice = levelTasks.slice(batchStart, batchStart + CONCURRENCY);
      const results = await Promise.allSettled(
        batchSlice.map(task => generateOneLevelWithRetries(task))
      );

      for (let i = 0; i < results.length; i++) {
        const r = results[i];
        const task = batchSlice[i];
        if (r.status === 'fulfilled') {
          generatedLevels[task.levelIndex] = r.value.levelJson;
          actualDifficulties[task.levelIndex] = r.value.difficulty;
          grades[task.levelIndex] = r.value.grade;
        }
        completedCount++;
      }

      onProgress?.(completedCount, config.levelCount);
    }

    const successfulLevels = generatedLevels.filter((l) => l !== null);
    const successfulDifficulties = actualDifficulties.filter((_, i) => generatedLevels[i] !== null);
    const successfulGrades = grades.filter((_, i) => generatedLevels[i] !== null);

    if (successfulLevels.length === 0) {
      return null;
    }

    const reorderResult = reorderLevelsByDifficulty(
      successfulLevels,
      successfulDifficulties,
      successfulGrades,
      difficulties.slice(0, successfulLevels.length)
    );

    const setId = `set_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    const finalLevels = reorderResult.reorderedLevels.map((level, newIndex) => ({
      ...level,
      level_index: newIndex + 1,
      name: `${setName} - Level ${newIndex + 1}`,
      id: `${setId}_level_${String(newIndex + 1).padStart(3, '0')}`,
    }));

    return {
      metadata: {
        id: setId,
        name: setName,
        created_at: new Date().toISOString(),
        level_count: finalLevels.length,
        difficulty_profile: difficulties.slice(0, finalLevels.length),
        actual_difficulties: reorderResult.reorderedDifficulties,
        grades: reorderResult.reorderedGrades,
        generation_config: config.baseParams,
      },
      levels: finalLevels,
    };
  }, [config]);

  // Start multi-set generation
  const handleStartMultiSetGeneration = useCallback(async () => {
    const multiSetConfig = config.multiSetConfig || createDefaultMultiSetConfig();

    if (!config.setName.trim()) {
      addNotification('error', '세트 이름을 입력해주세요');
      return;
    }

    const totalSets = multiSetConfig.setCount;
    const totalLevels = config.levelCount * totalSets;

    // Initialize multi-set progress
    const initialSetResults = Array.from({ length: totalSets }, (_, i) => ({
      setIndex: i,
      setName: `${config.setName} ${i + 1}`,
      levelCount: config.levelCount,
      status: 'pending' as const,
    }));

    setMultiSetProgress({
      status: 'generating',
      totalSets,
      currentSetIndex: 0,
      totalLevels,
      currentLevelIndex: 0,
      completedSets: 0,
      setResults: initialSetResults,
      startTime: Date.now(),
    });

    setGeneratedLevelSets([]);

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const completedSets: LevelSet[] = [];

    try {
      for (let setIdx = 0; setIdx < totalSets; setIdx++) {
        if (signal.aborted) {
          throw new Error('cancelled');
        }

        const setName = `${config.setName} ${setIdx + 1}`;
        const difficultyShift = setIdx * multiSetConfig.difficultyShiftPerSet;
        const shiftedPoints = shiftDifficultyPoints(
          difficultyPoints,
          difficultyShift,
          multiSetConfig.maxDifficultyClamp
        );

        console.log(`🚀 Starting Set ${setIdx + 1}/${totalSets}: "${setName}" (shift: +${(difficultyShift * 100).toFixed(0)}%)`);

        // Update progress: mark current set as generating
        setMultiSetProgress(prev => ({
          ...prev,
          currentSetIndex: setIdx,
          setResults: prev.setResults.map((r, i) =>
            i === setIdx ? { ...r, status: 'generating' } : r
          ),
        }));

        // Calculate global level start index for gimmick intensity progression
        const globalLevelStart = setIdx * config.levelCount;

        const levelSet = await generateSingleSet(
          setName,
          setIdx,
          shiftedPoints,
          signal,
          (levelIndex, _total) => {
            setMultiSetProgress(prev => ({
              ...prev,
              currentLevelIndex: setIdx * config.levelCount + levelIndex,
            }));
          },
          globalLevelStart,  // Global level start for this set
          totalLevels        // Total levels across all sets
        );

        if (levelSet) {
          completedSets.push(levelSet);

          // Save the set immediately
          try {
            await saveLevelSet({
              name: levelSet.metadata.name,
              levels: levelSet.levels,
              difficulty_profile: levelSet.metadata.difficulty_profile,
              actual_difficulties: levelSet.metadata.actual_difficulties,
              grades: levelSet.metadata.grades,
              generation_config: levelSet.metadata.generation_config as Record<string, unknown>,
            });
            console.log(`✅ Set ${setIdx + 1} saved: "${setName}"`);
          } catch (err) {
            console.error(`Failed to save set ${setIdx + 1}:`, err);
          }

          // Update progress: mark current set as completed
          setMultiSetProgress(prev => ({
            ...prev,
            completedSets: setIdx + 1,
            setResults: prev.setResults.map((r, i) =>
              i === setIdx ? { ...r, status: 'completed' } : r
            ),
          }));

          setGeneratedLevelSets([...completedSets]);
        } else {
          // Mark as failed
          setMultiSetProgress(prev => ({
            ...prev,
            setResults: prev.setResults.map((r, i) =>
              i === setIdx ? { ...r, status: 'failed', error: '레벨 생성 실패' } : r
            ),
          }));
        }
      }

      setMultiSetProgress(prev => ({
        ...prev,
        status: 'completed',
      }));

      addNotification(
        'success',
        `🎉 ${completedSets.length}개 세트 생성 완료! (총 ${completedSets.reduce((sum, s) => sum + s.levels.length, 0)}개 레벨)`
      );
    } catch (err) {
      if ((err as Error).message === 'cancelled') {
        setMultiSetProgress(prev => ({
          ...prev,
          status: 'cancelled',
        }));
        addNotification('info', `생성이 취소되었습니다. ${completedSets.length}개 세트가 저장되었습니다.`);
      } else {
        setMultiSetProgress(prev => ({
          ...prev,
          status: 'error',
          error: err instanceof Error ? err.message : '알 수 없는 오류',
        }));
        addNotification('error', `생성 오류: ${err instanceof Error ? err.message : '알 수 없는 오류'}`);
      }
    }
  }, [config, difficultyPoints, addNotification, generateSingleSet]);

  // Start generation - Grade-based fast generation
  const handleStartGeneration = useCallback(async () => {
    if (!config.setName.trim()) {
      addNotification('error', '세트 이름을 입력해주세요');
      return;
    }

    const difficulties = interpolateDifficulties(difficultyPoints, config.levelCount);

    // Calculate grade distribution from target difficulties
    const gradeDistribution = calculateGradeDistribution(difficulties);
    const generationPlan = createGenerationPlan(gradeDistribution);

    console.log('📊 Grade distribution:', gradeDistribution);
    console.log('📋 Generation plan:', generationPlan);

    // Check if high difficulty grades require obstacles (only relevant for manual mode)
    const hasHighDifficultyGrades = gradeDistribution.B > 0 || gradeDistribution.C > 0 || gradeDistribution.D > 0;

    if (config.gimmickMode === 'manual') {
      const hasNoObstacles = !config.baseParams.obstacle_types || config.baseParams.obstacle_types.length === 0;
      if (hasHighDifficultyGrades && hasNoObstacles) {
        addNotification(
          'warning',
          `⚠️ B/C/D 등급(${gradeDistribution.B + gradeDistribution.C + gradeDistribution.D}개)을 달성하려면 장애물이 필요합니다. 장애물 없이는 A등급(~40%)이 상한선입니다.`
        );
      }
    } else if (config.gimmickMode === 'auto' || config.gimmickMode === 'hybrid') {
      // Auto/Hybrid mode - check if gimmick pool is empty for high difficulty
      const hasNoGimmickPool = !config.availableGimmicks || config.availableGimmicks.length === 0;
      if (hasHighDifficultyGrades && hasNoGimmickPool) {
        addNotification(
          'warning',
          `⚠️ B/C/D 등급에는 기믹이 필요합니다. 기믹 풀에 최소 1개 이상의 기믹을 추가하세요.`
        );
      }
    }

    // Initialize progress state
    const initialResults: GenerationResultItem[] = difficulties.map((targetDiff, i) => ({
      levelIndex: i + 1,
      targetDifficulty: targetDiff,
      actualDifficulty: 0,
      grade: getGradeFromDifficulty(targetDiff),
      status: 'pending',
    }));

    const now = Date.now();
    setProgress({
      status: 'generating',
      total: config.levelCount,
      current: 0,
      results: initialResults,
      totalStartTime: now,
      currentLevelStartTime: now,
      completedTimes: [],
      averageTimePerLevel: 0,
    });
    setGeneratedLevelSet(null);

    // Create abort controller
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const generatedLevels: LevelJSON[] = [];
    const actualDifficulties: number[] = [];
    const grades: DifficultyGrade[] = [];

    try {
      let levelIndex = 0;

      // Generate levels by grade (fast mode - no validation)
      for (const plan of generationPlan) {
        for (let j = 0; j < plan.count; j++) {
          if (signal.aborted) {
            throw new Error('cancelled');
          }

          const levelStartTime = Date.now();

          // Update progress
          setProgress((prev) => ({
            ...prev,
            current: levelIndex + 1,
            currentLevelStartTime: levelStartTime,
            results: prev.results.map((r, idx) =>
              idx === levelIndex ? { ...r, status: 'generating' } : r
            ),
          }));

          // Configure parameters based on grade and gimmick mode
          const baseParams: GenerationParams = {
            ...config.baseParams,
            target_difficulty: plan.targetDifficulty,
          };

          // Handle gimmick mode
          let useAutoGimmicks = false;
          let autoGimmickPool: string[] | undefined;

          if (config.gimmickMode === 'auto') {
            // Full auto mode: let backend select gimmicks
            useAutoGimmicks = true;
            autoGimmickPool = config.availableGimmicks;
            baseParams.obstacle_types = [];  // Clear manual obstacles
          } else if (config.gimmickMode === 'hybrid') {
            // Check if this level has an override
            const override = config.levelGimmickOverrides?.find(o => o.levelIndex === levelIndex + 1);
            if (override) {
              // Use specific gimmicks for this level
              baseParams.obstacle_types = override.gimmicks;
            } else {
              // Use auto selection
              useAutoGimmicks = true;
              autoGimmickPool = config.availableGimmicks;
              baseParams.obstacle_types = [];
            }
          }
          // manual mode: use baseParams.obstacle_types as-is

          // Calculate gimmick intensity based on global level position
          // Uses smooth linear progression: first 20% = 0, then linear increase to 1.0
          const gimmickIntensity = calculateGimmickIntensity(levelIndex, config.levelCount);

          // Debug: log generation parameters
          const gimmickInfo = useAutoGimmicks ? `auto(pool: ${autoGimmickPool?.join(',')})` : `manual(${baseParams.obstacle_types?.join(',') || 'none'})`;
          const unlockInfo = config.useGimmickUnlock ? `unlock_enabled(level=${levelIndex + 1})` : 'unlock_disabled';
          console.log(`🎮 Level ${levelIndex + 1}/${config.levelCount}: grade=${plan.grade}, intensity=${gimmickIntensity.toFixed(2)}, gimmicks=${gimmickInfo}, ${unlockInfo}`);

          try {
            // auto_select_gimmicks must be true when gimmick unlock is enabled (for tutorial_gimmick processing)
            const needsAutoSelect = useAutoGimmicks || config.useGimmickUnlock;

            // Prepare gimmick options - always include gimmick_intensity for level progression
            const gimmickOpts = {
              gimmick_intensity: gimmickIntensity,  // Level progression: early levels have no gimmicks
              auto_select_gimmicks: needsAutoSelect,  // Required for tutorial_gimmick in backend
              ...(useAutoGimmicks && {
                available_gimmicks: autoGimmickPool,
              }),
              // Gimmick unlock system - filter gimmicks based on level number
              ...(config.useGimmickUnlock && {
                gimmick_unlock_levels: config.gimmickUnlockLevels ?? DEFAULT_GIMMICK_UNLOCK_LEVELS,
                level_number: levelIndex + 1,  // 1-based level number
              }),
            };

            // Generate with strict grade matching - retry with adjusted difficulty until grade matches
            const MAX_RETRIES = 30;
            const API_ERROR_RETRIES = 10;
            let retryCount = 0;
            let difficultyAdjustment = 0;

            // Helper function to generate with API error retry
            // On repeated failures, progressively adjust parameters to find a working combination
            const generateWithRetry = async (params: typeof baseParams, opts: typeof gimmickOpts) => {
              let lastError: Error | null = null;
              for (let apiRetry = 0; apiRetry < API_ERROR_RETRIES; apiRetry++) {
                try {
                  // Progressive difficulty variation: starts small, gets larger on later retries
                  // Retry 1-3: ±5%, Retry 4-6: ±15%, Retry 7-10: ±25%
                  let variationRange = 0.1;
                  if (apiRetry >= 7) variationRange = 0.5;
                  else if (apiRetry >= 4) variationRange = 0.3;

                  const diffVariation = apiRetry > 0 ? (Math.random() - 0.5) * variationRange : 0;
                  const adjustedDiff = Math.max(0.05, Math.min(0.95, params.target_difficulty + diffVariation));

                  // On very late retries (7+), also try reducing gimmick intensity
                  const adjustedOpts = { ...opts };
                  if (apiRetry >= 7 && adjustedOpts.gimmick_intensity !== undefined) {
                    adjustedOpts.gimmick_intensity = Math.max(0, adjustedOpts.gimmick_intensity - 0.3);
                  }

                  // On retries 4+, try reducing available gimmicks if auto mode
                  let adjustedParams = { ...params, target_difficulty: adjustedDiff };
                  if (apiRetry >= 4 && adjustedOpts.available_gimmicks && adjustedOpts.available_gimmicks.length > 3) {
                    // Randomly remove some gimmicks to reduce complexity
                    const shuffled = [...adjustedOpts.available_gimmicks].sort(() => Math.random() - 0.5);
                    adjustedOpts.available_gimmicks = shuffled.slice(0, Math.max(3, shuffled.length - apiRetry + 3));
                    console.log(`Retry ${apiRetry + 1}: Reduced gimmicks to [${adjustedOpts.available_gimmicks.join(', ')}]`);
                  }

                  return await generateLevel(adjustedParams, adjustedOpts);
                } catch (err) {
                  lastError = err as Error;
                  console.warn(`API error (attempt ${apiRetry + 1}/${API_ERROR_RETRIES}):`, err);
                  // Wait with exponential backoff
                  await new Promise(resolve => setTimeout(resolve, 100 * Math.pow(1.5, apiRetry)));
                }
              }
              throw lastError;
            };

            let result = await generateWithRetry(baseParams, gimmickOpts);

            // Progressive retry logic with escalating adjustments
            const gradeOrder = ['S', 'A', 'B', 'C', 'D'];
            const targetGradeIdx = gradeOrder.indexOf(plan.grade);

            const isAcceptableGrade = (grade: string, retry: number): boolean => {
              const actualIdx = gradeOrder.indexOf(grade);
              // After 20 retries, accept adjacent grade (±1)
              if (retry >= 20 && Math.abs(actualIdx - targetGradeIdx) <= 1) {
                return true;
              }
              return grade === plan.grade;
            };

            while (!isAcceptableGrade(result.grade, retryCount) && retryCount < MAX_RETRIES) {
              retryCount++;
              const actualGradeIdx = gradeOrder.indexOf(result.grade);

              // Progressive step size and cap based on retry count
              let stepSize: number;
              let maxCap: number;
              if (retryCount <= 10) {
                stepSize = 0.03;
                maxCap = 0.15;
              } else if (retryCount <= 20) {
                stepSize = 0.05;
                maxCap = 0.30;
              } else {
                stepSize = 0.08;
                maxCap = 0.45;
              }

              if (actualGradeIdx < targetGradeIdx) {
                // Got easier grade, increase difficulty
                difficultyAdjustment += stepSize;
              } else {
                // Got harder grade, decrease difficulty
                difficultyAdjustment -= stepSize;
              }

              // Clamp adjustment with progressive cap
              difficultyAdjustment = Math.max(-maxCap, Math.min(maxCap, difficultyAdjustment));

              const adjustedParams = {
                ...baseParams,
                target_difficulty: Math.max(0.05, Math.min(0.95, plan.targetDifficulty + difficultyAdjustment)),
              };

              // Update progress with retry info
              setProgress((prev) => ({
                ...prev,
                results: prev.results.map((r, idx) =>
                  idx === levelIndex
                    ? { ...r, retryCount, targetGrade: plan.grade }
                    : r
                ),
              }));

              console.log(`Level ${levelIndex + 1}: Grade mismatch (wanted ${plan.grade}, got ${result.grade}, diff=${(result.actual_difficulty * 100).toFixed(1)}%), retry ${retryCount}/${MAX_RETRIES} (adj: ${difficultyAdjustment > 0 ? '+' : ''}${(difficultyAdjustment * 100).toFixed(0)}%, cap: ±${(maxCap * 100).toFixed(0)}%)`);
              result = await generateWithRetry(adjustedParams, gimmickOpts);
            }

            if (result.grade !== plan.grade) {
              const wasAccepted = isAcceptableGrade(result.grade, retryCount);
              if (wasAccepted) {
                console.log(`Level ${levelIndex + 1}: Accepted adjacent grade ${result.grade} (target: ${plan.grade}) after ${retryCount} retries`);
              } else {
                console.warn(`Level ${levelIndex + 1}: Could not achieve grade ${plan.grade} after ${MAX_RETRIES} retries, got ${result.grade}`);
              }
            }

            generatedLevels.push(result.level_json);
            actualDifficulties.push(result.actual_difficulty);
            grades.push(result.grade);

            const levelElapsed = Date.now() - levelStartTime;
            const gradeMatched = result.grade === plan.grade;

            // Update progress with success
            setProgress((prev) => {
              const newCompletedTimes = [...(prev.completedTimes || []), levelElapsed];
              const newAverage = newCompletedTimes.reduce((a, b) => a + b, 0) / newCompletedTimes.length;

              return {
                ...prev,
                completedTimes: newCompletedTimes,
                averageTimePerLevel: newAverage,
                results: prev.results.map((r, idx) =>
                  idx === levelIndex
                    ? {
                        ...r,
                        status: 'success',
                        actualDifficulty: result.actual_difficulty,
                        grade: result.grade,
                        levelJson: result.level_json,
                        retryCount,
                        targetGrade: plan.grade,
                        validationPassed: gradeMatched,
                      }
                    : r
                ),
              };
            });

            const matchStatus = result.grade === plan.grade ? '✓' : `✗ (wanted ${plan.grade})`;
            console.log(`Level ${levelIndex + 1}: ${result.grade} ${matchStatus} (${(result.actual_difficulty * 100).toFixed(0)}%) ${retryCount > 0 ? `[${retryCount} retries]` : ''}`);
          } catch (err) {
            console.error(`Level ${levelIndex + 1}: Generation failed:`, err);
            setProgress((prev) => ({
              ...prev,
              results: prev.results.map((r, idx) =>
                idx === levelIndex
                  ? {
                      ...r,
                      status: 'failed',
                      error: `생성 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`,
                    }
                  : r
              ),
            }));

            generatedLevels.push(null as unknown as LevelJSON);
            actualDifficulties.push(0);
            grades.push('D');
          }

          levelIndex++;
        }
      }

      // Filter out failed levels
      const successfulLevels = generatedLevels.filter((l) => l !== null);
      const successfulDifficulties = actualDifficulties.filter((_, i) => generatedLevels[i] !== null);
      const successfulGrades = grades.filter((_, i) => generatedLevels[i] !== null);

      if (successfulLevels.length === 0) {
        throw new Error('모든 레벨 생성이 실패했습니다');
      }

      // Post-processing: Reorder levels to match the target difficulty curve
      // This is the key optimization - generate by grade, then reorder to match graph
      const reorderResult = reorderLevelsByDifficulty(
        successfulLevels,
        successfulDifficulties,
        successfulGrades,
        difficulties.slice(0, successfulLevels.length)
      );

      console.log(
        `📊 Reordering complete: ${reorderResult.improvements.swapCount} levels moved. ` +
        `Error: ${(reorderResult.improvements.beforeError * 100).toFixed(1)}% → ${(reorderResult.improvements.afterError * 100).toFixed(1)}%`
      );

      // Update level metadata with new indices
      const setId = `set_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const finalLevels = reorderResult.reorderedLevels.map((level, newIndex) => ({
        ...level,
        level_index: newIndex + 1,
        name: `${config.setName} - Level ${newIndex + 1}`,
        id: `${setId}_level_${String(newIndex + 1).padStart(3, '0')}`,
      }));

      // Create level set with reordered data
      const levelSet: LevelSet = {
        metadata: {
          id: setId,
          name: config.setName,
          created_at: new Date().toISOString(),
          level_count: finalLevels.length,
          difficulty_profile: difficulties.slice(0, finalLevels.length),
          actual_difficulties: reorderResult.reorderedDifficulties,
          grades: reorderResult.reorderedGrades,
          generation_config: config.baseParams,
        },
        levels: finalLevels,
      };

      setGeneratedLevelSet(levelSet);

      // Update progress with final reordered results
      const finalResults: GenerationResultItem[] = reorderResult.reorderedLevels.map((_, idx) => ({
        levelIndex: idx + 1,
        targetDifficulty: difficulties[idx],
        actualDifficulty: reorderResult.reorderedDifficulties[idx],
        grade: reorderResult.reorderedGrades[idx],
        status: 'success' as const,
      }));

      setProgress((prev) => ({
        ...prev,
        status: 'completed',
        results: finalResults,
      }));

      // Show completion notification with grade distribution info
      const gradeInfo = Object.entries(gradeDistribution)
        .filter(([k, v]) => k !== 'total' && v > 0)
        .map(([k, v]) => `${k}:${v}`)
        .join(' ');
      addNotification(
        'success',
        `레벨 세트 "${config.setName}" 생성 완료! (${gradeInfo})`
      );
      onLevelSetCreated?.(levelSet);
    } catch (err) {
      if ((err as Error).message === 'cancelled') {
        setProgress((prev) => ({
          ...prev,
          status: 'cancelled',
        }));
      } else {
        setProgress((prev) => ({
          ...prev,
          status: 'error',
          error: err instanceof Error ? err.message : '알 수 없는 오류',
        }));
      }
    }
  }, [config, difficultyPoints, addNotification, onLevelSetCreated]);

  // Cancel generation
  const handleCancel = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  // Save level set
  const handleSave = useCallback(async () => {
    if (!generatedLevelSet) return;

    try {
      await saveLevelSet({
        name: generatedLevelSet.metadata.name,
        levels: generatedLevelSet.levels,
        difficulty_profile: generatedLevelSet.metadata.difficulty_profile,
        actual_difficulties: generatedLevelSet.metadata.actual_difficulties,
        grades: generatedLevelSet.metadata.grades,
        generation_config: generatedLevelSet.metadata.generation_config as Record<string, unknown>,
      });
      addNotification('success', '레벨 세트가 저장되었습니다');
    } catch (err) {
      addNotification('error', `저장 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`);
    }
  }, [generatedLevelSet, addNotification]);

  // Export as file
  const handleExport = useCallback(() => {
    if (!generatedLevelSet) return;
    exportLevelSetAsFile(generatedLevelSet);
    addNotification('info', '레벨 세트 파일이 다운로드됩니다');
  }, [generatedLevelSet, addNotification]);

  // Reset
  const handleReset = useCallback(() => {
    setProgress({
      status: 'idle',
      total: 0,
      current: 0,
      results: [],
    });
    setMultiSetProgress({
      status: 'idle',
      totalSets: 0,
      currentSetIndex: 0,
      totalLevels: 0,
      currentLevelIndex: 0,
      completedSets: 0,
      setResults: [],
    });
    setGeneratedLevelSet(null);
    setGeneratedLevelSets([]);
  }, []);

  const multiSetConfig = config.multiSetConfig || createDefaultMultiSetConfig();
  const isMultiSetMode = multiSetConfig.enabled;

  const isGenerating = isMultiSetMode
    ? multiSetProgress.status === 'generating'
    : progress.status === 'generating';
  const isCompleted = isMultiSetMode
    ? multiSetProgress.status === 'completed'
    : progress.status === 'completed';
  const hasError = isMultiSetMode
    ? multiSetProgress.status === 'error' || multiSetProgress.status === 'cancelled'
    : progress.status === 'error' || progress.status === 'cancelled';

  // Check if difficulty ceiling warning is needed
  const maxDifficulty = Math.max(...difficultyPoints.map(p => p.difficulty));
  const showDifficultyCeilingWarning = maxDifficulty > 0.4 && (
    (config.gimmickMode === 'manual' && (!config.baseParams.obstacle_types || config.baseParams.obstacle_types.length === 0)) ||
    ((config.gimmickMode === 'auto' || config.gimmickMode === 'hybrid') && (!config.availableGimmicks || config.availableGimmicks.length === 0))
  );

  // Multi-set progress display component
  const MultiSetProgressDisplay = () => {
    if (multiSetProgress.status === 'idle') return null;

    const elapsed = multiSetProgress.startTime
      ? Math.floor((Date.now() - multiSetProgress.startTime) / 1000)
      : 0;
    const progressPercent = multiSetProgress.totalLevels > 0
      ? (multiSetProgress.currentLevelIndex / multiSetProgress.totalLevels) * 100
      : 0;

    return (
      <div className="bg-gray-800 rounded-lg p-4 space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-medium text-white">
            🔄 다중 세트 생성 중
          </h3>
          <span className="text-xs text-gray-400">
            {Math.floor(elapsed / 60)}:{String(elapsed % 60).padStart(2, '0')}
          </span>
        </div>

        {/* Overall progress */}
        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-gray-400">
              세트 {multiSetProgress.status === 'completed'
                ? multiSetProgress.completedSets
                : multiSetProgress.currentSetIndex + 1}/{multiSetProgress.totalSets}
            </span>
            <span className="text-gray-400">
              레벨 {multiSetProgress.currentLevelIndex}/{multiSetProgress.totalLevels}
            </span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-indigo-600 to-purple-600 transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Set list */}
        <div className="max-h-48 overflow-y-auto space-y-1">
          {multiSetProgress.setResults.map((set, idx) => (
            <div
              key={idx}
              className={`flex items-center justify-between px-2 py-1 rounded text-xs ${
                set.status === 'generating' ? 'bg-indigo-900/50' :
                set.status === 'completed' ? 'bg-green-900/30' :
                set.status === 'failed' ? 'bg-red-900/30' :
                'bg-gray-700/30'
              }`}
            >
              <span className="text-gray-300">{set.setName}</span>
              <span className={`${
                set.status === 'generating' ? 'text-indigo-400' :
                set.status === 'completed' ? 'text-green-400' :
                set.status === 'failed' ? 'text-red-400' :
                'text-gray-500'
              }`}>
                {set.status === 'generating' ? '생성 중...' :
                 set.status === 'completed' ? '✓ 완료' :
                 set.status === 'failed' ? '✗ 실패' :
                 '대기'}
              </span>
            </div>
          ))}
        </div>

        {multiSetProgress.status === 'generating' && (
          <Button onClick={handleCancel} variant="danger" className="w-full">
            🛑 생성 중지
          </Button>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Difficulty Graph */}
      <DifficultyGraph
        levelCount={config.levelCount}
        points={difficultyPoints}
        onPointsChange={setDifficultyPoints}
      />

      {/* Difficulty Ceiling Warning */}
      {showDifficultyCeilingWarning && !isGenerating && !isCompleted && (
        <div className="bg-yellow-900/50 border border-yellow-600 rounded-lg p-3 text-yellow-200 text-sm">
          <span className="font-bold">⚠️ 난이도 상한 경고:</span> 기믹 없이는 A등급(~40%)이 최대입니다.
          {config.gimmickMode === 'manual'
            ? <> B/C/D 등급을 생성하려면 <span className="font-semibold">상세 설정 → 장애물</span>에서 장애물을 추가하세요.</>
            : <> B/C/D 등급을 생성하려면 <span className="font-semibold">기믹 배분 모드</span>에서 기믹 풀을 선택하세요.</>
          }
        </div>
      )}

      {/* Configuration */}
      {!isGenerating && !isCompleted && (
        <LevelSetConfig
          config={config}
          onConfigChange={handleConfigChange}
          difficultyPoints={difficultyPoints}
          disabled={isGenerating}
        />
      )}

      {/* Progress - Single Set Mode */}
      {!isMultiSetMode && (isGenerating || isCompleted || progress.status === 'cancelled' || progress.status === 'error') && (
        <GenerationProgress state={progress} onCancel={handleCancel} />
      )}

      {/* Progress - Multi-Set Mode */}
      {isMultiSetMode && multiSetProgress.status !== 'idle' && (
        <MultiSetProgressDisplay />
      )}

      {/* Multi-Set Completion Summary */}
      {isMultiSetMode && isCompleted && generatedLevelSets.length > 0 && (
        <div className="bg-green-900/30 border border-green-600 rounded-lg p-4 space-y-2">
          <div className="flex items-center gap-2 text-green-400 font-medium">
            <span>🎉</span>
            <span>다중 세트 생성 완료!</span>
          </div>
          <div className="text-sm text-gray-300">
            <span className="text-green-400 font-bold">{generatedLevelSets.length}</span>개 세트,
            총 <span className="text-green-400 font-bold">
              {generatedLevelSets.reduce((sum, s) => sum + s.levels.length, 0)}
            </span>개 레벨이 자동으로 저장되었습니다.
          </div>
          <div className="text-xs text-gray-400">
            로컬 레벨 브라우저에서 생성된 레벨들을 확인할 수 있습니다.
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {!isGenerating && !isCompleted && !hasError && (
          <Button
            onClick={isMultiSetMode ? handleStartMultiSetGeneration : handleStartGeneration}
            className="flex-1"
          >
            {isMultiSetMode ? (
              <>🚀 {multiSetConfig.setCount}개 세트 생성 시작 ({config.levelCount * multiSetConfig.setCount}개 레벨)</>
            ) : (
              <>🚀 레벨 세트 생성 시작</>
            )}
          </Button>
        )}

        {!isMultiSetMode && isCompleted && generatedLevelSet && (
          <>
            <Button onClick={handleSave} className="flex-1">
              💾 저장
            </Button>
            <Button onClick={handleExport} variant="secondary" className="flex-1">
              📥 내보내기
            </Button>
            <Button onClick={handleReset} variant="danger">
              🔄 새로 만들기
            </Button>
          </>
        )}

        {isMultiSetMode && isCompleted && (
          <Button onClick={handleReset} className="flex-1">
            🔄 새 세트 만들기
          </Button>
        )}

        {hasError && (
          <Button onClick={handleReset} className="flex-1">
            🔄 다시 시도
          </Button>
        )}
      </div>
    </div>
  );
}
