import { useState } from 'react';
import { ScoreDisplay } from './ScoreDisplay';
import { MetricsTable } from './MetricsTable';
import { CollapsiblePanel } from '../ui/CollapsiblePanel';
import { Skeleton } from '../common/Skeleton';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { analyzeLevel } from '../../api/analyze';
import { simulateLevel, generateValidatedLevel } from '../../api/generate';
import type { SimulationResult, LevelJSON, SymmetryMode, PatternType } from '../../types';
import { Button, Tooltip } from '../ui';
import { Search, Dices, Lightbulb } from 'lucide-react';
import { AutoPlayPanel } from '../AutoPlayPanel';

// Skeleton for analysis loading state
function AnalysisSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      {/* Score Display Skeleton */}
      <div className="flex items-center justify-center gap-6 py-4">
        <Skeleton variant="circular" width={80} height={80} />
        <div className="space-y-2">
          <Skeleton variant="text" width={60} height={32} />
          <Skeleton variant="text" width={100} height={16} />
        </div>
      </div>

      {/* Metrics Table Skeleton */}
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex justify-between items-center py-2 border-b border-gray-700">
            <Skeleton variant="text" width={80} height={16} />
            <Skeleton variant="text" width={60} height={16} />
          </div>
        ))}
      </div>

      {/* Recommendations Skeleton */}
      <div className="space-y-2">
        <Skeleton variant="text" width={100} height={18} />
        <div className="space-y-1">
          {Array.from({ length: 2 }).map((_, i) => (
            <Skeleton key={i} variant="text" height={14} className="w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}

// Skeleton for simulation loading state
function SimulationSkeleton() {
  return (
    <div className="border-t border-gray-700 pt-4 animate-pulse">
      <Skeleton variant="text" width={120} height={18} className="mb-2" />
      <div className="bg-purple-900/30 rounded-lg p-3">
        <div className="grid grid-cols-2 gap-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <Skeleton variant="text" width={60} height={14} />
              <Skeleton variant="text" width={40} height={14} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface DifficultyPanelProps {
  className?: string;
}

export function DifficultyPanel({ className }: DifficultyPanelProps) {
  const { level, analysisResult, isAnalyzing, setAnalysisResult, setIsAnalyzing, setLevel } =
    useLevelStore();
  const { addNotification } = useUIStore();

  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenerationProgress, setRegenerationProgress] = useState<{
    current: number;
    total: number;
    bestScore: number;
  } | undefined>(undefined);

  // Get target difficulty from level metadata
  const targetDifficulty = (level as any).target_difficulty ?? (level as any).targetDifficulty;

  const handleAnalyze = async () => {
    setIsAnalyzing(true);
    try {
      const result = await analyzeLevel(level);
      setAnalysisResult(result);
      addNotification('success', '난이도 분석이 완료되었습니다');
    } catch (error) {
      console.error('Analysis failed:', error);
      addNotification('error', '난이도 분석에 실패했습니다');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSimulate = async () => {
    setIsSimulating(true);
    try {
      const result = await simulateLevel(level, 500, 'greedy');
      setSimulationResult(result);
      addNotification('success', '시뮬레이션이 완료되었습니다');
    } catch (error) {
      console.error('Simulation failed:', error);
      addNotification('error', '시뮬레이션에 실패했습니다');
    } finally {
      setIsSimulating(false);
    }
  };

  const handleRegenerate = async (attempts: number = 1) => {
    if (targetDifficulty === undefined) {
      addNotification('error', '레벨에 목표 난이도 정보가 없습니다');
      return;
    }

    setIsRegenerating(true);
    setRegenerationProgress({ current: 0, total: attempts, bestScore: 0 });

    try {
      // Extract generation parameters from current level
      // Use type assertion for extended properties that may exist at runtime
      const currentLevel = level as LevelJSON & {
        name?: string;
        id?: string;
        level_index?: number;
        goalCount?: Record<string, number>;
        symmetry_mode?: SymmetryMode;
        pattern_type?: PatternType;
      };

      // Get grid size from layer_0 if available
      const layer0 = currentLevel.layer_0;
      const gridWidth = layer0?.col ? parseInt(layer0.col, 10) : 7;
      const gridHeight = layer0?.row ? parseInt(layer0.row, 10) : 7;

      // Extract goals from current level's goalCount
      // goalCount format: { "craft_s": 3, "craft_n": 3, "stack_e": 2 }
      // Convert to goals format: [{ type: "craft", direction: "s", count: 3 }, ...]
      type GoalType = 'craft' | 'stack';
      type GoalDirection = 's' | 'n' | 'e' | 'w';
      let goals: Array<{ type: GoalType; direction: GoalDirection; count: number }> | undefined;
      if (currentLevel.goalCount) {
        goals = Object.entries(currentLevel.goalCount)
          .filter(([key]) => key.includes('_')) // Only process valid goal keys like "craft_s"
          .map(([key, count]) => {
            // Parse key like "craft_s" or "stack_n"
            const parts = key.split('_');
            return {
              type: parts[0] as GoalType,
              direction: parts[1] as GoalDirection,
              count
            };
          });
        console.log('Preserved goals from current level:', goals);
      }

      // Extract tile types from current level (e.g., ["t0", "t2", "t4", "t5", "t6"])
      const tileTypes: string[] = [];
      const obstacleTypes: string[] = [];
      const GIMMICK_TYPES = ['chain', 'ice', 'frog', 'bomb', 'link_e', 'link_w', 'link_n', 'link_s', 'curtain', 'grass'];

      // Scan all layers to extract tile types and gimmicks
      for (let i = 0; i < (currentLevel.layer ?? 8); i++) {
        const layerData = (currentLevel as any)[`layer_${i}`];
        if (layerData?.tiles) {
          Object.values(layerData.tiles).forEach((tileData: any) => {
            if (Array.isArray(tileData)) {
              // Extract tile type (e.g., "t0", "t2")
              const tileType = tileData[0];
              if (typeof tileType === 'string' && tileType.startsWith('t') && !tileTypes.includes(tileType)) {
                tileTypes.push(tileType);
              }
              // Extract gimmick (e.g., "chain", "ice", "frog")
              const gimmick = tileData[1];
              if (typeof gimmick === 'string' && gimmick && !obstacleTypes.includes(gimmick)) {
                // Normalize link gimmicks to just "link"
                const normalizedGimmick = gimmick.startsWith('link_') ? 'link' : gimmick;
                if (GIMMICK_TYPES.some(g => gimmick.startsWith(g.split('_')[0])) && !obstacleTypes.includes(normalizedGimmick)) {
                  obstacleTypes.push(normalizedGimmick);
                }
              }
            }
          });
        }
      }

      console.log('Extracted tile types:', tileTypes);
      console.log('Extracted obstacle types:', obstacleTypes);

      // Extract symmetry_mode and pattern_type from current level
      const symmetryMode: SymmetryMode | undefined = currentLevel.symmetry_mode;
      const patternType: PatternType | undefined = currentLevel.pattern_type;
      console.log('Preserved symmetry_mode:', symmetryMode);
      console.log('Preserved pattern_type:', patternType);

      // PARALLEL GENERATION: Generate all attempts concurrently and pick the best
      let bestResult: Awaited<ReturnType<typeof generateValidatedLevel>> | null = null;
      let bestMatchScore = 0;

      const regenParams = {
        target_difficulty: targetDifficulty,
        grid_size: [gridWidth, gridHeight] as [number, number],
        max_layers: currentLevel.layer ?? 8,
        goals: goals,
        tile_types: tileTypes.length > 0 ? tileTypes : undefined,
        obstacle_types: obstacleTypes.length > 0 ? obstacleTypes : undefined,
        symmetry_mode: symmetryMode,
        pattern_type: patternType,
      };
      const regenOptions = {
        max_retries: 5,
        tolerance: 15.0,
        simulation_iterations: 50,
        use_best_match: true,
      };

      // Run all attempts in parallel
      const attemptPromises = Array.from({ length: attempts }, (_, i) =>
        generateValidatedLevel(regenParams, regenOptions)
          .then(result => {
            // Track best result as results come in
            if (result.match_score > bestMatchScore) {
              bestMatchScore = result.match_score;
              bestResult = result;
            }
            setRegenerationProgress({
              current: i + 1,
              total: attempts,
              bestScore: bestMatchScore,
            });
            console.log(`Attempt ${i + 1}/${attempts}: match_score=${result.match_score.toFixed(1)}%, best=${bestMatchScore.toFixed(1)}%`);
            return result;
          })
          .catch(err => {
            console.error(`Regeneration attempt ${i + 1} failed:`, err);
            return null;
          })
      );

      const allResults = await Promise.allSettled(attemptPromises);

      // Final best selection (in case of race conditions in progress tracking)
      for (const r of allResults) {
        if (r.status === 'fulfilled' && r.value && r.value.match_score > bestMatchScore) {
          bestMatchScore = r.value.match_score;
          bestResult = r.value;
        }
      }

      if (!bestResult) {
        throw new Error('모든 재생성 시도가 실패했습니다');
      }

      // Preserve original level metadata (like name, id, level_index)
      // These are runtime properties added by the application
      // Also preserve symmetry_mode and pattern_type if they were in the original level
      const levelJson = bestResult.level_json as LevelJSON & {
        symmetry_mode?: SymmetryMode;
        pattern_type?: PatternType;
      };
      const newLevel = {
        ...levelJson,
        name: currentLevel.name,
        id: currentLevel.id,
        level_index: currentLevel.level_index,
        target_difficulty: targetDifficulty,
        // Preserve symmetry_mode and pattern_type (from backend response or original level)
        symmetry_mode: levelJson.symmetry_mode || symmetryMode,
        pattern_type: levelJson.pattern_type || patternType,
      } as LevelJSON;

      // Update the level in the store
      setLevel(newLevel);

      // Clear analysis results to show the new level needs re-analysis
      setAnalysisResult(null);
      setSimulationResult(null);

      const passStatus = bestResult.validation_passed ? '검증 통과 ✓' : '최선 결과';
      addNotification(
        'success',
        `레벨 재생성 완료! (${attempts}회 중 최적 선택, ${passStatus}, 일치도: ${bestMatchScore.toFixed(0)}%)`
      );
    } catch (error) {
      console.error('Regeneration failed:', error);
      addNotification('error', `레벨 재생성 실패: ${error instanceof Error ? error.message : '알 수 없는 오류'}`);
    } finally {
      setIsRegenerating(false);
      setRegenerationProgress(undefined);
    }
  };

  const headerButtons = (
    <div className="flex gap-2">
      <Tooltip content="타일 구성, 목표 달성 난이도 평가">
        <Button
          onClick={handleAnalyze}
          disabled={isAnalyzing}
          isLoading={isAnalyzing}
          variant="primary"
          size="sm"
          icon={<Search className="w-full h-full" />}
        >
          {isAnalyzing ? '분석 중...' : '분석'}
        </Button>
      </Tooltip>
      <Tooltip content="AI 플레이로 클리어율 측정">
        <Button
          onClick={handleSimulate}
          disabled={isSimulating}
          isLoading={isSimulating}
          variant="secondary"
          size="sm"
          icon={<Dices className="w-full h-full" />}
          className="!bg-purple-600 hover:!bg-purple-700"
        >
          {isSimulating ? '시뮬레이션 중...' : '시뮬레이션'}
        </Button>
      </Tooltip>
    </div>
  );

  return (
    <CollapsiblePanel
      title="난이도 분석"
      icon="📊"
      headerRight={headerButtons}
      className={className}
    >
      <div className="flex flex-col gap-4">
        {isAnalyzing ? (
          <AnalysisSkeleton />
        ) : analysisResult ? (
          <>
            <ScoreDisplay score={analysisResult.score} grade={analysisResult.grade} />
            <MetricsTable metrics={analysisResult.metrics} />

            {/* Recommendations */}
            {analysisResult.recommendations.length > 0 && (
              <div>
                <h3 className="text-sm font-medium text-gray-300 mb-2 flex items-center gap-1.5">
                  <Lightbulb className="w-4 h-4 text-yellow-400" />
                  권장사항
                </h3>
                <ul className="space-y-1">
                  {analysisResult.recommendations.map((rec, i) => (
                    <li key={i} className="text-sm text-gray-400 flex items-start gap-2">
                      <span className="text-yellow-500">•</span>
                      <span>{rec}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <div className="py-8 text-center">
            <div className="text-4xl mb-3 flex justify-center">
              <Search className="w-10 h-10 text-gray-500" />
            </div>
            <p className="text-gray-400 font-medium mb-2">레벨 난이도를 분석해보세요</p>
            <div className="text-sm text-gray-500 space-y-1">
              <p className="flex items-center justify-center gap-1.5">
                <Search className="w-3.5 h-3.5" />
                <span className="text-gray-400">분석</span>: 타일 구성, 목표 달성 난이도 평가
              </p>
              <p className="flex items-center justify-center gap-1.5">
                <Dices className="w-3.5 h-3.5" />
                <span className="text-gray-400">시뮬레이션</span>: AI 플레이로 클리어율 측정
              </p>
            </div>
          </div>
        )}

        {/* Simulation Results */}
        {isSimulating ? (
          <SimulationSkeleton />
        ) : simulationResult && (
          <div className="border-t border-gray-700 pt-4">
            <h3 className="text-sm font-medium text-gray-300 mb-2 flex items-center gap-1.5">
              <Dices className="w-4 h-4 text-purple-400" />
              시뮬레이션 결과
            </h3>
            <div className="bg-purple-900/50 rounded-lg p-3">
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <span className="text-gray-400">클리어율:</span>
                  <span className="ml-2 font-medium text-gray-200">
                    {(simulationResult.clear_rate * 100).toFixed(1)}%
                  </span>
                </div>
                <div>
                  <span className="text-gray-400">평균 이동:</span>
                  <span className="ml-2 font-medium text-gray-200">{simulationResult.avg_moves.toFixed(1)}</span>
                </div>
                <div>
                  <span className="text-gray-400">최소 이동:</span>
                  <span className="ml-2 font-medium text-gray-200">{simulationResult.min_moves}</span>
                </div>
                <div>
                  <span className="text-gray-400">최대 이동:</span>
                  <span className="ml-2 font-medium text-gray-200">{simulationResult.max_moves}</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* AutoPlay Analysis Panel */}
        <AutoPlayPanel
          className="border-t border-gray-700 pt-4"
          embedded
          targetDifficulty={targetDifficulty}
          onRegenerate={targetDifficulty !== undefined ? handleRegenerate : undefined}
          isRegenerating={isRegenerating}
          regenerationProgress={regenerationProgress}
        />
      </div>
    </CollapsiblePanel>
  );
}

export { ScoreDisplay } from './ScoreDisplay';
export { MetricsTable } from './MetricsTable';
