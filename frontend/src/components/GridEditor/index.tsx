import { TileGrid } from './TileGrid';
import { LayerSelector } from './LayerSelector';
import { ToolPalette } from './ToolPalette';
import { Minimap } from './Minimap';
import { useLevelStore } from '../../stores/levelStore';
import { useUIStore } from '../../stores/uiStore';
import { Button, Tooltip } from '../ui';
import { Eye, EyeOff, FileJson, RotateCcw, ZoomIn, Grid3X3, Map } from 'lucide-react';
import clsx from 'clsx';

interface GridEditorProps {
  className?: string;
}

export function GridEditor({ className }: GridEditorProps) {
  const { resetLevel } = useLevelStore();
  const {
    setJsonModalOpen,
    addNotification,
    showOtherLayers,
    setShowOtherLayers,
    gridZoom,
    setGridZoom,
    showGridCoordinates,
    setShowGridCoordinates,
    showMinimap,
    setShowMinimap,
  } = useUIStore();

  const handleReset = () => {
    if (confirm('레벨을 초기화하시겠습니까?')) {
      resetLevel();
      addNotification('info', '레벨을 초기화했습니다');
    }
  };

  const handleViewJson = () => {
    setJsonModalOpen(true);
  };

  return (
    <div className={clsx('flex flex-col gap-4 p-4 bg-gray-800 rounded-xl shadow-lg border border-gray-700', className)}>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold text-gray-100">그리드 에디터</h2>
        <div className="flex gap-2">
          {/* Layer transparency toggle */}
          <Tooltip content={showOtherLayers ? '다른 레이어 숨기기' : '다른 레이어 표시'}>
            <Button
              onClick={() => setShowOtherLayers(!showOtherLayers)}
              variant={showOtherLayers ? 'primary' : 'secondary'}
              size="sm"
              icon={showOtherLayers ? <Eye className="w-full h-full" /> : <EyeOff className="w-full h-full" />}
            >
              {showOtherLayers ? '다른층 표시' : '다른층 숨김'}
            </Button>
          </Tooltip>
          <Tooltip content="JSON 데이터 보기">
            <Button
              onClick={handleViewJson}
              variant="secondary"
              size="sm"
              icon={<FileJson className="w-full h-full" />}
            >
              JSON
            </Button>
          </Tooltip>
          <Tooltip content="레벨 초기화">
            <Button
              onClick={handleReset}
              variant="danger"
              size="sm"
              icon={<RotateCcw className="w-full h-full" />}
            >
              초기화
            </Button>
          </Tooltip>
        </div>
      </div>

      {/* View controls: zoom, coordinates, minimap */}
      <div className="flex items-center gap-4 px-2 py-2 bg-gray-750 rounded-lg">
        {/* Zoom slider */}
        <Tooltip content="그리드 확대/축소 (Ctrl+휠)">
          <div className="flex items-center gap-2">
            <ZoomIn className="w-4 h-4 text-gray-400" />
            <input
              type="range"
              min="0.5"
              max="2"
              step="0.1"
              value={gridZoom}
              onChange={(e) => setGridZoom(parseFloat(e.target.value))}
              className="w-24 h-1.5 bg-gray-600 rounded-lg appearance-none cursor-pointer accent-primary-500"
            />
            <span className="text-xs text-gray-400 w-10">{Math.round(gridZoom * 100)}%</span>
          </div>
        </Tooltip>

        <div className="w-px h-4 bg-gray-600" />

        {/* Coordinates toggle */}
        <Tooltip content="좌표 표시 토글">
          <button
            onClick={() => setShowGridCoordinates(!showGridCoordinates)}
            className={clsx(
              'px-2 py-1 text-xs rounded transition-colors flex items-center gap-1',
              showGridCoordinates
                ? 'bg-primary-700 text-primary-100'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            )}
          >
            <Grid3X3 className="w-3.5 h-3.5" />
            좌표
          </button>
        </Tooltip>

        {/* Minimap toggle */}
        <Tooltip content="미니맵 표시 토글">
          <button
            onClick={() => setShowMinimap(!showMinimap)}
            className={clsx(
              'px-2 py-1 text-xs rounded transition-colors flex items-center gap-1',
              showMinimap
                ? 'bg-primary-700 text-primary-100'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            )}
          >
            <Map className="w-3.5 h-3.5" />
            미니맵
          </button>
        </Tooltip>
      </div>

      <LayerSelector />

      <div className="flex gap-4">
        <div className="flex-1 overflow-auto relative">
          <TileGrid />
          {/* Minimap overlay */}
          {showMinimap && (
            <div className="absolute bottom-2 right-2 z-20">
              <Minimap />
            </div>
          )}
        </div>
        <div className="w-56 flex-shrink-0">
          <ToolPalette />
        </div>
      </div>
    </div>
  );
}

export { TileGrid } from './TileGrid';
export { LayerSelector } from './LayerSelector';
export { ToolPalette } from './ToolPalette';
export { Minimap } from './Minimap';
