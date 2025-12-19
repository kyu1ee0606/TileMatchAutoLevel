import { useState } from 'react';
import { ScoreDisplay } from './ScoreDisplay';
import { MetricsTable } from './MetricsTable';
import { CollapsiblePanel } from '../ui/CollapsiblePanel';
import { Skeleton } from '../common/Skeleton';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { analyzeLevel } from '../../api/analyze';
import { simulateLevel } from '../../api/generate';
import type { SimulationResult } from '../../types';
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
  const { level, analysisResult, isAnalyzing, setAnalysisResult, setIsAnalyzing } =
    useLevelStore();
  const { addNotification } = useUIStore();

  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

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
        <AutoPlayPanel className="border-t border-gray-700 pt-4" embedded />
      </div>
    </CollapsiblePanel>
  );
}

export { ScoreDisplay } from './ScoreDisplay';
export { MetricsTable } from './MetricsTable';
