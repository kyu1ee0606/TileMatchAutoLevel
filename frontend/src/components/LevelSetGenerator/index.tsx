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
  type DifficultyPoint,
  type LevelSetGenerationConfig,
  type GenerationProgressState,
  type GenerationResultItem,
  type LevelSet,
} from '../../types/levelSet';
import type { LevelJSON, DifficultyGrade, GenerationParams } from '../../types';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';

interface LevelSetGeneratorProps {
  onLevelSetCreated?: (levelSet: LevelSet) => void;
}

const DEFAULT_CONFIG: LevelSetGenerationConfig = {
  setName: '',
  levelCount: 10,
  difficultyPoints: createDefaultDifficultyPoints(10),
  baseParams: {
    grid_size: [7, 7],
    max_layers: 7,
    tile_types: ['t0', 't2', 't4', 't5', 't6'],
    obstacle_types: [],  // 수동 모드일 때 사용
    goals: [{ type: 'craft', direction: 's', count: 3 }],
    symmetry_mode: 'none',
    pattern_type: 'geometric',  // 기본값: 기하학적 패턴
  },
  // 기믹 자동 선택 관련 - 기본값: 자동 모드
  gimmickMode: 'auto',
  availableGimmicks: ['chain', 'frog', 'ice'],  // 기본 기믹 풀
  levelGimmickOverrides: [],
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

          // Debug: log generation parameters
          const gimmickInfo = useAutoGimmicks ? `auto(pool: ${autoGimmickPool?.join(',')})` : `manual(${baseParams.obstacle_types?.join(',') || 'none'})`;
          console.log(`Level ${levelIndex + 1}: grade=${plan.grade}, diff=${plan.targetDifficulty}, gimmicks=${gimmickInfo}`);

          try {
            // Prepare gimmick options for auto selection
            const gimmickOpts = useAutoGimmicks ? {
              auto_select_gimmicks: true,
              available_gimmicks: autoGimmickPool,
            } : undefined;

            // Generate with strict grade matching - retry with adjusted difficulty until grade matches
            const MAX_RETRIES = 30;
            let result = await generateLevel(baseParams, gimmickOpts);
            let retryCount = 0;
            let difficultyAdjustment = 0;

            while (result.grade !== plan.grade && retryCount < MAX_RETRIES) {
              retryCount++;

              // Adjust target difficulty based on grade mismatch
              const gradeOrder = ['S', 'A', 'B', 'C', 'D'];
              const targetGradeIdx = gradeOrder.indexOf(plan.grade);
              const actualGradeIdx = gradeOrder.indexOf(result.grade);

              if (actualGradeIdx < targetGradeIdx) {
                // Got easier grade, increase difficulty
                difficultyAdjustment += 0.05;
              } else {
                // Got harder grade, decrease difficulty
                difficultyAdjustment -= 0.05;
              }

              // Clamp adjustment
              difficultyAdjustment = Math.max(-0.15, Math.min(0.15, difficultyAdjustment));

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

              console.log(`Level ${levelIndex + 1}: Grade mismatch (wanted ${plan.grade}, got ${result.grade}, diff=${(result.actual_difficulty * 100).toFixed(1)}%), retry ${retryCount}/${MAX_RETRIES} (adj: ${difficultyAdjustment > 0 ? '+' : ''}${(difficultyAdjustment * 100).toFixed(0)}%)`);
              result = await generateLevel(adjustedParams, gimmickOpts);
            }

            if (result.grade !== plan.grade) {
              console.warn(`Level ${levelIndex + 1}: Could not achieve grade ${plan.grade} after ${MAX_RETRIES} retries, got ${result.grade}`);
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
    setGeneratedLevelSet(null);
  }, []);

  const isGenerating = progress.status === 'generating';
  const isCompleted = progress.status === 'completed';

  // Check if difficulty ceiling warning is needed
  const maxDifficulty = Math.max(...difficultyPoints.map(p => p.difficulty));
  const showDifficultyCeilingWarning = maxDifficulty > 0.4 && (
    (config.gimmickMode === 'manual' && (!config.baseParams.obstacle_types || config.baseParams.obstacle_types.length === 0)) ||
    ((config.gimmickMode === 'auto' || config.gimmickMode === 'hybrid') && (!config.availableGimmicks || config.availableGimmicks.length === 0))
  );

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

      {/* Progress */}
      {(isGenerating || isCompleted || progress.status === 'cancelled' || progress.status === 'error') && (
        <GenerationProgress state={progress} onCancel={handleCancel} />
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {!isGenerating && !isCompleted && (
          <Button onClick={handleStartGeneration} className="flex-1">
            🚀 레벨 세트 생성 시작
          </Button>
        )}

        {isCompleted && generatedLevelSet && (
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

        {(progress.status === 'cancelled' || progress.status === 'error') && (
          <Button onClick={handleReset} className="flex-1">
            🔄 다시 시도
          </Button>
        )}
      </div>
    </div>
  );
}
