/**
 * Production Batch List Component
 * 프로덕션 배치 목록 표시
 */

import { ProductionBatch } from '../../types/production';

interface ProductionBatchListProps {
  batches: ProductionBatch[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ProductionBatchList({
  batches,
  selectedId,
  onSelect,
  onDelete,
}: ProductionBatchListProps) {
  if (batches.length === 0) {
    return (
      <div className="text-center text-gray-500 py-4">
        배치가 없습니다.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {batches.map((batch) => {
        const progress = batch.total_levels > 0
          ? (batch.generated_count / batch.total_levels) * 100
          : 0;

        return (
          <div
            key={batch.id}
            className={`p-3 rounded-lg cursor-pointer transition-colors ${
              selectedId === batch.id
                ? 'bg-indigo-900/50 border border-indigo-500'
                : 'bg-gray-800 hover:bg-gray-700'
            }`}
            onClick={() => onSelect(batch.id)}
          >
            <div className="flex justify-between items-start">
              <div>
                <div className="text-sm font-medium text-white">{batch.name}</div>
                <div className="text-xs text-gray-400">
                  {new Date(batch.created_at).toLocaleDateString()}
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(batch.id);
                }}
                className="text-gray-500 hover:text-red-400 text-xs"
              >
                삭제
              </button>
            </div>

            {/* Progress Bar */}
            <div className="mt-2">
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span>{batch.generated_count}/{batch.total_levels}</span>
                <span>{progress.toFixed(0)}%</span>
              </div>
              <div className="h-1 bg-gray-700 rounded-full overflow-hidden">
                <div
                  className="h-full bg-indigo-500"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>

            {/* Stats */}
            <div className="mt-2 flex gap-3 text-xs">
              <span className="text-green-400">승인: {batch.approved_count}</span>
              <span className="text-yellow-400">테스트: {batch.playtest_count}</span>
              <span className="text-red-400">거부: {batch.rejected_count}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
