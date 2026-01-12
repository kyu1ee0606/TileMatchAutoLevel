import { useState, useEffect } from 'react';
import { uploadLocalToGBoost, uploadThumbnail } from '../../api/gboost';
import { getLocalLevel } from '../../services/localLevelsApi';
import { renderLevelThumbnail } from '../../utils/levelThumbnailRenderer';
import clsx from 'clsx';

interface UploadResult {
  levelId: string;
  targetId: string;
  status: 'pending' | 'uploading' | 'success' | 'failed';
  message: string;
  thumbnailStatus?: 'pending' | 'uploading' | 'success' | 'failed';
}

interface GBoostUploadModalProps {
  isOpen: boolean;
  onClose: () => void;
  levelIds: string[];
  onComplete: (successCount: number, failCount: number) => void;
}

type RenameStrategy = 'keep' | 'sequential' | 'prefix';

export function GBoostUploadModal({
  isOpen,
  onClose,
  levelIds,
  onComplete,
}: GBoostUploadModalProps) {
  const [boardId, setBoardId] = useState('levels');
  const [renameStrategy, setRenameStrategy] = useState<RenameStrategy>('keep');
  const [targetPrefix, setTargetPrefix] = useState('level_');
  const [startIndex, setStartIndex] = useState(1);
  const [overwrite, setOverwrite] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([]);
  const [currentPhase, setCurrentPhase] = useState<'config' | 'uploading' | 'complete'>('config');

  // Reset state when modal opens
  useEffect(() => {
    if (isOpen) {
      setCurrentPhase('config');
      setUploadResults([]);
      setIsUploading(false);
    }
  }, [isOpen]);

  // Generate preview of target IDs
  const getTargetId = (levelId: string, index: number): string => {
    switch (renameStrategy) {
      case 'keep':
        return `level_${levelId}`;
      case 'sequential':
        return `${targetPrefix}${startIndex + index}`;
      case 'prefix':
        return `${targetPrefix}${levelId}`;
      default:
        return `level_${levelId}`;
    }
  };

  const handleUpload = async () => {
    if (levelIds.length === 0) return;

    setIsUploading(true);
    setCurrentPhase('uploading');

    // Initialize results
    const initialResults: UploadResult[] = levelIds.map((levelId, index) => ({
      levelId,
      targetId: getTargetId(levelId, index),
      status: 'pending',
      message: '대기 중...',
      thumbnailStatus: 'pending',
    }));
    setUploadResults(initialResults);

    let successCount = 0;
    let failCount = 0;

    try {
      // Build custom names mapping
      const customNames: Record<string, string> = {};
      levelIds.forEach((levelId, index) => {
        customNames[levelId] = getTargetId(levelId, index);
      });

      // Update all to uploading state
      setUploadResults(prev => prev.map(r => ({ ...r, status: 'uploading', message: '레벨 업로드 중...' })));

      // Upload all levels at once
      const result = await uploadLocalToGBoost({
        board_id: boardId,
        level_ids: levelIds,
        rename_strategy: 'custom',
        custom_names: customNames,
        overwrite,
      });

      // Process results and upload thumbnails
      for (const item of result.results) {
        const resultIndex = levelIds.findIndex(id => customNames[id] === item.target_id);
        if (resultIndex === -1) continue;

        if (item.status === 'success') {
          successCount++;

          // Update level status
          setUploadResults(prev => prev.map((r, i) =>
            i === resultIndex
              ? { ...r, status: 'success', message: '레벨 업로드 완료', thumbnailStatus: 'uploading' }
              : r
          ));

          // Upload thumbnail
          try {
            const levelData = await getLocalLevel(levelIds[resultIndex]);
            if (levelData?.level_data) {
              const base64Data = await renderLevelThumbnail(levelData.level_data, 128);
              if (base64Data) {
                await uploadThumbnail({
                  board_id: boardId,
                  level_id: item.target_id,
                  png_base64: base64Data,
                  size: 128,
                });
                setUploadResults(prev => prev.map((r, i) =>
                  i === resultIndex
                    ? { ...r, thumbnailStatus: 'success', message: '완료 (썸네일 포함)' }
                    : r
                ));
              } else {
                setUploadResults(prev => prev.map((r, i) =>
                  i === resultIndex
                    ? { ...r, thumbnailStatus: 'failed', message: '완료 (썸네일 실패)' }
                    : r
                ));
              }
            }
          } catch (thumbErr) {
            console.warn(`Thumbnail upload failed for ${item.target_id}:`, thumbErr);
            setUploadResults(prev => prev.map((r, i) =>
              i === resultIndex
                ? { ...r, thumbnailStatus: 'failed', message: '완료 (썸네일 실패)' }
                : r
            ));
          }
        } else {
          failCount++;
          setUploadResults(prev => prev.map((r, i) =>
            i === resultIndex
              ? { ...r, status: 'failed', message: item.message || '업로드 실패' }
              : r
          ));
        }
      }
    } catch (err) {
      console.error('GBoost upload error:', err);
      setUploadResults(prev => prev.map(r => ({
        ...r,
        status: r.status === 'pending' || r.status === 'uploading' ? 'failed' : r.status,
        message: r.status === 'pending' || r.status === 'uploading' ? '업로드 오류' : r.message
      })));
      failCount = levelIds.length - successCount;
    }

    setIsUploading(false);
    setCurrentPhase('complete');
    onComplete(successCount, failCount);
  };

  const handleClose = () => {
    if (!isUploading) {
      onClose();
    }
  };

  if (!isOpen) return null;

  const successCount = uploadResults.filter(r => r.status === 'success').length;
  const failCount = uploadResults.filter(r => r.status === 'failed').length;
  const progress = uploadResults.length > 0
    ? Math.round(((successCount + failCount) / uploadResults.length) * 100)
    : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-800 rounded-lg shadow-xl w-full max-w-lg mx-4 max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 border-b border-gray-700 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <span>☁️</span>
            GBoost 업로드
          </h2>
          <button
            onClick={handleClose}
            disabled={isUploading}
            className={clsx(
              'text-gray-400 hover:text-white transition-colors',
              isUploading && 'opacity-50 cursor-not-allowed'
            )}
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto flex-1">
          {currentPhase === 'config' && (
            <div className="space-y-4">
              {/* Level count */}
              <div className="bg-blue-900/30 border border-blue-700 rounded-lg p-3">
                <p className="text-blue-300 text-sm">
                  <span className="font-semibold">{levelIds.length}개</span>의 레벨을 업로드합니다
                </p>
              </div>

              {/* Board ID */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-1">
                  Board ID
                </label>
                <input
                  type="text"
                  value={boardId}
                  onChange={(e) => setBoardId(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                  placeholder="levels"
                />
              </div>

              {/* Rename Strategy */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  이름 변경 전략
                </label>
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="renameStrategy"
                      checked={renameStrategy === 'keep'}
                      onChange={() => setRenameStrategy('keep')}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-300">원본 유지</span>
                    <span className="text-xs text-gray-500">level_[원본ID]</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="renameStrategy"
                      checked={renameStrategy === 'sequential'}
                      onChange={() => setRenameStrategy('sequential')}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-300">순차 번호</span>
                    <span className="text-xs text-gray-500">[접두사]1, 2, 3...</span>
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="renameStrategy"
                      checked={renameStrategy === 'prefix'}
                      onChange={() => setRenameStrategy('prefix')}
                      className="text-blue-500"
                    />
                    <span className="text-sm text-gray-300">접두사 추가</span>
                    <span className="text-xs text-gray-500">[접두사][원본ID]</span>
                  </label>
                </div>
              </div>

              {/* Prefix & Start Index (conditional) */}
              {(renameStrategy === 'sequential' || renameStrategy === 'prefix') && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">
                      접두사
                    </label>
                    <input
                      type="text"
                      value={targetPrefix}
                      onChange={(e) => setTargetPrefix(e.target.value)}
                      className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                      placeholder="level_"
                    />
                  </div>
                  {renameStrategy === 'sequential' && (
                    <div>
                      <label className="block text-sm font-medium text-gray-300 mb-1">
                        시작 번호
                      </label>
                      <input
                        type="number"
                        value={startIndex}
                        onChange={(e) => setStartIndex(Math.max(1, parseInt(e.target.value) || 1))}
                        min={1}
                        className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-lg text-white text-sm focus:outline-none focus:border-blue-500"
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Overwrite option */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={overwrite}
                  onChange={(e) => setOverwrite(e.target.checked)}
                  className="rounded text-blue-500"
                />
                <span className="text-sm text-gray-300">기존 레벨 덮어쓰기</span>
              </label>

              {/* Preview */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  미리보기 (처음 5개)
                </label>
                <div className="bg-gray-900 rounded-lg p-2 max-h-32 overflow-y-auto">
                  {levelIds.slice(0, 5).map((levelId, index) => (
                    <div key={levelId} className="flex items-center gap-2 text-xs py-1">
                      <span className="text-gray-500 truncate flex-1">{levelId}</span>
                      <span className="text-gray-600">→</span>
                      <span className="text-green-400 truncate flex-1">{getTargetId(levelId, index)}</span>
                    </div>
                  ))}
                  {levelIds.length > 5 && (
                    <div className="text-xs text-gray-500 pt-1">
                      ... 외 {levelIds.length - 5}개
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {(currentPhase === 'uploading' || currentPhase === 'complete') && (
            <div className="space-y-4">
              {/* Progress bar */}
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-400">진행률</span>
                  <span className="text-white">{progress}%</span>
                </div>
                <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={clsx(
                      'h-full transition-all duration-300',
                      currentPhase === 'complete' && failCount === 0 ? 'bg-green-500' :
                      currentPhase === 'complete' && failCount > 0 ? 'bg-yellow-500' :
                      'bg-blue-500'
                    )}
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>

              {/* Summary */}
              <div className="flex gap-4 text-sm">
                <div className="flex items-center gap-1">
                  <span className="text-green-400">✓</span>
                  <span className="text-gray-300">{successCount} 성공</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-red-400">✕</span>
                  <span className="text-gray-300">{failCount} 실패</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-gray-500">○</span>
                  <span className="text-gray-300">
                    {uploadResults.filter(r => r.status === 'pending' || r.status === 'uploading').length} 대기
                  </span>
                </div>
              </div>

              {/* Results list */}
              <div className="bg-gray-900 rounded-lg max-h-64 overflow-y-auto">
                {uploadResults.map((result) => (
                  <div
                    key={result.levelId}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-2 text-sm border-b border-gray-800 last:border-0',
                      result.status === 'uploading' && 'bg-blue-900/20'
                    )}
                  >
                    <span className={clsx(
                      'flex-shrink-0',
                      result.status === 'success' && 'text-green-400',
                      result.status === 'failed' && 'text-red-400',
                      result.status === 'uploading' && 'text-blue-400 animate-pulse',
                      result.status === 'pending' && 'text-gray-500'
                    )}>
                      {result.status === 'success' ? '✓' :
                       result.status === 'failed' ? '✕' :
                       result.status === 'uploading' ? '◐' : '○'}
                    </span>
                    <span className="text-gray-400 truncate flex-1 max-w-[120px]">
                      {result.levelId}
                    </span>
                    <span className="text-gray-600">→</span>
                    <span className={clsx(
                      'truncate flex-1 max-w-[120px]',
                      result.status === 'success' ? 'text-green-400' :
                      result.status === 'failed' ? 'text-red-400' :
                      'text-gray-400'
                    )}>
                      {result.targetId}
                    </span>
                    <span className="text-xs text-gray-500 flex-shrink-0">
                      {result.message}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-700 flex justify-end gap-2">
          {currentPhase === 'config' && (
            <>
              <button
                onClick={handleClose}
                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
              >
                취소
              </button>
              <button
                onClick={handleUpload}
                disabled={!boardId || levelIds.length === 0}
                className={clsx(
                  'px-4 py-2 text-sm rounded-lg transition-colors',
                  !boardId || levelIds.length === 0
                    ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
                    : 'bg-blue-600 hover:bg-blue-500 text-white'
                )}
              >
                업로드 시작
              </button>
            </>
          )}
          {currentPhase === 'uploading' && (
            <button
              disabled
              className="px-4 py-2 text-sm bg-gray-600 text-gray-400 rounded-lg cursor-not-allowed"
            >
              업로드 중...
            </button>
          )}
          {currentPhase === 'complete' && (
            <button
              onClick={handleClose}
              className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
            >
              완료
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
