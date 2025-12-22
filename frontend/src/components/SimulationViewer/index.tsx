import { useState } from 'react';
import { useLevelStore } from '../../stores/levelStore';
import { useSimulationStore } from '../../stores/simulationStore';
import { SimulationGrid } from './SimulationGrid';
import { PlaybackControls } from './PlaybackControls';
import { Button } from '../ui/Button';
import { AlertTriangle, CheckCircle, Shuffle } from 'lucide-react';
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

  // Seed management
  const [useRandomSeed, setUseRandomSeed] = useState(false);
  const [customSeed, setCustomSeed] = useState<number | undefined>(undefined);

  // Generate random seed
  const generateRandomSeed = () => {
    const newSeed = Math.floor(Math.random() * 1000000);
    setCustomSeed(newSeed);
    return newSeed;
  };

  // Refresh simulation with current seed settings
  const handleRefresh = () => {
    clearResults();
    const seed = useRandomSeed ? generateRandomSeed() : customSeed;
    fetchSimulation(level, undefined, undefined, seed);
  };

  return (
    <div className={clsx('flex flex-col gap-4', className)}>
      {/* Header */}
      <div className="bg-gray-800 rounded-lg px-4 py-3 space-y-3">
        <div className="flex items-center justify-between">
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

        {/* Seed Controls */}
        <div className="flex items-center gap-3 pt-2 border-t border-gray-700">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="randomSeed"
              checked={useRandomSeed}
              onChange={(e) => setUseRandomSeed(e.target.checked)}
              className="w-4 h-4 rounded border-gray-600 bg-gray-700 text-blue-500 focus:ring-2 focus:ring-blue-500"
            />
            <label htmlFor="randomSeed" className="text-sm text-gray-300 cursor-pointer">
              매 시뮬레이션마다 랜덤 시드
            </label>
          </div>

          {!useRandomSeed && (
            <>
              <div className="flex items-center gap-2">
                <label className="text-sm text-gray-400">시드:</label>
                <input
                  type="number"
                  value={customSeed ?? ''}
                  onChange={(e) => setCustomSeed(e.target.value ? parseInt(e.target.value) : undefined)}
                  placeholder="비어있으면 랜덤"
                  className="w-32 px-2 py-1 text-sm bg-gray-700 border border-gray-600 rounded text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setCustomSeed(generateRandomSeed())}
                className="flex items-center gap-1"
              >
                <Shuffle className="w-4 h-4" />
                랜덤 생성
              </Button>
            </>
          )}

          {customSeed !== undefined && (
            <span className="text-xs text-gray-500">
              현재 시드: {customSeed}
            </span>
          )}
        </div>
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
          {/* Tile count validation warning from simulation */}
          {results.metadata?.tile_count_valid !== undefined && (
            <div
              className={clsx(
                'flex items-center gap-2 px-4 py-3 rounded-lg text-sm',
                results.metadata.tile_count_valid
                  ? 'bg-green-900/30 border border-green-700 text-green-300'
                  : 'bg-red-900/30 border border-red-600 text-red-300'
              )}
            >
              {results.metadata.tile_count_valid ? (
                <CheckCircle className="w-5 h-5 text-green-400 flex-shrink-0" />
              ) : (
                <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />
              )}
              <span className="font-medium">{String(results.metadata.tile_count_message)}</span>
              {!results.metadata.tile_count_valid && (
                <span className="text-red-400 ml-auto">
                  클리어 불가능한 레벨입니다
                </span>
              )}
            </div>
          )}

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
