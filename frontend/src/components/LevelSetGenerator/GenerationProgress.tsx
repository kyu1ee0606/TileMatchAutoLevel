import { useState, useEffect } from 'react';
import type { GenerationProgressState, GenerationResultItem } from '../../types/levelSet';
import { getGradeColor } from '../../utils/helpers';
import { Button } from '../ui';

interface GenerationProgressProps {
  state: GenerationProgressState;
  onCancel: () => void;
}

// Format milliseconds to human readable time
function formatTime(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}초`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}분 ${remainingSeconds}초`;
}

export function GenerationProgress({ state, onCancel }: GenerationProgressProps) {
  const { status, current, total, results, error, currentLevelStartTime, totalStartTime, averageTimePerLevel, completedTimes } = state;
  const progress = total > 0 ? (current / total) * 100 : 0;

  // Real-time elapsed time tracking
  const [currentElapsed, setCurrentElapsed] = useState(0);
  const [totalElapsed, setTotalElapsed] = useState(0);

  useEffect(() => {
    if (status !== 'generating') {
      setCurrentElapsed(0);
      return;
    }

    const interval = setInterval(() => {
      const now = Date.now();
      if (currentLevelStartTime) {
        setCurrentElapsed(now - currentLevelStartTime);
      }
      if (totalStartTime) {
        setTotalElapsed(now - totalStartTime);
      }
    }, 100); // Update every 100ms for smooth display

    return () => clearInterval(interval);
  }, [status, currentLevelStartTime, totalStartTime]);

  const successCount = results.filter((r) => r.status === 'success').length;
  const failedCount = results.filter((r) => r.status === 'failed').length;

  // Calculate estimated remaining time
  const getEstimatedRemaining = () => {
    if (!averageTimePerLevel || current >= total) return null;
    const remaining = total - current;
    return remaining * averageTimePerLevel;
  };

  const estimatedRemaining = getEstimatedRemaining();

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
          <div className="space-y-2">
            <p className="text-blue-400 font-medium">
              레벨 {current}/{total} 생성 중...
            </p>
            {/* Detailed timing info */}
            <div className="bg-gray-900/50 rounded-lg p-3 space-y-1.5">
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">현재 레벨 경과:</span>
                <span className="text-yellow-400 font-mono">
                  {formatTime(currentElapsed)}
                  {currentElapsed > 30000 && ' ⏳'}
                </span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-gray-400">총 경과 시간:</span>
                <span className="text-white font-mono">{formatTime(totalElapsed)}</span>
              </div>
              {averageTimePerLevel && averageTimePerLevel > 0 && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-gray-400">레벨당 평균:</span>
                  <span className="text-gray-300 font-mono">{formatTime(averageTimePerLevel)}</span>
                </div>
              )}
              {estimatedRemaining && estimatedRemaining > 0 && (
                <div className="flex items-center justify-between text-sm border-t border-gray-700 pt-1.5 mt-1.5">
                  <span className="text-gray-400">예상 남은 시간:</span>
                  <span className="text-green-400 font-mono">~{formatTime(estimatedRemaining)}</span>
                </div>
              )}
            </div>
            {/* Long generation warning */}
            {currentElapsed > 30000 && (
              <div className="flex items-center gap-2 text-xs text-yellow-500 bg-yellow-900/20 rounded px-2 py-1">
                <span>⚠️</span>
                <span>높은 난이도 레벨은 최적 결과를 찾기 위해 시간이 더 걸릴 수 있습니다</span>
              </div>
            )}
          </div>
        )}
        {status === 'completed' && (
          <div className="space-y-2">
            <p className="text-green-400">
              ✅ 생성 완료! {successCount}개 성공, {failedCount}개 실패
            </p>
            {completedTimes && completedTimes.length > 0 && (
              <p className="text-xs text-gray-400">
                총 소요 시간: {formatTime(completedTimes.reduce((a, b) => a + b, 0))}
              </p>
            )}
          </div>
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
  const { levelIndex, status, grade, actualDifficulty, targetDifficulty, matchScore, validationPassed, retryCount, targetGrade } = result;

  let bgColor = 'bg-gray-700';

  if (status === 'success') {
    bgColor = 'bg-opacity-50';
  } else if (status === 'failed') {
    bgColor = 'bg-red-900/50';
  } else if (status === 'generating') {
    bgColor = 'bg-blue-900/50';
  }

  // Determine validation indicator (grade match status)
  const getValidationIndicator = () => {
    if (status !== 'success') return null;
    if (targetGrade !== undefined) {
      // Check if achieved grade matches target grade
      if (grade === targetGrade) return { icon: '✓', color: 'text-green-400' };
      return { icon: '!', color: 'text-yellow-400' };
    }
    if (matchScore === undefined) return null;
    if (validationPassed) return { icon: '✓', color: 'text-green-400' };
    if (matchScore >= 70) return { icon: '~', color: 'text-yellow-400' };
    return { icon: '!', color: 'text-red-400' };
  };
  const validation = getValidationIndicator();

  const tooltipParts = [];
  if (status === 'success') {
    tooltipParts.push(`목표: ${Math.round(targetDifficulty * 100)}% → 실제: ${Math.round(actualDifficulty * 100)}%`);
    if (targetGrade !== undefined) {
      tooltipParts.push(`목표 등급: ${targetGrade} → 실제: ${grade}`);
      if (retryCount && retryCount > 0) {
        tooltipParts.push(`재시도: ${retryCount}회`);
      }
      tooltipParts.push(grade === targetGrade ? '등급 일치 ✓' : '등급 불일치');
    } else if (matchScore !== undefined) {
      tooltipParts.push(`매치 점수: ${Math.round(matchScore)}%`);
      tooltipParts.push(validationPassed ? '검증 통과' : '검증 미통과');
    }
  } else if (status === 'generating' && retryCount !== undefined && retryCount > 0) {
    tooltipParts.push(`재시도 중: ${retryCount}회 (목표: ${targetGrade})`);
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
          {retryCount !== undefined && retryCount > 0 && (
            <span className="absolute -bottom-0.5 -right-0.5 text-[8px] text-gray-400">
              ×{retryCount}
            </span>
          )}
        </div>
      ) : status === 'generating' ? (
        <div className="relative">
          <div className="text-lg text-blue-400 animate-spin">⟳</div>
          {retryCount !== undefined && retryCount > 0 && (
            <span className="absolute -bottom-0.5 left-1/2 -translate-x-1/2 text-[9px] text-yellow-400 whitespace-nowrap">
              {retryCount}회
            </span>
          )}
        </div>
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

  // Calculate grade match statistics
  const successResults = results.filter((r) => r.status === 'success' && r.targetGrade !== undefined);
  const matchedCount = successResults.filter((r) => r.grade === r.targetGrade).length;
  const totalWithTarget = successResults.length;
  const matchRate = totalWithTarget > 0 ? Math.round((matchedCount / totalWithTarget) * 100) : null;

  // Calculate total retry count
  const totalRetries = results
    .filter((r) => r.status === 'success')
    .reduce((sum, r) => sum + (r.retryCount || 0), 0);

  return (
    <div className="space-y-2">
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
      {matchRate !== null && (
        <div className="flex justify-between items-center text-xs">
          <span className={`${matchRate >= 80 ? 'text-green-400' : matchRate >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>
            등급 일치율: {matchedCount}/{totalWithTarget} ({matchRate}%)
          </span>
          {totalRetries > 0 && (
            <span className="text-gray-500">
              총 재시도: {totalRetries}회
            </span>
          )}
        </div>
      )}
    </div>
  );
}
