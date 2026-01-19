/**
 * Production Export Component
 * 프로덕션 레벨 내보내기
 */

import { useState } from 'react';
import { ProductionStats, ProductionExportConfig } from '../../types/production';
import { Button } from '../ui';
import { useUIStore } from '../../stores/uiStore';
import { exportProductionLevels } from '../../storage/productionStorage';

interface ProductionExportProps {
  batchId: string;
  stats: ProductionStats;
  onExportComplete?: (count: number) => void;
}

export function ProductionExport({
  batchId,
  stats,
  onExportComplete,
}: ProductionExportProps) {
  const { addNotification } = useUIStore();
  const [format, setFormat] = useState<'json' | 'json_minified' | 'json_split'>('json');
  const [includeMeta, setIncludeMeta] = useState(false);
  const [filenamePattern, setFilenamePattern] = useState('level_{number:04d}.json');
  const [isExporting, setIsExporting] = useState(false);

  const readyCount = stats.by_status.approved;
  const exportedCount = stats.by_status.exported;
  const totalReady = readyCount + exportedCount;

  const handleExport = async () => {
    if (readyCount === 0) {
      addNotification('warning', '내보낼 승인된 레벨이 없습니다');
      return;
    }

    setIsExporting(true);

    try {
      const config: ProductionExportConfig = {
        format,
        include_meta: includeMeta,
        filename_pattern: filenamePattern,
        output_dir: '',
      };

      const result = await exportProductionLevels(batchId, config);

      if ('files' in result) {
        // Multiple files - create and download zip
        // For now, just show info
        addNotification('success', `${result.files.length}개 파일 생성됨`);

        // Download first 10 files as individual downloads (demo)
        if (result.files.length <= 10) {
          for (const file of result.files) {
            const url = URL.createObjectURL(file.data);
            const a = document.createElement('a');
            a.href = url;
            a.download = file.name;
            a.click();
            URL.revokeObjectURL(url);
          }
        } else {
          addNotification('info', 'ZIP 다운로드는 추후 지원 예정입니다. JSON 포맷을 권장합니다.');
        }
      } else {
        // Single file
        const url = URL.createObjectURL(result);
        const a = document.createElement('a');
        a.href = url;
        a.download = `production_levels_${batchId}.json`;
        a.click();
        URL.revokeObjectURL(url);

        addNotification('success', `${totalReady}개 레벨 내보내기 완료`);
      }

      onExportComplete?.(totalReady);
    } catch (err) {
      addNotification('error', `내보내기 실패: ${(err as Error).message}`);
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Export Summary */}
      <div className="p-4 bg-gray-800 rounded-lg">
        <h3 className="text-sm font-medium text-white mb-3">내보내기 요약</h3>
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-green-400">{readyCount}</div>
            <div className="text-xs text-gray-400">승인됨 (대기)</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-indigo-400">{exportedCount}</div>
            <div className="text-xs text-gray-400">내보내기 완료</div>
          </div>
          <div className="text-center p-3 bg-gray-700 rounded">
            <div className="text-2xl font-bold text-white">{totalReady}</div>
            <div className="text-xs text-gray-400">총 출시 가능</div>
          </div>
        </div>
      </div>

      {/* Export Settings */}
      <div className="p-4 bg-gray-800 rounded-lg space-y-4">
        <h3 className="text-sm font-medium text-white">내보내기 설정</h3>

        {/* Format */}
        <div>
          <label className="block text-xs text-gray-400 mb-1">파일 포맷</label>
          <select
            value={format}
            onChange={(e) => setFormat(e.target.value as typeof format)}
            className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
          >
            <option value="json">JSON (단일 파일, 포맷팅)</option>
            <option value="json_minified">JSON (단일 파일, 압축)</option>
            <option value="json_split">JSON (개별 파일)</option>
          </select>
        </div>

        {/* Filename Pattern (for split mode) */}
        {format === 'json_split' && (
          <div>
            <label className="block text-xs text-gray-400 mb-1">파일명 패턴</label>
            <input
              type="text"
              value={filenamePattern}
              onChange={(e) => setFilenamePattern(e.target.value)}
              placeholder="level_{number:04d}.json"
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-sm"
            />
            <p className="text-xs text-gray-500 mt-1">
              {'{number}'} = 레벨 번호, {'{number:04d}'} = 4자리 패딩, {'{grade}'} = 등급
            </p>
          </div>
        )}

        {/* Include Meta */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={includeMeta}
            onChange={(e) => setIncludeMeta(e.target.checked)}
            className="rounded border-gray-600"
          />
          <span className="text-sm text-gray-300">메타데이터 포함</span>
          <span className="text-xs text-gray-500">(난이도, 등급, 플레이테스트 결과 등)</span>
        </label>

        {/* File Size Estimate */}
        <div className="text-xs text-gray-500">
          예상 파일 크기: ~{(totalReady * 2).toFixed(0)}KB
          {format === 'json_minified' && ' (압축시 ~50%)'}
        </div>
      </div>

      {/* Export Button */}
      <div className="flex gap-2">
        <Button
          onClick={handleExport}
          disabled={isExporting || readyCount === 0}
          className="flex-1"
        >
          {isExporting ? (
            <>내보내는 중...</>
          ) : (
            <>내보내기 ({totalReady}개)</>
          )}
        </Button>
      </div>

      {/* Export History */}
      {exportedCount > 0 && (
        <div className="p-3 bg-gray-800 rounded-lg">
          <div className="text-xs text-gray-400">
            이미 {exportedCount}개 레벨이 내보내기 되었습니다.
          </div>
        </div>
      )}
    </div>
  );
}
