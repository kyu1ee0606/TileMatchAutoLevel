import { useLevelStore } from '../../stores/levelStore';
import { useSimulationStore } from '../../stores/simulationStore';
import { SimulationGrid } from './SimulationGrid';
import { PlaybackControls } from './PlaybackControls';
import { Button } from '../ui/Button';
import clsx from 'clsx';

interface SimulationViewerProps {
  className?: string;
}

export function SimulationViewer({ className }: SimulationViewerProps) {
  const { level } = useLevelStore();
  const {
    results,
    isLoading,
    error,
    currentStep,
    fetchSimulation,
    clearResults,
  } = useSimulationStore();

  // Refresh simulation
  const handleRefresh = () => {
    clearResults();
    fetchSimulation(level);
  };

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      {/* Header */}
      <div className="flex items-center justify-between bg-gray-800 rounded-lg px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="text-xl">🎬</span>
          <h2 className="text-lg font-semibold text-white">시뮬레이션 뷰어</h2>
          {results && (
            <span className="text-sm text-gray-400">
              ({results.bot_results.length}개 봇 프로필)
            </span>
          )}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={handleRefresh}
          disabled={isLoading}
        >
          🔄 새로고침
        </Button>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-16 bg-gray-800 rounded-lg">
          <div className="animate-spin w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full" />
          <p className="mt-4 text-gray-400">시뮬레이션 실행 중...</p>
        </div>
      )}

      {/* Error state */}
      {!isLoading && error && (
        <div className="flex flex-col items-center justify-center py-16 bg-gray-800 rounded-lg">
          <span className="text-5xl mb-4">⚠️</span>
          <p className="text-red-400 mb-4 text-lg">{error}</p>
          <Button variant="primary" onClick={handleRefresh}>
            다시 시도
          </Button>
        </div>
      )}

      {/* Results */}
      {!isLoading && !error && results && (
        <>
          {/* Playback controls - 상단에 배치 */}
          <div className="bg-gray-800 rounded-lg p-4">
            <PlaybackControls />
          </div>

          {/* Bot simulation grids */}
          <SimulationGrid
            levelJson={level}
            results={results}
            currentStep={currentStep}
            className="bg-gray-800 rounded-lg p-4"
          />
        </>
      )}

      {/* Initial waiting state (before first load) */}
      {!isLoading && !error && !results && (
        <div className="flex flex-col items-center justify-center py-16 bg-gray-800 rounded-lg">
          <span className="text-5xl mb-4">🎮</span>
          <p className="text-gray-400 mb-4">시뮬레이션을 시작하려면 새로고침을 클릭하세요</p>
          <Button variant="primary" onClick={handleRefresh}>
            🎬 시뮬레이션 시작
          </Button>
        </div>
      )}
    </div>
  );
}
