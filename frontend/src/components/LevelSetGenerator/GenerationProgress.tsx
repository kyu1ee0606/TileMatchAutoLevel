import type { GenerationProgressState, GenerationResultItem } from '../../types/levelSet';
import { getGradeColor } from '../../utils/helpers';
import { Button } from '../ui';

interface GenerationProgressProps {
  state: GenerationProgressState;
  onCancel: () => void;
}

export function GenerationProgress({ state, onCancel }: GenerationProgressProps) {
  const { status, current, total, results, error } = state;
  const progress = total > 0 ? (current / total) * 100 : 0;

  const successCount = results.filter((r) => r.status === 'success').length;
  const failedCount = results.filter((r) => r.status === 'failed').length;

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      {/* Header */}
      <div className="flex justify-between items-center mb-4">
        <h3 className="text-lg font-semibold text-white">레벨 세트 생성</h3>
        {status === 'generating' && (
          <Button size="sm" variant="danger" onClick={onCancel}>
            취소
          </Button>
        )}
      </div>

      {/* Status */}
      <div className="mb-4">
        {status === 'idle' && (
          <p className="text-gray-400">생성 준비 중...</p>
        )}
        {status === 'generating' && (
          <p className="text-blue-400">
            레벨 {current}/{total} 생성 중...
          </p>
        )}
        {status === 'completed' && (
          <p className="text-green-400">
            ✅ 생성 완료! {successCount}개 성공, {failedCount}개 실패
          </p>
        )}
        {status === 'cancelled' && (
          <p className="text-yellow-400">⚠️ 생성이 취소되었습니다</p>
        )}
        {status === 'error' && (
          <p className="text-red-400">❌ 오류: {error}</p>
        )}
      </div>

      {/* Progress Bar */}
      <div className="mb-4">
        <div className="h-4 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full transition-all duration-300 ease-out"
            style={{
              width: `${progress}%`,
              backgroundColor:
                status === 'completed'
                  ? '#22c55e'
                  : status === 'error' || status === 'cancelled'
                  ? '#ef4444'
                  : '#3b82f6',
            }}
          />
        </div>
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>{current}/{total}</span>
          <span>{Math.round(progress)}%</span>
        </div>
      </div>

      {/* Results Grid */}
      {results.length > 0 && (
        <div className="max-h-48 overflow-y-auto">
          <div className="grid grid-cols-5 gap-2">
            {results.map((result) => (
              <ResultItem key={result.levelIndex} result={result} />
            ))}
          </div>
        </div>
      )}

      {/* Summary */}
      {status === 'completed' && results.length > 0 && (
        <div className="mt-4 pt-4 border-t border-gray-700">
          <GradeSummary results={results} />
        </div>
      )}
    </div>
  );
}

function ResultItem({ result }: { result: GenerationResultItem }) {
  const { levelIndex, status, grade, actualDifficulty, targetDifficulty, matchScore, validationPassed } = result;

  let bgColor = 'bg-gray-700';

  if (status === 'success') {
    bgColor = 'bg-opacity-50';
  } else if (status === 'failed') {
    bgColor = 'bg-red-900/50';
  } else if (status === 'generating') {
    bgColor = 'bg-blue-900/50';
  }

  // Determine validation indicator
  const getValidationIndicator = () => {
    if (matchScore === undefined) return null;
    if (validationPassed) return { icon: '✓', color: 'text-green-400' };
    if (matchScore >= 70) return { icon: '~', color: 'text-yellow-400' };
    return { icon: '!', color: 'text-red-400' };
  };
  const validation = getValidationIndicator();

  const tooltipParts = [];
  if (status === 'success') {
    tooltipParts.push(`목표: ${Math.round(targetDifficulty * 100)}% → 실제: ${Math.round(actualDifficulty * 100)}%`);
    if (matchScore !== undefined) {
      tooltipParts.push(`매치 점수: ${Math.round(matchScore)}%`);
      tooltipParts.push(validationPassed ? '검증 통과' : '검증 미통과');
    }
  } else if (status === 'failed') {
    tooltipParts.push(result.error || '생성 실패');
  }

  return (
    <div
      className={`relative p-2 rounded text-center ${bgColor}`}
      style={status === 'success' ? { backgroundColor: `${getGradeColor(grade)}33` } : {}}
      title={tooltipParts.join('\n')}
    >
      <div className="text-xs text-gray-400 mb-1">Lv.{levelIndex}</div>
      {status === 'success' ? (
        <div className="relative">
          <div
            className="text-lg font-bold"
            style={{ color: getGradeColor(grade) }}
          >
            {grade}
          </div>
          {validation && (
            <span className={`absolute -top-1 -right-1 text-[10px] ${validation.color}`}>
              {validation.icon}
            </span>
          )}
        </div>
      ) : status === 'generating' ? (
        <div className="text-lg text-blue-400 animate-spin">⟳</div>
      ) : status === 'failed' ? (
        <div className="text-lg text-red-400">✕</div>
      ) : (
        <div className="text-lg text-gray-500">○</div>
      )}
    </div>
  );
}

function GradeSummary({ results }: { results: GenerationResultItem[] }) {
  const grades = ['S', 'A', 'B', 'C', 'D'] as const;
  const gradeCounts = grades.reduce((acc, grade) => {
    acc[grade] = results.filter((r) => r.status === 'success' && r.grade === grade).length;
    return acc;
  }, {} as Record<string, number>);

  const avgDifficulty =
    results
      .filter((r) => r.status === 'success')
      .reduce((sum, r) => sum + r.actualDifficulty, 0) /
    Math.max(1, results.filter((r) => r.status === 'success').length);

  return (
    <div className="flex justify-between items-center">
      <div className="flex gap-2">
        {grades.map((grade) => (
          <div
            key={grade}
            className="flex items-center gap-1 px-2 py-1 rounded text-xs"
            style={{
              backgroundColor: `${getGradeColor(grade)}33`,
              color: getGradeColor(grade),
            }}
          >
            <span className="font-bold">{grade}</span>
            <span>{gradeCounts[grade]}</span>
          </div>
        ))}
      </div>
      <div className="text-sm text-gray-400">
        평균 난이도: <span className="text-white font-bold">{Math.round(avgDifficulty * 100)}%</span>
      </div>
    </div>
  );
}
