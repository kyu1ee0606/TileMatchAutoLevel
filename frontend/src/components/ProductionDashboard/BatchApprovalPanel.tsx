/**
 * BatchApprovalPanel
 * 스마트 필터링 기반 배치 승인 시스템
 * P0: 시니어 디자이너의 검토 시간 90% 단축
 */

import { useState, useEffect, useMemo } from 'react';
import { Button } from '../ui';
import { CheckCircle, AlertTriangle, XCircle, Filter, Zap } from 'lucide-react';
import { ProductionLevel } from '../../types/production';
import { getProductionLevelsByBatch, approveLevel, rejectLevel } from '../../storage/productionStorage';

interface BatchApprovalCriteria {
  minMatchScore: number;        // 최소 매치 점수 (%)
  autoApproveGrades: string[];  // 자동 승인 등급
  autoRejectGrades: string[];   // 자동 거부 등급
  maxMatchScoreForReject: number; // 이 매치점수 미만은 재생성 대상
}

interface FilteredLevels {
  autoApprove: ProductionLevel[];
  manualReview: ProductionLevel[];
  autoReject: ProductionLevel[];
}

interface BatchApprovalPanelProps {
  batchId: string;
  onComplete: () => void;
  onStatsUpdate: () => void;
}

export function BatchApprovalPanel({ batchId, onComplete, onStatsUpdate }: BatchApprovalPanelProps) {
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [levels, setLevels] = useState<ProductionLevel[]>([]);
  const [processedCount, setProcessedCount] = useState(0);

  // 승인 기준 설정
  const [criteria, setCriteria] = useState<BatchApprovalCriteria>({
    minMatchScore: 80,
    autoApproveGrades: ['S', 'A'],
    autoRejectGrades: ['D'],
    maxMatchScoreForReject: 60,
  });

  // 미승인/미거부 레벨만 로드
  useEffect(() => {
    loadPendingLevels();
  }, [batchId]);

  const loadPendingLevels = async () => {
    setIsLoading(true);
    try {
      const allLevels = await getProductionLevelsByBatch(batchId);
      // 아직 승인/거부되지 않은 레벨만 필터링
      const pending = allLevels.filter(
        l => l.meta.status !== 'approved' &&
             l.meta.status !== 'rejected' &&
             l.meta.status !== 'exported'
      );
      setLevels(pending);
    } catch (err) {
      console.error('Failed to load levels:', err);
    } finally {
      setIsLoading(false);
    }
  };

  // 필터링된 레벨 계산
  const filteredLevels = useMemo<FilteredLevels>(() => {
    const autoApprove: ProductionLevel[] = [];
    const manualReview: ProductionLevel[] = [];
    const autoReject: ProductionLevel[] = [];

    for (const level of levels) {
      const matchScore = level.meta.match_score ?? 0;
      const grade = level.meta.grade;

      // 자동 거부 조건: D등급 AND 매치점수 60% 미만
      if (
        criteria.autoRejectGrades.includes(grade) &&
        matchScore < criteria.maxMatchScoreForReject
      ) {
        autoReject.push(level);
        continue;
      }

      // 자동 승인 조건: S/A등급 AND 매치점수 80% 이상
      if (
        criteria.autoApproveGrades.includes(grade) &&
        matchScore >= criteria.minMatchScore
      ) {
        autoApprove.push(level);
        continue;
      }

      // 나머지는 수동 검토 필요
      manualReview.push(level);
    }

    return { autoApprove, manualReview, autoReject };
  }, [levels, criteria]);

  // 배치 승인 실행
  const handleBatchApprove = async () => {
    if (filteredLevels.autoApprove.length === 0) return;

    setIsProcessing(true);
    setProcessedCount(0);

    try {
      for (const level of filteredLevels.autoApprove) {
        await approveLevel(batchId, level.meta.level_number, '자동승인');
        setProcessedCount(prev => prev + 1);
      }
      await loadPendingLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Batch approval failed:', err);
    } finally {
      setIsProcessing(false);
    }
  };

  // 배치 거부 (재생성 대상 마킹)
  const handleBatchReject = async () => {
    if (filteredLevels.autoReject.length === 0) return;

    setIsProcessing(true);
    setProcessedCount(0);

    try {
      for (const level of filteredLevels.autoReject) {
        await rejectLevel(batchId, level.meta.level_number, '자동거부: 낮은 매치점수');
        setProcessedCount(prev => prev + 1);
      }
      await loadPendingLevels();
      onStatsUpdate();
    } catch (err) {
      console.error('Batch rejection failed:', err);
    } finally {
      setIsProcessing(false);
    }
  };

  // 모든 자동 처리 실행
  const handleProcessAll = async () => {
    setIsProcessing(true);
    setProcessedCount(0);

    try {
      // 자동 승인
      for (const level of filteredLevels.autoApprove) {
        await approveLevel(batchId, level.meta.level_number, '자동승인');
        setProcessedCount(prev => prev + 1);
      }

      // 자동 거부
      for (const level of filteredLevels.autoReject) {
        await rejectLevel(batchId, level.meta.level_number, '자동거부: 낮은 매치점수');
        setProcessedCount(prev => prev + 1);
      }

      await loadPendingLevels();
      onStatsUpdate();

      if (filteredLevels.manualReview.length === 0) {
        onComplete();
      }
    } catch (err) {
      console.error('Batch processing failed:', err);
    } finally {
      setIsProcessing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="p-4 bg-gray-800 rounded-lg">
        <div className="text-center text-gray-400 py-8">레벨 분석 중...</div>
      </div>
    );
  }

  const totalAutoProcess = filteredLevels.autoApprove.length + filteredLevels.autoReject.length;

  return (
    <div className="space-y-4">
      {/* 헤더 */}
      <div className="flex items-center gap-2 text-lg font-bold text-gray-100">
        <Filter className="w-5 h-5 text-indigo-400" />
        스마트 필터링 & 배치 승인
      </div>

      {/* 자동 승인 조건 설정 */}
      <div className="p-4 bg-gray-800/50 rounded-lg space-y-3">
        <div className="text-sm font-medium text-gray-300">자동 승인 조건:</div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={criteria.autoApproveGrades.includes('S')}
            onChange={(e) => {
              setCriteria(prev => ({
                ...prev,
                autoApproveGrades: e.target.checked
                  ? [...prev.autoApproveGrades.filter(g => g !== 'S'), 'S']
                  : prev.autoApproveGrades.filter(g => g !== 'S')
              }));
            }}
            className="w-4 h-4 text-green-500 rounded"
          />
          <span className="text-sm text-gray-300">S등급</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={criteria.autoApproveGrades.includes('A')}
            onChange={(e) => {
              setCriteria(prev => ({
                ...prev,
                autoApproveGrades: e.target.checked
                  ? [...prev.autoApproveGrades.filter(g => g !== 'A'), 'A']
                  : prev.autoApproveGrades.filter(g => g !== 'A')
              }));
            }}
            className="w-4 h-4 text-green-500 rounded"
          />
          <span className="text-sm text-gray-300">A등급</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={criteria.autoApproveGrades.includes('B')}
            onChange={(e) => {
              setCriteria(prev => ({
                ...prev,
                autoApproveGrades: e.target.checked
                  ? [...prev.autoApproveGrades.filter(g => g !== 'B'), 'B']
                  : prev.autoApproveGrades.filter(g => g !== 'B')
              }));
            }}
            className="w-4 h-4 text-green-500 rounded"
          />
          <span className="text-sm text-gray-300">B등급 (수동 검토 권장)</span>
        </label>

        <div className="flex items-center gap-2 mt-2">
          <span className="text-sm text-gray-400">매치점수</span>
          <input
            type="number"
            value={criteria.minMatchScore}
            onChange={(e) => setCriteria(prev => ({ ...prev, minMatchScore: parseInt(e.target.value) || 0 }))}
            className="w-16 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            min={0}
            max={100}
          />
          <span className="text-sm text-gray-400">% 이상</span>
        </div>
      </div>

      {/* 자동 처리 조건 */}
      <div className="p-4 bg-gray-800/50 rounded-lg space-y-3">
        <div className="text-sm font-medium text-gray-300">자동 거부/재생성 조건:</div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={criteria.autoRejectGrades.includes('D')}
            onChange={(e) => {
              setCriteria(prev => ({
                ...prev,
                autoRejectGrades: e.target.checked
                  ? [...prev.autoRejectGrades.filter(g => g !== 'D'), 'D']
                  : prev.autoRejectGrades.filter(g => g !== 'D')
              }));
            }}
            className="w-4 h-4 text-red-500 rounded"
          />
          <span className="text-sm text-gray-300">D등급 재생성 대상 표시</span>
        </label>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={criteria.autoRejectGrades.includes('C')}
            onChange={(e) => {
              setCriteria(prev => ({
                ...prev,
                autoRejectGrades: e.target.checked
                  ? [...prev.autoRejectGrades.filter(g => g !== 'C'), 'C']
                  : prev.autoRejectGrades.filter(g => g !== 'C')
              }));
            }}
            className="w-4 h-4 text-red-500 rounded"
          />
          <span className="text-sm text-gray-300">C등급 재생성 대상 표시</span>
        </label>

        <div className="flex items-center gap-2 mt-2">
          <span className="text-sm text-gray-400">매치점수</span>
          <input
            type="number"
            value={criteria.maxMatchScoreForReject}
            onChange={(e) => setCriteria(prev => ({ ...prev, maxMatchScoreForReject: parseInt(e.target.value) || 0 }))}
            className="w-16 px-2 py-1 bg-gray-700 border border-gray-600 rounded text-sm text-white"
            min={0}
            max={100}
          />
          <span className="text-sm text-gray-400">% 미만 재생성</span>
        </div>
      </div>

      {/* 필터 결과 요약 */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-2">
        <div className="text-sm font-medium text-gray-300 mb-3">필터 결과:</div>

        <div className="flex items-center gap-2 text-sm">
          <CheckCircle className="w-4 h-4 text-green-400" />
          <span className="text-gray-300">자동 승인 가능:</span>
          <span className="text-green-400 font-bold">{filteredLevels.autoApprove.length}개</span>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <AlertTriangle className="w-4 h-4 text-yellow-400" />
          <span className="text-gray-300">수동 검토 필요:</span>
          <span className="text-yellow-400 font-bold">{filteredLevels.manualReview.length}개</span>
        </div>

        <div className="flex items-center gap-2 text-sm">
          <XCircle className="w-4 h-4 text-red-400" />
          <span className="text-gray-300">재생성 대상:</span>
          <span className="text-red-400 font-bold">{filteredLevels.autoReject.length}개</span>
        </div>

        {isProcessing && (
          <div className="mt-3 p-2 bg-indigo-900/30 rounded">
            <div className="flex items-center gap-2 text-sm text-indigo-300">
              <div className="w-4 h-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
              처리 중... {processedCount}/{totalAutoProcess}
            </div>
            <div className="mt-2 h-1.5 bg-gray-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-500 transition-all"
                style={{ width: `${(processedCount / totalAutoProcess) * 100}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* 액션 버튼 */}
      <div className="flex gap-2">
        <Button
          onClick={handleProcessAll}
          disabled={isProcessing || totalAutoProcess === 0}
          className="flex-1"
        >
          <Zap className="w-4 h-4 mr-2" />
          전체 자동 처리 ({totalAutoProcess}개)
        </Button>

        <Button
          variant="secondary"
          onClick={handleBatchApprove}
          disabled={isProcessing || filteredLevels.autoApprove.length === 0}
        >
          승인만 ({filteredLevels.autoApprove.length})
        </Button>

        <Button
          variant="danger"
          onClick={handleBatchReject}
          disabled={isProcessing || filteredLevels.autoReject.length === 0}
        >
          거부만 ({filteredLevels.autoReject.length})
        </Button>
      </div>

      {/* 안내 메시지 */}
      {filteredLevels.manualReview.length > 0 && !isProcessing && (
        <div className="p-3 bg-yellow-900/20 border border-yellow-700/30 rounded-lg">
          <div className="flex items-start gap-2">
            <AlertTriangle className="w-4 h-4 text-yellow-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-yellow-200">
              <strong>{filteredLevels.manualReview.length}개</strong> 레벨은 수동 검토가 필요합니다.
              <br />
              <span className="text-yellow-400/70">
                (B/C등급 또는 매치점수 경계값 레벨)
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
