/**
 * Production Progress Component
 * 프로덕션 생성 진행 상태 표시
 */

import { ProductionGenerationProgress } from '../../types/production';
import { Button } from '../ui';

interface ProductionProgressProps {
  progress: ProductionGenerationProgress;
  onPause?: () => void;
  onResume?: () => void;
}

export function ProductionProgress({
  progress,
  onPause,
  onResume,
}: ProductionProgressProps) {
  const percent = progress.total_levels > 0
    ? (progress.completed_levels / progress.total_levels) * 100
    : 0;

  const formatTime = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);

    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    }
    if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`;
    }
    return `${seconds}s`;
  };

  const statusColors = {
    idle: 'text-gray-400',
    generating: 'text-indigo-400',
    paused: 'text-yellow-400',
    completed: 'text-green-400',
    error: 'text-red-400',
  };

  const statusLabels = {
    idle: '대기',
    generating: '생성 중',
    paused: '일시 정지',
    completed: '완료',
    error: '오류',
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-medium text-white">생성 진행 상태</h3>
        <span className={`text-sm ${statusColors[progress.status]}`}>
          {statusLabels[progress.status]}
        </span>
      </div>

      {/* Main Progress */}
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="text-gray-400">
            레벨 {progress.completed_levels} / {progress.total_levels}
          </span>
          <span className="text-gray-300">{percent.toFixed(1)}%</span>
        </div>
        <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${
              progress.status === 'error' ? 'bg-red-500' :
              progress.status === 'completed' ? 'bg-green-500' :
              progress.status === 'paused' ? 'bg-yellow-500' :
              'bg-indigo-500'
            }`}
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>

      {/* Set Progress */}
      <div className="text-sm text-gray-400">
        세트 {progress.completed_sets} / {progress.total_sets}
        {progress.status === 'generating' && (
          <span className="ml-2 text-indigo-400">
            (현재: 세트 {progress.current_set_index + 1})
          </span>
        )}
      </div>

      {/* Time Stats */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-gray-400">경과: </span>
          <span className="text-white">{formatTime(progress.elapsed_ms)}</span>
        </div>
        <div>
          <span className="text-gray-400">예상 남은: </span>
          <span className="text-white">{formatTime(progress.estimated_remaining_ms)}</span>
        </div>
      </div>

      {/* Failed Levels */}
      {progress.failed_levels.length > 0 && (
        <div className="text-sm">
          <span className="text-red-400">
            실패: {progress.failed_levels.length}개
          </span>
          <span className="text-gray-500 ml-2">
            ({progress.failed_levels.slice(0, 5).join(', ')}
            {progress.failed_levels.length > 5 && '...'})
          </span>
        </div>
      )}

      {/* Error Message */}
      {progress.last_error && (
        <div className="p-2 bg-red-900/50 rounded text-sm text-red-300">
          오류: {progress.last_error}
        </div>
      )}

      {/* Checkpoint Info */}
      {progress.last_checkpoint_at && (
        <div className="text-xs text-gray-500">
          마지막 체크포인트: {new Date(progress.last_checkpoint_at).toLocaleTimeString()}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        {progress.status === 'generating' && onPause && (
          <Button onClick={onPause} variant="secondary" size="sm" className="flex-1">
            일시 정지
          </Button>
        )}
        {progress.status === 'paused' && onResume && (
          <Button onClick={onResume} size="sm" className="flex-1">
            계속 생성
          </Button>
        )}
      </div>
    </div>
  );
}
