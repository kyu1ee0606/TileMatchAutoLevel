import { useSimulationStore } from '../../stores/simulationStore';
import type { PlaybackSpeed } from '../../types/simulation';
import { Button } from '../ui/Button';
import clsx from 'clsx';

interface PlaybackControlsProps {
  className?: string;
}

const SPEED_OPTIONS: PlaybackSpeed[] = [1, 2, 4];

export function PlaybackControls({ className }: PlaybackControlsProps) {
  const {
    results,
    isPlaying,
    currentStep,
    playbackSpeed,
    togglePlayPause,
    stepBackward,
    stepForward,
    goToStart,
    goToEnd,
    seekTo,
    setPlaybackSpeed,
  } = useSimulationStore();

  if (!results) return null;

  const maxStep = results.max_steps;
  const progress = maxStep > 0 ? (currentStep / maxStep) * 100 : 0;

  return (
    <div className={clsx('bg-gray-800 rounded-lg p-3', className)}>
      {/* Progress bar with seek */}
      <div className="mb-3">
        <div className="relative h-2 bg-gray-700 rounded-full cursor-pointer group">
          <div
            className="absolute h-full bg-blue-500 rounded-full transition-all duration-100"
            style={{ width: `${progress}%` }}
          />
          <input
            type="range"
            min={0}
            max={maxStep}
            value={currentStep}
            onChange={(e) => seekTo(parseInt(e.target.value))}
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
          />
          {/* Thumb indicator */}
          <div
            className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-400 rounded-full shadow-md transition-all group-hover:scale-125"
            style={{ left: `calc(${progress}% - 6px)` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-gray-400 mt-1">
          <span>Step {currentStep}</span>
          <span>Total {maxStep}</span>
        </div>
      </div>

      {/* Control buttons */}
      <div className="flex items-center justify-center gap-2">
        {/* Go to start */}
        <Button
          variant="secondary"
          size="sm"
          onClick={goToStart}
          disabled={currentStep === 0}
          className="px-2"
          title="처음으로"
        >
          ⏮
        </Button>

        {/* Step backward */}
        <Button
          variant="secondary"
          size="sm"
          onClick={stepBackward}
          disabled={currentStep === 0}
          className="px-2"
          title="이전 스텝"
        >
          ◀
        </Button>

        {/* Play/Pause */}
        <Button
          variant="primary"
          size="sm"
          onClick={togglePlayPause}
          disabled={currentStep >= maxStep && !isPlaying}
          className="px-4 min-w-[60px]"
        >
          {isPlaying ? '⏸ 일시정지' : '▶ 재생'}
        </Button>

        {/* Step forward */}
        <Button
          variant="secondary"
          size="sm"
          onClick={stepForward}
          disabled={currentStep >= maxStep}
          className="px-2"
          title="다음 스텝"
        >
          ▶
        </Button>

        {/* Go to end */}
        <Button
          variant="secondary"
          size="sm"
          onClick={goToEnd}
          disabled={currentStep >= maxStep}
          className="px-2"
          title="끝으로"
        >
          ⏭
        </Button>

        {/* Speed control */}
        <div className="ml-4 flex items-center gap-1">
          <span className="text-xs text-gray-400 mr-1">속도:</span>
          {SPEED_OPTIONS.map((speed) => (
            <button
              key={speed}
              onClick={() => setPlaybackSpeed(speed)}
              className={clsx(
                'px-2 py-1 text-xs rounded transition-colors',
                playbackSpeed === speed
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
              )}
            >
              {speed}x
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
