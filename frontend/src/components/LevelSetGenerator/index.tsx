import { useState, useCallback, useRef } from 'react';
import { DifficultyGraph } from './DifficultyGraph';
import { LevelSetConfig, type ValidationOptions } from './LevelSetConfig';
import { GenerationProgress } from './GenerationProgress';
import { generateLevel, generateValidatedLevel } from '../../api/generate';
import { saveLevelSet, exportLevelSetAsFile } from '../../api/levelSet';
import {
  interpolateDifficulties,
  createDefaultDifficultyPoints,
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
    obstacle_types: [],  // 기본값: 장애물 없음
    goals: [{ type: 'craft', direction: 's', count: 3 }],
    symmetry_mode: 'none',
    pattern_type: 'geometric',  // 기본값: 기하학적 패턴
  },
};

export function LevelSetGenerator({ onLevelSetCreated }: LevelSetGeneratorProps) {
  const { addNotification } = useUIStore();
  const [config, setConfig] = useState<LevelSetGenerationConfig>(DEFAULT_CONFIG);
  const [difficultyPoints, setDifficultyPoints] = useState<DifficultyPoint[]>(
    createDefaultDifficultyPoints(DEFAULT_CONFIG.levelCount)
  );
  const [validationOptions, setValidationOptions] = useState<ValidationOptions>({
    enabled: true,  // Default to enabled for better difficulty matching
    max_retries: 5,
    tolerance: 15,
  });
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

  // Start generation
  const handleStartGeneration = useCallback(async () => {
    if (!config.setName.trim()) {
      addNotification('error', '세트 이름을 입력해주세요');
      return;
    }

    const difficulties = interpolateDifficulties(difficultyPoints, config.levelCount);

    // Initialize progress state
    const initialResults: GenerationResultItem[] = difficulties.map((targetDiff, i) => ({
      levelIndex: i + 1,
      targetDifficulty: targetDiff,
      actualDifficulty: 0,
      grade: 'S' as DifficultyGrade,
      status: 'pending',
    }));

    setProgress({
      status: 'generating',
      total: config.levelCount,
      current: 0,
      results: initialResults,
    });
    setGeneratedLevelSet(null);

    // Create abort controller
    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    const generatedLevels: LevelJSON[] = [];
    const actualDifficulties: number[] = [];
    const grades: DifficultyGrade[] = [];

    try {
      for (let i = 0; i < config.levelCount; i++) {
        if (signal.aborted) {
          throw new Error('cancelled');
        }

        const targetDifficulty = difficulties[i];

        // Update progress to show generating
        setProgress((prev) => ({
          ...prev,
          current: i + 1,
          results: prev.results.map((r, idx) =>
            idx === i ? { ...r, status: 'generating' } : r
          ),
        }));

        try {
          const params: GenerationParams = {
            ...config.baseParams,
            target_difficulty: targetDifficulty,
          };

          let result;
          let matchScore = 0;
          let validationPassed = false;

          if (validationOptions.enabled) {
            // Use validated generation API
            const validatedResult = await generateValidatedLevel(params, {
              max_retries: validationOptions.max_retries,
              tolerance: validationOptions.tolerance,
              simulation_iterations: 30,
            });
            result = {
              level_json: validatedResult.level_json,
              actual_difficulty: validatedResult.actual_difficulty,
              grade: validatedResult.grade as DifficultyGrade,
              generation_time_ms: validatedResult.generation_time_ms,
            };
            matchScore = validatedResult.match_score;
            validationPassed = validatedResult.validation_passed;
          } else {
            // Use standard generation API
            result = await generateLevel(params);
          }

          generatedLevels.push(result.level_json);
          actualDifficulties.push(result.actual_difficulty);
          grades.push(result.grade);

          // Update progress with success (include match info if validated)
          setProgress((prev) => ({
            ...prev,
            results: prev.results.map((r, idx) =>
              idx === i
                ? {
                    ...r,
                    status: 'success',
                    actualDifficulty: result.actual_difficulty,
                    grade: result.grade,
                    levelJson: result.level_json,
                    // Store validation info for display
                    matchScore: validationOptions.enabled ? matchScore : undefined,
                    validationPassed: validationOptions.enabled ? validationPassed : undefined,
                  }
                : r
            ),
          }));
        } catch (err) {
          // Update progress with failure
          setProgress((prev) => ({
            ...prev,
            results: prev.results.map((r, idx) =>
              idx === i
                ? {
                    ...r,
                    status: 'failed',
                    error: err instanceof Error ? err.message : '생성 실패',
                  }
                : r
            ),
          }));

          // Continue with next level
          generatedLevels.push(null as unknown as LevelJSON);
          actualDifficulties.push(0);
          grades.push('D');
        }
      }

      // Filter out failed levels
      const successfulLevels = generatedLevels.filter((l) => l !== null);
      const successfulDifficulties = actualDifficulties.filter((_, i) => generatedLevels[i] !== null);
      const successfulGrades = grades.filter((_, i) => generatedLevels[i] !== null);

      if (successfulLevels.length === 0) {
        throw new Error('모든 레벨 생성이 실패했습니다');
      }

      // Create level set
      const levelSet: LevelSet = {
        metadata: {
          id: `set_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
          name: config.setName,
          created_at: new Date().toISOString(),
          level_count: successfulLevels.length,
          difficulty_profile: difficulties.slice(0, successfulLevels.length),
          actual_difficulties: successfulDifficulties,
          grades: successfulGrades,
          generation_config: config.baseParams,
        },
        levels: successfulLevels,
      };

      setGeneratedLevelSet(levelSet);

      setProgress((prev) => ({
        ...prev,
        status: 'completed',
      }));

      addNotification('success', `레벨 세트 "${config.setName}" 생성 완료!`);
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

  return (
    <div className="space-y-4">
      {/* Difficulty Graph */}
      <DifficultyGraph
        levelCount={config.levelCount}
        points={difficultyPoints}
        onPointsChange={setDifficultyPoints}
      />

      {/* Configuration */}
      {!isGenerating && !isCompleted && (
        <LevelSetConfig
          config={config}
          onConfigChange={handleConfigChange}
          validationOptions={validationOptions}
          onValidationOptionsChange={setValidationOptions}
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
