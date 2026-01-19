/**
 * Level Review Panel Component
 * 레벨 검토 및 승인/거부 패널
 */

import { ProductionLevel } from '../../types/production';
import { Button } from '../ui';

interface LevelReviewPanelProps {
  level: ProductionLevel;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onNeedsRework: (reason: string) => void;
}

export function LevelReviewPanel({
  level,
  onApprove,
  onReject,
  onNeedsRework,
}: LevelReviewPanelProps) {
  const { meta } = level;

  const handleReject = () => {
    const reason = prompt('거부 사유를 입력하세요:');
    if (reason) {
      onReject(reason);
    }
  };

  const handleNeedsRework = () => {
    const reason = prompt('수정이 필요한 이유를 입력하세요:');
    if (reason) {
      onNeedsRework(reason);
    }
  };

  const gradeColors = {
    S: 'text-green-400',
    A: 'text-blue-400',
    B: 'text-yellow-400',
    C: 'text-orange-400',
    D: 'text-red-400',
  };

  return (
    <div className="p-4 bg-gray-800 rounded-lg space-y-4">
      {/* Header */}
      <div className="flex justify-between items-center">
        <h3 className="text-sm font-medium text-white">
          레벨 {meta.level_number} 검토
        </h3>
        <span className={`text-lg font-bold ${gradeColors[meta.grade]}`}>
          {meta.grade}
        </span>
      </div>

      {/* Level Info */}
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-gray-400">목표 난이도:</span>
          <span className="text-white ml-2">{(meta.target_difficulty * 100).toFixed(0)}%</span>
        </div>
        <div>
          <span className="text-gray-400">실제 난이도:</span>
          <span className="text-white ml-2">{(meta.actual_difficulty * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Bot Clear Rates */}
      {meta.bot_clear_rates && (
        <div>
          <div className="text-xs text-gray-400 mb-2">봇 클리어율</div>
          <div className="grid grid-cols-5 gap-1 text-xs">
            {Object.entries(meta.bot_clear_rates).map(([bot, rate]) => (
              <div key={bot} className="text-center p-1 bg-gray-700 rounded">
                <div className="text-gray-400 capitalize">{bot}</div>
                <div className="text-white">{(rate * 100).toFixed(0)}%</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Match Score */}
      {meta.match_score !== undefined && (
        <div className="flex items-center justify-between p-2 bg-gray-700 rounded">
          <span className="text-xs text-gray-400">매치 점수</span>
          <span className={`font-medium ${
            meta.match_score >= 80 ? 'text-green-400' :
            meta.match_score >= 60 ? 'text-yellow-400' :
            'text-red-400'
          }`}>
            {meta.match_score.toFixed(1)}%
          </span>
        </div>
      )}

      {/* Playtest Results Summary */}
      {meta.playtest_results && meta.playtest_results.length > 0 && (
        <div className="p-2 bg-gray-700 rounded">
          <div className="text-xs text-gray-400 mb-2">플레이테스트 결과 ({meta.playtest_results.length}회)</div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <span className="text-gray-400">클리어율:</span>
              <span className="text-white ml-1">
                {((meta.playtest_results.filter(r => r.cleared).length / meta.playtest_results.length) * 100).toFixed(0)}%
              </span>
            </div>
            <div>
              <span className="text-gray-400">평균 재미:</span>
              <span className="text-white ml-1">
                {(meta.playtest_results.reduce((sum, r) => sum + r.fun_rating, 0) / meta.playtest_results.length).toFixed(1)}
              </span>
            </div>
            <div>
              <span className="text-gray-400">평균 난이도:</span>
              <span className="text-white ml-1">
                {(meta.playtest_results.reduce((sum, r) => sum + r.perceived_difficulty, 0) / meta.playtest_results.length).toFixed(1)}
              </span>
            </div>
          </div>

          {/* Issues from playtests */}
          {meta.playtest_results.some(r => r.issues.length > 0) && (
            <div className="mt-2 text-xs">
              <span className="text-red-400">발견된 문제: </span>
              <span className="text-gray-300">
                {[...new Set(meta.playtest_results.flatMap(r => r.issues))].join(', ')}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Current Status */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-gray-400">현재 상태:</span>
        <span className={`text-xs px-2 py-0.5 rounded ${
          meta.status === 'approved' ? 'bg-green-900 text-green-300' :
          meta.status === 'rejected' ? 'bg-red-900 text-red-300' :
          meta.status === 'needs_rework' ? 'bg-purple-900 text-purple-300' :
          meta.status === 'playtest_queue' ? 'bg-yellow-900 text-yellow-300' :
          'bg-gray-700 text-gray-300'
        }`}>
          {meta.status === 'approved' ? '승인됨' :
           meta.status === 'rejected' ? '거부됨' :
           meta.status === 'needs_rework' ? '수정필요' :
           meta.status === 'playtest_queue' ? '테스트 대기' :
           meta.status === 'generated' ? '생성됨' :
           meta.status}
        </span>
      </div>

      {/* Rejection Reason */}
      {meta.rejection_reason && (
        <div className="p-2 bg-red-900/30 rounded text-xs text-red-300">
          거부 사유: {meta.rejection_reason}
        </div>
      )}

      {/* Actions */}
      {meta.status !== 'approved' && meta.status !== 'exported' && (
        <div className="flex gap-2">
          <Button onClick={onApprove} className="flex-1">
            승인
          </Button>
          <Button onClick={handleNeedsRework} variant="secondary" className="flex-1">
            수정필요
          </Button>
          <Button onClick={handleReject} variant="danger">
            거부
          </Button>
        </div>
      )}

      {meta.status === 'approved' && (
        <div className="text-center text-sm text-green-400">
          {meta.approved_by && `${meta.approved_by}님이 `}
          {meta.approved_at && `${new Date(meta.approved_at).toLocaleDateString()}에 `}
          승인함
        </div>
      )}
    </div>
  );
}
